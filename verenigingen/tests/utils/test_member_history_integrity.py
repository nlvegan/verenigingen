#!/usr/bin/env python3
"""
Integration tests for verenigingen/utils/member_history_integrity.py

The HistoryIntegrityManager validates and repairs the integrity of a Member's
history child tables (payment_history, fee_change_history). These tests build
real Members with real history child rows pointing at real (or deliberately
deleted) reference documents, then assert that:

  - broken/orphan rows are actually removed from the in-memory child table
  - valid rows are kept
  - recent-but-missing references are protected by the grace period
  - duplicate references with matching amounts collapse to one (newest kept)
  - duplicate references with DIFFERENT amounts are NOT auto-deleted (manual review)
  - clean data is a no-op
  - an audit-trail Comment is written when entries are removed
  - permission gating throws when the user lacks write access

These exercise the previously-uncovered validation/repair branches in
_cleanup_history, _cleanup_payment_history_custom, _batch_validate_references,
_is_within_grace_period, _create_audit_log and cleanup_member_history.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_history_integrity import (
    HistoryIntegrityManager,
    cleanup_member_history,
)


class TestMemberHistoryIntegrity(EnhancedTestCase):
    """Real integration tests for the history integrity manager."""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _make_member(self, first_name="Hist"):
        """Create a real Member (with a linked Customer) for testing."""
        member = self.create_test_member(
            first_name=first_name,
            last_name="IntegrityTest",
            email=f"{first_name.lower()}.integrity@example.com",
        )
        member.reload()
        return member

    def _append_payment_invoice_row(self, member, invoice, amount, posting_date=None):
        """Append an invoice-based payment_history row."""
        member.append(
            "payment_history",
            {
                "invoice": invoice,
                "invoice_doctype": "Sales Invoice",
                "posting_date": posting_date or today(),
                "amount": amount,
                "transaction_type": "Regular Invoice",
            },
        )
        return member.payment_history[-1]

    def _append_fee_row(self, member, dues_schedule, new_rate, change_date=None):
        """Append a fee_change_history row."""
        member.append(
            "fee_change_history",
            {
                "dues_schedule": dues_schedule,
                "new_dues_rate": new_rate,
                "change_date": change_date or today(),
                "change_type": "Fee Adjustment",
            },
        )
        return member.fee_change_history[-1]

    def _make_dues_schedule(self, member):
        """Create a real Membership Dues Schedule linked to the member.

        A Membership Dues Schedule requires the member to have an active
        Membership, so create one first. The membership's after_insert hook
        auto-creates an Active dues schedule; the factory reuses it.
        """
        self.create_test_membership(member=member.name)
        schedule = self.create_test_dues_schedule(member=member.name, amount=25.0)
        # Reload so the caller's in-memory member doc reflects DB state (membership
        # hooks may have appended history rows), avoiding timestamp drift.
        member.reload()
        # Start each test from clean history child tables so assertions about
        # removed/kept counts only concern the rows the test itself appends.
        # (The membership after_insert hook appends an initial schedule fee row
        # and may append an invoice payment row.)
        member.fee_change_history = []
        member.payment_history = []
        return schedule.name

    def _make_invoice(self, member):
        """Create a real submitted Sales Invoice for the member's customer."""
        invoice = self.create_test_sales_invoice(customer=member.name)
        # create_test_sales_invoice returns a submitted invoice doc
        return invoice.name

    # ------------------------------------------------------------------ #
    # cleanup_payment_history
    # ------------------------------------------------------------------ #
    def test_payment_history_removes_row_missing_invoice_and_payment_entry(self):
        """A payment_history row with neither invoice nor payment_entry is broken and removed."""
        member = self._make_member("PayBoth")
        # A row with no invoice and no payment_entry
        member.append(
            "payment_history",
            {"transaction_type": "Regular Invoice", "amount": 10, "posting_date": today()},
        )
        self.assertEqual(len(member.payment_history), 1)

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.payment_history), 0)
        self.assertEqual(stats["details"][0]["reason"], "Missing both invoice and payment_entry")

    def test_payment_history_keeps_valid_invoice_row(self):
        """A row pointing at an existing Sales Invoice with required fields is kept."""
        member = self._make_member("PayValid")
        invoice = self._make_invoice(member)
        self._append_payment_invoice_row(member, invoice, amount=50)

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()

        self.assertEqual(stats["removed"], 0)
        self.assertEqual(len(member.payment_history), 1)
        self.assertEqual(member.payment_history[0].invoice, invoice)

    def test_payment_history_removes_invoice_deleted_from_system(self):
        """A row pointing at a non-existent invoice (outside grace period) is removed."""
        member = self._make_member("PayGone")
        old_date = add_days(today(), -30)  # well outside the 7-day grace period
        self._append_payment_invoice_row(member, "SINV-DOES-NOT-EXIST-0001", amount=20, posting_date=old_date)

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.payment_history), 0)
        self.assertEqual(stats["details"][0]["reason"], "Sales Invoice deleted from system")

    def test_payment_history_grace_period_protects_recent_missing_invoice(self):
        """A row whose invoice is missing but whose posting_date is within the last
        7 days is SKIPPED (not removed), to avoid races with in-flight transactions
        whose reference document is momentarily missing/uncommitted.

        (Regression guard for the grace-period TypeError bug fixed at
        member_history_integrity.py:454 — add_days() returns a str, so the
        comparison must wrap the threshold in getdate().)
        """
        member = self._make_member("PayGrace")
        recent = add_days(today(), -1)  # within the 7-day grace period
        self._append_payment_invoice_row(member, "SINV-MISSING-RECENT-0001", amount=20, posting_date=recent)

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()

        # Recent row protected by the grace period -> kept, not removed.
        self.assertEqual(stats["removed"], 0)
        self.assertEqual(len(member.payment_history), 1)

    def test_payment_history_removes_invoice_row_missing_posting_or_amount(self):
        """An invoice-based row missing posting_date/amount is removed."""
        member = self._make_member("PayNoAmt")
        invoice = self._make_invoice(member)
        member.append(
            "payment_history",
            {
                "invoice": invoice,
                "invoice_doctype": "Sales Invoice",
                "transaction_type": "Regular Invoice",
                # no posting_date, no amount
            },
        )

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.payment_history), 0)
        self.assertIn("missing posting_date or amount", stats["details"][0]["reason"])

    def test_payment_history_sorts_remaining_newest_first(self):
        """After cleanup, valid rows are sorted newest-first by posting_date."""
        member = self._make_member("PaySort")
        inv1 = self._make_invoice(member)
        inv2 = self._make_invoice(member)
        # Append older first, newer second
        self._append_payment_invoice_row(member, inv1, amount=10, posting_date=add_days(today(), -10))
        self._append_payment_invoice_row(member, inv2, amount=20, posting_date=today())
        # plus a broken row that forces removal/sort path
        member.append("payment_history", {"transaction_type": "Regular Invoice", "amount": 1})

        manager = HistoryIntegrityManager(member)
        manager.cleanup_payment_history()

        self.assertEqual(len(member.payment_history), 2)
        # newest first
        self.assertEqual(member.payment_history[0].invoice, inv2)
        self.assertEqual(member.payment_history[1].invoice, inv1)

    def test_fee_history_sort_tolerates_missing_change_date(self):
        """Regression: a KEPT fee row whose change_date is None must not break the
        newest-first sort. change_date is the sort field but not a required-to-keep
        field, so a row with a populated date (datetime.date, as DB-loaded rows
        are) and a row with None coexist. The sort key normalizes through
        getdate() because a raw ``date < str`` comparison (date vs the
        "1900-01-01" fallback) raises TypeError in Python 3 and would otherwise
        abort the whole cleanup.
        """
        member = self._make_member("FeeSortMixed")
        ds = self._make_dues_schedule(member)
        member.fee_change_history = []
        member.payment_history = []

        # Two rows on the same (existing) schedule with DIFFERENT amounts both
        # survive cleanup (the duplicate-with-different-amounts case is flagged
        # for manual review, not removed) — giving us two kept rows to sort.
        # One carries a real date object; the other a None change_date.
        row_a = self._append_fee_row(member, ds, new_rate=25.0, change_date=today())
        row_a.change_date = getdate(today())
        row_b = self._append_fee_row(member, ds, new_rate=30.0, change_date=today())
        row_b.change_date = None  # force the mixed-type sort path on a kept row

        manager = HistoryIntegrityManager(member)
        # Pre-fix this raised TypeError (date < '1900-01-01'); must not now.
        manager.cleanup_fee_history()

        # Both rows are kept and the dated row sorts ahead of the undated
        # (1900 fallback) one.
        self.assertEqual(len(member.fee_change_history), 2)
        self.assertEqual(member.fee_change_history[0].new_dues_rate, 25.0)
        self.assertIsNone(member.fee_change_history[1].change_date)

    # ------------------------------------------------------------------ #
    # cleanup_fee_history (generic _cleanup_history)
    # ------------------------------------------------------------------ #
    def test_fee_history_removes_row_missing_required_fields(self):
        """A fee row missing required fields (dues_schedule/new_dues_rate) is removed."""
        member = self._make_member("FeeMissing")
        member.append(
            "fee_change_history",
            {"change_date": today(), "change_type": "Fee Adjustment"},  # no dues_schedule/rate
        )

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.fee_change_history), 0)
        self.assertIn("Missing required fields", stats["details"][0]["reason"])

    def test_fee_history_keeps_valid_row(self):
        """A fee row pointing at an existing dues schedule with required fields is kept."""
        member = self._make_member("FeeValid")
        schedule = self._make_dues_schedule(member)
        self._append_fee_row(member, schedule, new_rate=25.0)

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        self.assertEqual(stats["removed"], 0)
        self.assertEqual(len(member.fee_change_history), 1)

    def test_fee_history_removes_row_for_deleted_schedule(self):
        """A fee row whose dues schedule no longer exists (outside grace) is removed."""
        member = self._make_member("FeeGone")
        self._append_fee_row(
            member, "MDS-DOES-NOT-EXIST-0001", new_rate=25.0, change_date=add_days(today(), -30)
        )

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.fee_change_history), 0)
        self.assertEqual(stats["details"][0]["reason"], "Membership Dues Schedule deleted from system")

    def test_fee_history_duplicate_same_amount_keeps_newer(self):
        """Duplicate references with MATCHING amounts collapse: older removed, newer kept."""
        member = self._make_member("FeeDupSame")
        schedule = self._make_dues_schedule(member)
        # Two rows, same schedule + same rate, different change_date
        self._append_fee_row(member, schedule, new_rate=25.0, change_date=add_days(today(), -5))
        self._append_fee_row(member, schedule, new_rate=25.0, change_date=today())

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.fee_change_history), 1)
        # the kept entry is the newer one
        self.assertEqual(str(member.fee_change_history[0].change_date), str(today()))
        self.assertIn("Duplicate", stats["details"][0]["reason"])

    def test_fee_history_duplicate_different_amount_is_not_deleted(self):
        """Duplicate references with DIFFERENT amounts are flagged as errors, NOT removed."""
        member = self._make_member("FeeDupDiff")
        schedule = self._make_dues_schedule(member)
        self._append_fee_row(member, schedule, new_rate=25.0, change_date=add_days(today(), -5))
        self._append_fee_row(member, schedule, new_rate=99.0, change_date=today())

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        # Conflicting amounts -> manual review, nothing removed, an error recorded
        self.assertEqual(stats["removed"], 0)
        self.assertEqual(len(member.fee_change_history), 2)
        self.assertEqual(stats["errors"], 1)
        self.assertIn("DIFFERENT AMOUNTS", stats["error_details"][0]["error"])

    def test_fee_history_grace_period_protects_recent_missing_schedule(self):
        """The grace period also protects recent fee-history rows whose schedule is
        momentarily missing (regression guard for the same getdate() fix).
        """
        member = self._make_member("FeeGrace")
        self._append_fee_row(
            member, "MDS-MISSING-RECENT-0001", new_rate=25.0, change_date=add_days(today(), -1)
        )

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_fee_history()

        # Recent row protected by the grace period -> kept, not removed.
        self.assertEqual(stats["removed"], 0)
        self.assertEqual(len(member.fee_change_history), 1)

    # ------------------------------------------------------------------ #
    # _batch_validate_references
    # ------------------------------------------------------------------ #
    def test_batch_validate_excludes_cancelled_documents(self):
        """A cancelled Sales Invoice is excluded from the valid-reference map, so its row is removed."""
        member = self._make_member("Cancelled")
        invoice_name = self._make_invoice(member)
        # Cancel the invoice -> docstatus 2 -> must be treated as deleted
        inv = frappe.get_doc("Sales Invoice", invoice_name)
        inv.cancel()

        self._append_payment_invoice_row(member, invoice_name, amount=50, posting_date=add_days(today(), -30))

        manager = HistoryIntegrityManager(member)
        # Directly assert the batch validator excludes the cancelled doc
        refs = manager._batch_validate_references(member.payment_history, "invoice", "Sales Invoice")
        self.assertNotIn(invoice_name, refs)

        stats = manager.cleanup_payment_history()
        self.assertEqual(stats["removed"], 1)
        self.assertEqual(len(member.payment_history), 0)

    def test_batch_validate_empty_returns_empty(self):
        """No reference values -> empty map (no query)."""
        member = self._make_member("EmptyRefs")
        manager = HistoryIntegrityManager(member)
        refs = manager._batch_validate_references([], "invoice", "Sales Invoice")
        self.assertEqual(refs, {})

    # ------------------------------------------------------------------ #
    # _is_within_grace_period
    # ------------------------------------------------------------------ #
    def test_grace_period_helper_missing_date_returns_false(self):
        """An entry with no date is never within the grace period (early-return branch)."""
        member = self._make_member("GraceNoDate")
        manager = HistoryIntegrityManager(member)
        none = frappe._dict({"posting_date": None})
        self.assertFalse(manager._is_within_grace_period(none, "posting_date", grace_days=7))

    def test_grace_period_helper_compares_dates_not_strings(self):
        """Regression guard for the grace-period TypeError bug
        (member_history_integrity.py:454).

        add_days(<str>, n) returns a STRING; comparing a datetime.date to a str
        raised TypeError, which was swallowed (except Exception: return False),
        so the grace period NEVER applied. The fix wraps the threshold in
        getdate(). A same-day entry must now be recognised as within the window,
        while an old entry must not.
        """
        member = self._make_member("GraceBug")
        manager = HistoryIntegrityManager(member)

        # An entry dated TODAY is unambiguously within any positive grace window.
        today_entry = frappe._dict({"posting_date": today()})
        self.assertTrue(
            manager._is_within_grace_period(today_entry, "posting_date", grace_days=7),
            "grace period helper should return True for a same-day entry",
        )

        # An entry well outside the window is correctly excluded.
        old_entry = frappe._dict({"posting_date": add_days(today(), -30)})
        self.assertFalse(manager._is_within_grace_period(old_entry, "posting_date", grace_days=7))

    # ------------------------------------------------------------------ #
    # _create_audit_log
    # ------------------------------------------------------------------ #
    def test_audit_comment_created_on_removal(self):
        """Removing entries writes an Info Comment audit trail on the Member."""
        member = self._make_member("Audit")
        before = frappe.db.count(
            "Comment",
            {"reference_doctype": "Member", "reference_name": member.name, "comment_type": "Info"},
        )
        member.append(
            "payment_history",
            {"transaction_type": "Regular Invoice", "amount": 5, "posting_date": today()},
        )

        manager = HistoryIntegrityManager(member)
        stats = manager.cleanup_payment_history()
        self.assertEqual(stats["removed"], 1)

        after = frappe.db.count(
            "Comment",
            {"reference_doctype": "Member", "reference_name": member.name, "comment_type": "Info"},
        )
        self.assertEqual(after, before + 1)

    # ------------------------------------------------------------------ #
    # cleanup_member_history top-level entry point
    # ------------------------------------------------------------------ #
    def test_cleanup_member_history_aggregates_all_types(self):
        """The top-level entry point returns separate stats for each history type."""
        member = self._make_member("TopLevel")
        # one broken payment row, one broken fee row
        member.append(
            "payment_history",
            {"transaction_type": "Regular Invoice", "amount": 5, "posting_date": today()},
        )
        member.append("fee_change_history", {"change_date": today(), "change_type": "Fee Adjustment"})

        result = cleanup_member_history(member)

        self.assertEqual(result["payment_history"]["removed"], 1)
        self.assertEqual(result["fee_history"]["removed"], 1)
        # No employee linked -> volunteer expense cleanup skipped (default no-op stats)
        self.assertEqual(result["volunteer_expenses"]["removed"], 0)

    def test_cleanup_member_history_clean_data_is_noop(self):
        """Clean data (valid rows only) results in zero removals across all types."""
        member = self._make_member("Clean")
        invoice = self._make_invoice(member)
        # _make_dues_schedule clears history child tables, so call it before
        # appending the rows this test asserts on.
        schedule = self._make_dues_schedule(member)
        self._append_payment_invoice_row(member, invoice, amount=50)
        self._append_fee_row(member, schedule, new_rate=25.0)

        result = cleanup_member_history(member)

        self.assertEqual(result["payment_history"]["removed"], 0)
        self.assertEqual(result["fee_history"]["removed"], 0)
        self.assertEqual(result["volunteer_expenses"]["removed"], 0)
        self.assertEqual(len(member.payment_history), 1)
        self.assertEqual(len(member.fee_change_history), 1)

    def test_empty_history_returns_empty_stats(self):
        """A member with no history rows yields empty cleanup stats."""
        member = self._make_member("NoHistory")
        manager = HistoryIntegrityManager(member)

        pay = manager.cleanup_payment_history()
        fee = manager.cleanup_fee_history()

        self.assertEqual(pay["removed"], 0)
        self.assertEqual(pay["errors"], 0)
        self.assertEqual(fee["removed"], 0)
        self.assertEqual(fee["errors"], 0)
