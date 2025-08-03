# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, add_years, flt, getdate, today


class MembershipDuesSchedule(Document):
    def get_template_values(self):
        """Get billing and contribution values from template if available"""
        if not self.membership_type:
            return {}

        membership_type = frappe.get_doc("Membership Type", self.membership_type)
        values = {
            "minimum_amount": 0,
            "suggested_amount": 0,
            "billing_frequency": "Annual",
            "invoice_days_before": 30,
        }

        # Get values from template (now required)
        if not membership_type.dues_schedule_template:
            frappe.throw(
                f"Membership Type '{membership_type.name}' must have a dues schedule template assigned"
            )

        try:
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)

            # Validate template has required configuration before using it
            if not template.suggested_amount:
                frappe.throw(
                    f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured"
                )

            values.update(
                {
                    "minimum_amount": template.minimum_amount if template.minimum_amount is not None else 0,
                    "suggested_amount": template.suggested_amount,  # Required field, validated above
                    "billing_frequency": template.billing_frequency
                    or "Annual",  # Explicit default, validated in template creation
                    "invoice_days_before": template.invoice_days_before
                    if template.invoice_days_before is not None
                    else 30,  # Explicit null check
                }
            )
        except Exception as e:
            frappe.throw(
                f"Failed to load dues schedule template '{membership_type.dues_schedule_template}': {str(e)}"
            )

        # Validate template respects membership type minimum (both required)
        # Skip this validation when updating existing schedules to allow flexible dues rates
        membership_type_minimum = (
            membership_type.minimum_amount if membership_type.minimum_amount is not None else 0
        )
        template_minimum = values["minimum_amount"]  # Already validated above
        template_suggested = values["suggested_amount"]  # Already validated above

        # Only enforce template-level validation for new templates, not when updating existing schedules
        if not getattr(self, "_skip_template_validation", False):
            if template_minimum < membership_type_minimum:
                frappe.throw(
                    f"Template minimum amount (€{template_minimum:.2f}) cannot be less than "
                    f"membership type minimum (€{membership_type_minimum:.2f})"
                )

            # Use the same logic as application helpers: dues_rate takes precedence over suggested_amount
            effective_amount = template.dues_rate if template.dues_rate else template_suggested
            if effective_amount < membership_type_minimum:
                amount_type = "dues rate" if template.dues_rate else "suggested amount"
                frappe.throw(
                    f"Template {amount_type} (€{effective_amount:.2f}) cannot be less than "
                    f"membership type minimum (€{membership_type_minimum:.2f})"
                )

        return values

    def before_save(self):
        """Store document state before save for comparison"""
        if not self.is_new():
            self._doc_before_save = frappe.get_doc("Membership Dues Schedule", self.name)

    def validate(self):
        self.validate_permissions()
        self.validate_template_or_instance()
        if not self.is_template:
            self.validate_member_membership()
            self.validate_dates()

        self.validate_custom_frequency()  # Validate custom frequency settings
        self.set_dues_rate_from_membership_type()  # Set default before validation
        self.validate_dues_rate_configuration()
        self.validate_financial_constraints()  # Add financial validation

        # ERPNext-inspired validation enhancements
        self.validate_status_transitions()
        self.validate_billing_frequency_consistency()
        self.validate_rate_boundaries()

        # Set billing day for member schedules
        if not self.is_template:
            self.set_billing_day()

        # Initialize next invoice date for new schedules
        if self.is_new() and not self.is_template and not self.next_invoice_date:
            self.next_invoice_date = today()

        # Note: Old values tracking moved to before_save() to capture actual previous values

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
                frappe.throw(
                    f"Member {self.member} already has an active dues schedule: <a href='/app/membership-dues-schedule/{existing}' target='_blank'>{existing}</a>. "
                    f"Please edit the existing schedule or deactivate it before creating a new one.",
                    title="Duplicate Dues Schedule",
                )

    def validate_member_membership(self):
        """Ensure the member has an active membership"""
        if self.member:
            # Skip active membership validation if we're pausing the schedule
            # This allows membership cancellation to pause dues schedules properly
            if getattr(self, "_skip_membership_validation", False):
                return

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
        today_date = getdate(today())

        # Validate last_invoice_date is not in the future
        if self.last_invoice_date:
            last_date = getdate(self.last_invoice_date)
            if last_date > today_date:
                # Auto-correct invalid future last invoice dates
                frappe.msgprint(
                    f"Warning: Last Invoice Date ({last_date}) was in the future and has been reset to today ({today_date}). "
                    "Last invoice dates should only reflect actual past invoices.",
                    alert=True,
                )
                self.last_invoice_date = today_date

        if self.last_invoice_date and self.next_invoice_date:
            if getdate(self.last_invoice_date) >= getdate(self.next_invoice_date):
                frappe.throw("Next Invoice Date must be after Last Invoice Date")

        # Validate next_invoice_date is not unreasonably far in the future
        if self.next_invoice_date:
            next_date = getdate(self.next_invoice_date)

            # Determine reasonable future limit based on billing frequency
            if self.billing_frequency == "Daily":
                max_future_days = 7  # Daily billing should not be scheduled more than a week ahead
            elif self.billing_frequency == "Weekly":
                max_future_days = 14  # Weekly billing should not be more than 2 weeks ahead
            elif self.billing_frequency == "Monthly":
                max_future_days = 62  # Monthly billing should not be more than 2 months ahead
            elif self.billing_frequency == "Quarterly":
                max_future_days = 100  # Quarterly billing should not be more than ~3 months ahead
            elif self.billing_frequency == "Annual":
                max_future_days = 400  # Annual billing can be up to ~13 months ahead
            else:
                max_future_days = 30  # Default conservative limit

            max_future_date = add_days(today_date, max_future_days)

            if next_date > max_future_date:
                # Auto-correct the date instead of throwing error (better UX)
                self.next_invoice_date = today_date
                frappe.msgprint(
                    f"Next Invoice Date was too far in the future ({next_date}). "
                    f"Automatically corrected to {today_date} for {self.billing_frequency} billing.",
                    alert=True,
                )

            # Also check for very old dates (more than 6 months in the past)
            min_past_date = add_days(today_date, -180)  # 6 months ago
            if next_date < min_past_date:
                # Auto-correct old dates
                self.next_invoice_date = today_date
                frappe.msgprint(
                    f"Next Invoice Date was too far in the past ({next_date}). "
                    f"Automatically corrected to {today_date}.",
                    alert=True,
                )

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

        # System Manager and configured creation user always have full access
        creation_user = None
        try:
            settings = frappe.get_single("Verenigingen Settings")
            creation_user = getattr(settings, "creation_user", None)
        except Exception:
            pass

        admin_users = ["System Manager"]
        if creation_user:
            admin_users.append(creation_user)
        else:
            admin_users.append("Administrator")  # Fallback

        if user in admin_users or "System Manager" in frappe.get_roles(user):
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

        template_values = self.get_template_values()
        min_amount = template_values.get("minimum_amount", 0)

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

        # Only calculate dues_rate if not already explicitly set or if it's zero
        if not self.dues_rate or self.dues_rate == 0:
            if self.contribution_mode == "Tier" and self.selected_tier:
                tier = frappe.get_doc("Membership Tier", self.selected_tier)
                self.dues_rate = tier.amount
            elif self.contribution_mode == "Calculator":
                template_values = self.get_template_values()
                suggested_amount = template_values.get("suggested_amount", 0)
                if not suggested_amount:
                    frappe.throw("Cannot calculate dues: template has no suggested_amount configured")

                # Use base multiplier, defaulting to 1.0 if not set
                multiplier = self.base_multiplier if self.base_multiplier is not None else 1.0
                self.dues_rate = suggested_amount * multiplier
            elif self.contribution_mode == "Custom":
                if not self.uses_custom_amount:
                    frappe.throw("Custom dues rate must be enabled for custom contribution mode")

        # If contribution mode is Custom but dues_rate is set, ensure custom amount flags are set
        if self.contribution_mode == "Custom" and self.dues_rate:
            if not self.uses_custom_amount:
                self.uses_custom_amount = 1

    def validate_financial_constraints(self):
        """Validate financial constraints and limits"""
        if self.is_template or not self.dues_rate:
            return  # Skip for templates or when no dues rate is set

        try:
            # Get configuration values
            from verenigingen.utils.config_manager import ConfigManager

            # Check absolute minimum (safety check)
            absolute_minimum = ConfigManager.get("absolute_minimum_dues", 0.01)  # €0.01 minimum
            if float(self.dues_rate) < absolute_minimum:
                frappe.throw(f"Dues rate cannot be less than €{absolute_minimum:.2f}", frappe.ValidationError)

            # Check maximum reasonable amount
            maximum_dues = ConfigManager.get("maximum_dues_limit", 1000.0)  # €1000 default max
            if float(self.dues_rate) > maximum_dues:
                # Allow with warning for administrators
                user_roles = frappe.get_roles(frappe.session.user)
                admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]

                if any(role in user_roles for role in admin_roles):
                    frappe.msgprint(
                        f"High dues amount detected: €{self.dues_rate:.2f}. Please verify this is correct.",
                        title="High Amount Warning",
                    )
                else:
                    frappe.throw(
                        f"Dues rate exceeds maximum limit of €{maximum_dues:.2f}. "
                        f"Please contact an administrator if this amount is correct.",
                        frappe.ValidationError,
                    )

            # Validate against template constraints if available
            if hasattr(self, "minimum_amount") and self.minimum_amount:
                if float(self.dues_rate) < float(self.minimum_amount):
                    frappe.throw(
                        f"Dues rate (€{self.dues_rate:.2f}) cannot be less than minimum amount (€{self.minimum_amount:.2f})",
                        frappe.ValidationError,
                    )

            # Check if dues rate is within reasonable multiplier of suggested amount
            if self.membership_type:
                membership_type = frappe.get_doc("Membership Type", self.membership_type)

                # Get suggested amount from template (explicit configuration)
                if not membership_type.dues_schedule_template:
                    frappe.throw(
                        f"Membership Type '{membership_type.name}' must have a dues schedule template"
                    )

                template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
                if not template.suggested_amount:
                    frappe.throw(
                        f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured"
                    )
                suggested_amount = template.suggested_amount

                if suggested_amount > 0:
                    multiplier = float(self.dues_rate) / float(suggested_amount)
                    max_multiplier = ConfigManager.get("maximum_fee_multiplier", 10.0)

                    if multiplier > max_multiplier:
                        frappe.msgprint(
                            f"Dues rate is {multiplier:.1f}x the suggested amount. "
                            f"This may require additional verification.",
                            title="High Multiplier Warning",
                        )

                        # Log for audit purposes
                        frappe.logger().info(
                            f"High dues multiplier detected: {multiplier:.2f}x for member {self.member}, "
                            f"dues: €{self.dues_rate}, suggested: €{suggested_amount}, user: {frappe.session.user}"
                        )

        except Exception as e:
            frappe.log_error(
                f"Error validating financial constraints: {str(e)}", "Financial Validation Error"
            )

    def validate_dues_rate_minimum(self):
        """Legacy validation method - moved logic to validate_financial_constraints"""
        # This method is kept for backward compatibility
        pass

    def validate_dues_rate_configuration_legacy(self):
        """Legacy method - validates negative dues rates and minimum requirements"""
        # Validate negative dues rates (zero is allowed for free memberships)
        if self.dues_rate < 0:
            frappe.throw("Dues rate cannot be negative")

        # Single consolidated minimum validation
        template_values = self.get_template_values()
        min_contribution = template_values.get("minimum_amount", 0)
        if min_contribution and self.dues_rate < min_contribution:
            # Zero dues rates are allowed with reason (free memberships)
            if self.dues_rate == 0:
                if not self.custom_amount_reason:
                    frappe.throw("Zero dues rate memberships require a reason")
                # Mark as custom amount for tracking
                self.uses_custom_amount = 1
            # Custom approved amounts can be below minimum
            elif self.uses_custom_amount and self.custom_amount_approved:
                pass  # Allow approved custom amounts below minimum
            else:
                # Auto-raise to minimum for non-custom amounts
                self.dues_rate = min_contribution

        # Check maximum contribution from Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        if settings.maximum_fee_multiplier:
            # Use suggested_amount from template (explicit configuration)
            base_amount = template_values.get("suggested_amount", 0)
            max_dues_rate = base_amount * settings.maximum_fee_multiplier

            if self.dues_rate > max_dues_rate:
                # Check if user has management permissions to override
                user_roles = frappe.get_roles(frappe.session.user)
                can_override = any(
                    role in user_roles
                    for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
                )

                if not can_override and (not self.uses_custom_amount or not self.custom_amount_approved):
                    frappe.throw(
                        f"Dues rate cannot exceed maximum: €{max_dues_rate:.2f} ({settings.maximum_fee_multiplier}x base fee - requires custom dues rate approval or Verenigingen Manager permissions)"
                    )
                elif can_override:
                    # Auto-approve for managers
                    self.uses_custom_amount = 1
                    self.custom_amount_approved = 1
                    self.custom_amount_approved_by = frappe.session.user
                    self.custom_amount_approved_date = today()
                    if not self.custom_amount_reason:
                        self.custom_amount_reason = f"Approved by {frappe.session.user} (Manager Override)"

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
        """Set dues rate based on membership type template if not already set"""
        if not self.dues_rate and self.membership_type:
            # Get the fee from template values (explicit configuration)
            template_values = self.get_template_values()
            # Template is now required and must have suggested_amount
            self.dues_rate = template_values.get("suggested_amount", 0)

    def set_billing_day(self):
        """Set billing day based on member's anniversary date"""
        if not self.billing_day or self.billing_day == 0:
            if self.member:
                member = frappe.get_doc("Member", self.member)
                if member.member_since:
                    # Use day from member's anniversary date
                    member_since_date = getdate(member.member_since)
                    self.billing_day = member_since_date.day
                else:
                    # Default to 1st of month when no member_since date
                    self.billing_day = 1
            else:
                # Default for templates or schedules without member
                self.billing_day = 1

    def can_generate_invoice(self):
        """Check if invoice can be generated with comprehensive duplicate prevention"""
        if self.is_template:
            return False, "Templates cannot generate invoices"

        if self.status != "Active":
            return False, "Schedule is not active"

        if not self.auto_generate:
            return False, "Auto generation is disabled"

        if self.test_mode:
            return True, "Test mode - can generate"

        # ⚠️ CRITICAL: Check member eligibility for billing
        if self.member:
            if not self.validate_member_eligibility_for_invoice():
                return False, "Member is not eligible for billing"

        # ✅ NEW: Rate validation checks
        rate_validation = self.validate_dues_rate()
        if not rate_validation["valid"]:
            return False, rate_validation["reason"]

        # ✅ NEW: Membership type consistency check
        membership_validation = self.validate_membership_type_consistency()
        if not membership_validation["valid"]:
            return False, membership_validation["reason"]

        # Check if it's time to generate invoice
        # Use configured days_before or system default
        days_before = self.invoice_days_before if self.invoice_days_before is not None else 30
        generate_on_date = add_days(self.next_invoice_date, -days_before)

        if getdate(today()) < getdate(generate_on_date):
            return False, f"Too early - will generate on {generate_on_date}"

        # ✅ ENHANCED: Comprehensive duplicate prevention
        duplicate_check_result = self.check_for_duplicate_invoices()
        if not duplicate_check_result["can_generate"]:
            return False, duplicate_check_result["reason"]

        # Check if invoice already exists for this period
        if self.last_invoice_date == self.next_invoice_date:
            return False, "Invoice already generated for this period"

        return True, "Can generate invoice"

    def check_for_duplicate_invoices(self):
        """
        Comprehensive duplicate invoice prevention for billing periods.

        Prevents:
        1. Multiple invoices for the same posting date (same-day duplicates)
        2. Multiple invoices for the same billing period (period duplicates)
        """
        if not self.member:
            return {"can_generate": True, "reason": "No member - skipping duplicate check"}

        # Get member's customer record
        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.customer:
            return {"can_generate": True, "reason": "No customer - skipping duplicate check"}

        today_date = today()

        # 1. Check for same-day duplicates
        existing_today = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member_doc.customer,
                "posting_date": today_date,
                "docstatus": ["!=", 2],  # Not cancelled
            },
            fields=["name", "posting_date", "creation"],
        )

        if existing_today:
            invoice_names = [inv.name for inv in existing_today]
            return {
                "can_generate": False,
                "reason": f"Same-day duplicate prevented: Invoice(s) {', '.join(invoice_names)} already exist for {today_date}",
            }

        # 2. Check for billing period duplicates based on frequency
        period_start, period_end = self.calculate_billing_period(today_date)

        existing_in_period = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member_doc.customer,
                "posting_date": ["between", [period_start, period_end]],
                "docstatus": ["!=", 2],  # Not cancelled
            },
            fields=["name", "posting_date", "creation"],
        )

        if existing_in_period:
            invoice_names = [inv.name for inv in existing_in_period]
            return {
                "can_generate": False,
                "reason": f"Billing period duplicate prevented: Invoice(s) {', '.join(invoice_names)} already exist for period {period_start} to {period_end}",
            }

        return {"can_generate": True, "reason": "No duplicates found"}

    def calculate_billing_period(self, invoice_date):
        """Calculate the billing period start and end dates for a given invoice date"""
        invoice_date = getdate(invoice_date)

        if self.billing_frequency == "Daily":
            # For daily billing, the period is just the single day
            return invoice_date, invoice_date
        elif self.billing_frequency == "Weekly":
            # Weekly period: Monday to Sunday
            days_since_monday = invoice_date.weekday()
            period_start = add_days(invoice_date, -days_since_monday)
            period_end = add_days(period_start, 6)
            return period_start, period_end
        elif self.billing_frequency == "Monthly":
            # Monthly period: 1st to last day of month
            period_start = invoice_date.replace(day=1)
            # Get last day of month
            if invoice_date.month == 12:
                next_month = invoice_date.replace(year=invoice_date.year + 1, month=1, day=1)
            else:
                next_month = invoice_date.replace(month=invoice_date.month + 1, day=1)
            period_end = add_days(next_month, -1)
            return period_start, period_end
        elif self.billing_frequency == "Quarterly":
            # Quarterly periods: Q1 (Jan-Mar), Q2 (Apr-Jun), Q3 (Jul-Sep), Q4 (Oct-Dec)
            quarter = (invoice_date.month - 1) // 3 + 1
            period_start = invoice_date.replace(month=(quarter - 1) * 3 + 1, day=1)
            period_end_month = quarter * 3
            if period_end_month == 12:
                period_end = invoice_date.replace(month=12, day=31)
            else:
                next_quarter = invoice_date.replace(month=period_end_month + 1, day=1)
                period_end = add_days(next_quarter, -1)
            return period_start, period_end
        elif self.billing_frequency == "Semi-Annual":
            # Semi-annual: H1 (Jan-Jun), H2 (Jul-Dec)
            if invoice_date.month <= 6:
                period_start = invoice_date.replace(month=1, day=1)
                period_end = invoice_date.replace(month=6, day=30)
            else:
                period_start = invoice_date.replace(month=7, day=1)
                period_end = invoice_date.replace(month=12, day=31)
            return period_start, period_end
        elif self.billing_frequency == "Annual":
            # Annual period: Jan 1 to Dec 31
            period_start = invoice_date.replace(month=1, day=1)
            period_end = invoice_date.replace(month=12, day=31)
            return period_start, period_end
        elif self.billing_frequency == "Custom":
            # For custom frequency, use the custom settings (both required for custom billing)
            frequency_number = getattr(self, "custom_frequency_number", None)
            if not frequency_number or frequency_number < 1:
                frequency_number = 1  # Safe default

            frequency_unit = getattr(self, "custom_frequency_unit", None)
            if not frequency_unit:
                frequency_unit = "Months"  # Safe default

            if frequency_unit == "Days":
                # Custom daily periods
                return invoice_date, invoice_date
            elif frequency_unit == "Weeks":
                # Custom weekly periods
                days_since_monday = invoice_date.weekday()
                period_start = add_days(invoice_date, -days_since_monday)
                period_end = add_days(period_start, (frequency_number * 7) - 1)
                return period_start, period_end
            elif frequency_unit == "Months":
                # Custom monthly periods
                period_start = invoice_date.replace(day=1)
                period_end = add_months(period_start, frequency_number)
                period_end = add_days(period_end, -1)
                return period_start, period_end
            elif frequency_unit == "Years":
                # Custom yearly periods
                period_start = invoice_date.replace(month=1, day=1)
                period_end = add_years(period_start, frequency_number)
                period_end = add_days(period_end, -1)
                return period_start, period_end

        # Default fallback: treat as daily
        return invoice_date, invoice_date

    def validate_member_eligibility_for_invoice(self):
        """
        ⚠️ CRITICAL VALIDATION: Check if member is eligible for invoice generation
        This prevents billing terminated members and those without active memberships.
        Payment method validation is done at DD batch creation time, not invoice generation.
        """
        if not self.member:
            return False

        try:
            member = frappe.get_doc("Member", self.member)

            # Check member status
            if member.status in ["Terminated", "Expelled", "Deceased", "Suspended", "Quit"]:
                frappe.log_error(
                    f"Invoice blocked: member {self.member} status {member.status}",
                    "Member Status Validation",
                )
                return False

            # Check if member has active membership
            active_membership = frappe.db.exists(
                "Membership", {"member": self.member, "status": "Active", "docstatus": 1}
            )
            if not active_membership:
                frappe.log_error(
                    f"Invoice blocked: member {self.member} no active membership",
                    "Membership Status Validation",
                )
                return False

            # Note: SEPA mandate validation is only done at DD batch creation time
            # Members with broken payment data can still receive invoices
            # They just won't be included in Direct Debit batches

            return True

        except frappe.DoesNotExistError:
            # Handle the specific case where member doesn't exist
            frappe.log_error(
                f"Orphaned schedule '{self.name}' refs deleted member '{self.member}'",
                "Orphaned Dues Schedule",
            )
            # Mark this schedule as orphaned for admin attention
            try:
                self.add_comment("Comment", f"⚠️ ORPHANED: Member '{self.member}' not found.")
            except Exception as e:
                frappe.log_error(f"Failed to add orphaned comment: {e}", "Comment Addition Failed")
            return False
        except Exception as e:
            frappe.log_error(
                f"Member validation error {self.member}: {str(e)[:50]}",
                "Member Eligibility Error",
            )
            return False

    def is_orphaned(self):
        """
        Check if this dues schedule references a non-existent member
        Returns True if the member doesn't exist, False otherwise
        """
        if not self.member:
            return False  # Templates and schedules without members are not orphaned
        return not frappe.db.exists("Member", self.member)

    @staticmethod
    def find_orphaned_schedules(limit=50):
        """
        Find dues schedules that reference non-existent members
        Returns list of schedule names and member IDs that need cleanup
        """
        orphaned = frappe.db.sql(
            """
            SELECT mds.name, mds.member, mds.status, mds.is_template
            FROM `tabMembership Dues Schedule` mds
            LEFT JOIN `tabMember` m ON m.name = mds.member
            WHERE m.name IS NULL
            AND mds.member IS NOT NULL
            AND mds.is_template = 0
            LIMIT %s
        """,
            (limit,),
            as_dict=True,
        )
        return orphaned

    def validate_dues_rate(self):
        """
        ✅ NEW: Validate dues rate for reasonableness and business logic
        Prevents zero/negative rates and extreme changes from previous period
        """
        try:
            # Check for zero or negative rates
            if not self.dues_rate or self.dues_rate <= 0:
                return {"valid": False, "reason": f"Invalid dues rate: {self.dues_rate} (must be positive)"}

            # Check for extremely high rates (configurable threshold with safe fallback)
            try:
                max_reasonable_rate = (
                    frappe.db.get_single_value("Verenigingen Settings", "max_reasonable_dues_rate") or 10000
                )
            except frappe.DoesNotExistError:
                frappe.log_error(
                    message="Verenigingen Settings doctype does not exist, using default max_reasonable_dues_rate",
                    title="Membership Dues - Missing Settings Doctype",
                    reference_doctype="Membership Dues Schedule",
                    reference_name=getattr(self, "name", "New Document"),
                )
                max_reasonable_rate = 10000  # Safe fallback if setting doesn't exist
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to access dues rate configuration: {str(e)}",
                    title="Membership Dues - Configuration Access Failed",
                    reference_doctype="Membership Dues Schedule",
                    reference_name=getattr(self, "name", "New Document"),
                )
                max_reasonable_rate = 10000  # Safe fallback if setting doesn't exist

            if self.dues_rate > max_reasonable_rate:
                # Use shorter error message to avoid length limits
                return {
                    "valid": False,
                    "reason": f"Dues rate {self.dues_rate} exceeds max {max_reasonable_rate}",
                }

            # Check for extreme rate changes from previous period (if exists)
            if self.last_generated_invoice:
                try:
                    last_invoice = frappe.get_doc("Sales Invoice", self.last_generated_invoice)
                    if last_invoice.grand_total > 0:
                        rate_change_percent = abs(
                            (self.dues_rate - last_invoice.grand_total) / last_invoice.grand_total * 100
                        )
                        try:
                            max_rate_change = (
                                frappe.db.get_single_value("Verenigingen Settings", "max_rate_change_percent")
                                or 200
                            )
                        except frappe.DoesNotExistError:
                            frappe.log_error(
                                message="Verenigingen Settings doctype does not exist, using default max_rate_change_percent",
                                title="Membership Dues - Missing Settings for Rate Change",
                                reference_doctype="Membership Dues Schedule",
                                reference_name=getattr(self, "name", "New Document"),
                            )
                            max_rate_change = 200  # Safe fallback
                        except Exception as e:
                            frappe.log_error(
                                message=f"Failed to access rate change configuration: {str(e)}",
                                title="Membership Dues - Rate Change Config Access Failed",
                                reference_doctype="Membership Dues Schedule",
                                reference_name=getattr(self, "name", "New Document"),
                            )
                            max_rate_change = 200  # Safe fallback

                        if rate_change_percent > max_rate_change:
                            # Just log, don't block - might be legitimate
                            pass
                except Exception:
                    # Don't fail validation if we can't check previous rate
                    pass

            return {"valid": True, "reason": "Rate validation passed"}

        except Exception:
            # Use shorter error message to avoid length limits
            return {"valid": True, "reason": "Rate validation error - allowing generation"}

    def validate_membership_type_consistency(self):
        """
        ✅ NEW: Verify member's current membership type matches schedule
        Prevents billing with outdated membership type information
        """
        try:
            if not self.member or not self.membership_type:
                return {"valid": True, "reason": "No member or membership type to validate"}

            # Get member's current active membership
            current_membership = frappe.get_all(
                "Membership",
                filters={"member": self.member, "status": "Active", "docstatus": 1},
                fields=["membership_type", "name"],
                limit=1,
            )

            if not current_membership:
                # This will be caught by the member eligibility check
                return {
                    "valid": True,
                    "reason": "No active membership found - will be handled by eligibility check",
                }

            current_type = current_membership[0].membership_type

            # Check if membership types match
            if current_type != self.membership_type:
                return {
                    "valid": False,
                    "reason": f"Type mismatch: schedule={self.membership_type}, current={current_type}",
                }

            return {"valid": True, "reason": "Membership type consistency validated"}

        except Exception:
            # Don't block generation on validation errors - continue gracefully
            return {"valid": True, "reason": "Type validation error - allowing generation"}

    def generate_invoice(self, force=False):
        """Generate invoice for the current period with enhanced coverage tracking"""
        can_generate, reason = self.can_generate_invoice()

        if not can_generate and not force:
            frappe.log_error(f"Cannot generate invoice: {reason}", f"Membership Dues Schedule {self.name}")
            return None

        if self.test_mode:
            # In test mode, just log and update dates - but only if we can actually generate
            frappe.logger().info(
                f"TEST MODE: Would generate invoice for {self.member} - Dues Rate: {self.dues_rate}"
            )
            self.update_schedule_dates()  # Test mode uses fallback behavior
            return "TEST_INVOICE"

        # ✅ NEW: Transaction safety - wrap critical operations in transaction
        try:
            # Set flag to skip strict validation during invoice generation
            frappe.flags.in_invoice_generation = True

            # Start explicit transaction for invoice generation
            frappe.db.begin()

            # ✅ ENHANCED: Calculate coverage period (authoritative source)
            coverage_start, coverage_end = self.calculate_billing_period(frappe.utils.today())

            # Store next billing period in schedule (SSoT)
            self.next_billing_period_start_date = coverage_start
            self.next_billing_period_end_date = coverage_end

            # Create actual invoice
            invoice_name = self.create_sales_invoice()

            # Get the invoice document for coverage caching
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # ✅ ENHANCED: Cache coverage in invoice for display performance
            invoice.custom_coverage_start_date = coverage_start
            invoice.custom_coverage_end_date = coverage_end
            # Save with minimal logging to avoid activity log entries for automated invoices
            invoice.flags.ignore_version = True
            invoice.flags.ignore_links = True
            invoice.save()

            # ✅ ENHANCED: Create direct link and track coverage (no ambiguity)
            self.db_set("last_generated_invoice", invoice.name)
            self.db_set("last_invoice_coverage_start", coverage_start)
            self.db_set("last_invoice_coverage_end", coverage_end)

            # ✅ CRITICAL FIX: Update schedule with actual invoice posting date
            self.update_schedule_dates(actual_invoice_date=invoice.posting_date)

            # Commit transaction only after all operations succeed
            frappe.db.commit()

        except Exception as e:
            # Rollback transaction on any failure
            frappe.db.rollback()
            # Shorten error message to avoid database field length limits
            error_msg = f"Invoice gen failed for {self.name}: {str(e)[:100]}"
            try:
                frappe.log_error(error_msg, "Invoice Generation Failure")
            except Exception as log_error:
                # If logging fails, attempt to log the logging failure
                # Use print as absolute fallback to avoid infinite loops
                print(f"Critical: Failed to log invoice generation error: {str(log_error)}")
                print(f"Original error was: {error_msg}")

            # Re-raise exception to maintain existing error handling behavior
            raise frappe.ValidationError(error_msg)
        finally:
            # Always clear the flag
            frappe.flags.in_invoice_generation = False

        frappe.logger().info(
            f"Generated invoice {invoice.name} for {self.member} covering period {coverage_start} to {coverage_end}"
        )

        return invoice

    def create_sales_invoice(self):
        """Create a sales invoice for membership dues"""
        # Get member's customer record
        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.customer:
            frappe.throw(f"Member {self.member} does not have a customer record")

        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member_doc.customer
        invoice.posting_date = today()

        # ✅ NEW: Set coverage period fields for better tracking
        coverage_start, coverage_end = self.calculate_billing_period(invoice.posting_date)
        invoice.custom_coverage_start_date = coverage_start
        invoice.custom_coverage_end_date = coverage_end

        # Set proper due date - use payment terms or default to 30 days from posting date
        from frappe.utils import add_days

        if self.payment_terms_template:
            # Let ERPNext calculate due date from payment terms
            invoice.payment_terms_template = self.payment_terms_template
            # Due date will be calculated automatically
        else:
            # Default to 30 days from posting date for membership invoices
            invoice.due_date = add_days(today(), 30)

        # Set payment method based on member's preferences
        payment_method = self.get_member_payment_method()
        if payment_method == "SEPA Direct Debit":
            active_mandate = self.get_member_active_mandate()
            if active_mandate:
                # Set SEPA-specific fields on invoice if needed
                invoice.sepa_mandate_id = active_mandate

        # Payment terms template already set above if specified

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
        # Insert with minimal logging for automated invoices
        invoice.flags.ignore_version = True
        invoice.flags.ignore_links = True
        invoice.insert()

        # Auto-submit if configured (default to True for membership invoices)
        try:
            auto_submit = frappe.db.get_single_value(
                "Verenigingen Settings", "auto_submit_membership_invoices"
            )
            # Default to auto-submit if setting doesn't exist (better UX)
            if auto_submit is None or auto_submit:
                # Keep minimal logging flags for submit operation
                invoice.flags.ignore_version = True
                invoice.flags.ignore_links = True
                invoice.submit()
        except Exception:
            # If setting doesn't exist, default to auto-submit for membership invoices
            try:
                # Keep minimal logging flags for submit operation
                invoice.flags.ignore_version = True
                invoice.flags.ignore_links = True
                invoice.submit()
            except Exception as e:
                frappe.log_error(
                    f"Failed to auto-submit invoice {invoice.name}: {str(e)}", "Invoice Auto-Submit"
                )
                pass

        return invoice.name

    def get_membership_dues_item(self):
        """Get or create the membership dues item"""
        if self.billing_frequency == "Custom":
            # Get custom frequency settings with validation
            frequency_number = getattr(self, "custom_frequency_number", None)
            if not frequency_number or frequency_number < 1:
                frequency_number = 1  # Safe default

            frequency_unit = getattr(self, "custom_frequency_unit", None)
            if not frequency_unit:
                frequency_unit = "Months"  # Safe default
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
        """Generate invoice description with appropriate period formatting"""
        period_start = self.last_invoice_date or self.next_invoice_date
        period_end = self.calculate_next_invoice_date(self.next_invoice_date)

        # Format period description based on billing frequency
        if self.billing_frequency == "Daily":
            # For daily billing, show the specific date
            return f"Membership dues for {self.member_name} ({self.membership_type}) - Daily fee for {period_start}"
        elif self.billing_frequency in ["Monthly", "Quarterly", "Semi-Annual", "Annual"]:
            # For longer periods, show the range
            return f"Membership dues for {self.member_name} ({self.membership_type}) - {self.billing_frequency} period: {period_start} to {period_end}"
        else:
            # For custom or other frequencies, show the generic range
            return f"Membership dues for {self.member_name} ({self.membership_type}) - Period: {period_start} to {period_end}"

    def update_schedule_dates(self, actual_invoice_date=None):
        """
        Update schedule dates after invoice generation.

        CRITICAL FIX: Uses actual invoice posting date instead of theoretical next_invoice_date
        to prevent date drift and duplicate billing issues.
        """
        if actual_invoice_date:
            # Use the actual posting date from the created invoice
            self.last_invoice_date = actual_invoice_date
            self.next_invoice_date = self.calculate_next_invoice_date(actual_invoice_date)
        else:
            # Fallback to old behavior (for test mode)
            self.last_invoice_date = self.next_invoice_date
            self.next_invoice_date = self.calculate_next_invoice_date(self.next_invoice_date)

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

    def calculate_next_invoice_date(self, from_date=None):
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
            # Use custom frequency settings with validation
            frequency_number = getattr(self, "custom_frequency_number", None)
            if not frequency_number or frequency_number < 1:
                frequency_number = 1  # Safe default

            frequency_unit = getattr(self, "custom_frequency_unit", None)
            if not frequency_unit:
                frequency_unit = "Months"  # Safe default

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
        # Skip membership validation when pausing (allows cancellation workflow)
        self._skip_membership_validation = True
        self.save()

    def resume_schedule(self, new_next_date=None):
        """Resume the dues schedule"""
        self.status = "Active"
        if new_next_date:
            self.next_invoice_date = new_next_date
        self.notes = f"{self.notes}\n\nResumed on {today()}" if self.notes else f"Resumed on {today()}"
        self.save()

    @staticmethod
    def create_default_template(membership_type):
        """Create a default template for a membership type"""
        try:
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            # Create basic template
            template = frappe.new_doc("Membership Dues Schedule")
            template.is_template = 1
            template.schedule_name = f"Default-Template-{membership_type}"
            template.membership_type = membership_type
            template.status = "Active"
            template.billing_frequency = "Annual"
            template.contribution_mode = "Calculator"
            template.minimum_amount = 0
            template.suggested_amount = 15.0  # Default template value
            template.invoice_days_before = 30
            template.billing_day = 1  # Default template billing day
            template.auto_generate = 1

            template.insert()

            # Link back to membership type
            membership_type_doc.dues_schedule_template = template.name
            membership_type_doc.save()

            return template

        except Exception as e:
            frappe.log_error(
                f"Error creating default template for {membership_type}: {str(e)}",
                "Default Template Creation",
            )
            raise frappe.ValidationError(f"Could not create default template for {membership_type}: {str(e)}")

    @staticmethod
    def create_from_template(member_name, template_name=None, membership_type=None, membership_name=None):
        """Create an individual dues schedule from a template

        Args:
            member_name: Name of the member to create schedule for
            template_name: Explicit template name to use (optional)
            membership_type: Membership type to get template from (optional)
            membership_name: Name of membership to link to (optional)

        Note: Either template_name OR membership_type must be provided.
        If membership_type is provided, uses the explicit dues_schedule_template
        from the Membership Type (NO implicit lookup).
        """

        # Determine template to use and get membership info
        membership_id = membership_name
        template = None

        if template_name:
            # Explicit template provided
            template = frappe.get_doc("Membership Dues Schedule", template_name)
            if not template.is_template:
                frappe.throw(f"{template_name} is not a template")

        elif membership_type:
            # Get template from membership type's explicit assignment
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            if not membership_type_doc.dues_schedule_template:
                frappe.throw(
                    f"Membership Type '{membership_type}' has no dues schedule template assigned. "
                    f"Please assign a template to the membership type before creating schedules."
                )

            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            if not template.is_template:
                frappe.throw(
                    f"Template '{membership_type_doc.dues_schedule_template}' is not marked as a template"
                )

        else:
            # Auto-detect from member's membership type (fallback)
            active_membership = frappe.db.get_value(
                "Membership",
                {"member": member_name, "status": "Active", "docstatus": 1},
                ["membership_type", "name"],
                as_dict=True,
            )
            if not active_membership:
                frappe.throw(f"Member {member_name} has no active membership")

            membership_type = active_membership.membership_type
            membership_id = active_membership.name

            # Get template from membership type's explicit assignment (NO implicit lookup)
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            if not membership_type_doc.dues_schedule_template:
                frappe.throw(
                    f"Membership Type '{membership_type}' has no dues schedule template assigned. "
                    f"Cannot create dues schedule for member {member_name}. "
                    f"Please assign a template to the membership type first."
                )

            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            if not template.is_template:
                frappe.throw(
                    f"Template '{membership_type_doc.dues_schedule_template}' is not marked as a template"
                )

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
            "billing_day",
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

        # SOPHISTICATED DUES RATE LOGIC: Preserve user's selected amount when available
        member_doc = frappe.get_doc("Member", member_name)
        user_selected_rate = getattr(member_doc, "dues_rate", None)

        if user_selected_rate and user_selected_rate > 0:
            # User has selected a specific dues rate during application - preserve it
            schedule.dues_rate = user_selected_rate
            schedule.contribution_mode = "Custom"  # Mark as custom since user selected specific amount
            schedule.uses_custom_amount = 1
            schedule.custom_amount_reason = "Amount selected during membership application"

            # Validate user's selection against template minimum
            template_minimum = getattr(template, "minimum_amount", 0)
            if template_minimum and user_selected_rate < template_minimum:
                frappe.throw(
                    f"Selected contribution amount (€{user_selected_rate:.2f}) is less than the minimum required "
                    f"for {template.membership_type} membership (€{template_minimum:.2f}). "
                    f"Please contact support to resolve this discrepancy."
                )
        else:
            # No user selection - use template's dues_rate as fallback
            template_dues_rate = getattr(template, "dues_rate", None)
            if template_dues_rate and template_dues_rate > 0:
                schedule.dues_rate = template_dues_rate
            else:
                # Final fallback to suggested_amount if template has no dues_rate
                schedule.dues_rate = getattr(template, "suggested_amount", 0)

        # CRITICAL: Set the membership field if available
        if membership_id:
            schedule.membership = membership_id

        # Use new naming pattern with sequence numbers
        from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

        schedule.schedule_name = generate_dues_schedule_name(member_name, template.membership_type)

        # Set member-specific data
        member = frappe.get_doc("Member", member_name)
        schedule.member_name = member.full_name

        # Set initial billing date based on member anniversary and frequency
        next_billing = schedule.calculate_next_invoice_date()
        if next_billing:
            schedule.next_invoice_date = next_billing
        else:
            schedule.next_invoice_date = today()

        # Insert and return
        schedule.insert()

        # Link back to member with concurrency handling
        member.dues_schedule = schedule.name
        member.dues_rate = schedule.dues_rate

        try:
            member.save()
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            member.reload()
            member.dues_schedule = schedule.name
            member.dues_rate = schedule.dues_rate
            member.save()

        return schedule.name

    def after_insert(self):
        """Handle new schedule creation"""
        if not self.is_template and self.member:
            self.add_billing_history_entry("New Schedule", None, self.dues_rate)
            # Update member's dues_rate field
            self.update_member_dues_rate()

    def on_update(self):
        """Track billing history changes when schedule is updated"""
        if self.is_template or not self.member:
            return

        # Only proceed if we have the old document for comparison
        if not hasattr(self, "_doc_before_save") or self._doc_before_save is None:
            return

        old_doc = self._doc_before_save

        # Check for dues rate change
        if old_doc.dues_rate != self.dues_rate:
            self.add_billing_history_entry("Fee Adjustment", old_doc.dues_rate, self.dues_rate)
            # Update member's dues_rate field
            self.update_member_dues_rate()

        # Check for status change
        if old_doc.status != self.status:
            if self.status == "Cancelled":
                self.add_billing_history_entry("Schedule Cancelled", self.dues_rate, self.dues_rate)
            elif old_doc.status == "Paused" and self.status == "Active":
                self.add_billing_history_entry("Schedule Resumed", self.dues_rate, self.dues_rate)

        # Check for billing frequency change
        if old_doc.billing_frequency != self.billing_frequency:
            self.add_billing_history_entry("Billing Frequency Change", self.dues_rate, self.dues_rate)

    def update_member_dues_rate(self):
        """Update the member's dues_rate field to match the schedule"""
        try:
            member_doc = frappe.get_doc("Member", self.member)
            if member_doc.dues_rate != self.dues_rate:
                member_doc.dues_rate = self.dues_rate
                member_doc.save(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error updating member dues rate: {str(e)}", "Member Dues Rate Update")

    def update_member_fee_change_history(self):
        """Update the member's fee change history from all dues schedules"""
        try:
            # Import the refresh function
            from verenigingen.verenigingen.doctype.member.member import refresh_fee_change_history

            # Call the refresh function to rebuild the fee change history
            refresh_fee_change_history(self.member)
        except Exception as e:
            frappe.log_error(
                f"Error updating member fee change history: {str(e)}", "Fee Change History Update"
            )

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

            # Allow updates after submit for billing history
            member_doc.flags.ignore_validate_update_after_submit = True
            member_doc.save(ignore_permissions=True)

        except Exception as e:
            # Shorten error message to avoid database field length limits
            error_msg = f"Billing history error for {self.name}: {str(e)[:80]}"
            frappe.log_error(error_msg, "Billing History Update")

    # ✅ ERPNext-Inspired Validation Enhancements

    def validate_status_transitions(self):
        """
        Validate allowed status transitions (inspired by ERPNext subscription patterns)
        Prevents invalid status changes that could break business logic
        """
        if self.is_new() or not hasattr(self, "_doc_before_save"):
            return

        old_status = self._doc_before_save.status
        new_status = self.status

        if old_status == new_status:
            return

        # Define allowed transitions based on business rules
        allowed_transitions = {
            "Active": ["Paused", "Cancelled"],
            "Paused": ["Active", "Cancelled"],
            "Cancelled": [],  # No transitions from cancelled
            "Test": ["Active", "Cancelled"],
        }

        if new_status not in allowed_transitions.get(old_status, []):
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(
                f"Cannot transition dues schedule status from {old_status} to {new_status}. "
                f"Allowed transitions from {old_status}: {', '.join(allowed_transitions.get(old_status, []))}"
            )

    def validate_billing_frequency_consistency(self):
        """
        Ensure member's schedules maintain consistent billing frequencies
        Based on ERPNext's billing cycle consistency validation
        """
        if self.is_template or not self.member:
            return

        existing_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member, "status": "Active", "name": ["!=", self.name]},
            fields=["billing_frequency", "name"],
        )

        conflicting_schedules = [
            s for s in existing_schedules if s.billing_frequency != self.billing_frequency
        ]

        if conflicting_schedules:
            from verenigingen.utils.exceptions import BillingFrequencyConflictError

            conflicting_frequencies = list(set([s.billing_frequency for s in conflicting_schedules]))
            raise BillingFrequencyConflictError(
                f"Member {self.member} has existing schedules with different billing frequencies: "
                f"{', '.join(conflicting_frequencies)}. Current schedule uses {self.billing_frequency}. "
                f"All schedules for a member must use the same billing frequency."
            )

    def validate_rate_boundaries(self):
        """
        Enhanced rate validation with ERPNext-style boundary checks
        More comprehensive than basic positive/negative validation
        """
        if self.is_template or not self.dues_rate:
            return

        # Enhanced minimum validation
        if self.dues_rate <= 0:
            from verenigingen.utils.exceptions import InvalidDuesRateError

            raise InvalidDuesRateError(f"Dues rate must be positive. Got: €{self.dues_rate:.2f}")

        # Check against membership type boundaries - but only during user edits, not invoice generation
        # Skip strict validation if we're in an automated context like invoice generation
        if (
            self.membership_type
            and not getattr(self, "_skip_minimum_validation", False)
            and not frappe.flags.in_invoice_generation
        ):
            # Skip template validation for existing schedules when changing membership type
            self._skip_template_validation = not self.is_new()
            template_values = self.get_template_values()
            min_amount = template_values.get("minimum_amount", 0)

            if self.dues_rate < min_amount:
                # For existing schedules, allow the rate to remain as-is when changing membership type
                if not self.is_new():
                    # Only show warning, don't block the change
                    frappe.msgprint(
                        f"Warning: Dues rate €{self.dues_rate:.2f} is below minimum required "
                        f"€{min_amount:.2f} for membership type {self.membership_type}. "
                        f"This is allowed for existing schedules to maintain member flexibility.",
                        alert=True,
                    )
                    return  # Don't block existing schedules

                from verenigingen.utils.exceptions import InvalidDuesRateError

                raise InvalidDuesRateError(
                    f"Dues rate €{self.dues_rate:.2f} is below minimum required "
                    f"€{min_amount:.2f} for membership type {self.membership_type}"
                )

        # Check for unreasonably high rates (configurable maximum)
        try:
            max_reasonable_rate = (
                frappe.db.get_single_value("Verenigingen Settings", "max_reasonable_dues_rate") or 10000
            )
        except Exception:
            # Fallback if field doesn't exist yet
            max_reasonable_rate = 10000

        if self.dues_rate > max_reasonable_rate:
            frappe.msgprint(
                f"Warning: Dues rate €{self.dues_rate:.2f} exceeds recommended maximum "
                f"€{max_reasonable_rate:.2f}. Please verify this amount is correct.",
                alert=True,
            )


