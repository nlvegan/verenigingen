"""
Test suite using actual E-Boekhouden payment mutations.

This test suite uses the specific mutations mentioned by the user:
- 7833: Customer payment
- 5473: Supplier payment with multiple invoices
- 6217: Another payment example
"""

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate
import json

from verenigingen.e_boekhouden.utils.payment_processing import PaymentEntryHandler


class TestActualPaymentMutations(FrappeTestCase):
    """Test payment processing with actual E-Boekhouden mutations."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data based on actual mutations."""
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "Test Company"
        
        # Actual mutation data based on API analysis
        cls.mutations = {
            7833: {
                "id": 7833,
                "type": 3,  # Customer payment
                "date": "2024-01-15",
                "amount": 250.00,
                "ledgerId": 13201869,  # Triodos bank
                "relationId": "CUST-001",
                "invoiceNumber": "INV-2024-001",
                "description": "Payment for invoice INV-2024-001",
                "rows": [
                    {"ledgerId": 13201852, "amount": 250.00}  # Receivable account
                ]
            },
            5473: {
                "id": 5473,
                "type": 4,  # Supplier payment
                "date": "2024-12-10",
                "amount": 121.79,
                "ledgerId": 13201869,  # Triodos bank
                "relationId": "6104885",
                "invoiceNumber": "7771-2024-15525,7771-2024-15644",  # Multiple invoices!
                "description": "Payment for multiple supplier invoices",
                "rows": [
                    {"ledgerId": 13201853, "amount": -60.50},  # First invoice
                    {"ledgerId": 13201853, "amount": -61.29}   # Second invoice
                ]
            },
            6217: {
                "id": 6217,
                "type": 3,  # Customer payment
                "date": "2024-11-20",
                "amount": 500.00,
                "ledgerId": 13201869,  # Triodos bank
                "relationId": "CUST-123",
                "invoiceNumber": "SI-2024-0456",
                "description": "Customer payment via bank transfer"
            }
        }
        
        # Set up test ledger mappings
        cls._setup_test_ledger_mappings()
        
    @classmethod
    def _setup_test_ledger_mappings(cls):
        """Set up ledger mappings for test mutations."""
        # Ensure we have a Triodos bank account
        triodos = frappe.db.get_value(
            "Account",
            {"account_number": "10440", "company": cls.company},
            "name"
        )
        
        if not triodos:
            # Create test bank account
            triodos = frappe.new_doc("Account")
            triodos.account_name = "Triodos Test"
            triodos.account_number = "10440"
            triodos.parent_account = frappe.db.get_value(
                "Account",
                {"account_type": "Bank", "is_group": 1, "company": cls.company},
                "name"
            )
            triodos.account_type = "Bank"
            triodos.company = cls.company
            triodos.save()
            triodos = triodos.name
        
        # Create ledger mapping for Triodos (13201869)
        if not frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": 13201869}):
            mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
            mapping.ledger_id = 13201869
            mapping.ledger_code = "10440"
            mapping.ledger_name = "Triodos Bank"
            mapping.erpnext_account = triodos
            mapping.save()
    
    def setUp(self):
        """Set up for each test."""
        self.handler = PaymentEntryHandler(self.company)
        
    def tearDown(self):
        """Clean up test payments."""
        # Clean up any test payments created
        test_mutations = ["7833", "5473", "6217"]
        for mutation_id in test_mutations:
            payments = frappe.get_all(
                "Payment Entry",
                filters={"eboekhouden_mutation_nr": mutation_id},
                pluck="name"
            )
            for payment in payments:
                doc = frappe.get_doc("Payment Entry", payment)
                if doc.docstatus == 1:
                    doc.cancel()
                doc.delete()
    
    def test_mutation_7833_single_customer_payment(self):
        """Test mutation 7833 - Single customer payment."""
        mutation = self.mutations[7833]
        
        # Create test customer
        if not frappe.db.exists("Customer", "CUST-001"):
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Customer 001"
            customer.customer_group = frappe.db.get_value("Customer Group", {}, "name")
            customer.territory = frappe.db.get_value("Territory", {}, "name")
            customer.save()
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.received_amount, 250.00)
        self.assertEqual(pe.party_type, "Customer")
        self.assertEqual(pe.party, "CUST-001")
        self.assertEqual(pe.reference_no, "INV-2024-001")
        
        # Verify bank account mapping
        self.assertIn("Triodos", pe.paid_to)  # Should map to Triodos, not Kas
        self.assertNotIn("Kas", pe.paid_to)
        
        # Check debug log
        self.assertIn("Mapped ledger 13201869", " ".join(self.handler.debug_log))
    
    def test_mutation_5473_multi_invoice_supplier_payment(self):
        """Test mutation 5473 - Supplier payment with multiple invoices."""
        mutation = self.mutations[5473]
        
        # Create test supplier
        if not frappe.db.exists("Supplier", "6104885"):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "Test Supplier 6104885"
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
        self.assertEqual(pe.party, "6104885")
        
        # Verify multi-invoice handling
        self.assertEqual(pe.reference_no, "7771-2024-15525,7771-2024-15644")
        
        # Verify bank account
        self.assertIn("Triodos", pe.paid_from)
        self.assertNotIn("Kas", pe.paid_from)
        
        # Check allocation strategy was triggered
        self.assertIn("Found 2 invoice(s)", " ".join(self.handler.debug_log))
        self.assertIn("Allocating 2 row(s)", " ".join(self.handler.debug_log))
    
    def test_mutation_6217_customer_payment_without_rows(self):
        """Test mutation 6217 - Customer payment without row details."""
        mutation = self.mutations[6217]
        
        # Create test customer
        if not frappe.db.exists("Customer", "CUST-123"):
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Customer 123"
            customer.customer_group = frappe.db.get_value("Customer Group", {}, "name")
            customer.territory = frappe.db.get_value("Territory", {}, "name")
            customer.save()
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.received_amount, 500.00)
        self.assertEqual(pe.party, "CUST-123")
        self.assertEqual(pe.reference_no, "SI-2024-0456")
        
        # Should still use Triodos bank
        self.assertIn("Triodos", pe.paid_to)
    
    def test_multi_invoice_parsing(self):
        """Test parsing of comma-separated invoice numbers from mutation 5473."""
        mutation = self.mutations[5473]
        
        invoice_numbers = self.handler._parse_invoice_numbers(mutation['invoiceNumber'])
        
        self.assertEqual(len(invoice_numbers), 2)
        self.assertEqual(invoice_numbers[0], "7771-2024-15525")
        self.assertEqual(invoice_numbers[1], "7771-2024-15644")
    
    def test_row_amount_extraction(self):
        """Test extraction of row amounts for allocation."""
        mutation = self.mutations[5473]
        
        row_amounts = [abs(row['amount']) for row in mutation['rows']]
        
        self.assertEqual(len(row_amounts), 2)
        self.assertEqual(row_amounts[0], 60.50)
        self.assertEqual(row_amounts[1], 61.29)
        self.assertAlmostEqual(sum(row_amounts), 121.79, places=2)
    
    def test_complete_payment_flow_with_invoices(self):
        """Test complete payment flow with actual invoice creation and reconciliation."""
        # Create test supplier
        if not frappe.db.exists("Supplier", "TEST-SUPP-5473"):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "Test Supplier for 5473"
            supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
            supplier.save()
        
        # Create test purchase invoices matching mutation 5473
        pi1 = frappe.new_doc("Purchase Invoice")
        pi1.supplier = "TEST-SUPP-5473"
        pi1.company = self.company
        pi1.posting_date = "2024-12-01"
        pi1.append("items", {
            "item_code": frappe.db.get_value("Item", {"is_stock_item": 0}, "name") or "Service",
            "qty": 1,
            "rate": 60.50
        })
        pi1.save()
        pi1.submit()
        
        pi2 = frappe.new_doc("Purchase Invoice")
        pi2.supplier = "TEST-SUPP-5473"
        pi2.company = self.company
        pi2.posting_date = "2024-12-05"
        pi2.append("items", {
            "item_code": frappe.db.get_value("Item", {"is_stock_item": 0}, "name") or "Service",
            "qty": 1,
            "rate": 61.29
        })
        pi2.save()
        pi2.submit()
        
        # Create mutation with actual invoice names
        mutation = self.mutations[5473].copy()
        mutation['relationId'] = "TEST-SUPP-5473"
        mutation['invoiceNumber'] = f"{pi1.name},{pi2.name}"
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment and allocations
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(len(pe.references), 2)
        
        # Check allocations match row amounts
        self.assertEqual(pe.references[0].allocated_amount, 60.50)
        self.assertEqual(pe.references[1].allocated_amount, 61.29)
        
        # Clean up
        pe.cancel()
        pe.delete()
        pi1.cancel()
        pi1.delete()
        pi2.cancel()
        pi2.delete()
    
    def test_ledger_cache_performance(self):
        """Test that ledger lookups are cached for performance."""
        mutation = self.mutations[7833]
        
        # Clear cache
        self.handler._ledger_cache.clear()
        
        # First lookup
        account1 = self.handler._determine_bank_account(13201869, "Receive")
        self.assertEqual(len(self.handler._ledger_cache), 1)
        
        # Second lookup should use cache
        account2 = self.handler._determine_bank_account(13201869, "Receive")
        self.assertEqual(account1, account2)
        self.assertEqual(len(self.handler._ledger_cache), 1)  # Still only one entry
        
        # Different payment type creates new cache entry
        account3 = self.handler._determine_bank_account(13201869, "Pay")
        self.assertEqual(len(self.handler._ledger_cache), 2)


def run_tests():
    """Run the test suite."""
    unittest.main(module=__name__, exit=False)


if __name__ == "__main__":
    run_tests()