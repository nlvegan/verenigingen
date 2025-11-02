# File: verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.py

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now, today

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


class MembershipTerminationRequest(Document):
    def validate(self):
        self.set_defaults()
        self.calculate_termination_date()  # Calculate date so it's visible in all statuses
        self.set_approval_requirements()
        self.validate_permissions()
        self.validate_dates()
        self.validate_termination_request()  # Moved from hooks.py

    def get_grace_period_days(self):
        """Get grace period days from Verenigingen Settings"""
        settings = frappe.get_cached_doc("Verenigingen Settings")
        return settings.default_grace_period_days or 30  # Fallback to 30 if not set

    def calculate_termination_date(self):
        """Calculate termination date from member request date or today"""
        if not self.termination_date:
            if self.member_request_date:
                if self.apply_grace_period:
                    grace_days = self.get_grace_period_days()
                    self.termination_date = add_days(self.member_request_date, grace_days)
                else:
                    self.termination_date = self.member_request_date
            else:
                # Disciplinary/Administrative terminations without member request date use today
                self.termination_date = today()

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
            # IDEMPOTENCY CHECK: Prevent double-execution
            if self.execution_date:
                frappe.logger().info(
                    f"Termination {self.name} already executed on {self.execution_date} "
                    f"by {self.executed_by} - skipping duplicate execution"
                )
                frappe.msgprint(
                    _("This termination was already executed on {0}").format(
                        frappe.format(self.execution_date, {"fieldtype": "Datetime"})
                    ),
                    indicator="blue",
                )
                return True

            frappe.logger().info(f"Starting termination execution for {self.name}")

            # PRE-EXECUTION VALIDATION: Minimal checks for retry safety
            # Only check member exists - don't check status, as this enables retry after partial failure
            if not frappe.db.exists("Member", self.member):
                frappe.throw(_("Member {0} no longer exists").format(self.member))

            # Log member current status for audit purposes but don't block
            current_member_status = frappe.db.get_value("Member", self.member, "status")
            frappe.logger().info(
                f"Executing termination {self.name} - member {self.member} current status: {current_member_status}"
            )

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
            self.outstanding_invoices_cancelled = results.get("outstanding_invoices_cancelled", 0)

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
            self.flags.skip_termination_validation = True  # Skip validation during error recovery
            self.save()

            frappe.throw(_("Failed to execute termination: {0}").format(error_msg))

    def execute_system_updates_safely(self):
        """Execute system updates using safe integration methods from utils"""
        from verenigingen.utils.termination_integration import (
            cancel_dues_schedule_safe,
            cancel_future_invoices_safe,
            cancel_membership_safe,
            cancel_outstanding_invoices_safe,
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
            "dues_schedules_cancelled": 0,
            "invoices_updated": 0,
            "invoices_cancelled": 0,
            "invoices_deleted": 0,
            "outstanding_invoices_cancelled": 0,
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

        # 6. Update customer record if exists
        if member_doc.customer:
            termination_note = f"Member terminated on {self.termination_date or today()} - Type: {self.termination_type} - Request: {self.name}"
            # Note: Never disable customer - Member status already indicates termination
            # Customer record needs to remain accessible for financial/historical data
            disable_customer = False

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

            # 6a. Cancel outstanding invoices if requested (WARNING: Cannot be undone)
            if self.cancel_outstanding_invoices:
                termination_reason = (
                    f"Member terminated - Type: {self.termination_type} - Request: {self.name}"
                )
                outstanding_cancel_results = cancel_outstanding_invoices_safe(
                    member_doc.customer, termination_reason
                )
                results["outstanding_invoices_cancelled"] = outstanding_cancel_results.get(
                    "invoices_cancelled", 0
                ) + outstanding_cancel_results.get("invoices_deleted", 0)

                if results["outstanding_invoices_cancelled"] > 0:
                    results["actions_taken"].append(
                        f"Cancelled {results['outstanding_invoices_cancelled']} outstanding invoice(s)"
                    )

                # Log any errors from outstanding invoice cancellation
                for error in outstanding_cancel_results.get("errors", []):
                    results["errors"].append(error)

            # 6b. Cancel future invoices (coverage starts after termination)
            future_invoice_results = cancel_future_invoices_safe(
                member_doc.customer, self.termination_date or today()
            )
            results["invoices_cancelled"] = future_invoice_results.get("invoices_cancelled", 0)
            results["invoices_deleted"] = future_invoice_results.get("invoices_deleted", 0)

            if results["invoices_cancelled"] > 0:
                results["actions_taken"].append(
                    f"Cancelled {results['invoices_cancelled']} future invoice(s) with coverage after termination"
                )
            if results["invoices_deleted"] > 0:
                results["actions_taken"].append(
                    f"Deleted {results['invoices_deleted']} draft invoice(s) with coverage after termination"
                )

            # Log any errors from future invoice cancellation
            for error in future_invoice_results.get("errors", []):
                results["errors"].append(error)

        # 7. Cancel active dues schedules
        if member_doc.name:
            active_dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "member": member_doc.name,
                    "status": ["in", ["Active", "Past Due"]],
                },
                fields=["name"],
            )

            frappe.logger().info(f"Found {len(active_dues_schedules)} dues schedules to cancel")

            for dues_data in active_dues_schedules:
                if cancel_dues_schedule_safe(dues_data.name):
                    results["dues_schedules_cancelled"] += 1
                    results["actions_taken"].append(f"Cancelled dues schedule {dues_data.name}")
                else:
                    results["errors"].append(f"Failed to cancel dues schedule {dues_data.name}")

        # FINAL STEP: Update member status (only after all other operations complete)
        # This is the "commit point" - member status should be the last thing that changes
        if update_member_status_safe(
            member_doc.name, self.termination_type, self.termination_date or today(), self.name
        ):
            results["member_updated"] = True
            results["actions_taken"].append("Updated member status to Terminated")
            frappe.logger().info(f"Member {member_doc.name} status updated to Terminated as final step")

            # Recalculate total membership duration after termination
            try:
                member_doc.reload()  # Reload to get updated status
                member_doc.calculate_cumulative_membership_duration()
                member_doc.save(ignore_permissions=False)
                results["actions_taken"].append("Recalculated total membership duration")
                frappe.logger().info(
                    f"Total membership duration recalculated for {member_doc.name}: {member_doc.cumulative_membership_duration}"
                )
            except Exception as duration_error:
                error_msg = f"Failed to recalculate membership duration: {str(duration_error)}"
                results["errors"].append(error_msg)
                frappe.logger().error(f"Member {member_doc.name} duration calculation failed: {error_msg}")
        else:
            results["errors"].append("Failed to update member status")
            frappe.logger().error(
                f"CRITICAL: Failed to update member {member_doc.name} status - termination incomplete"
            )

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
        # Only set defaults for new documents - don't override user's choice on save
        if not self.is_new():
            return

        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

        if self.termination_type in disciplinary_types:
            # Default to requiring secondary approval for disciplinary
            # But Verenigingen Administrators can uncheck this if needed
            self.requires_secondary_approval = 1
        else:
            self.requires_secondary_approval = 0

    def handle_approved_status(self):
        """Handle when termination request is approved"""
        if not self.approved_by:
            self.approved_by = frappe.session.user
        if not self.approval_date:
            self.approval_date = now()

        # Calculate termination date using centralized logic
        self.calculate_termination_date()

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
    @critical_api(operation_type=OperationType.ADMIN)
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
            self.approval_date = now()

        # Calculate termination date using centralized logic
        self.calculate_termination_date()

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
    @critical_api(operation_type=OperationType.ADMIN)
    def approve_request(self, decision, notes=""):
        """Approve or reject the termination request"""
        if self.status not in ["Pending", "Draft"]:
            frappe.throw(_("Only pending or draft requests can be approved/rejected"))

        if decision == "approved":
            self.status = "Approved"
            self.approved_by = frappe.session.user
            self.approval_date = now()
            self.approver_notes = notes

            # Calculate termination date using centralized logic
            self.calculate_termination_date()

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
    @critical_api(operation_type=OperationType.ADMIN)
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
            # Validate permissions before querying Chapter Member records
            if frappe.has_permission("Chapter Member", "read"):
                member_chapters = frappe.get_all(
                    "Chapter Member",
                    filters={"member": self.member, "enabled": 1},
                    fields=["parent"],
                    order_by="chapter_join_date desc",
                    limit=1,
                )
                if member_chapters:
                    expulsion_entry.chapter_involved = member_chapters[0].parent
            else:
                # Log permission issue but continue - chapter is supplementary audit data
                frappe.logger().warning(
                    f"User {frappe.session.user} lacks permission to read Chapter Member - "
                    f"chapter information omitted from expulsion report"
                )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            # Secure expulsion report entry creation with explicit permission validation
            expulsion_result = secure_document_operation(
                operation="insert",
                doc=expulsion_entry,
                justification=f"Expulsion report entry creation for member termination {self.name}",
                required_permissions=["Expulsion Report:create"],
            )

            if not expulsion_result.success:
                frappe.logger().error(
                    f"Failed to create expulsion report entry: {'; '.join(expulsion_result.errors)}"
                )
                # Don't throw here - this is supplementary audit trail, shouldn't block termination

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
        # For voluntary exits, termination date shouldn't be before member request date
        if self.member_request_date and self.termination_date:
            if getdate(self.termination_date) < getdate(self.member_request_date):
                frappe.throw(_("Termination date cannot be before member request date"))

    def validate_termination_request(self):
        """Additional validation logic for termination requests (moved from hooks.py)"""
        # Skip validation if we're executing - member status was just changed by this process
        if self.status == "Executed":
            return

        # Skip validation during error recovery
        if getattr(self.flags, "skip_termination_validation", False):
            return

        # Validate that member exists and is active
        if not frappe.db.exists("Member", self.member):
            frappe.throw(_("Member {0} does not exist").format(self.member))

        member_status = frappe.db.get_value("Member", self.member, "status")
        # Allow termination of Expired members (formal closure), but not already Terminated/Banned/Deceased
        if member_status in ["Terminated", "Banned", "Deceased"]:
            frappe.throw(_("Cannot terminate member with status: {0}").format(member_status))

        # Validate disciplinary terminations
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        if self.termination_type in disciplinary_types:
            # Require documentation
            if not self.disciplinary_documentation:
                frappe.throw(_("Documentation is required for disciplinary terminations"))

            # Require secondary approver for pending approval status
            if not self.secondary_approver and self.status == "Pending Approval":
                frappe.throw(_("Secondary approver is required for disciplinary terminations"))

            # Validate approver permissions
            if self.secondary_approver:
                self._validate_approver_permissions(self.secondary_approver)

    def _validate_approver_permissions(self, user):
        """Validate that the user has permission to approve termination requests"""
        # Check if user exists and is enabled
        if not frappe.db.exists("User", user):
            frappe.throw(_("Approver {0} does not exist").format(user))

        user_doc = frappe.get_doc("User", user)
        if not user_doc.enabled:
            frappe.throw(_("Approver {0} is disabled").format(user))

        # Check if user has appropriate roles
        required_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Chapter Administrator",
            "Board Member",
        ]
        user_roles = frappe.get_roles(user)

        if not any(role in user_roles for role in required_roles):
            frappe.throw(_("User {0} does not have permission to approve termination requests").format(user))

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_termination_preview(self):
        """Get preview of what will be affected by this termination"""
        from verenigingen.utils.termination_utils import validate_termination_readiness

        return validate_termination_readiness(self.member)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
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
@high_security_api(operation_type=OperationType.MEMBER_DATA)
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
            "mollie_mandates": 0,
            "board_positions": 0,
            "outstanding_invoices": 0,
            "active_dues_schedules": 0,
            "volunteer_records": 0,
            "pending_volunteer_expenses": 0,
            "employee_records": 0,
            "user_account": False,
            "customer_linked": False,
        }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def execute_safe_member_termination(member, termination_type, termination_date=None):
    """Public API to execute termination using safe methods"""
    from verenigingen.api.termination_api import execute_safe_termination

    return execute_safe_termination(member, termination_type, termination_date)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_termination_status(member):
    """Get termination status for a member - redirect to member_utils"""
    from verenigingen.verenigingen.doctype.member.member_utils import get_member_termination_status

    return get_member_termination_status(member)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
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
@high_security_api(operation_type=OperationType.REPORTING)
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
@high_security_api(operation_type=OperationType.ADMIN)
def get_eligible_approvers(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
    """Get list of users eligible to approve termination requests

    Used as query function for Link field - returns list of tuples
    """
    try:
        # Get users with termination approval roles
        approval_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Chapter Administrator",
            "Board Member",
        ]

        conditions = "u.enabled = 1"
        if txt:
            conditions += f" AND (u.name LIKE %(txt)s OR u.full_name LIKE %(txt)s OR u.email LIKE %(txt)s)"

        # Get users with approval roles
        users = frappe.db.sql(
            f"""
            SELECT DISTINCT u.name, u.full_name
            FROM `tabUser` u
            INNER JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role IN %(roles)s
            AND {conditions}
            ORDER BY u.full_name
            LIMIT %(start)s, %(page_len)s
            """,
            {
                "roles": approval_roles,
                "txt": f"%{txt}%" if txt else "%",
                "start": start,
                "page_len": page_len,
            },
            as_list=True,
        )

        return users

    except Exception as e:
        frappe.log_error(f"Error getting eligible approvers: {str(e)}")
        return []


