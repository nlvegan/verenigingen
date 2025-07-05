"""
Contact Request Automation
Handles automated workflows for member contact requests and CRM integration
"""


import frappe
from frappe import _
from frappe.utils import add_days, today


def process_contact_request_automation():
    """
    Scheduled task to process contact request automation
    - Follow-up reminders
    - Escalation for overdue requests
    - Auto-close resolved requests
    """

    try:
        send_follow_up_reminders()
        escalate_overdue_requests()
        auto_close_resolved_requests()
        sync_crm_status_updates()

        frappe.logger().info("Contact request automation completed successfully")

    except Exception as e:
        frappe.log_error(f"Error in contact request automation: {str(e)}", "Contact Request Automation")


def send_follow_up_reminders():
    """Send follow-up reminders for pending requests"""

    # Get requests that need follow-up reminders
    overdue_requests = frappe.get_all(
        "Member Contact Request",
        filters={
            "status": ["in", ["Open", "In Progress"]],
            "follow_up_date": ["<=", today()],
            "assigned_to": ["!=", ""],
        },
        fields=["name", "subject", "assigned_to", "member_name", "urgency", "follow_up_date"],
    )

    for request in overdue_requests:
        try:
            # Send reminder email to assigned user
            assigned_user = frappe.get_doc("User", request.assigned_to)
            if assigned_user.enabled and assigned_user.email:
                subject = f"Follow-up Reminder: {request.subject}"
                message = """
                <h3>Contact Request Follow-up Reminder</h3>
                <p>This is a reminder that the following contact request needs follow-up:</p>

                <p><strong>Request:</strong> {request.subject}</p>
                <p><strong>Member:</strong> {request.member_name}</p>
                <p><strong>Urgency:</strong> {request.urgency}</p>
                <p><strong>Follow-up Date:</strong> {request.follow_up_date}</p>

                <p><a href="/app/member-contact-request/{request.name}">View Contact Request</a></p>
                """

                frappe.sendmail(
                    recipients=[assigned_user.email],
                    subject=subject,
                    message=message,
                    reference_doctype="Member Contact Request",
                    reference_name=request.name,
                )

                # Update follow-up date to avoid duplicate reminders
                frappe.db.set_value(
                    "Member Contact Request", request.name, "follow_up_date", add_days(today(), 2)
                )

                frappe.logger().info(f"Sent follow-up reminder for contact request {request.name}")

        except Exception as e:
            frappe.log_error(
                f"Error sending follow-up reminder for {request.name}: {str(e)}", "Follow-up Reminder Error"
            )


def escalate_overdue_requests():
    """Escalate contact requests that are significantly overdue"""

    # Define escalation thresholds based on urgency
    urgency_thresholds = {
        "Urgent": 1,  # Escalate after 1 day
        "High": 3,  # Escalate after 3 days
        "Normal": 7,  # Escalate after 1 week
        "Low": 14,  # Escalate after 2 weeks
    }

    for urgency, threshold_days in urgency_thresholds.items():
        cutoff_date = add_days(today(), -threshold_days)

        overdue_requests = frappe.get_all(
            "Member Contact Request",
            filters={
                "status": ["in", ["Open", "In Progress"]],
                "urgency": urgency,
                "request_date": ["<=", cutoff_date],
            },
            fields=["name", "subject", "member_name", "assigned_to", "request_date", "urgency"],
        )

        for request in overdue_requests:
            try:
                escalate_contact_request(request, threshold_days)
            except Exception as e:
                frappe.log_error(
                    f"Error escalating contact request {request.name}: {str(e)}", "Escalation Error"
                )


