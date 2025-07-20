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

                # Update template with the basic amount from membership type
                template.suggested_amount = self.amount or 0

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
        # Ensure amount is positive
        if flt(self.amount) < 0:
            frappe.throw(_("Amount cannot be negative"))

        # Round monetary amounts to 2 decimal places
        if hasattr(self, "amount"):
            self.amount = flt(self.amount, 2)

    # Updated to use dues schedule system

    # Updated to use dues schedule system

    def get_or_create_membership_item(self):
        """Get or create an Item for membership"""
        # Check if a membership item already exists
        existing_items = frappe.get_all(
            "Item",
            filters={"item_group": "Membership", "item_name": ["like", f"{self.membership_type_name}%"]},
            fields=["name"],
            limit=1,
        )

        if existing_items:
            return existing_items[0].name

        # Create a new item for membership
        item = frappe.new_doc("Item")
        item.item_name = f"{self.membership_type_name} Membership"
        item.item_code = f"MEM-{self.membership_type_name}".upper().replace(" ", "-")
        item.item_group = "Membership"  # Create this item group if it doesn't exist
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
                "minimum": 5.0,
                "suggested": self.amount or 15.0,
                "maximum": (self.amount or 15.0) * 10,
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
                "suggested": template.suggested_amount or self.amount or 15.0,
                "maximum": template.maximum_amount
                or ((template.suggested_amount or self.amount or 15.0) * 10),
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
                "minimum": 5.0,
                "suggested": self.amount or 15.0,
                "maximum": (self.amount or 15.0) * 10,
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
        """Create or update the dues schedule template for this membership type"""
        # Check if template already exists
        existing_template = frappe.db.get_value(
            "Membership Dues Schedule", {"membership_type": self.name, "is_template": 1}, "name"
        )

        if existing_template:
            # Update existing template
            template = frappe.get_doc("Membership Dues Schedule", existing_template)
        else:
            # Create new template
            template = frappe.new_doc("Membership Dues Schedule")
            template.is_template = 1
            template.schedule_name = f"Template-{self.name}"
            template.membership_type = self.name
            template.status = "Active"
            # Set required fields to avoid validation errors during creation
            template.amount = 0.0

        # Set/update template fields with sensible defaults
        template.billing_frequency = "Annual"  # Default billing frequency
        template.contribution_mode = "Calculator"  # Default contribution mode
        template.minimum_amount = 5.0  # Default minimum
        template.suggested_amount = self.amount or 15.0  # Use membership type amount as suggested
        template.invoice_days_before = 30  # Default invoice days
        template.auto_generate = 1
        template.status = "Active"
        # Ensure amount is set for templates
        if not template.amount:
            template.amount = self.amount or 15.0

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
