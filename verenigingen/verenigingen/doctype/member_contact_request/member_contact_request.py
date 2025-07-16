import frappe
from frappe import _
from frappe.model.document import Document


class MemberContactRequest(Document):
    def validate(self):
        """Validate member contact request data"""
        self.validate_member_exists()
        self.set_member_details()
        self.validate_contact_preferences()

    def validate_member_exists(self):
        """Ensure the member exists and is active"""
        if not self.member:
            frappe.throw(_("Member is required"))

        member_doc = frappe.get_doc("Member", self.member)
        if member_doc.membership_status != "Active":
            frappe.throw(_("Contact requests can only be created for active members"))

    def set_member_details(self):
        """Auto-populate member details from linked member record"""
        if self.member and not self.member_name:
            member_doc = frappe.get_doc("Member", self.member)
            self.member_name = member_doc.member_name
            self.email = member_doc.email_address
            self.phone = member_doc.phone_number
            self.organization = member_doc.organization

    def validate_contact_preferences(self):
        """Validate contact method preferences"""
        if self.preferred_contact_method == "Phone" and not self.phone:
            frappe.throw(_("Phone number is required when phone is the preferred contact method"))

        if self.preferred_contact_method == "Email" and not self.email:
            frappe.throw(_("Email address is required when email is the preferred contact method"))

    def on_insert(self):
        """Handle post-creation tasks"""
        self.create_crm_lead()
        self.notify_staff()

    def create_crm_lead(self):
        """Create a corresponding CRM Lead for this contact request"""
        try:
            # Check if CRM module is available
            if not frappe.db.exists("DocType", "Lead"):
                frappe.log_error("CRM Lead doctype not available", "Member Contact Request")
                return

            # Create CRM Lead
            lead_data = {
                "doctype": "Lead",
                "lead_name": self.member_name,
                "email_id": self.email,
                "phone": self.phone,
                "source": self.lead_source or "Member Portal",
                "status": "Open",
                "title": f"Member Contact Request: {self.subject}",
                "notes": f"Contact Request: {self.message}\n\nRequest Type: {self.request_type}\nUrgency: {self.urgency}\nPreferred Contact: {self.preferred_contact_method}",
                "company": frappe.defaults.get_defaults().get("company"),
                "custom_member_contact_request": self.name,
                "custom_member_id": self.member,
            }

            # Add preferred contact time if specified
            if self.preferred_time:
                lead_data["notes"] += f"\nPreferred Contact Time: {self.preferred_time}"

            lead_doc = frappe.get_doc(lead_data)
            lead_doc.insert(ignore_permissions=True)

            # Link back to the contact request
            self.db_set("crm_lead", lead_doc.name, update_modified=False)

            frappe.logger().info(f"Created CRM Lead {lead_doc.name} for Member Contact Request {self.name}")

        except Exception as e:
            frappe.log_error(
                f"Failed to create CRM Lead for Member Contact Request {self.name}: {str(e)}",
                "CRM Integration Error",
            )

    def notify_staff(self):
        """Send notification to staff about new contact request"""
        try:
            # Determine who to notify based on request type and urgency
            recipients = self.get_notification_recipients()

            if not recipients:
                return

            # Prepare notification
            subject = f"New Member Contact Request: {self.subject}"

            # Create message content
            message = f"""
            <h3>New Member Contact Request</h3>
            <p><strong>Member:</strong> {self.member_name} ({self.member})</p>
            <p><strong>Request Type:</strong> {self.request_type}</p>
            <p><strong>Urgency:</strong> {self.urgency}</p>
            <p><strong>Subject:</strong> {self.subject}</p>
            <p><strong>Message:</strong></p>
            <div style="background: #f8f9fa; padding: 10px; border-left: 3px solid #007bff;">
                {self.message}
            </div>
            <p><strong>Preferred Contact Method:</strong> {self.preferred_contact_method}</p>
            """

            if self.preferred_time:
                message += f"<p><strong>Preferred Time:</strong> {self.preferred_time}</p>"

            if self.email:
                message += f"<p><strong>Email:</strong> {self.email}</p>"

            if self.phone:
                message += f"<p><strong>Phone:</strong> {self.phone}</p>"

            message += f"""
            <p><strong>CRM Lead:</strong> {self.crm_lead or 'Not created'}</p>
            <hr>
            <p><a href="/app/member-contact-request/{self.name}">View Contact Request</a></p>
            """

            # Send notification
            frappe.sendmail(
                recipients=recipients,
                subject=subject,
                message=message,
                reference_doctype=self.doctype,
                reference_name=self.name,
            )

        except Exception as e:
            frappe.log_error(
                f"Failed to send notification for Member Contact Request {self.name}: {str(e)}",
                "Notification Error",
            )

    def get_notification_recipients(self):
        """Determine who should be notified based on request type and urgency"""
        recipients = []

        # Get users with Verenigingen Administrator role
        managers = frappe.get_all(
            "Has Role",
            filters={"role": "Verenigingen Administrator", "parenttype": "User"},
            fields=["parent"],
        )
        recipients.extend([m.parent for m in managers])

        # For urgent requests, also notify System Managers
        if self.urgency == "Urgent":
            system_managers = frappe.get_all(
                "Has Role", filters={"role": "System Manager", "parenttype": "User"}, fields=["parent"]
            )
            recipients.extend([sm.parent for sm in system_managers])

        # Remove duplicates and filter out disabled users
        recipients = list(set(recipients))
        active_recipients = []

        for recipient in recipients:
            user = frappe.get_doc("User", recipient)
            if user.enabled and user.email:
                active_recipients.append(user.email)

        return active_recipients

    def on_update(self):
        """Handle status changes and updates"""
        if self.has_value_changed("status"):
            self.handle_status_change()

        if self.has_value_changed("assigned_to"):
            self.handle_assignment_change()

    def handle_status_change(self):
        """Handle status changes"""
        if self.status == "In Progress" and not self.response_date:
            self.response_date = frappe.utils.today()

        if self.status in ["Resolved", "Closed"] and not self.closed_date:
            self.closed_date = frappe.utils.today()

        # Update CRM Lead status if linked
        if self.crm_lead:
            try:
                lead_doc = frappe.get_doc("Lead", self.crm_lead)
                if self.status == "Resolved":
                    lead_doc.status = "Converted"
                elif self.status == "Closed":
                    lead_doc.status = "Do Not Contact"
                else:
                    lead_doc.status = "Open"

                lead_doc.save(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Failed to update CRM Lead status: {str(e)}", "CRM Integration Error")

    def handle_assignment_change(self):
        """Handle assignment changes"""
        if self.assigned_to:
            # Set follow-up date if not already set
            if not self.follow_up_date:
                self.follow_up_date = frappe.utils.add_days(frappe.utils.today(), 2)

            # Notify assigned user
            try:
                assigned_user = frappe.get_doc("User", self.assigned_to)
                if assigned_user.enabled and assigned_user.email:
                    subject = f"Member Contact Request Assigned: {self.subject}"
                    message = f"""
                    <h3>Contact Request Assigned to You</h3>
                    <p>You have been assigned a member contact request.</p>
                    <p><strong>Member:</strong> {self.member_name}</p>
                    <p><strong>Subject:</strong> {self.subject}</p>
                    <p><strong>Urgency:</strong> {self.urgency}</p>
                    <p><strong>Follow Up Date:</strong> {self.follow_up_date}</p>
                    <p><a href="/app/member-contact-request/{self.name}">View Contact Request</a></p>
                    """

                    frappe.sendmail(
                        recipients=[assigned_user.email],
                        subject=subject,
                        message=message,
                        reference_doctype=self.doctype,
                        reference_name=self.name,
                    )
            except Exception as e:
                frappe.log_error(f"Failed to notify assigned user: {str(e)}", "Assignment Notification Error")


@frappe.whitelist()
def create_contact_request(
    member,
    subject,
    message,
    request_type="General Inquiry",
    preferred_contact_method="Email",
    urgency="Normal",
    preferred_time=None,
):
    """API method to create a contact request from the member portal"""

    # Validate member access
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(_("Authentication required"))

    # Check if user has access to this member
    member_doc = frappe.get_doc("Member", member)
    if not member_doc.has_permission("read"):
        frappe.throw(_("You don't have permission to create contact requests for this member"))

    # Create contact request
    contact_request = frappe.get_doc(
        {
            "doctype": "Member Contact Request",
            "member": member,
            "subject": subject,
            "message": message,
            "request_type": request_type,
            "preferred_contact_method": preferred_contact_method,
            "urgency": urgency,
            "preferred_time": preferred_time,
            "created_by_portal": 1,
            "request_date": frappe.utils.today(),
        }
    )

    contact_request.insert(ignore_permissions=True)

    return {
        "success": True,
        "message": _("Your contact request has been submitted successfully. We will get back to you soon."),
        "contact_request": contact_request.name,
    }


@frappe.whitelist()
def get_member_contact_requests(member, limit=10):
    """Get contact requests for a specific member"""

    # Validate member access
    member_doc = frappe.get_doc("Member", member)
    if not member_doc.has_permission("read"):
        frappe.throw(_("You don't have permission to view contact requests for this member"))

    contact_requests = frappe.get_all(
        "Member Contact Request",
        filters={"member": member},
        fields=["name", "subject", "request_type", "status", "request_date", "response_date"],
        order_by="request_date desc",
        limit=limit,
    )

    return contact_requests
