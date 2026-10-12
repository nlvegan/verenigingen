"""The HRMS script report "Unpaid Expense Claim" reads every claim with raw frappe.qb and no
permission filter, and it was open to Expense Approver. Giving Staff Expense Approver (#1606)
would have shown them every unpaid claim, contradicting "Staff must not see all expenses".
"""

import frappe
from frappe.desk.query_report import run

from verenigingen.setup.custom_docperm_setup import _restrict_report_roles
from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase

REPORT = "Unpaid Expense Claim"


class TestUnpaidExpenseClaimReport(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        _restrict_report_roles()
        # a decided, submitted, unpaid claim in a chapter nobody here sits on
        self.claim_in_report = self.claim(self.volunteer_emp, chapter=self.chapter_b, submit=True)

    def _names_in_report(self, user):
        result = self.act_as(user, lambda: run(REPORT, filters={"company": self.company}))
        return {row.get("name") for row in result["result"] if isinstance(row, dict)}

    def test_the_treasurer_still_sees_the_report(self):
        # control: the report works, so a refusal below is the role restriction and not a broken report
        self.assertIn(self.claim_in_report.name, self._names_in_report(self.treasurer))

    def test_plain_staff_is_refused(self):
        with self.assertRaises(frappe.PermissionError):
            self._names_in_report(self.staff)

    def test_a_board_member_with_expense_approver_is_refused(self):
        board = self._staffexp_user("Verenigingen Chapter Board Member", "cbm")
        self._staffexp_employee(board)
        with self.assertRaises(frappe.PermissionError):
            self._names_in_report(board)

    def test_the_restriction_is_idempotent_and_keeps_hr_manager_and_system_manager(self):
        _restrict_report_roles()
        roles = frappe.get_doc("Custom Role", {"report": REPORT}).roles
        names = [r.role for r in roles]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"HR Manager", "System Manager"} <= set(names))
        self.assertNotIn("Expense Approver", names)
