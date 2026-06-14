from datetime import date
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_to_date, flt, getdate, nowdate, today

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation_utilities import DateRangeValidator


class Membership(Document):
    def validate(self) -> None:
        self._membership_type_doc = None  # Reset per-validate cache
        self.validate_dates()
        self.validate_membership_type()
        self.validate_existing_memberships()
        self.validate_grace_period()  # Moved from hooks.py
        self.set_renewal_date()  # Calculate renewal date based on start date and membership type
        self.set_grace_period_expiry()  # Set default grace period expiry if needed
        self.set_status()

    def _get_membership_type_doc(self):
        """Get cached Membership Type doc for current validate cycle (avoids 4 redundant DB fetches).

        Uses getattr so callers that invoke validate_dates()/set_renewal_date()
        directly (outside the full validate() cycle that initialises the cache)
        do not hit an AttributeError.
        """
        if getattr(self, "_membership_type_doc", None) is None and self.membership_type:
            self._membership_type_doc = frappe.get_doc("Membership Type", self.membership_type)
        return getattr(self, "_membership_type_doc", None)

    def on_submit(self) -> None:
        """Create or update dues schedule when membership is submitted"""
        # Skip dues schedule creation if flag is set (used in testing)
        if not getattr(self.flags, "skip_dues_schedule_creation", False):
            self.create_or_update_dues_schedule()

        # Check if parent Member is coordinating updates for performance optimization
        # If so, skip our member updates - parent will do them in one consolidated save
        if self.member:
            try:
                from verenigingen.utils.document_coordination import should_skip_child_updates

                member_doc = frappe.get_doc("Member", self.member)
                if should_skip_child_updates(member_doc, "Membership"):
                    frappe.logger().info(
                        f"Skipping member field updates for {self.member} - "
                        f"coordinated by Member.create_membership_on_approval"
                    )
                    return
            except Exception as e:
                # If coordination check fails, proceed with normal updates
                frappe.logger().warning(
                    f"Coordination check failed for {self.member}, proceeding with updates: {e}"
                )

        # No coordination active, update member normally
        self.update_member_current_membership_plan()
        self.update_member_duration()

    def on_cancel(self) -> None:
        """Handle dues schedule when membership is cancelled"""
        self.pause_dues_schedule()

    def on_trash(self) -> None:
        """Clean up Membership Dues Schedules linked to this membership"""
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule", filters={"membership": self.name}, pluck="name"
        )

        for schedule_name in dues_schedules:
            try:
                frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True)
                frappe.logger().info(f"Deleted orphaned Membership Dues Schedule {schedule_name}")
            except Exception as e:
                frappe.logger().error(f"Error deleting Membership Dues Schedule {schedule_name}: {str(e)}")

    def create_or_update_dues_schedule(self):
        """Create or update the member's dues schedule with improved error handling"""
        frappe.logger().info(
            f"[DUES SCHEDULE] create_or_update_dues_schedule called for {self.name}, "
            f"member={self.member}, status={self.status}"
        )
        if not self.member or self.status != "Active":
            frappe.logger().warning(
                f"[DUES SCHEDULE] Skipping dues schedule creation: member={self.member}, status={self.status}"
            )
            return

        # Check if the member actually exists in the database
        if not frappe.db.exists("Member", self.member):
            frappe.logger().error(
                f"[DUES SCHEDULE] Orphaned membership {self.name}: member {self.member} does not exist"
            )
            return

        # Check if member has CSV import custom fee set (optimized query)
        custom_fee, custom_fee_reason = frappe.db.get_value(
            "Member", self.member, ["csv_import_custom_fee", "csv_import_custom_fee_reason"]
        ) or (None, None)

        # Check if member already has a dues schedule
        repo = DuesScheduleRepository()
        existing_schedule_info = repo.get_active_schedule(self.member, fields=["name", "membership_type"])
        existing_schedule = existing_schedule_info.name if existing_schedule_info else None

        if existing_schedule:
            # Update existing schedule with new membership type if changed
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
                if schedule.membership_type != self.membership_type:
                    schedule.membership_type = self.membership_type
                    # Get template from membership type if available
                    membership_type_doc = frappe.get_doc("Membership Type", self.membership_type)
                    if membership_type_doc.dues_schedule_template:
                        template = frappe.get_doc(
                            "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                        )
                        # Validate template has required configuration
                        if not template.suggested_amount:
                            raise ValueError(
                                f"Dues schedule template '{membership_type_doc.dues_schedule_template}' must have a suggested_amount configured"
                            )
                        schedule.minimum_amount = (
                            template.minimum_amount if template.minimum_amount is not None else 0
                        )
                        schedule.suggested_amount = template.suggested_amount
                    schedule.save()
            except Exception as e:
                self._handle_dues_schedule_error(e, "update", existing_schedule)
        else:
            # Create new dues schedule from template with enhanced error handling
            try:
                from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                    MembershipDuesSchedule,
                )

                # Pass custom amount if CSV import fee is set (check for > 0, not just truthy)
                kwargs = {"membership_type": self.membership_type, "membership_name": self.name}
                if custom_fee and custom_fee > 0:
                    kwargs["custom_amount"] = custom_fee
                    kwargs["custom_amount_reason"] = custom_fee_reason or "Imported from CSV"
                    kwargs["custom_amount_approved"] = 1  # Auto-approve for CSV imports

                    # CRITICAL: Clear fields after use to prevent reuse on renewals
                    self._clear_csv_import_fee_fields()

                schedule_name = MembershipDuesSchedule.create_from_template(self.member, **kwargs)

                self._update_member_dues_schedule_link(schedule_name)

                # Log successful creation for monitoring
                frappe.logger().info(
                    f"Successfully created dues schedule {schedule_name} for member {self.member}"
                )

            except Exception as e:
                # Use new service-based retry instead of cache queue
                from verenigingen.services.billing.dues_schedule_creation_service import (
                    DuesScheduleCreationService,
                )

                service = DuesScheduleCreationService()
                result = service.create_schedule_with_retry(
                    member_name=self.member,
                    membership_name=self.name,
                    membership_type=self.membership_type,
                    custom_amount=custom_fee if custom_fee and custom_fee > 0 else None,
                    custom_amount_reason=custom_fee_reason if custom_fee and custom_fee > 0 else None,
                    custom_amount_approved=1 if custom_fee and custom_fee > 0 else 0,
                    retry_count=0,
                )

                if result.success:
                    self._update_member_dues_schedule_link(result.data)

                    # Clear CSV import fields if used
                    if custom_fee and custom_fee > 0:
                        self._clear_csv_import_fee_fields()

                    frappe.logger().info(
                        f"Successfully created dues schedule {result.data} via retry service"
                    )
                elif result.metadata.get("retry_job_id"):
                    # Retry enqueued - show user-friendly message
                    frappe.msgprint(
                        "Dues schedule creation will be retried automatically in the background. "
                        "You can continue working - the system will handle this.",
                        title="Dues Schedule Queued",
                        indicator="orange",
                        alert=True,
                    )
                else:
                    # Permanent failure - show error
                    self._handle_dues_schedule_error(e, "create")

    def _clear_csv_import_fee_fields(self):
        """Clear CSV import custom fee fields after use to prevent reuse on renewals."""
        frappe.logger().info(
            f"[DUES SCHEDULE] Clearing csv_import_custom_fee after use for member {self.member}"
        )
        frappe.db.set_value(
            "Member",
            self.member,
            {
                "csv_import_custom_fee": 0,  # Set to 0, not None (Currency field)
                "csv_import_custom_fee_reason": "",  # Set to empty string, not None
            },
            update_modified=False,
        )

    def _update_member_dues_schedule_link(self, schedule_name):
        """Update member record with dues schedule link, retrying on timestamp mismatch."""
        member = frappe.get_doc("Member", self.member)
        member.current_dues_schedule = schedule_name
        # Mark as system update to bypass fee override validation
        # (dues_rate was just set by schedule creation)
        member._system_update = True

        # Handle timestamp mismatch by reloading and retrying once
        try:
            member.save()
        except frappe.TimestampMismatchError:
            member.reload()
            member.current_dues_schedule = schedule_name
            member._system_update = True
            member.save()

    def _handle_dues_schedule_error(self, error, operation="create", schedule_name=None):
        """Enhanced error handling for dues schedule operations (simplified - retry handled by service)"""
        error_msg = str(error)

        # Create detailed error log
        log_title = f"Dues Schedule {operation.title()} Failed: {self.member}"
        if len(log_title) > 140:  # Frappe title limit
            log_title = f"Dues Schedule Error: {self.member[:50]}..."

        frappe.log_error(
            f"Dues Schedule {operation.title()} Error Details:\n"
            f"Membership: {self.name}\n"
            f"Member: {self.member}\n"
            f"Membership Type: {self.membership_type}\n"
            f"Operation: {operation}\n"
            f"Schedule: {schedule_name or 'N/A'}\n"
            f"Error: {error_msg}\n"
            f"Timestamp: {frappe.utils.now()}",
            log_title,
        )

        # Show user-friendly message (retry is handled by DuesScheduleCreationService)
        if "minimum_amount" in error_msg.lower() or "template" in error_msg.lower():
            frappe.msgprint(
                f"Warning: Dues schedule {operation} failed due to configuration issue. "
                f"Please check the membership type configuration.",
                title="Dues Schedule Configuration Issue",
                indicator="orange",
                alert=True,
            )
        else:
            frappe.msgprint(
                f"Warning: Could not {operation} dues schedule automatically. "
                f"Administrators have been notified.",
                title="Dues Schedule Issue",
                indicator="orange",
                alert=True,
            )

    # REMOVED: _create_dues_schedule_alert() - replaced by DuesScheduleCreationService._create_failure_alert()

    # REMOVED: _schedule_dues_schedule_retry() - replaced by DuesScheduleCreationService with frappe.enqueue()

    def pause_dues_schedule(self):
        """Pause the member's dues schedule when membership is cancelled"""
        if not self.member:
            return

        repo = DuesScheduleRepository()
        existing_schedule_info = repo.get_active_schedule(self.member, fields=["name"])

        if existing_schedule_info:
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule_info.name)
            schedule.pause_schedule(f"Membership {self.name} cancelled on {today()}")

    def get_dues_schedule(self):
        """Get the member's dues schedule"""
        if not self.member:
            return None

        repo = DuesScheduleRepository()
        # Don't pass fields param - get full object with all financial fields
        schedule_info = repo.get_active_schedule(self.member)
        return schedule_info.name if schedule_info else None

    def validate_existing_memberships(self):
        """Check if there are any existing active memberships for this member"""
        if self.is_new() and self.member:
            existing_memberships = frappe.get_all(
                "Membership",
                filters={
                    "member": self.member,
                    "status": ["not in", ["Cancelled", "Expired"]],
                    "docstatus": 1,
                    "name": ["!=", self.name],
                },
                fields=["name", "membership_type", "start_date", "renewal_date", "status"],
            )

            # Check for overlapping memberships
            if existing_memberships and self.start_date:
                for existing in existing_memberships:
                    # Check if the new membership overlaps with existing ones
                    existing_start = getdate(existing.start_date)
                    existing_renewal = getdate(existing.renewal_date) if existing.renewal_date else None
                    new_start = getdate(self.start_date)

                    # If we have both dates, check for overlap
                    if existing_renewal and hasattr(self, "renewal_date") and self.renewal_date:
                        new_renewal = getdate(self.renewal_date)
                        # Check for overlap
                        if not (new_renewal < existing_start or new_start > existing_renewal):
                            frappe.throw(
                                _(
                                    "This membership period overlaps with an existing active membership for this member"
                                ),
                                title=_("Overlapping Membership"),
                            )

            if existing_memberships:
                membership = existing_memberships[0]
                msg = _("This member already has an active membership:")
                msg += f"<br><b>{membership.name}</b> ({membership.membership_type})"
                msg += f"<br>Status: {membership.status}"
                msg += f"<br>Start Date: {frappe.format(membership.start_date, {'fieldtype': 'Date'})}"
                msg += f"<br>Renewal Date: {frappe.format(membership.renewal_date, {'fieldtype': 'Date'})}"

                if len(existing_memberships) > 1:
                    msg += (
                        f"<br><br>{_('And')} {len(existing_memberships) - 1} {_('more active memberships.')}"
                    )

                # Add view memberships link
                msg += f'<br><br><a href="/app/membership/list?member={self.member}">{_("View All Memberships")}</a>'

                # Add allow creation checkbox
                allow_creation = frappe.form_dict.get("allow_multiple_memberships")

                if not allow_creation:
                    msg += f"<br><br>{_('If you want to create multiple memberships for this member, check the Allow Multiple Memberships box.')}"

                    frappe.msgprint(
                        msg=msg,
                        title=_("Existing Membership Found"),
                        indicator="orange",
                        primary_action={
                            "label": _("Create Anyway"),
                            "server_action": "verenigingen.verenigingen.doctype.membership.membership.allow_multiple_memberships",
                            "args": {"member": self.member},
                        },
                    )

                    if not frappe.flags.get("allow_multiple_memberships"):
                        frappe.throw(
                            _(
                                "Member already has an active membership. Cancel the existing membership before creating a new one."
                            ),
                            title=_("Duplicate Membership"),
                        )

    def validate_dates(self):
        # Validate renewal date is not before start date
        if self.renewal_date and self.start_date:
            if DateRangeValidator.is_date_before(self.renewal_date, self.start_date):
                frappe.throw(_("Renewal date cannot be before start date"))

        # Check if minimum period enforcement is enabled for this membership type
        membership_type = self._get_membership_type_doc()
        enforce_minimum = membership_type.get("enforce_minimum_period", True) if membership_type else True

        # If cancellation date is set and minimum period is enforced, check if it's at least 1 year after start date
        # but allow exceptions for admins and unsubmitted memberships
        if self.cancellation_date and self.start_date and self.docstatus == 1 and enforce_minimum:
            min_membership_period = add_months(getdate(self.start_date), 12)
            if DateRangeValidator.is_date_before(self.cancellation_date, min_membership_period):
                # Check if user is an admin
                is_admin = Roles.SYSTEM_MANAGER in frappe.get_roles(frappe.session.user)

                if is_admin:
                    # Show warning but allow cancellation
                    frappe.msgprint(
                        _("Warning: Membership is being cancelled before the minimum 1-year period."),
                        indicator="yellow",
                        alert=True,
                    )
                else:
                    frappe.throw(
                        _("Cancellation is only allowed after a minimum membership period of 1 year")
                    )

    def set_renewal_date(self):
        """Calculate renewal date based on membership type and start date"""
        if self.membership_type and self.start_date:
            membership_type = self._get_membership_type_doc()

            # Get duration from membership type (billing_period is optional)
            billing_period = getattr(membership_type, "billing_period", None) or "Annual"
            if billing_period != "Lifetime":
                billing_period_in_months = getattr(membership_type, "billing_period_in_months", None)
                months = self.get_months_from_period(billing_period, billing_period_in_months)

                # Check if minimum period enforcement is enabled for this membership type
                enforce_minimum = (
                    membership_type.get("enforce_minimum_period", True) if membership_type else True
                )

                # Ensure minimum 1-year membership period if enabled
                if months and months < 12 and enforce_minimum:
                    months = 12
                    # Only show message once per session
                    message_key = f"renewal_message_{self.name or 'new'}"
                    if not frappe.flags.get(message_key):
                        frappe.msgprint(
                            _(
                                "Note: Membership type has a period less than 1 year. Due to the mandatory minimum period, the renewal date is set to 1 year from start date."
                            ),
                            indicator="yellow",
                        )
                        frappe.flags[message_key] = True

                if months:
                    # For CSV imports with historic start_date, calculate renewal from today
                    # to ensure Active status rather than Expired
                    reference_date = self.start_date
                    if getattr(self, "_is_csv_import", False) and getdate(self.start_date) < getdate(today()):
                        reference_date = today()
                        frappe.logger().info(
                            f"[MEMBERSHIP] CSV import with historic start_date {self.start_date}, "
                            f"calculating renewal_date from today: {reference_date}"
                        )

                    self.renewal_date = add_to_date(reference_date, months=months)
                elif billing_period == "Daily":
                    # Handle daily period
                    if enforce_minimum:
                        # Even for daily, enforce 1 year minimum
                        self.renewal_date = add_to_date(self.start_date, months=12)
                        message_key = f"daily_minimum_message_{self.name or 'new'}"
                        if not frappe.flags.get(message_key):
                            frappe.msgprint(
                                _("Note: Daily membership type has minimum 1-year period enforced."),
                                indicator="yellow",
                            )
                            frappe.flags[message_key] = True
                    else:
                        # For daily without minimum period, set renewal to 1 day
                        self.renewal_date = add_to_date(self.start_date, days=1)
            else:
                # Check if minimum period enforcement is enabled for this membership type
                enforce_minimum = (
                    membership_type.get("enforce_minimum_period", True) if membership_type else True
                )

                if enforce_minimum:
                    # For lifetime memberships, still set a minimum 1-year initial period
                    # This allows the 1-year cancellation rule to be enforced
                    # For CSV imports with historic start_date, calculate from today
                    reference_date = self.start_date
                    if getattr(self, "_is_csv_import", False) and getdate(self.start_date) < getdate(today()):
                        reference_date = today()

                    self.renewal_date = add_to_date(reference_date, months=12)
                    # Only show message once per session and if renewal date is not already set
                    message_key = f"lifetime_message_{self.name or 'new'}"
                    if not frappe.flags.get(message_key) and not getattr(
                        self, "_lifetime_message_shown", False
                    ):
                        frappe.msgprint(
                            _(
                                "Note: Although this is a lifetime membership, a 1-year minimum commitment period still applies."
                            ),
                            indicator="info",
                        )
                        frappe.flags[message_key] = True
                        self._lifetime_message_shown = True
                else:
                    # For lifetime memberships without minimum period, set a far future date
                    self.renewal_date = add_to_date(self.start_date, years=50)

        # Set commitment end date (typically 1 year from start for welcome gift eligibility)
        # This is separate from renewal_date as it tracks when members can quit
        self.set_commitment_end_date()

    def set_commitment_end_date(self):
        """
        Set the commitment end date - the minimum period members must remain before quitting.
        This is typically 1 year from start date for members who receive welcome gifts.

        Only sets commitment_end_date if enforce_minimum_period is enabled on the Membership Type.
        """
        if not self.start_date:
            return

        # Check if minimum period enforcement is enabled for this membership type
        if self.membership_type:
            membership_type = self._get_membership_type_doc()
            enforce_minimum = membership_type.get("enforce_minimum_period", True) if membership_type else True
            if not enforce_minimum:
                # Don't set commitment_end_date if minimum period is not enforced
                return

        # Default to 1 year commitment period (welcome gift eligibility requirement)
        # Can be overridden if needed for special cases
        if not self.commitment_end_date:
            self.commitment_end_date = add_to_date(self.start_date, months=12)

    def get_months_from_period(self, period, custom_months=None):
        period_months = {
            "Daily": 0,  # Will be handled specially
            "Monthly": 1,
            "Quarterly": 3,
            "Biannual": 6,
            "Annual": 12,
            "Lifetime": 0,
            "Custom": custom_months or 0,
        }

        return period_months.get(period, 0)

    def validate_membership_type(self):
        # Check if membership type exists and is active
        if self.membership_type:
            membership_type = self._get_membership_type_doc()

            if not membership_type.is_active:
                frappe.throw(_("Membership Type {0} is inactive").format(self.membership_type))

    def validate_grace_period(self):
        """Validation for Membership grace period fields (moved from hooks.py)"""
        from frappe.utils import getdate, today

        # Validate grace period expiry date
        if self.grace_period_status == "Grace Period":
            if not getattr(self, "grace_period_expiry_date", None):
                frappe.throw(_("Grace period expiry date is required when grace period status is set"))

            # Ensure grace period expiry is in the future (allow same day)
            if getdate(self.grace_period_expiry_date) < getdate(today()):
                frappe.throw(_("Grace period expiry date cannot be in the past"))

    def set_status(self):
        """Set the status based on dates, payment amount, and cancellation"""
        if self.docstatus == 0:
            self.status = "Draft"
        elif self.docstatus == 2:
            self.status = "Cancelled"
        elif self.cancellation_date and DateRangeValidator.is_date_today_or_past(self.cancellation_date):
            # Membership is cancelled
            self.status = "Cancelled"
        elif hasattr(self, "unpaid_amount") and self.unpaid_amount and flt(self.unpaid_amount) > 0:
            # Has unpaid invoices - membership inactive
            # Note: This field may not exist in all installations
            self.status = "Inactive"
        elif self.renewal_date and DateRangeValidator.is_date_in_past(self.renewal_date):
            # Past renewal date - membership expired
            self.status = "Expired"
        else:
            # All good - active membership
            self.status = "Active"

    def set_grace_period_expiry(self):
        """Set grace period expiry date based on settings if grace period status is set"""
        self.grace_period_expiry_date = None
        if self.grace_period_status == "Grace Period" and not self.grace_period_expiry_date:
            # Get default grace period days from settings
            settings = frappe.get_single("Verenigingen Settings")
            default_days = getattr(settings, "default_grace_period_days", 30)

            # Set expiry date to default days from today
            self.grace_period_expiry_date = add_to_date(today(), days=default_days)

            # Optional: Log the auto-setting of grace period
            if not frappe.flags.get("suppress_grace_period_message"):
                frappe.msgprint(
                    _("Grace period expiry date automatically set to {0} days from today ({1})").format(
                        default_days, frappe.format(self.grace_period_expiry_date, {"fieldtype": "Date"})
                    ),
                    indicator="info",
                    alert=True,
                )

    @staticmethod
    def auto_apply_grace_period_if_enabled(member_name):
        """Apply grace period automatically if enabled in settings"""
        settings = frappe.get_single("Verenigingen Settings")

        if not getattr(settings, "grace_period_auto_apply", False):
            return False

        # Find active membership for this member
        membership = frappe.get_value("Membership", {"member": member_name, "status": "Active"}, "name")

        if not membership:
            return False

        # Get membership document
        membership_doc = frappe.get_doc("Membership", membership)

        # Check if already in grace period
        if membership_doc.grace_period_status == "Grace Period":
            return False

        # Apply grace period
        membership_doc.grace_period_status = "Grace Period"
        membership_doc.grace_period_reason = "Automatically applied due to overdue payments"

        # An Active membership is always submitted (docstatus=1), and the
        # grace-period fields are not allow_on_submit, so a plain save() raises
        # UpdateAfterSubmitError. Allow the post-submit field update (same pattern
        # used by cancel_membership / process_membership_statuses).
        membership_doc.flags.ignore_validate_update_after_submit = True

        # The set_grace_period_expiry method will set the expiry date
        frappe.flags.suppress_grace_period_message = True
        membership_doc.save()
        frappe.flags.suppress_grace_period_message = False

        return True

    # DEPRECATED: Legacy fee calculation method - use dues schedule system instead
    def calculate_effective_amount(self):
        """DEPRECATED: Calculate the effective amount and difference from standard

        This method is deprecated. Use the Membership Dues Schedule system instead.
        Maintained for backward compatibility only.
        """
        frappe.log_error(
            "calculate_effective_amount method is deprecated. Use dues schedule system instead.",
            "Deprecated Function",
        )

        # Get amount from dues schedule template (explicit configuration)
        if self.membership_type:
            template = load_template_for_membership_type(self.membership_type)
            if not template.suggested_amount:
                frappe.throw(
                    f"Dues schedule template '{template.name}' must have a suggested_amount configured"
                )
            return template.suggested_amount
        return 0

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def get_billing_amount(self):
        """Get the billing amount for this membership"""
        # Get amount from member's dues schedule if exists
        if self.member:
            repo = DuesScheduleRepository()
            dues_schedule_info = repo.get_active_schedule(self.member, fields=["dues_rate"])
            if dues_schedule_info:
                return dues_schedule_info.dues_rate

        # Fallback to membership type template amount
        if self.membership_type:
            template = load_template_for_membership_type(self.membership_type)
            if not template.suggested_amount:
                frappe.throw(
                    f"Dues schedule template '{template.name}' must have a suggested_amount configured"
                )
            return template.suggested_amount

        return 0

    def update_member_status(self):
        """Update the membership status in the Member document"""
        if self.member:
            try:
                member = frappe.get_doc("Member", self.member)
                member.save()  # This will trigger the update_membership_status method
            except frappe.PermissionError:
                # If user doesn't have permission to update member, skip
                frappe.logger().debug(
                    f"Skipping member status update for {self.member} due to permission error"
                )

    def update_member_current_membership_plan(self):
        """Update the member's current_membership_plan and current_dues_schedule fields when membership becomes active"""
        if not self.member or self.status != "Active":
            return

        try:
            member_doc = frappe.get_doc("Member", self.member)
            member_doc.current_membership_plan = self.name
            # Mark as system update to bypass fee override validation
            member_doc._system_update = True

            # Also update current_dues_schedule to match the member's dues schedule
            dues_schedule_name = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": self.member, "status": "Active", "is_template": 0},
                "name",
            )
            if dues_schedule_name:
                member_doc.current_dues_schedule = dues_schedule_name

            member_doc.save()
            frappe.logger().info(
                f"Updated current_membership_plan for member {self.member} to {self.name}"
                + (f" and current_dues_schedule to {dues_schedule_name}" if dues_schedule_name else "")
            )
        except Exception as e:
            frappe.logger().error(f"Failed to update member fields for {self.member}: {str(e)}")
            # Don't fail the membership submission if this update fails

    def update_member_duration(self):
        """Update the member's cumulative membership duration when membership is submitted"""
        if not self.member:
            return

        try:
            from verenigingen.services.member.utils.membership_duration_service import (
                update_member_duration_fields,
            )

            member_doc = frappe.get_doc("Member", self.member)
            result = update_member_duration_fields(member_doc)

            if result.success:
                # Mark as system update to bypass fee override validation
                member_doc._system_update = True
                member_doc.save()
                duration = result.data.get("duration") if result.data else None
                frappe.logger().info(f"Updated membership duration for {self.member}: {duration}")
        except Exception as e:
            frappe.logger().error(f"Failed to update membership duration for {self.member}: {str(e)}")
            # Don't fail the membership submission if this update fails


