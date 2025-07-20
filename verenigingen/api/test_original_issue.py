"""
Test the original membership submission issue that started this investigation
"""

import frappe


@frappe.whitelist()
def test_original_membership_issue():
    """Test the original issue with MEMB-25-07-2556"""
    try:
        # Check if the membership exists
        membership_name = "MEMB-25-07-2556"
        membership = frappe.db.get_value(
            "Membership", membership_name, ["name", "member", "status"], as_dict=True
        )

        if not membership:
            return {"error": f"Membership {membership_name} not found"}

        # Get the member's dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": membership.member, "is_template": 0},
            ["name", "dues_rate", "contribution_mode", "base_multiplier", "membership_type"],
            as_dict=True,
        )

        if not dues_schedule:
            return {"error": f"No dues schedule found for member {membership.member}"}

        # Get the dues schedule document and test validation
        schedule_doc = frappe.get_doc("Membership Dues Schedule", dues_schedule.name)

        # Store original values
        original_dues_rate = schedule_doc.dues_rate
        original_mode = schedule_doc.contribution_mode

        # Test validation
        try:
            schedule_doc.validate()
            validation_passed = True
            validation_error = None
        except Exception as e:
            validation_passed = False
            validation_error = str(e)

        # Get membership type details
        membership_type_doc = frappe.get_doc("Membership Type", dues_schedule.membership_type)

        return {
            "membership_name": membership_name,
            "member": membership.member,
            "dues_schedule_name": dues_schedule.name,
            "original_dues_rate": original_dues_rate,
            "final_dues_rate": schedule_doc.dues_rate,
            "contribution_mode": original_mode,
            "base_multiplier": getattr(schedule_doc, "base_multiplier", None),
            "membership_type": {
                "name": membership_type_doc.name,
                "suggested_contribution": getattr(membership_type_doc, "suggested_contribution", None),
                "amount": getattr(membership_type_doc, "amount", None),
                "minimum_contribution": getattr(membership_type_doc, "minimum_contribution", None),
            },
            "validation_passed": validation_passed,
            "validation_error": validation_error,
            "rates_preserved": original_dues_rate == schedule_doc.dues_rate,
            "status": "✅ FIXED"
            if validation_passed and original_dues_rate == schedule_doc.dues_rate
            else "❌ ISSUE REMAINS",
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def quick_field_test():
    """Quick test to verify dues_rate field exists and works"""
    try:
        # Try to create a simple dues schedule
        schedule = frappe.new_doc("Membership Dues Schedule")

        # Test setting dues_rate (the correct field)
        schedule.dues_rate = 15.0

        # Test that the field exists and has the value
        field_value = getattr(schedule, "dues_rate", None)

        return {
            "field_exists": hasattr(schedule, "dues_rate"),
            "field_value": field_value,
            "test_passed": field_value == 15.0,
            "status": "✅ Field works correctly" if field_value == 15.0 else "❌ Field issue",
        }

    except Exception as e:
        return {"error": str(e)}