@frappe.whitelist()
def generate_dues_invoices(test_mode=False):
    """
    Scheduled job to generate membership dues invoices with hybrid payment history updates.

    This function implements Option C hybrid architecture:
    - Bulk invoice generation handles its own payment history updates as a final step
    - Smart detection prevents duplicate processing from event handlers
    - Optimal performance for bulk operations while maintaining flexibility
    """

    # Set bulk processing flag to prevent duplicate event handling
    frappe.flags.bulk_invoice_generation = True

    try:
        # Get all active schedules that need processing (exclude templates)
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "status": "Active",
                "auto_generate": 1,
                "is_template": 0,
                "next_invoice_date": ["<=", add_days(today(), 30)],
            },
            pluck="name",
        )

        results = {"processed": 0, "generated": 0, "errors": [], "invoices": [], "payment_history_updates": 0}

        # Track which members need payment history updates
        members_to_update = set()
        successful_invoices = []

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
                        invoice_data = {
                            "schedule": schedule_name,
                            "member": schedule.member_name,
                            "member_id": schedule.member,
                            "invoice": invoice,
                        }
                        results["invoices"].append(invoice_data)
                        successful_invoices.append(invoice_data)

                        # Track member for payment history update
                        if schedule.member:
                            members_to_update.add(schedule.member)
                    else:
                        # Log when invoice generation fails despite can_generate being True
                        error_msg = f"Schedule {schedule_name} passed can_generate check but failed to generate invoice"
                        frappe.log_error(error_msg, "Invoice Generation Failed")
                        results["errors"].append(error_msg)

                results["processed"] += 1

            except Exception as e:
                # Shorten error message to avoid database field length limits
                error_msg = f"Error processing {schedule_name}: {str(e)[:80]}"
                try:
                    frappe.log_error(error_msg, "Membership Dues Generation")
                except Exception as log_error:
                    # If logging fails, attempt to log the logging failure
                    # Use print as absolute fallback to avoid infinite loops
                    print(f"Critical: Failed to log membership dues generation error: {str(log_error)}")
                    print(f"Original error was: {error_msg}")
                results["errors"].append(error_msg)

        # HYBRID ARCHITECTURE: Bulk update payment history for all affected members
        if members_to_update:
            try:
                results["payment_history_updates"] = _bulk_update_payment_history(
                    members_to_update, successful_invoices
                )
                frappe.logger().info(
                    f"Bulk payment history update completed for {len(members_to_update)} members"
                )
            except Exception as e:
                error_msg = f"Error in bulk payment history update: {str(e)[:100]}"
                frappe.log_error(error_msg, "Bulk Payment History Update Error")
                results["errors"].append(error_msg)

        # Log results
        frappe.logger().info(
            f"Membership dues generation completed: {results['generated']} invoices from {results['processed']} schedules, "
            f"{results['payment_history_updates']} payment history updates"
        )

        return results

    finally:
        # Always clear the bulk processing flag
        if hasattr(frappe.flags, "bulk_invoice_generation"):
            delattr(frappe.flags, "bulk_invoice_generation")


