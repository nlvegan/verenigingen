#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focused Tests for Payment System Functionality

Tests core functionality without triggering race conditions or complex concurrent scenarios.
Focuses on realistic data generation and business logic validation.
"""

import time
from datetime import datetime

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.payment_history_validator import (
    get_payment_history_validation_stats,
    validate_and_repair_payment_history,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    standard_api,
    utility_api,
)


class TestPaymentSystemFunctionality(VereningingenTestCase):
    """Test core payment system functionality with realistic data"""

    def setUp(self):
        super().setUp()
        self.test_start_time = now_datetime()
        
        # Create test member with customer
        self.test_member = self.create_test_member(
            first_name="PaymentSystem",
            last_name="TestUser",
            email="payment.system.test@example.com"
        )
        
        # Ensure customer exists
        if not self.test_member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
            customer.customer_type = "Individual"
            customer.member = self.test_member.name
            customer.save()
            self.test_member.customer = customer.name
            self.test_member.save()
            self.track_doc("Customer", customer.name)

    def test_basic_payment_history_addition(self):
        """Test basic payment history functionality without race conditions"""
        # Create a simple invoice
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=today(),
            is_membership_invoice=1
        )
        
        # Get initial payment history count
        initial_count = len(self.test_member.payment_history or [])
        
        # Add invoice to payment history
        self.test_member.add_invoice_to_payment_history(invoice.name)
        
        # Reload member to get latest data
        self.test_member.reload()
        
        # Verify invoice was added
        final_count = len(self.test_member.payment_history or [])
        self.assertGreater(final_count, initial_count, 
                          "Invoice should be added to payment history")
        
        # Find the specific entry
        found_entry = None
        for entry in self.test_member.payment_history:
            if entry.invoice == invoice.name:
                found_entry = entry
                break
        
        # Verify entry details
        self.assertIsNotNone(found_entry, "Invoice entry should be found in payment history")
        self.assertEqual(found_entry.amount, invoice.grand_total)
        self.assertEqual(found_entry.status, invoice.status)

    def test_payment_history_validator_basic_functionality(self):
        """Test payment history validator with realistic scenarios"""
        # Create invoice without payment history entry (simulate missing entry)
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=add_days(today(), -1),
            is_membership_invoice=1
        )
        
        # Verify invoice is not in payment history initially
        payment_history_invoices = [entry.invoice for entry in (self.test_member.payment_history or [])]
        self.assertNotIn(invoice.name, payment_history_invoices, 
                        "Invoice should not be in payment history initially")
        
        # Run validator to detect and repair missing entries
        result = validate_and_repair_payment_history()
        
        # Verify validator ran successfully
        self.assertTrue(result["success"], "Validator should run successfully")
        
        # Check if missing entries were found and repaired
        if result["missing_found"] > 0:
            self.assertGreater(result["repaired"], 0, "Some missing entries should be repaired")

    def test_payment_history_statistics(self):
        """Test payment history statistics generation"""
        # Create some test data
        for i in range(3):
            invoice = self.create_test_sales_invoice(
                customer=self.test_member.customer,
                posting_date=add_days(today(), -i),
                is_membership_invoice=1
            )
            self.test_member.add_invoice_to_payment_history(invoice.name)
        
        # Get validation statistics
        stats = get_payment_history_validation_stats()
        
        # Verify statistics structure
        self.assertTrue(stats["success"], "Statistics generation should succeed")
        self.assertIn("total_invoices", stats)
        self.assertIn("invoices_with_members", stats)
        self.assertIn("payment_history_entries", stats)
        self.assertIn("sync_rate", stats)
        
        # Verify reasonable values
        self.assertGreaterEqual(stats["total_invoices"], 0)
        self.assertGreaterEqual(stats["sync_rate"], 0)
        self.assertLessEqual(stats["sync_rate"], 100)

    def test_api_security_decorators_basic_functionality(self):
        """Test API security decorators with basic functionality"""
        
        # Test utility API decorator
        @utility_api()
        def test_utility_function():
            return {"status": "utility_ok", "timestamp": now_datetime()}
        
        # Test standard API decorator
        @standard_api()
        def test_standard_function():
            return {"status": "standard_ok", "timestamp": now_datetime()}
        
        # Verify decorator attributes are set
        self.assertTrue(hasattr(test_utility_function, '_security_protected'))
        self.assertTrue(hasattr(test_standard_function, '_security_protected'))
        
        # Create test user with appropriate permissions
        test_user = self.create_test_user(
            "functional.test@example.com",
            roles=["Verenigingen Staff", "Verenigingen Manager"]
        )
        
        # Test function execution with proper user context
        with self.as_user(test_user.email):
            # Test utility function
            utility_result = test_utility_function()
            self.assertEqual(utility_result["status"], "utility_ok")
            self.assertIn("timestamp", utility_result)
            
            # Test standard function
            standard_result = test_standard_function()
            self.assertEqual(standard_result["status"], "standard_ok")
            self.assertIn("timestamp", standard_result)

    def test_member_customer_relationship(self):
        """Test member-customer relationship functionality"""
        # Verify member has customer
        self.assertIsNotNone(self.test_member.customer, "Member should have customer")
        
        # Verify customer exists
        customer_exists = frappe.db.exists("Customer", self.test_member.customer)
        self.assertTrue(customer_exists, "Customer should exist in database")
        
        # Verify bidirectional relationship
        customer_doc = frappe.get_doc("Customer", self.test_member.customer)
        self.assertEqual(customer_doc.member, self.test_member.name, 
                        "Customer should link back to member")

    def test_invoice_creation_with_proper_fields(self):
        """Test invoice creation with all proper fields"""
        # Create invoice with comprehensive field set
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=today(),
            due_date=add_days(today(), 30),
            is_membership_invoice=1
        )
        
        # Verify invoice was created successfully
        self.assertIsNotNone(invoice.name, "Invoice should have name")
        self.assertEqual(invoice.customer, self.test_member.customer)
        self.assertGreater(invoice.grand_total, 0, "Invoice should have positive amount")
        
        # Verify invoice status
        self.assertIn(invoice.status, ["Draft", "Unpaid", "Overdue"], 
                     "Invoice should have valid status")

    def test_payment_entry_creation(self):
        """Test payment entry creation and linking"""
        # Create invoice first
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=today(),
            is_membership_invoice=1
        )
        
        # Create payment entry
        payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            paid_amount=invoice.grand_total,
            posting_date=today()
        )
        
        # Link payment to invoice
        payment.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": invoice.grand_total
        })
        payment.save()
        
        # Verify payment entry was created
        self.assertIsNotNone(payment.name, "Payment entry should have name")
        self.assertEqual(payment.party, self.test_member.customer)
        self.assertEqual(payment.paid_amount, invoice.grand_total)

    def test_bulk_flag_behavior(self):
        """Test bulk processing flag behavior"""
        # Test without bulk flag
        frappe.flags.bulk_invoice_generation = False
        
        invoice1 = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=today(),
            is_membership_invoice=1
        )
        
        start_time = time.time()
        self.test_member.add_invoice_to_payment_history(invoice1.name)
        normal_time = time.time() - start_time
        
        # Test with bulk flag
        frappe.flags.bulk_invoice_generation = True
        
        try:
            invoice2 = self.create_test_sales_invoice(
                customer=self.test_member.customer,
                posting_date=add_days(today(), -1),
                is_membership_invoice=1
            )
            
            start_time = time.time()
            self.test_member.add_invoice_to_payment_history(invoice2.name)
            bulk_time = time.time() - start_time
            
            # Both should complete successfully
            self.assertLess(normal_time, 10.0, "Normal processing should be fast")
            self.assertLess(bulk_time, 10.0, "Bulk processing should complete reasonably")
            
        finally:
            # Clean up flag
            frappe.flags.bulk_invoice_generation = False

    def test_error_handling_graceful_degradation(self):
        """Test error handling and graceful degradation"""
        # Test with non-existent invoice
        fake_invoice_name = "FAKE-INVOICE-DOES-NOT-EXIST"
        
        # This should not raise an exception
        try:
            self.test_member.add_invoice_to_payment_history(fake_invoice_name)
            error_handled = True
        except Exception as e:
            error_handled = False
            print(f"Unexpected exception for fake invoice: {e}")
        
        self.assertTrue(error_handled, "Fake invoice should be handled gracefully")
        
        # Verify fake invoice is not in payment history
        payment_history_invoices = [entry.invoice for entry in (self.test_member.payment_history or [])]
        self.assertNotIn(fake_invoice_name, payment_history_invoices, 
                        "Fake invoice should not be in payment history")

    def test_performance_reasonable_execution_times(self):
        """Test that operations complete within reasonable time"""
        # Create multiple invoices for performance testing
        invoices = []
        for i in range(5):
            invoice = self.create_test_sales_invoice(
                customer=self.test_member.customer,
                posting_date=add_days(today(), -i),
                is_membership_invoice=1
            )
            invoices.append(invoice)
        
        # Measure performance of adding all invoices
        start_time = time.time()
        
        for invoice in invoices:
            self.test_member.add_invoice_to_payment_history(invoice.name)
        
        total_time = time.time() - start_time
        
        # Should complete within reasonable time (10 seconds for 5 invoices)
        self.assertLess(total_time, 10.0, 
                       f"Processing 5 invoices should complete within 10s: {total_time:.2f}s")
        
        # Average time per invoice should be reasonable
        avg_time = total_time / len(invoices)
        self.assertLess(avg_time, 2.0, 
                       f"Average time per invoice should be under 2s: {avg_time:.2f}s")

    def test_data_consistency_after_operations(self):
        """Test data consistency after payment operations"""
        # Create invoice and add to payment history
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            posting_date=today(),
            is_membership_invoice=1
        )
        
        self.test_member.add_invoice_to_payment_history(invoice.name)
        
        # Reload member and verify consistency
        self.test_member.reload()
        
        # Find the payment history entry
        found_entry = None
        for entry in self.test_member.payment_history:
            if entry.invoice == invoice.name:
                found_entry = entry
                break
        
        # Verify data consistency
        self.assertIsNotNone(found_entry, "Payment history entry should exist")
        self.assertEqual(found_entry.amount, invoice.grand_total, 
                        "Payment history amount should match invoice total")
        self.assertEqual(found_entry.status, invoice.status,
                        "Payment history status should match invoice status")

    def tearDown(self):
        """Clean up test data"""
        try:
            # Reset any bulk processing flags  
            frappe.flags.bulk_invoice_generation = False
            
            # Check for any errors during testing
            error_count = frappe.db.count("Error Log", filters={
                "creation": [">=", self.test_start_time]
            })
            
            if error_count > 0:
                print(f"Warning: {error_count} errors logged during test execution")
                
        except Exception as e:
            print(f"Warning: Error during tearDown: {e}")
        
        super().tearDown()