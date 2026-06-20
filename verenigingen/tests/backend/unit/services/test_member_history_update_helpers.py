# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit coverage for the pure helper methods of MemberHistoryUpdateService.

These static/instance helpers operate on plain data containers (history rows are
frappe._dict, payment rows are frappe._dict). The tests use lightweight data
stubs — no business logic is mocked; we only supply the row/payment data the
helpers iterate over.

Covered:
- _build_dues_payment_row: maps Payment Entry fields and assembles the notes string
- _row_needs_update: detects when an existing row differs from expected
- _remove_stale_history_rows: drops rows scoped to a transaction_type when stale
- _update_or_add_history_row: update vs append vs no-op
- _process_fee_amendments: appends only new amendment-driven entries
"""

from types import SimpleNamespace

import frappe

from verenigingen.services.member.history.member_history_update_service import (
    MemberHistoryUpdateService,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class _FakeMember:
    """Minimal member stand-in exposing a single child table and append()."""

    def __init__(self, field_name, rows=None):
        self.name = "FAKE-MEMBER-001"
        setattr(self, field_name, rows if rows is not None else [])
        self._field_name = field_name
        self.appended = []

    def append(self, field_name, row):
        getattr(self, field_name).append(frappe._dict(row))
        self.appended.append(row)


class TestMemberHistoryUpdateHelpers(VereningingenTestCase):
    """Pure-helper coverage for MemberHistoryUpdateService."""

    def setUp(self):
        super().setUp()
        self.service = MemberHistoryUpdateService()

    # ----- _build_dues_payment_row -----

    def test_build_dues_payment_row_maps_fields_and_notes(self):
        payment = frappe._dict(
            name="PE-001",
            posting_date="2026-01-15",
            received_amount=50.0,
            paid_amount=50.0,
            mode_of_payment="Bank Transfer",
            remarks="Monthly dues",
            reference_no="REF-99",
        )
        row = MemberHistoryUpdateService._build_dues_payment_row(payment)
        self.assertEqual(row["payment_entry"], "PE-001")
        self.assertEqual(row["transaction_type"], "Membership Dues Payment")
        self.assertEqual(row["amount"], 50.0)
        self.assertEqual(row["payment_status"], "Paid")
        self.assertEqual(row["reconciled"], 0)
        # Notes combine remarks and the reference number.
        self.assertIn("Monthly dues", row["notes"])
        self.assertIn("Ref: REF-99", row["notes"])
        # Dynamic-link guard: never store arbitrary reference strings.
        self.assertIsNone(row["reference_doctype"])
        self.assertIsNone(row["reference_name"])

    def test_build_dues_payment_row_falls_back_to_paid_amount(self):
        payment = frappe._dict(
            name="PE-002",
            posting_date="2026-01-16",
            received_amount=0,
            paid_amount=33.0,
            mode_of_payment="Cash",
            remarks=None,
            reference_no=None,
        )
        row = MemberHistoryUpdateService._build_dues_payment_row(payment)
        # received_amount is falsy -> falls back to paid_amount.
        self.assertEqual(row["amount"], 33.0)
        self.assertEqual(row["notes"], "")

    # ----- _row_needs_update -----

    def test_row_needs_update_detects_difference(self):
        existing = SimpleNamespace(amount=10.0, payment_status="Unpaid")
        self.assertTrue(
            MemberHistoryUpdateService._row_needs_update(existing, {"amount": 10.0, "payment_status": "Paid"})
        )

    def test_row_needs_update_returns_false_when_equal(self):
        existing = SimpleNamespace(amount=10.0, payment_status="Paid")
        self.assertFalse(
            MemberHistoryUpdateService._row_needs_update(existing, {"amount": 10.0, "payment_status": "Paid"})
        )

    # ----- _remove_stale_history_rows -----

    def test_remove_stale_rows_drops_only_scoped_stale_rows(self):
        rows = [
            frappe._dict(payment_entry="PE-1", transaction_type="Membership Dues Payment"),
            frappe._dict(payment_entry="PE-2", transaction_type="Membership Dues Payment"),
            frappe._dict(payment_entry="PE-3", transaction_type="Regular Invoice"),
        ]
        member = _FakeMember("payment_history", rows)
        # Only PE-1 remains valid; PE-2 is stale and dues-scoped; PE-3 is a
        # different scope and must be preserved.
        removed = MemberHistoryUpdateService._remove_stale_history_rows(
            member,
            "payment_history",
            valid_names={"PE-1"},
            filter_field="payment_entry",
            filter_value=("transaction_type", "Membership Dues Payment"),
        )
        self.assertEqual(removed, 1)
        remaining = {r.payment_entry for r in member.payment_history}
        self.assertEqual(remaining, {"PE-1", "PE-3"})

    # ----- _update_or_add_history_row -----

    def test_update_or_add_appends_new_row(self):
        member = _FakeMember("payment_history", [])
        updated, added = self.service._update_or_add_history_row(
            member, "payment_history", "INV-1", {"amount": 5.0}, existing_lookup={}
        )
        self.assertEqual((updated, added), (0, 1))
        self.assertEqual(len(member.payment_history), 1)

    def test_update_or_add_updates_existing_row(self):
        existing_row = SimpleNamespace(amount=1.0)
        member = _FakeMember("payment_history", [existing_row])
        updated, added = self.service._update_or_add_history_row(
            member, "payment_history", "INV-1", {"amount": 9.0}, existing_lookup={"INV-1": existing_row}
        )
        self.assertEqual((updated, added), (1, 0))
        self.assertEqual(existing_row.amount, 9.0)

    def test_update_or_add_noop_when_unchanged(self):
        existing_row = SimpleNamespace(amount=9.0)
        member = _FakeMember("payment_history", [existing_row])
        updated, added = self.service._update_or_add_history_row(
            member, "payment_history", "INV-1", {"amount": 9.0}, existing_lookup={"INV-1": existing_row}
        )
        self.assertEqual((updated, added), (0, 0))

    # ----- _process_fee_amendments -----

    def test_process_fee_amendments_appends_only_new(self):
        captured = []

        class _AmendMember:
            def add_fee_change_to_history(self, data):
                captured.append(data)

        member = _AmendMember()
        amendments = [
            frappe._dict(
                name="AM-1",
                requested_amount=20.0,
                current_amount=10.0,
                reason="raise",
                applied_date="2026-01-01",
                effective_date="2026-01-01",
                applied_by="Administrator",
            ),
            frappe._dict(
                name="AM-2",
                requested_amount=30.0,
                current_amount=20.0,
                reason=None,
                applied_date=None,
                effective_date="2026-02-01",
                applied_by=None,
            ),
        ]
        # AM-1 already present -> only AM-2 should be appended.
        changes = MemberHistoryUpdateService._process_fee_amendments(
            member, amendments, existing_entries_by_amendment={"AM-1": object()}
        )
        self.assertTrue(changes)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["amendment_request"], "AM-2")
        # Missing reason -> synthesized "Amendment AM-2" label; changed_by default.
        self.assertEqual(captured[0]["reason"], "Amendment AM-2")
        self.assertEqual(captured[0]["changed_by"], "Administrator")
