# File: verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now, today


class MembershipTerminationRequest(Document):
    def validate(self):
        self.set_defaults()
        self.set_approval_requirements()
        self.validate_permissions()
        self.validate_dates()

    def set_defaults(self):
        """Set default values"""
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.request_date:
            self.request_date = today()

    def before_save(self):
        self.add_audit_entry("Document Updated", f"Status: {self.status}")

    def after_insert(self):
        self.add_audit_entry("Request Created", f"Termination type: {self.termination_type}")

    def on_update_after_submit(self):
        """Handle status changes after document is submitted (workflow changes)"""
        if self.has_value_changed("status"):
            self.handle_status_change()

    def on_submit(self):
        """Called when document is submitted via workflow"""
        if self.status == "Executed":
            self.execute_termination_internal()

    def handle_status_change(self):
        """Handle workflow status changes"""
        old_status = self.get_doc_before_save().status if self.get_doc_before_save() else None
        new_status = self.status

        frappe.logger().info(
            f"Termination request {self.name} status changed from {old_status} to {new_status}"
        )

        # Add audit trail entry
        self.add_audit_entry(
            "Status Changed", f"Status changed from {old_status} to {new_status}", is_system=True
        )

        # Handle specific status transitions
        if new_status == "Executed" and old_status != "Executed":
            frappe.logger().info(f"Executing termination for request {self.name}")
            self.execute_termination_internal()
        elif new_status == "Approved":
            self.handle_approved_status()
        elif new_status == "Rejected":
            self.handle_rejected_status()

    def execute_termination_internal(self):
        """Internal method for executing termination using safe integration methods"""
        try:
            frappe.logger().info(f"Starting termination execution for {self.name}")

            # Validate we can execute
            if self.status != "Executed":
                frappe.throw(_("Termination can only be executed when status is 'Executed'"))

            # Execute system updates using safe integration methods
            results = self.execute_system_updates_safely()

            # Update execution fields
            if not self.executed_by:
                self.executed_by = frappe.session.user
            if not self.execution_date:
                self.execution_date = now()

            # Update counters from results
            self.sepa_mandates_cancelled = results.get("sepa_mandates_cancelled", 0)
            self.positions_ended = results.get("positions_ended", 0)
            self.newsletters_updated = 1 if results.get("customer_updated") else 0

            # Save changes (use flags to avoid validation issues)
            self.flags.ignore_validate_update_after_submit = True
            self.save()

            self.add_audit_entry(
                "Termination Executed",
                f"System updates completed: {len(results.get('actions_taken', []))} actions",
            )

            frappe.logger().info(f"Termination execution completed for {self.name}")

            # Show success message
            if results.get("errors"):
                frappe.msgprint(
                    _("Membership termination executed with {0} warnings. Check logs for details.").format(
                        len(results["errors"])
                    ),
                    indicator="orange",
                )
            else:
                frappe.msgprint(_("Membership termination executed successfully"))

            return True

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Termination execution failed for {self.name}: {error_msg}")
            self.add_audit_entry("Execution Failed", f"Error: {error_msg}")

            # Revert status if execution failed
            self.status = "Approved"
            self.flags.ignore_validate_update_after_submit = True
            self.save()

            frappe.throw(_("Failed to execute termination: {0}").format(error_msg))

    def execute_system_updates_safely(self):
        """Execute system updates using safe integration methods from utils"""
        from verenigingen.utils.termination_integration import (  # Updated to use dues schedule system
            cancel_membership_safe,
            cancel_sepa_mandate_safe,
            deactivate_user_account_safe,
            end_board_positions_safe,
            suspend_team_memberships_safe,
            terminate_employee_records_safe,
            terminate_volunteer_records_safe,
            update_customer_safe,
            update_invoice_safe,
            update_member_status_safe,
        )

        results = {
            "actions_taken": [],
            "errors": [],
            "sepa_mandates_cancelled": 0,
            "memberships_cancelled": 0,
            "positions_ended": 0,
            # "dues_schedules_cancelled": 0,  # Updated to use dues schedule system
            "invoices_updated": 0,
            "customer_updated": False,
            "member_updated": False,
            "volunteers_terminated": 0,
            "volunteer_expenses_cancelled": 0,
            "employees_terminated": 0,
            "user_deactivated": False,
        }

        # Get member document
        member_doc = frappe.get_doc("Member", self.member)

        frappe.logger().info(f"Starting safe system updates for member {self.member}")

        # 1. Cancel active memberships
        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_doc.name, "status": ["in", ["Active", "Pending"]], "docstatus": 1},
            fields=["name", "membership_type"],  # Removed legacy field
        )

        frappe.logger().info(f"Found {len(active_memberships)} active memberships to cancel")

        for membership_data in active_memberships:
            if cancel_membership_safe(
                membership_data.name,
                self.termination_date or today(),
                f"Member terminated - Request: {self.name}",
                "Immediate",
            ):
                results["memberships_cancelled"] += 1
                results["actions_taken"].append(f"Cancelled membership {membership_data.name}")

                # Updated to use dues schedule system
                # Also cancel associated dues schedule
                # if membership_data.dues_schedule:
                #     if cancel_dues_schedule_safe(membership_data.dues_schedule):
                #         results["dues_schedules_cancelled"] += 1
                #         results["actions_taken"].append(
                #             f"Cancelled dues schedule {membership_data.dues_schedule}"
                #         )
                #     else:
                #         results["errors"].append(
                #             f"Failed to cancel dues schedule {membership_data.dues_schedule}"
                #         )
            else:
                results["errors"].append(f"Failed to cancel membership {membership_data.name}")

        # 2. Cancel SEPA mandates if requested
        if self.cancel_sepa_mandates:
            active_mandates = frappe.get_all(
                "SEPA Mandate",
                filters={"member": member_doc.name, "status": "Active", "is_active": 1},
                fields=["name", "mandate_id"],
            )

            frappe.logger().info(f"Found {len(active_mandates)} SEPA mandates to cancel")

            for mandate_data in active_mandates:
                if cancel_sepa_mandate_safe(
                    mandate_data.name,
                    f"Member terminated - Request: {self.name}",
                    self.termination_date or today(),
                ):
                    results["sepa_mandates_cancelled"] += 1
                    results["actions_taken"].append(f"Cancelled SEPA mandate {mandate_data.mandate_id}")
                else:
                    results["errors"].append(f"Failed to cancel SEPA mandate {mandate_data.mandate_id}")

        # 3. End board positions if requested
        if self.end_board_positions:
            positions_ended = end_board_positions_safe(
                member_doc.name, self.termination_date or today(), f"Member terminated - Request: {self.name}"
            )
            results["positions_ended"] = positions_ended
            if positions_ended > 0:
                results["actions_taken"].append(f"Ended {positions_ended} board position(s)")

        # 4. Suspend team memberships
        teams_suspended = suspend_team_memberships_safe(
            member_doc.name, self.termination_date or today(), f"Member terminated - Request: {self.name}"
        )
        results["teams_suspended"] = teams_suspended
        if teams_suspended > 0:
            results["actions_taken"].append(f"Suspended {teams_suspended} team membership(s)")

        # 5. Deactivate user account
        termination_reason = f"Member terminated - Type: {self.termination_type} - Request: {self.name}"
        if deactivate_user_account_safe(member_doc.name, self.termination_type, termination_reason):
            results["user_deactivated"] = True
            results["actions_taken"].append("Deactivated user account")
        else:
            results["user_deactivated"] = False
            results["errors"].append("Failed to deactivate user account")

        # 5a. Terminate volunteer records
        volunteer_results = terminate_volunteer_records_safe(
            member_doc.name, self.termination_type, self.termination_date or today(), termination_reason
        )
        results["volunteers_terminated"] = volunteer_results["volunteers_terminated"]
        results["volunteer_expenses_cancelled"] = volunteer_results["volunteer_expenses_cancelled"]
        results["actions_taken"].extend(volunteer_results["actions_taken"])
        results["errors"].extend(volunteer_results["errors"])

        # 5b. Terminate employee records
        employee_results = terminate_employee_records_safe(
            member_doc.name, self.termination_type, self.termination_date or today(), termination_reason
        )
        results["employees_terminated"] = employee_results["employees_terminated"]
        results["actions_taken"].extend(employee_results["actions_taken"])
        results["errors"].extend(employee_results["errors"])

        # 6. Update member status
        if update_member_status_safe(
            member_doc.name, self.termination_type, self.termination_date or today(), self.name
        ):
            results["member_updated"] = True
            results["actions_taken"].append("Updated member status")
        else:
            results["errors"].append("Failed to update member status")

        # 5. Update customer record if exists
        if member_doc.customer:
            termination_note = f"Member terminated on {self.termination_date or today()} - Type: {self.termination_type} - Request: {self.name}"
            disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
            disable_customer = self.termination_type in disciplinary_types

            if update_customer_safe(member_doc.customer, termination_note, disable_customer):
                results["customer_updated"] = True
                results["actions_taken"].append("Updated customer record")
            else:
                results["errors"].append("Failed to update customer record")

        # 6. Update outstanding invoices
        if member_doc.customer:
            outstanding_invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "customer": member_doc.customer,
                    "docstatus": 1,
                    "status": ["in", ["Unpaid", "Overdue", "Partially Paid"]],
                },
                fields=["name"],
            )

            termination_note = (
                f"Member terminated on {self.termination_date or today()} - Request: {self.name}"
            )

            for invoice_data in outstanding_invoices:
                if update_invoice_safe(invoice_data.name, termination_note):
                    results["invoices_updated"] += 1
                else:
                    results["errors"].append(f"Failed to update invoice {invoice_data.name}")

            if results["invoices_updated"] > 0:
                results["actions_taken"].append(
                    f"Updated {results['invoices_updated']} outstanding invoice(s)"
                )

        # Updated to use dues schedule system
        # 7. Handle additional dues schedules not linked to memberships
        # if member_doc.name:
        #     remaining_dues_schedules = frappe.get_all(
        #         "Membership Dues Schedule",
        #         filters={
        #             "member": member_doc.name,
        #             "status": ["in", ["Active", "Past Due"]],
        #         },
        #         fields=["name"],
        #     )
        #
        #     for dues_data in remaining_dues_schedules:
        #         if cancel_dues_schedule_safe(dues_data.name):
        #             results["dues_schedules_cancelled"] += 1
        #             results["actions_taken"].append(f"Cancelled additional dues schedule {dues_data.name}")
        #         else:
        #             results["errors"].append(f"Failed to cancel dues schedule {dues_data.name}")

        # Log results
        frappe.logger().info(f"System updates completed: {results}")

        # Add detailed audit entries
        for action in results["actions_taken"]:
            self.add_audit_entry("System Update", action, is_system=True)

        for error in results["errors"]:
            self.add_audit_entry("System Update Error", error, is_system=True)

        return results

    def add_audit_entry(self, action, details, is_system=False):
        """Add an entry to the audit trail with proper user handling"""
        # Handle system entries properly - use Administrator instead of "System"
        audit_user = frappe.session.user if not is_system else "Administrator"

        # Ensure the user exists
        if not frappe.db.exists("User", audit_user):
            audit_user = "Administrator"

        self.append(
            "audit_trail",
            {
                "timestamp": now(),
                "action": action,
                "user": audit_user,
                "details": details,
                "system_action": 1 if is_system else 0,
            },
        )

    def set_approval_requirements(self):
        """Set whether secondary approval is required based on termination type"""
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

        if self.termination_type in disciplinary_types:
            self.requires_secondary_approval = 1
        else:
            self.requires_secondary_approval = 0

    def handle_approved_status(self):
        """Handle when termination request is approved"""
        if not self.approved_by:
            self.approved_by = frappe.session.user
        if not self.approval_date:
            self.approval_date = now()

        # Set default termination date if not provided
        if not self.termination_date:
            self.termination_date = today()

        # Add to expulsion report if disciplinary
        if self.requires_secondary_approval:
            self.add_to_expulsion_report()

    def handle_rejected_status(self):
        """Handle when termination request is rejected"""
        if not self.approved_by:
            self.approved_by = frappe.session.user
        if not self.approval_date:
            self.approval_date = now()

    @frappe.whitelist()
    def submit_for_approval(self):
        """Submit the termination request for approval"""
        if self.status != "Draft":
            frappe.throw(_("Only draft requests can be submitted for approval"))

        # Validate required fields
        if not self.termination_reason:
            frappe.throw(_("Termination reason is required"))

        # Check disciplinary documentation requirement
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        if self.termination_type in disciplinary_types and not self.disciplinary_documentation:
            frappe.throw(_("Documentation is required for disciplinary actions"))

        # Set approval requirements
        self.set_approval_requirements()

        # Update status
        if self.requires_secondary_approval:
            self.status = "Pending"
            if not self.secondary_approver:
                frappe.throw(_("Secondary approver is required for this termination type"))
        else:
            # For simple terminations, can go directly to approved
            self.status = "Approved"
            self.approved_by = frappe.session.user
            self.approved_date = now()

        # Set default termination date if not provided
        if not self.termination_date:
            grace_period_types = ["Voluntary", "Non-payment", "Deceased"]
            if self.termination_type in grace_period_types:
                self.termination_date = add_days(today(), 30)  # 30-day grace period
                self.grace_period_end = self.termination_date
            else:
                self.termination_date = today()  # Immediate for disciplinary

        # Save the document
        self.save()

        # Add audit entry
        self.add_audit_entry("Submitted for Approval", f"Status changed to {self.status}")

        # Send notifications if needed
        if self.status == "Pending" and self.secondary_approver:
            self.send_approval_notification()

        frappe.msgprint(_("Termination request submitted for approval"))

        return {"status": self.status, "message": "Request submitted successfully"}

    def send_approval_notification(self):
        """Send notification to approver"""
        try:
            if self.secondary_approver:
                # Could implement email notification here
                frappe.logger().info(f"Approval notification should be sent to {self.secondary_approver}")
        except Exception as e:
            frappe.logger().error(f"Failed to send approval notification: {str(e)}")

    @frappe.whitelist()
    def approve_request(self, decision, notes=""):
        """Approve or reject the termination request"""
        if self.status not in ["Pending", "Draft"]:
            frappe.throw(_("Only pending or draft requests can be approved/rejected"))

        if decision == "approved":
            self.status = "Approved"
            self.approved_by = frappe.session.user
            self.approved_date = now()
            self.approver_notes = notes

            # Set default termination date if not provided
            if not self.termination_date:
                grace_period_types = ["Voluntary", "Non-payment", "Deceased"]
                if self.termination_type in grace_period_types:
                    self.termination_date = add_days(today(), 30)  # 30-day grace period
                    self.grace_period_end = self.termination_date
                else:
                    self.termination_date = today()  # Immediate for disciplinary

            self.add_audit_entry("Request Approved", f"Approved by {frappe.session.user}")
            frappe.msgprint(_("Termination request approved"))

        elif decision == "rejected":
            self.status = "Rejected"
            self.approved_by = frappe.session.user
            self.approval_date = now()
            self.approver_notes = notes

            self.add_audit_entry("Request Rejected", f"Rejected by {frappe.session.user}: {notes}")
            frappe.msgprint(_("Termination request rejected"))

        else:
            frappe.throw(_("Invalid decision. Must be 'approved' or 'rejected'"))

        # Save the document
        self.save()

        return {"status": self.status, "message": f"Request {decision} successfully"}

    @frappe.whitelist()
    def execute_termination(self):
        """Execute the termination request"""
        if self.status != "Approved":
            frappe.throw(_("Only approved requests can be executed"))

        # Update status to executed
        self.status = "Executed"

        # Call the internal execution method
        success = self.execute_termination_internal()

        if success:
            frappe.msgprint(_("Termination executed successfully"))
            return {"status": self.status, "message": "Termination executed successfully"}
        else:
            frappe.throw(_("Failed to execute termination"))

    def add_to_expulsion_report(self):
        """Add disciplinary termination to expulsion report"""
        if self.termination_type not in ["Policy Violation", "Disciplinary Action", "Expulsion"]:
            return

        try:
            # Create expulsion report entry
            expulsion_entry = frappe.new_doc("Expulsion Report Entry")
            expulsion_entry.member_name = self.member_name
            expulsion_entry.member_id = self.member
            expulsion_entry.expulsion_date = self.termination_date or today()
            expulsion_entry.expulsion_type = self.termination_type
            expulsion_entry.initiated_by = self.requested_by
            expulsion_entry.approved_by = self.approved_by
            expulsion_entry.documentation = self.disciplinary_documentation
            expulsion_entry.status = "Active"

            # Get member's primary chapter from Chapter Member table
            member_chapters = frappe.get_all(
                "Chapter Member",
                filters={"member": self.member, "enabled": 1},
                fields=["parent"],
                order_by="chapter_join_date desc",
                limit=1,
                ignore_permissions=True,
            )
            if member_chapters:
                expulsion_entry.chapter_involved = member_chapters[0].parent

            expulsion_entry.flags.ignore_permissions = True
            expulsion_entry.insert()

            frappe.logger().info(f"Added expulsion report entry for {self.member_name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create expulsion report entry: {str(e)}")

    def validate_permissions(self):
        """Validate user permissions for different termination types"""
        from verenigingen.permissions import can_access_termination_functions, can_terminate_member

        # Check if user can access termination functions in general
        if not can_access_termination_functions():
            frappe.throw(_("You don't have permission to access termination functions"))

        # Check if user can terminate this specific member
        if self.member and not can_terminate_member(self.member):
            frappe.throw(_("You don't have permission to terminate this member"))

    def validate_dates(self):
        """Validate termination and grace period dates"""
        if self.termination_date and getdate(self.termination_date) < getdate(self.request_date):
            frappe.throw(_("Termination date cannot be before request date"))

        if self.grace_period_end and self.termination_date:
            if getdate(self.grace_period_end) < getdate(self.termination_date):
                frappe.throw(_("Grace period end cannot be before termination date"))

    @frappe.whitelist()
    def get_termination_preview(self):
        """Get preview of what will be affected by this termination"""
        from verenigingen.utils.termination_utils import validate_termination_readiness

        return validate_termination_readiness(self.member)

    @frappe.whitelist()
    def simulate_execution(self):
        """Simulate what would happen if this termination were executed"""
        from verenigingen.utils.termination_utils import get_termination_impact_summary

        return get_termination_impact_summary(self.member)


