"""#3248: the held-reversal ToDo dedup must survive a desk edit of the description.

``ToDo.description`` is a Text Editor field. Once a Treasurer edits the ToDo in the desk, the
editor stores it HTML-wrapped (``<div class="ql-editor read-mode"><p>..</p><p>Reference: key</p></div>``),
so the key is no longer the last thing in the description and a Mollie redelivery raised a
second alert.

Real flow: the Bank Transaction comes from ``BankTransactionCreator``, the first alert from
``hold_unmatched_reversal`` itself, and the desk edit is a real ``ToDo.save()`` of the wrapped
HTML the editor produces (the test asserts what Frappe stored). Probe shortcut: the wrapped
string is written by hand in the editor's shape, not by a browser.

Run:
    PYTHONPATH=<worktree> bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_held_reversal_html_dedup_3248
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_bank_transaction_creator_coverage import (
    COMPANY,
    _BankTxnFixtureMixin,
)
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.mollie.utils.held_reversals import hold_unmatched_reversal
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import build_reversal_key
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator


class TestHeldReversalHtmlDedup3248(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.payment_id = f"tr_3248_{frappe.generate_hash(length=8)}"
        gl_account = self._ensure_gl_account()
        bank_account = self._ensure_bank_account(gl_account)
        self.bank_transaction = BankTransactionCreator().create_from_dict(
            {"date": "2025-06-01", "amount": 25.0, "currency": "EUR", "reference_number": self.payment_id},
            bank_account=bank_account,
            company=COMPANY,
            source_type="Donation Import",
        )
        self._ensure_a_treasurer()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _ensure_a_treasurer(self):
        if not frappe.db.exists("Role", Roles.TREASURER):
            frappe.get_doc({"doctype": "Role", "role_name": Roles.TREASURER}).insert(ignore_permissions=True)
        email = f"treasurer3248-{frappe.generate_hash(length=6)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Treasurer3248",
                "send_welcome_email": 0,
                "user_type": "System User",
                "roles": [{"role": Roles.TREASURER}],
            }
        )
        user.insert(ignore_permissions=True)

    def _hold(self, reversal_id):
        return hold_unmatched_reversal(self.payment_id, "refund", reversal_id, 25.0, self.bank_transaction)

    def _todos_for_payment(self):
        return frappe.get_all(
            "ToDo", filters={"description": ["like", f"%{self.payment_id}_refund_%"]}, pluck="name"
        )

    def _desk_edit_all(self, key_suffix):
        """One ToDo exists per Treasurer user on the site, so edit every one for the key: a
        single plain sibling would let the old lookup find it and hide the defect."""
        names = frappe.get_all("ToDo", filters={"description": ["like", f"%{key_suffix}"]}, pluck="name")
        self.assertTrue(names)
        for name in names:
            self._desk_edit(name)
        return names

    def _desk_edit_single_paragraph(self, key_suffix, after_key):
        """The shape Frappe's quill produces on a plain load: the whole description collapsed
        into ONE <p>, with whatever the Treasurer typed after the key on the same line."""
        names = frappe.get_all("ToDo", filters={"description": ["like", f"%{key_suffix}"]}, pluck="name")
        self.assertTrue(names)
        for name in names:
            todo = frappe.get_doc("ToDo", name)
            flat = todo.description.replace("\n", " ")
            todo.description = f'<div class="ql-editor read-mode"><p>{flat}{after_key}</p></div>'
            todo.save()
            stored = frappe.db.get_value("ToDo", name, "description")
            self.assertTrue(stored.rstrip().endswith(f"{after_key}</p></div>"), stored)
        return names

    def _assert_redelivery_dedups_after(self, reversal_id, after_key):
        self._hold(reversal_id)
        edited = self._desk_edit_single_paragraph(reversal_id, after_key)
        before = sorted(self._todos_for_payment())
        self.assertIn(self._hold(reversal_id), edited)
        self.assertEqual(sorted(self._todos_for_payment()), before)

    def test_note_appended_on_the_keys_line(self):
        self._assert_redelivery_dedups_after("re_note", " done")

    def test_trailing_space_after_the_key(self):
        self._assert_redelivery_dedups_after("re_space", " ")

    def test_nbsp_after_the_key(self):
        self._assert_redelivery_dedups_after("re_nbsp", " &nbsp;")

    def test_a_longer_held_id_with_a_note_is_not_the_shorter_key(self):
        """re_12 held and edited with a note on its line; re_1's alert must still be raised."""
        self._hold("re_12")
        edited = self._desk_edit_single_paragraph("re_12", " done")
        self.assertNotIn(self._hold("re_1"), edited)

    def test_a_key_differing_only_at_an_underscore_is_a_different_payment(self):
        """Real rows for a payment id that differs from ours only where ours has `_`."""
        lookalike = self.payment_id.replace("tr_", "trX", 1)
        hold_unmatched_reversal(lookalike, "refund", "re_u", 25.0, self.bank_transaction)
        lookalike_todos = frappe.get_all(
            "ToDo", filters={"description": ["like", f"%{lookalike}_refund_re_u%"]}, pluck="name"
        )
        self.assertTrue(lookalike_todos)
        for name in lookalike_todos:
            self._desk_edit(name)
        mine = self._hold("re_u")
        self.assertNotIn(mine, lookalike_todos)

    def _desk_edit(self, todo_name):
        """Re-save the description the way the desk Text Editor stores it: every line a <p>,
        the whole wrapped in the editor's div."""
        todo = frappe.get_doc("ToDo", todo_name)
        paragraphs = "".join(f"<p>{line}</p>" for line in todo.description.split("\n"))
        todo.description = f'<div class="ql-editor read-mode">{paragraphs}</div>'
        todo.save()
        stored = frappe.db.get_value("ToDo", todo_name, "description")
        self.assertIn("ql-editor", stored)
        self.assertTrue(stored.rstrip().endswith("</p></div>"), stored)

    def test_redelivery_after_a_desk_edit_does_not_raise_a_second_alert(self):
        self._hold("re_ok1")
        edited = self._desk_edit_all("re_ok1")
        before = sorted(self._todos_for_payment())

        self.assertIn(self._hold("re_ok1"), edited)
        self.assertEqual(sorted(self._todos_for_payment()), before)

    def test_a_key_that_prefixes_a_held_key_is_a_different_reversal(self):
        """Control with a real row: re_12 is held (and desk-edited); re_1 must still be alerted."""
        self._hold("re_12")
        longer = self._desk_edit_all("re_12")

        shorter = self._hold("re_1")
        self.assertNotIn(shorter, longer)
        self.assertIn(
            build_reversal_key(self.payment_id, "refund", "re_1"),
            frappe.db.get_value("ToDo", shorter, "description"),
        )

    def test_a_plain_description_still_dedups(self):
        self._hold("re_plain")
        before = sorted(self._todos_for_payment())
        self._hold("re_plain")
        self.assertEqual(sorted(self._todos_for_payment()), before)
