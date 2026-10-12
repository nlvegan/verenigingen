"""The HRMS script report "Unpaid Expense Claim" reads every claim with raw frappe.qb and no
permission filter, and it was open to Expense Approver. Giving Staff Expense Approver (#1606)
would have shown them every unpaid claim, contradicting "Staff must not see all expenses".
"""

import frappe
from frappe.desk.query_report import run

from verenigingen.setup.custom_docperm_setup import _restrict_report_roles, apply_custom_permissions
from verenigingen.tests.fixtures.enhanced_test_factory import suspend_insert_capture
from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase

REPORT = "Unpaid Expense Claim"


class TestUnpaidExpenseClaimReport(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        # Start from "no Custom Role" whatever the site carries, so the build below is what
        # these tests exercise (a leftover restricted role would hide a broken helper).
        for name in frappe.get_all("Custom Role", filters={"report": REPORT}, pluck="name"):
            frappe.delete_doc("Custom Role", name, ignore_permissions=True, force=True)
        # The Custom Role is site-wide state that migrate/install builds, not a per-test row:
        # built outside the captured-insert drain so the drain does not delete it afterwards and
        # leave every later module in the shard without the restriction.
        with suspend_insert_capture():
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

    def test_apply_custom_permissions_applies_the_restriction(self):
        # The install/migrate entry point must actually call the helper
        for name in frappe.get_all("Custom Role", filters={"report": REPORT}, pluck="name"):
            frappe.delete_doc("Custom Role", name, ignore_permissions=True, force=True)
        self.assertFalse(frappe.db.exists("Custom Role", {"report": REPORT}), "precondition")

        with suspend_insert_capture():
            apply_custom_permissions()

        names = [r.role for r in frappe.get_doc("Custom Role", {"report": REPORT}).roles]
        self.assertIn("HR Manager", names)
        self.assertNotIn("Expense Approver", names)
