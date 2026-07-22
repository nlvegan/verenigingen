# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for PaymentHistoryService and PaymentCoverageService.

The existing backend/unit/services/test_payment_history_service.py is heavily
mock-based and never exercises the real load path against a member with real
Sales Invoices / Payment Entries. This module drives the actual query-optimized
loaders end-to-end and asserts the REAL child-table rows that land on
member.payment_history (amounts, payment_status, reconciliation, transaction
type, unreconciled-payment handling).

Covered branches:
- load_payment_history_batched: invoices found -> entry built; reconciled
  payment marks status Paid + reconciled=1; unpaid invoice marks Unpaid;
  payment_history is invoice-only -- a standalone Payment Entry with no
  invoice allocation never produces its own row (no "Unreconciled Payment" /
  "Donation Payment" phantom rows; production has produced zero of these
  ever, since the real flow is always SI first -> PE at reconciliation).
- refresh_financial_history: atomic refresh returns stats; cleanup removes
  rows referencing deleted invoices.
- build_payment_history_entry: builds from a real Sales Invoice document.
- PaymentCoverageService.get_coverage_for_invoice fallback to invoice cache.
"""

import frappe
from frappe.utils import today

from verenigingen.services.member.payment.payment_coverage_service import (
    CoveragePeriod,
    get_payment_coverage_service,
)
from verenigingen.services.member.payment.payment_history_service import (
    get_payment_history_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentHistoryServiceRealDB(EnhancedTestCase):
    """Exercise payment history loading against real invoices/payments."""

    def setUp(self):
        super().setUp()
        self.service = get_payment_history_service()
        self.member = self.create_test_member(first_name="Pay", last_name="Hist")
        self.link_member_to_customer(self.member)
        self.member.reload()

    # ---- helpers (allowed to do privileged setup) ----

    def _make_submitted_invoice(self, **kwargs):
        unique_series = f"TPHS-{frappe.generate_hash(length=8).upper()}-.#####"
        invoice = self.create_test_sales_invoice(self.member.name, naming_series=unique_series, **kwargs)
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _pay_invoice(self, invoice, reference_no="TEST-PHS-PAY"):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def _entry_for_invoice(self, invoice_name):
        rows = [r for r in (self.member.payment_history or []) if r.invoice == invoice_name]
        return rows[0] if rows else None

    # ---- load_payment_history_batched ----

    def test_load_with_no_customer_skips(self):
        """A member without a customer short-circuits with skipped=True."""
        bare = self.create_test_member(first_name="No", last_name="Customer")
        # create_test_member auto-creates a customer; null it for this branch.
        bare.customer = None
        result = self.service.load_payment_history_batched(bare)
        self.assertTrue(result.success)
        self.assertTrue(result.data["skipped"])
        self.assertEqual(result.data["reason"], "no_customer")

    def test_load_no_invoices_returns_zero(self):
        """Customer with zero invoices loads zero entries."""
        result = self.service.load_payment_history_batched(self.member)
        self.assertTrue(result.success)
        self.assertEqual(result.data["entries_loaded"], 0)
        self.assertEqual(result.data["invoices_found"], 0)

    def test_load_unpaid_invoice_builds_unpaid_row(self):
        """A submitted, unpaid invoice yields one Unpaid history row with the grand total."""
        invoice = self._make_submitted_invoice()
        result = self.service.load_payment_history_batched(self.member)

        self.assertTrue(result.success)
        self.assertEqual(result.data["invoices_processed"], 1)
        row = self._entry_for_invoice(invoice.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.payment_status, "Unpaid")
        self.assertEqual(float(row.amount), float(invoice.grand_total))
        self.assertEqual(row.reconciled, 0)
        self.assertEqual(row.transaction_type, "Regular Invoice")

    def test_load_paid_invoice_builds_reconciled_row(self):
        """A paid invoice yields a Paid, reconciled row carrying the payment entry."""
        invoice = self._make_submitted_invoice()
        pe = self._pay_invoice(invoice)

        result = self.service.load_payment_history_batched(self.member)
        self.assertTrue(result.success)

        row = self._entry_for_invoice(invoice.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.payment_status, "Paid")
        self.assertEqual(row.reconciled, 1)
        self.assertEqual(row.payment_entry, pe.name)
        self.assertGreater(float(row.paid_amount), 0.0)

    def test_membership_invoice_transaction_type(self):
        """is_membership_invoice flag classifies the row as Membership Invoice."""
        invoice = self._make_submitted_invoice(is_membership_invoice=1)
        self.service.load_payment_history_batched(self.member)
        row = self._entry_for_invoice(invoice.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.transaction_type, "Membership Invoice")

    def test_membership_invoice_without_link_classified_by_boolean(self):
        """is_membership_invoice (boolean) classifies the row even with no membership link."""
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        # No membership link set on the invoice.
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        rows = [r for r in self.member.payment_history if r.invoice == inv.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].transaction_type, "Membership Invoice")
        self.assertIsNone(rows[0].reference_name)

    def test_membership_reference_persists_and_flows_to_history(self):
        """With the membership field present, a linked membership becomes the row reference."""
        membership = self.create_test_membership(member=self.member.name)
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        frappe.db.set_value("Sales Invoice", inv.name, "membership", membership.name)
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        row = next(r for r in self.member.payment_history if r.invoice == inv.name)
        self.assertEqual(row.transaction_type, "Membership Invoice")
        self.assertEqual(row.reference_doctype, "Membership")
        self.assertEqual(row.reference_name, membership.name)

    def _make_standalone_payment(self, reference_no="STANDALONE-PHS", amount=17.0):
        """Build a submitted, customer-linked Payment Entry with no invoice allocation.

        Derives the bank/receivable accounts from a throwaway invoice-based
        Payment Entry so the accounts are valid for this company, then strips
        the invoice reference to leave an unallocated (unreconciled) payment.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        seed_invoice = self._make_submitted_invoice()
        template = get_payment_entry("Sales Invoice", seed_invoice.name)

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.party_type = "Customer"
        pe.party = self.member.customer
        pe.company = template.company
        pe.paid_from = template.paid_from
        pe.paid_to = template.paid_to
        pe.paid_from_account_currency = template.paid_from_account_currency
        pe.paid_to_account_currency = template.paid_to_account_currency
        pe.posting_date = today()
        pe.paid_amount = amount
        pe.received_amount = amount
        pe.source_exchange_rate = 1.0
        pe.target_exchange_rate = 1.0
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def test_standalone_payment_produces_no_row(self):
        """payment_history is invoice-only: a Payment Entry with no invoice ref
        (previously turned into a standalone "Unreconciled Payment" row) now adds
        nothing to the child table."""
        pe = self._make_standalone_payment()

        result = self.service.load_payment_history_batched(self.member)
        self.assertTrue(result.success)
        self.assertNotIn("unreconciled_payments", result.data)

        matching = [r for r in self.member.payment_history if r.payment_entry == pe.name]
        self.assertEqual(matching, [])
        types = {r.transaction_type for r in self.member.payment_history}
        self.assertNotIn("Unreconciled Payment", types)
        self.assertNotIn("Donation Payment", types)

    def test_no_pe_based_rows_are_emitted(self):
        """payment_history is invoice-only; standalone Payment Entries never add rows."""
        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self._pay_invoice(inv)  # creates a PE referencing the SI
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        types = {r.transaction_type for r in self.member.payment_history}
        self.assertNotIn("Unreconciled Payment", types)
        self.assertNotIn("Donation Payment", types)
        # The reconciling PE marks the invoice row Paid, it does not add its own row.
        self.assertTrue(all(r.invoice for r in self.member.payment_history))
        self.assertEqual(len(self.member.payment_history), 1)

    # ---- refresh_financial_history ----

    def test_refresh_financial_history_returns_stats(self):
        """refresh_financial_history runs cleanup + atomic refresh and reports counts."""
        self._make_submitted_invoice()
        result = self.service.refresh_financial_history(self.member)
        self.assertTrue(result.success)
        self.assertIn("payment_history_count", result.data)
        self.assertEqual(result.data["method"], "atomic_updates_with_cleanup")
        self.assertEqual(result.data["removed_entries"], 0)

    def test_refresh_cleans_broken_invoice_row(self):
        """A history row pointing at a non-existent invoice is removed by cleanup."""
        # Seed a row referencing an invoice that does not exist.
        self.member.append(
            "payment_history",
            {
                "invoice": "SINV-DOES-NOT-EXIST-PHS",
                "posting_date": today(),
                "amount": 5.0,
                "outstanding_amount": 5.0,
                "payment_status": "Unpaid",
                "transaction_type": "Regular Invoice",
            },
        )
        cleanup = self.service._cleanup_broken_history_entries(self.member)
        self.assertEqual(cleanup["removed"], 1)
        remaining = [r.invoice for r in (self.member.payment_history or [])]
        self.assertNotIn("SINV-DOES-NOT-EXIST-PHS", remaining)

    # ---- build_payment_history_entry ----

    def test_build_payment_history_entry_from_real_invoice(self):
        """Building an entry from a real Sales Invoice returns invoice + amount fields."""
        invoice = self._make_submitted_invoice()
        invoice.reload()
        entry = self.service.build_payment_history_entry(invoice, member_doc=self.member)
        self.assertEqual(entry["invoice"], invoice.name)
        self.assertEqual(float(entry["amount"]), float(invoice.grand_total))

    # ---- get_financial_summary ----

    def test_financial_summary_has_no_phantom_counters(self):
        """get_financial_summary no longer advertises the removed phantom-row
        counters ("donations" / "unreconciled_payments"), since payment_history
        is invoice-only and those transaction types are never produced."""
        self._make_submitted_invoice(is_membership_invoice=1)
        self.member.reload()
        self.service.load_payment_history_batched(self.member)
        summary = self.member.get_financial_summary()
        self.assertNotIn("donations", summary)
        self.assertNotIn("unreconciled_payments", summary)
        self.assertIn("membership_invoices", summary)

    # ---- background_jobs delegation (Task 4) ----

    def test_refresh_optimized_uses_service_invoice_only(self):
        """refresh_member_financial_history_optimized delegates row construction to
        the service -- the persisted payment_history is invoice-only, with no
        drifted "Unreconciled Payment" rows from the old inline rebuild.

        A standalone (unallocated) Payment Entry is deliberately added alongside
        the invoice: the old inline `load_payment_history_batch_optimized` body
        turned exactly this shape into a phantom "Unreconciled Payment" row, so
        without it this test would pass under both the old and new code and
        would not actually catch a regression back to the inline rebuild.
        """
        from verenigingen.utils.background_jobs import refresh_member_financial_history_optimized

        inv = self._make_submitted_invoice(is_membership_invoice=1)
        self._make_standalone_payment()
        self.member.reload()
        result = refresh_member_financial_history_optimized(self.member)
        self.assertEqual(result["status"], "completed")
        self.member.reload()
        types = {r.transaction_type for r in self.member.payment_history}
        self.assertNotIn("Unreconciled Payment", types)
        self.assertTrue(any(r.invoice == inv.name for r in self.member.payment_history))


class TestPaymentCoverageServiceRealDB(EnhancedTestCase):
    """Real-DB coverage extraction priority/fallback."""

    def setUp(self):
        super().setUp()
        self.service = get_payment_coverage_service()

    def test_get_coverage_for_invoice_falls_back_to_invoice_cache(self):
        """With no schedule link, coverage comes from the invoice's cached custom fields."""
        invoice_data = frappe._dict(
            {
                "custom_coverage_start_date": "2024-01-01",
                "custom_coverage_end_date": "2024-12-31",
            }
        )
        coverage = self.service.get_coverage_for_invoice(
            "MEM-NONEXISTENT-COV", "INV-NONEXISTENT-COV", invoice_data
        )
        self.assertEqual(coverage.source, "invoice_cache")
        self.assertEqual(str(coverage.start_date), "2024-01-01")

    def test_get_coverage_for_invoice_returns_none_when_nothing(self):
        """No schedule and no invoice data yields an empty 'none' coverage."""
        coverage = self.service.get_coverage_for_invoice("MEM-NONEXISTENT-COV", "INV-NONEXISTENT-COV", None)
        self.assertIsInstance(coverage, CoveragePeriod)
        self.assertEqual(coverage.source, "none")
        self.assertFalse(coverage.is_valid)