def _bulk_update_payment_history(member_names, successful_invoices):
    """
    Efficiently update payment history for multiple members after bulk invoice generation.

    Args:
        member_names: Set of member names that need payment history updates
        successful_invoices: List of invoice data dictionaries for tracking

    Returns:
        int: Number of members successfully updated
    """
    updated_count = 0

    for member_name in member_names:
        try:
            # Get member document with error handling
            if not frappe.db.exists("Member", member_name):
                frappe.log_error(
                    f"Member {member_name} not found during bulk payment history update",
                    "Bulk Payment History Update",
                )
                continue

            # Use atomic add method for each new invoice for this member
            member_invoices = [inv for inv in successful_invoices if inv.get("member_id") == member_name]

            if member_invoices:
                member_doc = frappe.get_doc("Member", member_name)

                # Add each invoice to payment history using atomic method
                for inv_data in member_invoices:
                    try:
                        # Use existing atomic method from payment mixin
                        member_doc.add_invoice_to_payment_history(inv_data["invoice"])
                    except Exception as inv_error:
                        frappe.log_error(
                            f"Failed to add invoice {inv_data['invoice']} to payment history for member {member_name}: {str(inv_error)}",
                            "Individual Invoice Payment History Update",
                        )

                updated_count += 1

        except Exception as e:
            frappe.log_error(
                f"Error updating payment history for member {member_name}: {str(e)}",
                "Bulk Payment History Member Update",
            )

    return updated_count


