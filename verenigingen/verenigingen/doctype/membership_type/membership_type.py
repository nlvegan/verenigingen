import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MembershipType(Document):
    def validate(self):
        self.validate_billing_period()
        self.validate_amount()

    def on_update(self):
        """Update template when membership type changes"""
        if not frappe.flags.in_migrate:
            self.update_dues_schedule_template()

    def update_dues_schedule_template(self):
        """Update the dues schedule template when membership type changes"""
        if self.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", self.dues_schedule_template)

                # Update template with default amount (preserve existing if set)
                if not template.suggested_amount:
                    template.suggested_amount = 15.0

                template.save()
            except Exception as e:
                frappe.log_error(f"Error updating dues schedule template: {str(e)}", "Membership Type Update")

    def validate_billing_period(self):
        # Legacy period fields have been removed
        # All references now use billing_period and billing_period_in_months directly

        # Skip validation during migration if new fields are not available
        if frappe.flags.in_migrate or not hasattr(self, "billing_period"):
            return

        # Ensure billing_period_in_months is set for custom periods
        if self.billing_period == "Custom" and not self.billing_period_in_months:
            frappe.throw(_("Billing Period in Months is required for Custom billing period"))

        # Clear billing_period_in_months for non-custom periods
        if self.billing_period != "Custom":
            self.billing_period_in_months = None

    def validate_amount(self):
        # Ensure minimum amount is positive
        if flt(self.minimum_amount) < 0:
            frappe.throw(_("Minimum amount cannot be negative"))

        # Round monetary amounts to 2 decimal places
        if hasattr(self, "minimum_amount"):
            self.minimum_amount = flt(self.minimum_amount, 2)

    # Updated to use dues schedule system

    # Updated to use dues schedule system

    def get_or_create_membership_item(self):
        """Get or create an Item for membership"""
        # Check for explicitly configured membership item first
        if hasattr(self, "membership_item") and self.membership_item:
            if frappe.db.exists("Item", self.membership_item):
                return self.membership_item
            else:
                frappe.log_error(
                    f"Membership Type '{self.name}' references non-existent item '{self.membership_item}'",
                    "Membership Type Configuration Error",
                )

        # Check if a membership item already exists using exact naming convention
        expected_item_code = f"MEM-{self.membership_type_name}".upper().replace(" ", "-")
        if frappe.db.exists("Item", expected_item_code):
            return expected_item_code

        # Check for item with exact membership item name
        expected_item_name = f"{self.membership_type_name} Membership"
        existing_item = frappe.db.get_value(
            "Item", {"item_name": expected_item_name, "item_group": "Membership"}, "name"
        )

        if existing_item:
            return existing_item

        # Create a new item for membership
        item = frappe.new_doc("Item")
        item.item_name = f"{self.membership_type_name} Membership"
        item.item_code = f"MEM-{self.membership_type_name}".upper().replace(" ", "-")
        item.item_group = "Memberships"  # Create this item group if it doesn't exist
        item.is_stock_item = 0
        item.include_item_in_manufacturing = 0
        item.is_service_item = 1
        # Removed: item.is_legacy_item = 1  # Not needed with dues schedule system

        # Set item defaults
        item.append(
            "item_defaults",
            {"company": frappe.defaults.get_global_default("company"), "default_warehouse": None},
        )

        item.flags.ignore_mandatory = True
        item.insert(ignore_permissions=True)

        frappe.msgprint(_("Item {0} created for membership type").format(item.name))
        return item.name

    def get_contribution_options(self):
        """Get contribution options from the dues schedule template"""
        if not self.dues_schedule_template:
            # Return basic defaults if no template
            return {
                "mode": "Calculator",
                "minimum": self.minimum_amount or 5.0,
                "suggested": 15.0,
                "maximum": 15.0 * 10,
                "calculator": {
                    "enabled": True,
                    "percentage": 0.75,
                    "description": "We suggest 0.75% of your monthly net income",
                },
                "tiers": [],
                "quick_amounts": [],
            }

        try:
            template = frappe.get_doc("Membership Dues Schedule", self.dues_schedule_template)

            # Get all configuration from the template
            options = {
                "mode": template.contribution_mode or "Calculator",
                "minimum": template.minimum_amount or 5.0,
                "suggested": template.suggested_amount or 15.0,
                "maximum": ((template.suggested_amount or 15.0) * 10),
                "calculator": {
                    "enabled": template.enable_income_calculator
                    if hasattr(template, "enable_income_calculator")
                    else True,
                    "percentage": template.income_percentage_rate
                    if hasattr(template, "income_percentage_rate")
                    else 0.75,
                    "description": template.calculator_description
                    if hasattr(template, "calculator_description")
                    else "",
                },
                "tiers": [],
                "quick_amounts": [],
            }

            # Add tiers if available
            if hasattr(template, "predefined_tiers") and template.predefined_tiers:
                for tier in template.predefined_tiers:
                    options["tiers"].append(
                        {
                            "name": tier.tier_name,
                            "display_name": tier.display_name,
                            "amount": tier.amount,
                            "description": tier.description,
                            "requires_verification": getattr(tier, "requires_verification", 0),
                            "is_default": getattr(tier, "is_default", 0),
                            "display_order": getattr(tier, "display_order", 0) or 0,
                        }
                    )

            # Generate quick amounts for calculator mode
            if options["mode"] in ["Calculator", "Both"]:
                multipliers = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
                for multiplier in multipliers:
                    amount = options["suggested"] * multiplier
                    if amount >= options["minimum"]:
                        options["quick_amounts"].append(
                            {
                                "multiplier": multiplier,
                                "amount": amount,
                                "label": f"{int(multiplier * 100)}%" if multiplier != 1.0 else "Suggested",
                                "is_default": multiplier == 1.0,
                            }
                        )

            return options

        except Exception as e:
            frappe.log_error(f"Error getting contribution options: {str(e)}", "Membership Type")
            # Return defaults on error
            return {
                "mode": "Calculator",
                "minimum": self.minimum_amount or 5.0,
                "suggested": 15.0,
                "maximum": 15.0 * 10,
                "calculator": {
                    "enabled": True,
                    "percentage": 0.75,
                    "description": "We suggest 0.75% of your monthly net income",
                },
                "tiers": [],
                "quick_amounts": [],
            }

    def after_insert(self):
        """Create dues schedule template after membership type creation"""
        # Skip during migration to avoid validation issues
        if not frappe.flags.in_migrate:
            self.create_dues_schedule_template()

    def create_dues_schedule_template(self):
        """Get or create the dues schedule template for this membership type

        Uses fixture-based templates first, falls back to creation only if needed.
        Standardizes on '[Type] Membership Template' naming pattern.
        """
        # First, check if fixture template exists (preferred pattern)
        fixture_template_name = f"{self.membership_type_name} Template"
        if frappe.db.exists("Membership Dues Schedule", fixture_template_name):
            # Update membership type to use fixture template
            if self.dues_schedule_template != fixture_template_name:
                frappe.db.set_value(
                    "Membership Type", self.name, "dues_schedule_template", fixture_template_name
                )
            return fixture_template_name

        # Check if any template already exists for this membership type
        existing_template = frappe.db.get_value(
            "Membership Dues Schedule", {"membership_type": self.name, "is_template": 1}, "name"
        )

        if existing_template:
            # Use existing template
            return existing_template
        else:
            # Only create if no fixture and no existing template found
            template = frappe.new_doc("Membership Dues Schedule")
            template.is_template = 1
            # Use fixture naming pattern for consistency
            template.schedule_name = fixture_template_name
            template.membership_type = self.name
            template.status = "Active"
            # Set required fields to avoid validation errors during creation
            template.suggested_amount = 15.0  # Default template amount

        # Set/update template fields with sensible defaults, preserving existing values
        if not template.billing_frequency:
            template.billing_frequency = "Annual"  # Only set default if not already set
        if not template.contribution_mode:
            template.contribution_mode = "Calculator"  # Only set default if not already set
        if not template.minimum_amount:
            template.minimum_amount = 5.0  # Only set default if not already set
        if not template.suggested_amount:
            template.suggested_amount = 15.0  # Default template suggested amount
        if not template.invoice_days_before:
            template.invoice_days_before = 30  # Only set default if not already set
        template.auto_generate = 1  # Always ensure auto_generate is enabled
        template.status = "Active"  # Always ensure template is active
        # Ensure dues_rate is set for templates (field confirmed in JSON schema)
        if not template.dues_rate:
            template.dues_rate = 15.0  # Default template dues rate

        if existing_template:
            template.save()
        else:
            template.insert()
            # Link template back to membership type
            self.dues_schedule_template = template.name
            self.save()

        return template.name

    @frappe.whitelist()
    def get_dues_schedule_template(self):
        """Get the dues schedule template for this membership type"""
        if self.dues_schedule_template:
            return self.dues_schedule_template

        # Try to find existing template
        template_name = frappe.db.get_value(
            "Membership Dues Schedule", {"membership_type": self.name, "is_template": 1}, "name"
        )

        if template_name:
            self.dues_schedule_template = template_name
            self.save()
            return template_name

        # Create new template
        return self.create_dues_schedule_template()


# Updated to use dues schedule system


@frappe.whitelist()
def get_membership_contribution_options(membership_type_name):
    """Get contribution options for a specific membership type"""
    membership_type = frappe.get_doc("Membership Type", membership_type_name)
    return membership_type.get_contribution_options()


@frappe.whitelist()
def get_template_query():
    """Query function for dues schedule template filter"""
    return {"filters": [["Membership Dues Schedule", "is_template", "=", 1]]}
