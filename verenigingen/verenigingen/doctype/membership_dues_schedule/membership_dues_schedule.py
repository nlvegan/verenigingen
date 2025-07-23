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
            values.update(
                {
                    "minimum_amount": template.minimum_amount or 0,
                    "suggested_amount": template.suggested_amount or 0,
                    "billing_frequency": template.billing_frequency or "Annual",
                    "invoice_days_before": template.invoice_days_before or 30,
                }
            )
        except Exception as e:
            frappe.throw(
                f"Failed to load dues schedule template '{membership_type.dues_schedule_template}': {str(e)}"
            )

        # Validate template has required values
        if not values["suggested_amount"]:
            frappe.throw(
                f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured"
            )

        # Validate template respects membership type minimum
        membership_type_minimum = membership_type.minimum_amount or 0
        template_minimum = values["minimum_amount"] or 0
        template_suggested = values["suggested_amount"] or 0

        if template_minimum < membership_type_minimum:
            frappe.throw(
                f"Template minimum amount (€{template_minimum:.2f}) cannot be less than "
                f"membership type minimum (€{membership_type_minimum:.2f})"
            )

        if template_suggested < membership_type_minimum:
            frappe.throw(
                f"Template suggested amount (€{template_suggested:.2f}) cannot be less than "
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
                self.dues_rate = template_values.get("suggested_amount", 0) * (self.base_multiplier or 1.0)
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
                suggested_amount = template.suggested_amount or 0

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
        """Check if invoice can be generated"""
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

        # Check if it's time to generate invoice
        days_before = self.invoice_days_before or 30
        generate_on_date = add_days(self.next_invoice_date, -days_before)

        if getdate(today()) < getdate(generate_on_date):
            return False, f"Too early - will generate on {generate_on_date}"

        # Check if invoice already exists for this period
        if self.last_invoice_date == self.next_invoice_date:
            return False, "Invoice already generated for this period"

        return True, "Can generate invoice"

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
                    f"Attempted to generate invoice for terminated member: {self.member} (status: {member.status})",
                    "Member Status Validation - Invoice Generation",
                )
                return False

            # Check if member has active membership
            active_membership = frappe.db.exists(
                "Membership", {"member": self.member, "status": "Active", "docstatus": 1}
            )
            if not active_membership:
                frappe.log_error(
                    f"Member {self.member} does not have active membership",
                    "Membership Status Validation - Invoice Generation",
                )
                return False

            # Note: SEPA mandate validation is only done at DD batch creation time
            # Members with broken payment data can still receive invoices
            # They just won't be included in Direct Debit batches

            return True

        except Exception as e:
            frappe.log_error(
                f"Error validating member eligibility for invoice generation {self.member}: {str(e)}",
                "Member Eligibility Validation Error",
            )
            return False

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
        # Get member's customer record
        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.customer:
            frappe.throw(f"Member {self.member} does not have a customer record")

        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = member_doc.customer
        invoice.posting_date = today()

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
        invoice.insert()

        # Auto-submit if configured (default to True for membership invoices)
        try:
            auto_submit = frappe.db.get_single_value(
                "Verenigingen Settings", "auto_submit_membership_invoices"
            )
            # Default to auto-submit if setting doesn't exist (better UX)
            if auto_submit is None or auto_submit:
                invoice.submit()
        except Exception:
            # If setting doesn't exist, default to auto-submit for membership invoices
            try:
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
        """Generate invoice description with appropriate period formatting"""
        period_start = self.last_invoice_date or self.next_invoice_date
        period_end = self.calculate_next_billing_date(self.next_invoice_date)

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
        next_billing = schedule.calculate_next_billing_date()
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
            # This is the problematic line
            billing_frequency = template.billing_frequency or "Annual"

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
