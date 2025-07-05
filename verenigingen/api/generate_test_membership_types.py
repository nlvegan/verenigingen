"""
Generate proper test membership types with linked subscription plans
"""


import frappe


@frappe.whitelist()
def generate_test_membership_types():
    """
    Generate comprehensive test membership types for testing
    Includes subscription plans and proper item setup
    """

    # Ensure we have the membership item group
    ensure_membership_item_group()

    # Define test membership types with various configurations
    test_types = [
        {
            "membership_type_name": "TEST - Daily Membership",
            "description": "Test membership type with daily billing for short cycle testing",
            "subscription_period": "Daily",
            "amount": 25.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 0,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Regular Monthly",
            "description": "Standard monthly membership for regular members",
            "subscription_period": "Monthly",
            "amount": 100.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 0,
            "default_for_new_members": 1,
        },
        {
            "membership_type_name": "TEST - Student Monthly",
            "description": "Discounted monthly membership for students",
            "subscription_period": "Monthly",
            "amount": 50.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Quarterly Premium",
            "description": "Premium quarterly membership with additional benefits",
            "subscription_period": "Quarterly",
            "amount": 275.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 0,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Annual Corporate",
            "description": "Annual corporate membership for organizations",
            "subscription_period": "Annual",
            "amount": 1200.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Lifetime Honorary",
            "description": "Lifetime honorary membership (no recurring fees)",
            "subscription_period": "Lifetime",
            "amount": 0.00,
            "currency": "EUR",
            "allow_auto_renewal": 0,
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Custom 2-Month",
            "description": "Custom 2-month membership for testing custom periods",
            "subscription_period": "Custom",
            "subscription_period_in_months": 2,
            "amount": 180.00,
            "currency": "EUR",
            "allow_auto_renewal": 1,
            "require_approval": 0,
            "default_for_new_members": 0,
        },
    ]

    created_types = []
    errors = []

    for type_data in test_types:
        try:
            # Check if already exists
            if frappe.db.exists("Membership Type", type_data["membership_type_name"]):
                # Update existing
                membership_type = frappe.get_doc("Membership Type", type_data["membership_type_name"])
                for key, value in type_data.items():
                    setattr(membership_type, key, value)
                membership_type.save(ignore_permissions=True)
                action = "updated"
            else:
                # Create new
                membership_type = frappe.new_doc("Membership Type")
                for key, value in type_data.items():
                    setattr(membership_type, key, value)
                membership_type.insert(ignore_permissions=True)
                action = "created"

            # Create subscription plan if not already linked
            if not membership_type.subscription_plan:
                try:
                    plan_name = create_subscription_plan_for_membership_type(membership_type)
                    if plan_name:
                        membership_type.subscription_plan = plan_name
                        membership_type.save(ignore_permissions=True)
                except Exception as e:
                    # Log error but continue
                    frappe.log_error(
                        f"Failed to create subscription plan for {membership_type.name}: {str(e)}"
                    )

            created_types.append(
                {
                    "name": membership_type.name,
                    "subscription_period": membership_type.subscription_period,
                    "amount": membership_type.amount,
                    "subscription_plan": membership_type.subscription_plan,
                    "action": action,
                }
            )

        except Exception as e:
            errors.append({"membership_type": type_data["membership_type_name"], "error": str(e)})

    # Generate summary
    summary = {
        "total_created": len([t for t in created_types if t["action"] == "created"]),
        "total_updated": len([t for t in created_types if t["action"] == "updated"]),
        "total_errors": len(errors),
    }

    return {"success": True, "summary": summary, "membership_types": created_types, "errors": errors}


def ensure_membership_item_group():
    """Ensure the Membership item group exists"""
    if not frappe.db.exists("Item Group", "Membership"):
        item_group = frappe.new_doc("Item Group")
        item_group.item_group_name = "Membership"
        item_group.parent_item_group = "All Item Groups"
        item_group.is_group = 0
        item_group.insert(ignore_permissions=True)
        frappe.db.commit()


def create_subscription_plan_for_membership_type(membership_type):
    """
    Create a subscription plan for a membership type with proper item setup
    """
    try:
        # Get or create membership item
        item_name = get_or_create_membership_item(membership_type)
        if not item_name:
            return None

        # Determine billing interval and count based on subscription period
        interval_config = get_billing_interval_config(membership_type)

        # Create subscription plan
        plan = frappe.new_doc("Subscription Plan")
        plan.plan_name = f"{membership_type.membership_type_name} - Plan"
        plan.currency = membership_type.currency

        # Add plan details
        plan.append("plans", {"item": item_name, "qty": 1, "rate": membership_type.amount})

        # Set billing interval
        plan.billing_interval = interval_config["interval"]
        plan.billing_interval_count = interval_config["count"]

        # Additional settings
        plan.price_determination = "Fixed Rate"

        plan.insert(ignore_permissions=True)
        frappe.db.commit()

        return plan.name

    except Exception as e:
        frappe.log_error(f"Error creating subscription plan: {str(e)}")
        return None