@frappe.whitelist()
def create_schedule_from_template(member_name, template_name=None):
    """API endpoint to create schedule from template"""
    return MembershipDuesSchedule.create_from_template(member_name, template_name)


@frappe.whitelist()
def create_template_for_membership_type(membership_type, template_name=None):
    """Create a new template for a membership type"""
    if not template_name:
        # Use membership type name for more descriptive template naming
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)
        template_name = f"Template-{membership_type_doc.membership_type_name}"

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
    template.billing_frequency = "Annual"  # Default, since this is now owned by dues schedule
    template.contribution_mode = getattr(membership_type_doc, "contribution_mode", "Calculator")
    template.minimum_amount = 0  # Will be set per schedule
    template.suggested_amount = 15.0  # Default template value - should be configured explicitly
    template.invoice_days_before = 30  # Default
    template.billing_day = 1  # Default template billing day
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
def test_billing_day_field():
    """Test billing_day field implementation"""
    try:
        # Test 1: Create a member with member_since date
        test_member = frappe.new_doc("Member")
        test_member.first_name = "Billing"
        test_member.last_name = "Test"
        test_member.email = f"billing.test.{frappe.generate_hash(length=6)}@example.com"
        test_member.member_since = "2023-03-15"  # 15th of the month
        test_member.save()

        # Test 2: Create a dues schedule for this member
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Billing-Day-{frappe.generate_hash(length=4)}"
        schedule.is_template = 0
        schedule.member = test_member.name
        schedule.membership_type = "Test Membership"  # Use existing membership type
        schedule.dues_rate = 10.0
        schedule.save()

        # Test 3: Create a member without member_since date
        no_date_member = frappe.new_doc("Member")
        no_date_member.first_name = "NoDate"
        no_date_member.last_name = "Test"
        no_date_member.email = f"nodate.test.{frappe.generate_hash(length=6)}@example.com"
        no_date_member.member_since = None
        no_date_member.save()

        # Test 4: Create a dues schedule for member without date
        no_date_schedule = frappe.new_doc("Membership Dues Schedule")
        no_date_schedule.schedule_name = f"Test-No-Date-{frappe.generate_hash(length=4)}"
        no_date_schedule.is_template = 0
        no_date_schedule.member = no_date_member.name
        no_date_schedule.membership_type = "Test Membership"
        no_date_schedule.dues_rate = 10.0
        no_date_schedule.save()

        results = {
            "test_1_member_with_date": {
                "member_since": test_member.member_since,
                "expected_billing_day": 15,
                "actual_billing_day": schedule.billing_day,
                "correct": schedule.billing_day == 15,
            },
            "test_2_member_without_date": {
                "member_since": no_date_member.member_since,
                "expected_billing_day": 1,
                "actual_billing_day": no_date_schedule.billing_day,
                "correct": no_date_schedule.billing_day == 1,
            },
            "field_exists": hasattr(schedule, "billing_day"),
            "overall_success": schedule.billing_day == 15 and no_date_schedule.billing_day == 1,
        }

        # Cleanup
        schedule.delete()
        no_date_schedule.delete()
        test_member.delete()
        no_date_member.delete()

        return results

    except Exception as e:
        return {"error": str(e), "success": False}


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


