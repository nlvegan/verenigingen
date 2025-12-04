import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator, DocumentExistenceValidator

# Configuration Constants
MINIMUM_FEE_PERCENTAGE = 0.3  # 30% of base amount
STUDENT_MINIMUM_FEE_PERCENTAGE = 0.5  # 50% of base amount for students
ABSOLUTE_MINIMUM_FEE = 5.0  # €5 absolute minimum
SMALL_ADJUSTMENT_THRESHOLD = 0.05  # 5% threshold for auto-approval
ERROR_MESSAGE_MAX_LENGTH = 200  # Maximum error message length for logging


def format_error_for_logging(error, context=""):
    """
    Format error messages for structured logging.

    Args:
        error: Exception or string error message
        context: Additional context for the error

    Returns:
        dict: Structured error information for logging
    """
    error_str = str(error)

    return {
        "error_type": type(error).__name__ if hasattr(error, "__class__") else "Unknown",
        "error_message": (
            error_str if len(error_str) <= ERROR_MESSAGE_MAX_LENGTH else error_str[:ERROR_MESSAGE_MAX_LENGTH]
        ),
        "full_error_logged": len(error_str) > ERROR_MESSAGE_MAX_LENGTH,
        "context": context,
    }


class ContributionAmendmentRequest(Document):
    def validate(self):
        """Validate amendment request"""
        # For existing documents, only run essential validations
        # New documents get full validation in before_insert()
        if not self.is_new():
            self.validate_membership_exists()
            self.validate_effective_date()
            self.validate_amount_changes()
            self.set_current_details()
            self.set_default_effective_date()
            self.set_requested_by()

    def validate_membership_exists(self):
        """Ensure membership exists and is active"""
        if not self.membership:
            frappe.throw(_("Membership is required"))

        # Use validation utilities for existence and status checking
        DocumentExistenceValidator.validate_document_exists(
            "Membership", self.membership, "Membership is required for amendment request"
        )

        membership = frappe.get_doc("Membership", self.membership)
        if membership.status not in ["Active", "Inactive"]:
            frappe.throw(_("Can only create amendments for Active or Inactive memberships"))

    def validate_effective_date(self):
        """Validate effective date is today or in the future"""
        if self.effective_date:
            # Use DateRangeValidator for standardized date validation
            if not DateRangeValidator.is_date_today_or_future(self.effective_date):
                frappe.throw(
                    _("Effective date cannot be in the past. Date provided: {0}, Today: {1}").format(
                        getdate(self.effective_date), getdate(today())
                    )
                )

    def validate_amount_changes(self):
        """Validate amount changes are reasonable"""
        # Validate membership type changes
        if self.amendment_type == "Membership Type Change":
            if self.current_membership_type and self.requested_membership_type:
                if self.current_membership_type == self.requested_membership_type:
                    frappe.throw(_("Cannot change to the same membership type"))

        if self.amendment_type == "Fee Change" and self.requested_amount is not None:
            if self.requested_amount <= 0:
                frappe.throw(_("Requested amount must be greater than 0"))

            # Check if amount is significantly different (to avoid accidental changes)
            if self.current_amount and abs(self.requested_amount - self.current_amount) < 0.01:
                frappe.throw(_("Requested amount is the same as current amount"))

            # Check minimum fee enforcement
            if self.membership:
                membership = frappe.get_doc("Membership", self.membership)
                if membership.membership_type:
                    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
                    if not membership_type.dues_schedule_template:
                        frappe.throw(
                            f"Membership Type '{membership_type.name}' must have a dues schedule template"
                        )
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type.dues_schedule_template
                    )
                    # Validate template configuration before proceeding
                    if not template.suggested_amount:
                        frappe.throw(
                            f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured for contribution calculations"
                        )
                    base_amount = template.suggested_amount

                    # Calculate minimum fee (configurable percentage of base or absolute minimum)
                    minimum_fee = max(base_amount * MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE)

                    # Check if member is a student (gets higher minimum percentage)
                    if self.member:
                        member = frappe.get_doc("Member", self.member)
                        if getattr(member, "student_status", 0):
                            minimum_fee = max(
                                base_amount * STUDENT_MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE
                            )

                    if self.requested_amount < minimum_fee:
                        frappe.throw(
                            _("Requested amount is less than minimum fee of €{0}").format(minimum_fee)
                        )

    def validate_no_conflicting_amendments(self):
        """Validate that there are no existing pending amendments for this member"""
        if not self.member or not self.is_new():
            return  # Only check for new documents

        # Check for existing pending amendments (only "Pending Approval" should block new requests)
        existing_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.member,
                "name": ["!=", self.name],  # Exclude current amendment
                "status": ["in", ["Pending Approval"]],  # Only truly pending requests should block
            },
            fields=["name", "status", "requested_amount"],
        )

        if existing_amendments:
            amendment_details = []
            for amendment in existing_amendments:
                amendment_details.append(f"{amendment['name']} ({amendment['status']})")

            frappe.throw(
                _(
                    "Cannot create new amendment. Member {0} has pending amendments: {1}. "
                    "Please wait for approval before creating new ones."
                ).format(self.member, ", ".join(amendment_details))
            )

    def validate_adjustment_frequency(self):
        """Validate that member hasn't exceeded adjustment frequency limits"""
        if not self.member or not self.requested_by_member:
            return  # Only check for member-requested adjustments

        # Get settings
        settings = frappe.get_single("Verenigingen Settings")
        max_adjustments = getattr(settings, "max_fee_adjustments_per_year", 2)

        # Count adjustments in past 365 days (excluding this one if it exists)
        date_365_days_ago = add_days(today(), -365)
        filters = {
            "member": self.member,
            "amendment_type": "Fee Change",
            "creation": [">=", date_365_days_ago],
            "requested_by_member": 1,
        }

        # Exclude current amendment if it already exists
        if not self.is_new():
            filters["name"] = ["!=", self.name]

        adjustments_past_year = frappe.db.count("Contribution Amendment Request", filters=filters)

        if adjustments_past_year >= max_adjustments:
            frappe.throw(
                _(
                    "You have reached the maximum number of fee adjustments ({0}) allowed in a 365-day period"
                ).format(max_adjustments)
            )

    def set_current_details(self):
        """Set current membership details using new dues schedule approach"""
        if not self.membership:
            return

        membership = frappe.get_doc("Membership", self.membership)
        member_doc = frappe.get_doc("Member", self.member)

        # Set current membership type
        self.current_membership_type = membership.membership_type

        # PRIORITY 1: Get current amount from active dues schedule
        repo = DuesScheduleRepository()
        active_dues_schedule = repo.get_active_schedule(self.member)

        if active_dues_schedule:
            self.current_amount = active_dues_schedule.dues_rate
            self.current_billing_interval = active_dues_schedule.billing_frequency or "Monthly"
            self.current_dues_schedule = active_dues_schedule.name
        else:
            # PRIORITY 2: Fall back to legacy fee calculation
            try:
                current_fee = member_doc.get_current_membership_fee()
                self.current_amount = current_fee.get("amount", 0)
            except Exception:
                self.current_amount = (
                    membership.get_billing_amount() if hasattr(membership, "get_billing_amount") else 0
                )

        # Set current billing interval from dues schedule or membership type
        if active_dues_schedule:
            # Already set above from dues schedule
            pass
        elif membership.membership_type:
            # Get billing interval from membership type
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            self.current_billing_interval = getattr(membership_type, "billing_period", "Monthly")
        else:
            self.current_billing_interval = "Monthly"

    def set_default_effective_date(self):
        """Set default effective date to next billing period"""
        if not self.effective_date and self.membership:
            self.effective_date = None
            try:
                # Check if there's an active dues schedule
                repo = DuesScheduleRepository()
                active_dues_schedule = repo.get_active_schedule(
                    self.member, fields=["name", "next_invoice_date"]
                )

                if active_dues_schedule and active_dues_schedule.next_invoice_date:
                    # Set to next billing period, but not in the past
                    next_invoice_date = getdate(active_dues_schedule.next_invoice_date)
                    if next_invoice_date >= today():
                        self.effective_date = next_invoice_date
                    else:
                        # Next invoice date is in the past, use today + 30 days
                        self.effective_date = add_days(today(), 30)
                else:
                    # Fallback to next month
                    self.effective_date = add_days(today(), 30)
            except Exception:
                self.effective_date = add_days(today(), 30)

    def set_requested_by(self):
        """Set requested by to current user"""
        if not self.requested_by:
            self.requested_by = None
            self.requested_by = frappe.session.user

    def _check_respects_minimum_fee(self):
        """
        Check if requested amount respects minimum fee requirements.

        Returns:
            bool: True if requested amount meets minimum fee requirements, False otherwise
        """
        if not self.requested_amount or not self.membership:
            return False

        try:
            membership = frappe.get_doc("Membership", self.membership)
            if not membership.membership_type:
                return True  # No membership type means no minimum to enforce

            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            if not membership_type.dues_schedule_template:
                return True  # No template means no minimum to enforce

            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            if not template.suggested_amount:
                return True  # No suggested amount means no minimum to enforce

            base_amount = template.suggested_amount

            # Calculate minimum fee (configurable percentage of base or absolute minimum)
            minimum_fee = max(base_amount * MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE)

            # Check if member is a student (gets higher minimum percentage)
            if self.member:
                member = frappe.get_doc("Member", self.member)
                if getattr(member, "student_status", 0):
                    minimum_fee = max(base_amount * STUDENT_MINIMUM_FEE_PERCENTAGE, ABSOLUTE_MINIMUM_FEE)

            # CRITICAL: Ensure minimum respects template's minimum_amount and membership type minimum
            # This ensures backend validation matches portal UX
            template_minimum = float(template.minimum_amount or 0)
            membership_type_minimum = float(membership_type.minimum_amount or 0)
            minimum_fee = max(minimum_fee, template_minimum, membership_type_minimum)

            # Return True if requested amount meets or exceeds minimum
            return self.requested_amount >= minimum_fee

        except Exception as e:
            frappe.logger().warning(f"Error checking minimum fee for amendment {self.name}: {str(e)}")
            return False  # If we can't determine minimum, require manual approval

    def before_insert(self):
        """Set approval status for certain cases with enhanced rules"""
        # Run all validations first before determining approval status
        # This prevents auto-approval of invalid requests
        try:
            # Run the same validations as validate() but allow them to raise exceptions
            # that we can handle gracefully for auto-approval decisions
            self.validate_membership_exists()
            self.validate_effective_date()
            self.validate_amount_changes()
            self.validate_no_conflicting_amendments()
            self.validate_adjustment_frequency()  # Always validate frequency here
            self.set_current_details()
            self.set_default_effective_date()
            self.set_requested_by()
        except frappe.ValidationError:
            # If any validation fails, don't auto-approve
            self.status = "Pending Approval"
            self.internal_notes = "Requires manual approval due to validation issues"
            return

        # Enhanced auto-approval logic - only after all validations pass
        if self.amendment_type == "Fee Change" and self.requested_amount and self.current_amount:
            # Check if requested amount respects minimum fee requirements
            respects_minimum = self._check_respects_minimum_fee()

            # AUTO-APPROVE ALL DUES RATE CHANGES that respect minimums
            # regardless of who requests them or whether they're increases/decreases
            if respects_minimum:
                self.status = "Approved"
                self.approved_by = frappe.session.user
                self.approved_date = now_datetime()
                self.internal_notes = "Auto-approved: Dues rate change respects minimum requirements"

            # Otherwise require manual approval
            else:
                self.status = "Pending Approval"
                approval_reason = []
                if not respects_minimum:
                    approval_reason.append("requested amount below minimum fee")

                self.internal_notes = f"Requires approval: {', '.join(approval_reason)}"

        # MEMBERSHIP TYPE CHANGES always require approval
        elif self.amendment_type == "Membership Type Change":
            self.status = "Pending Approval"
            self.internal_notes = "Requires approval: Membership type changes require manual review"

    def after_insert(self):
        """Handle post-insertion tasks"""
        # If this amendment was auto-approved in before_insert, cancel conflicting amendments
        if self.status == "Approved":
            self.cancel_conflicting_amendments()
            self.save()

    def on_update(self):
        """Handle status changes and trigger Mollie sync when applicable.

        When amendment status becomes 'Applied', queues a background job to sync
        the subscription update to Mollie. This ensures the database transaction
        commits before making external API calls, preventing partial state issues.

        The job is deduplicated to prevent multiple sync attempts if the document
        is updated multiple times before the job executes.
        """
        # Check if status just changed to "Applied"
        if self.has_value_changed("status") and self.status == "Applied":
            # Emit event for Mollie subscription sync
            frappe.publish_realtime(
                event="amendment_applied",
                message={
                    "amendment_id": self.name,
                    "membership_id": self.membership,
                    "amendment_type": self.amendment_type,
                    "effective_date": self.effective_date,
                },
                user=frappe.session.user,
            )

            # Only queue job if not already completed or queued
            if not self.mollie_sync_completed and self.mollie_sync_status in ["Not Started", "Failed"]:
                # Check if job already queued/running
                existing_job = frappe.get_all(
                    "RQ Job",
                    filters={"job_name": f"mollie_sync_{self.name}", "status": ["in", ["queued", "started"]]},
                    limit=1,
                )

                if existing_job:
                    frappe.logger().info(f"Mollie sync job already queued for {self.name}")
                    return

                # Update status to Queued before queuing job
                frappe.db.set_value(
                    "Contribution Amendment Request",
                    self.name,
                    "mollie_sync_status",
                    "Queued",
                    update_modified=False,
                )
                frappe.db.commit()

                # Queue background job for Mollie sync
                # This ensures database transaction commits before external API calls
                job_id = f"mollie_sync_{self.name}"
                frappe.enqueue(
                    "verenigingen.integrations.mollie.events.amendment_events.sync_mollie_subscription_on_amendment_applied",
                    queue="default",
                    timeout=60,
                    doc=self,
                    is_async=True,
                    job_name=job_id,
                    job_id=job_id,
                    deduplicate=True,
                    enqueue_after_commit=True,
                )

    def handle_mollie_sync_failure(self, error_message):
        """Handle Mollie sync failure notification.

        Called when background sync job fails. Updates status and notifies administrators.

        Args:
            error_message: Error message from failed sync operation
        """
        frappe.logger().error(f"Mollie sync failed for amendment {self.name}: {error_message}")

        # Update status to Failed
        frappe.db.set_value(
            "Contribution Amendment Request", self.name, "mollie_sync_status", "Failed", update_modified=False
        )
        frappe.db.commit()

        # Log error for tracking
        frappe.log_error(
            title=f"Mollie Sync Failed: {self.name}",
            message=f"Failed to sync amendment {self.name} to Mollie.\n\nError: {error_message}",
        )

        # Notify administrators using EmailService template
        try:
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()

            # Get administrator emails
            admin_roles = ["System Manager", "Verenigingen Administrator"]
            admin_emails = frappe.get_all(
                "Has Role",
                filters={"role": ["in", admin_roles], "parenttype": "User"},
                fields=["parent"],
                distinct=True,
            )

            recipients = [admin["parent"] for admin in admin_emails]

            if recipients:
                # Get member details for notification
                membership = frappe.get_doc("Membership", self.membership)
                member = frappe.get_doc("Member", membership.member)

                result = email_service.send_templated_email(
                    template_name="mollie_sync_failed",
                    recipients=recipients,
                    context={
                        "amendment_id": self.name,
                        "amendment_type": self.amendment_type,
                        "member_name": member.full_name,
                        "member_id": member.name,
                        "requested_amount": (
                            frappe.format_value(self.requested_amount, "Currency")
                            if self.requested_amount
                            else None
                        ),
                        "error_message": error_message,
                        "amendment_link": frappe.utils.get_url()
                        + "/app/contribution-amendment-request/"
                        + self.name,
                        "timestamp": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    reference_doctype="Contribution Amendment Request",
                    reference_name=self.name,
                )

                if result.get("success"):
                    frappe.logger().info(f"Sent failure notification to {len(recipients)} administrators")
                else:
                    frappe.log_error(
                        f"Failed to send Mollie sync failure notification: {result.get('message')}",
                        "Mollie Sync Notification Error",
                    )

        except Exception as email_error:
            frappe.log_error(
                f"Failed to send Mollie sync failure notification: {str(email_error)}",
                "Mollie Sync Notification Error",
            )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def approve_amendment(self, approval_notes=None):
        """
        Approve the amendment request.

        Args:
            approval_notes (str, optional): Notes to add to the approval for audit trail

        Raises:
            frappe.ValidationError: If amendment is not in "Pending Approval" status
        """
        if self.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be approved"))

        # Cancel any other pending or approved amendments for the same member
        self.cancel_conflicting_amendments()

        self.status = "Approved"
        self.approved_by = frappe.session.user
        self.approved_date = now_datetime()

        if approval_notes:
            self.internal_notes = (self.internal_notes or "") + f"\nApproval Notes: {approval_notes}"

        self.save()
        frappe.msgprint(_("Amendment approved successfully"))

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def reject_amendment(self, rejection_reason):
        """
        Reject the amendment request.

        Args:
            rejection_reason (str): Required reason for rejection (stored for audit trail)

        Raises:
            frappe.ValidationError: If amendment is not in "Pending Approval" status
        """
        if self.status != "Pending Approval":
            frappe.throw(_("Only pending amendments can be rejected"))

        self.status = "Rejected"
        self.rejection_reason = rejection_reason
        self.save()

        # Notify the requester
        self.send_rejection_notification()
        frappe.msgprint(_("Amendment rejected"))

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL, self_service_only=True)
    def apply_amendment(self):
        """
        Apply the approved amendment to the membership and dues schedule.

        This method:
        1. Validates the amendment is approved and ready to apply
        2. Updates the member's dues schedule with the new amount
        3. Updates legacy override fields for backward compatibility
        4. Marks the amendment as "Applied" with timestamp

        Returns:
            dict: Operation result with status ("success", "error", "warning") and message

        Raises:
            frappe.ValidationError: If amendment is not approved or other validation fails
        """
        if self.status != "Approved":
            frappe.msgprint(_("Only approved amendments can be applied"), indicator="red")
            return {"status": "error", "message": "Amendment not approved"}

        # For auto-approved amendments or those with effective date today/past, apply immediately
        # For future-dated amendments, only apply if explicitly requested or past effective date
        if DateRangeValidator.is_date_in_future(self.effective_date):
            # Check if this is being called automatically (e.g., by submit_fee_adjustment_request)
            # or manually by a user
            if not getattr(self, "_force_apply", False):
                effective_date_formatted = frappe.utils.formatdate(self.effective_date)
                frappe.msgprint(
                    _(
                        "This amendment is scheduled to be applied automatically on {0}. You cannot apply it manually before the effective date."
                    ).format(effective_date_formatted),
                    title=_("Amendment Not Ready"),
                    indicator="orange",
                )
                return {"status": "warning", "message": "Amendment scheduled for future date"}

        try:
            membership = frappe.get_doc("Membership", self.membership)

            if self.amendment_type == "Fee Change":
                self.apply_fee_change(membership)
            elif self.amendment_type == "Billing Interval Change":
                self.apply_billing_change(membership)
            elif self.amendment_type == "Membership Type Change":
                self.apply_membership_type_change(membership)

            self.status = "Applied"
            self.applied_date = now_datetime()
            self.applied_by = frappe.session.user
            self.save()

            frappe.msgprint(_("Amendment applied successfully"), indicator="green")
            return {"status": "success", "message": "Amendment applied successfully"}

        except Exception as e:
            # Use structured error logging
            error_info = format_error_for_logging(e, f"Amendment {self.name} application")

            frappe.logger().error(f"Error applying amendment {self.name}", extra=error_info)

            # Show user-friendly message
            user_message = error_info["error_message"]
            if error_info["full_error_logged"]:
                user_message += "... (see logs for full details)"

            frappe.msgprint(_("Error applying amendment: {0}").format(user_message), indicator="red")
            return {"status": "error", "message": f"Error applying amendment: {user_message}"}

    def apply_fee_change(self, membership):
        """Apply fee change to membership"""
        try:
            # IDEMPOTENCY CHECK: Skip if member's current dues_rate already matches requested amount
            member_doc = frappe.get_doc("Member", self.member)
            current_rate = getattr(member_doc, "dues_rate", 0) or 0

            if current_rate == self.requested_amount:
                frappe.logger().info(
                    f"Amendment {self.name} already applied - member {self.member} dues_rate "
                    f"already matches requested amount €{self.requested_amount}"
                )
                self.processing_notes = (
                    f"Skipped: Member dues_rate already set to €{self.requested_amount} "
                    f"(amendment appears to have been applied previously)"
                )
                return  # Skip re-application

            # Check if this is a pure fee change (no membership type change)
            is_pure_fee_change = self.amendment_type == "Fee Change" and (
                not self.requested_membership_type
                or self.requested_membership_type == self.current_membership_type
            )

            if is_pure_fee_change:
                # For pure fee changes, just update the existing dues schedule
                # Use the current_dues_schedule field that was populated during set_current_details()
                if self.current_dues_schedule:
                    existing_schedule = self.current_dues_schedule
                    # Update the existing schedule
                    schedule_doc = frappe.get_doc("Membership Dues Schedule", existing_schedule)
                    schedule_doc.dues_rate = self.requested_amount
                    schedule_doc.contribution_mode = "Custom"
                    schedule_doc.uses_custom_amount = 1
                    schedule_doc.custom_amount_approved = 1
                    schedule_doc.custom_amount_reason = f"Amendment Request: {self.reason}"
                    schedule_doc.custom_amount_approved_by = frappe.session.user
                    schedule_doc.custom_amount_approved_date = today()

                    # Add amendment note
                    schedule_doc.notes = (
                        schedule_doc.notes or ""
                    ) + f"\nAmended via {self.name} on {today()}: €{self.requested_amount:.2f}"

                    # CRITICAL FIX: Set flag to bypass duplicate schedule validation
                    # This is necessary because we're updating the existing schedule, not creating a duplicate
                    schedule_doc.flags.from_amendment = True

                    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation

                    schedule_result = secure_document_operation(
                        operation="save",
                        doc=schedule_doc,
                        justification=f"Apply fee change amendment {self.name} to dues schedule",
                        required_permissions=["Membership Dues Schedule:write"],
                    )

                    if not schedule_result.success:
                        frappe.logger().error(
                            f"Failed to apply fee change to schedule: {'; '.join(schedule_result.errors)}"
                        )
                        frappe.throw(
                            _("Failed to apply fee change to schedule: {0}").format(
                                "; ".join(schedule_result.errors)
                            )
                        )

                    # Add comment
                    schedule_doc.add_comment(
                        text=f"Fee adjusted via amendment {self.name}. New amount: €{self.requested_amount:.2f}"
                    )

                    self.new_dues_schedule = existing_schedule
                    self.processing_notes = (
                        f"Updated existing dues schedule {existing_schedule} with new fee amount."
                    )
                else:
                    # SHOULD NEVER HAPPEN: Member has no dues schedule at all
                    # This indicates a data integrity issue - member has active membership but no schedule
                    frappe.throw(
                        _(
                            "Cannot apply fee change: Member {0} has no active dues schedule. "
                            "Please create a dues schedule first or contact system administrator."
                        ).format(self.member)
                    )
            else:
                # For membership type changes or other complex changes, create new schedule
                dues_schedule_name = self.create_dues_schedule_for_amendment()
                self.new_dues_schedule = dues_schedule_name
                self.processing_notes = f"Dues schedule {dues_schedule_name} created for amendment."

            # Update legacy override fields for backward compatibility
            # Re-use member_doc from idempotency check above

            # CRITICAL: Capture old rate BEFORE reload to ensure accurate history
            # The reload() may pick up intermediate changes, giving us wrong "old" values
            actual_current_rate = getattr(member_doc, "dues_rate", 0) or 0

            member_doc.reload()  # Refresh to avoid timestamp mismatch

            # Record fee change in history before updating
            # Using pre-reload actual_current_rate ensures we log the true previous value
            dues_schedule_ref = self.new_dues_schedule or (
                dues_schedule_name if "dues_schedule_name" in locals() else ""
            )
            member_doc.record_fee_change(
                {
                    "change_date": now_datetime(),
                    "old_amount": actual_current_rate,  # Use pre-reload current rate
                    "new_amount": self.requested_amount,
                    "reason": f"Amendment {self.name}: {self.reason}",
                    "changed_by": frappe.session.user,
                    "dues_schedule_name": dues_schedule_ref,
                    "dues_schedule_action": f"Applied via {dues_schedule_ref}",
                    "amendment_request_name": self.name,  # For true idempotency
                }
            )

            member_doc.dues_rate = self.requested_amount
            member_doc.fee_override_reason = f"Amendment: {self.reason}"
            member_doc.fee_override_date = today()
            member_doc.fee_override_by = frappe.session.user
            # Set flag to bypass permission check for system updates
            member_doc._system_update = True
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            # using secure_document_operation from top-level import

            member_result = secure_document_operation(
                operation="save",
                doc=member_doc,
                justification=f"Apply fee override from amendment {self.name}",
                required_permissions=["Member:write"],
            )

            if not member_result.success:
                frappe.logger().error(
                    f"Failed to apply fee override to member: {'; '.join(member_result.errors)}"
                )
                frappe.throw(
                    _("Failed to apply fee override to member: {0}").format("; ".join(member_result.errors))
                )

        except Exception as e:
            frappe.throw(_("Error applying fee change: {0}").format(str(e)))

    def create_dues_schedule_for_amendment(self):
        """Create a new dues schedule for this amendment"""
        try:
            # Get current active membership
            membership = frappe.db.get_value(
                "Membership",
                {"member": self.member, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )

            if not membership:
                frappe.throw(_("No active membership found for creating dues schedule"))

            # Deactivate existing active or paused dues schedule
            repo = DuesScheduleRepository()
            existing_schedule_info = repo.get_active_or_paused_schedule(self.member, fields=["name"])

            if existing_schedule_info:
                cancel_result = repo.cancel_schedule(
                    existing_schedule_info.name,
                    f"Cancelled and replaced by amendment {self.name}: €{self.requested_amount:.2f}",
                )
                if not cancel_result.success:
                    error_details = "; ".join(cancel_result.errors)
                    frappe.throw(
                        _("Failed to cancel dues schedule {0} during amendment {1}: {2}").format(
                            existing_schedule_info.name, self.name, error_details
                        )
                    )

                frappe.logger().info(
                    f"Cancelled schedule {existing_schedule_info.name}, proceeding to create new one"
                )

            # Create new dues schedule
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.flags.from_amendment = True  # Flag to skip duplicate schedule check
            dues_schedule.schedule_name = f"Amendment {self.name} - {frappe.utils.random_string(6)}"
            dues_schedule.member = self.member
            dues_schedule.membership = membership.name
            # Use requested membership type if this is a membership type change, otherwise use current
            if self.amendment_type == "Membership Type Change" and self.requested_membership_type:
                dues_schedule.membership_type = self.requested_membership_type
            else:
                dues_schedule.membership_type = membership.membership_type
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = self.requested_amount
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_approved = 1  # Amendment already approved
            dues_schedule.custom_amount_reason = f"Amendment Request: {self.reason}"

            # Handle zero amounts specially
            if not self.requested_amount:
                dues_schedule.custom_amount_reason = f"Free membership via amendment: {self.reason}"

            # Get billing frequency from membership type's template
            # Use requested membership type if this is a membership type change
            membership_type_to_use = (
                self.requested_membership_type
                if self.amendment_type == "Membership Type Change" and self.requested_membership_type
                else membership.membership_type
            )

            if membership_type_to_use:
                membership_type_doc = frappe.get_doc("Membership Type", membership_type_to_use)
                if membership_type_doc.dues_schedule_template:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    dues_schedule.billing_frequency = template.billing_frequency
                else:
                    # Fallback to membership type's billing period
                    billing_period_map = {
                        "Daily": "Daily",
                        "Monthly": "Monthly",
                        "Quarterly": "Quarterly",
                        "Biannual": "Semi-Annual",
                        "Annual": "Annual",
                        "Custom": "Custom",
                    }
                    dues_schedule.billing_frequency = billing_period_map.get(
                        membership_type_doc.billing_period, "Annual"
                    )
                    # Handle custom frequency
                    if membership_type_doc.billing_period == "Custom" and hasattr(
                        membership_type_doc, "billing_period_in_months"
                    ):
                        dues_schedule.custom_frequency_number = membership_type_doc.billing_period_in_months
                        dues_schedule.custom_frequency_unit = "Months"
            else:
                dues_schedule.billing_frequency = "Monthly"  # Default fallback
            # Payment method is determined dynamically based on member's payment setup
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 1
            dues_schedule.test_mode = 0
            dues_schedule.effective_date = self.effective_date or today()
            dues_schedule.next_invoice_date = self.effective_date or today()

            # Add amendment metadata in notes
            dues_schedule.notes = (
                f"Created from amendment request {self.name} by {frappe.session.user} on {today()}"
            )

            # Create new dues schedule with proper security validation
            # using secure_document_operation from top-level import

            create_result = secure_document_operation(
                operation="save",
                doc=dues_schedule,
                justification=f"Create new dues schedule for amendment {self.name} - Rate: €{self.requested_amount:.2f}",
                required_permissions=["Membership Dues Schedule:create"],
            )
            if not create_result.success:
                error_details = "; ".join(create_result.errors)
                frappe.throw(
                    _("Failed to create dues schedule for amendment {0} with rate €{1}: {2}").format(
                        self.name, self.requested_amount, error_details
                    )
                )

            # Add comment about the amendment
            dues_schedule.add_comment(
                text=f"Created from amendment request {self.name}. Amount: €{self.requested_amount:.2f}. Reason: {self.reason}"
            )

            return dues_schedule.name

        except Exception as e:
            frappe.log_error(
                f"Error creating dues schedule for amendment: {str(e)}", "Amendment Dues Schedule Error"
            )
            frappe.throw(_("Error creating dues schedule: {0}").format(str(e)))

    def apply_billing_change(self, membership):
        """Apply billing interval change"""
        # This would involve creating a new dues schedule with different billing interval
        # Implementation depends on specific requirements
        frappe.throw(_("Billing interval changes are not yet implemented"))

    def apply_membership_type_change(self, membership):
        """Apply membership type change with optional fee change"""
        try:
            # Update the membership type
            membership.membership_type = self.requested_membership_type
            membership.save()

            # Cancel existing dues schedule and create new one with proper billing frequency
            repo = DuesScheduleRepository()
            existing_schedule_info = repo.get_active_or_paused_schedule(self.member, fields=["name"])

            if existing_schedule_info:
                cancel_result = repo.cancel_schedule(
                    existing_schedule_info.name,
                    f"Cancelled due to membership type change via amendment {self.name}",
                )
                if not cancel_result.success:
                    frappe.throw(
                        _("Failed to cancel existing dues schedule: {0}").format(
                            "; ".join(cancel_result.errors)
                        )
                    )

            # Create new dues schedule with new membership type settings
            dues_schedule_name = self.create_dues_schedule_for_amendment()
            self.new_dues_schedule = dues_schedule_name

            # Update legacy override fields if there's also a fee change
            if self.requested_amount:
                member_doc = frappe.get_doc("Member", self.member)
                member_doc.reload()

                # CRITICAL FIX: Use actual current member dues_rate, not amendment's stored current_amount
                actual_current_rate = getattr(member_doc, "dues_rate", 0) or 0

                # Record fee change in history before updating
                member_doc.record_fee_change(
                    {
                        "change_date": now_datetime(),
                        "old_amount": actual_current_rate,  # Use actual current rate, not stored value
                        "new_amount": self.requested_amount,
                        "reason": f"Membership type change amendment {self.name}: {self.reason}",
                        "changed_by": frappe.session.user,
                        "dues_schedule_action": f"Applied via {dues_schedule_name}",
                        "amendment_request_name": self.name,  # For true idempotency
                    }
                )

                member_doc.dues_rate = self.requested_amount
                member_doc.fee_override_reason = f"Amendment: {self.reason}"
                member_doc.fee_override_date = today()
                member_doc.fee_override_by = frappe.session.user
                member_doc._system_update = True
                member_result = secure_document_operation(
                    operation="save",
                    doc=member_doc,
                    justification=f"Update member fee override for membership type change amendment {self.name}",
                    required_permissions=["Member:write"],
                )
                if not member_result.success:
                    frappe.throw(
                        _("Failed to update member fee override: {0}").format("; ".join(member_result.errors))
                    )

            self.processing_notes = f"Membership type changed to {self.requested_membership_type}. New dues schedule {dues_schedule_name} created."

        except Exception as e:
            frappe.throw(_("Error applying membership type change: {0}").format(str(e)))

    def cancel_conflicting_amendments(self):
        """Cancel conflicting amendments - only those that haven't taken effect yet"""
        if not self.member:
            return

        # Find amendments that conflict with this one:
        # 1. Pending Approval - always conflicts
        # 2. Approved but with future effective dates - conflicts
        # 3. Approved with past/today effective dates should already be Applied
        conflicting_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.member,
                "name": ["!=", self.name],  # Exclude current amendment
                "status": ["in", ["Pending Approval", "Approved"]],
            },
            fields=["name", "status", "requested_amount", "effective_date"],
        )

        cancelled_count = 0
        for amendment_data in conflicting_amendments:
            try:
                # Only cancel if it hasn't taken effect yet
                should_cancel = False

                if amendment_data.status == "Pending Approval":
                    # Always cancel pending amendments
                    should_cancel = True
                elif amendment_data.status == "Approved":
                    # Only cancel approved amendments with future effective dates
                    if amendment_data.effective_date and DateRangeValidator.is_date_in_future(
                        amendment_data.effective_date
                    ):
                        should_cancel = True
                    elif not amendment_data.effective_date:
                        # No effective date set, treat as immediate - should be applied already
                        # Log this as a potential issue but don't cancel
                        frappe.logger().warning(
                            f"Approved amendment {amendment_data.name} has no effective date"
                        )
                        should_cancel = False

                if should_cancel:
                    amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)

                    # Add cancellation note
                    cancellation_note = f"Cancelled due to approval of newer amendment {self.name}"
                    amendment.internal_notes = (amendment.internal_notes or "") + f"\n{cancellation_note}"

                    # Set status to cancelled
                    amendment.status = "Cancelled"
                    amendment.flags.ignore_validate_update_after_submit = True
                    amendment.save()

                    cancelled_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Error cancelling conflicting amendment {amendment_data.name}: {str(e)}",
                    "Amendment Cancellation Error",
                )

        if cancelled_count > 0:
            self.internal_notes = (
                self.internal_notes or ""
            ) + f"\nCancelled {cancelled_count} conflicting amendment(s) upon approval"
            frappe.logger().info(
                f"Cancelled {cancelled_count} conflicting amendments for member {self.member}"
            )

    def send_rejection_notification(self):
        """Send notification to requester about rejection using EmailService template"""
        if not self.requested_by:
            return

        try:
            from verenigingen.services.communication.email_service import get_email_service

            # Get member details for personalization
            membership = frappe.get_doc("Membership", self.membership)
            member = frappe.get_doc("Member", membership.member)

            email_service = get_email_service()
            result = email_service.send_templated_email(
                template_name="amendment_rejected",
                recipients=[self.requested_by],
                context={
                    "member_name": member.full_name,
                    "amendment_id": self.name,
                    "amendment_type": self.amendment_type or "N/A",
                    "requested_amount": (
                        frappe.format_value(self.requested_amount, "Currency")
                        if self.requested_amount
                        else None
                    ),
                    "rejection_reason": self.rejection_reason or "No reason provided",
                    "portal_link": frappe.utils.get_url()
                    + "/app/contribution-amendment-request/"
                    + self.name,
                    "current_year": frappe.utils.now_datetime().year,
                },
                reference_doctype="Contribution Amendment Request",
                reference_name=self.name,
            )

            if not result.get("success"):
                frappe.log_error(
                    f"Failed to send rejection notification: {result.get('message')}",
                    "Amendment Rejection Email Error",
                )
        except Exception as e:
            frappe.log_error(f"Error sending rejection notification: {str(e)}")

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def get_impact_preview(self):
        """
        Generate a preview of the financial impact of this amendment.

        Calculates the difference between current and requested amounts,
        including annual impact based on billing frequency.

        Returns:
            dict: Contains "html" key with formatted impact preview HTML,
                  or error message if preview cannot be generated
        """
        if not self.membership or self.amendment_type != "Fee Change":
            return {"html": "<p>No preview available</p>"}

        try:
            # Use the current_amount that was already populated from the actual dues schedule
            # Don't rely on membership.get_billing_amount() which might be outdated
            current_amount = self.current_amount or 0
            new_amount = self.requested_amount or current_amount

            difference = new_amount - current_amount
            percentage_change = (difference / current_amount * 100) if current_amount > 0 else 0

            impact_class = (
                "text-success" if difference > 0 else "text-danger" if difference < 0 else "text-muted"
            )
            impact_text = "increase" if difference > 0 else "decrease" if difference < 0 else "no change"

            # Get billing interval information from dues schedule or membership type
            billing_interval_display = "per month"  # Default
            annual_multiplier = 12  # Default fallback for monthly

            # Try to get billing interval from current dues schedule
            if self.current_dues_schedule:
                try:
                    dues_schedule = frappe.get_doc("Membership Dues Schedule", self.current_dues_schedule)
                    billing_frequency = getattr(dues_schedule, "billing_frequency", "Monthly")

                    # Map billing frequency to display text and multiplier
                    freq_mapping = {
                        "Monthly": ("per month", 12.0),
                        "Quarterly": ("per quarter", 4.0),
                        "Annual": ("per year", 1.0),
                        "Biannual": ("per 6 months", 2.0),
                        "Weekly": ("per week", 52.0),
                        "Daily": ("per day", 365.0),
                    }

                    if billing_frequency in freq_mapping:
                        billing_interval_display, annual_multiplier = freq_mapping[billing_frequency]
                    else:
                        billing_interval_display = f"per {billing_frequency.lower()}"
                        annual_multiplier = 12.0  # Default fallback

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from dues schedule: {str(e)}")

            # If no dues schedule, try membership type
            elif self.membership:
                try:
                    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
                    billing_period = getattr(membership_type, "billing_period", "Monthly")

                    # Map billing period to display text and multiplier
                    period_mapping = {
                        "Monthly": ("per month", 12.0),
                        "Quarterly": ("per quarter", 4.0),
                        "Annual": ("per year", 1.0),
                        "Biannual": ("per 6 months", 2.0),
                        "Weekly": ("per week", 52.0),
                        "Daily": ("per day", 365.0),
                        "Lifetime": ("lifetime", 1.0),
                    }

                    if billing_period in period_mapping:
                        billing_interval_display, annual_multiplier = period_mapping[billing_period]
                    else:
                        billing_interval_display = f"per {billing_period.lower()}"
                        annual_multiplier = 12.0  # Default fallback

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from membership type: {str(e)}")

            # If all parsing failed, keep defaults
            # (billing_interval_display = "per month", annual_multiplier = 12)

            # Calculate annual impact based on proper billing interval
            # Use round() to avoid floating point precision issues in HTML
            annual_difference = round(difference * annual_multiplier, 2)

            # Format currency values safely
            current_amount_formatted = frappe.format_value(current_amount, "Currency")
            new_amount_formatted = frappe.format_value(new_amount, "Currency")
            difference_formatted = frappe.format_value(abs(difference), "Currency")
            annual_difference_formatted = frappe.format_value(annual_difference, "Currency")

            # Format effective date safely
            effective_date_str = (
                frappe.utils.formatdate(self.effective_date) if self.effective_date else "Not set"
            )

            # Clean billing interval for display
            billing_display_clean = billing_interval_display.replace("per ", "").title()

            # Debug info removed - issue resolved

            html = f"""
            <div class="amendment-impact">
                <h5>Amendment Impact Preview</h5>

                <div class="row">
                    <div class="col-md-6">
                        <h6>Current</h6>
                        <p><strong>{current_amount_formatted}</strong> {billing_interval_display}</p>
                    </div>
                    <div class="col-md-6">
                        <h6>After Amendment</h6>
                        <p><strong>{new_amount_formatted}</strong> {billing_interval_display}</p>
                    </div>
                </div>

                <div class="alert alert-info">
                    <h6 class="{impact_class}">
                        {difference_formatted} {impact_text}
                        ({percentage_change:+.1f}%)
                    </h6>
                    <p>Annual impact: <strong class="{impact_class}">{annual_difference_formatted}</strong></p>
                </div>

                <div class="small text-muted">
                    <p><strong>Effective Date:</strong> {effective_date_str}</p>
                    <p><strong>Billing Interval:</strong> {billing_display_clean}</p>
                    <p><strong>Next Billing:</strong> New amount will apply from the next billing period</p>
                </div>
            </div>
            """

            return {"html": html}

        except Exception as e:
            return {"html": f"<p class='text-danger'>Error generating preview: {str(e)}</p>"}


