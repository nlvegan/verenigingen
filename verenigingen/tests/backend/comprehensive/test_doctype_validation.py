"""
Comprehensive unit tests for doctype validation issues to prevent field validation bugs
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase, shared_fixture
from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
import unittest


class TestDoctypeValidationComprehensive(EnhancedTestCase):
    """Test doctype field validations to catch validation issues early"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        # EnhancedTestCase handles permissions automatically

    def tearDown(self):
        """Clean up after tests"""
        frappe.db.rollback()
        super().tearDown()

    def test_volunteer_status_validation(self):
        """Test that volunteer status field accepts only valid values"""

        # Get valid status options from doctype
        volunteer_meta = frappe.get_meta("Volunteer")
        status_field = None
        for field in volunteer_meta.fields:
            if field.fieldname == "status":
                status_field = field
                break

        self.assertIsNotNone(status_field, "Status field should exist in Volunteer doctype")
        valid_options = status_field.options.split("\n") if status_field.options else []
        self.assertTrue(len(valid_options) > 0, "Status field should have valid options defined")

        # Test each valid status option
        for status in valid_options:
            if status.strip():  # Skip empty lines
                with self.subTest(status=status):
                    volunteer = frappe.get_doc(
                        {
                            "doctype": "Volunteer",
                            "volunteer_name": f"Test {status} Volunteer",
                            "email": f"test.{status.lower()}@example.com",
                            "first_name": "Test",
                            "last_name": status,
                            "status": status.strip(),
                            "available": 1,
                            "date_joined": today()}
                    )

                    # This should not raise an exception
                    try:
                        volunteer.insert()
                        volunteer.delete()  # Clean up immediately
                    except Exception as e:
                        self.fail(f"Valid status '{status}' should not cause validation error: {str(e)}")

        # Test invalid status values
        invalid_statuses = ["Pending", "Submitted", "Approved", "Draft", "Invalid"]
        for invalid_status in invalid_statuses:
            with self.subTest(invalid_status=invalid_status):
                volunteer = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": f"Test {invalid_status} Volunteer",
                        "email": f"test.invalid.{invalid_status.lower()}@example.com",
                        "first_name": "Test",
                        "last_name": "Invalid",
                        "status": invalid_status,
                        "available": 1,
                        "date_joined": today()}
                )

                # EnhancedTestCase runs with frappe.flags.in_import=True, which
                # SKIPS Frappe's Select-field validation. production_validation()
                # clears it so the invalid Select value is actually rejected
                # (production behavior).
                with self.production_validation():
                    # This should raise a validation exception
                    with self.assertRaises(frappe.ValidationError):
                        volunteer.insert()

    def test_member_status_validation(self):
        """Test member status field validation"""

        # Get valid status options for Member
        member_meta = frappe.get_meta("Member")
        status_field = None
        for field in member_meta.fields:
            if field.fieldname == "status":
                status_field = field
                break

        if status_field and status_field.options:
            valid_options = [opt.strip() for opt in status_field.options.split("\n") if opt.strip()]

            for status in valid_options:
                with self.subTest(status=status):
                    member = frappe.get_doc(
                        {
                            "doctype": "Member",
                            "first_name": "Test",
                            "last_name": f"{status} Member",
                            "email": f"test.member.{status.lower().replace(' ', '')}@example.com",
                            "status": status}
                    )

                    try:
                        member.insert()
                        member.delete()
                    except Exception as e:
                        self.fail(
                            f"Valid member status '{status}' should not cause validation error: {str(e)}"
                        )

    def test_application_status_validation(self):
        """Test application_status field validation for Member doctype"""

        # Common application status values that should be valid
        valid_app_statuses = ["Pending", "Under Review", "Approved", "Rejected"]

        for app_status in valid_app_statuses:
            with self.subTest(app_status=app_status):
                member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "first_name": "Test",
                        "last_name": f"App {app_status} Member",
                        "email": f"test.app.{app_status.lower().replace(' ', '')}@example.com",
                        "application_status": app_status}
                )

                try:
                    member.insert()
                    member.delete()
                except Exception as e:
                    self.fail(
                        f"Valid application status '{app_status}' should not cause validation error: {str(e)}"
                    )

    def test_volunteer_creation_in_application_flow(self):
        """Test volunteer creation as part of membership application"""

        # Test the create_volunteer_record function with proper member setup
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Volunteer Application",
                "email": "test.volunteer.app@example.com",
                "application_status": "Pending"}
        )
        member.insert()

        # Set volunteer interest
        member.interested_in_volunteering = 1

        # Import and test the function
        from verenigingen.utils.application_helpers import create_volunteer_record

        volunteer = create_volunteer_record(member)

        if volunteer:
            # Verify the volunteer was created with correct status
            self.assertEqual(volunteer.status, "New", "Volunteer should be created with 'New' status")
            # The volunteer's `email` is the ORGANIZATION email, which is intentionally
            # NOT set at creation (create_volunteer_from_member assigns it later when a
            # system account is provisioned). So it should be empty here, not the
            # member's personal email.
            self.assertIn(volunteer.email, (None, ""), "Volunteer org email is assigned later, not at creation")
            # The volunteer is linked back to the member.
            self.assertEqual(volunteer.member, member.name)

            # Clean up: clear the member's volunteer_record link first, otherwise
            # deleting the volunteer raises LinkExistsError.
            frappe.db.set_value("Member", member.name, "volunteer_record", None, update_modified=False)
            volunteer.delete()

        member.delete()

    @shared_fixture
    def _ensure_membership_type(self, name="Maandlid"):
        """Self-seed the membership type the application submission references.

        The test site may not ship the 'Maandlid' master, which would make
        submit_application fail with 'Could not find Selected Membership Type'.

        @shared_fixture (#1026): site-wide master data, no company/test scope.
        """
        if not frappe.db.exists("Membership Type", name):
            role_profile = frappe.db.get_value(
                "Role Profile", "Verenigingen Member", "name"
            ) or frappe.db.get_value("Role Profile", {}, "name")
            frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": name,
                    "billing_period": "Monthly",
                    "is_active": 1,
                    "minimum_amount": 10.0,
                    "amount": 10.0,
                    "role_profile": role_profile,
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()
        return name

    def test_doctype_select_field_validations(self):
        """Test that all select fields in key doctypes have proper validation"""

        key_doctypes = ["Member", "Volunteer", "Membership", "Chapter"]

        for doctype_name in key_doctypes:
            with self.subTest(doctype=doctype_name):
                try:
                    meta = frappe.get_meta(doctype_name)
                    select_fields = [field for field in meta.fields if field.fieldtype == "Select"]

                    for field in select_fields:
                        # Check that select fields have options defined
                        if field.fieldname in ["status", "application_status", "payment_status"]:
                            self.assertTrue(
                                field.options and field.options.strip(),
                                f"{doctype_name}.{field.fieldname} should have options defined",
                            )

                            # Verify options are not empty after splitting
                            options = [opt.strip() for opt in field.options.split("\n") if opt.strip()]
                            self.assertTrue(
                                len(options) > 0,
                                f"{doctype_name}.{field.fieldname} should have at least one valid option",
                            )

                except frappe.DoesNotExistError:
                    # Skip if doctype doesn't exist
                    pass


def run_validation_tests():
    """Run all validation tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDoctypeValidationComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def run_doctype_validation_tests():
    """Whitelisted function to run doctype validation tests"""
    try:
        # Run the tests
        result = run_validation_tests()

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "failure_details": [f"{test}: {error}" for test, error in result.failures],
            "error_details": [f"{test}: {error}" for test, error in result.errors],
            "message": f"Validation tests completed: {result.testsRun} tests, {len(result.failures)} failures, {len(result.errors)} errors"}
    except Exception as e:
        return {"success": False, "error": str(e), "message": f"Test execution failed: {str(e)}"}


if __name__ == "__main__":
    run_validation_tests()
