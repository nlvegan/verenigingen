"""
Test suite using actual E-Boekhouden payment mutations.

This test suite uses the specific mutations mentioned by the user:
- 7833: Customer payment
- 5473: Supplier payment with multiple invoices
- 6217: Another payment example
"""

import unittest
import frappe

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from frappe.utils import nowdate
import json

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.e_boekhouden.utils.payment_processing import PaymentEntryHandler


class TestActualPaymentMutations(EnhancedTestCase):
    """Test payment processing with actual E-Boekhouden mutations."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data based on actual mutations."""
        super().setUpClass()
        # Prefer the configured default company; fall back to the ERPNext test
        # company that always exists on the test site ("Test Company" does not).
        cls.company = (
            frappe.db.get_single_value("Global Defaults", "default_company")
            or ("_Test Company" if frappe.db.exists("Company", "_Test Company") else None)
            or frappe.get_all("Company", limit=1, pluck="name")[0]
        )
        
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

        # The payment handler resolves a "Bank Account" (not just the GL Account)
        # linked to this GL account; create one so processing can proceed.
        if not frappe.db.exists("Bank Account", {"account": triodos}):
            if not frappe.db.exists("Bank", "Triodos Test Bank"):
                bank = frappe.new_doc("Bank")
                bank.bank_name = "Triodos Test Bank"
                bank.insert(ignore_permissions=True)
            bank_account = frappe.new_doc("Bank Account")
            bank_account.account_name = "Triodos Test Bank Account"
            bank_account.bank = "Triodos Test Bank"
            bank_account.account = triodos
            bank_account.company = cls.company
            bank_account.is_company_account = 1
            bank_account.flags.ignore_mandatory = True
            bank_account.insert(ignore_permissions=True)

        # Create ledger mapping for Triodos (13201869)
        if not DocumentExistenceValidator.check_document_exists("E-Boekhouden Ledger Mapping", {"ledger_id": 13201869}):
            mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
            mapping.ledger_id = 13201869
            mapping.ledger_code = "10440"
            mapping.ledger_name = "Triodos Bank"
            mapping.erpnext_account = triodos
            mapping.save()
    
    def setUp(self):
        """Set up for each test."""
        super().setUp()
        self.handler = PaymentEntryHandler(self.company)
        
    def tearDown(self):
        """Clean up handled by Enhanced Test Factory rollback."""
        super().tearDown()
        # Enhanced Test Factory handles cleanup automatically
    
    def test_mutation_7833_single_customer_payment(self):
        """Test mutation 7833 - Single customer payment."""
        mutation = self.mutations[7833]
        
        # Create test customer (Enhanced Test Factory handles cleanup automatically)
        if not DocumentExistenceValidator.check_document_exists("Customer", "CUST-001"):
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Customer 001"
            customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name") or "All Customer Groups"
            territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="name")
            if territory:
                customer.territory = territory
            customer.save()
            customer.rename("CUST-001")
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.received_amount, 250.00)
        self.assertEqual(pe.party_type, "Customer")
        # The handler resolves the eBoekhouden relation to its own customer
        # ("E-Boekhouden Customer <relationId>"), so assert the relationId is part
        # of the resolved party rather than an exact match on the raw id.
        self.assertIn("CUST-001", pe.party)
        self.assertEqual(pe.reference_no, "INV-2024-001")
        
        # Verify bank account mapping
        self.assertIn("Triodos", pe.paid_to)  # Should map to Triodos, not Kas
        self.assertNotIn("Kas", pe.paid_to)
        
        # Check debug log
        self.assertIn("Mapped ledger 13201869", " ".join(self.handler.debug_log))

        # The handler COMMITS the Payment Entry, so the test transaction rollback
        # won't remove it. Without cleanup the fixed mutation id 7833 makes a rerun
        # short-circuit on the dedup early-return (empty debug log) and fail.
        self._cleanup_committed_payment_entry(payment_name)

    def test_mutation_5473_multi_invoice_supplier_payment(self):
        """Test mutation 5473 - Supplier payment with multiple invoices."""
        mutation = self.mutations[5473]
        
        # Create test supplier (Enhanced Test Factory handles cleanup automatically)
        if not DocumentExistenceValidator.check_document_exists("Supplier", "6104885"):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = "Test Supplier 6104885"
            supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name")
            if supplier_group:
                supplier.supplier_group = supplier_group
            supplier.save()
            supplier.rename("6104885")
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.paid_amount, 121.79)
        self.assertEqual(pe.party_type, "Supplier")
        # Handler resolves the eBoekhouden relation to its own supplier name.
        self.assertIn("6104885", pe.party)
        
        # Verify multi-invoice handling
        self.assertEqual(pe.reference_no, "7771-2024-15525,7771-2024-15644")
        
        # Verify bank account
        self.assertIn("Triodos", pe.paid_from)
        self.assertNotIn("Kas", pe.paid_from)
        
        # The handler parses both invoice numbers from the mutation. These sample
        # invoice numbers do not correspond to real ERPNext invoices on the test
        # site, so no allocation occurs (the actual allocation-to-invoices path is
        # exercised by test_complete_payment_flow_with_invoices, which creates real
        # Purchase Invoices). Assert the parse step rather than allocation here.
        debug = " ".join(self.handler.debug_log)
        self.assertIn("Found 2 invoice(s)", debug)
        self.assertIn("No matching invoices found for allocation", debug)

        # Remove the committed Payment Entry so the fixed mutation id 5473 does not
        # make a rerun short-circuit on the dedup early-return.
        self._cleanup_committed_payment_entry(payment_name)

    def test_mutation_6217_customer_payment_without_rows(self):
        """Test mutation 6217 - Customer payment without row details."""
        mutation = self.mutations[6217]
        
        # Create test customer (Enhanced Test Factory handles cleanup automatically)
        if not DocumentExistenceValidator.check_document_exists("Customer", "CUST-123"):
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Test Customer 123"
            customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name") or "All Customer Groups"
            territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="name")
            if territory:
                customer.territory = territory
            customer.save()
            customer.rename("CUST-123")
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.received_amount, 500.00)
        # Handler resolves the eBoekhouden relation to its own customer name.
        self.assertIn("CUST-123", pe.party)
        self.assertEqual(pe.reference_no, "SI-2024-0456")
        
        # Should still use Triodos bank
        self.assertIn("Triodos", pe.paid_to)

        # Remove the committed Payment Entry so the fixed mutation id 6217 does not
        # make a rerun short-circuit on the dedup early-return.
        self._cleanup_committed_payment_entry(payment_name)

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
        """Real end-to-end allocation: payment -> two Purchase Invoices -> reconciled.

        This is the live proof that the handler's allocation path actually links a
        payment to its invoices (not just parses invoice numbers). It exercises the
        "Allocating N row(s)" branch in PaymentEntryHandler._allocate_to_invoices and
        asserts the resulting Payment Entry carries the expected references.

        Three things are required for the handler to allocate against real ERPNext
        invoices, each addressing a concrete blocker found while writing this test:

        1. The supplier must carry the same ``eboekhouden_relation_code`` that the
           mutation's ``relationId`` uses. The handler resolves the party through
           EBoekhoudenPartyResolver, which (with no live E-Boekhouden API in the test
           env) matches on ``eboekhouden_relation_code``. Without it the resolver
           creates a *different* provisional supplier, so the invoices -- linked to
           our supplier -- would never match the resolved party in the handler's
           exact-name lookup (`_find_invoice_by_number` Strategy 3).

        2. ``invoiceNumber`` must equal the Purchase Invoice ``name`` exactly, because
           Strategy 3 does an exact ``name`` match (verified at
           payment_entry_handler.py:1135). The default ACC-PINV naming series keeps
           these well within the Payment Entry title's 140-char limit.

        3. The invoices need ``disable_rounded_total = 1``. The test company rounds
           grand totals, so a 60.50 invoice would otherwise have an *outstanding* of
           60.00 while the mutation row allocates 60.50 -- ERPNext then rejects with
           "Allocated Amount cannot be greater than outstanding amount" and the
           handler silently falls back to an *unallocated* payment, defeating the
           point of this test. Disabling rounding keeps outstanding == grand_total so
           the real allocation succeeds.
        """
        # Supplier carrying the relation code the mutation will reference, so the
        # party resolver returns THIS supplier (the one the invoices are linked to).
        relation_code = "TEST-EB-REL-5473"
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = "Test Supplier for 5473"
        supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name")
        if supplier_group:
            supplier.supplier_group = supplier_group
        supplier.eboekhouden_relation_code = relation_code
        supplier.save()

        item_code = frappe.db.get_value("Item", {"is_stock_item": 0}, "name") or "Service"

        def _make_purchase_invoice(rate, posting_date):
            pi = frappe.new_doc("Purchase Invoice")
            pi.supplier = supplier.name
            pi.company = self.company
            pi.posting_date = posting_date
            # Keep outstanding == grand_total so the row amount can be fully allocated
            # (the test company otherwise rounds grand totals down).
            pi.disable_rounded_total = 1
            pi.append("items", {"item_code": item_code, "qty": 1, "rate": rate})
            pi.save()
            pi.submit()
            pi.reload()
            return pi

        pi1 = _make_purchase_invoice(60.50, "2024-12-01")
        pi2 = _make_purchase_invoice(61.29, "2024-12-05")

        # Sanity: rounding really is disabled so the full row amount can allocate.
        self.assertEqual(pi1.outstanding_amount, 60.50)
        self.assertEqual(pi2.outstanding_amount, 61.29)

        # Mutation referencing the real invoices by exact name. The handler dedupes
        # on mutation id via a COMMITTED atomic operation (the Payment Entry it creates
        # is persisted, not rolled back with the test transaction), so the id must be
        # unique per run -- a fixed id would make a rerun short-circuit on the stale
        # payment from a previous run instead of allocating against this run's fresh
        # invoices. Derive a run-unique id from a fresh hash so each run allocates anew.
        unique_mutation_id = 900000000 + (int(frappe.generate_hash(length=8), 16) % 99999999)
        mutation = self.mutations[5473].copy()
        mutation['id'] = unique_mutation_id
        mutation['relationId'] = relation_code  # resolver matches our supplier by code
        mutation['invoiceNumber'] = f"{pi1.name},{pi2.name}"

        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)

        # Verify payment and allocations
        self.assertIsNotNone(payment_name)

        debug = " ".join(self.handler.debug_log)
        # Hard-prove the real allocation branch ran (not the parse-only path).
        self.assertIn("Found invoice", debug)
        self.assertIn("via exact name match", debug)
        self.assertIn("Allocating 2 row(s)", debug)
        # And prove we did NOT silently fall back to an unallocated payment.
        self.assertNotIn("No matching invoices found for allocation", debug)
        self.assertNotIn("Created unallocated Payment Entry", debug)

        pe = frappe.get_doc("Payment Entry", payment_name)
        # Payment Entry was actually submitted (reconciliation is real, not a draft).
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(len(pe.references), 2)

        # References point at the real invoices with the expected allocations.
        allocations = {ref.reference_name: ref.allocated_amount for ref in pe.references}
        self.assertEqual(allocations.get(pi1.name), 60.50)
        self.assertEqual(allocations.get(pi2.name), 61.29)
        for ref in pe.references:
            self.assertEqual(ref.reference_doctype, "Purchase Invoice")

        # The payment fully reconciled both invoices (outstanding now zero).
        pi1.reload()
        pi2.reload()
        self.assertEqual(pi1.outstanding_amount, 0.0)
        self.assertEqual(pi2.outstanding_amount, 0.0)

        # The handler COMMITS the Payment Entry (atomic_migration_operation), so the
        # Enhanced Test Factory transaction rollback will not remove it. Cancel and
        # delete it explicitly to keep the test idempotent and avoid leaking a
        # submitted PE (and its GL entries) into the test database.
        self._cleanup_committed_payment_entry(payment_name)

    @staticmethod
    def _cleanup_committed_payment_entry(payment_name):
        """Cancel + delete a committed Payment Entry so reruns stay clean."""
        if not payment_name or not frappe.db.exists("Payment Entry", payment_name):
            return
        pe = frappe.get_doc("Payment Entry", payment_name)
        if pe.docstatus == 1:
            pe.cancel()
        frappe.delete_doc("Payment Entry", payment_name, force=True)
        frappe.db.commit()
    
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





