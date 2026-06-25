# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for MemberHistoryUpdateService.

Covers the orchestration and the standalone row-building/diffing helpers that
the existing suite did not exercise:

- incremental_update_history_tables: full rebuild against a member with real
  Sales Invoices + a reconciled Payment Entry; returns OperationResult.ok and
  populates payment_history rows.
- _prefetch_payment_references: builds the reference cache from real refs.
- _update_invoice_payment_history / _update_dues_payment_history: real rows.
- _remove_stale_history_rows / _row_needs_update / _resolve_payment_entry /
  _build_dues_payment_row / _build_invoice_history_row: pure logic on real data.
- refresh_fee_change_history: rebuilds fee_change_history from a real dues
  schedule and returns the documented OperationResult shape.
"""

import frappe
from frappe.utils import today

from verenigingen.services.member.history.member_history_update_service import (
    MemberHistoryUpdateService,
    PaymentReferenceCache,
    get_member_history_update_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberHistoryUpdateServiceRealDB(EnhancedTestCase):
    """Exercise the history orchestration + helpers against real documents."""

    def setUp(self):
        super().setUp()
        self.service = get_member_history_update_service()
        self.member = self.create_test_member(first_name="HistUpd", last_name="Svc")
        self.link_member_to_customer(self.member)
        self.member.reload()

    # ---- helpers (privileged setup) ----

    def _make_submitted_invoice(self, **kwargs):
        unique_series = f"THUS-{frappe.generate_hash(length=8).upper()}-.#####"
        invoice = self.create_test_sales_invoice(self.member.name, naming_series=unique_series, **kwargs)
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _pay_invoice(self, invoice, reference_no="THUS-PAY"):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        return pe

    # ---- singleton / construction ----

    def test_service_singleton_and_name(self):
        self.assertEqual(self.service.service_name, "MemberHistoryUpdateService")

    # ---- _prefetch_payment_references ----

    def test_prefetch_no_customer_returns_empty_cache(self):
        """A member with no customer yields an empty reference cache."""
        bare = self.create_test_member(first_name="Bare", last_name="NoCust")
        bare.customer = None
        cache = self.service._prefetch_payment_references(bare)
        self.assertIsInstance(cache, PaymentReferenceCache)
        self.assertEqual(cache.member_invoice_names, [])

    def test_prefetch_collects_reconciled_payment(self):
        """Prefetch finds the invoice and its reconciled payment entry."""
        invoice = self._make_submitted_invoice()
        pe = self._pay_invoice(invoice)

        cache = self.service._prefetch_payment_references(self.member)
        self.assertIn(invoice.name, cache.member_invoice_names)
        self.assertIn(pe.name, cache.reconciled_payment_entries)
        self.assertIn(invoice.name, cache.payment_refs_by_invoice)

    # ---- _update_invoice_payment_history ----

    def test_update_invoice_history_adds_row(self):
        """Invoice history update appends a reconciled row for a paid invoice."""
        invoice = self._make_submitted_invoice()
        pe = self._pay_invoice(invoice)
        cache = self.service._prefetch_payment_references(self.member)

        changes = self.service._update_invoice_payment_history(self.member, cache)
        self.assertGreaterEqual(changes, 1)

        rows = [r for r in self.member.payment_history if r.invoice == invoice.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reconciled, 1)
        self.assertEqual(rows[0].payment_entry, pe.name)
        self.assertEqual(rows[0].payment_status, "Paid")

    def test_update_invoice_history_no_customer_returns_zero(self):
        """No customer -> invoice history update is a no-op returning 0."""
        bare = self.create_test_member(first_name="Bare2", last_name="NoCust")
        bare.customer = None
        cache = PaymentReferenceCache()
        self.assertEqual(self.service._update_invoice_payment_history(bare, cache), 0)

    # ---- _update_dues_payment_history (unreconciled standalone payment) ----

    def test_update_dues_history_adds_unreconciled_payment(self):
        """A custom_member Payment Entry NOT tied to an invoice becomes a dues row."""
        # Build a standalone Receive payment carrying custom_member.
        seed_invoice = self._make_submitted_invoice()
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

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
        pe.paid_amount = 12.0
        pe.received_amount = 12.0
        pe.source_exchange_rate = 1.0
        pe.target_exchange_rate = 1.0
        pe.reference_no = "DUES-STANDALONE"
        pe.reference_date = today()
        if pe.meta.has_field("custom_member"):
            pe.custom_member = self.member.name
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        # Empty cache -> this payment is NOT reconciled, so it must appear.
        cache = PaymentReferenceCache()
        changes = self.service._update_dues_payment_history(self.member, cache)
        self.assertGreaterEqual(changes, 1)

        rows = [r for r in self.member.payment_history if r.payment_entry == pe.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].transaction_type, "Membership Dues Payment")
        self.assertEqual(rows[0].payment_status, "Paid")

    # ---- incremental_update_history_tables (full orchestration) ----

    def test_incremental_update_returns_ok(self):
        """Full orchestration over a paid invoice succeeds and records invoice changes."""
        invoice = self._make_submitted_invoice()
        self._pay_invoice(invoice)

        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)
        # The invoice row must be present after the rebuild.
        self.member.reload()
        invoice_rows = [r for r in (self.member.payment_history or []) if r.invoice == invoice.name]
        self.assertEqual(len(invoice_rows), 1)

    def test_incremental_update_no_invoices_ok_no_changes(self):
        """A member with no financial activity returns ok with 'No changes'."""
        result = self.service.incremental_update_history_tables(self.member)
        self.assertTrue(result.success)

    # ---- static helpers: pure logic ----

    def test_row_needs_update_detects_diff(self):
        """_row_needs_update is True when any expected field differs."""
        row = frappe._dict(payment_status="Unpaid", amount=10.0)
        self.assertTrue(MemberHistoryUpdateService._row_needs_update(row, {"payment_status": "Paid"}))
        self.assertFalse(MemberHistoryUpdateService._row_needs_update(row, {"payment_status": "Unpaid"}))

    def test_resolve_payment_entry_picks_most_recent(self):
        """_resolve_payment_entry returns the latest posting_date payment."""
        refs = [frappe._dict(parent="PE-A"), frappe._dict(parent="PE-B")]
        data = {
            "PE-A": frappe._dict(name="PE-A", posting_date="2024-01-01", mode_of_payment="Cash"),
            "PE-B": frappe._dict(name="PE-B", posting_date="2024-06-01", mode_of_payment="Bank"),
        }
        name, date_, method, reconciled = MemberHistoryUpdateService._resolve_payment_entry(refs, data)
        self.assertEqual(name, "PE-B")
        self.assertEqual(method, "Bank")
        self.assertEqual(reconciled, 1)

    def test_resolve_payment_entry_empty_refs(self):
        """No refs -> all-None, reconciled 0."""
        result = MemberHistoryUpdateService._resolve_payment_entry([], {})
        self.assertEqual(result, (None, None, None, 0))

    def test_build_dues_payment_row_includes_notes(self):
        """_build_dues_payment_row composes notes from remarks + reference_no."""
        payment = frappe._dict(
            name="PE-1",
            remarks="Bank import",
            reference_no="REF99",
            posting_date="2024-03-01",
            received_amount=20.0,
            paid_amount=20.0,
            mode_of_payment="Bank",
        )
        row = MemberHistoryUpdateService._build_dues_payment_row(payment)
        self.assertEqual(row["transaction_type"], "Membership Dues Payment")
        self.assertEqual(row["amount"], 20.0)
        self.assertIn("Bank import", row["notes"])
        self.assertIn("Ref: REF99", row["notes"])

    def test_remove_stale_history_rows(self):
        """_remove_stale_history_rows pops rows whose ref is no longer valid (scoped)."""
        member = self.create_test_member(first_name="Stale", last_name="Rows")
        member.append(
            "payment_history",
            {
                "payment_entry": "PE-GONE",
                "transaction_type": "Membership Dues Payment",
                "amount": 1.0,
            },
        )
        member.append(
            "payment_history",
            {
                "payment_entry": "PE-KEEP",
                "transaction_type": "Membership Dues Payment",
                "amount": 1.0,
            },
        )
        removed = MemberHistoryUpdateService._remove_stale_history_rows(
            member,
            "payment_history",
            {"PE-KEEP"},
            "payment_entry",
            ("transaction_type", "Membership Dues Payment"),
        )
        self.assertEqual(removed, 1)
        remaining = {r.payment_entry for r in member.payment_history}
        self.assertEqual(remaining, {"PE-KEEP"})


class TestRefreshFeeChangeHistoryRealDB(EnhancedTestCase):
    """refresh_fee_change_history rebuild from real dues schedules."""

    def setUp(self):
        super().setUp()
        self.service = get_member_history_update_service()

    def test_refresh_with_no_schedules_no_changes(self):
        """A member with no schedules/amendments yields a 'no_changes' ok result."""
        member = self.create_test_member(first_name="FeeRef", last_name="None")
        result = self.service.refresh_fee_change_history(member.name)
        self.assertTrue(result.success)
        self.assertEqual(result.data["dues_schedules_found"], 0)
        self.assertEqual(result.data["amendments_found"], 0)

    def test_refresh_builds_entry_from_schedule(self):
        """A real dues schedule produces a Schedule-Created fee_change_history row."""
        membership_type = self.create_test_membership_type(amount=15.0)
        member, schedule = self.create_test_member_with_schedule(
            first_name="FeeRef",
            last_name="Sched",
            membership_type_name=membership_type.name,
            start_date=today(),
        )

        result = self.service.refresh_fee_change_history(member.name)
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.data["dues_schedules_found"], 1)

        member.reload()
        rows = [r for r in (member.fee_change_history or []) if r.dues_schedule == schedule.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].new_dues_rate), float(schedule.dues_rate))

    def test_refresh_unknown_member_returns_fail(self):
        """Refreshing a non-existent member returns a failed OperationResult (HIST_006)."""
        result = self.service.refresh_fee_change_history("MEM-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "HIST_006")
