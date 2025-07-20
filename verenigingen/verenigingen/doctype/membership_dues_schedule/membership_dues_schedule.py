# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, add_years, flt, getdate, today


class MembershipDuesSchedule(Document):
    def validate(self):
        self.validate_permissions()
        self.validate_template_or_instance()
        if not self.is_template:
            self.validate_member_membership()
            self.validate_dates()

        self.validate_custom_frequency()  # Validate custom frequency settings
        self.set_dues_rate_from_membership_type()  # Set default before validation
        self.validate_dues_rate_configuration()

        # Track old values for history
        if not self.is_new() and not self.is_template:
            old_doc = frappe.get_doc(self.doctype, self.name)
            self._old_dues_rate = getattr(old_doc, "dues_rate", None)
            self._old_status = old_doc.status
            self._old_billing_frequency = old_doc.billing_frequency

    def validate_template_or_instance(self):
        """Validate template vs instance fields"""
        if self.is_template:
            # Templates must have membership type but no member
            if not self.membership_type:
                frappe.throw("Templates must specify a Membership Type")
            if self.member:
                frappe.throw("Templates cannot have a specific member")
            if self.template_reference:
                frappe.throw("Templates cannot reference other templates")
        else:
            # Instances must have member
            if not self.member:
                frappe.throw("Individual schedules must specify a member")
            # Validate uniqueness - one active schedule per member
            existing = frappe.db.exists(
                "Membership Dues Schedule",
                {
                    "member": self.member,
                    "is_template": 0,
                    "status": "Active",
                    "name": ["!=", self.name or ""],
                },
            )
            if existing:
                frappe.throw(f"Member {self.member} already has an active dues schedule: {existing}")

    def validate_member_membership(self):
        """Ensure the member has an active membership"""
        if self.member:
            # Check if member has any active membership
            active_membership = frappe.db.exists(
                "Membership", {"member": self.member, "status": "Active", "docstatus": 1}
            )
            if not active_membership:
                frappe.throw(f"Member {self.member} does not have an active membership")

            # Auto-link to membership type from active membership if not set
            if not self.membership_type:
                membership_type = frappe.db.get_value("Membership", active_membership, "membership_type")
                if membership_type:
                    self.membership_type = membership_type

    def validate_dates(self):
        """Validate schedule dates"""
        if self.last_invoice_date and self.next_invoice_date:
            if getdate(self.last_invoice_date) >= getdate(self.next_invoice_date):
                frappe.throw("Next Invoice Date must be after Last Invoice Date")

    def validate_custom_frequency(self):
        """Validate custom frequency settings"""
        if self.billing_frequency == "Custom":
            # Check if fields exist (might not exist during migration)
            frequency_number = getattr(self, "custom_frequency_number", None)
            frequency_unit = getattr(self, "custom_frequency_unit", None)

            if not frequency_number or frequency_number <= 0:
                frappe.throw("Custom frequency number must be a positive integer")
            if not frequency_unit:
                frappe.throw("Custom frequency unit must be specified when using custom billing")

    def validate_permissions(self):
        """Validate user permissions for editing this document"""
        # Skip permission check if ignore_permissions flag is set
        if getattr(self, "_ignore_permissions", False) or frappe.flags.ignore_permissions:
            return

        if not self.is_new() and self.has_value_changed("is_template"):
            frappe.throw("Cannot change template status after creation")

        user = frappe.session.user

        # System Manager and Administrator always have full access
        if user in ["Administrator", "System Manager"] or "System Manager" in frappe.get_roles(user):
            return

        # Check if user has Verenigingen Administrator role
        if "Verenigingen Administrator" in frappe.get_roles(user):
            return  # Full access

        # Template editing is restricted to Verenigingen Administrator only
        if self.is_template:
            frappe.throw("Only Verenigingen Administrators can edit template schedules")

        # For individual schedules, check various permission levels
        if not self.can_user_edit_schedule(user):
            frappe.throw("You don't have permission to edit this dues schedule")

    def can_user_edit_schedule(self, user):
        """Check if user can edit this individual (non-template) schedule"""
        if not self.member:
            return False

        # Check if user is the member themselves
        member_user = frappe.db.get_value("Member", self.member, "user")
        if member_user == user:
            return self.validate_member_edit()

        # Check if user has Verenigingen Manager role
        if "Verenigingen Manager" in frappe.get_roles(user):
            return True

        # Check if user is a chapter board member with finance permissions
        if self.is_chapter_board_with_finance(user):
            return True

        return False

    def validate_member_edit(self):
        """Validate what fields a member can edit on their own schedule"""
        # Members can only edit certain fields
        allowed_fields = [
            "dues_rate",
            "base_multiplier",
            "contribution_mode",
            "selected_tier",
            "uses_custom_amount",
            "custom_amount_reason",
            "notes",
            "status",
        ]

        # Check if any restricted fields were changed
        if self.is_new():
            return True

        # Check each field for changes
        for field in self.meta.fields:
            if field.fieldname in allowed_fields:
                continue

            if self.has_value_changed(field.fieldname):
                # Special case: dues_rate can be changed if it meets minimum
                if field.fieldname == "dues_rate":
                    if self.validate_dues_rate_change():
                        continue

                frappe.throw(f"Members cannot modify the field: {field.label}")

        return True

    def validate_dues_rate_change(self):
        """Validate if dues rate change meets requirements"""
        if not self.membership_type:
            return False

        membership_type = frappe.get_doc("Membership Type", self.membership_type)
        min_amount = getattr(membership_type, "minimum_contribution", 0) or 0

        if self.dues_rate < min_amount:
            frappe.throw(f"Dues rate cannot be less than minimum contribution: €{min_amount:.2f}")

        return True

    def is_chapter_board_with_finance(self, user):
        """Check if user is a chapter board member with financial permissions"""
        if not self.member:
            return False

        # Get member's chapter through Chapter Member relationship
        chapter = frappe.db.get_value("Chapter Member", {"member": self.member, "status": "Active"}, "parent")
        if not chapter:
            return False

        # Check if user is a board member of this chapter with finance permissions
        board_member = frappe.db.get_value(
            "Chapter Board Member",
            {
                "parent": chapter,
                "member": frappe.db.get_value("Member", {"user": user}, "name"),
                "is_active": 1,
            },
            ["name", "chapter_role"],
            as_dict=True,
        )

        if not board_member:
            return False

        # Check if the role has financial permissions
        if board_member.chapter_role:
            role_doc = frappe.get_doc("Chapter Role", board_member.chapter_role)
            return getattr(role_doc, "permissions_level", None) in ["Financial", "Admin"]

        return False

    def validate_dues_rate_configuration(self):
        """Validate dues rate based on contribution mode"""
        # Templates may not have all dues rate fields set
        if self.is_template:
            return

        if not self.membership_type:
            return

        membership_type = frappe.get_doc("Membership Type", self.membership_type)

        if self.contribution_mode == "Tier" and self.selected_tier:
            tier = frappe.get_doc("Membership Tier", self.selected_tier)
            self.dues_rate = tier.amount
        elif self.contribution_mode == "Calculator":
            self.dues_rate = membership_type.suggested_contribution * (self.base_multiplier or 1.0)
        elif self.contribution_mode == "Custom":
            if not self.uses_custom_amount:
                frappe.throw("Custom dues rate must be enabled for custom contribution mode")

        # Validate negative dues rates (zero is allowed for free memberships)
        if self.dues_rate < 0:
            frappe.throw("Dues rate cannot be negative")

        # Validate against minimum contribution from membership type
        if hasattr(membership_type, "minimum_contribution") and membership_type.minimum_contribution:
            if self.dues_rate < membership_type.minimum_contribution:
                # Allow zero dues rates and custom dues rates with approval
                if self.dues_rate == 0:
                    # Zero dues rate is allowed but requires special handling
                    if not self.custom_amount_reason:
                        frappe.throw("Zero dues rate memberships require a reason")
                elif not (self.uses_custom_amount and self.custom_amount_approved):
                    frappe.throw(
                        f"Dues rate cannot be less than minimum: €{membership_type.minimum_contribution:.2f} (requires custom dues rate approval)"
                    )

        # Check maximum contribution from Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        if settings.maximum_fee_multiplier:
            max_dues_rate = membership_type.amount * settings.maximum_fee_multiplier
            if self.dues_rate > max_dues_rate:
                if not self.uses_custom_amount or not self.custom_amount_approved:
                    frappe.throw(
                        f"Dues rate cannot exceed maximum: €{max_dues_rate:.2f} ({settings.maximum_fee_multiplier}x base fee - requires custom dues rate approval)"
                    )

        # Ensure currency precision (2 decimal places)
        self.dues_rate = flt(self.dues_rate, 2)

        # Additional template validation
        self.validate_template_fields()

    def validate_template_fields(self):
        """Additional validation for template-specific fields"""
        if self.is_template:
            # Templates should not have member-specific data
            # (Most member-specific fields have been removed)
            pass
        else:
            # Instances should have required member data
            if not self.member_name:
                if self.member:
                    member_doc = frappe.get_doc("Member", self.member)
                    self.member_name = member_doc.full_name

    def set_dues_rate_from_membership_type(self):
        """Set dues rate based on membership type if not already set"""
        if not self.dues_rate and self.membership_type:
            # Get the fee from membership type
            membership_type_doc = frappe.get_doc("Membership Type", self.membership_type)
            if hasattr(membership_type_doc, "amount"):
                self.dues_rate = membership_type_doc.amount
            elif hasattr(membership_type_doc, "fee"):
                self.dues_rate = membership_type_doc.fee

    def can_generate_invoice(self):
        """Check if invoice can be generated"""
        if self.is_template:
            return False, "Templates cannot generate invoices"

        if self.status != "Active":
            return False, "Schedule is not active"

        if not self.auto_generate:
            return False, "Auto generation is disabled"

        if self.test_mode:
            return True, "Test mode - can generate"

        # Check if member has active membership
        if self.member:
            active_membership = frappe.db.exists(
                "Membership", {"member": self.member, "status": "Active", "docstatus": 1}
            )
            if not active_membership:
                return False, "Member does not have active membership"

        # Check if it's time to generate invoice
        days_before = self.invoice_days_before or 30
        generate_on_date = add_days(self.next_invoice_date, -days_before)

        if getdate(today()) < getdate(generate_on_date):
            return False, f"Too early - will generate on {generate_on_date}"

        # Check if invoice already exists for this period
        if self.last_invoice_date == self.next_invoice_date:
            return False, "Invoice already generated for this period"

        return True, "Can generate invoice"

    def generate_invoice(self, force=False):
        """Generate invoice for the current period"""
        can_generate, reason = self.can_generate_invoice()

        if not can_generate and not force:
            frappe.log_error(f"Cannot generate invoice: {reason}", f"Membership Dues Schedule {self.name}")
            return None

        if self.test_mode:
            # In test mode, just log and update dates
            frappe.logger().info(
                f"TEST MODE: Would generate invoice for {self.member} - Dues Rate: {self.dues_rate}"
            )
            self.update_schedule_dates()
            return "TEST_INVOICE"

        # Create actual invoice
        invoice = self.create_sales_invoice()

        # Update schedule
        self.update_schedule_dates()

        # Payment history is automatically tracked via the Member Payment History table
        # when the invoice is created with the customer (member) reference

        return invoice

    def create_sales_invoice(self):
        """Create a sales invoice for membership dues"""
        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.member
        invoice.due_date = self.next_invoice_date
        invoice.posting_date = today()

        # Set payment method based on member's preferences
        payment_method = self.get_member_payment_method()
        if payment_method == "SEPA Direct Debit":
            active_mandate = self.get_member_active_mandate()
            if active_mandate:
                # Set SEPA-specific fields on invoice if needed
                invoice.sepa_mandate_id = active_mandate

        # Set payment terms if specified
        if self.payment_terms_template:
            invoice.payment_terms_template = self.payment_terms_template

        # Add membership dues item
        invoice.append(
            "items",
            {
                "item_code": self.get_membership_dues_item(),
                "qty": 1,
                "rate": self.dues_rate,
                "description": self.get_invoice_description(),
            },
        )

        # Add reference to this schedule (as a custom field or in remarks)
        invoice.remarks = (
            f"Generated from Membership Dues Schedule: {self.name}\n{self.get_invoice_description()}"
        )

        # Save and optionally submit
        invoice.insert()

        # Auto-submit if configured
        if frappe.db.get_single_value("Verenigingen Settings", "auto_submit_membership_invoices"):
            invoice.submit()

        return invoice.name

    def get_membership_dues_item(self):
        """Get or create the membership dues item"""
        if self.billing_frequency == "Custom":
            frequency_number = getattr(self, "custom_frequency_number", 1) or 1
            frequency_unit = getattr(self, "custom_frequency_unit", "Months") or "Months"
            frequency_desc = f"Every {frequency_number} {frequency_unit}"
            item_name = f"Membership Dues - Custom ({frequency_desc})"
        else:
            item_name = f"Membership Dues - {self.billing_frequency}"

        if not frappe.db.exists("Item", item_name):
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services"
            item.is_sales_item = 1
            item.is_service_item = 1
            item.insert()

        return item_name

    def get_invoice_description(self):
        """Generate invoice description"""
        period_start = self.last_invoice_date or self.next_invoice_date
        period_end = self.calculate_next_billing_date(self.next_invoice_date)

        return f"Membership dues for {self.member_name} ({self.membership_type}) - Period: {period_start} to {period_end}"

    def update_schedule_dates(self):
        """Update schedule dates after invoice generation"""
        self.last_invoice_date = self.next_invoice_date
        self.next_invoice_date = self.calculate_next_billing_date(self.next_invoice_date)
        self.save()

    def get_member_payment_method(self):
        """Get member's preferred payment method"""
        if not self.member:
            return "Bank Transfer"  # Default

        active_mandate = frappe.db.exists(
            "SEPA Mandate",
            {"member": self.member, "status": "Active", "is_active": 1, "used_for_memberships": 1},
        )

        if active_mandate:
            return "SEPA Direct Debit"
        else:
            return "Bank Transfer"

    def get_member_active_mandate(self):
        """Get member's active SEPA mandate if exists"""
        if not self.member:
            return None

        return frappe.db.get_value(
            "SEPA Mandate",
            {"member": self.member, "status": "Active", "is_active": 1, "used_for_memberships": 1},
            "name",
        )

    def calculate_next_billing_date(self, from_date=None):
        """Calculate next billing date based on frequency"""
        if not from_date:
            from_date = self.next_invoice_date or today()

        from_date = getdate(from_date)

        if self.billing_frequency == "Daily":
            return add_days(from_date, 1)
        elif self.billing_frequency == "Monthly":
            return add_months(from_date, 1)
        elif self.billing_frequency == "Quarterly":
            return add_months(from_date, 3)
        elif self.billing_frequency == "Semi-Annual":
            return add_months(from_date, 6)
        elif self.billing_frequency == "Annual":
            return add_years(from_date, 1)
        elif self.billing_frequency == "Custom":
            # Use custom frequency settings
            frequency_number = getattr(self, "custom_frequency_number", 1) or 1
            frequency_unit = getattr(self, "custom_frequency_unit", "Months") or "Months"

            if frequency_unit == "Days":
                return add_days(from_date, frequency_number)
            elif frequency_unit == "Weeks":
                return add_days(from_date, frequency_number * 7)
            elif frequency_unit == "Months":
                return add_months(from_date, frequency_number)
            elif frequency_unit == "Years":
                return add_years(from_date, frequency_number)
            else:
                # Fallback to monthly if unit is invalid
                return add_months(from_date, 1)
        else:
            # Unknown frequency - default to monthly
            return add_months(from_date, 1)

    def pause_schedule(self, reason=None):
        """Pause the dues schedule"""
        self.status = "Paused"
        if reason:
            self.notes = (
                f"{self.notes}\n\nPaused on {today()}: {reason}"
                if self.notes
                else f"Paused on {today()}: {reason}"
            )
        self.save()

    def resume_schedule(self, new_next_date=None):
        """Resume the dues schedule"""
        self.status = "Active"
        if new_next_date:
            self.next_invoice_date = new_next_date
        self.notes = f"{self.notes}\n\nResumed on {today()}" if self.notes else f"Resumed on {today()}"
        self.save()

    @staticmethod
    def create_from_template(member_name, template_name=None, membership_type=None):
        """Create an individual dues schedule from a template"""

        # Determine template to use
        if template_name:
            template = frappe.get_doc("Membership Dues Schedule", template_name)
            if not template.is_template:
                frappe.throw(f"{template_name} is not a template")
        elif membership_type:
            # Find template for membership type
            template_name = frappe.db.get_value(
                "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1}, "name"
            )
            if not template_name:
                frappe.throw(f"No template found for membership type {membership_type}")
            template = frappe.get_doc("Membership Dues Schedule", template_name)
        else:
            # Auto-detect from member's membership type
            active_membership = frappe.db.get_value(
                "Membership",
                {"member": member_name, "status": "Active", "docstatus": 1},
                ["membership_type", "name"],
            )
            if not active_membership:
                frappe.throw(f"Member {member_name} has no active membership")

            membership_type = active_membership[0]
            template_name = frappe.db.get_value(
                "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1}, "name"
            )
            if not template_name:
                frappe.throw(f"No template found for membership type {membership_type}")
            template = frappe.get_doc("Membership Dues Schedule", template_name)

        # Check if member already has a schedule
        existing = frappe.db.exists("Membership Dues Schedule", {"member": member_name, "is_template": 0})
        if existing:
            frappe.throw(f"Member {member_name} already has a dues schedule: {existing}")

        # Create new individual schedule
        schedule = frappe.new_doc("Membership Dues Schedule")

        # Copy template fields
        template_fields = [
            "membership_type",
            "billing_frequency",
            "custom_frequency_number",
            "custom_frequency_unit",
            "contribution_mode",
            "base_multiplier",
            "minimum_amount",
            "suggested_amount",
            "invoice_days_before",
            "payment_terms_template",
            "auto_generate",
        ]

        for field in template_fields:
            if hasattr(template, field) and getattr(template, field):
                setattr(schedule, field, getattr(template, field))

        # Set instance-specific fields
        schedule.is_template = 0
        schedule.member = member_name
        schedule.template_reference = template.name
        schedule.status = "Active"
        schedule.schedule_name = f"Schedule-{member_name}-{template.membership_type}"

        # Set member-specific data
        member = frappe.get_doc("Member", member_name)
        schedule.member_name = member.full_name

        # Set initial billing date based on member anniversary and frequency
        next_billing = schedule.calculate_next_billing_date()
        if next_billing:
            schedule.next_invoice_date = next_billing
        else:
            schedule.next_invoice_date = today()

        # Insert and return
        schedule.insert()

        # Link back to member
        member.dues_schedule = schedule.name
        member.save()

        return schedule.name

    def after_save(self):
        """Track billing history changes"""
        if self.is_template or not self.member:
            return

        # Check if this is a new schedule or if key fields changed
        if self.is_new():
            self.add_billing_history_entry("New Schedule", None, self.dues_rate)
        else:
            # Check for dues rate change
            if hasattr(self, "_old_dues_rate") and self._old_dues_rate != self.dues_rate:
                self.add_billing_history_entry("Fee Adjustment", self._old_dues_rate, self.dues_rate)

            # Check for status change
            if hasattr(self, "_old_status") and self._old_status != self.status:
                if self.status == "Cancelled":
                    self.add_billing_history_entry("Schedule Cancelled", self.dues_rate, self.dues_rate)
                elif self._old_status == "Paused" and self.status == "Active":
                    self.add_billing_history_entry("Schedule Resumed", self.dues_rate, self.dues_rate)

            # Check for billing frequency change
            if (
                hasattr(self, "_old_billing_frequency")
                and self._old_billing_frequency != self.billing_frequency
            ):
                self.add_billing_history_entry("Billing Frequency Change", self.dues_rate, self.dues_rate)

    def add_billing_history_entry(self, change_type, old_rate, new_rate):
        """Add entry to member's billing history"""
        try:
            member_doc = frappe.get_doc("Member", self.member)

            # Determine reason based on context
            reason = (
                self.custom_amount_reason
                if self.uses_custom_amount
                else f"{change_type} - {self.schedule_name}"
            )

            # Check if this change is from an amendment
            amendment_request = None
            if frappe.db.exists("Contribution Amendment Request", {"new_dues_schedule": self.name}):
                amendment_request = frappe.db.get_value(
                    "Contribution Amendment Request", {"new_dues_schedule": self.name}, "name"
                )

            # Add history entry
            member_doc.append(
                "fee_change_history",
                {
                    "change_date": frappe.utils.now_datetime(),
                    "dues_schedule": self.name,
                    "billing_frequency": self.billing_frequency,
                    "old_dues_rate": old_rate,
                    "new_dues_rate": new_rate,
                    "change_type": change_type,
                    "reason": reason,
                    "amendment_request": amendment_request,
                    "changed_by": frappe.session.user,
                },
            )

            member_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(f"Error adding billing history: {str(e)}", "Billing History Update")