def on_submit(doc, method=None):
    """
    This is called when a membership document is submitted.
    It simply calls the document's on_submit method.
    """
    # The class already has on_submit method, so this is just a passthrough


def on_cancel(doc, method=None):
    """
    This is called when a membership document is cancelled.
    It simply calls the document's on_cancel method.
    """
    # The class already has on_cancel method, so this is just a passthrough


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def cancel_membership(
    membership_name: str,
    cancellation_date: str = None,
    cancellation_reason: str = None,
    cancellation_type: str = "Immediate",
):
    """
    Cancel a membership with the given details
    - cancellation_date: Date when the cancellation was requested
    - cancellation_reason: Reason for cancellation
    - cancellation_type: "Immediate" or "End of Period"
    """
    if not cancellation_date:
        cancellation_date = nowdate()

    membership = frappe.get_doc("Membership", membership_name)

    # For unsubmitted memberships, allow immediate cancellation without restrictions
    if membership.docstatus == 0:
        frappe.msgprint(_("Draft membership can be cancelled without restrictions"))
        return membership.name

    # Check if minimum period enforcement is enabled for this membership type
    membership_type = (
        frappe.get_doc("Membership Type", membership.membership_type) if membership.membership_type else None
    )
    enforce_minimum = membership_type.get("enforce_minimum_period", True) if membership_type else True

    # Check 1-year minimum period for submitted memberships if enforcement is enabled
    if membership.docstatus == 1 and enforce_minimum:
        min_membership_period = add_months(getdate(membership.start_date), 12)
        if DateRangeValidator.is_date_before(cancellation_date, min_membership_period):
            # Check if user is an admin
            is_admin = Roles.SYSTEM_MANAGER in frappe.get_roles(frappe.session.user)

            if is_admin:
                # Show warning but allow cancellation
                frappe.msgprint(
                    _(
                        "Warning: Membership is being cancelled before the minimum 1-year period. This is allowed for administrators only."
                    ),
                    indicator="yellow",
                    alert=True,
                )
            else:
                frappe.throw(_("Cancellation is only allowed after a minimum membership period of 1 year"))

    # Set cancellation details
    membership.cancellation_date = cancellation_date
    membership.cancellation_reason = cancellation_reason
    membership.cancellation_type = cancellation_type

    # Immediate cancellation updates status right away
    if cancellation_type == "Immediate":
        membership.status = "Cancelled"

    # For end of period, status remains active until renewal date
    membership.flags.ignore_validate_update_after_submit = True
    membership.save()

    frappe.msgprint(_("Membership {0} has been cancelled").format(membership.name))
    return membership.name


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def sync_membership_payments(membership_name: str = None):
    """
    Sync payment details for a membership or all active memberships
    """
    if membership_name:
        frappe.msgprint(
            _("Payment sync from legacy system is deprecated. Use dues schedule system instead."),
            indicator="orange",
            alert=True,
        )
        return True
    else:
        frappe.msgprint(
            _("Payment sync from legacy system is deprecated. Use dues schedule system instead."),
            indicator="orange",
            alert=True,
        )
        count = 0

        return count


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def process_membership_statuses():
    """
    Scheduled job to update membership statuses based on dates and payments
    - Expire memberships past renewal date
    - Mark memberships as inactive if payment is overdue
    - Auto-renew memberships if configured
    """
    # using getdate, today from top-level import

    # Get memberships that need status updates
    memberships = frappe.get_all(
        "Membership",
        filters={"docstatus": 1, "status": ["not in", ["Cancelled", "Expired"]]},
        fields=["name", "renewal_date", "status"],
    )

    today_date = getdate(today())

    for membership_info in memberships:
        try:
            membership = frappe.get_doc("Membership", membership_info.name)

            # Check expiry - if past renewal date
            # Note: Auto-renewal is handled by the billing system, not individual memberships
            if membership.renewal_date and DateRangeValidator.is_date_before(
                membership.renewal_date, today_date
            ):
                # Mark as expired - renewal is handled by the billing/dues schedule system
                membership.status = "Expired"
                membership.flags.ignore_validate_update_after_submit = True
                membership.save()

                frappe.logger().info(f"Marked membership {membership.name} as Expired")

            # Check cancellations with end-of-period dates that have now been reached
            elif membership.cancellation_date and membership.cancellation_type == "End of Period":
                if DateRangeValidator.is_date_today_or_before(membership.renewal_date, today_date):
                    membership.status = "Cancelled"
                    membership.flags.ignore_validate_update_after_submit = True
                    membership.save()

                    frappe.logger().info(
                        f"Processed end-of-period cancellation for membership {membership.name}"
                    )

        except Exception as e:
            frappe.log_error(
                f"Error processing membership status for {membership_info.name}: {str(e)}",
                "Membership Status Update Error",
            )

    return True


