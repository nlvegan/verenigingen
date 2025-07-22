import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_to_date, flt, getdate, nowdate, today


class Membership(Document):
    def validate(self):
        self.validate_dates()
        self.validate_membership_type()
        self.validate_existing_memberships()
        self.set_renewal_date()  # Calculate renewal date based on start date and membership type
        self.set_grace_period_expiry()  # Set default grace period expiry if needed
        self.set_status()

    def on_submit(self):
        """Create or update dues schedule when membership is submitted"""
        self.create_or_update_dues_schedule()

    def on_cancel(self):
        """Handle dues schedule when membership is cancelled"""
        self.pause_dues_schedule()

    def create_or_update_dues_schedule(self):
        """Create or update the member's dues schedule"""
        if not self.member or self.status != "Active":
            return

        # Check if member already has a dues schedule
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": self.member, "is_template": 0}, "name"
        )

        if existing_schedule:
            # Update existing schedule with new membership type if changed
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            if schedule.membership_type != self.membership_type:
                schedule.membership_type = self.membership_type
                # Get template from membership type if available
                membership_type_doc = frappe.get_doc("Membership Type", self.membership_type)
                if membership_type_doc.dues_schedule_template:
                    template = frappe.get_doc(
                        "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                    )
                    schedule.minimum_amount = template.minimum_amount or 0
                    schedule.suggested_amount = template.suggested_amount or 0
                schedule.save()
        else:
            # Create new dues schedule from template
            try:
                from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                    MembershipDuesSchedule,
                )

                schedule_name = MembershipDuesSchedule.create_from_template(
                    self.member, membership_type=self.membership_type
                )

                # Update member record with dues schedule link
                member = frappe.get_doc("Member", self.member)
                member.dues_schedule = schedule_name

                # Handle timestamp mismatch by reloading and retrying once
                try:
                    member.save()
                except frappe.TimestampMismatchError:
                    # Reload member and retry save once
                    member.reload()
                    member.dues_schedule = schedule_name
                    member.save()

            except Exception as e:
                # Create shorter error message for log title to avoid character limit
                error_msg = str(e)
                if len(error_msg) > 100:
                    error_msg = error_msg[:97] + "..."

                frappe.log_error(
                    f"Full error details:\nMember: {self.member}\nError: {str(e)}",
                    f"Dues Schedule Error: {self.member}",
                )
                # Don't fail the membership creation if dues schedule fails
                frappe.msgprint(
                    "Warning: Could not create dues schedule automatically. Please create manually if needed.",
                    alert=True,
                )

    def pause_dues_schedule(self):
        """Pause the member's dues schedule when membership is cancelled"""
        if not self.member:
            return

        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": self.member, "is_template": 0}, "name"
        )

        if existing_schedule:
            schedule = frappe.get_doc("Membership Dues Schedule", existing_schedule)
            schedule.pause_schedule(f"Membership {self.name} cancelled on {today()}")

    def get_dues_schedule(self):
        """Get the member's dues schedule"""
        if not self.member:
            return None

        return frappe.db.get_value(
            "Membership Dues Schedule", {"member": self.member, "is_template": 0}, "name"
        )

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
                    msg += f'<br><br>{_("If you want to create multiple memberships for this member, check the Allow Multiple Memberships box.")}'

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
            if getdate(self.renewal_date) < getdate(self.start_date):
                frappe.throw(_("Renewal date cannot be before start date"))

        # Check if minimum period enforcement is enabled for this membership type
        membership_type = (
            frappe.get_doc("Membership Type", self.membership_type) if self.membership_type else None
        )
        enforce_minimum = membership_type.get("enforce_minimum_period", True) if membership_type else True

        # If cancellation date is set and minimum period is enforced, check if it's at least 1 year after start date
        # but allow exceptions for admins and unsubmitted memberships
        if self.cancellation_date and self.start_date and self.docstatus == 1 and enforce_minimum:
            min_membership_period = add_months(getdate(self.start_date), 12)
            if getdate(self.cancellation_date) < min_membership_period:
                # Check if user is an admin
                is_admin = "System Manager" in frappe.get_roles(frappe.session.user)

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
            membership_type = frappe.get_doc("Membership Type", self.membership_type)

            # Get duration from membership type
            billing_period = getattr(membership_type, "billing_period", "Annual")
            if billing_period != "Lifetime":
                billing_period_in_months = getattr(membership_type, "billing_period_in_months", None)
                months = self.get_months_from_period(billing_period, billing_period_in_months)

                # Check if minimum period enforcement is enabled for this membership type
                enforce_minimum = membership_type.get("enforce_minimum_period", True)

                # Ensure minimum 1-year membership period if enabled
                if months and months < 12 and enforce_minimum:
                    months = 12
                    # Only show message once per session and if renewal date is not already set
                    message_key = f"renewal_message_{self.name or 'new'}"
                    if not frappe.flags.get(message_key) and not self.renewal_date:
                        frappe.msgprint(
                            _(
                                "Note: Membership type has a period less than 1 year. Due to the mandatory minimum period, the renewal date is set to 1 year from start date."
                            ),
                            indicator="yellow",
                        )
                        frappe.flags[message_key] = True

                if months:
                    self.renewal_date = add_to_date(self.start_date, months=months)
                elif billing_period == "Daily":
                    # Handle daily period
                    if enforce_minimum:
                        # Even for daily, enforce 1 year minimum
                        self.renewal_date = add_to_date(self.start_date, months=12)
                        message_key = f"daily_minimum_message_{self.name or 'new'}"
                        if not frappe.flags.get(message_key) and not self.renewal_date:
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
                enforce_minimum = membership_type.get("enforce_minimum_period", True)

                if enforce_minimum:
                    # For lifetime memberships, still set a minimum 1-year initial period
                    # This allows the 1-year cancellation rule to be enforced
                    self.renewal_date = add_to_date(self.start_date, months=12)
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
            membership_type = frappe.get_doc("Membership Type", self.membership_type)

            if not membership_type.is_active:
                frappe.throw(_("Membership Type {0} is inactive").format(self.membership_type))

    def set_status(self):
        """Set the status based on dates, payment amount, and cancellation"""
        if self.docstatus == 0:
            self.status = "Draft"
        elif self.docstatus == 2:
            self.status = "Cancelled"
        elif self.cancellation_date and getdate(self.cancellation_date) <= getdate(today()):
            # Membership is cancelled
            self.status = "Cancelled"
        elif hasattr(self, "unpaid_amount") and self.unpaid_amount and flt(self.unpaid_amount) > 0:
            # Has unpaid invoices - membership inactive
            # Note: This field may not exist in all installations
            self.status = "Inactive"
        elif self.renewal_date and getdate(self.renewal_date) < getdate(today()):
            # Past renewal date - membership expired
            self.status = "Expired"
        else:
            # All good - active membership
            self.status = "Active"

    def set_grace_period_expiry(self):
        """Set grace period expiry date based on settings if grace period status is set"""
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

        # Return basic amount from membership type for backward compatibility
        if self.membership_type:
            membership_type = frappe.get_cached_doc("Membership Type", self.membership_type)
            return membership_type.amount
        return 0

    def get_billing_amount(self):
        """Get the billing amount for this membership"""
        # Get amount from member's dues schedule if exists
        if self.member:
            dues_schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": self.member, "is_template": 0}, "dues_rate"
            )
            if dues_schedule:
                return dues_schedule

        # Fallback to membership type amount
        if self.membership_type:
            membership_type = frappe.get_doc("Membership Type", self.membership_type)
            return membership_type.amount

        return 0

    @frappe.whitelist()
    def create_dues_schedule_from_membership(self):
        """Create a Membership Dues Schedule for this membership"""
        dues_schedule = getattr(self, "dues_schedule", None)
        if dues_schedule:
            return dues_schedule

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")

        # Set required fields using new naming pattern
        from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

        dues_schedule.schedule_name = generate_dues_schedule_name(self.member, self.membership_type)
        dues_schedule.member = self.member
        dues_schedule.membership_type = self.membership_type

        # Set dues rate from billing amount or membership type
        billing_amount = self.get_billing_amount() if hasattr(self, "get_billing_amount") else None
        if billing_amount:
            dues_schedule.dues_rate = billing_amount
        else:
            # Fallback to membership type amount or template
            membership_type = frappe.get_doc("Membership Type", self.membership_type)
            if membership_type.dues_schedule_template:
                template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
                dues_schedule.dues_rate = (
                    template.suggested_amount or template.dues_rate or membership_type.amount
                )
            else:
                dues_schedule.dues_rate = membership_type.amount or 0

        # Set billing frequency based on membership type
        if self.membership_type:
            membership_type = frappe.get_doc("Membership Type", self.membership_type)
            # Map membership type billing periods to billing frequencies
            period_mapping = {
                "Monthly": "Monthly",
                "Quarterly": "Quarterly",
                "Annual": "Annual",
                "Biannual": "Semi-Annual",  # Fixed mapping
                "Lifetime": "Annual",  # Lifetime memberships still bill annually
                "Daily": "Monthly",  # Daily periods converted to monthly billing
                "Custom": "Annual",  # Custom periods default to annual
            }

            billing_period = getattr(membership_type, "billing_period", "Annual")
            dues_schedule.billing_frequency = period_mapping.get(billing_period, "Annual")

        # Set contribution mode - use proper values
        dues_schedule.contribution_mode = "Calculator"  # Default to calculator mode
        dues_schedule.base_multiplier = 1.0

        # Set status
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 1  # Enable auto invoice generation

        # Insert the dues schedule
        dues_schedule.insert()

        # Link to membership
        self.dues_schedule = dues_schedule.name
        self.db_set("dues_schedule", dues_schedule.name)

        return dues_schedule.name

    def sync_payment_details_from_dues_schedule(self):
        """Sync payment details from linked dues schedule"""
        if not getattr(self, "dues_schedule", None):
            return

        # Get invoices related to this member through the dues schedule
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": frappe.db.get_value("Member", self.member, "customer"),
                "docstatus": 1,
                "posting_date": [">=", self.start_date],
            },
            fields=["name", "status", "outstanding_amount", "posting_date", "grand_total"],
        )

        # Calculate unpaid amount
        unpaid_amount = 0
        payment_date = None

        for invoice in invoices:
            if invoice.status in ["Unpaid", "Overdue"]:
                unpaid_amount += invoice.outstanding_amount
            elif invoice.status == "Paid":
                if not payment_date or invoice.posting_date > payment_date:
                    payment_date = invoice.posting_date

        # Update membership
        self.unpaid_amount = unpaid_amount
        self.db_set("unpaid_amount", unpaid_amount)

        if payment_date:
            self.last_payment_date = payment_date
            self.db_set("last_payment_date", payment_date)

    def on_submit_legacy(self):  # Renamed to avoid duplicate definition
        import json

        import frappe
        from frappe import _
        from frappe.utils import add_days, add_months, getdate

        # Update member's current membership
        self.update_member_status()

        # Make sure unpaid_amount is set if field exists and not already set
        if hasattr(self, "unpaid_amount") and not self.unpaid_amount:
            self.unpaid_amount = 0

        # Initialize next_billing_date to start_date if not set
        if not self.next_billing_date:
            self.next_billing_date = self.start_date

        # Clear cancellation fields if not set
        if not self.cancellation_date:
            self.cancellation_date = None
            self.cancellation_reason = None
            self.cancellation_type = None

        # Update status properly
        self.set_status()

        # Force update to database
        self.db_set("status", self.status)
        unpaid_amount = getattr(self, "unpaid_amount", None)
        if unpaid_amount is not None:
            self.db_set("unpaid_amount", unpaid_amount)
        self.db_set("next_billing_date", self.next_billing_date)
        self.db_set("cancellation_date", None)
        self.db_set("cancellation_reason", None)
        self.db_set("cancellation_type", None)

        # Update member's current membership
        self.update_member_status()

        # Create dues schedule if not exists
        # Note: dues_schedule field doesn't exist in Membership doctype
        # This functionality should be handled differently
        # if not self.dues_schedule:
        #     self.create_dues_schedule_from_membership()

        # Sync payment details from dues schedule
        # self.sync_payment_details_from_dues_schedule()

    def on_cancel_legacy(self):  # Renamed to avoid duplicate definition
        """Handle when membership is cancelled directly (not the same as member cancellation)"""
        from frappe.utils import add_months, getdate, nowdate, today

        # Check if membership is submitted (docstatus == 1) before enforcing the 1-year rule
        if self.docstatus == 1 and getdate(self.start_date):
            min_membership_period = add_months(getdate(self.start_date), 12)
            current_date = getdate(today())

            if current_date < min_membership_period:
                # Check if user is an admin
                is_admin = "System Manager" in frappe.get_roles(frappe.session.user)

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
                    frappe.throw(_("Membership cannot be cancelled before 1 year from start date"))

        self.status = "Cancelled"
        self.cancellation_date = self.cancellation_date or nowdate()

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
def cancel_membership(
    membership_name, cancellation_date=None, cancellation_reason=None, cancellation_type="Immediate"
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
        if getdate(cancellation_date) < min_membership_period:
            # Check if user is an admin
            is_admin = "System Manager" in frappe.get_roles(frappe.session.user)

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
def sync_membership_payments(membership_name=None):
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
def show_payment_history(membership_name):
    """
    Get payment history for a membership from linked dues schedule
    """
    membership = frappe.get_doc("Membership", membership_name)

    if not membership.dues_schedule:
        return []

    # Get payment history from dues schedule system
    from verenigingen.verenigingen.doctype.membership.enhanced_dues_schedule import (
        get_membership_payment_history,
    )

    return get_membership_payment_history(membership)


@frappe.whitelist()
def renew_membership(membership_name):
    """Renew a membership and return the new membership doc"""
    membership = frappe.get_doc("Membership", membership_name)
    return membership.renew_membership()


@frappe.whitelist()
def process_membership_statuses():
    """
    Scheduled job to update membership statuses based on dates and payments
    - Expire memberships past renewal date
    - Mark memberships as inactive if payment is overdue
    - Auto-renew memberships if configured
    """
    from frappe.utils import getdate, today

    # Get memberships that need status updates
    memberships = frappe.get_all(
        "Membership",
        filters={"docstatus": 1, "status": ["not in", ["Cancelled", "Expired"]]},
        fields=["name", "renewal_date", "status", "auto_renew"],
    )

    today_date = getdate(today())

    for membership_info in memberships:
        try:
            membership = frappe.get_doc("Membership", membership_info.name)

            # Sync payment details from dues schedule
            if membership.dues_schedule:
                membership.sync_payment_details_from_dues_schedule()

            # Check expiry - if past renewal date
            if membership.renewal_date and getdate(membership.renewal_date) < today_date:
                if membership.auto_renew:
                    # Auto-renew if configured
                    new_membership_name = membership.renew_membership()

                    # Submit the new membership
                    new_membership = frappe.get_doc("Membership", new_membership_name)
                    new_membership.docstatus = 1
                    new_membership.save()

                    frappe.logger().info(
                        f"Auto-renewed membership {membership.name} to {new_membership_name}"
                    )
                else:
                    # Just mark as expired if not auto-renewing
                    membership.status = "Expired"
                    membership.flags.ignore_validate_update_after_submit = True
                    membership.save()

                    frappe.logger().info(f"Marked membership {membership.name} as Expired")

            # Check if payment is overdue and update status
            elif (
                membership.unpaid_amount
                and flt(membership.unpaid_amount) > 0
                and membership.status != "Inactive"
            ):
                membership.status = "Inactive"
                membership.flags.ignore_validate_update_after_submit = True
                membership.save()

                frappe.logger().info(f"Marked membership {membership.name} as Inactive due to unpaid amount")

            # Check cancellations with end-of-period dates that have now been reached
            elif membership.cancellation_date and membership.cancellation_type == "End of Period":
                if getdate(membership.renewal_date) <= today_date:
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

    import frappe

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
def show_all_invoices(membership_name):
    """
    Get all invoices related to a membership through dues schedule
    or direct links
    """
    membership = frappe.get_doc("Membership", membership_name)
    invoices = []

    # Get invoices from dues schedule if available
    if membership.dues_schedule:
        from verenigingen.verenigingen.doctype.membership.enhanced_dues_schedule import (
            get_membership_payment_history,
        )

        payment_history = get_membership_payment_history(membership)

        for payment in payment_history:
            invoices.append(
                {
                    "invoice": payment.get("invoice"),
                    "date": payment.get("date"),
                    "amount": payment.get("amount"),
                    "outstanding": payment.get("outstanding", 0),
                    "status": payment.get("status"),
                    "due_date": payment.get("due_date"),
                    "source": "Dues Schedule",
                }
            )

    # Also look for invoices that might be directly linked to the membership
    direct_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "membership": membership.name,
        },
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "due_date"],
    )

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
def get_member_sepa_mandates(doctype, txt, searchfield, start, page_len, filters):
    """Get SEPA mandates for a specific member"""
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
def revert_to_standard_amount(membership_name, reason=None):
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

    # Get standard amount
    membership_type = frappe.get_doc("Membership Type", membership.membership_type)
    standard_amount = membership_type.amount

    return {
        "success": True,
        "old_amount": 0,  # Placeholder for backward compatibility
        "new_amount": standard_amount,
        "message": _("Reverted to standard amount: {0}").format(
            frappe.format_value(standard_amount, {"fieldtype": "Currency"})
        ),
    }


@frappe.whitelist()
def allow_multiple_memberships(member):
    """Set a flag to allow creating multiple memberships for a member"""
    frappe.flags.allow_multiple_memberships = True
    return True
