# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEBoekhoudenAccountMapping(FrappeTestCase):
    def setUp(self):
        # Clean up any existing test mappings
        frappe.db.delete("E-Boekhouden Account Mapping", {"account_name": ["like", "Test%"]})

    def tearDown(self):
        # Clean up test mappings
        frappe.db.delete("E-Boekhouden Account Mapping", {"account_name": ["like", "Test%"]})

    def test_specific_account_mapping(self):
        """Test mapping with specific account code"""
        mapping = frappe.new_doc("E-Boekhouden Account Mapping")
        mapping.account_code = "40001"
        mapping.account_name = "Test Wages Account"
        mapping.document_type = "Journal Entry"
        mapping.transaction_category = "Wages and Salaries"
        mapping.insert()

        # Test matching
        self.assertTrue(mapping.matches_account("40001"))
        self.assertFalse(mapping.matches_account("40002"))
        self.assertFalse(mapping.matches_account(None))

    def test_account_range_mapping(self):
        """Test mapping with account range"""
        mapping = frappe.new_doc("E-Boekhouden Account Mapping")
        mapping.account_range_start = "40000"
        mapping.account_range_end = "40999"
        mapping.account_name = "Test Wages Range"
        mapping.document_type = "Journal Entry"
        mapping.transaction_category = "Wages and Salaries"
        mapping.insert()

        # Test matching
        self.assertTrue(mapping.matches_account("40000"))
        self.assertTrue(mapping.matches_account("40500"))
        self.assertTrue(mapping.matches_account("40999"))
        self.assertFalse(mapping.matches_account("39999"))
        self.assertFalse(mapping.matches_account("41000"))

    def test_description_pattern_mapping(self):
        """Test mapping with description patterns"""
        mapping = frappe.new_doc("E-Boekhouden Account Mapping")
        mapping.description_patterns = "belastingdienst\nloonheffing"
        mapping.account_name = "Test Tax Mapping"
        mapping.document_type = "Journal Entry"
        mapping.transaction_category = "Tax Payments"
        mapping.insert()

        # Test matching
        self.assertTrue(mapping.matches_description("Betaling aan Belastingdienst"))
        self.assertTrue(mapping.matches_description("Loonheffing januari 2025"))
        self.assertFalse(mapping.matches_description("Regular supplier invoice"))
        self.assertFalse(mapping.matches_description(None))

    def test_usage_recording(self):
        """Test recording usage statistics"""
        mapping = frappe.new_doc("E-Boekhouden Account Mapping")
        mapping.account_code = "40001"
        mapping.account_name = "Test Usage Account"
        mapping.document_type = "Journal Entry"
        mapping.insert()

        # Record usage
        mapping.record_usage("Test transaction 1")
        self.assertEqual(mapping.usage_count, 1)
        self.assertIsNotNone(mapping.last_used)
        self.assertIn("Test transaction 1", mapping.sample_descriptions)

        # Record more usage
        mapping.record_usage("Test transaction 2")
        self.assertEqual(mapping.usage_count, 2)
        self.assertIn("Test transaction 2", mapping.sample_descriptions)

    def test_priority_ordering(self):
        """Test that higher priority mappings are selected first"""
        # Create low priority mapping
        low_priority = frappe.new_doc("E-Boekhouden Account Mapping")
        low_priority.account_code = "40001"
        low_priority.account_name = "Test Low Priority"
        low_priority.document_type = "Purchase Invoice"
        low_priority.priority = 10
        low_priority.insert()

        # Create high priority mapping
        high_priority = frappe.new_doc("E-Boekhouden Account Mapping")
        high_priority.account_code = "40001"
        high_priority.account_name = "Test High Priority"
        high_priority.document_type = "Journal Entry"
        high_priority.priority = 100
        high_priority.insert()

        # Test that high priority is selected
        from verenigingen.verenigingen.doctype.e_boekhouden_account_mapping.e_boekhouden_account_mapping import (
            get_mapping_for_mutation,
        )

        result = get_mapping_for_mutation("40001", None)
        self.assertEqual(result["document_type"], "Journal Entry")
