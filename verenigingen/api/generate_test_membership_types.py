"""
Generate proper test membership types with linked dues schedule templates
"""


import frappe


@frappe.whitelist()
def generate_test_membership_types():
    """
    Generate comprehensive test membership types for testing
    Includes dues schedule templates and proper billing frequency setup
    """

    # Ensure we have the membership item group
    ensure_membership_item_group()

    # Define test membership types with various configurations
    test_types = [
        {
            "membership_type_name": "TEST - Daily Membership",
            "description": "Test membership type with daily billing for short cycle testing",
            "billing_frequency": "Daily",
            "amount": 25.00,
            "currency": "EUR",
            "require_approval": 0,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Regular Monthly",
            "description": "Standard monthly membership for regular members",
            "billing_frequency": "Monthly",
            "amount": 100.00,
            "currency": "EUR",
            "require_approval": 0,
            "default_for_new_members": 1,
        },
        {
            "membership_type_name": "TEST - Student Monthly",
            "description": "Discounted monthly membership for students",
            "billing_frequency": "Monthly",
            "amount": 50.00,
            "currency": "EUR",
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Quarterly Premium",
            "description": "Premium quarterly membership with additional benefits",
            "billing_frequency": "Quarterly",
            "amount": 275.00,
            "currency": "EUR",
            "require_approval": 0,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Annual Corporate",
            "description": "Annual corporate membership for organizations",
            "billing_frequency": "Annual",
            "amount": 1200.00,
            "currency": "EUR",
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Lifetime Honorary",
            "description": "Lifetime honorary membership (no recurring fees)",
            "billing_frequency": "Lifetime",
            "amount": 0.00,
            "currency": "EUR",
            "require_approval": 1,
            "default_for_new_members": 0,
        },
        {
            "membership_type_name": "TEST - Custom 2-Month",
            "description": "Custom 2-month membership for testing custom periods",
            "billing_frequency": "Custom",
            "billing_frequency_months": 2,
            "amount": 180.00,
            "currency": "EUR",
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

            # Create dues schedule template if not already linked
            if not getattr(membership_type, "dues_schedule_template", None):
                try:
                    template_name = create_dues_schedule_template_for_membership_type(membership_type)
                    if template_name:
                        membership_type.dues_schedule_template = template_name
                        membership_type.save(ignore_permissions=True)
                except Exception as e:
                    # Log error but continue
                    frappe.log_error(
                        f"Failed to create dues schedule template for {membership_type.name}: {str(e)}"
                    )

            created_types.append(
                {
                    "name": membership_type.name,
                    "billing_frequency": membership_type.billing_frequency,
                    "minimum_amount": membership_type.minimum_amount,
                    "dues_schedule_template": getattr(membership_type, "dues_schedule_template", None),
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


def create_dues_schedule_template_for_membership_type(membership_type):
    """
    Create a dues schedule template for a membership type
    """
    try:
        # Create dues schedule template
        template = frappe.new_doc("Membership Dues Schedule Template")
        template.template_name = f"{membership_type.membership_type_name} - Template"
        template.membership_type = membership_type.name
        template.billing_frequency = membership_type.billing_frequency
        template.dues_rate = 15.0  # Default template amount
        template.currency = membership_type.currency
        template.contribution_mode = "Membership Fee"
        template.is_active = 1

        # Handle custom billing frequency
        if membership_type.billing_frequency == "Custom" and hasattr(
            membership_type, "billing_frequency_months"
        ):
            template.custom_months = membership_type.billing_frequency_months

        template.insert(ignore_permissions=True)
        frappe.db.commit()

        return template.name

    except Exception as e:
        frappe.log_error(f"Error creating dues schedule template: {str(e)}")
        return None


# Item creation is no longer needed for dues schedule system
# Dues schedules work directly with membership types


# Billing interval configuration is now handled directly in dues schedule templates


@frappe.whitelist()
def cleanup_test_membership_types():
    """Remove all test membership types and their associated data"""
    test_types = frappe.get_all(
        "Membership Type",
        filters={"membership_type_name": ["like", "TEST - %"]},
        fields=["name", "dues_schedule_template"],
    )

    deleted_count = 0
    deleted_templates = 0

    for mt in test_types:
        try:
            # Delete dues schedule template if exists
            template_name = getattr(mt, "dues_schedule_template", None)
            if template_name:
                if frappe.db.exists("Membership Dues Schedule Template", template_name):
                    frappe.delete_doc(
                        "Membership Dues Schedule Template", template_name, ignore_permissions=True
                    )
                    deleted_templates += 1

            # Delete membership type
            frappe.delete_doc("Membership Type", mt.name, ignore_permissions=True)
            deleted_count += 1

        except Exception as e:
            frappe.log_error(f"Failed to delete test membership type {mt.name}: {str(e)}")

    frappe.db.commit()

    return {
        "success": True,
        "deleted_membership_types": deleted_count,
        "deleted_dues_schedule_templates": deleted_templates,
    }


@frappe.whitelist()
def get_test_membership_types_status():
    """Get status of test membership types"""
    test_types = frappe.get_all(
        "Membership Type",
        filters={"membership_type_name": ["like", "TEST - %"]},
        fields=["name", "billing_period", "amount", "dues_schedule_template"],
    )

    # Group by billing period
    by_frequency = {}
    for mt in test_types:
        frequency = mt.billing_period
        if frequency not in by_frequency:
            by_frequency[frequency] = []
        by_frequency[frequency].append(mt)

    # Check linked dues schedule templates
    with_templates = len([mt for mt in test_types if getattr(mt, "dues_schedule_template", None)])
    without_templates = len(test_types) - with_templates

    return {
        "total": len(test_types),
        "by_frequency": by_frequency,
        "with_dues_schedule_templates": with_templates,
        "without_dues_schedule_templates": without_templates,
        "membership_types": test_types,
    }
