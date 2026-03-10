#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit Tests for financial_utils.py
=================================

Tests for standardized financial query utilities.
Ensures the new utilities work correctly and handle edge cases.
"""

import frappe

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
# Unused import removed - using EnhancedTestCase
from frappe.utils import add_months, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_utils import (
    get_customer_invoices,
    get_outstanding_invoices,
    get_member_for_customer,
    get_customer_for_member,
    has_outstanding_invoices,
    get_total_outstanding_amount
)
import unittest


class TestFinancialUtils(EnhancedTestCase):
    """Test suite for financial utilities"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test member with customer
        self.member = self.create_test_member(
            first_name="Financial",
            last_name="Test",
            email="financial.test@test.com",
            birth_date="1990-01-01"
        )
        self.customer_name = self.member.customer

    def test_get_customer_invoices_basic(self):
        """Test basic customer invoice retrieval"""
        invoices = get_customer_invoices(self.customer_name)
        
        # Should return empty list for new customer
        self.assertIsInstance(invoices, list)
        
        # Test with invalid customer
        empty_invoices = get_customer_invoices("INVALID-CUSTOMER")
        self.assertEqual(empty_invoices, [])
        
        # Test with empty input
        no_invoices = get_customer_invoices("")
        self.assertEqual(no_invoices, [])

    def test_get_outstanding_invoices(self):
        """Test outstanding invoice retrieval"""
        outstanding = get_outstanding_invoices(self.customer_name)
        
        # Should return list
        self.assertIsInstance(outstanding, list)
        
        # Test with invalid customer
        no_outstanding = get_outstanding_invoices("INVALID-CUSTOMER")
        self.assertEqual(no_outstanding, [])

    def test_member_customer_lookups(self):
        """Test member-customer relationship lookups"""
        
        # Test customer -> member lookup
        found_member = get_member_for_customer(self.customer_name)
        self.assertEqual(found_member, self.member.name)
        
        # Test member -> customer lookup  
        found_customer = get_customer_for_member(self.member.name)
        self.assertEqual(found_customer, self.customer_name)
        
        # Test with invalid inputs
        self.assertIsNone(get_member_for_customer("INVALID-CUSTOMER"))
        self.assertIsNone(get_customer_for_member("INVALID-MEMBER"))
        self.assertIsNone(get_member_for_customer(""))
        self.assertIsNone(get_customer_for_member(""))

    def test_convenience_functions(self):
        """Test convenience utility functions"""
        
        # Test has_outstanding_invoices
        has_outstanding = has_outstanding_invoices(self.customer_name)
        self.assertIsInstance(has_outstanding, bool)
        
        # Test get_total_outstanding_amount
        total_outstanding = get_total_outstanding_amount(self.customer_name)
        self.assertIsInstance(total_outstanding, float)
        self.assertGreaterEqual(total_outstanding, 0.0)

    def test_error_handling(self):
        """Test error handling in utilities"""
        
        # All functions should handle None/empty inputs gracefully
        self.assertEqual(get_customer_invoices(None), [])
        self.assertEqual(get_outstanding_invoices(None), [])
        self.assertIsNone(get_member_for_customer(None))
        self.assertIsNone(get_customer_for_member(None))
        
        # Boolean functions should return appropriate defaults
        self.assertFalse(has_outstanding_invoices(""))
        self.assertEqual(get_total_outstanding_amount(""), 0.0)

    def test_field_customization(self):
        """Test custom field selection"""
        
        # Test with custom fields
        custom_fields = ["name", "posting_date"]
        invoices = get_customer_invoices(self.customer_name, fields=custom_fields)
        
        self.assertIsInstance(invoices, list)
        
        # Test outstanding invoices with custom fields
        outstanding = get_outstanding_invoices(self.customer_name, fields=custom_fields)
        self.assertIsInstance(outstanding, list)

    def test_filtering_options(self):
        """Test various filtering options"""
        
        # Test outstanding_only filter
        outstanding_only = get_customer_invoices(self.customer_name, outstanding_only=True)
        self.assertIsInstance(outstanding_only, list)
        
        # Test date filtering
        date_from = add_months(today(), -1)
        recent_invoices = get_customer_invoices(self.customer_name, date_from=date_from)
        self.assertIsInstance(recent_invoices, list)
        
        # Test limit
        limited_invoices = get_customer_invoices(self.customer_name, limit=5)
        self.assertIsInstance(limited_invoices, list)
        self.assertLessEqual(len(limited_invoices), 5)

    def test_member_customer_field_validation(self):
        """Test critical Member-Customer field relationships to prevent regression"""
        
        # Verify member has customer field populated
        self.assertIsNotNone(self.member.customer, "Member must have customer field populated")
        self.assertTrue(len(self.member.customer) > 0, "Customer field should contain valid customer ID")
        
        # Test that financial queries use customer name, not member name  
        member_invoices_wrong = get_customer_invoices(self.member.name)  # This should return empty
        customer_invoices_correct = get_customer_invoices(self.customer_name)  # This is correct
        
        # Member name should not work as customer lookup (would indicate bug)
        self.assertEqual(member_invoices_wrong, [], "Member name should not work for customer invoice lookup")
        
        # Customer name should work (even if empty for new customer)
        self.assertIsInstance(customer_invoices_correct, list, "Customer name should work for invoice lookup")
        
        # Test outstanding invoice queries use customer, not member
        outstanding_wrong = get_outstanding_invoices(self.member.name)  # Should be empty
        outstanding_correct = get_outstanding_invoices(self.customer_name)  # Should work
        
        self.assertEqual(outstanding_wrong, [], "Member name should not work for outstanding invoice lookup")
        self.assertIsInstance(outstanding_correct, list, "Customer name should work for outstanding lookup")

    def test_reverse_lookup_validation(self):
        """Test Member-Customer reverse lookup validation"""
        
        # Customer -> Member lookup should work
        found_member = get_member_for_customer(self.customer_name)
        self.assertEqual(found_member, self.member.name, "Customer->Member lookup should return correct member")
        
        # Member -> Customer lookup should work  
        found_customer = get_customer_for_member(self.member.name)
        self.assertEqual(found_customer, self.customer_name, "Member->Customer lookup should return correct customer")
        
        # Verify these are different values (not the same ID)
        self.assertNotEqual(self.member.name, self.customer_name, "Member and Customer should have different IDs")
        
        # Member name should not work as customer in reverse lookup
        reverse_lookup_wrong = get_member_for_customer(self.member.name)
        self.assertIsNone(reverse_lookup_wrong, "Member name should not work in customer->member lookup")

    def test_payment_processing_field_correctness(self):
        """Test that payment processing uses correct field references"""
        
        # This tests the financial mixin logic indirectly
        # by verifying the underlying utilities work correctly
        
        # Outstanding invoices should use customer, not member
        outstanding = get_outstanding_invoices(self.customer_name)
        self.assertIsInstance(outstanding, list, "Outstanding invoices should work with customer name")
        
        # Should not work with member name (preventing the bug we fixed)
        outstanding_wrong = get_outstanding_invoices(self.member.name)
        self.assertEqual(outstanding_wrong, [], "Outstanding invoices should not work with member name")
        
        # Verify customer field exists and is valid Customer DocType reference
        self.assertTrue(
            DocumentExistenceValidator.check_document_exists("Customer", self.customer_name),
            "Member.customer field should reference valid Customer document"
        )


if __name__ == '__main__':
    import unittest
    unittest.main()