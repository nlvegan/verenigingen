from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseHookDefers(EnhancedTestCase):
    def _patch_lookup(self, member):
        # Stub the Volunteer->member resolution so the test needs no HR fixtures.
        return patch(
            "verenigingen.services.volunteer.expense_handlers.frappe.db.get_value",
            side_effect=lambda dt, *a, **k: (
                {"Volunteer": "VOL-X"}.get(dt, member)
                if dt == "Volunteer" and "employee_id" in str(a)
                else member
            ),
        )

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
        self.assertEqual(k.get("job_id"), "fin_history_expense_MEMBER-X_EXP-1")
