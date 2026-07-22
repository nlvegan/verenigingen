# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit coverage for the pure helper methods of MemberHistoryUpdateService.

These static helpers operate on plain data containers (amendment rows are
frappe._dict). The tests use lightweight data stubs — no business logic is
mocked; we only supply the row data the helpers iterate over.

Covered:
- _process_fee_amendments: appends only new amendment-driven entries

NOTE: the payment-history row-building/diffing helpers (_build_dues_payment_row,
_row_needs_update, _remove_stale_history_rows, _update_or_add_history_row,
_resolve_payment_entry, _build_invoice_history_row) were removed when the
Member-form "Rebuild Payment History" path was unified onto
PaymentHistoryService.load_payment_history_batched / PaymentHistoryEntryBuilder.
Invoice-row construction is now covered by the builder's own tests
(test_payment_history_writer_parity.py, test_regression_payment_history_dynamic_links.py).
"""

import frappe

from verenigingen.services.member.history.member_history_update_service import (
    MemberHistoryUpdateService,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberHistoryUpdateHelpers(VereningingenTestCase):
    """Pure-helper coverage for MemberHistoryUpdateService."""

    def setUp(self):
        super().setUp()
        self.service = MemberHistoryUpdateService()

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
