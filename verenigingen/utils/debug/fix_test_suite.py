import frappe


@frappe.whitelist()
def identify_test_issues():
    """Identify common issues in test suite after template changes"""

    issues = {
        "duplicate_dues_schedule_tests": [],
        "invalid_amendment_types": [],
        "template_assignment_issues": [],
    }

    # Check for tests that manually create dues schedules after membership submission
    test_files_with_issues = [
        "test_billing_transitions_simplified.py",
        "test_billing_transitions_proper.py",
        "test_advanced_prorating.py",
        "test_comprehensive_prorating.py",
    ]

    issues["duplicate_dues_schedule_tests"] = test_files_with_issues

    # Invalid amendment types that need fixing
    invalid_types = [
        {
            "wrong": "Billing Frequency Change",
            "correct": "Billing Interval Change",
            "files": ["test_billing_transitions_simplified.py"],
        }
    ]

    issues["invalid_amendment_types"] = invalid_types

    # Check for membership types without templates (would break tests)
    missing_templates = frappe.db.sql(
        """
        SELECT name, membership_type_name
        FROM `tabMembership Type`
        WHERE (dues_schedule_template IS NULL OR dues_schedule_template = '')
        AND is_active = 1
    """,
        as_dict=True,
    )

    issues["template_assignment_issues"] = missing_templates

    return {
        "total_issues": len(issues["duplicate_dues_schedule_tests"])
        + len(issues["invalid_amendment_types"])
        + len(issues["template_assignment_issues"]),
        "issues": issues,
        "recommendations": [
            "Update tests to either: 1) Not submit membership, 2) Check for existing dues schedule, or 3) Use the auto-created schedule",
            "Replace 'Billing Frequency Change' with 'Billing Interval Change' in amendment requests",
            "Ensure all membership types have template assignments before running tests",
        ],
    }


@frappe.whitelist()
def get_test_suite_status():
    """Get overall status of test suite compatibility"""

    # Test basic functionality
    try:
        # Try to create a member (should work)
        from verenigingen.tests.fixtures.test_data_factory import TestDataFactory

        factory = TestDataFactory()

        test_member_name = f"TEST-Suite-Check-{frappe.utils.now()}"

        member = factory.create_test_member(
            name=test_member_name,
            first_name="TestSuite",
            last_name="Check",
            email="testsuite.check@example.com",
        )

        # Clean up immediately
        frappe.delete_doc("Member", member.name)
        frappe.db.commit()

        member_creation_works = True
        member_error = None

    except Exception as e:
        member_creation_works = False
        member_error = str(e)

    # Test membership creation
    try:
        from verenigingen.tests.fixtures.test_data_factory import TestDataFactory

        factory = TestDataFactory()

        # Get a membership type with template
        membership_type = frappe.db.get_value(
            "Membership Type", {"is_active": 1, "dues_schedule_template": ["!=", ""]}, "name"
        )

        if membership_type:
            test_member_name = f"TEST-Membership-Check-{frappe.utils.now()}"

            member = factory.create_test_member(
                name=test_member_name,
                first_name="TestMembership",
                last_name="Check",
                email="testmembership.check@example.com",
            )

            membership = factory.create_test_membership(member=member.name, membership_type=membership_type)

            # Clean up
            frappe.delete_doc("Membership", membership.name)
            frappe.delete_doc("Member", member.name)
            frappe.db.commit()

            membership_creation_works = True
            membership_error = None
        else:
            membership_creation_works = False
            membership_error = "No membership types with templates found"

    except Exception as e:
        membership_creation_works = False
        membership_error = str(e)

    return {
        "member_creation_works": member_creation_works,
        "member_error": member_error,
        "membership_creation_works": membership_creation_works,
        "membership_error": membership_error,
        "overall_status": "WORKING" if (member_creation_works and membership_creation_works) else "BROKEN",
    }
