import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MembershipType(Document):
    def validate(self):
        self.validate_subscription_period()
        self.validate_amount()
        self.validate_subscription_plan()

    def validate_subscription_period(self):
        # Ensure subscription_period_in_months is set for custom periods
        if self.subscription_period == "Custom" and not self.subscription_period_in_months:
            frappe.throw(_("Subscription Period in Months is required for Custom subscription period"))

        # Clear subscription_period_in_months for non-custom periods
        if self.subscription_period != "Custom":
            self.subscription_period_in_months = None

    def validate_amount(self):
        # Ensure amount is positive
        if flt(self.amount) < 0:
            frappe.throw(_("Amount cannot be negative"))

    def validate_subscription_plan(self):
        # If subscription_plan is set, validate it exists
        if self.subscription_plan and not frappe.db.exists("Subscription Plan", self.subscription_plan):
            frappe.throw(_("Subscription Plan {0} does not exist").format(self.subscription_plan))

        # If subscription_plan is set but linked to another membership type, warn user
        if self.subscription_plan:
            other_membership_types = frappe.get_all(
                "Membership Type",
                filters={"subscription_plan": self.subscription_plan, "name": ["!=", self.name]},
                fields=["name"],
            )

            if other_membership_types:
                frappe.msgprint(
                    _("Subscription Plan {0} is also linked to Membership Type {1}").format(
                        self.subscription_plan, other_membership_types[0].name
                    ),
                    indicator="orange",
                    alert=True,
                )

    def create_subscription_plan(self):
        """Create a subscription plan matching this membership type"""
        if self.subscription_plan:
            frappe.msgprint(_("Subscription Plan {0} already linked").format(self.subscription_plan))
            return self.subscription_plan

        # Determine plan interval based on subscription period
        # ERPNext only supports Day, Week, Month, Year
        interval_map = {
            "Daily": "Day",
            "Monthly": "Month",
            "Quarterly": "Month",  # Will use 3 months
            "Biannual": "Month",  # Will use 6 months
            "Annual": "Year",
            "Lifetime": "Year",  # ERPNext doesn't have 'Lifetime', use Year
            "Custom": "Month",  # Custom will use months as the base unit
        }

        interval = interval_map.get(self.subscription_period, "Month")

        # Calculate interval count for custom periods
        interval_count_map = {
            "Daily": 1,  # 1 day
            "Monthly": 1,  # 1 month
            "Quarterly": 3,  # 3 months
            "Biannual": 6,  # 6 months
            "Annual": 1,  # 1 year
            "Lifetime": 1,  # 1 year
            "Custom": self.subscription_period_in_months or 1,
        }

        interval_count = interval_count_map.get(self.subscription_period, 1)

        # Create new subscription plan
        plan = frappe.new_doc("Subscription Plan")
        plan.plan_name = self.membership_type_name
        plan.item = self.get_or_create_membership_item()
        plan.price_determination = "Fixed Rate"
        plan.cost = self.amount
        plan.billing_interval = interval
        plan.billing_interval_count = interval_count

        # Handle GST/tax if applicable
        if (
            hasattr(self, "tax_inclusive")
            and self.tax_inclusive
            and hasattr(self, "tax_rate")
            and self.tax_rate
        ):
            plan.is_including_tax = 1
            # Would need to handle tax template assignment here

        plan.flags.ignore_mandatory = True
        plan.insert(ignore_permissions=True)

        # Link the created plan back to membership type
        self.subscription_plan = plan.name
        self.save()

        frappe.msgprint(_("Subscription Plan {0} created successfully").format(plan.name))
        return plan.name

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
        item.is_subscription_item = 1

        # Set item defaults
        item.append(
            "item_defaults",
            {"company": frappe.defaults.get_global_default("company"), "default_warehouse": None},
        )

        item.flags.ignore_mandatory = True
        item.insert(ignore_permissions=True)

        frappe.msgprint(_("Item {0} created for membership type").format(item.name))
        return item.name


@frappe.whitelist()
def create_subscription_plan(membership_type_name):
    """Create a subscription plan from a membership type"""
    membership_type = frappe.get_doc("Membership Type", membership_type_name)
    return membership_type.create_subscription_plan()
