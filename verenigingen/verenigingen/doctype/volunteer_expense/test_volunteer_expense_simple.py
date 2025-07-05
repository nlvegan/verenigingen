import unittest

import frappe


class TestVolunteerExpenseSimple(unittest.TestCase):
    def test_basic_doctype_creation(self):
        """Test that the Volunteer Expense doctype exists and can be instantiated"""
        # Just test that we can create the doc object
        expense = frappe.get_doc({"doctype": "Volunteer Expense"})
        self.assertEqual(expense.doctype, "Volunteer Expense")

        # Test that required fields are defined
        meta = frappe.get_meta("Volunteer Expense")
        [field.fieldname for field in meta.fields if field.reqd]

        expected_required_fields = [
            "volunteer",
            "expense_date",
            "category",
            "description",
            "amount",
            "organization_type",
            "company",
        ]

        for field in expected_required_fields:
            self.assertIn(
                field, [f.fieldname for f in meta.fields], f"Field {field} should exist in Volunteer Expense"
            )

    def test_expense_category_doctype_creation(self):
        """Test that the Expense Category doctype exists and can be instantiated"""
        category = frappe.get_doc({"doctype": "Expense Category"})
        self.assertEqual(category.doctype, "Expense Category")

        # Test that required fields are defined
        meta = frappe.get_meta("Expense Category")
        [field.fieldname for field in meta.fields if field.reqd]

        expected_required_fields = ["category_name", "expense_account"]

        for field in expected_required_fields:
            self.assertIn(
                field, [f.fieldname for f in meta.fields], f"Field {field} should exist in Expense Category"
            )
