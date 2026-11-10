"""#2396: the Mollie debug page styles a Bank Transaction row on a classified outcome.

The page used to colour a row on ``status === 'Reconciled'``. Since #2082/#2083 a draft keeps
ERPNext's "Pending" and the reconcile pool records its outcome in ``custom_processing_status``,
so a draft the pool reconciled rendered as cancelled. ``search_transactions_by_description`` and
``check_transaction_status`` now return ``outcome`` (reconciled / unreconciled / pending) and
the marker as ``processing_status``.

Rows come from the real producer (``bank_transaction_creator``) through the #2088 fixtures,
which this module borrows. Probe shortcuts, stated: the marker is written by the app's own
``record_pool_outcome`` rather than by a pool run, and ``description`` is set with
``db.set_value`` to a unique token so the search finds only this test's rows. The "Reconciled"
submitted row is reconciled through ERPNext's own journal-entry flow.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.tests.unit import test_zabbix_mollie_bank_transaction_metrics as zabbix_2088
from verenigingen.verenigingen_payments.api import balance_transaction_processing as api
from verenigingen.verenigingen_payments.utils import bank_transaction_status as bts


class TestDebugPageRowOutcome(BTRBase):
    _national_board_member = zabbix_2088.TestZabbixMollieBankTransactionMetrics._national_board_member
    _baltr = zabbix_2088.TestZabbixMollieBankTransactionMetrics._baltr

    def setUp(self):
        super().setUp()
        self.token = f"dbg2396{frappe.generate_hash(length=8)}"

    def _row(self, submitted, marker=None):
        bt = self._baltr(submitted=submitted)
        frappe.db.set_value("Bank Transaction", bt.name, "description", f"{self.token} {bt.name}")
        bt.reload()  # the direct write above moved `modified`
        if marker:
            bts.record_pool_outcome(bt, marker)
        return bt

    def _found(self):
        result = api.search_transactions_by_description(self.token, limit=100)
        self.assertEqual(result["status"], "success", result)
        return {r["name"]: r for r in result["results"]}

    def test_every_marker_state_is_classified(self):
        expected = {
            None: "pending",
            "SEPA Identified": "pending",
            "Partial - Manual Review Required": "pending",
            "Excess - Manual Review Required": "pending",
            bts.FAILED: "unreconciled",
            bts.RECONCILED: "reconciled",
            "Manually Reconciled": "reconciled",
            "Mollie Settlement Processed": "reconciled",
        }
        rows = {marker: self._row(False, marker) for marker in expected}
        found = self._found()

        for marker, bt in rows.items():
            row = found[bt.name]
            self.assertEqual(row["status"], "Pending", "fixture: ERPNext keeps a draft Pending")
            self.assertEqual(row["processing_status"] or None, marker)
            self.assertEqual(row["outcome"], expected[marker], f"marker {marker!r}")

    def test_a_submitted_row_is_classified_by_erpnext_status(self):
        unreconciled = self._row(True)
        found = self._found()
        self.assertEqual(found[unreconciled.name]["status"], "Unreconciled")
        self.assertEqual(found[unreconciled.name]["outcome"], "unreconciled")

    def test_a_cancelled_row_carrying_a_marker_is_pending(self):
        """Control for the marker branch: #2397's counts include no cancelled row, so the page
        may not claim an outcome for one. Probe shortcut: the marker is written with
        ``db.set_value`` onto the cancelled row (no flow leaves one there; a draft marked by the
        pool and later submitted would, but submit re-validates the Select and fails on sites
        whose Custom Field options predate the fixtures)."""
        for marker in (bts.RECONCILED, bts.FAILED):
            bt = self._row(True)
            bt.cancel()
            frappe.db.set_value("Bank Transaction", bt.name, bts.FIELD, marker, update_modified=False)
            self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "docstatus"), 2)
            row = self._found()[bt.name]
            self.assertEqual(row["processing_status"], marker, "fixture: the marker is on the row")
            self.assertEqual(row["outcome"], "pending", f"cancelled row with marker {marker!r}")

    def test_a_submitted_reconciled_row_is_reconciled(self):
        """Control: ``status`` is still honoured where ERPNext owns it (submitted rows)."""
        from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
            create_journal_entry_bts,
        )

        income = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Income", "is_group": 0}, "name"
        )
        self.assertTrue(income, "the shared test company has no income leaf account")
        bt = self._row(True)
        je = create_journal_entry_bts(
            bt.name,
            reference_number=bt.reference_number,
            reference_date=today(),
            posting_date=today(),
            entry_type="Journal Entry",
            second_account=income,
        )
        je_doc = je if hasattr(je, "doctype") else frappe.get_doc("Journal Entry", je)
        self.track_doc("Journal Entry", je_doc.name)

        row = self._found()[bt.name]

        self.assertEqual(row["status"], "Reconciled", "ERPNext did not reconcile the row")
        self.assertEqual(row["outcome"], "reconciled")

    def test_check_transaction_status_returns_the_same_outcome(self):
        reconciled = self._row(False, bts.RECONCILED)
        failed = self._row(False, bts.FAILED)
        partial = self._row(False, "Partial - Manual Review Required")

        for bt, outcome in (
            (reconciled, "reconciled"),
            (failed, "unreconciled"),
            (partial, "pending"),
        ):
            result = api.check_transaction_status(bt.reference_number)
            self.assertTrue(result["processed"], result)
            self.assertEqual(result["bank_transaction"]["outcome"], outcome)
            self.assertEqual(
                result["bank_transaction"]["processing_status"], bt.get(bts.FIELD) or None
            )
