import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MembershipType(Document):
    def validate(self):
        self.validate_billing_period()
        self.validate_amount()
        self.validate_contribution_system()

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
        if hasattr(self, "minimum_contribution"):
            self.minimum_contribution = flt(self.minimum_contribution, 2)
        if hasattr(self, "suggested_contribution"):
            self.suggested_contribution = flt(self.suggested_contribution, 2)
        if hasattr(self, "maximum_contribution"):
            self.maximum_contribution = flt(self.maximum_contribution, 2)

        # Ensure minimum contribution is not negative
        if hasattr(self, "minimum_contribution") and flt(self.minimum_contribution) < 0:
            self.minimum_contribution = 0.0

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

    def validate_contribution_system(self):
        """Validate the contribution system configuration"""
        # Skip validation during migration or if new fields are not available
        if (
            frappe.flags.in_migrate
            or not hasattr(self, "minimum_contribution")
            or not hasattr(self, "suggested_contribution")
        ):
            return

        # Set defaults for new fields if not set
        if not self.minimum_contribution:
            self.minimum_contribution = 5.0
        if not self.suggested_contribution:
            self.suggested_contribution = max(self.amount or 15.0, self.minimum_contribution or 5.0)
        if not self.fee_slider_max_multiplier:
            self.fee_slider_max_multiplier = 10.0
        if not self.contribution_mode:
            self.contribution_mode = "Calculator"

        # Only validate if we have all required fields
        try:
            # Ensure minimum and suggested amounts are reasonable
            if flt(self.minimum_contribution) < 0:
                frappe.throw(_("Minimum contribution cannot be negative"))

            if flt(self.suggested_contribution) < flt(self.minimum_contribution):
                # Auto-fix during migration
                self.suggested_contribution = max(flt(self.minimum_contribution), flt(self.amount or 15.0))

            # Validate maximum contribution if set
            if self.maximum_contribution and flt(self.maximum_contribution) < flt(
                self.suggested_contribution
            ):
                frappe.throw(_("Maximum contribution cannot be less than suggested contribution"))

            # Validate fee slider multiplier
            if flt(self.fee_slider_max_multiplier) <= 0:
                self.fee_slider_max_multiplier = 10.0

            # Validate income percentage rate
            if self.enable_income_calculator and flt(self.income_percentage_rate) <= 0:
                frappe.throw(_("Income percentage rate must be greater than 0"))

            # Validate tiers if present
            if self.contribution_mode in ["Tiers", "Both"] and self.predefined_tiers:
                self.validate_predefined_tiers()
        except Exception as e:
            # Log error during migration but don't fail
            if frappe.flags.in_migrate:
                frappe.log_error(f"Validation error during migration: {str(e)}", "MembershipType Validation")
            else:
                raise

    def validate_predefined_tiers(self):
        """Validate predefined tiers configuration"""
        tier_names = []
        has_default = False

        for tier in self.predefined_tiers:
            # Check for duplicate tier names
            if tier.tier_name in tier_names:
                frappe.throw(_("Duplicate tier name: {0}").format(tier.tier_name))
            tier_names.append(tier.tier_name)

            # Check tier amount is reasonable
            if flt(tier.amount) < flt(self.minimum_contribution):
                frappe.throw(
                    _("Tier '{0}' amount cannot be less than minimum contribution").format(tier.tier_name)
                )

            # Check for default tier
            if tier.is_default:
                if has_default:
                    frappe.throw(_("Only one tier can be marked as default"))
                has_default = True

    def get_contribution_options(self):
        """Get contribution options based on organization configuration"""
        options = {
            "mode": self.contribution_mode,
            "minimum": self.minimum_contribution,
            "suggested": self.suggested_contribution,
            "maximum": self.maximum_contribution
            or (self.suggested_contribution * self.fee_slider_max_multiplier),
            "calculator": {
                "enabled": self.enable_income_calculator,
                "percentage": self.income_percentage_rate,
                "description": self.calculator_description,
            },
        }

        if self.contribution_mode in ["Tiers", "Both"]:
            options["tiers"] = []
            for tier in self.predefined_tiers:
                options["tiers"].append(
                    {
                        "name": tier.tier_name,
                        "display_name": tier.display_name,
                        "amount": tier.amount,
                        "description": tier.description,
                        "requires_verification": tier.requires_verification,
                        "is_default": tier.is_default,
                        "display_order": tier.display_order or 0,
                    }
                )

        if self.contribution_mode in ["Calculator", "Both"]:
            # Generate fractional multipliers for calculator-based organizations
            multipliers = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
            options["quick_amounts"] = []
            for multiplier in multipliers:
                amount = self.suggested_contribution * multiplier
                if amount >= self.minimum_contribution:
                    options["quick_amounts"].append(
                        {
                            "multiplier": multiplier,
                            "amount": amount,
                            "label": f"{int(multiplier * 100)}%" if multiplier != 1.0 else "Suggested",
                            "is_default": multiplier == 1.0,
                        }
                    )

        return options


# Updated to use dues schedule system


@frappe.whitelist()
def get_membership_contribution_options(membership_type_name):
    """Get contribution options for a specific membership type"""
    membership_type = frappe.get_doc("Membership Type", membership_type_name)
    return membership_type.get_contribution_options()