def escalate_contact_request(request, overdue_days):
    """Escalate a specific contact request"""

    # Get managers to escalate to
    managers = frappe.get_all(
        "Has Role", filters={"role": "Verenigingen Administrator", "parenttype": "User"}, fields=["parent"]
    )

    if not managers:
        return

    manager_emails = []
    for manager in managers:
        user = frappe.get_doc("User", manager.parent)
        if user.enabled and user.email:
            manager_emails.append(user.email)

    if manager_emails:
        subject = f"ESCALATION: Overdue Contact Request - {request.subject}"
        message = """
        <h3 style="color: #dc3545;">Contact Request Escalation</h3>
        <p>The following contact request is overdue and requires immediate attention:</p>

        <p><strong>Request:</strong> {request.subject}</p>
        <p><strong>Member:</strong> {request.member_name}</p>
        <p><strong>Urgency:</strong> {request.urgency}</p>
        <p><strong>Submitted:</strong> {request.request_date}</p>
        <p><strong>Days Overdue:</strong> {overdue_days}</p>
        <p><strong>Currently Assigned:</strong> {request.assigned_to or "Unassigned"}</p>

        <p style="color: #dc3545;"><strong>Action Required:</strong> Please review and assign appropriate resources to resolve this request.</p>

        <p><a href="/app/member-contact-request/{request.name}">View Contact Request</a></p>
        """

        frappe.sendmail(
            recipients=manager_emails,
            subject=subject,
            message=message,
            reference_doctype="Member Contact Request",
            reference_name=request.name,
        )

        # Add escalation note to the request
        doc = frappe.get_doc("Member Contact Request", request.name)
        current_notes = doc.notes or ""
        escalation_note = (
            f"\n[{today()}] ESCALATED: Request overdue by {overdue_days} days. Managers notified."
        )
        doc.notes = current_notes + escalation_note
        doc.save(ignore_permissions=True)

        frappe.logger().info(f"Escalated contact request {request.name} after {overdue_days} days")


def auto_close_resolved_requests():
    """Automatically close resolved requests after a grace period"""

    grace_period_days = 7  # Wait 7 days before auto-closing resolved requests
    cutoff_date = add_days(today(), -grace_period_days)

    resolved_requests = frappe.get_all(
        "Member Contact Request",
        filters={
            "status": "Resolved",
            "closed_date": ["is", "not set"],
            "response_date": ["<=", cutoff_date],
        },
        fields=["name", "subject", "member", "member_name"],
    )

    for request in resolved_requests:
        try:
            # Update status to closed
            doc = frappe.get_doc("Member Contact Request", request.name)
            doc.status = "Closed"
            doc.closed_date = today()

            # Add auto-close note
            current_notes = doc.notes or ""
            auto_close_note = f"\n[{today()}] AUTO-CLOSED: Request automatically closed after {grace_period_days} day grace period."
            doc.notes = current_notes + auto_close_note

            doc.save(ignore_permissions=True)

            # Notify member that their request has been closed
            member_doc = frappe.get_doc("Member", request.member)
            if member_doc.email_address:
                subject = f"Contact Request Closed: {request.subject}"
                message = """
                <h3>Contact Request Closed</h3>
                <p>Dear {request.member_name},</p>

                <p>Your contact request "{request.subject}" has been marked as closed.</p>

                <p>If you need further assistance with this matter, please feel free to submit a new contact request through the member portal.</p>

                <p>Thank you for being a valued member!</p>

                <p><a href="/contact_request">Submit New Contact Request</a></p>
                """

                frappe.sendmail(
                    recipients=[member_doc.email_address],
                    subject=subject,
                    message=message,
                    reference_doctype="Member Contact Request",
                    reference_name=request.name,
                )

            frappe.logger().info(f"Auto-closed contact request {request.name}")

        except Exception as e:
            frappe.log_error(
                f"Error auto-closing contact request {request.name}: {str(e)}", "Auto-close Error"
            )