# Module-level functions for scheduled tasks and API calls


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_pending_amendments():
    """Hourly scheduled task to process approved amendments that are ready to be applied"""
    try:
        # Get all approved amendments with effective date today or earlier
        # CRITICAL FIX: Only process amendments that haven't been applied yet
        amendments_to_process = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "status": "Approved",
                "effective_date": ["<=", today()],
                "applied_date": ["is", "not set"],  # Only process unapplied amendments
            },
            fields=["name", "effective_date", "member", "requested_amount"],
            order_by="creation asc",  # CRITICAL: Process amendments in chronological order
        )

        processed_count = 0
        error_count = 0

        for amendment_data in amendments_to_process:
            try:
                amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)

                # SAFETY CHECK: Skip if already applied (in case filter didn't catch it)
                if amendment.status == "Applied" or amendment.applied_date:
                    frappe.logger().info(
                        f"Skipping amendment {amendment.name} - already applied "
                        f"(status: {amendment.status}, applied_date: {amendment.applied_date})"
                    )
                    continue

                # Force apply even if effective date is future (since we filtered for ready ones)
                amendment._force_apply = True
                result = amendment.apply_amendment()

                if result.get("status") == "success":
                    processed_count += 1
                    frappe.logger().info(
                        "Applied amendment %s for member %s", amendment.name, amendment.member
                    )
                else:
                    error_count += 1
                    # CRITICAL FIX: Mark failed amendments properly to prevent reprocessing
                    amendment.status = "Failed"
                    amendment.internal_notes = (
                        amendment.internal_notes or ""
                    ) + f"\nScheduled processing failed: {result.get('message', 'Unknown error')}"
                    amendment.save()

                    # Use structured error logging for failed amendments
                    result_message = result.get("message", "Unknown error")
                    error_info = format_error_for_logging(
                        result_message, f"Daily processing of amendment {amendment.name}"
                    )

                    frappe.logger().error(f"Failed to apply amendment {amendment.name}", extra=error_info)

            except Exception as e:
                error_count += 1
                # CRITICAL FIX: Mark failed amendments properly to prevent reprocessing
                try:
                    amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)
                    amendment.status = "Failed"
                    amendment.internal_notes = (
                        amendment.internal_notes or ""
                    ) + f"\nScheduled processing exception: {str(e)[:200]}"
                    amendment.save()
                except Exception as save_error:
                    frappe.logger().error(
                        f"Could not update failed amendment {amendment_data.name}: {save_error}"
                    )

                # Use structured error logging for processing exceptions
                error_info = format_error_for_logging(
                    e, f"Daily processing of amendment {amendment_data.name}"
                )
                frappe.logger().error(f"Error processing amendment {amendment_data.name}", extra=error_info)

        # Log summary
        if processed_count > 0 or error_count > 0:
            frappe.logger().info(
                f"Amendment processing complete: {processed_count} applied, {error_count} errors"
            )

        return {
            "success": True,
            "processed": processed_count,
            "errors": error_count,
            "message": f"Processed {processed_count} amendments with {error_count} errors",
        }

    except Exception as e:
        # Use structured error logging for scheduled processing failures
        error_info = format_error_for_logging(e, "Scheduled amendment processing")
        frappe.logger().error("Error in scheduled amendment processing", extra=error_info)
        return {"success": False, "error": error_info["error_message"]}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_fee_change_amendment(member_name, new_amount, reason, effective_date=None):
    """
    Create a fee change amendment for a member.

    Args:
        member_name (str): Name/ID of the member to create amendment for
        new_amount (float): New requested dues amount
        reason (str): Reason for the fee change (required for audit trail)
        effective_date (str, optional): Date when change should take effect.
                                       If not provided, defaults to next billing period

    Returns:
        ContributionAmendmentRequest: The created amendment document

    Raises:
        frappe.ValidationError: If member has no active membership
    """
    member = frappe.get_doc("Member", member_name)

    # Get current active membership using service
    from verenigingen.services.member.core.member_membership_service import get_member_membership_service

    membership = get_member_membership_service().get_active_membership(member_name)
    if not membership:
        frappe.throw(_("No active membership found for this member"))

    # Set default effective date if not provided
    if not effective_date:
        # Default to next billing period or next month
        try:
            # Check if there's an active dues schedule
            repo = DuesScheduleRepository()
            active_dues_schedule = repo.get_active_schedule(member.name, fields=["next_invoice_date"])

            if active_dues_schedule and active_dues_schedule.next_invoice_date:
                effective_date = active_dues_schedule.next_invoice_date
            else:
                effective_date = add_days(today(), 30)
        except Exception:
            effective_date = add_days(today(), 30)

    # Create amendment request
    amendment = frappe.get_doc(
        {
            "doctype": "Contribution Amendment Request",
            "membership": membership.name,
            "member": member.name,
            "amendment_type": "Fee Change",
            "requested_amount": new_amount,
            "reason": reason,
            "effective_date": effective_date,
            "status": "Draft",
        }
    )

    amendment.insert()

    # Auto-approve if it's a fee increase by the member themselves
    if (
        amendment.current_amount
        and new_amount > amendment.current_amount
        and frappe.session.user == member.user
    ):
        amendment.approve_amendment("Auto-approved fee increase by member")

    return amendment


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_pending_contribution_amendments(member_name):
    """
    Get all pending contribution amendments for a member.

    Retrieves amendments in Draft, Pending Approval, or Approved status.
    Filters out approved amendments that have passed their effective date.

    Args:
        member_name (str): Name/ID of the member to get amendments for

    Returns:
        list[dict]: List of amendment records with fields:
                   - name: Amendment ID
                   - amendment_type: Type of amendment
                   - status: Current status
                   - requested_amount: Requested amount
                   - effective_date: When amendment takes effect
                   - reason: Reason for amendment
    """
    # using getdate, today from top-level import

    amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "amendment_type", "status", "requested_amount", "effective_date", "reason"],
        order_by="creation desc",
    )

    # Filter out approved amendments that have passed their effective date
    filtered_amendments = []
    for amendment in amendments:
        # Always show Draft and Pending Approval amendments
        if amendment.status in ["Draft", "Pending Approval"]:
            filtered_amendments.append(amendment)
        # For Approved amendments, only show if effective date hasn't passed
        elif amendment.status == "Approved" and amendment.effective_date:
            if DateRangeValidator.is_date_today_or_future(amendment.effective_date):
                filtered_amendments.append(amendment)
        # For Approved amendments without effective date, show them (edge case)
        elif amendment.status == "Approved" and not amendment.effective_date:
            filtered_amendments.append(amendment)

    return filtered_amendments
