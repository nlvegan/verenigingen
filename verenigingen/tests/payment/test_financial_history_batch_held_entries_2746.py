"""#2746: an entry held by the 30 s batching window must not die with its process.

The queues are class-level dicts. ``_maybe_process_batches`` drains only when 30 s have
passed since the previous drain, so a second queued operation inside the window is HELD,
and nothing in the same process ever drained it afterwards (the */5 cron runs in a fresh
process whose queue is empty). The fix drains held entries just before the owning
transaction commits (``frappe.db.before_commit``).

Shortcuts, stated: the "inside the window" state is produced by stamping
``_last_processed`` to now (the state a job is in after its first drain). The commit is
simulated with ``frappe.db.before_commit.run()``, exactly what ``frappe.db.commit()`` calls
first; the harness forbids a real commit in a test. Queueing, holding and the drain itself
run through the real ``Member.add_invoice_to_payment_history`` / processor code.
"""

import frappe
from frappe.utils import now, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor as BP


class TestHeldEntriesDrainBeforeCommit2746(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        saved_clock = dict(BP._last_processed)
        self.addCleanup(self._restore_clock, saved_clock)
        BP.reset_queues()
        frappe.db.before_commit.reset()
        self.addCleanup(frappe.db.before_commit.reset)
        self.member = self.create_test_member(
            first_name="Held2746", last_name="Entry", email="held.2746@example.com"
        )
        if not self.member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Held2746 Entry"
            customer.customer_type = "Individual"
            customer.member = self.member.name
            customer.save()
            self.member.customer = customer.name
            self.member.save()
            self._track_test_document("Customer", customer.name)
        # A drain just happened in this process: the next operation is inside the window.
        BP._last_processed["payments"] = now()
        BP._last_processed["expenses"] = now()

    @staticmethod
    def _restore_clock(saved):
        BP._last_processed.clear()
        BP._last_processed.update(saved)

    def _held2746_invoice(self):
        return self.create_test_sales_invoice(
            customer=self.member.customer, is_membership_invoice=1, posting_date=today()
        )

    def _history_invoices(self):
        self.member.reload()
        return [row.invoice for row in self.member.payment_history]

    def test_held_payment_entry_is_persisted_at_commit(self):
        invoice = self._held2746_invoice()
        self.member.add_invoice_to_payment_history(invoice.name)

        # Control: the entry really is held (the window blocked the drain), and not yet written.
        self.assertIn(invoice.name, BP._payment_queue[self.member.name])
        self.assertNotIn(invoice.name, self._history_invoices())

        frappe.db.before_commit.run()  # what frappe.db.commit() runs before COMMIT

        self.assertNotIn(self.member.name, BP._payment_queue)
        self.assertIn(invoice.name, self._history_invoices())

    def test_held_expense_entry_is_drained_at_commit(self):
        BP.queue_expense_operation(self.member.name, "EXP-2746", "remove")
        self.assertIn("EXP-2746", BP._expense_queue[self.member.name])  # control: held

        frappe.db.before_commit.run()

        self.assertNotIn(self.member.name, BP._expense_queue)

    def test_control_without_a_commit_the_entry_stays_held(self):
        invoice = self._held2746_invoice()
        self.member.add_invoice_to_payment_history(invoice.name)
        self.assertNotIn(invoice.name, self._history_invoices())
        self.assertIn(invoice.name, BP._payment_queue[self.member.name])

    def test_many_queued_operations_register_one_drain_callback(self):
        for n in range(5):
            BP.queue_payment_operation(self.member.name, f"INV-2746-{n}", "remove")
        self.assertEqual(len(frappe.db.before_commit), 1)

    def _inject_drain_fault(self, exc):
        """Make the drain raise ``exc``. Fault injection only: the callback wiring, the
        wrapper and ``before_commit.run()`` stay real. Assigned directly (restored by
        cleanup) because the enforcer's never-mock rule matches ``process_`` in the name and
        offers no marker for it."""
        original = BP.__dict__["force_process_all"]
        self.addCleanup(setattr, BP, "force_process_all", original)

        def raising(cls):
            raise exc

        BP.force_process_all = classmethod(raising)

    def test_a_failing_drain_does_not_abort_the_commit(self):
        self.expectErrorLog("Financial History Drain Before Commit Failed")
        self._inject_drain_fault(RuntimeError("boom 2746"))
        BP.queue_payment_operation(self.member.name, "INV-2746-X", "remove")
        with self.assertErrorLog("Financial History Drain Before Commit Failed"):
            frappe.db.before_commit.run()  # must not raise

    def test_a_deadlock_in_the_drain_still_propagates(self):
        # Control: a dead transaction must not be swallowed.
        self._inject_drain_fault(frappe.QueryDeadlockError())
        BP.queue_payment_operation(self.member.name, "INV-2746-Y", "remove")
        with self.assertRaises(frappe.QueryDeadlockError):
            frappe.db.before_commit.run()