def get_or_create_membership_item(membership_type):
    """Get or create an item for the membership type"""
    try:
        item_code = f"MEM-{membership_type.membership_type_name}".upper().replace(" ", "-")

        # Check if item exists
        if frappe.db.exists("Item", item_code):
            return item_code

        # Get default company
        company = frappe.defaults.get_global_default("company")
        if not company:
            companies = frappe.get_all("Company", limit=1)
            if companies:
                company = companies[0].name

        # Create new item
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = f"{membership_type.membership_type_name} Membership"
        item.item_group = "Membership"
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.include_item_in_manufacturing = 0
        item.is_sales_item = 1
        item.is_service_item = 1

        # Set item defaults if company exists
        if company:
            item.append("item_defaults", {"company": company, "default_warehouse": None})

        item.insert(ignore_permissions=True)
        frappe.db.commit()

        return item.name

    except Exception as e:
        frappe.log_error(f"Error creating membership item: {str(e)}")
        return None


def get_billing_interval_config(membership_type):
    """Get billing interval configuration based on membership type"""
    # Map subscription periods to ERPNext billing intervals
    config_map = {
        "Daily": {"interval": "Day", "count": 1},
        "Monthly": {"interval": "Month", "count": 1},
        "Quarterly": {"interval": "Month", "count": 3},
        "Biannual": {"interval": "Month", "count": 6},
        "Annual": {"interval": "Year", "count": 1},
        "Lifetime": {"interval": "Year", "count": 1},
        "Custom": {"interval": "Month", "count": membership_type.subscription_period_in_months or 1},
    }

    return config_map.get(membership_type.subscription_period, {"interval": "Month", "count": 1})


@frappe.whitelist()
def cleanup_test_membership_types():
    """Remove all test membership types and their associated data"""
    test_types = frappe.get_all(
        "Membership Type",
        filters={"membership_type_name": ["like", "TEST - %"]},
        fields=["name", "subscription_plan"],
    )

    deleted_count = 0
    deleted_plans = 0
    deleted_items = 0

    for mt in test_types:
        try:
            # Delete subscription plan if exists
            if mt.subscription_plan:
                if frappe.db.exists("Subscription Plan", mt.subscription_plan):
                    # Get item from plan before deleting
                    plan_items = frappe.get_all(
                        "Subscription Plan Detail", filters={"parent": mt.subscription_plan}, fields=["item"]
                    )

                    frappe.delete_doc("Subscription Plan", mt.subscription_plan, ignore_permissions=True)
                    deleted_plans += 1

                    # Delete associated items
                    for plan_item in plan_items:
                        if plan_item.item and plan_item.item.startswith("MEM-TEST"):
                            if frappe.db.exists("Item", plan_item.item):
                                frappe.delete_doc("Item", plan_item.item, ignore_permissions=True)
                                deleted_items += 1

            # Delete membership type
            frappe.delete_doc("Membership Type", mt.name, ignore_permissions=True)
            deleted_count += 1

        except Exception as e:
            frappe.log_error(f"Failed to delete test membership type {mt.name}: {str(e)}")

    frappe.db.commit()

    return {
        "success": True,
        "deleted_membership_types": deleted_count,
        "deleted_subscription_plans": deleted_plans,
        "deleted_items": deleted_items,
    }


@frappe.whitelist()
def get_test_membership_types_status():
    """Get status of test membership types"""
    test_types = frappe.get_all(
        "Membership Type",
        filters={"membership_type_name": ["like", "TEST - %"]},
        fields=["name", "subscription_period", "amount", "subscription_plan", "currency"],
    )

    # Group by subscription period
    by_period = {}
    for mt in test_types:
        period = mt.subscription_period
        if period not in by_period:
            by_period[period] = []
        by_period[period].append(mt)

    # Check linked subscription plans
    with_plans = len([mt for mt in test_types if mt.subscription_plan])
    without_plans = len(test_types) - with_plans

    return {
        "total": len(test_types),
        "by_period": by_period,
        "with_subscription_plans": with_plans,
        "without_subscription_plans": without_plans,
        "membership_types": test_types,
    }
