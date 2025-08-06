import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestVolunteerPortalSecurity(FrappeTestCase):
    """Security-focused tests for the volunteer portal"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create minimal test data for security testing"""
        # Create test users
        cls.volunteer_email = "security.volunteer@test.com"
        cls.malicious_email = "malicious.user@test.com"
        cls.admin_email = "admin.user@test.com"

        for email, name in [
            (cls.volunteer_email, "Security Volunteer"),
            (cls.malicious_email, "Malicious User"),
            (cls.admin_email, "Admin User"),
        ]:
            if not frappe.db.exists("User", email):
                user = frappe.get_doc(
                    {
                        "doctype": "User",
                        "email": email,
                        "first_name": name.split()[0],
                        "last_name": name.split()[-1],
                        "full_name": name,
                        "enabled": 1}
                )
                user.insert()

        # Create test chapter
        cls.test_chapter = "Security Test Chapter"
        if not frappe.db.exists("Chapter", cls.test_chapter):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "chapter_name": cls.test_chapter,
                    "city": "Security City",
                    "enabled": 1}
            )
            chapter.insert()

        # Create legitimate volunteer
        cls.test_member = "SEC-MEMBER-001"
        if not frappe.db.exists("Member", cls.test_member):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": cls.test_member,
                    "first_name": "Security",
                    "last_name": "Verenigingen Volunteer",
                    "full_name": "Security Volunteer",
                    "email": cls.volunteer_email,
                    "status": "Active"}
            )
            member.insert()

        cls.test_volunteer = "SEC-VOL-001"
        if not frappe.db.exists("Volunteer", cls.test_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": cls.test_volunteer,
                    "volunteer_name": "Security Volunteer",
                    "member": cls.test_member,
                    "email": cls.volunteer_email,
                    "status": "Active"}
            )
            volunteer.insert()

        # Set up chapter membership
        chapter_doc = frappe.get_doc("Chapter", cls.test_chapter)
        member_exists = any(m.member == cls.test_member for m in chapter_doc.members)
        if not member_exists:
            chapter_doc.append(
                "members", {"member": cls.test_member, "chapter_join_date": today(), "enabled": 1}
            )
            chapter_doc.save()

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test"""
        frappe.set_user("Administrator")

    # AUTHENTICATION TESTS

    def test_guest_access_denied_dashboard(self):
        """Test that guest users cannot access volunteer dashboard"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user("Guest")

        with self.assertRaises(frappe.PermissionError) as cm:
            context = {}
            get_context(context)

        self.assertIn("Please login", str(cm.exception))

    def test_guest_access_denied_expenses(self):
        """Test that guest users cannot access expense portal"""
        from verenigingen.templates.pages.volunteer.expenses import get_context

        frappe.set_user("Guest")

        with self.assertRaises(frappe.PermissionError) as cm:
            context = {}
            get_context(context)

        self.assertIn("Please login", str(cm.exception))

    def test_non_volunteer_access_denied(self):
        """Test that users without volunteer records cannot access portal"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user(self.malicious_email)

        context = {}
        get_context(context)

        self.assertIn("error_message", context)
        self.assertIn("No volunteer record found", context["error_message"])

    # AUTHORIZATION TESTS

    def test_expense_access_control_by_volunteer(self):
        """Test that volunteers can only access their own expenses"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_details

        # Create expense for legitimate volunteer
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer,
                "description": "Legitimate expense",
                "amount": 50.00,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter}
        )
        expense.insert()
        expense.submit()

        try:
            # Legitimate volunteer can access their expense
            frappe.set_user(self.volunteer_email)
            details = get_expense_details(expense.name)
            self.assertEqual(details["volunteer"], self.test_volunteer)

            # Admin trying to access should fail (not their expense)
            frappe.set_user(self.admin_email)
            with self.assertRaises(frappe.PermissionError):
                get_expense_details(expense.name)

        finally:
            frappe.set_user("Administrator")
            frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_organization_access_control(self):
        """Test that volunteers can only submit expenses for authorized organizations"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create unauthorized chapter
        unauthorized_chapter = "Unauthorized Chapter"
        if not frappe.db.exists("Chapter", unauthorized_chapter):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "chapter_name": unauthorized_chapter,
                    "city": "Unauthorized City",
                    "enabled": 1}
            )
            chapter.insert()

        frappe.set_user(self.volunteer_email)

        # Try to submit expense for unauthorized chapter
        expense_data = {
            "description": "Unauthorized expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": unauthorized_chapter}

        result = submit_expense(expense_data)

        self.assertFalse(result["success"])
        # Should fail due to organization access validation

    # INPUT VALIDATION TESTS

    def test_sql_injection_prevention_description(self):
        """Test that SQL injection attempts in description are prevented"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        malicious_description = "'; DROP TABLE `tabVolunteer Expense`; --"

        expense_data = {
            "description": malicious_description,
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        # Should succeed but with escaped content
        self.assertTrue(result["success"])

        # Verify table still exists and data is properly escaped
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.description, malicious_description)  # Should be stored as-is, safely

        # Verify table still exists
        expenses_count = frappe.db.count("Volunteer Expense")
        self.assertGreater(expenses_count, 0)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_xss_prevention_in_notes(self):
        """Test that XSS attempts in notes are handled safely"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        xss_notes = "<script>alert('XSS Attack');</script>"

        expense_data = {
            "description": "XSS test expense",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter,
            "notes": xss_notes}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify data is stored but will be escaped when displayed
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.notes, xss_notes)  # Stored as-is, will be escaped on display

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_path_traversal_prevention(self):
        """Test that path traversal attempts are prevented"""
        from verenigingen.templates.pages.volunteer.expenses import get_organization_options

        frappe.set_user(self.volunteer_email)

        # Try path traversal in organization_type
        malicious_org_type = "../../../etc/passwd"

        options = get_organization_options(malicious_org_type, self.test_volunteer)

        # Should return empty list for invalid organization type
        self.assertEqual(options, [])

    def test_mass_assignment_prevention(self):
        """Test that mass assignment attacks are prevented"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # Try to set sensitive fields via mass assignment
        expense_data = {
            "description": "Mass assignment test",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter,
            # Malicious fields
            "status": "Approved",  # Try to bypass approval
            "approved_by": "Administrator",  # Try to set approver
            "approved_on": today(),  # Try to set approval date
            "docstatus": 1,  # Try to set document status
            "owner": "Administrator",  # Try to change owner
        }

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify malicious fields were not set
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.status, "Submitted")  # Should be default status
        self.assertIsNone(expense.approved_by)  # Should not be set
        self.assertIsNone(expense.approved_on)  # Should not be set
        self.assertEqual(expense.owner, self.volunteer_email)  # Should be current user

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    # DATA EXPOSURE TESTS

    def test_sensitive_data_not_exposed_in_context(self):
        """Test that sensitive data is not exposed in portal context"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user(self.volunteer_email)

        context = {}
        get_context(context)

        # Check that sensitive fields are not exposed
        volunteer_profile = context.get("volunteer_profile", {})

        # Should not expose internal system fields
        sensitive_fields = ["password", "api_key", "api_secret", "creation", "modified", "owner"]
        for field in sensitive_fields:
            self.assertNotIn(field, volunteer_profile)

    def test_other_volunteers_data_not_exposed(self):
        """Test that other volunteers' data is not exposed"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses

        # Create another volunteer's expense
        other_volunteer = "OTHER-VOL-001"
        if not frappe.db.exists("Volunteer", other_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": other_volunteer,
                    "volunteer_name": "Other Volunteer",
                    "status": "Active"}
            )
            volunteer.insert()

        other_expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": other_volunteer,
                "description": "Other volunteer expense",
                "amount": 100.00,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter}
        )
        other_expense.insert()
        other_expense.submit()

        try:
            frappe.set_user(self.volunteer_email)

            # Get current volunteer's expenses
            expenses = get_volunteer_expenses(self.test_volunteer)

            # Should not contain other volunteer's expenses
            for expense in expenses:
                self.assertEqual(expense["volunteer"], self.test_volunteer)

        finally:
            frappe.set_user("Administrator")
            frappe.delete_doc("Volunteer Expense", other_expense.name, force=1)
            frappe.delete_doc("Volunteer", other_volunteer, force=1)

    # RATE LIMITING TESTS

    def test_expense_submission_rate_limiting(self):
        """Test protection against rapid expense submissions"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        expenses = []
        success_count = 0

        try:
            # Try to submit many expenses rapidly
            for i in range(10):
                expense_data = {
                    "description": f"Rapid submission {i}",
                    "amount": 10.00,
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter}

                result = submit_expense(expense_data)
                if result["success"]:
                    success_count += 1
                    expenses.append(result["expense_name"])

            # All should succeed as we don't have rate limiting implemented yet
            # But this test documents the behavior and can be updated when rate limiting is added
            self.assertEqual(success_count, 10)

        finally:
            # Clean up
            for expense_name in expenses:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # SESSION SECURITY TESTS

    def test_session_fixation_prevention(self):
        """Test that session fixation attacks are prevented"""
        # This test verifies that Frappe's built-in session management is working
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        # Login as volunteer
        frappe.set_user(self.volunteer_email)
        original_session = frappe.session.sid

        context = {}
        get_context(context)

        # Session should remain consistent
        self.assertEqual(frappe.session.sid, original_session)

        # Verify user context is correct
        self.assertEqual(frappe.session.user, self.volunteer_email)

    def test_concurrent_session_handling(self):
        """Test handling of concurrent sessions"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # Simulate concurrent requests
        expense_data = {
            "description": "Concurrent session test",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        # Multiple submissions should work independently
        results = []
        for i in range(3):
            result = submit_expense(expense_data.copy())
            results.append(result)

        # All should succeed
        for result in results:
            self.assertTrue(result["success"])

        # Clean up
        for result in results:
            if result["success"]:
                try:
                    frappe.delete_doc("Volunteer Expense", result["expense_name"], force=1)
                except Exception:
                    pass

    # ERROR HANDLING TESTS

    def test_graceful_error_handling_invalid_volunteer(self):
        """Test graceful handling of invalid volunteer references"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

        # Test with non-existent volunteer
        organizations = get_volunteer_organizations("NON-EXISTENT-VOLUNTEER")

        # Should return empty organizations without crashing
        self.assertEqual(len(organizations["chapters"]), 0)
        self.assertEqual(len(organizations["teams"]), 0)

    def test_graceful_error_handling_database_issues(self):
        """Test graceful handling of database connectivity issues"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # Mock database error
        with patch("frappe.get_doc") as mock_get_doc:
            mock_get_doc.side_effect = Exception("Database connection error")

            expense_data = {
                "description": "DB error test",
                "amount": 50.00,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter}

            result = submit_expense(expense_data)

            # Should fail gracefully
            self.assertFalse(result["success"])
            self.assertIn("message", result)

    # AUDIT TRAIL TESTS

    def test_expense_creation_audit_trail(self):
        """Test that expense creation is properly audited"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "Audit trail test",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify audit information
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.owner, self.volunteer_email)
        self.assertIsNotNone(expense.creation)
        self.assertIsNotNone(expense.modified)
        self.assertEqual(expense.modified_by, self.volunteer_email)

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)


if __name__ == "__main__":
    unittest.main()
