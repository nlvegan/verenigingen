"""
Comprehensive tests for membership application submission edge cases and validation
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
import unittest


class TestApplicationSubmissionValidation(EnhancedTestCase):
    """Test application submission validation and edge cases"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed masters so submit_application (which creates Member -> Customer and
        # may run the creation_user-gated secure paths) succeeds in ISOLATION.
        # before_tests is unreliable for single-module runs in this v16 setup.
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        # EnhancedTestCase handles permissions automatically
        self.test_cleanup_records = []

        # The application form references a membership type by name. "Maandlid"
        # is a production fixture that does not exist on a fresh test site, so
        # the Link field validation fails. Create a real membership type here
        # and use its name in the submitted application data.
        from verenigingen.tests.backend.components.test_membership_utilities import (
            MembershipTestUtilities,
        )

        self.membership_type = MembershipTestUtilities.create_membership_type_with_dues_schedule(
            name="App Validation Monthly",
            period="Monthly",
            amount=10.0,
            test_case=self,
        )["membership_type"]
        self.membership_type_name = self.membership_type.name

    def tearDown(self):
        """Clean up test records"""
        try:
            for record_type, record_name in self.test_cleanup_records:
                if frappe.db.exists(record_type, record_name):
                    frappe.delete_doc(record_type, record_name, force=True)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
        super().tearDown()

    def add_cleanup_record(self, doctype, name):
        """Add record to cleanup list"""
        self.test_cleanup_records.append((doctype, name))

    def test_application_with_volunteer_interest_valid_status(self):
        """Test that applications with volunteer interest use valid volunteer status"""

        test_data = {
            "first_name": "Verenigingen Volunteer",
            "last_name": "Interest Test",
            "email": "volunteer.interest.test@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type_name,
            "interested_in_volunteering": 1,
            "payment_method": "Bank Transfer"}

        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=test_data)

        # Application should succeed
        self.assertTrue(
            result.get("success"), f"Application with volunteer interest should succeed: {result}"
        )

        if result.get("success"):
            member_record = (result.get("data") or {}).get("member_record") or result.get("member_record")
            self.add_cleanup_record("Member", member_record)

            # Check volunteer was created with correct status
            volunteers = frappe.get_all(
                "Volunteer", filters={"member": member_record}, fields=["name", "status", "volunteer_name"]
            )

            if volunteers:
                volunteer = volunteers[0]
                self.add_cleanup_record("Verenigingen Volunteer", volunteer["name"])
                self.assertEqual(volunteer["status"], "New", "Volunteer should be created with 'New' status")

            # Check member record
            member = frappe.get_doc("Member", member_record)
            if member.primary_address:
                self.add_cleanup_record("Address", member.primary_address)

    def test_volunteer_status_options_are_valid(self):
        """Test that all volunteer status options are properly defined"""

        volunteer_meta = frappe.get_meta("Volunteer")
        status_field = None

        for field in volunteer_meta.fields:
            if field.fieldname == "status":
                status_field = field
                break

        self.assertIsNotNone(status_field, "Volunteer doctype should have status field")
        self.assertTrue(status_field.options, "Volunteer status field should have options defined")

        valid_options = [opt.strip() for opt in status_field.options.split("\n") if opt.strip()]

        # Expected valid options
        expected_options = ["New", "Onboarding", "Active", "Inactive", "Retired"]

        for expected in expected_options:
            self.assertIn(expected, valid_options, f"'{expected}' should be a valid volunteer status option")

        # "Pending" should NOT be in the valid options
        self.assertNotIn("Pending", valid_options, "'Pending' should not be a valid volunteer status")

    def test_application_helper_create_volunteer_uses_valid_status(self):
        """Test that create_volunteer_record helper uses valid status"""

        # Create a test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Helper",
                "last_name": "Test Member",
                "email": "helper.test.member@example.com",
                "application_status": "Pending"}
        )
        member.insert()
        self.add_cleanup_record("Member", member.name)

        # Set volunteer interest
        member.interested_in_volunteering = 1

        # Test the helper function
        from verenigingen.utils.application_helpers import create_volunteer_record

        volunteer = create_volunteer_record(member)

        if volunteer:
            self.add_cleanup_record("Verenigingen Volunteer", volunteer.name)

            # Verify correct status is used
            self.assertEqual(volunteer.status, "New", "create_volunteer_record should use 'New' status")

            # Verify the volunteer is linked back to the member and carries the
            # member's display name. NOTE: the `email` field on Volunteer is the
            # *organization* email, intentionally NOT set at creation (assigned
            # later when a system account is provisioned), so it is expected to
            # be empty here. start_date defaults to member_since or today().
            self.assertEqual(volunteer.member, member.name)
            self.assertIn(member.first_name, volunteer.volunteer_name)
            self.assertTrue(volunteer.start_date, "Volunteer start_date should be set")

    def test_application_submission_edge_cases(self):
        """Test various edge cases in application submission"""

        # Test case 1: Application without volunteer interest
        test_data_no_volunteer = {
            "first_name": "No",
            "last_name": "Verenigingen Volunteer",
            "email": "no.volunteer.test@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type_name,
            "interested_in_volunteering": 0,  # No volunteer interest
            "payment_method": "Bank Transfer"}

        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=test_data_no_volunteer)
        self.assertTrue(result.get("success"), "Application without volunteer interest should succeed")

        if result.get("success"):
            member_record = (result.get("data") or {}).get("member_record") or result.get("member_record")
            self.add_cleanup_record("Member", member_record)

            # Should NOT create volunteer record
            volunteers = frappe.get_all("Volunteer", filters={"member": member_record})
            self.assertEqual(len(volunteers), 0, "No volunteer record should be created when not interested")

            member = frappe.get_doc("Member", member_record)
            if member.primary_address:
                self.add_cleanup_record("Address", member.primary_address)

        # Test case 2: Application with volunteer interest
        test_data_with_volunteer = {
            "first_name": "With",
            "last_name": "Verenigingen Volunteer",
            "email": "with.volunteer.test@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 456",
            "city": "Amsterdam",
            "postal_code": "1000BB",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type_name,
            "interested_in_volunteering": 1,  # With volunteer interest
            "payment_method": "Bank Transfer"}

        result = submit_application(data=test_data_with_volunteer)
        self.assertTrue(result.get("success"), "Application with volunteer interest should succeed")

        if result.get("success"):
            member_record = (result.get("data") or {}).get("member_record") or result.get("member_record")
            self.add_cleanup_record("Member", member_record)

            # SHOULD create volunteer record
            volunteers = frappe.get_all(
                "Volunteer", filters={"member": member_record}, fields=["name", "status"]
            )
            self.assertEqual(len(volunteers), 1, "Exactly one volunteer record should be created")
            self.assertEqual(volunteers[0]["status"], "New", "Volunteer should have 'New' status")
            self.add_cleanup_record("Verenigingen Volunteer", volunteers[0]["name"])

            member = frappe.get_doc("Member", member_record)
            if member.primary_address:
                self.add_cleanup_record("Address", member.primary_address)

    def test_application_validation_prevents_invalid_data(self):
        """Test that application validation catches invalid data before processing"""

        # Test invalid membership type
        invalid_data = {
            "first_name": "Invalid",
            "last_name": "Membership",
            "email": "invalid.membership@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "city": "Amsterdam",
            "postal_code": "1000AA",
            "country": "Netherlands",
            "selected_membership_type": "NonexistentMembershipType",
            "interested_in_volunteering": 0,
            "payment_method": "Bank Transfer"}

        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=invalid_data)
        self.assertFalse(result.get("success"), "Application with invalid membership type should fail")
        self.assertIn("error", result, "Error should be reported for invalid membership type")

    def test_special_character_handling_in_volunteer_creation(self):
        """Test that special characters in names are handled correctly in volunteer creation"""

        test_data = {
            "first_name": "José María",
            "last_name": "García-López",
            "email": "jose.maria.volunteer@example.com",
            "birth_date": "1990-01-01",
            "address_line1": "Calle de Test 123",
            "city": "Amsterdam",
            "postal_code": "1000CC",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type_name,
            "interested_in_volunteering": 1,
            "payment_method": "Bank Transfer"}

        from verenigingen.api.membership_application import submit_application

        result = submit_application(data=test_data)
        self.assertTrue(result.get("success"), "Application with special characters should succeed")

        if result.get("success"):
            member_record = (result.get("data") or {}).get("member_record") or result.get("member_record")
            self.add_cleanup_record("Member", member_record)

            # Check volunteer was created correctly
            volunteers = frappe.get_all(
                "Volunteer", filters={"member": member_record}, fields=["name", "volunteer_name", "status"]
            )

            if volunteers:
                volunteer = volunteers[0]
                self.add_cleanup_record("Verenigingen Volunteer", volunteer["name"])

                # Verify volunteer was created with correct status and name handling
                self.assertEqual(volunteer["status"], "New")
                self.assertIn("José María", volunteer["volunteer_name"])
                self.assertIn("García-López", volunteer["volunteer_name"])

                # Get the full volunteer doc to verify member linkage. The
                # `email` field is the organization email (assigned later, not
                # at creation), so it is intentionally empty here — do not
                # assert it equals the applicant's personal email.
                volunteer_doc = frappe.get_doc("Volunteer", volunteer["name"])
                self.assertEqual(volunteer_doc.member, member_record)

            member = frappe.get_doc("Member", member_record)
            if member.primary_address:
                self.add_cleanup_record("Address", member.primary_address)


def run_application_validation_tests():
    """Run all application validation tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestApplicationSubmissionValidation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def run_application_submission_tests():
    """Whitelisted function to run application submission validation tests"""
    try:
        result = run_application_validation_tests()

        return {
            "success": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "failure_details": [f"{test}: {error}" for test, error in result.failures],
            "error_details": [f"{test}: {error}" for test, error in result.errors],
            "message": f"Application validation tests completed: {result.testsRun} tests, {len(result.failures)} failures, {len(result.errors)} errors"}
    except Exception as e:
        return {"success": False, "error": str(e), "message": f"Test execution failed: {str(e)}"}


if __name__ == "__main__":
    run_application_validation_tests()