# Module-level function for workflow integration
def on_workflow_action(doc, action):
    """Called by workflow when action is taken"""
    frappe.logger().info(f"Workflow action '{action}' taken on {doc.name}")

    if action == "Execute" and doc.status == "Executed":
        frappe.logger().info(f"Executing termination via workflow for {doc.name}")
        doc.execute_termination_internal()


# Module-level function for document hooks
def handle_status_change(doc, method=None):
    """Handle status changes for termination requests"""
    if hasattr(doc, "handle_status_change"):
        doc.handle_status_change()


# Public API methods that can be called from outside
@frappe.whitelist()
def get_termination_impact_preview(member):
    """Public API to get termination impact preview"""
    from verenigingen.utils.termination_utils import validate_termination_readiness

    readiness_data = validate_termination_readiness(member)

    # Return the impact data in the format expected by the frontend
    if readiness_data and "impact" in readiness_data:
        impact = readiness_data["impact"]

        # Add customer linkage info
        member_doc = frappe.get_doc("Member", member)
        impact["customer_linked"] = bool(member_doc.customer)

        return impact
    else:
        # Fallback - return empty impact data
        return {
            "active_memberships": 0,
            "sepa_mandates": 0,
            "board_positions": 0,
            "outstanding_invoices": 0,
            # "dues_schedules": 0,  # Updated to use dues schedule system
            "volunteer_records": 0,
            "pending_volunteer_expenses": 0,
            "employee_records": 0,
            "user_account": False,
            "customer_linked": False,
        }