@frappe.whitelist()
@critical_api(operation_type=OperationType.REPORTING)
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
            conditions.append("mem.current_chapter_display = %s")
            values.append(filters["chapter"])

        # Add disciplinary/expulsion filter using parameterized query
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        # Build IN clause with proper number of placeholders
        in_placeholders = ", ".join(["%s"] * len(disciplinary_types))
        conditions.append(f"ter.termination_type IN ({in_placeholders})")
        values.extend(disciplinary_types)  # Add each type individually to values list

        # Get expulsion data - safe from SQL injection via parameterized WHERE clause
        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                ter.name as termination_request,
                ter.member,
                mem.full_name as member_name,
                mem.email as member_email,
                mem.current_chapter_display,
                ter.termination_type,
                ter.termination_reason,
                ter.termination_date,
                ter.execution_date,
                ter.executed_by,
                ter.status
            FROM `tabMembership Termination Request` ter
            LEFT JOIN `tabMember` mem ON ter.member = mem.name
            WHERE {where_clause}
            ORDER BY ter.termination_date DESC
        """

        expulsions = frappe.db.sql(query, tuple(values), as_dict=True)

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
            chapter = exp.current_chapter_display or "Unknown"
            summary["by_chapter"][chapter] = summary["by_chapter"].get(chapter, 0) + 1

        return {"success": True, "expulsions": expulsions, "summary": summary}

    except Exception as e:
        frappe.log_error(f"Error generating expulsion report: {str(e)}")
        return {"success": False, "error": str(e), "expulsions": [], "summary": {}}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
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

        # MIGRATED: Use unified EmailService for disciplinary notifications
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Prepare context for template
        context = {
            "member": member_doc,
            "member_name": member_doc.full_name,
            "reference": termination_request,
            "termination_request": termination_request,
        }

        # Send email if member has email
        if member_doc.email:
            result = email_service.send_notification(
                notification_type="member_suspension",  # Use existing notification type
                recipients=[member_doc.email],
                data=context,
                reference_doctype="Membership Termination Request",
                reference_name=termination_request,
            )

            return result.get("success", False)

        return False

    except Exception as e:
        frappe.log_error(f"Error sending disciplinary notification to {member}: {str(e)}")
        return False
