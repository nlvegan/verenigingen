import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    self_service_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator, DocumentExistenceValidator

# Configuration Constants
MINIMUM_FEE_PERCENTAGE = 0.3  # 30% of base amount
STUDENT_MINIMUM_FEE_PERCENTAGE = 0.5  # 50% of base amount for students
ABSOLUTE_MINIMUM_FEE = 5.0  # EUR 5 absolute minimum
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
                    template = load_template_for_membership_type(membership_type)
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
                            _("Requested amount is less than minimum fee of EUR{0}").format(minimum_fee)
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
            # Get billing interval from membership type (billing_period is optional)
            membership_type = frappe.get_doc("Membership Type", membership.membership_type)
            self.current_billing_interval = getattr(membership_type, "billing_period", None) or "Monthly"
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

    def set_requested_date(self):
        """Default the request date to today when not provided.

        Mirrors the field's "Today" default for documents created via
        frappe.get_doc({...}), which does not apply field defaults.
        """
        if not self.requested_date:
            self.requested_date = today()

    def before_insert(self):
        """Set approval status for certain cases with enhanced rules"""
        # requested_date is a reqd field with a "Today" default, but that default
        # is only applied by frappe.new_doc(); documents built via
        # frappe.get_doc({...}) (the common API/test path) skip it and would fail
        # mandatory validation. Set it unconditionally and before the validation
        # try-block so it is populated on every creation path.
        self.set_requested_date()

        # Hard business-rule validations: these MUST block creation when they
        # fail, so let their frappe.throw propagate. (Previously they were wrapped
        # in a try/except that swallowed every ValidationError and silently
        # downgraded the request to "Pending Approval" — which defeated conflict
        # detection: a second pending amendment for the same member was created
        # instead of being rejected.)
        self.validate_membership_exists()
        self.validate_effective_date()
        self.validate_amount_changes()
        self.validate_no_conflicting_amendments()
        self.validate_adjustment_frequency()

        # Detail population for the auto-approval decision. If any of these can't
        # be determined, fall back to manual approval rather than auto-approving.
        try:
            self.set_current_details()
            self.set_default_effective_date()
            self.set_requested_by()

            from verenigingen.services.approval import ContributionAmendmentApprovalService

            approval_service = ContributionAmendmentApprovalService(self)
            approval_service.set_auto_approval_status()
        except frappe.ValidationError:
            # Could not determine details/auto-approval; require manual review.
            self.status = "Pending Approval"
            self.internal_notes = "Requires manual approval due to validation issues"

    def after_insert(self):
        """Handle post-insertion tasks"""
        # If this amendment was auto-approved in before_insert, cancel conflicting amendments
        if self.status == "Approved":
            from verenigingen.services.approval import ContributionAmendmentApprovalService

            approval_service = ContributionAmendmentApprovalService(self)
            approval_service.cancel_conflicting_amendments()
            self.save()

    def on_update(self):
        """Handle status changes and trigger Mollie sync when applicable.

        When amendment status becomes 'Applied', queues a background job to sync
        the subscription update to Mollie. This ensures the database transaction
        commits before making external API calls, preventing partial state issues.
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
                job_id = f"mollie_sync_{self.name}"
                frappe.enqueue(
                    "verenigingen.verenigingen_payments.mollie.events.amendment_events.sync_mollie_subscription_on_amendment_applied",
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
            admin_roles = Roles.ADMIN_PAIR
            admin_emails = frappe.get_all(
                "Has Role",
                filters={"role": ["in", list(admin_roles)], "parenttype": "User"},
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
                    notification_key="contribution_sync_failed",
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
        """Approve the amendment request - delegates to service."""
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        approval_service.approve_amendment(approval_notes)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def reject_amendment(self, rejection_reason):
        """Reject the amendment request - delegates to service."""
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        approval_service.reject_amendment(rejection_reason)

    @frappe.whitelist()
    @self_service_api(operation_type=OperationType.FINANCIAL)
    def apply_amendment(self):
        """Apply the approved amendment - delegates to service.

        Self-service: a member may apply their own approved amendment.
        Auth tier is LOW (any authenticated user); ownership is enforced by
        SelfServiceAccessController via the document's `member` field.
        """
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        return approval_service.apply_amendment()

    def create_dues_schedule_for_amendment(self):
        """Create dues schedule for this amendment - delegates to service."""
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        return approval_service.create_dues_schedule_for_amendment()

    def apply_fee_change(self, membership):
        """Apply fee change to membership - delegates to service."""
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        return approval_service.apply_fee_change(membership)

    def cancel_conflicting_amendments(self):
        """Cancel conflicting amendments - delegates to service."""
        from verenigingen.services.approval import ContributionAmendmentApprovalService

        approval_service = ContributionAmendmentApprovalService(self)
        return approval_service.cancel_conflicting_amendments()

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
            current_amount = self.current_amount or 0
            new_amount = self.requested_amount or current_amount

            difference = new_amount - current_amount
            percentage_change = (difference / current_amount * 100) if current_amount > 0 else 0

            impact_class = (
                "text-success" if difference > 0 else "text-danger" if difference < 0 else "text-muted"
            )
            impact_text = "increase" if difference > 0 else "decrease" if difference < 0 else "no change"

            # Get billing interval information
            billing_interval_display = "per month"
            annual_multiplier = 12

            if self.current_dues_schedule:
                try:
                    dues_schedule = frappe.get_doc("Membership Dues Schedule", self.current_dues_schedule)
                    billing_frequency = getattr(dues_schedule, "billing_frequency", "Monthly")

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
                        annual_multiplier = 12.0

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from dues schedule: {str(e)}")

            elif self.membership:
                try:
                    membership = frappe.get_doc("Membership", self.membership)
                    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
                    billing_period = getattr(membership_type, "billing_period", None) or "Monthly"

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
                        annual_multiplier = 12.0

                except Exception as e:
                    frappe.log_error(f"Error getting billing interval from membership type: {str(e)}")

            annual_difference = round(difference * annual_multiplier, 2)

            current_amount_formatted = frappe.format_value(current_amount, "Currency")
            new_amount_formatted = frappe.format_value(new_amount, "Currency")
            difference_formatted = frappe.format_value(abs(difference), "Currency")
            annual_difference_formatted = frappe.format_value(annual_difference, "Currency")

            effective_date_str = (
                frappe.utils.formatdate(self.effective_date) if self.effective_date else "Not set"
            )

            billing_display_clean = billing_interval_display.replace("per ", "").title()

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
    from verenigingen.services.approval import ContributionAmendmentApprovalService

    try:
        # Get all approved amendments with effective date today or earlier
        amendments_to_process = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "status": "Approved",
                "effective_date": ["<=", today()],
                "applied_date": ["is", "not set"],
            },
            fields=["name", "effective_date", "member", "requested_amount"],
            order_by="creation asc",
        )

        processed_count = 0
        error_count = 0

        for amendment_data in amendments_to_process:
            try:
                amendment = frappe.get_doc("Contribution Amendment Request", amendment_data.name)

                # SAFETY CHECK: Skip if already applied
                if amendment.status == "Applied" or amendment.applied_date:
                    frappe.logger().info(
                        f"Skipping amendment {amendment.name} - already applied "
                        f"(status: {amendment.status}, applied_date: {amendment.applied_date})"
                    )
                    continue

                # Force apply even if effective date is future
                amendment._force_apply = True
                approval_service = ContributionAmendmentApprovalService(amendment)
                result = approval_service.apply_amendment()

                if result.get("status") == "success":
                    processed_count += 1
                    frappe.logger().info(
                        "Applied amendment %s for member %s", amendment.name, amendment.member
                    )
                else:
                    error_count += 1
                    amendment.status = "Failed"
                    amendment.internal_notes = (
                        amendment.internal_notes or ""
                    ) + f"\nScheduled processing failed: {result.get('message', 'Unknown error')}"
                    amendment.save()

                    error_info = format_error_for_logging(
                        result.get("message", "Unknown error"),
                        f"Daily processing of amendment {amendment.name}",
                    )
                    frappe.logger().error(f"Failed to apply amendment {amendment.name}", extra=error_info)

            except Exception as e:
                error_count += 1
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

                error_info = format_error_for_logging(
                    e, f"Daily processing of amendment {amendment_data.name}"
                )
                frappe.logger().error(f"Error processing amendment {amendment_data.name}", extra=error_info)

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

    Returns:
        ContributionAmendmentRequest: The created amendment document
    """
    member = frappe.get_doc("Member", member_name)

    # Get current active membership using service
    from verenigingen.services.member.core.member_membership_service import get_member_membership_service

    membership = get_member_membership_service().get_active_membership(member_name)
    if not membership:
        frappe.throw(_("No active membership found for this member"))

    # Set default effective date if not provided
    if not effective_date:
        try:
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

    Args:
        member_name (str): Name/ID of the member to get amendments for

    Returns:
        list[dict]: List of amendment records
    """
    amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "amendment_type", "status", "requested_amount", "effective_date", "reason"],
        order_by="creation desc",
    )

    # Filter out approved amendments that have passed their effective date
    filtered_amendments = []
    for amendment in amendments:
        if amendment.status in ["Draft", "Pending Approval"]:
            filtered_amendments.append(amendment)
        elif amendment.status == "Approved" and amendment.effective_date:
            if DateRangeValidator.is_date_today_or_future(amendment.effective_date):
                filtered_amendments.append(amendment)
        elif amendment.status == "Approved" and not amendment.effective_date:
            filtered_amendments.append(amendment)

    return filtered_amendments
