"""#2088: the Zabbix Mollie balance-transaction metrics use one window and see failed drafts.

``get_mollie_bank_transaction_metrics`` used to count ALL-TIME ``status = 'Unreconciled'``
rows against a 24h-and-then-some denominator (the window started at yesterday's midnight),
so old backlog dragged the rate down, even below zero. Since #2082 the app also writes no
``status`` on drafts: a draft the reconcile pool gave up on is ``custom_processing_status =
'Reconciliation Failed'`` with ERPNext's ``status = 'Pending'``, so it was never counted.

Rows are built by ``bank_transaction_creator`` (the real producer). Probe shortcuts, stated:
the age of a row is set with ``db.set_value("creation", ...)`` (there is no flow that
produces an old row inside a test), and the FAILED marker is written by the app's own
``record_pool_outcome`` rather than by a pool run that fails (the pool's failure path is
covered by ``test_reconcile_pool_app_owned_marker_2082``). All assertions are deltas: the
site carries ambient ``baltr_`` rows.
"""

import sys
from pathlib import Path

import frappe
from frappe.utils import add_to_date, now_datetime, today

from verenigingen.tests.payment import test_creator_draft_reconcile_pool_2083 as pool_2083
from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)
from verenigingen.verenigingen_payments.utils import bank_transaction_status as bts

# scripts/ sits outside the installed package; same trick as test_zabbix_churn_metric.py.
_SCRIPTS_MONITORING = str(Path(__file__).resolve().parents[3] / "scripts" / "monitoring")
if _SCRIPTS_MONITORING not in sys.path:
    sys.path.insert(0, _SCRIPTS_MONITORING)

import zabbix_integration  # noqa: E402

COUNT = "frappe.mollie.bank_transactions.count_24h"
UNREC = "frappe.mollie.bank_transactions.unreconciled"
RATE = "frappe.mollie.bank_transactions.reconciliation_rate"


class TestZabbixMollieBankTransactionMetrics(BTRBase):
    # The real way a creator draft comes about (a user who cannot submit).
    _national_board_member = pool_2083.TestCreatorDraftInReconcilePool._national_board_member

    def _metrics(self):
        return zabbix_integration.get_mollie_bank_transaction_metrics()

    def _baltr(self, submitted):
        """A balance-transaction Bank Transaction made by the creator.

        Submitted (as Administrator, who can submit) it has nothing allocated, so ERPNext
        derives status "Unreconciled". As a National Board Member it stays a draft.
        """
        kwargs = dict(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=12.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=f"baltr_{frappe.generate_hash(length=10)}",
            description="zabbix 2088",
        )
        if submitted:
            name = get_bank_transaction_creator().create(**kwargs)
        else:
            user = self._national_board_member()
            self.expectErrorLog("Secure Operation Failed")
            previous = frappe.session.user
            frappe.set_user(user)
            try:
                name = get_bank_transaction_creator().create(**kwargs)
            finally:
                frappe.set_user(previous)
        self.assertTrue(name)
        bt = frappe.get_doc("Bank Transaction", name)
        self.assertEqual(bt.docstatus, 1 if submitted else 0)
        self.assertEqual(bt.status, "Unreconciled" if submitted else "Pending")
        return bt

    def _back_date_creation(self, bt, hours):
        frappe.db.set_value(
            "Bank Transaction",
            bt.name,
            "creation",
            add_to_date(now_datetime(), hours=-hours),
            update_modified=False,
        )

    def test_a_failed_draft_in_the_window_is_counted_as_unreconciled(self):
        before = self._metrics()
        draft = self._baltr(submitted=False)
        bts.record_pool_outcome(draft, bts.FAILED)

        after = self._metrics()

        self.assertEqual(after[COUNT] - before[COUNT], 1)
        self.assertEqual(after[UNREC] - before[UNREC], 1)

    def test_a_pending_draft_the_pool_has_not_failed_is_not_unreconciled(self):
        """Control: only the pool's terminal failure counts, not merely being a draft."""
        before = self._metrics()
        self._baltr(submitted=False)

        after = self._metrics()

        self.assertEqual(after[COUNT] - before[COUNT], 1)
        self.assertEqual(after[UNREC] - before[UNREC], 0)

    def test_a_submitted_unreconciled_row_in_the_window_is_counted(self):
        before = self._metrics()
        self._baltr(submitted=True)

        after = self._metrics()

        self.assertEqual(after[COUNT] - before[COUNT], 1)
        self.assertEqual(after[UNREC] - before[UNREC], 1)

    def test_an_old_unreconciled_row_outside_the_window_is_not_counted(self):
        before = self._metrics()
        old = self._baltr(submitted=True)
        self._back_date_creation(old, hours=72)

        after = self._metrics()

        self.assertEqual(after[COUNT], before[COUNT])
        self.assertEqual(after[UNREC], before[UNREC])

    def test_the_window_is_24_hours_not_since_yesterdays_midnight(self):
        """A row 30h old is outside; one 12h old is inside (control)."""
        before = self._metrics()
        outside = self._baltr(submitted=True)
        self._back_date_creation(outside, hours=30)
        inside = self._baltr(submitted=True)
        self._back_date_creation(inside, hours=12)

        after = self._metrics()

        self.assertEqual(after[COUNT] - before[COUNT], 1)
        self.assertEqual(after[UNREC] - before[UNREC], 1)

    def test_old_backlog_cannot_push_the_rate_negative(self):
        """Many old unreconciled rows and one fresh clean draft: the rate stays in 0..100."""
        for _ in range(3):
            self._back_date_creation(self._baltr(submitted=True), hours=100)
        self._baltr(submitted=False)

        metrics = self._metrics()

        self.assertLessEqual(metrics[UNREC], metrics[COUNT])
        self.assertGreaterEqual(metrics[RATE], 0)
        self.assertLessEqual(metrics[RATE], 100)
