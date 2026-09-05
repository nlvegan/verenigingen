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
from frappe.utils import add_days, nowdate

from verenigingen.e_boekhouden.utils.payment_processing import PaymentEntryHandler
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class TestPaymentEntryHandler(EnhancedTestCase):
    """Test enhanced payment entry handler functionality."""
    
    # Ledger IDs used by the payment mutations in these tests.
    BANK_LEDGER_ID = 10440  # Triodos-style bank ledger
    UNMAPPED_LEDGER_ID = 88888  # deliberately has no mapping

    @classmethod
    def setUpClass(cls):
        """Set up test data.

        These tests drive the e-Boekhouden PaymentEntryHandler, which resolves
        a mutation's ledgerId to a Bank/Cash GL account via E-Boekhouden Ledger
        Mapping and fails hard when no mapping exists. A fresh test site has none
        of that infrastructure, so seed an EUR company with a Bank account and a
        ledger mapping for the bank ledger the mutations use.
        """
        super().setUpClass()

        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.bank_account = cls._ensure_bank_account(cls.company)
        cls._ensure_ledger_mapping(cls.BANK_LEDGER_ID, "TRIODOS-TEST", cls.bank_account)

    # Account autonames account_name + " - " + abbr, and this must be the
    # existence-check key -- the shared EUR test company routinely already
    # has other leaf Bank accounts (created by sibling suites), and querying
    # by "any leaf Bank account for the company" adopts one of those instead
    # of owning "Test Bank Triodos" by name (#308). The ledger mapping this
    # class builds is pinned to a Triodos-named ledger code, so adopting an
    # unrelated account silently mismatches it.
    OWN_ACCOUNT_NAME = "Test Bank Triodos"

    @classmethod
    def _ensure_bank_account(cls, company):
        """Return a Bank-type GL account for the company, creating one if needed.

        The handler also needs a Bank Account *master* (the doctype that links a
        Bank to the GL account) to build the Payment Entry, so create that too.
        """
        gl_account = frappe.db.get_value(
            "Account", {"account_name": cls.OWN_ACCOUNT_NAME, "company": company}, "name"
        )
        if not gl_account:
            parent = frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 1, "account_type": "Bank"},
                "name",
            ) or frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 1, "root_type": "Asset"},
                "name",
            )
            account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": cls.OWN_ACCOUNT_NAME,
                    "parent_account": parent,
                    "company": company,
                    "account_type": "Bank",
                    "is_group": 0,
                }
            )
            account.insert(ignore_permissions=True)
            gl_account = account.name

        cls._ensure_bank_account_master(company, gl_account)
        return gl_account

    # Bank Account autonames account_name + " - " + bank; guarding on
    # {"account": gl_account, "company": company} instead can miss a row that
    # already carries this literal name under a different `account`, and then
    # collide on insert with a DuplicateEntryError -- same guard-key-vs-
    # autoname-key gap as _ensure_bank_account above (#308).
    OWN_BANK_ACCOUNT_NAME = "Test Bank Triodos Account"

    @classmethod
    def _ensure_bank_account_master(cls, company, gl_account):
        """Create a Bank Account master linking a Bank to the GL account."""
        bank_name = "Test Bank (Triodos)"
        if frappe.db.exists("Bank Account", {"account_name": cls.OWN_BANK_ACCOUNT_NAME, "bank": bank_name}):
            return
        if not frappe.db.exists("Bank", bank_name):
            frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": cls.OWN_BANK_ACCOUNT_NAME,
                "bank": bank_name,
                "account": gl_account,
                "company": company,
                "is_company_account": 1,
            }
        ).insert(ignore_permissions=True)

    @classmethod
    def _ensure_ledger_mapping(cls, ledger_id, ledger_code, erpnext_account):
        """Create an E-Boekhouden Ledger Mapping linking ledger_id to a GL account."""
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}):
            return
        mapping = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Ledger Mapping",
                "ledger_id": ledger_id,
                "ledger_code": ledger_code,
                "ledger_name": f"Test Ledger {ledger_id}",
                "erpnext_account": erpnext_account,
            }
        )
        mapping.insert(ignore_permissions=True)


    def setUp(self):
        """Set up for each test."""
        super().setUp()
        self.handler = PaymentEntryHandler(self.company)
        
    def tearDown(self):
        """Clean up handled by Enhanced Test Factory rollback."""
        super().tearDown()
        # Enhanced Test Factory handles cleanup automatically
    
    def test_ensure_bank_account_owns_its_row_not_any_leaf_bank_account(self):
        """A pre-existing leaf Bank account for the (intentionally shared) EUR
        test company, created by some other suite, must not be adopted (#308).
        Before the fix, _ensure_bank_account resolved by "any leaf Bank
        account for the company", so whichever one a co-tenant suite created
        first won -- silently mismatching this class's Triodos ledger mapping."""
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "account_type": "Bank"}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}, "name"
        )
        neighbour = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": f"Some Other Suite's Bank {frappe.generate_hash()[:6]}",
                "parent_account": parent,
                "company": self.company,
                "account_type": "Bank",
                "is_group": 0,
            }
        ).insert(ignore_permissions=True)
        self.created_records.append(("Account", neighbour.name))

        resolved = self._ensure_bank_account(self.company)

        self.assertEqual(
            resolved,
            self.bank_account,
            "must resolve to its own owned account, not a neighbour's leaf Bank account",
        )

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
        # Seed a mapping for ledger 99999 -> the seeded Bank account.
        self._ensure_ledger_mapping(99999, "TEST-BANK", self.bank_account)

        # Test determination
        result = self.handler._determine_bank_account(99999, "Receive")
        self.assertIsNotNone(result)
        self.assertNotIn("Kas", result)  # Should not be cash account

        # Enhanced Test Factory handles cleanup automatically

    def test_bank_account_fallback(self):
        """An unmapped ledger fails hard (no silent fallback).

        The handler deliberately raises when a ledgerId has no Bank/Cash mapping
        and no description pattern to fall back on, rather than guessing an account
        (which would post payments to the wrong ledger). Verify that contract.
        """
        with self.assertRaises(frappe.ValidationError):
            self.handler._determine_bank_account(self.UNMAPPED_LEDGER_ID, "Receive")
    
    def test_single_invoice_payment(self):
        """Test payment creation for single invoice."""
        import time

        # Use unique mutation ID to avoid conflicts
        unique_mutation_id = int(time.time() * 1000) % 10000000 + 1000

        mutation = {
            "id": unique_mutation_id,
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
        self.assertEqual(pe.eboekhouden_mutation_nr, str(unique_mutation_id))

        # Enhanced Test Factory handles cleanup automatically
    
    def test_multi_invoice_payment_with_rows(self):
        """Test payment with multiple invoices and row allocations."""
        import time

        # Use a unique supplier name for this test
        supplier_name = "Test Supplier for Payment Handler"
        # Use unique mutation ID to avoid conflicts with previous test runs
        unique_mutation_id = int(time.time() * 1000) % 10000000

        mutation = {
            "id": unique_mutation_id,
            "type": 4,  # Supplier payment
            "date": nowdate(),
            "amount": 121.79,
            "ledgerId": 10440,
            "relationId": supplier_name,
            "invoiceNumber": "TEST-PINV-001,TEST-PINV-002",
            "description": "TEST-PAYMENT Multi-invoice with rows",
            "rows": [
                {"ledgerId": 13201853, "amount": -60.50},
                {"ledgerId": 13201853, "amount": -61.29}
            ]
        }

        # Create test supplier if it doesn't exist
        if not DocumentExistenceValidator.check_document_exists("Supplier", supplier_name):
            supplier = frappe.new_doc("Supplier")
            supplier.supplier_name = supplier_name
            supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name")
            if supplier_group:
                supplier.supplier_group = supplier_group
            supplier.insert(ignore_if_duplicate=True)
        
        # Process payment
        payment_name = self.handler.process_payment_mutation(mutation)
        
        # Verify payment
        self.assertIsNotNone(payment_name)
        
        pe = frappe.get_doc("Payment Entry", payment_name)
        self.assertEqual(pe.payment_type, "Pay")
        self.assertEqual(pe.paid_amount, 121.79)
        self.assertEqual(pe.party_type, "Supplier")
        # Handler may auto-create supplier with different naming convention
        self.assertIn(supplier_name, pe.party)

        # Check debug log for row allocation
        debug_output = " ".join(self.handler.debug_log)
        self.assertIn("Found 2 invoice(s)", debug_output)
        # Check for row processing (message format: "Checking X rows")
        self.assertIn("rows", debug_output.lower())
        
        # Enhanced Test Factory handles cleanup automatically
    
    def test_payment_without_party_returns_none(self):
        """A type 3/4 payment with no relationId declines to create a PE.

        PaymentEntryHandler._get_or_create_party returns None for a falsy
        relation_id, and process_payment_mutation then returns None at the
        "Could not determine party" guard. Customer/supplier payments inherently
        need a party; party-less money movements are types 5/6, handled
        elsewhere as Journal Entries. This pins that contract instead of
        skipping when (correctly) no Payment Entry is produced.
        """
        import time

        unique_mutation_id = int(time.time() * 1000) % 10000000 + 2000

        mutation = {
            "id": unique_mutation_id,
            "type": 3,
            "date": nowdate(),
            "amount": 50.00,
            "ledgerId": self.BANK_LEDGER_ID,
            "description": "TEST-PAYMENT Anonymous payment (no relationId)",
        }

        payment_name = self.handler.process_payment_mutation(mutation)

        # No party => handler returns None and creates no Payment Entry.
        self.assertIsNone(payment_name)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"eboekhouden_mutation_nr": str(unique_mutation_id)}),
            "no Payment Entry should be persisted for a party-less payment",
        )
        # The decline reason is the missing party, not some unrelated failure.
        self.assertIn("party", " ".join(self.handler.debug_log).lower())

        # Enhanced Test Factory handles cleanup automatically
    
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
        import time

        # Use unique mutation ID
        unique_mutation_id = int(time.time() * 1000) % 10000000 + 3000

        # Process a simple mutation
        mutation = {
            "id": unique_mutation_id,
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
        self.assertIn(f"Processing payment mutation {unique_mutation_id}", " ".join(debug_log))
        self.assertIn("Found 0 invoice(s)", " ".join(debug_log))


def run_tests():
    """Run the test suite."""
    unittest.main(module=__name__, exit=False)


if __name__ == "__main__":
    run_tests()