@frappe.whitelist()
def generate_dues_invoices(test_mode=False):
    """Scheduled job to generate membership dues invoices"""

    # Get all active schedules that need processing
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "next_invoice_date": ["<=", add_days(today(), 30)]},
        pluck="name",
    )

    results = {"processed": 0, "generated": 0, "errors": [], "invoices": []}

    for schedule_name in schedules:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

            # Skip if test_mode flag doesn't match
            if test_mode and not schedule.test_mode:
                continue
            elif not test_mode and schedule.test_mode:
                continue

            can_generate, reason = schedule.can_generate_invoice()

            if can_generate:
                invoice = schedule.generate_invoice()
                if invoice:
                    results["generated"] += 1
                    results["invoices"].append(
                        {"schedule": schedule_name, "member": schedule.member_name, "invoice": invoice}
                    )

            results["processed"] += 1

        except Exception as e:
            error_msg = f"Error processing schedule {schedule_name}: {str(e)}"
            frappe.log_error(error_msg, "Membership Dues Generation")
            results["errors"].append(error_msg)

    # Log results
    frappe.logger().info(
        f"Membership dues generation completed: {results['generated']} invoices from {results['processed']} schedules"
    )

    return results


@frappe.whitelist()
def create_schedule_from_template(member_name, template_name=None):
    """API endpoint to create schedule from template"""
    return MembershipDuesSchedule.create_from_template(member_name, template_name)


