#!/usr/bin/env python3

import json
import unittest

import frappe
from frappe.utils import add_days, flt, today


class TestVolunteerExpensePortal(unittest.TestCase):
    """Comprehensive tests for volunteer expense portal functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.test_company = frappe.get_doc(
            {"doctype": "Company", "company_name": "Test Company", "default_currency": "EUR"}
        ).insert(ignore_if_duplicate=True)

        cls.test_user = "test.volunteer@example.com"
        cls.test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Test Volunteer",
                "email": cls.test_user,
                "status": "Active"}
        ).insert(ignore_if_duplicate=True)

        cls.test_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Test Category",
                "description": "Test category for unit tests",
                "is_active": 1}
        ).insert(ignore_if_duplicate=True)

        cls.test_chapter = frappe.get_doc({"doctype": "Chapter", "chapter_name": "Test Chapter"}).insert(
            ignore_if_duplicate=True
        )

        cls.test_team = frappe.get_doc({"doctype": "Team", "team_name": "Test Team"}).insert(
            ignore_if_duplicate=True
        )

    def setUp(self):
        """Set up for each test"""
        frappe.set_user(self.test_user)
        frappe.db.rollback()

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()
        frappe.set_user("Administrator")

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        frappe.set_user("Administrator")
        # Clean up test documents
        test_docs = [
            ("Volunteer Expense", {"volunteer": cls.test_volunteer.name}),
            ("Volunteer", {"name": cls.test_volunteer.name}),
            ("Expense Category", {"name": cls.test_category.name}),
            ("Chapter", {"name": cls.test_chapter.name}),
            ("Team", {"name": cls.test_team.name}),
            ("Company", {"name": cls.test_company.name}),
        ]

        for doctype, filters in test_docs:
            try:
                docs = frappe.get_all(doctype, filters=filters)
                for doc in docs:
                    frappe.delete_doc(doctype, doc.name, force=True)
            except Exception:
                pass

    def test_submit_expense_success(self):
        """Test successful expense submission"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense",
            "amount": "50.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "notes": "Test notes"}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Expense submitted successfully")
        self.assertIn("expense_name", result)

        # Verify expense was created
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.volunteer, self.test_volunteer.name)
        self.assertEqual(expense.description, "Test expense")
        self.assertEqual(flt(expense.amount), 50.00)
        self.assertEqual(expense.status, "Submitted")

    def test_submit_expense_with_json_string(self):
        """Test expense submission with JSON string input"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = json.dumps(
            {
                "description": "Test expense JSON",
                "amount": "75.50",
                "expense_date": today(),
                "category": self.test_category.name,
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name}
        )

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(flt(expense.amount), 75.50)

    def test_submit_expense_missing_required_fields(self):
        """Test expense submission with missing required fields"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test missing description
        expense_data = {
            "amount": "50.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name}

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("description", result["message"])

    def test_submit_expense_invalid_organization_type(self):
        """Test expense submission with invalid organization selection"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test Chapter organization type without chapter selection
        expense_data = {
            "description": "Test expense",
            "amount": "50.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter"
            # Missing chapter field
        }

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("chapter", result["message"])

    def test_submit_expense_with_receipt(self):
        """Test expense submission with receipt attachment"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test expense with receipt",
            "amount": "100.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name,
            "receipt_attachment": "/files/test_receipt.pdf"}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.receipt_attachment, "/files/test_receipt.pdf")

    def test_expense_naming_pattern(self):
        """Test that expense names follow correct pattern"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test naming",
            "amount": "25.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name}

        result = submit_expense(expense_data)
        expense_name = result["expense_name"]

        # Should follow pattern VE-YYYY-MM-NNNNN
        import re

        pattern = r"^VE-\d{4}-\d{2}-\d{5}$"
        self.assertTrue(
            re.match(pattern, expense_name), f"Expense name '{expense_name}' doesn't match expected pattern"
        )

    def test_volunteer_access_validation(self):
        """Test volunteer access validation"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Test with valid volunteer user
        frappe.set_user(self.test_user)
        volunteer = get_user_volunteer_record()
        self.assertIsNotNone(volunteer)
        self.assertEqual(volunteer.name, self.test_volunteer.name)

        # Test with non-volunteer user
        frappe.set_user("Administrator")
        volunteer = get_user_volunteer_record()
        self.assertIsNone(volunteer)

    def test_get_expense_categories(self):
        """Test getting expense categories"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_categories

        categories = get_expense_categories()
        self.assertIsInstance(categories, list)

        # Should include our test category
        category_names = [cat.name for cat in categories]
        self.assertIn(self.test_category.name, category_names)

    def test_get_volunteer_expenses(self):
        """Test getting volunteer's expenses"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses, submit_expense

        # Create a test expense first
        expense_data = {
            "description": "Test for listing",
            "amount": "30.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name}
        submit_expense(expense_data)

        # Get expenses for volunteer
        expenses = get_volunteer_expenses(self.test_volunteer.name)
        self.assertIsInstance(expenses, list)
        self.assertGreater(len(expenses), 0)

        # Check expense data structure
        expense = expenses[0]
        self.assertIn("description", expense)
        self.assertIn("amount", expense)
        self.assertIn("status", expense)
        self.assertIn("category_name", expense)

    def test_expense_statistics(self):
        """Test expense statistics calculation"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics, submit_expense

        # Create test expenses with different statuses
        for i, status in enumerate(["Submitted", "Approved", "Submitted"]):
            expense_data = {
                "description": f"Test expense {i}",
                "amount": f"{(i + 1) * 10}.00",
                "expense_date": today(),
                "category": self.test_category.name,
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name}
            result = submit_expense(expense_data)

            # Update status for testing
            if status != "Submitted":
                expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
                expense.db_set("status", status)

        stats = get_expense_statistics(self.test_volunteer.name)

        self.assertIn("total_submitted", stats)
        self.assertIn("total_approved", stats)
        self.assertIn("pending_count", stats)
        self.assertIn("approved_count", stats)
        self.assertGreater(stats["total_submitted"], 0)

    def test_expense_validation_edge_cases(self):
        """Test expense validation edge cases"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test future date
        future_date = add_days(today(), 1)
        expense_data = {
            "description": "Future expense",
            "amount": "50.00",
            "expense_date": future_date,
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name}

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("future", result["message"])

        # Test zero amount
        expense_data["expense_date"] = today()
        expense_data["amount"] = "0.00"

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("greater than zero", result["message"])

        # Test negative amount
        expense_data["amount"] = "-10.00"

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("greater than zero", result["message"])

    def test_company_default_setting(self):
        """Test automatic company setting"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Test company setting",
            "amount": "40.00",
            "expense_date": today(),
            "category": self.test_category.name,
            "organization_type": "Chapter",
            "chapter": self.test_chapter.name}

        result = submit_expense(expense_data)
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])

        # Should have company set automatically
        self.assertIsNotNone(expense.company)

    def test_expense_portal_context(self):
        """Test expense portal context generation"""
        from verenigingen.templates.pages.volunteer.expenses import get_context

        frappe.set_user(self.test_user)
        context = {}
        result_context = get_context(context)

        self.assertIn("volunteer", result_context)
        self.assertIn("expense_categories", result_context)
        self.assertIn("recent_expenses", result_context)
        self.assertIn("expense_stats", result_context)
        self.assertEqual(result_context["volunteer"].name, self.test_volunteer.name)

    def test_error_handling(self):
        """Test error handling in various scenarios"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test with malformed JSON
        malformed_json = '{"description": "test", "amount": invalid}'
        result = submit_expense(malformed_json)
        self.assertFalse(result["success"])

        # Test with None input
        result = submit_expense(None)
        self.assertFalse(result["success"])

        # Test with empty dict
        result = submit_expense({})
        self.assertFalse(result["success"])


class TestVolunteerExpenseNaming(unittest.TestCase):
    """Test naming functionality specifically"""

    def test_naming_series_format(self):
        """Test naming series format is correct"""

        # Check doctype configuration
        meta = frappe.get_meta("Volunteer Expense")
        self.assertEqual(meta.naming_rule, "Expression (Old Style)")
        self.assertEqual(meta.autoname, "format:VE-{YYYY}-{MM}-{#####}")

    def test_sequential_naming(self):
        """Test that names are sequential"""
        # This would require creating actual documents
        # Implementation depends on test data setup


class TestVolunteerExpensePermissions(unittest.TestCase):
    """Test permission validation"""

    def test_volunteer_organization_access(self):
        """Test volunteer organization access validation"""
        # This would test the validate_volunteer_organization_access method
        # Implementation depends on test data setup with members/chapters


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    unittest.main()
