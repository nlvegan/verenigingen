"""#2344: ``get_processing_statistics`` classifies drafts by the pool's marker, not ``status``.

Since #2082 the app writes no ``status``: ERPNext keeps every draft Bank Transaction at
"Pending", and the reconcile pool records its outcome in ``custom_processing_status``. The
statistics used to count ``status = Reconciled/Unreconciled`` only, so a draft the pool gave
up on was never "unreconciled" and a draft it reconciled was never "reconciled".

Rows come from the real producer (``bank_transaction_creator``) through the fixtures of the
#2088 test, which this module borrows. Probe shortcuts, stated: ``date`` and
``reference_number`` of the two control rows are set with ``db.set_value`` (no flow makes an
old or non-``baltr_`` row inside a test), and the marker is written by the app's own
``record_pool_outcome`` rather than by a pool run. All assertions are deltas: the site
carries ambient ``baltr_`` rows.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.tests.unit import test_zabbix_mollie_bank_transaction_metrics as zabbix_2088
from verenigingen.verenigingen_payments.api import balance_transaction_processing as api
from verenigingen.verenigingen_payments.utils import bank_transaction_status as bts


class TestProcessingStatisticsDrafts(BTRBase):
    # Fixture helpers borrowed from the #2088 test; bound in the class body so that module's
    # TestCase is not collected (and re-run) here.
    _national_board_member = zabbix_2088.TestZabbixMollieBankTransactionMetrics._national_board_member
    _baltr = zabbix_2088.TestZabbixMollieBankTransactionMetrics._baltr
    _reconcile_through_erpnext = zabbix_2088.TestZabbixMollieBankTransactionMetrics._reconcile_through_erpnext

    def _totals(self):
        result = api.get_processing_statistics(days=7)
        self.assertEqual(result["status"], "success", result)
        return result["totals"]

    def test_every_state_is_classified_and_controls_are_left_out(self):
        before = self._totals()

        submitted_unreconciled = self._baltr(submitted=True)
        submitted_reconciled = self._baltr(submitted=True)
        self._reconcile_through_erpnext(submitted_reconciled)
        draft_failed = self._baltr(submitted=False)
        bts.record_pool_outcome(draft_failed, bts.FAILED)
        draft_reconciled = self._baltr(submitted=False)
        bts.record_pool_outcome(draft_reconciled, bts.RECONCILED)
        draft_manual = self._baltr(submitted=False)
        bts.record_pool_outcome(draft_manual, "Manually Reconciled")  # SEPA dashboard's marker
        self._baltr(submitted=False)  # plain draft, still in the pool

        # Controls: each carries a state that WOULD count, but sits outside the filter.
        old_failed = self._baltr(submitted=False)
        bts.record_pool_outcome(old_failed, bts.FAILED)
        frappe.db.set_value("Bank Transaction", old_failed.name, "date", add_days(today(), -200))
        other_failed = self._baltr(submitted=False)
        bts.record_pool_outcome(other_failed, bts.FAILED)
        frappe.db.set_value("Bank Transaction", other_failed.name, "reference_number", "other_" + other_failed.name)

        for bt in (draft_failed, draft_reconciled):
            self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "status"), "Pending")
        self.assertEqual(submitted_unreconciled.status, "Unreconciled")

        after = self._totals()

        self.assertEqual(after["total_processed"] - before["total_processed"], 6)
        self.assertEqual(after["reconciled"] - before["reconciled"], 3)  # submitted + 2 marked drafts
        self.assertEqual(after["unreconciled"] - before["unreconciled"], 2)  # submitted + FAILED draft
