#!/usr/bin/env python3

"""
Comprehensive unit tests for termination system covering all issues encountered
"""

import unittest

import frappe
from frappe.utils import today


class TestTerminationSystemComprehensive(unittest.TestCase):
    """Comprehensive tests for the termination system enhancements"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        frappe.set_user("Administrator")

        # Create test member
        cls.test_member_name = "TEST-MEMBER-TERMINATION-001"
        cls.test_user_email = "test_termination@example.com"

        # Clean up any existing test data
        cls.cleanup_test_data()

        # Create test member
        cls.create_test_member()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        cls.cleanup_test_data()

    @classmethod
    def cleanup_test_data(cls):
        """Clean up test data"""
        for doctype in ["Member", "User", "Employee", "Volunteer", "Membership Termination Request"]:
            try:
                if doctype == "Member":
                    if frappe.db.exists("Member", cls.test_member_name):
                        frappe.delete_doc("Member", cls.test_member_name, force=True)
                elif doctype == "User":
                    if frappe.db.exists("User", cls.test_user_email):
                        frappe.delete_doc("User", cls.test_user_email, force=True)
                elif doctype == "Employee":
                    employees = frappe.get_all("Employee", filters={"user_id": cls.test_user_email})
                    for emp in employees:
                        frappe.delete_doc("Employee", emp.name, force=True)
                elif doctype == "Volunteer":
                    volunteers = frappe.get_all("Volunteer", filters={"member": cls.test_member_name})
                    for vol in volunteers:
                        frappe.delete_doc("Volunteer", vol.name, force=True)
                elif doctype == "Membership Termination Request":
                    requests = frappe.get_all(
                        "Membership Termination Request", filters={"member": cls.test_member_name}
                    )
                    for req in requests:
                        frappe.delete_doc("Membership Termination Request", req.name, force=True)
            except Exception:
                pass

        frappe.db.commit()

    @classmethod
    def create_test_member(cls):
        """Create test member with user and employee records"""

        # Create user
        user_doc = frappe.new_doc("User")
        user_doc.email = cls.test_user_email
        user_doc.first_name = "Test"
        user_doc.last_name = "Termination"
        user_doc.enabled = 1
        user_doc.insert(ignore_permissions=True)

        # Create member
        member_doc = frappe.new_doc("Member")
        member_doc.name = cls.test_member_name
        member_doc.full_name = "Test Termination User"
        member_doc.user = cls.test_user_email
        member_doc.status = "Active"
        member_doc.insert(ignore_permissions=True)

        # Create employee with different field configurations for testing
        employee_doc = frappe.new_doc("Employee")
        employee_doc.employee_name = "Test Termination Employee"
        employee_doc.user_id = cls.test_user_email  # Primary linking method
        employee_doc.personal_email = cls.test_user_email  # Alternative linking method
        employee_doc.status = "Active"
        employee_doc.insert(ignore_permissions=True)

        # Create volunteer
        volunteer_doc = frappe.new_doc("Volunteer")
        volunteer_doc.volunteer_name = "Test Termination Volunteer"
        volunteer_doc.member = cls.test_member_name
        volunteer_doc.status = "Active"
        volunteer_doc.insert(ignore_permissions=True)

        frappe.db.commit()

        cls.test_employee_id = employee_doc.name
        cls.test_volunteer_id = volunteer_doc.name

    def test_member_status_override_protection(self):
        """Test that termination statuses are protected from application status override"""

        member = frappe.get_doc("Member", self.test_member_name)

        # Test each termination status
        termination_statuses = ["Deceased", "Banned", "Suspended", "Terminated", "Expired"]

        for status in termination_statuses:
            # Set member to termination status
            member.status = status
            member.application_status = "Rejected"  # This would normally override

            # Save and check status is preserved
            member.save(ignore_permissions=True)

            # Reload and verify
            member.reload()
            self.assertEqual(
                member.status,
                status,
                f"Member status {status} should not be overridden by application_status",
            )

    def test_enhanced_employee_detection_user_id(self):
        """Test employee detection via user_id field"""

        from verenigingen.utils.termination_utils import validate_termination_readiness

        impact_data = validate_termination_readiness(self.test_member_name)

        self.assertIsNotNone(impact_data)
        self.assertIn("impact", impact_data)

        # Should detect at least 1 employee record
        employee_count = impact_data["impact"].get("employee_records", 0)
        self.assertGreater(employee_count, 0, "Should detect employee via user_id field")

    def test_enhanced_employee_detection_alternative_fields(self):
        """Test employee detection via alternative email fields"""

        # Create employee with only personal_email (no user_id)
        alt_employee = frappe.new_doc("Employee")
        alt_employee.employee_name = "Alternative Email Employee"
        alt_employee.personal_email = self.test_user_email
        alt_employee.status = "Active"
        # Deliberately not setting user_id
        alt_employee.insert(ignore_permissions=True)

        try:
            from verenigingen.utils.termination_utils import validate_termination_readiness

            impact_data = validate_termination_readiness(self.test_member_name)

            # Should still detect employees
            employee_count = impact_data["impact"].get("employee_records", 0)
            self.assertGreater(employee_count, 0, "Should detect employee via alternative email fields")

        finally:
            # Cleanup
            frappe.delete_doc("Employee", alt_employee.name, force=True)
            frappe.db.commit()

    def test_volunteer_record_detection(self):
        """Test volunteer record detection"""

        from verenigingen.utils.termination_utils import validate_termination_readiness

        impact_data = validate_termination_readiness(self.test_member_name)

        volunteer_count = impact_data["impact"].get("volunteer_records", 0)
        self.assertGreater(volunteer_count, 0, "Should detect volunteer records")

    def test_user_account_detection(self):
        """Test user account detection"""

        from verenigingen.utils.termination_utils import validate_termination_readiness

        impact_data = validate_termination_readiness(self.test_member_name)

        user_detected = impact_data["impact"].get("user_account", False)
        self.assertTrue(user_detected, "Should detect user account")

    def test_termination_integration_employee_handling(self):
        """Test employee termination integration"""

        from verenigingen.utils.termination_integration import terminate_employee_records_safe

        results = terminate_employee_records_safe(
            self.test_member_name, "Voluntary", today(), "Test termination"
        )

        self.assertGreater(results["employees_terminated"], 0, "Should terminate employee records")
        self.assertGreater(len(results["actions_taken"]), 0, "Should record actions taken")

        # Verify employee status was updated
        employee = frappe.get_doc("Employee", self.test_employee_id)
        self.assertEqual(employee.status, "Left", "Employee status should be updated to 'Left'")

    def test_termination_integration_volunteer_handling(self):
        """Test volunteer termination integration"""

        from verenigingen.utils.termination_integration import terminate_volunteer_records_safe

        results = terminate_volunteer_records_safe(
            self.test_member_name, "Voluntary", today(), "Test termination"
        )

        self.assertGreater(results["volunteers_terminated"], 0, "Should terminate volunteer records")
        self.assertGreater(len(results["actions_taken"]), 0, "Should record actions taken")

        # Verify volunteer status was updated
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer_id)
        self.assertEqual(volunteer.status, "Inactive", "Volunteer status should be updated to 'Inactive'")

    def test_termination_status_mapping(self):
        """Test correct status mapping for different termination types"""

        from verenigingen.utils.termination_integration import update_member_status_safe

        test_cases = [
            ("Voluntary", "Expired"),
            ("Non-payment", "Suspended"),
            ("Deceased", "Deceased"),
            ("Policy Violation", "Suspended"),
            ("Disciplinary Action", "Suspended"),
            ("Expulsion", "Banned"),
        ]

        for termination_type, expected_status in test_cases:
            with self.subTest(termination_type=termination_type):
                # Reset member status
                member = frappe.get_doc("Member", self.test_member_name)
                member.status = "Active"
                member.save(ignore_permissions=True)

                # Apply termination
                success = update_member_status_safe(
                    self.test_member_name, termination_type, today(), "TEST-REQ-001"
                )

                self.assertTrue(success, f"Should successfully update status for {termination_type}")

                # Verify status mapping
                member.reload()
                self.assertEqual(
                    member.status,
                    expected_status,
                    f"Status should be {expected_status} for {termination_type}",
                )

    def test_termination_request_doctype_fields(self):
        """Test that termination request doctype has required tracking fields"""

        # Get doctype meta
        meta = frappe.get_meta("Membership Termination Request")

        required_fields = ["volunteers_terminated", "volunteer_expenses_cancelled", "employees_terminated"]

        for field_name in required_fields:
            field = meta.get_field(field_name)
            self.assertIsNotNone(field, f"Field {field_name} should exist in doctype")
            self.assertEqual(field.fieldtype, "Int", f"Field {field_name} should be Integer type")

    def test_javascript_termination_types_completeness(self):
        """Test that JavaScript termination types match doctype options"""

        # Read JavaScript file
        js_file_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/js/member/js_modules/termination-utils.js"

        try:
            with open(js_file_path, "r") as f:
                js_content = f.read()

            # Check for required termination types
            required_types = [
                "Voluntary",
                "Non-payment",
                "Deceased",
                "Policy Violation",
                "Disciplinary Action",
                "Expulsion",
            ]

            for term_type in required_types:
                self.assertIn(
                    term_type, js_content, f"JavaScript should include termination type: {term_type}"
                )

        except FileNotFoundError:
            self.fail("JavaScript termination utils file not found")

    def test_impact_preview_api(self):
        """Test the termination impact preview API"""

        from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
            get_termination_impact_preview,
        )

        impact_data = get_termination_impact_preview(self.test_member_name)

        self.assertIsInstance(impact_data, dict, "Should return dictionary")

        # Check required fields exist
        required_fields = [
            "employee_records",
            "volunteer_records",
            "user_account",
            "pending_volunteer_expenses",
        ]

        for field in required_fields:
            self.assertIn(field, impact_data, f"Impact data should include {field}")

    def test_termination_workflow_end_to_end(self):
        """Test complete termination workflow"""

        # Create termination request
        termination_req = frappe.new_doc("Membership Termination Request")
        termination_req.member = self.test_member_name
        termination_req.termination_type = "Voluntary"
        termination_req.termination_reason = "End-to-end test"
        termination_req.insert(ignore_permissions=True)

        try:
            # Submit for approval
            termination_req.submit_for_approval()
            self.assertEqual(termination_req.status, "Approved", "Simple termination should be auto-approved")

            # Execute termination
            termination_req.status = "Executed"
            termination_req.execute_termination_internal()

            # Verify tracking fields were updated
            termination_req.reload()
            self.assertGreater(termination_req.employees_terminated, 0, "Should track employee terminations")
            self.assertGreater(
                termination_req.volunteers_terminated, 0, "Should track volunteer terminations"
            )

        finally:
            # Cleanup
            frappe.delete_doc("Membership Termination Request", termination_req.name, force=True)
            frappe.db.commit()

    def test_error_handling_missing_member(self):
        """Test error handling for missing member"""

        from verenigingen.utils.termination_utils import validate_termination_readiness

        result = validate_termination_readiness("NON-EXISTENT-MEMBER")

        # Should handle gracefully without crashing
        self.assertIsNotNone(result)

    def test_error_handling_missing_user(self):
        """Test error handling for member without user"""

        # Create member without user
        memberless_user = frappe.new_doc("Member")
        memberless_user.name = "TEST-NO-USER-001"
        memberless_user.full_name = "Member Without User"
        memberless_user.status = "Active"
        # Deliberately not setting user field
        memberless_user.insert(ignore_permissions=True)

        try:
            from verenigingen.utils.termination_utils import validate_termination_readiness

            result = validate_termination_readiness("TEST-NO-USER-001")

            # Should handle gracefully
            self.assertIsNotNone(result)
            self.assertEqual(result["impact"]["user_account"], False, "Should detect no user account")
            self.assertEqual(result["impact"]["employee_records"], 0, "Should detect no employee records")

        finally:
            frappe.delete_doc("Member", "TEST-NO-USER-001", force=True)
            frappe.db.commit()

    def test_duplicate_employee_handling(self):
        """Test handling of duplicate employee records"""

        # Create second employee with same user_id
        duplicate_employee = frappe.new_doc("Employee")
        duplicate_employee.employee_name = "Duplicate Employee"
        duplicate_employee.user_id = self.test_user_email
        duplicate_employee.status = "Active"
        duplicate_employee.insert(ignore_permissions=True)

        try:
            from verenigingen.utils.termination_integration import terminate_employee_records_safe

            results = terminate_employee_records_safe(
                self.test_member_name, "Voluntary", today(), "Test duplicate handling"
            )

            # Should handle both employees
            self.assertGreaterEqual(
                results["employees_terminated"], 2, "Should handle multiple employee records"
            )

        finally:
            frappe.delete_doc("Employee", duplicate_employee.name, force=True)
            frappe.db.commit()


def run_comprehensive_termination_tests():
    """Run all comprehensive termination tests"""

    print("🧪 Running Comprehensive Termination System Tests...")
    print("=" * 60)

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTerminationSystemComprehensive)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(
        f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%"
    )

    if result.failures:
        print("\n❌ FAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}")

    if result.errors:
        print("\n💥 ERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}")

    if result.wasSuccessful():
        print("\n✅ All tests passed!")
    else:
        print("\n❌ Some tests failed - see details above")

    return result.wasSuccessful()


if __name__ == "__main__":
    frappe.init()
    run_comprehensive_termination_tests()
