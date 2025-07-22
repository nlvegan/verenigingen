import frappe


@frappe.whitelist()
def test_membership_creation_with_field():
    """Test that creating a membership properly sets the membership field in dues schedule"""

    try:
        # Clean up any existing test data
        frappe.db.delete("Membership Dues Schedule", {"member": "TEST-MEMBER-FIELD-123"})
        frappe.db.delete("Membership", {"member": "TEST-MEMBER-FIELD-123"})
        frappe.db.delete("Member", {"name": "TEST-MEMBER-FIELD-123"})
        frappe.db.commit()

        # Create test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "name": "TEST-MEMBER-FIELD-123",
                "member_id": "TEST-FIELD-123",
                "first_name": "Test",
                "last_name": "MembershipField",
                "full_name": "Test MembershipField",
                "email": "test.membershipfield@example.com",
                "date_of_birth": "1990-01-01",
                "status": "Active",
            }
        )
        member.insert()

        # Get a membership type
        membership_type = frappe.db.get_value("Membership Type", filters={"is_active": 1}, fieldname="name")
        if not membership_type:
            return {"error": "No active membership types found"}

        # Create test membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type,
                "start_date": "2025-07-22",
                "status": "Active",
            }
        )
        membership.insert()
        membership.submit()  # This should trigger dues schedule creation

        # Check if dues schedule was created with membership field
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0},
            ["name", "membership", "member", "membership_type"],
            as_dict=True,
        )

        result = {
            "member_created": member.name,
            "membership_created": membership.name,
            "dues_schedule_found": bool(dues_schedule),
        }

        if dues_schedule:
            result.update(
                {
                    "dues_schedule_name": dues_schedule.name,
                    "dues_schedule_membership_field": dues_schedule.membership,
                    "membership_field_populated": bool(dues_schedule.membership),
                    "membership_field_correct": dues_schedule.membership == membership.name,
                }
            )

            if dues_schedule.membership == membership.name:
                result["status"] = "SUCCESS - Membership field properly populated!"
            else:
                result[
                    "status"
                ] = f"ERROR - Membership field incorrect: expected {membership.name}, got {dues_schedule.membership}"
        else:
            result["status"] = "ERROR - No dues schedule created"

        return result

    except Exception as e:
        return {"error": str(e), "status": "FAILED"}


@frappe.whitelist()
def cleanup_test_membership_field():
    """Clean up test data"""
    try:
        frappe.db.delete("Membership Dues Schedule", {"member": "TEST-MEMBER-FIELD-123"})
        frappe.db.delete("Membership", {"member": "TEST-MEMBER-FIELD-123"})
        frappe.db.delete("Member", {"name": "TEST-MEMBER-FIELD-123"})
        frappe.db.commit()
        return {"status": "Cleanup completed"}
    except Exception as e:
        return {"error": str(e)}
