from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseHookDefers(EnhancedTestCase):
    def test_submit_handler_enqueues_add_and_no_inline_process(self):
        from verenigingen.services.volunteer import expense_handlers

        doc = frappe._dict(doctype="Expense Claim", name="EXP-1", employee="EMP-1")
        calls = []
        with (
            patch(
                "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
                return_value="MEMBER-X",
            ),
            patch(
                "verenigingen.services.volunteer.expense_handlers.frappe.enqueue",
                side_effect=lambda *a, **k: calls.append(k),
            ),
        ):
            expense_handlers.update_member_expense_history(doc)

        self.assertTrue(calls)
        k = calls[0]
        self.assertEqual(k.get("member"), "MEMBER-X")
        self.assertEqual(k.get("expense"), "EXP-1")
        self.assertEqual(k.get("operation"), "add")
        self.assertTrue(k.get("enqueue_after_commit"))
        self.assertTrue(k.get("deduplicate"))
        self.assertEqual(k.get("job_id"), "fin_history_expense_MEMBER-X_EXP-1_add")

    def test_cancel_handler_enqueues_remove_once(self):
        from verenigingen.services.volunteer import expense_handlers

        doc = frappe._dict(doctype="Expense Claim", name="EXP-2", employee="EMP-1")
        calls = []
        with patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
            return_value="MEMBER-Y",
        ), patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            expense_handlers.on_expense_claim_cancel(doc)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("operation"), "remove")
        self.assertEqual(calls[0].get("job_id"), "fin_history_expense_MEMBER-Y_EXP-2_remove")

    def test_update_after_submit_handler_enqueues_add(self):
        from verenigingen.events import delayed_expense_hooks

        doc = frappe._dict(doctype="Expense Claim", name="EXP-3", employee="EMP-1")
        calls = []
        with patch(
            "verenigingen.events.delayed_expense_hooks.frappe.db.get_value",
            return_value=frappe._dict(name="VOL-Z", member="MEMBER-Z"),
        ), patch(
            "verenigingen.events.delayed_expense_hooks.frappe.enqueue",
            side_effect=lambda *a, **k: calls.append(k),
        ):
            delayed_expense_hooks.schedule_member_expense_history_update(doc)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("operation"), "add")
        self.assertEqual(calls[0].get("member"), "MEMBER-Z")