@frappe.whitelist()
def execute_safe_member_termination(member, termination_type, termination_date=None):
    """Public API to execute termination using safe methods"""
    from verenigingen.api.termination_api import execute_safe_termination

    return execute_safe_termination(member, termination_type, termination_date)


@frappe.whitelist()
def get_member_termination_status(member):
    """Get termination status for a member - redirect to member_utils"""
    from verenigingen.verenigingen.doctype.member.member_utils import get_member_termination_status

    return get_member_termination_status(member)


@frappe.whitelist()
def get_member_termination_history(member):
    """Get termination history for a member"""
    try:
        # Get all termination requests for this member
        termination_requests = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member},
            fields=[
                "name",
                "termination_type",
                "termination_reason",
                "status",
                "request_date",
                "termination_date",
                "execution_date",
                "requested_by",
                "approved_by",
                "executed_by",
            ],
            order_by="request_date desc",
        )

        # Get audit trail for each request
        for request in termination_requests:
            audit_trail = frappe.get_all(
                "Termination Audit Entry",
                filters={"parent": request.name},
                fields=["timestamp", "action", "user", "details", "system_action"],
                order_by="timestamp desc",
            )
            request["audit_trail"] = audit_trail

        return {
            "success": True,
            "termination_requests": termination_requests,
            "total_requests": len(termination_requests),
        }

    except Exception as e:
        frappe.log_error(f"Error getting termination history for {member}: {str(e)}")
        return {"success": False, "error": str(e), "termination_requests": []}


