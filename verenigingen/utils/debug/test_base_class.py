import frappe


@frappe.whitelist()
def test_base_class_functionality():
    """Test if the base test class still works after template changes"""

    try:
        from verenigingen.tests.utils.base import VereningingenTestCase

        # Create a test instance
        test_case = VereningingenTestCase()
        test_case.setUp()

        # Test member creation
        member = test_case.create_test_member(
            first_name="TestBase", last_name="Member", email="testbase.member@example.com"
        )

        member_success = True
        member_error = None
        member_name = member.name

        # Test membership creation
        try:
            # Get a membership type with template
            membership_type = frappe.db.get_value(
                "Membership Type", {"is_active": 1, "dues_schedule_template": ["!=", ""]}, "name"
            )

            if membership_type:
                membership = test_case.create_test_membership(
                    member=member.name, membership_type=membership_type
                )

                membership_success = True
                membership_error = None
                membership_name = membership.name
            else:
                membership_success = False
                membership_error = "No membership types with templates found"
                membership_name = None

        except Exception as e:
            membership_success = False
            membership_error = str(e)
            membership_name = None

        # Clean up
        test_case.tearDown()

        return {
            "base_class_works": True,
            "member_creation": {"success": member_success, "error": member_error, "member_name": member_name},
            "membership_creation": {
                "success": membership_success,
                "error": membership_error,
                "membership_name": membership_name,
            },
            "overall_status": "WORKING" if (member_success and membership_success) else "PARTIALLY_WORKING",
        }

    except Exception as e:
        return {"base_class_works": False, "error": str(e), "overall_status": "BROKEN"}