def sync_crm_status_updates():
    """Sync status updates between Contact Requests and CRM Leads"""

    # Get contact requests with linked CRM leads
    linked_requests = frappe.get_all(
        "Member Contact Request", filters={"crm_lead": ["!=", ""]}, fields=["name", "status", "crm_lead"]
    )

    for request in linked_requests:
        try:
            if frappe.db.exists("Lead", request.crm_lead):
                lead_doc = frappe.get_doc("Lead", request.crm_lead)

                # Sync status from contact request to lead
                lead_status_map = {
                    "Open": "Open",
                    "In Progress": "Open",
                    "Waiting for Response": "Replied",
                    "Resolved": "Converted",
                    "Closed": "Do Not Contact",
                }

                new_lead_status = lead_status_map.get(request.status, "Open")

                if lead_doc.status != new_lead_status:
                    lead_doc.status = new_lead_status
                    lead_doc.save(ignore_permissions=True)

                    frappe.logger().info(
                        f"Synced status for CRM Lead {request.crm_lead} to {new_lead_status}"
                    )

        except Exception as e:
            frappe.log_error(
                f"Error syncing CRM status for contact request {request.name}: {str(e)}", "CRM Sync Error"
            )


@frappe.whitelist()
def create_opportunity_from_contact_request(contact_request_name):
    """Create a CRM Opportunity from a contact request"""

    try:
        contact_request = frappe.get_doc("Member Contact Request", contact_request_name)

        if not contact_request.crm_lead:
            frappe.throw(_("No CRM Lead linked to this contact request"))

        lead_doc = frappe.get_doc("Lead", contact_request.crm_lead)

        # Check if opportunity already exists
        if contact_request.crm_opportunity:
            frappe.throw(_("Opportunity already exists for this contact request"))

        # Create opportunity
        opportunity_data = {
            "doctype": "Opportunity",
            "opportunity_from": "Lead",
            "party_name": lead_doc.name,
            "customer_name": lead_doc.lead_name,
            "contact_email": lead_doc.email_id,
            "contact_mobile": lead_doc.phone,
            "source": lead_doc.source,
            "opportunity_type": "Sales",
            "title": f"Follow-up: {contact_request.subject}",
            "with_items": 0,
            "custom_member_contact_request": contact_request.name,
            "custom_member_id": contact_request.member,
        }

        opportunity_doc = frappe.get_doc(opportunity_data)
        opportunity_doc.insert(ignore_permissions=True)

        # Link back to contact request
        contact_request.crm_opportunity = opportunity_doc.name
        contact_request.save(ignore_permissions=True)

        return {
            "success": True,
            "message": _("Opportunity created successfully"),
            "opportunity": opportunity_doc.name,
        }

    except Exception as e:
        frappe.log_error(
            f"Error creating opportunity from contact request {contact_request_name}: {str(e)}",
            "Opportunity Creation Error",
        )
        frappe.throw(_("Failed to create opportunity: {0}").format(str(e)))


@frappe.whitelist()
def get_contact_request_analytics():
    """Get analytics data for contact requests"""

    try:
        # Get request counts by status
        status_counts = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabMember Contact Request`
            GROUP BY status
        """,
            as_dict=True,
        )

        # Get request counts by type
        type_counts = frappe.db.sql(
            """
            SELECT request_type, COUNT(*) as count
            FROM `tabMember Contact Request`
            GROUP BY request_type
            ORDER BY count DESC
        """,
            as_dict=True,
        )

        # Get average response time
        avg_response_time = frappe.db.sql(
            """
            SELECT AVG(DATEDIFF(response_date, request_date)) as avg_days
            FROM `tabMember Contact Request`
            WHERE response_date IS NOT NULL
        """,
            as_dict=True,
        )

        # Get monthly request volume
        monthly_volume = frappe.db.sql(
            """
            SELECT
                YEAR(request_date) as year,
                MONTH(request_date) as month,
                COUNT(*) as count
            FROM `tabMember Contact Request`
            WHERE request_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
            GROUP BY YEAR(request_date), MONTH(request_date)
            ORDER BY year, month
        """,
            as_dict=True,
        )

        return {
            "status_distribution": status_counts,
            "request_types": type_counts,
            "avg_response_time_days": avg_response_time[0].avg_days
            if avg_response_time and avg_response_time[0].avg_days
            else 0,
            "monthly_volume": monthly_volume,
        }

    except Exception as e:
        frappe.log_error(f"Error getting contact request analytics: {str(e)}", "Analytics Error")
        return {}