@frappe.whitelist()
def create_template_for_membership_type(membership_type, template_name=None):
    """Create a new template for a membership type"""
    if not template_name:
        template_name = f"Template-{membership_type}"

    # Check if template already exists
    existing = frappe.db.exists(
        "Membership Dues Schedule", {"membership_type": membership_type, "is_template": 1}
    )
    if existing:
        frappe.throw(f"Template already exists for {membership_type}: {existing}")

    # Get membership type details
    membership_type_doc = frappe.get_doc("Membership Type", membership_type)

    # Create template
    template = frappe.new_doc("Membership Dues Schedule")
    template.is_template = 1
    template.schedule_name = template_name
    template.membership_type = membership_type
    template.status = "Active"

    # Set defaults from membership type
    template.billing_frequency = getattr(membership_type_doc, "billing_frequency", "Annual")
    template.contribution_mode = getattr(membership_type_doc, "contribution_mode", "Calculator")
    template.minimum_amount = getattr(membership_type_doc, "minimum_contribution", 0)
    template.suggested_amount = getattr(membership_type_doc, "suggested_contribution", 0)
    template.invoice_days_before = getattr(membership_type_doc, "invoice_days_before", 30)
    template.auto_generate = 1

    template.insert()

    # Link template back to membership type
    membership_type_doc.dues_schedule_template = template.name
    membership_type_doc.save()

    return template.name