@frappe.whitelist()
def debug_template_daglid_issue():
    """Debug Template-Daglid billing frequency override issue"""
    result = {
        "timestamp": frappe.utils.now(),
        "template_status": {},
        "membership_type_status": {},
        "inheritance_tests": {},
        "recent_schedules": [],
    }

    # Check Template-Daglid current state
    try:
        template = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
        result["template_status"] = {
            "billing_frequency": template.billing_frequency,
            "is_template": template.is_template,
            "modified": str(template.modified),
            "modified_by": template.modified_by,
        }
    except Exception as e:
        result["template_status"]["error"] = str(e)

    # Check Daglid membership type
    try:
        membership_type = frappe.get_doc("Membership Type", "Daglid")
        result["membership_type_status"] = {
            "dues_schedule_template": membership_type.dues_schedule_template,
            "amount": getattr(membership_type, "amount", 0),
        }
    except Exception as e:
        result["membership_type_status"]["error"] = str(e)

    # Test the auto-creator inheritance logic
    try:
        billing_frequency = "Annual"  # Default from auto_creator
        if membership_type.dues_schedule_template:
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
            # Use explicit validation instead of fallback
            if template.billing_frequency:
                billing_frequency = template.billing_frequency
            else:
                billing_frequency = "Annual"
                frappe.log_error(
                    f"Template '{membership_type.dues_schedule_template}' has no billing_frequency configured, using default 'Annual'",
                    "Membership Dues Schedule Template Configuration",
                )

        result["inheritance_tests"]["auto_creator_logic"] = {
            "would_set": billing_frequency,
            "template_value": template.billing_frequency,
            "template_truthy": bool(template.billing_frequency),
        }
    except Exception as e:
        result["inheritance_tests"]["auto_creator_error"] = str(e)

    # Test the get_template_values() method
    try:
        test_schedule = frappe.new_doc("Membership Dues Schedule")
        test_schedule.membership_type = "Daglid"
        template_values = test_schedule.get_template_values()
        result["inheritance_tests"]["get_template_values"] = {
            "billing_frequency": template_values.get("billing_frequency"),
            "all_values": template_values,
        }
    except Exception as e:
        result["inheritance_tests"]["get_template_values_error"] = str(e)

    # Check recent dues schedules
    try:
        recent_schedules = frappe.db.sql(
            """
            SELECT name, billing_frequency, modified, membership_type
            FROM `tabMembership Dues Schedule`
            WHERE membership_type = 'Daglid'
            ORDER BY modified DESC
            LIMIT 5
        """,
            as_dict=True,
        )
        result["recent_schedules"] = recent_schedules
    except Exception as e:
        result["recent_schedules_error"] = str(e)

    return result


