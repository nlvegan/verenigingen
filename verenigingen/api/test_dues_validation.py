"""
Test the dues rate validation fix
"""

import frappe


@frappe.whitelist()
def test_membership_dues_validation(membership_name="MEMB-25-07-2556"):
    """Test the dues rate validation for specific membership"""
    try:
        # Get the membership document
        membership = frappe.get_doc("Membership", membership_name)

        # Get the member's dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": membership.member, "is_template": 0},
            ["name", "dues_rate", "contribution_mode", "base_multiplier", "membership_type"],
            as_dict=True,
        )

        if not dues_schedule:
            return {
                "error": f"No dues schedule found for member {membership.member}",
                "membership_name": membership_name,
            }

        # Get the membership type details
        membership_type = frappe.get_doc("Membership Type", dues_schedule.membership_type)

        # Load the actual dues schedule document
        schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule.name)

        # Get original values before validation
        original_dues_rate = schedule_doc.dues_rate
        original_contribution_mode = schedule_doc.contribution_mode

        # Test the validation
        try:
            schedule_doc.validate()
            validation_passed = True
            validation_error = None
        except Exception as e:
            validation_passed = False
            validation_error = str(e)

        return {
            "membership_name": membership_name,
            "member": membership.member,
            "dues_schedule_name": dues_schedule.name,
            "original_dues_rate": original_dues_rate,
            "final_dues_rate": schedule_doc.dues_rate,
            "contribution_mode": original_contribution_mode,
            "base_multiplier": getattr(schedule_doc, "base_multiplier", None),
            "membership_type": {
                "name": membership_type.name,
                "suggested_contribution": getattr(membership_type, "suggested_contribution", None),
                "amount": getattr(membership_type, "amount", None),
                "minimum_contribution": getattr(membership_type, "minimum_contribution", None),
            },
            "validation_passed": validation_passed,
            "validation_error": validation_error,
            "rates_match": original_dues_rate == schedule_doc.dues_rate,
            "status": "✅ Fixed - dues rate preserved"
            if validation_passed and original_dues_rate == schedule_doc.dues_rate
            else "❌ Issue remains",
        }

    except Exception as e:
        return {"error": str(e), "membership_name": membership_name}


@frappe.whitelist()
def test_manager_override_permissions():
    """Test that managers can set higher fees"""
    try:
        # Check current user roles
        current_user = frappe.session.user
        user_roles = frappe.get_roles(current_user)

        # Check if user has management permissions
        can_override = any(
            role in user_roles
            for role in ["System Manager", "Verenigingen Administrator", "Membership Manager"]
        )

        # Get Verenigingen Settings
        settings = frappe.get_single("Verenigingen Settings")
        max_fee_multiplier = getattr(settings, "maximum_fee_multiplier", None)

        return {
            "current_user": current_user,
            "user_roles": user_roles,
            "can_override_fees": can_override,
            "max_fee_multiplier": max_fee_multiplier,
            "manager_roles_present": bool(
                set(["System Manager", "Verenigingen Administrator", "Membership Manager"]) & set(user_roles)
            ),
        }

    except Exception as e:
        return {"error": str(e)}
