"""
Test suite for the enhanced PaymentEntryHandler.

Tests cover:
- Bank account mapping from ledger IDs
- Multi-invoice payment processing
- Row-to-invoice allocation strategies
- Error handling and edge cases
"""

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, add_days
from decimal import Decimal

from verenigingen.e_boekhouden.utils.payment_processing import PaymentEntryHandler


class TestPaymentEntryHandler(FrappeTestCase):
    """Test enhanced payment entry handler functionality."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "Test Company"
        
    def setUp(self):
        """Set up for each test."""
        self.handler = PaymentEntryHandler(self.company)
        
    def tearDown(self):
        """Clean up after each test."""
        # Clean up test payments
        test_payments = frappe.get_all(
            "Payment Entry",
            filters={"remarks": ["like", "%TEST-PAYMENT%"]},
            pluck="name"
        )
        for payment in test_payments:
            doc = frappe.get_doc("Payment Entry", payment)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete()
    
    def test_parse_invoice_numbers(self):
        """Test parsing of comma-separated invoice numbers."""
        # Single invoice
        result = self.handler._parse_invoice_numbers("INV-001")
        self.assertEqual(result, ["INV-001"])
        
        # Multiple invoices
        result = self.handler._parse_invoice_numbers("INV-001,INV-002,INV-003")
        self.assertEqual(result, ["INV-001", "INV-002", "INV-003"])
        
        # With spaces
        result = self.handler._parse_invoice_numbers("INV-001, INV-002 , INV-003")
        self.assertEqual(result, ["INV-001", "INV-002", "INV-003"])
        
        # Empty string
        result = self.handler._parse_invoice_numbers("")
        self.assertEqual(result, [])
        
        # None
        result = self.handler._parse_invoice_numbers(None)
        self.assertEqual(result, [])
    
    def test_bank_account_determination_with_ledger(self):
        """Test bank account determination from ledger mapping."""
        # Create test ledger mapping
        if not frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 99999}):
            # First ensure we have a bank account
            bank_account = frappe.db.get_value(
                "Account",
                {"account_type": "Bank", "company": self.company},
                "name"
            )
            
            if bank_account:
                mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
                mapping.ledger_id = 99999
                mapping.ledger_code = "TEST-BANK"
                mapping.ledger_name = "Test Bank Account"
                mapping.erpnext_account = bank_account
                mapping.save()
        
        # Test determination
        result = self.handler._determine_bank_account(99999, "Receive")
        self.assertIsNotNone(result)
        self.assertNotIn("Kas", result)  # Should not be cash account
        
        # Clean up
        frappe.db.delete("E-Boekhouden Ledger Mapping", {"ledger_id": 99999})
    
    def test_bank_account_fallback(self):
        """Test bank account fallback when no ledger mapping exists."""
        # Non-existent ledger
        result = self.handler._determine_bank_account(88888, "Receive")
        self.assertIsNotNone(result)
        # Should return a valid account
        self.assertTrue(frappe.db.exists("Account", {"name": result, "company": self.company}))
    
    def test_single_invoice_payment(self):
        """Test payment creation for single invoice."""
        mutation = {
            "id": 12345,
            "type": 3,  # Customer payment
            "date": nowdate(),
            "amount": 100.00,
            "ledgerId": 10440,  # Triodos
            "relationId": "TEST-CUST-001",
            "invoiceNumber": "TEST-INV-001",
            "description": "TEST-PAYMENT Single invoice payment"
        }
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment created
        self.assertIsNotNone(payment_name)
        
        # Check payment details
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.received_amount, 100.00)
        self.assertEqual(pe.eboekhouden_mutation_nr, "12345")
        
        # Clean up
        if pe.docstatus == 1:
            pe.cancel()
        pe.delete()
    
    def test_multi_invoice_payment_with_rows(self):
        """Test payment with multiple invoices and row allocations."""
        mutation = {
            "id": 5473,
            "type": 4,  # Supplier payment
            "date": nowdate(),
            "amount": 121.79,
            "ledgerId": 10440,
            "relationId": "TEST-SUPP-001",
            "invoiceNumber": "TEST-PINV-001,TEST-PINV-002",
            "description": "TEST-PAYMENT Multi-invoice with rows",
            "rows": [
                {"ledgerId": 13201853, "amount": -60.50},
                {"ledgerId": 13201853, "amount": -61.29}
            ]
        }
        
        # Create test supplier if needed
        if not frappe.db.exists("Supplier", "TEST-SUPP-001"):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "Test Supplier 001"
            supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
            supplier.save()
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.paid_amount, 121.79)
        self.assertEqual(pe.party_type, "Supplier")
        self.assertEqual(pe.party, "TEST-SUPP-001")
        
        # Check debug log for row allocation
        self.assertIn("Found 2 invoice(s)", " ".join(self.handler.debug_log))
        self.assertIn("row(s) to", " ".join(self.handler.debug_log))
        
        # Clean up
        if pe.docstatus == 1:
            pe.cancel()
        pe.delete()
    
    def test_payment_without_party(self):
        """Test payment creation without party (relation ID)."""
        mutation = {
            "id": 67890,
            "type": 3,
            "date": nowdate(),
            "amount": 50.00,
            "ledgerId": 10000,  # Cash
            "description": "TEST-PAYMENT Anonymous payment"
        }
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Should still create payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertIsNone(pe.party)
        self.assertEqual(pe.reference_no, "EB-67890")
        
        # Clean up
        if pe.docstatus == 1:
            pe.cancel()
        pe.delete()
    
    def test_error_handling_invalid_type(self):
        """Test error handling for invalid mutation type."""
        mutation = {
            "id": 11111,
            "type": 1,  # Invalid for payment
            "date": nowdate(),
            "amount": 100.00
        }
        
        # Should return None and log error
        result = self.handler.process_payment_mutation(mutation)
        self.assertIsNone(result)
        self.assertIn("Invalid mutation type", " ".join(self.handler.debug_log))
    
    def test_allocation_strategies(self):
        """Test different allocation strategies."""
        # Test 1:1 allocation
        invoices = [
            {"name": "INV-001", "doctype": "Sales Invoice", "grand_total": 100, "outstanding_amount": 100, "posting_date": nowdate()},
            {"name": "INV-002", "doctype": "Sales Invoice", "grand_total": 200, "outstanding_amount": 200, "posting_date": nowdate()}
        ]
        row_amounts = [100, 200]
        
        pe = frappe.new_doc("Payment Entry")
        self.handler._allocate_one_to_one(pe, invoices, row_amounts)
        
        self.assertEqual(len(pe.references), 2)
        self.assertEqual(pe.references[0].allocated_amount, 100)
        self.assertEqual(pe.references[1].allocated_amount, 200)
        
        # Test FIFO allocation
        pe2 = frappe.new_doc("Payment Entry")
        self.handler._allocate_fifo(pe2, invoices, [250])  # Less than total outstanding
        
        self.assertEqual(len(pe2.references), 2)
        self.assertEqual(pe2.references[0].allocated_amount, 100)  # First invoice fully paid
        self.assertEqual(pe2.references[1].allocated_amount, 150)  # Second invoice partially paid
    
    def test_debug_logging(self):
        """Test debug logging functionality."""
        # Process a simple mutation
        mutation = {
            "id": 99999,
            "type": 3,
            "date": nowdate(),
            "amount": 75.00,
            "ledgerId": 10440,
            "description": "TEST-PAYMENT Debug test"
        }
        
        self.handler.process_payment_mutation(mutation)
        
        # Check debug log
        debug_log = self.handler.get_debug_log()
        self.assertTrue(len(debug_log) > 0)
        self.assertIn("Processing payment mutation 99999", " ".join(debug_log))
        self.assertIn("Found 0 invoice(s)", " ".join(debug_log))


def run_tests():
    """Run the test suite."""
    unittest.main(module=__name__, exit=False)


if __name__ == "__main__":
    run_tests()