def verify_signature(data, signature, secret_key=None):
    """
    Verify a signature for webhook data (for donation verification)
    Args:
        data (dict or str): The data to verify
        signature (str): The signature received
        secret_key (str, optional): The secret key to use for verification.
                                   If not provided, will use config value.
    Returns:
        bool: True if signature is valid, False otherwise
    """
    import hashlib
    import hmac

    # using frappe from top-level import

    if not secret_key:
        # Get secret key from configuration
        secret_key = frappe.conf.get("webhook_secret_key")
        if not secret_key:
            frappe.log_error(
                "No webhook_secret_key found in configuration", "Payment Signature Verification Error"
            )
            return False
    # Convert data to string if it's a dict
    if isinstance(data, dict):
        import json

        data = json.dumps(data)
    # Convert to bytes if it's not already
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    # Create signature
    computed_signature = hmac.new(secret_key, data, hashlib.sha256).hexdigest()
    # Compare signatures (using constant-time comparison to prevent timing attacks)
    return hmac.compare_digest(computed_signature, signature)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def show_all_invoices(membership_name: str):
    """
    Get all invoices related to a membership through direct links or the
    member's customer record.
    """
    membership = frappe.get_doc("Membership", membership_name)
    invoices = []

    # Look for invoices that might be directly linked to the membership.
    # Sales Invoice has no `membership` column (only a `member` custom field), so
    # querying it unconditionally raises "Unknown column 'membership'". Guard on
    # the field's existence so the endpoint degrades to the member/customer lookup
    # below instead of crashing.
    if frappe.get_meta("Sales Invoice").has_field("membership"):
        direct_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "membership": membership.name,
            },
            fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "due_date"],
        )
    else:
        direct_invoices = []

    for inv in direct_invoices:
        # Check if this invoice is already in our list (to avoid duplicates)
        if not any(existing["invoice"] == inv.name for existing in invoices):
            invoices.append(
                {
                    "invoice": inv.name,
                    "date": inv.posting_date,
                    "amount": inv.grand_total,
                    "outstanding": inv.outstanding_amount,
                    "status": inv.status,
                    "due_date": inv.due_date,
                    "source": "Direct Link",
                }
            )

    # Look for invoices related to the member
    if membership.member:
        member = frappe.get_doc("Member", membership.member)

        # If the member has a linked customer
        if member.customer:
            customer_invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 1,
                    "customer": member.customer,
                    "posting_date": [
                        "between",
                        [membership.start_date, membership.renewal_date or "2099-12-31"],
                    ],
                },
                fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "due_date"],
            )

            for inv in customer_invoices:
                # Check if this invoice is already in our list (to avoid duplicates)
                if not any(existing["invoice"] == inv.name for existing in invoices):
                    invoices.append(
                        {
                            "invoice": inv.name,
                            "date": inv.posting_date,
                            "amount": inv.grand_total,
                            "outstanding": inv.outstanding_amount,
                            "status": inv.status,
                            "due_date": inv.due_date,
                            "source": "Member/Customer",
                        }
                    )

    # Sort all invoices by date (newest first)
    invoices.sort(key=lambda x: x["date"] or "1900-01-01", reverse=True)

    return invoices


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_member_sepa_mandates(
    doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | str
):
    """Get SEPA mandates for a specific member"""
    # Link-search callers pass `filters` as a dict, but it can also arrive as a
    # JSON string; the body uses .get(), so normalise to a dict here. Declaring
    # the annotation as dict (not str) also stops the v16 typing validator from
    # rejecting the dict that real search calls deliver.
    if isinstance(filters, str):
        import json

        filters = json.loads(filters) if filters else {}
    member = filters.get("member")

    if not member:
        # Try to get member from membership document
        if filters.get("doctype") == "Membership" and filters.get("name"):
            membership = frappe.get_doc("Membership", filters.get("name"))
            member = membership.member

    if not member:
        return []

    # Get active SEPA mandates for this member
    return frappe.db.sql(
        """
        SELECT
            sm.name,
            sm.mandate_id,
            sm.status
        FROM `tabSEPA Mandate` sm
        WHERE
            sm.member = %s
            AND sm.status = 'Active'
            AND sm.used_for_memberships = 1
            AND (sm.name LIKE %s OR sm.mandate_id LIKE %s)
        ORDER BY sm.creation DESC
    """,
        (member, "%" + txt + "%", "%" + txt + "%"),
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def revert_to_standard_amount(membership_name: str, reason: str = None):
    """Revert membership to use standard membership type amount"""

    membership = frappe.get_doc("Membership", membership_name)

    # Check permissions
    if not frappe.has_permission("Membership", "write", membership):
        frappe.throw(_("No permission to modify this membership"))

        # DEPRECATED:     if not membership.uses_custom_amount:
        frappe.throw(_("This membership is already using the standard amount"))

    # DEPRECATED:     old_amount = membership.custom_amount

    # Revert to standard amount
    # DEPRECATED:     membership.uses_custom_amount = 0
    # DEPRECATED:     membership.custom_amount = None
    # DEPRECATED:     membership.amount_reason = reason or "Reverted to standard amount"
    membership.flags.ignore_validate_update_after_submit = True
    membership.save()

    # Get standard amount from template (required configuration)
    template = load_template_for_membership_type(membership.membership_type)

    if not template.suggested_amount:
        frappe.throw(
            f"Dues schedule template for membership type '{membership.membership_type}' must have a suggested_amount configured"
        )
    standard_amount = template.suggested_amount

    return {
        "success": True,
        "old_amount": 0,  # Placeholder for backward compatibility
        "new_amount": standard_amount,
        "message": _("Reverted to standard amount: {0}").format(
            frappe.format_value(standard_amount, {"fieldtype": "Currency"})
        ),
    }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def allow_multiple_memberships(member: str):
    """Set a flag to allow creating multiple memberships for a member"""
    frappe.flags.allow_multiple_memberships = True
    return True
