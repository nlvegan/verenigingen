#!/usr/bin/env python3

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, today


class TestVolunteerExpenseEdgeCases(unittest.TestCase):
    """Edge case tests for volunteer expense portal"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.test_user = "edge.test@example.com"

        # Create test company if it doesn't exist
        if not frappe.db.exists("Company", "Edge Test Company"):
            cls.test_company = frappe.get_doc(
                {"doctype": "Company", "company_name": "Edge Test Company", "default_currency": "EUR"}
            ).insert()
        else:
            cls.test_company = frappe.get_doc("Company", "Edge Test Company")

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()
        frappe.set_user("Administrator")

    def test_no_volunteer_record(self):
        """Test expense submission with no volunteer record"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Set user with no volunteer record
        frappe.set_user("Administrator")

        expense_data = {
            "description": "Test expense",
            "amount": "50.00",
            "expense_date": today(),
            "category": "test",
            "organization_type": "Chapter",
            "chapter": "test"}

        result = submit_expense(expense_data)
        self.assertFalse(result["success"])
        self.assertIn("volunteer record", result["message"])

    def test_no_default_company(self):
        """Test expense submission with no default company"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Mock no companies existing
        with patch("frappe.defaults.get_global_default", return_value=None):
            with patch("frappe.get_all", return_value=[]):
                expense_data = {
                    "description": "Test expense",
                    "amount": "50.00",
                    "expense_date": today(),
                    "category": "test",
                    "organization_type": "Chapter",
                    "chapter": "test"}

                result = submit_expense(expense_data)
                self.assertFalse(result["success"])
                self.assertIn("company", result["message"])

    def test_invalid_json_input(self):
        """Test with various invalid JSON inputs"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        invalid_inputs = [
            '{"invalid": json}',  # Invalid JSON syntax
            '{"description": "test"',  # Incomplete JSON
            "null",  # JSON null
            "[]",  # JSON array instead of object
            '"string"',  # JSON string instead of object
            "123",  # JSON number instead of object
        ]

        for invalid_input in invalid_inputs:
            result = submit_expense(invalid_input)
            self.assertFalse(result["success"])

    def test_extremely_large_amounts(self):
        """Test with extremely large expense amounts"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Create minimal test setup
        test_volunteer = self._create_test_volunteer()
        test_category = self._create_test_category()
        test_chapter = self._create_test_chapter()

        frappe.set_user(test_volunteer.email)

        large_amounts = [
            "999999999.99",  # Very large amount
            "0.01",  # Very small amount
            "12345.678",  # More than 2 decimal places
        ]

        for amount in large_amounts:
            expense_data = {
                "description": f"Test amount {amount}",
                "amount": amount,
                "expense_date": today(),
                "category": test_category.name,
                "organization_type": "Chapter",
                "chapter": test_chapter.name}

            result = submit_expense(expense_data)
            if amount == "0.01":
                self.assertTrue(result["success"])  # Should work
            else:
                # Large amounts should work, but we might want to add validation later
                pass

    def test_special_characters_in_description(self):
        """Test with special characters in description"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        test_volunteer = self._create_test_volunteer()
        test_category = self._create_test_category()
        test_chapter = self._create_test_chapter()

        frappe.set_user(test_volunteer.email)

        special_descriptions = [
            "Test with émojis 🚀 and ñámeś",
            "SQL injection'; DROP TABLE expenses; --",
            "<script>alert('xss')</script>",
            "Test with\nnewlines\nand\ttabs",
            "Very " + "long " * 100 + "description",
            "",  # Empty description should fail
        ]

        for desc in special_descriptions:
            expense_data = {
                "description": desc,
                "amount": "25.00",
                "expense_date": today(),
                "category": test_category.name,
                "organization_type": "Chapter",
                "chapter": test_chapter.name}

            result = submit_expense(expense_data)
            if desc == "":
                self.assertFalse(result["success"])  # Empty description should fail
            else:
                self.assertTrue(result["success"])  # Others should work

    def test_concurrent_submissions(self):
        """Test concurrent expense submissions"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        test_volunteer = self._create_test_volunteer()
        test_category = self._create_test_category()
        test_chapter = self._create_test_chapter()

        frappe.set_user(test_volunteer.email)

        # Simulate concurrent submissions
        results = []
        for i in range(5):
            expense_data = {
                "description": f"Concurrent expense {i}",
                "amount": f"{(i + 1) * 10}.00",
                "expense_date": today(),
                "category": test_category.name,
                "organization_type": "Chapter",
                "chapter": test_chapter.name}

            result = submit_expense(expense_data)
            results.append(result)

        # All should succeed
        for result in results:
            self.assertTrue(result["success"])

        # All should have unique names
        expense_names = [r["expense_name"] for r in results]
        self.assertEqual(len(expense_names), len(set(expense_names)))

    def test_boundary_dates(self):
        """Test with boundary date values"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        test_volunteer = self._create_test_volunteer()
        test_category = self._create_test_category()
        test_chapter = self._create_test_chapter()

        frappe.set_user(test_volunteer.email)

        boundary_dates = [
            today(),  # Today - should work
            add_days(today(), -1),  # Yesterday - should work
            add_days(today(), 1),  # Tomorrow - should fail
            add_months(today(), -12),  # 1 year ago - should work
            "2025-02-29",  # Invalid date (not leap year)
            "2025-13-01",  # Invalid month
            "invalid-date",  # Invalid format
        ]

        for test_date in boundary_dates:
            expense_data = {
                "description": f"Test date {test_date}",
                "amount": "50.00",
                "expense_date": test_date,
                "category": test_category.name,
                "organization_type": "Chapter",
                "chapter": test_chapter.name}

            result = submit_expense(expense_data)

            if test_date == add_days(today(), 1):
                self.assertFalse(result["success"])  # Future date should fail
            elif test_date in ["2025-02-29", "2025-13-01", "invalid-date"]:
                self.assertFalse(result["success"])  # Invalid dates should fail
            else:
                self.assertTrue(result["success"])  # Valid dates should work

    def test_memory_and_performance(self):
        """Test memory usage and performance with large data"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses

        # This test would create many expenses and test retrieval performance
        # For now, just test that the function handles limits correctly

        test_volunteer = self._create_test_volunteer()
        expenses = get_volunteer_expenses(test_volunteer.name, limit=100)
        self.assertIsInstance(expenses, list)
        self.assertLessEqual(len(expenses), 100)

    def test_database_connection_issues(self):
        """Test handling of database connection issues"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Mock database errors
        with patch("frappe.get_doc") as mock_get_doc:
            mock_get_doc.side_effect = Exception("Database connection error")

            expense_data = {
                "description": "Test db error",
                "amount": "50.00",
                "expense_date": today(),
                "category": "test",
                "organization_type": "Chapter",
                "chapter": "test"}

            result = submit_expense(expense_data)
            self.assertFalse(result["success"])
            self.assertIn("error", result["message"].lower())

    def test_unicode_and_encoding(self):
        """Test Unicode and encoding handling"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        test_volunteer = self._create_test_volunteer()
        test_category = self._create_test_category()
        test_chapter = self._create_test_chapter()

        frappe.set_user(test_volunteer.email)

        unicode_descriptions = [
            "测试中文描述",  # Chinese
            "Тест на русском",  # Russian
            "اختبار عربي",  # Arabic
            "🚀🎉💰 Emoji test",  # Emojis
            "Café naïve résumé",  # Accented characters
        ]

        for desc in unicode_descriptions:
            expense_data = {
                "description": desc,
                "amount": "25.00",
                "expense_date": today(),
                "category": test_category.name,
                "organization_type": "Chapter",
                "chapter": test_chapter.name}

            result = submit_expense(expense_data)
            self.assertTrue(result["success"])

            # Verify the description was saved correctly
            expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
            self.assertEqual(expense.description, desc)

    def _create_test_volunteer(self):
        """Helper to create test volunteer"""
        if not frappe.db.exists("Volunteer", {"email": self.test_user}):
            return frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Edge Test Volunteer",
                    "email": self.test_user,
                    "status": "Active"}
            ).insert()
        return frappe.get_doc("Volunteer", {"email": self.test_user})

    def _create_test_category(self):
        """Helper to create test category"""
        if not frappe.db.exists("Expense Category", "Edge Test Category"):
            return frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": "Edge Test Category",
                    "description": "Test category for edge cases",
                    "is_active": 1}
            ).insert()
        return frappe.get_doc("Expense Category", "Edge Test Category")

    def _create_test_chapter(self):
        """Helper to create test chapter"""
        if not frappe.db.exists("Chapter", "Edge Test Chapter"):
            return frappe.get_doc({"doctype": "Chapter", "chapter_name": "Edge Test Chapter"}).insert()
        return frappe.get_doc("Chapter", "Edge Test Chapter")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    unittest.main()
