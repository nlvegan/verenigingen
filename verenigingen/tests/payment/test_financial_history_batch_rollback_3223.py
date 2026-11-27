"""#3223: queue entries must not outlive a ROLLED-BACK transaction.

The queues are class-level (per process). ``frappe.db.rollback()`` drops the before_commit
drain callback (#2746) but left the entries in memory, so an unrelated later transaction
drained them, naming rows (an invoice, even the member) the rolled-back transaction had
created and which no longer exist.

Shortcuts, stated: the invoice is created with the test factory and queued through the
real ``Member.add_invoice_to_payment_history``; the rollback is a real
``frappe.db.rollback()`` (it discards this test's own uncommitted fixtures too, so
the test creates its rows INSIDE the test and tolerates their disappearance at teardown).
The 30 s window is forced by stamping ``_last_processed`` to now, so the entry is held.
"""

import frappe
from frappe.utils import now, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor as BP


class TestQueueClearedOnRollback3223(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        saved_clock = dict(BP._last_processed)
        self.addCleanup(self._restore_clock3223, saved_clock)
        BP.reset_queues()
        self.addCleanup(BP.reset_queues)
        BP._last_processed["payments"] = now()
        BP._last_processed["expenses"] = now()

    @staticmethod
    def _restore_clock3223(saved):
        BP._last_processed.clear()
        BP._last_processed.update(saved)

    def _queue_held_invoice3223(self):
        member = self.create_test_member(
            first_name="Roll3223", last_name="Back", email="roll.3223@example.com"
        )
        if not member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = "Roll3223 Back"
            customer.customer_type = "Individual"
            customer.member = member.name
            customer.save()
            member.customer = customer.name
            member.save()
        invoice = self.create_test_sales_invoice(
            customer=member.customer, is_membership_invoice=1, posting_date=today()
        )
        member.add_invoice_to_payment_history(invoice.name)
        return member.name, invoice.name

    def test_a_rolled_back_payment_entry_is_dropped_with_its_transaction(self):
        member_name, invoice_name = self._queue_held_invoice3223()
        # Control: the entry is really held, naming a row that exists right now.
        self.assertIn(invoice_name, BP._payment_queue[member_name])
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice_name))

        frappe.db.rollback()

        # The creating transaction is gone, and the entry must have gone with it.
        self.assertFalse(frappe.db.exists("Sales Invoice", invoice_name))
        self.assertNotIn(member_name, BP._payment_queue)

    def test_a_rolled_back_expense_entry_is_dropped_with_its_transaction(self):
        BP.queue_expense_operation("M-3223", "EXP-3223", "remove")
        self.assertIn("EXP-3223", BP._expense_queue["M-3223"])  # control: held

        frappe.db.rollback()

        self.assertNotIn("M-3223", BP._expense_queue)

    def test_control_a_commit_still_drains_the_held_entry(self):
        """The rollback hook must not eat entries the commit path should persist."""
        BP.queue_payment_operation("M-3223", "INV-3223", "remove")
        self.assertIn("INV-3223", BP._payment_queue["M-3223"])
        frappe.db.before_commit.run()  # what frappe.db.commit() runs first
        self.assertNotIn("M-3223", BP._payment_queue)

    def test_entries_queued_after_a_rollback_are_kept(self):
        """Control against an always-clear mutant that leaves a stuck hook: a NEW
        transaction's entry must survive until its own commit."""
        BP.queue_payment_operation("M-3223", "INV-OLD", "remove")
        frappe.db.rollback()
        BP.queue_payment_operation("M-3223", "INV-NEW", "remove")
        self.assertIn("INV-NEW", BP._payment_queue["M-3223"])
