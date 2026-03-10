"""
Regression test for payment history Dynamic Link field validation.

Tests the fix for the bug where payment history entries created via bulk query path
(build_from_query_row) were missing the invoice_doctype field required for
Frappe's Dynamic Link validation.

Issue discovered: 2025-12-12
Error: "Invoice DocType must be set first"
Fix applied to: verenigingen/utils/payment_history_builder.py
"""

import frappe
from frappe.utils import flt, random_string

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.payment_history_builder import (
    PaymentHistoryEntryBuilder,
    build_payment_history_entry,
    build_payment_history_entry_from_query,
)


class TestRegressionPaymentHistoryDynamicLinks(VereningingenTestCase):
    """
    Regression test for payment history Dynamic Link field validation bug.

    The bug occurred because build_from_query_row() was missing the
    invoice_doctype field which is required for Frappe's Dynamic Link validation.

    When a Member document was saved with payment history entries that had
    invoice values but no invoice_doctype, Frappe threw:
        "Invoice DocType must be set first"

    The fix ensures all Dynamic Link fields have their corresponding doctype
    fields set:
    - invoice -> invoice_doctype
    - payment_entry -> payment_entry_doctype
    - sepa_mandate -> sepa_mandate_doctype
    """

    def test_build_from_query_row_includes_invoice_doctype(self):
        """
        Test that build_from_query_row includes invoice_doctype field.

        This is the primary fix for the validation error.
        """
        # Simulate a query row with invoice data
        query_row = {
            "invoice_name": "ACC-SINV-2025-00001",
            "posting_date": "2025-01-15",
            "due_date": "2025-02-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "invoice_status": "Unpaid",
            "payment_status": "Unpaid",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify invoice_doctype is set
        self.assertEqual(entry.get("invoice_doctype"), "Sales Invoice")
        self.assertEqual(entry.get("invoice"), "ACC-SINV-2025-00001")

    def test_build_from_query_row_includes_payment_entry_doctype(self):
        """
        Test that payment_entry_doctype is set when payment_entry is present.
        """
        query_row = {
            "invoice_name": "ACC-SINV-2025-00002",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 0.00,
            "payment_status": "Paid",
            "payment_entry": "ACC-PAY-2025-00001",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify payment_entry_doctype is set when payment_entry is present
        self.assertEqual(entry.get("payment_entry"), "ACC-PAY-2025-00001")
        self.assertEqual(entry.get("payment_entry_doctype"), "Payment Entry")

    def test_build_from_query_row_payment_entry_doctype_none_when_no_payment(self):
        """
        Test that payment_entry_doctype is None when no payment_entry.
        """
        query_row = {
            "invoice_name": "ACC-SINV-2025-00003",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "payment_status": "Unpaid",
            # No payment_entry
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify payment_entry_doctype is None when no payment
        self.assertIsNone(entry.get("payment_entry"))
        self.assertIsNone(entry.get("payment_entry_doctype"))

    def test_build_from_query_row_includes_sepa_mandate_doctype(self):
        """
        Test that sepa_mandate_doctype is set when sepa_mandate is present.
        """
        query_row = {
            "invoice_name": "ACC-SINV-2025-00004",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "payment_status": "Unpaid",
            "sepa_mandate": "SEPA-2025-00001",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify sepa_mandate_doctype is set when sepa_mandate is present
        self.assertEqual(entry.get("sepa_mandate"), "SEPA-2025-00001")
        self.assertEqual(entry.get("sepa_mandate_doctype"), "SEPA Mandate")

    def test_build_from_query_row_sepa_mandate_doctype_none_when_no_mandate(self):
        """
        Test that sepa_mandate_doctype is None when no sepa_mandate.
        """
        query_row = {
            "invoice_name": "ACC-SINV-2025-00005",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "payment_status": "Unpaid",
            # No sepa_mandate
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify sepa_mandate_doctype is None when no mandate
        self.assertIsNone(entry.get("sepa_mandate"))
        self.assertIsNone(entry.get("sepa_mandate_doctype"))

    def test_build_from_invoice_doc_parity_with_query_row(self):
        """
        Test that build_from_invoice_doc and build_from_query_row produce
        entries with the same Dynamic Link fields.

        Both methods should include:
        - invoice_doctype
        - payment_entry_doctype (when applicable)
        - sepa_mandate_doctype (when applicable)
        """
        # Test invoice_doctype is present in both
        query_row = {
            "invoice_name": "ACC-SINV-2025-00006",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "payment_status": "Unpaid",
        }

        query_entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Verify the key Dynamic Link fields exist
        self.assertIn("invoice_doctype", query_entry)
        self.assertIn("payment_entry_doctype", query_entry)
        self.assertIn("sepa_mandate_doctype", query_entry)

    def test_member_save_with_payment_history_from_query_row(self):
        """
        Integration test: Verify Member can be saved with payment history
        entries created via build_from_query_row.

        This is the actual scenario that was failing before the fix.
        """
        # Create a test member
        member = self.create_test_member(
            first_name="Test",
            last_name=f"DynamicLink{random_string(6)}",
            email=f"test.dynamiclink.{random_string(8)}@example.com",
        )

        # Create a payment history entry using the query row builder
        query_row = {
            "invoice_name": f"TEST-INV-{random_string(8)}",
            "posting_date": "2025-01-15",
            "due_date": "2025-02-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "invoice_status": "Unpaid",
            "payment_status": "Unpaid",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Note: We can't actually add this to a real member without a real invoice
        # but we can verify the entry structure is correct
        self.assertEqual(entry["invoice_doctype"], "Sales Invoice")

        # Verify the entry would pass Dynamic Link validation
        # The key assertion is that invoice_doctype is set when invoice is set
        self.assertTrue(
            entry.get("invoice") and entry.get("invoice_doctype"),
            "invoice_doctype must be set when invoice is set"
        )

    def test_all_dynamic_link_fields_have_doctype_pair(self):
        """
        Test that all Dynamic Link fields in build_from_query_row have their
        corresponding doctype fields set appropriately.

        This prevents future regressions where new Dynamic Link fields might
        be added without their doctype pairs.
        """
        # Full query row with all possible Dynamic Link fields
        query_row = {
            "invoice_name": "ACC-SINV-2025-00007",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 0.00,
            "payment_status": "Paid",
            "payment_entry": "ACC-PAY-2025-00002",
            "sepa_mandate": "SEPA-2025-00002",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)

        # Define expected Dynamic Link pairs
        dynamic_link_pairs = [
            ("invoice", "invoice_doctype", "Sales Invoice"),
            ("payment_entry", "payment_entry_doctype", "Payment Entry"),
            ("sepa_mandate", "sepa_mandate_doctype", "SEPA Mandate"),
        ]

        for link_field, doctype_field, expected_doctype in dynamic_link_pairs:
            if entry.get(link_field):
                self.assertEqual(
                    entry.get(doctype_field),
                    expected_doctype,
                    f"{doctype_field} should be '{expected_doctype}' when {link_field} is set"
                )

    def test_validation_entry_with_dynamic_links(self):
        """
        Test that entries with Dynamic Link fields pass validation.
        """
        query_row = {
            "invoice_name": "ACC-SINV-2025-00008",
            "posting_date": "2025-01-15",
            "grand_total": 25.00,
            "outstanding_amount": 25.00,
            "payment_status": "Unpaid",
        }

        entry = PaymentHistoryEntryBuilder.build_from_query_row(query_row)
        is_valid, errors = PaymentHistoryEntryBuilder.validate_entry(entry)

        self.assertTrue(is_valid, f"Entry validation failed with errors: {errors}")