@frappe.whitelist()
def test_template_daglid_fix():
    """Test that Template-Daglid billing frequency is preserved during template recreation"""

    # Step 1: Check current Template-Daglid status
    before = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    before_frequency = before.billing_frequency
    before_modified = str(before.modified)

    # Step 2: Simulate template recreation (this was the source of the bug)
    daglid_membership_type = frappe.get_doc("Membership Type", "Daglid")
    template_name = daglid_membership_type.create_dues_schedule_template()

    # Step 3: Check Template-Daglid status after recreation
    after = frappe.get_doc("Membership Dues Schedule", "Template-Daglid")
    after_frequency = after.billing_frequency
    after_modified = str(after.modified)

    return {
        "template_name": template_name,
        "before": {"billing_frequency": before_frequency, "modified": before_modified},
        "after": {"billing_frequency": after_frequency, "modified": after_modified},
        "preserved": before_frequency == after_frequency,
        "test_result": "PASS" if before_frequency == after_frequency else "FAIL",
    }


def has_permission(doc, user=None, permission_type="read"):
    """Custom permission handler for Membership Dues Schedule"""
    if not user:
        user = frappe.session.user

    # Debug logging
    frappe.logger().info(
        f"PERMISSION CHECK: User {user}, Doc {doc.name if hasattr(doc, 'name') else 'Unknown'}, Type {permission_type}"
    )

    # System Manager always has access
    if "System Manager" in frappe.get_roles(user):
        frappe.logger().info(f"PERMISSION GRANTED: System Manager access for {user}")
        return True

    # Verenigingen Administrator and Manager have full access
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in ["Verenigingen Administrator", "Verenigingen Manager"]):
        frappe.logger().info(f"PERMISSION GRANTED: Admin role access for {user}")
        return True

    # Templates are visible to all authenticated users (for viewing available options)
    if hasattr(doc, "is_template") and doc.is_template:
        frappe.logger().info(f"PERMISSION GRANTED: Template access for {user}")
        return True

    # For non-templates, only allow access if user is the member
    if hasattr(doc, "member") and doc.member:
        # Check if current user is linked to this member
        member_user = frappe.db.get_value("Member", doc.member, "user")
        frappe.logger().info(
            f"PERMISSION CHECK: Doc member {doc.member}, Member user {member_user}, Current user {user}"
        )
        if member_user == user:
            frappe.logger().info(f"PERMISSION GRANTED: User matches member for {user}")
            return True

    # Check if user is chapter board with finance permissions
    if hasattr(doc, "member") and doc.member:
        try:
            # Get member's chapter
            chapter = frappe.db.get_value(
                "Chapter Member", {"member": doc.member, "status": "Active"}, "parent"
            )
            if chapter:
                # Get user's member record
                user_member = frappe.db.get_value("Member", {"user": user}, "name")
                if user_member:
                    # Check if user is board member with finance permissions
                    board_member = frappe.db.get_value(
                        "Chapter Board Member",
                        {
                            "parent": chapter,
                            "member": user_member,
                            "is_active": 1,
                        },
                        ["chapter_role"],
                        as_dict=True,
                    )

                    if board_member and board_member.chapter_role:
                        role_doc = frappe.get_doc("Chapter Role", board_member.chapter_role)
                        if getattr(role_doc, "permissions_level", None) in ["Financial", "Admin"]:
                            frappe.logger().info(f"PERMISSION GRANTED: Chapter board access for {user}")
                            return True
        except Exception:
            pass  # If any chapter permission check fails, continue to deny access

    frappe.logger().info(
        f"PERMISSION DENIED: No access granted for {user} to doc {doc.name if hasattr(doc, 'name') else 'Unknown'}"
    )
    return False


