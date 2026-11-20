"""#3035: an Expense Claim's ``amended_from`` must point at a claim the filer may READ.

Measured before the fix: a plain Volunteer-profile member could insert a claim under their OWN
employee with ``amended_from`` = a stranger's cancelled claim. Nothing of the stranger's is
re-pointed, but the new claim links into (and is named after) a claim the member cannot read.
The guard sits in the Expense Claim validate hook and decides read access with the app's own
``has_expense_claim_permission``, so an unknown and a forbidden ``amended_from`` are refused
identically (same exception, message, message_log, Error Log rows and query count).

Attackers are real users with the Volunteer profile's roles; nothing runs as Administrator.
Probe shortcut, stated: the original claim is made ``docstatus=2`` with ``db.set_value`` (a real
cancel needs an approved, submitted claim; the path under test starts at the NEW document).
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.security.test_member_files_chapter_claim_2528 import MemberClaimBase

PERMISSION = (frappe.PermissionError, frappe.ValidationError)


class TestExpenseClaimAmendedFrom3035(MemberClaimBase):
    def setUp(self):
        super().setUp()
        self.stranger, self.stranger_emp, _member, _vol = self._person("strg3035")
        self.staff = self._staffexp_user("Verenigingen Staff", "stf3035", extra_roles=("Verenigingen Administrator",))
        self.staff_emp = self._staffexp_employee(self.staff)

    def _cancelled_claim_of(self, user, employee, **fields):
        original = self.act_as(user, lambda: frappe.get_doc(self.claim_data(employee=employee, **fields)).insert())
        frappe.db.set_value("Expense Claim", original.name, "docstatus", 2)  # probe shortcut (docstring)
        return original

    def _amend_as(self, actor, employee, source, **fields):
        data = self.claim_data(employee=employee, amended_from=source, **fields)
        return self.act_as(actor, lambda: frappe.get_doc(data).insert())

    def _refusal(self, actor, employee, source):
        """Every channel one refusal leaves, with the message_log and Error Log rows it added."""
        before = len(frappe.local.message_log)
        errors = frappe.db.count("Error Log")
        queries = []
        real_sql = frappe.db.sql

        def counting(*args, **kwargs):
            queries.append(1)
            return real_sql(*args, **kwargs)

        with patch.object(frappe.db, "sql", counting), self.assertRaises(PERMISSION) as raised:
            self._amend_as(actor, employee, source)
        logged = [m.get("message") if isinstance(m, dict) else m for m in frappe.local.message_log[before:]]
        del frappe.local.message_log[before:]
        return {
            "type": type(raised.exception),
            "text": str(raised.exception),
            "logged": logged,
            "error_logs": frappe.db.count("Error Log") - errors,
            "queries": len(queries),
        }

    def test_a_member_cannot_amend_a_strangers_cancelled_claim_onto_their_own_employee(self):
        foreign = self._cancelled_claim_of(self.stranger, self.stranger_emp)
        with self.assertRaises(PERMISSION):
            self._amend_as(self.user, self.employee, foreign.name)
        self.assertEqual(frappe.get_all("Expense Claim", filters={"employee": self.employee.name}), [])

    def test_a_forbidden_and_an_unknown_amended_from_are_refused_identically(self):
        foreign = self._cancelled_claim_of(self.stranger, self.stranger_emp)
        self._refusal(self.user, self.employee, foreign.name)  # warm the role/meta caches: not measured
        forbidden = self._refusal(self.user, self.employee, foreign.name)
        unknown = self._refusal(self.user, self.employee, "HR-EXP-0000-99999")
        self.assertTrue(forbidden["logged"], "control: the refusal does log a message")
        self.assertEqual(forbidden, unknown)

    def test_control_the_claimant_amends_their_own_cancelled_claim(self):
        own = self._cancelled_claim_of(self.user, self.employee)
        amended = self._amend_as(self.user, self.employee, own.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", amended.name, "amended_from"), own.name)

    def test_control_staff_amends_anyones_cancelled_claim(self):
        foreign = self._cancelled_claim_of(self.stranger, self.stranger_emp)
        amended = self._amend_as(self.staff, self.staff_emp, foreign.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", amended.name, "amended_from"), foreign.name)

    def test_control_a_chapter_approver_amends_a_claim_they_can_read(self):
        self.join(self.member.name, self.chapter)
        attributed = self._cancelled_claim_of(self.user, self.employee, custom_chapter=self.chapter.name)
        self.assertTrue(self.act_as(self.fin_user, lambda: frappe.has_permission("Expense Claim", "read", doc=attributed.name)))
        fin_emp = frappe.get_doc("Employee", frappe.db.get_value("Employee", {"user_id": self.fin_user.name}))
        amended = self._amend_as(self.fin_user, fin_emp, attributed.name)
        self.assertEqual(frappe.db.get_value("Expense Claim", amended.name, "amended_from"), attributed.name)

    def test_an_expense_approver_without_a_seat_cannot_amend_a_claim_they_cannot_read(self):
        other, other_emp, _m, _v = self._person("apr3035", extra_roles=("Expense Approver",))
        foreign = self._cancelled_claim_of(self.stranger, self.stranger_emp)
        with self.assertRaises(PERMISSION):
            self._amend_as(other, other_emp, foreign.name)

    def test_a_member_cannot_point_an_existing_claim_at_a_strangers_claim(self):
        foreign = self._cancelled_claim_of(self.stranger, self.stranger_emp)
        own = self.act_as(self.user, lambda: frappe.get_doc(self.claim_data()).insert())

        def relink():
            doc = frappe.get_doc("Expense Claim", own.name)
            doc.amended_from = foreign.name
            doc.save()

        with self.assertRaises(PERMISSION):
            self.act_as(self.user, relink)
        self.assertFalse(frappe.db.get_value("Expense Claim", own.name, "amended_from"))
