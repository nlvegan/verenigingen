"""
Validation regression test suite to prevent field validation bugs
"""

import unittest

import frappe
from frappe.utils import today


class TestValidationRegression(unittest.TestCase):
    """Regression tests to catch validation issues before they reach production"""

    @classmethod
    def setUpClass(cls):
        """Set up class-level fixtures"""
        frappe.set_user("Administrator")

    def setUp(self):
        """Set up test environment"""
        self.cleanup_records = []

    def tearDown(self):
        """Clean up test records"""
        try:
            for doctype, name in self.cleanup_records:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()

    def add_cleanup(self, doctype, name):
        """Add record to cleanup list"""
        self.cleanup_records.append((doctype, name))

    def test_critical_doctype_select_fields(self):
        """Test that critical select fields have proper validation"""

        critical_validations = {
            "Volunteer": {
                "status": {
                    "valid": ["New", "Onboarding", "Active", "Inactive", "Retired"],
                    "invalid": ["Pending", "Draft", "Submitted", "Approved"]}
            },
            "Member": {
                "application_status": {
                    "valid": ["Pending", "Under Review", "Approved", "Rejected"],
                    "invalid": ["New", "Draft", "Submitted"]}
            }}

        for doctype_name, field_validations in critical_validations.items():
            for field_name, validation_data in field_validations.items():
                # Test valid values
                for valid_value in validation_data["valid"]:
                    with self.subTest(doctype=doctype_name, field=field_name, value=valid_value):
                        try:
                            doc_data = self._get_minimal_doc_data(doctype_name)
                            doc_data[field_name] = valid_value

                            doc = frappe.get_doc(doc_data)
                            doc.insert(ignore_permissions=True)
                            self.add_cleanup(doctype_name, doc.name)

                        except Exception as e:
                            self.fail(
                                f"Valid value '{valid_value}' for {doctype_name}.{field_name} should not cause error: {str(e)}"
                            )

                # Test invalid values
                for invalid_value in validation_data["invalid"]:
                    with self.subTest(doctype=doctype_name, field=field_name, value=invalid_value):
                        try:
                            doc_data = self._get_minimal_doc_data(doctype_name)
                            doc_data[field_name] = invalid_value

                            doc = frappe.get_doc(doc_data)

                            # This should raise a ValidationError
                            with self.assertRaises(frappe.ValidationError):
                                doc.insert(ignore_permissions=True)

                        except AssertionError:
                            raise  # Re-raise assertion errors
                        except Exception:
                            # Other exceptions are also acceptable for invalid values
                            pass

    def _get_minimal_doc_data(self, doctype_name):
        """Get minimal data required to create a document"""

        base_data = {
            "doctype": doctype_name}

        if doctype_name == "Volunteer":
            base_data.update(
                {
                    "volunteer_name": f"Test Volunteer {frappe.utils.random_string(5)}",
                    "email": f"test.volunteer.{frappe.utils.random_string(5).lower()}@example.com",
                    "first_name": "Test",
                    "last_name": "Volunteer",
                    "available": 1,
                    "date_joined": today()}
            )
        elif doctype_name == "Member":
            base_data.update(
                {
                    "first_name": "Test",
                    "last_name": f"Member {frappe.utils.random_string(5)}",
                    "email": f"test.member.{frappe.utils.random_string(5).lower()}@example.com"}
            )

        return base_data

    def test_application_flow_volunteer_status_regression(self):
        """Regression test for the volunteer status bug that was fixed"""

        # This test specifically checks that the bug we fixed doesn't regress
        test_data = {
            "first_name": "Regression",
            "last_name": f"Test Volunteer {frappe.utils.random_string(5)}",
            "email": f"regression.test.{frappe.utils.random_string(5).lower()}@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Regression Test Street 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands",
            "selected_membership_type": "Maandlid",
            "interested_in_volunteering": 1,
            "payment_method": "Bank Transfer"}

        from verenigingen.api.membership_application import submit_application

        # This should NOT fail with volunteer status validation error
        result = submit_application(data=test_data)

        self.assertTrue(
            result.get("success"),
            f"Application submission should succeed - regression check failed: {result}",
        )

        if result.get("success"):
            member_record = result.get("member_record")
            self.add_cleanup("Member", member_record)

            # Verify volunteer was created with correct status
            volunteers = frappe.get_all(
                "Volunteer", filters={"member": member_record}, fields=["name", "status"]
            )

            if volunteers:
                self.add_cleanup("Volunteer", volunteers[0]["name"])
                self.assertEqual(
                    volunteers[0]["status"],
                    "New",
                    "Volunteer status regression: should be 'New', not 'Pending'",
                )

            # Clean up address if created
            member = frappe.get_doc("Member", member_record)
            if member.primary_address:
                self.add_cleanup("Address", member.primary_address)

    def test_doctype_field_consistency(self):
        """Test that doctype fields are consistent and properly defined"""

        critical_doctypes = ["Member", "Volunteer", "Membership", "Chapter"]

        for doctype_name in critical_doctypes:
            with self.subTest(doctype=doctype_name):
                try:
                    meta = frappe.get_meta(doctype_name)

                    # Check for status fields
                    status_fields = [f for f in meta.fields if f.fieldname.endswith("status")]

                    for field in status_fields:
                        if field.fieldtype == "Select":
                            # Select fields should have options
                            self.assertTrue(
                                field.options and field.options.strip(),
                                f"{doctype_name}.{field.fieldname} select field should have options",
                            )

                            # Options should not be empty after parsing
                            options = [opt.strip() for opt in field.options.split("\n") if opt.strip()]
                            self.assertTrue(
                                len(options) > 0,
                                f"{doctype_name}.{field.fieldname} should have valid options",
                            )

                except frappe.DoesNotExistError:
                    # Skip if doctype doesn't exist
                    pass

    def test_helper_function_validations(self):
        """Test that helper functions use valid field values"""

        # Test create_volunteer_record specifically
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Helper",
                "last_name": "Function Test",
                "email": f"helper.function.{frappe.utils.random_string(5).lower()}@example.com",
                "application_status": "Pending"}
        )
        member.insert(ignore_permissions=True)
        self.add_cleanup("Member", member.name)

        # Test with volunteer interest
        member.interested_in_volunteering = 1

        from verenigingen.utils.application_helpers import create_volunteer_record

        volunteer = create_volunteer_record(member)

        if volunteer:
            self.add_cleanup("Volunteer", volunteer.name)

            # Check that all fields use valid values
            self.assertIn(
                volunteer.status,
                ["New", "Onboarding", "Active", "Inactive", "Retired"],
                "create_volunteer_record should use valid status values",
            )
            self.assertTrue(
                isinstance(volunteer.available, int) and volunteer.available in [0, 1],
                "available field should be 0 or 1",
            )
            self.assertEqual(volunteer.date_joined, today(), "date_joined should be today")

    def test_api_error_handling(self):
        """Test that API functions handle validation errors gracefully"""

        # Test with invalid membership type (should fail gracefully)
        invalid_data = {
            "first_name": "API",
            "last_name": "Error Test",
            "email": "api.error.test@example.com",
            "birth_date": "1990-01-01",
            "selected_membership_type": "INVALID_MEMBERSHIP_TYPE",
            "interested_in_volunteering": 1}

        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=invalid_data)

        # Should fail but not crash
        self.assertFalse(result.get("success"), "Invalid data should cause graceful failure")
        self.assertIn("error", result, "Error should be reported in response")
        self.assertIsInstance(result, dict, "Response should be a valid dict")


def run_validation_regression_tests():
    """Run validation regression test suite"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestValidationRegression)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


@frappe.whitelist()
def run_validation_regression_suite():
    """Whitelisted function to run validation regression tests"""
    try:
        result = run_validation_regression_tests()

        summary = {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped) if hasattr(result, "skipped") else 0}

        # Detailed failure/error info
        if result.failures:
            summary["failure_details"] = [
                {"test": str(test), "error": error} for test, error in result.failures
            ]

        if result.errors:
            summary["error_details"] = [{"test": str(test), "error": error} for test, error in result.errors]

        summary["message"] = (
            f"Validation regression tests: {summary['tests_run']} run, "
            f"{summary['failures']} failures, {summary['errors']} errors"
        )

        return summary

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Validation regression test execution failed: {str(e)}"}


if __name__ == "__main__":
    run_validation_regression_tests()