@frappe.whitelist()
def get_termination_statistics():
    """Get termination statistics for dashboard display"""
    try:
        # Get statistics for different termination types and statuses
        stats = {}

        # Total termination requests
        stats["total_requests"] = frappe.db.count("Membership Termination Request")

        # By status
        status_counts = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabMembership Termination Request`
            GROUP BY status
        """,
            as_dict=True,
        )

        stats["by_status"] = {item.status: item.count for item in status_counts}

        # By termination type
        type_counts = frappe.db.sql(
            """
            SELECT termination_type, COUNT(*) as count
            FROM `tabMembership Termination Request`
            GROUP BY termination_type
        """,
            as_dict=True,
        )

        stats["by_type"] = {item.termination_type: item.count for item in type_counts}

        # Recent requests (last 30 days)
        recent_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMembership Termination Request`
            WHERE request_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        """,
            as_dict=True,
        )

        stats["recent_requests"] = recent_count[0].count if recent_count else 0

        # Pending approvals
        pending_count = frappe.db.count(
            "Membership Termination Request", filters={"status": ["in", ["Pending Approval", "Under Review"]]}
        )

        stats["pending_approvals"] = pending_count

        return {"success": True, "statistics": stats}

    except Exception as e:
        frappe.log_error(f"Error getting termination statistics: {str(e)}")
        return {"success": False, "error": str(e), "statistics": {}}


@frappe.whitelist()
def get_eligible_approvers():
    """Get list of users eligible to approve termination requests"""
    try:
        # Get users with termination approval roles
        approval_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Chapter Administrator",
            "Board Member",
        ]

        eligible_users = []

        for role in approval_roles:
            users = frappe.get_all(
                "Has Role", filters={"role": role, "parenttype": "User"}, fields=["parent as user"]
            )

            for user in users:
                user_doc = frappe.get_doc("User", user.user)
                if user_doc.enabled and user_doc.name not in [u["user"] for u in eligible_users]:
                    eligible_users.append(
                        {
                            "user": user_doc.name,
                            "full_name": user_doc.full_name,
                            "email": user_doc.email,
                            "role": role,
                        }
                    )

        return {"success": True, "approvers": eligible_users}

    except Exception as e:
        frappe.log_error(f"Error getting eligible approvers: {str(e)}")
        return {"success": False, "error": str(e), "approvers": []}


@frappe.whitelist()
def generate_expulsion_report(filters=None):
    """Generate expulsion report based on filters"""
    try:
        if not filters:
            filters = {}

        # Build query conditions
        conditions = ["1=1"]
        values = []

        if filters.get("from_date"):
            conditions.append("ter.termination_date >= %s")
            values.append(filters["from_date"])

        if filters.get("to_date"):
            conditions.append("ter.termination_date <= %s")
            values.append(filters["to_date"])

        if filters.get("termination_type"):
            conditions.append("ter.termination_type = %s")
            values.append(filters["termination_type"])

        if filters.get("chapter"):
            conditions.append("mem.current_chapter = %s")
            values.append(filters["chapter"])

        # Get expulsion data
        query = f"""
            SELECT
                ter.name as termination_request,
                ter.member,
                mem.full_name as member_name,
                mem.email as member_email,
                mem.current_chapter,
                ter.termination_type,
                ter.termination_reason,
                ter.termination_date,
                ter.execution_date,
                ter.executed_by,
                ter.status
            FROM `tabMembership Termination Request` ter
            LEFT JOIN `tabMember` mem ON ter.member = mem.name
            WHERE {' AND '.join(conditions)}
            AND ter.termination_type IN ('Disciplinary', 'Expulsion', 'Exclusion')
            ORDER BY ter.termination_date DESC
        """

        expulsions = frappe.db.sql(query, values, as_dict=True)

        # Get summary statistics
        summary = {
            "total_expulsions": len(expulsions),
            "by_type": {},
            "by_chapter": {},
            "date_range": {"from": filters.get("from_date"), "to": filters.get("to_date")},
        }

        for exp in expulsions:
            # Count by type
            exp_type = exp.termination_type
            summary["by_type"][exp_type] = summary["by_type"].get(exp_type, 0) + 1

            # Count by chapter
            chapter = exp.current_chapter or "Unknown"
            summary["by_chapter"][chapter] = summary["by_chapter"].get(chapter, 0) + 1

        return {"success": True, "expulsions": expulsions, "summary": summary}

    except Exception as e:
        frappe.log_error(f"Error generating expulsion report: {str(e)}")
        return {"success": False, "error": str(e), "expulsions": [], "summary": {}}


@frappe.whitelist()
def initiate_disciplinary_termination(member, reason, evidence=None, reporter=None):
    """Initiate disciplinary termination procedure for a member"""
    try:
        # Validate input
        if not member:
            frappe.throw(_("Member is required"))

        if not reason:
            frappe.throw(_("Reason is required for disciplinary termination"))

        # Check if member exists and is active
        member_doc = frappe.get_doc("Member", member)
        if member_doc.membership_status in ["Terminated", "Suspended"]:
            frappe.throw(_("Member is already terminated or suspended"))

        # Check if there's already a pending disciplinary request
        existing_request = frappe.db.exists(
            "Membership Termination Request",
            {
                "member": member,
                "termination_type": "Disciplinary",
                "status": ["in", ["Draft", "Pending Approval", "Under Review"]],
            },
        )

        if existing_request:
            frappe.throw(_("There is already a pending disciplinary termination request for this member"))

        # Create disciplinary termination request
        termination_request = frappe.new_doc("Membership Termination Request")
        termination_request.member = member
        termination_request.termination_type = "Disciplinary"
        termination_request.termination_reason = reason
        termination_request.requested_by = reporter or frappe.session.user
        termination_request.request_date = today()
        termination_request.status = "Draft"
        termination_request.requires_board_approval = 1
        termination_request.requires_governance_review = 1

        # Add evidence if provided
        if evidence:
            termination_request.supporting_documentation = evidence

        # Set disciplinary-specific fields
        termination_request.disciplinary_procedure = 1
        termination_request.investigation_required = 1

        # Save the request
        termination_request.insert()
        termination_request.add_audit_entry(
            "Disciplinary Procedure Initiated",
            f"Disciplinary termination initiated by {frappe.session.user}. Reason: {reason}",
        )

        # Submit for approval workflow
        termination_request.submit_for_approval()

        # Send notifications to relevant parties
        termination_request.send_approval_notification()

        # Notify the member if required by policy
        # TODO: Add notify_member_of_disciplinary_action field to Verenigingen Settings doctype
        # Future enhancement: send_disciplinary_notification(member, termination_request.name)

        return {
            "success": True,
            "termination_request": termination_request.name,
            "message": _("Disciplinary termination procedure has been initiated for {0}").format(
                member_doc.full_name
            ),
        }

    except Exception as e:
        frappe.log_error(f"Error initiating disciplinary termination for {member}: {str(e)}")
        return {"success": False, "error": str(e)}


def send_disciplinary_notification(member, termination_request):
    """Send notification to member about disciplinary action"""
    try:
        member_doc = frappe.get_doc("Member", member)

        # Prepare email content
        subject = _("Notice of Disciplinary Procedure")

        message = _(
            "Dear {0},\n\nThis is to inform you that a disciplinary procedure has been initiated regarding your membership. You will be contacted with further details as the process proceeds.\n\nReference: {1}\n\nRegards,\nMembership Administration"
        ).format(member_doc.full_name, termination_request)

        # Send email if member has email
        if member_doc.email:
            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message, delayed=False)

        return True

    except Exception as e:
        frappe.log_error(f"Error sending disciplinary notification to {member}: {str(e)}")
        return False
