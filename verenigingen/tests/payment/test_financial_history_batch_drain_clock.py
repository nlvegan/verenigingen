"""#2079: the batch processor's 30 s drain gate must compare TOTAL elapsed seconds.

``timedelta.seconds`` is only the seconds *part* (0..86399): a last drain 1 day + 10 s
old reads as 10 s (no drain), and a last-drain stamp in the FUTURE (clock stepped back)
reads as ~86400 - x (drains on every call).

The queue is seeded directly with made-up members (documented shortcut: the gate does
not read the queue contents; the real drain runs and handles the per-member failure).
"""

from datetime import timedelta

from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor as BP


class TestBatchDrainClock(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        saved_clock = dict(BP._last_processed)
        saved_payments = {k: dict(v) for k, v in BP._payment_queue.items()}
        saved_expenses = {k: dict(v) for k, v in BP._expense_queue.items()}
        self.addCleanup(self._restore, saved_clock, saved_payments, saved_expenses)
        BP._last_processed.clear()
        BP._payment_queue.clear()
        BP._expense_queue.clear()
        BP._payment_queue["M-2079"]["INV-2079"] = {"operation": "add_update", "timestamp": "x", "data": {}}
        BP._expense_queue["M-2079"]["EXP-2079"] = {"operation": "add_update", "timestamp": "x", "data": {}}

    @staticmethod
    def _restore(clock, payments, expenses):
        BP._last_processed.clear()
        BP._last_processed.update(clock)
        BP._payment_queue.clear()
        BP._payment_queue.update(payments)
        BP._expense_queue.clear()
        BP._expense_queue.update(expenses)

    def _drained(self, last_stamp):
        """Run the gate for real. A drain empties each queue before processing it (the
        per-member work then fails on the made-up member and is handled), so an emptied
        queue is the observable proof that the gate let the drain through."""
        BP._last_processed["payments"] = last_stamp
        BP._last_processed["expenses"] = last_stamp
        BP._maybe_process_batches()
        return (not BP._payment_queue, not BP._expense_queue)

    def test_drains_when_last_drain_is_a_day_and_ten_seconds_old(self):
        stamp = now_datetime() - timedelta(days=1, seconds=10)
        self.assertEqual(self._drained(stamp), (True, True))

    def test_does_not_drain_when_last_drain_is_in_the_future(self):
        stamp = add_to_date(now_datetime(), seconds=100)
        self.assertEqual(self._drained(stamp), (False, False))

    def test_control_does_not_drain_when_recent(self):
        stamp = now_datetime() - timedelta(seconds=10)
        self.assertEqual(self._drained(stamp), (False, False))

    def test_control_drains_when_thirty_one_seconds_old(self):
        stamp = now_datetime() - timedelta(seconds=31)
        self.assertEqual(self._drained(stamp), (True, True))
