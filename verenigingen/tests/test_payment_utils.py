#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit Tests for payment_utils.py
================================

Tests for standardized Payment Entry query utilities.
Ensures the new payment utilities work correctly and handle edge cases.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, today, flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.payment_utils import (
    get_customer_payments_summary,
    get_payment_history_for_customer,
    get_payment_references_for_invoice,
    get_unreconciled_payments,
    get_payment_allocation_status,
    has_payments,
    get_last_payment_date,
    get_payment_years_for_customer
)


class TestPaymentUtils(EnhancedTestCase):
    """Test suite for payment utilities"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test member with customer
        self.member = self.create_test_member(
            first_name="Payment",
            last_name="Test",
            email="payment.test@test.com",
            birth_date="1990-01-01"
        )
        self.customer_name = self.member.customer

    def test_get_customer_payments_summary_basic(self):
        """Test basic payment summary retrieval"""
        summary = get_customer_payments_summary(self.customer_name)
        
        # Should return dict with expected structure
        self.assertIsInstance(summary, dict)
        self.assertIn('customer_name', summary)
        self.assertIn('payment_count', summary)
        self.assertIn('total_amount', summary)
        
        # New customer should have zero payments
        self.assertEqual(summary.get('payment_count', 0), 0)
        self.assertEqual(summary.get('total_amount', 0), 0.0)
        
        # Test with invalid customer
        empty_summary = get_customer_payments_summary("INVALID-CUSTOMER")
        self.assertEqual(empty_summary, {})
        
        # Test with empty input
        no_summary = get_customer_payments_summary("")
        self.assertEqual(no_summary, {})

    def test_get_customer_payments_summary_year_filter(self):
        """Test payment summary with year filtering"""
        from datetime import datetime
        current_year = datetime.now().year
        
        summary = get_customer_payments_summary(self.customer_name, year=current_year)
        
        # Should include year filter in result
        self.assertIsInstance(summary, dict)
        period_filter = summary.get('period_filter', {})
        self.assertEqual(period_filter.get('year'), current_year)

    def test_get_payment_history_for_customer(self):
        """Test payment history retrieval"""
        history = get_payment_history_for_customer(self.customer_name)
        
        # Should return list
        self.assertIsInstance(history, list)
        
        # Test with invalid customer
        no_history = get_payment_history_for_customer("INVALID-CUSTOMER")
        self.assertEqual(no_history, [])
        
        # Test with empty input
        empty_history = get_payment_history_for_customer("")
        self.assertEqual(empty_history, [])

    def test_get_payment_history_with_custom_fields(self):
        """Test payment history with custom field selection"""
        custom_fields = ["name", "posting_date", "paid_amount"]
        history = get_payment_history_for_customer(self.customer_name, fields=custom_fields)
        
        self.assertIsInstance(history, list)
        # Should handle custom fields without error

    def test_get_payment_references_for_invoice(self):
        """Test payment reference retrieval"""
        references = get_payment_references_for_invoice("Sales Invoice", "SI-TEST-001")
        
        # Should return list
        self.assertIsInstance(references, list)
        
        # Test with invalid inputs
        no_refs = get_payment_references_for_invoice("", "SI-TEST-001")
        self.assertEqual(no_refs, [])
        
        empty_refs = get_payment_references_for_invoice("Sales Invoice", "")
        self.assertEqual(empty_refs, [])

    def test_get_payment_references_without_details(self):
        """Test payment references without payment details"""
        references = get_payment_references_for_invoice(
            "Sales Invoice", 
            "SI-TEST-001",
            include_payment_details=False
        )
        
        self.assertIsInstance(references, list)

    def test_get_unreconciled_payments(self):
        """Test unreconciled payments retrieval"""
        unreconciled = get_unreconciled_payments()
        
        # Should return list
        self.assertIsInstance(unreconciled, list)
        
        # Test with party filter
        customer_unreconciled = get_unreconciled_payments(
            party_type="Customer",
            customer=self.customer_name
        )
        self.assertIsInstance(customer_unreconciled, list)
        
        # Test with minimum amount filter
        high_amount_unreconciled = get_unreconciled_payments(minimum_amount=100.0)
        self.assertIsInstance(high_amount_unreconciled, list)

    def test_get_payment_allocation_status(self):
        """Test payment allocation status retrieval"""
        status = get_payment_allocation_status("PE-TEST-001")
        
        # Should return dict (empty for non-existent payment)
        self.assertIsInstance(status, dict)
        
        # Test with empty input
        no_status = get_payment_allocation_status("")
        self.assertEqual(no_status, {})

    def test_convenience_functions(self):
        """Test convenience utility functions"""
        
        # Test has_payments
        has_payment = has_payments(self.customer_name)
        self.assertIsInstance(has_payment, bool)
        self.assertFalse(has_payment)  # New customer should have no payments
        
        # Test get_last_payment_date
        last_date = get_last_payment_date(self.customer_name)
        self.assertIsNone(last_date)  # New customer should have no last payment
        
        # Test get_payment_years_for_customer
        years = get_payment_years_for_customer(self.customer_name)
        self.assertIsInstance(years, list)
        self.assertEqual(years, [])  # New customer should have no payment years

    def test_error_handling(self):
        """Test error handling in utilities"""
        
        # All functions should handle None/empty inputs gracefully
        self.assertEqual(get_customer_payments_summary(None), {})
        self.assertEqual(get_payment_history_for_customer(None), [])
        self.assertEqual(get_payment_references_for_invoice(None, None), [])
        self.assertEqual(get_unreconciled_payments(customer=None), [])
        self.assertEqual(get_payment_allocation_status(None), {})
        
        # Convenience functions should return appropriate defaults
        self.assertFalse(has_payments(None))
        self.assertIsNone(get_last_payment_date(None))
        self.assertEqual(get_payment_years_for_customer(None), [])

    def test_date_filtering_options(self):
        """Test various date filtering options"""
        from frappe.utils import add_months, today
        
        # Test date range filtering
        date_from = add_months(today(), -6)
        date_to = today()
        
        summary = get_customer_payments_summary(
            self.customer_name,
            date_from=date_from,
            date_to=date_to
        )
        self.assertIsInstance(summary, dict)
        
        # Test with only date_from
        summary_from = get_customer_payments_summary(
            self.customer_name,
            date_from=date_from
        )
        self.assertIsInstance(summary_from, dict)
        
        # Test with only date_to  
        summary_to = get_customer_payments_summary(
            self.customer_name,
            date_to=date_to
        )
        self.assertIsInstance(summary_to, dict)

    def test_payment_history_limits(self):
        """Test payment history with different limits"""
        
        # Test with custom limit
        limited_history = get_payment_history_for_customer(self.customer_name, limit=10)
        self.assertIsInstance(limited_history, list)
        self.assertLessEqual(len(limited_history), 10)
        
        # Test with year filter
        from datetime import datetime
        current_year = datetime.now().year
        yearly_history = get_payment_history_for_customer(self.customer_name, year=current_year)
        self.assertIsInstance(yearly_history, list)

    def test_field_validation_consistency(self):
        """Test consistent field handling across utilities"""
        
        # Test that all utilities handle field parameters consistently
        summary = get_customer_payments_summary(self.customer_name)
        self.assertIsInstance(summary, dict)
        
        history = get_payment_history_for_customer(
            self.customer_name, 
            fields=["name", "posting_date"]
        )
        self.assertIsInstance(history, list)
        
        references = get_payment_references_for_invoice(
            "Sales Invoice",
            "TEST-001",
            include_payment_details=True
        )
        self.assertIsInstance(references, list)

    def test_customer_relationship_validation(self):
        """Test customer relationship validation"""
        
        # Verify member has customer field populated
        self.assertIsNotNone(self.member.customer, "Member must have customer field populated")
        self.assertTrue(len(self.member.customer) > 0, "Customer field should contain valid customer ID")
        
        # Test payment utilities work with customer name, not member name
        member_summary_wrong = get_customer_payments_summary(self.member.name)  # Should be empty
        customer_summary_correct = get_customer_payments_summary(self.customer_name)  # Should work
        
        # Member name should not work for payment lookup (should return empty dict)
        self.assertEqual(member_summary_wrong, {}, "Member name should not work for payment summary lookup")
        
        # Customer name should work and return proper structure (even if zero payments for new customer)
        self.assertIsInstance(customer_summary_correct, dict, "Customer name should work for payment lookup")
        self.assertIn('payment_count', customer_summary_correct, "Valid customer should return structured data")

    def test_summary_data_structure(self):
        """Test payment summary data structure consistency"""
        
        # Test that utilities return consistent data structures
        summary = get_customer_payments_summary(self.customer_name)
        self.assertIsInstance(summary, dict)
        
        # Verify that summary contains expected data fields
        expected_fields = ['payment_count', 'total_amount', 'average_payment']
        for field in expected_fields:
            self.assertIn(field, summary)


if __name__ == '__main__':
    import unittest
    unittest.main()