@frappe.whitelist()
def get_member_dues_schedule(member=None):
    """Get dues schedule for a member (with permission checks)"""
    user = frappe.session.user

    # If no member specified, try to get current user's member record
    if not member:
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if not member:
            frappe.throw("No member record found for current user")

    # Check permissions
    member_user = frappe.db.get_value("Member", member, "user")
    if member_user != user:
        # Check if user has permission to view this member's schedule
        roles = frappe.get_roles(user)
        if not any(
            role in roles for role in ["Verenigingen Manager", "Verenigingen Administrator", "System Manager"]
        ):
            # Check if user is chapter board with finance permissions
            schedule_doc = frappe.new_doc("Membership Dues Schedule")
            schedule_doc.member = member
            if not schedule_doc.is_chapter_board_with_finance(user):
                frappe.throw("You don't have permission to view this member's dues schedule")

    # Get the schedule
    schedule_name = frappe.db.get_value(
        "Membership Dues Schedule", {"member": member, "is_template": 0}, "name"
    )

    if not schedule_name:
        return None

    return frappe.get_doc("Membership Dues Schedule", schedule_name)


@frappe.whitelist()
def update_member_contribution(schedule_name, updates):
    """Update member's contribution settings with permission checks"""
    if isinstance(updates, str):
        updates = frappe.parse_json(updates)

    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

    # Permission check happens in validate()

    # Only allow updating specific fields
    allowed_updates = {
        "contribution_mode": updates.get("contribution_mode"),
        "selected_tier": updates.get("selected_tier"),
        "base_multiplier": updates.get("base_multiplier"),
        "uses_custom_amount": updates.get("uses_custom_amount"),
        "custom_amount_reason": updates.get("custom_amount_reason"),
        "dues_rate": updates.get("dues_rate"),
        "notes": updates.get("notes"),
    }

    # Remove None values
    allowed_updates = {k: v for k, v in allowed_updates.items() if v is not None}

    # Update the document
    for field, value in allowed_updates.items():
        setattr(schedule, field, value)

    schedule.save()

    return {"success": True, "schedule": schedule.as_dict()}


@frappe.whitelist()
def create_test_schedule(member_name, membership_name=None):
    """Create a test dues schedule for development"""
    try:
        return MembershipDuesSchedule.create_from_template(member_name)
    except Exception:
        # Fallback to manual creation if no template exists
        # Get membership if not provided
        if not membership_name:
            membership_name = frappe.db.get_value("Membership", {"member": member_name}, "name")

        if not membership_name:
            frappe.throw(f"No membership found for member {member_name}")

        # Create test schedule
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.is_template = 0
        schedule.member = member_name
        schedule.schedule_name = f"Test-Schedule-{member_name}"
        schedule.billing_frequency = "Monthly"
        schedule.dues_rate = 10.00  # Test dues rate
        schedule.next_invoice_date = today()
        schedule.invoice_days_before = 0  # Generate immediately
        schedule.test_mode = 1
        schedule.auto_generate = 1
        schedule.status = "Test"
        schedule.insert()

        return schedule.name
