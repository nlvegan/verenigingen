"""
Integration coverage for the restored Member ``volunteer_expenses`` history.

Real Member / Volunteer / Employee / Expense Claim documents are built (no
business-logic mocking). Exercises the live persistence path that was dead
while the child table was archived:

    queue_expense_update / queue_expense_removal
      -> FinancialHistoryBatchProcessor.force_process_all
        -> MemberFinancialHistoryManager(member, "volunteer_expenses")
          -> ExpenseHistoryEntryBuilder.build_from_expense_doc

The hook wiring itself (Expense Claim doc_events -> expense_handlers) is
covered by test_expense_events_coverage.py; here we assert the denormalized
snapshot actually lands on Member.volunteer_expenses.
"""

import frappe
from frappe.utils import today

from verenigingen.utils.financial_history_batch_processor import (
    FinancialHistoryBatchProcessor,
    queue_expense_removal,
    queue_expense_update,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerExpensesHistoryRestore(EnhancedTestCase):
    """Real integration coverage for the restored volunteer_expenses child table."""

    def setUp(self):
        super().setUp()
        # The batch queues are class-level; flush any cross-test residue so a
        # prior test's queued op cannot leak into this member's batch.
        FinancialHistoryBatchProcessor.force_process_all()

    # ------------------------------------------------------------------ helpers
    def _company(self):
        return (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )

    def _accounts(self, company):
        expense = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        return expense, payable

    def _make_employee(self, company):
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"VeR{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _make_volunteer_member_employee(self):
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        member = self.create_test_member(first_name="VExp", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = self._make_employee(company)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        volunteer.reload()
        return member, volunteer, emp, company

    def _make_expense_claim(self, employee, company):
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": 12.5,
                        "sanctioned_amount": 12.5,
                        "expense_date": today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        )
        ec.insert(ignore_permissions=True)
        self._track_test_document("Expense Claim", ec.name, priority=1)
        return ec

    # ------------------------------------------------------------------ tests
    def test_queue_expense_update_persists_history_entry(self):
        """A queued expense update lands a real row on Member.volunteer_expenses."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)

        with self.assertNoErrorLog():
            queue_expense_update(member.name, ec.name)
            FinancialHistoryBatchProcessor.force_process_all()

        member.reload()
        entries = member.get("volunteer_expenses") or []
        self.assertEqual(len(entries), 1, "expected exactly one volunteer_expenses entry")
        row = entries[0]
        self.assertEqual(row.expense_claim, ec.name)
        self.assertEqual(row.volunteer, volunteer.name)
        self.assertEqual(row.total_claimed_amount, 12.5)
        self.assertEqual(row.total_sanctioned_amount, 12.5)