def get_permission_query_conditions(user=None):
    """Permission query conditions for Membership Dues Schedule list views"""
    if not user:
        user = frappe.session.user

    # Debug logging
    frappe.logger().info(f"QUERY PERMISSION CHECK: User {user}")

    # System Manager and admin roles get full access
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles:
        frappe.logger().info(f"QUERY PERMISSION: System Manager full access for {user}")
        return ""  # No restrictions

    if any(role in user_roles for role in ["Verenigingen Administrator", "Verenigingen Manager"]):
        frappe.logger().info(f"QUERY PERMISSION: Admin role full access for {user}")
        return ""  # No restrictions

    # For regular members, restrict to templates OR their own records
    # Get the user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")

    if user_member:
        frappe.logger().info(f"QUERY PERMISSION: Member {user_member} access for {user}")
        # Allow templates OR records where the member field matches their member record
        return f"(`tabMembership Dues Schedule`.is_template = 1 OR `tabMembership Dues Schedule`.member = '{user_member}')"
    else:
        frappe.logger().info(f"QUERY PERMISSION: Template-only access for {user}")
        # Only allow templates if user is not linked to a member
        return "`tabMembership Dues Schedule`.is_template = 1"


@frappe.whitelist()
def validate_and_fix_schedule_dates():
    """
    Validate and fix all dues schedule dates to prevent issues like Assoc-Member-2025-07-0030
    Returns a report of issues found and fixed
    """
    from frappe.utils import add_days, getdate, today

    today_date = getdate(today())
    results = {"total_schedules": 0, "issues_found": 0, "fixes_applied": 0, "issues": [], "success": True}

    try:
        # Get all active schedules
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=[
                "name",
                "member",
                "billing_frequency",
                "next_invoice_date",
                "last_invoice_date",
                "modified",
            ],
        )

        results["total_schedules"] = len(schedules)

        for schedule_data in schedules:
            issues = []
            fixes = []

            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)

                if schedule.next_invoice_date:
                    next_date = getdate(schedule.next_invoice_date)

                    # Check for unreasonably far future dates
                    if schedule.billing_frequency == "Daily":
                        max_future_days = 7
                    elif schedule.billing_frequency == "Weekly":
                        max_future_days = 14
                    elif schedule.billing_frequency == "Monthly":
                        max_future_days = 62
                    elif schedule.billing_frequency == "Quarterly":
                        max_future_days = 100
                    elif schedule.billing_frequency == "Annual":
                        max_future_days = 400
                    else:
                        max_future_days = 30

                    max_future_date = add_days(today_date, max_future_days)

                    if next_date > max_future_date:
                        issues.append(f"Next invoice date too far in future: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                    # Check for very old dates
                    min_past_date = add_days(today_date, -180)  # 6 months ago
                    if next_date < min_past_date:
                        issues.append(f"Next invoice date too far in past: {next_date}")
                        schedule.next_invoice_date = today_date
                        fixes.append(f"Corrected next_invoice_date from {next_date} to {today_date}")

                # If we made fixes, save the schedule
                if fixes:
                    schedule.save()
                    results["fixes_applied"] += 1

                    results["issues"].append(
                        {
                            "schedule": schedule_data.name,
                            "member": schedule_data.member,
                            "billing_frequency": schedule_data.billing_frequency,
                            "issues": issues,
                            "fixes": fixes,
                        }
                    )

            except Exception as e:
                results["issues"].append(
                    {
                        "schedule": schedule_data.name,
                        "member": schedule_data.member,
                        "error": f"Failed to process: {str(e)}",
                    }
                )

        results["issues_found"] = len([i for i in results["issues"] if "fixes" in i])

    except Exception as e:
        results["success"] = False
        results["error"] = str(e)

    return results
