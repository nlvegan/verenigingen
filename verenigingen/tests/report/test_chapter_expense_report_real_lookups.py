"""Real-DB tests for the *Chapter Expense Report*'s organisation / volunteer lookups.

``get_erpnext_expense_data`` resolves three display values out of an Expense
Claim's custom fields, and all three named a DocType that does not exist (#677):

===========================================  ==================================
``frappe.db.get_value("Verenigingen Chapter", ...)``   the doctype is ``Chapter``
``frappe.db.get_value("Verenigingen Volunteer Team", ...)``  the doctype is ``Team``
``frappe.db.get_value("Verenigingen Volunteer", ...)``  the doctype is ``Volunteer``
===========================================  ==================================

The issue that reported them predicted the first two would "fall through to
``or claim.get(...)``". Measured on ``test_site_5`` instead of read from the
source, they do not: unlike ``frappe.db.exists`` -- which routes through
``frappe.db.sql(..., ignore=True)`` and swallows the missing-table error --
``frappe.db.get_value`` lets MariaDB 1146 out::

    db.exists("Verenigingen Chapter", {...})              -> None
    db.get_value("Verenigingen Chapter", "x", "y")        -> ProgrammingError 1146
    db.set_value("Verenigingen Volunteer", ...)           -> ProgrammingError 1146

Neither call site is inside a ``try``, and ``execute`` -> ``get_data`` ->
``get_erpnext_expense_data`` adds none, so the whole report raised for any
Expense Claim carrying a Chapter or a Team. The third site *is* wrapped in
``except Exception: pass``, which is why the ``Volunteer`` column silently read
the employee name instead.

The existing suites could not see any of this: both
``tests/report/test_chapter_expense_report_gapfill.py`` and
``tests/backend/components/test_chapter_expense_report_unit.py`` patch
``get_erpnext_expense_data`` itself -- the function that holds the bug -- so the
lookups never run. This file builds a real Expense Claim and calls it.

Also pinned here: ``Chapter`` has **no** ``chapter_name`` field
(``autoname: prompt``, so the docname *is* the chapter name). Renaming the
doctype alone would have turned 1146 into 1054 "Unknown column 'chapter_name'",
which is why that call site drops the lookup rather than correcting it.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen.report.chapter_expense_report import chapter_expense_report as report


class TestChapterExpenseReportRealLookups(EnhancedTestCase):
    """Exercise the three doctype lookups against real rows."""

    def _employee(self, company):
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Exp{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _expense_claim(self, employee, company, **custom):
        # Inlined rather than lifted into an `_accounts` helper: six test files
        # already carry a near-identical private copy of exactly that, and the
        # duplicate-helper ratchet blocks a seventh -- correctly, since a
        # copy-pasted helper is where a fix goes to die.
        expense_acct = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available on the test company")
        claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
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
                **custom,
            }
        )
        claim.insert(ignore_permissions=True)
        # Drained highest-first: the claim reads its employee as the GL party on
        # cancel, so it must outrank the Employee (2) it points at.
        self._track_test_document("Expense Claim", claim.name, priority=6)
        return claim

    def _claim_row(self, claim_name):
        rows = report.get_erpnext_expense_data({})
        row = next((r for r in rows if r["name"] == claim_name), None)
        self.assertIsNotNone(row, f"the seeded Expense Claim {claim_name} must appear in the report data")
        return row

    def test_chapter_claim_reports_the_chapter_name(self):
        """Red on develop with ProgrammingError 1146 on `tabVerenigingen Chapter`."""
        company = get_eur_test_company()
        chapter = self.create_test_chapter()
        employee = self._employee(company)
        claim = self._expense_claim(
            employee, company, custom_organization_type="Chapter", custom_chapter=chapter.name
        )

        row = self._claim_row(claim.name)
        self.assertEqual(row["organization_type"], "Chapter")
        self.assertEqual(
            row["organization_name"],
            chapter.name,
            "Chapter autonames on prompt, so the docname is the chapter's name",
        )

    def test_team_claim_reports_the_team_name(self):
        """Red on develop with ProgrammingError 1146 on `tabVerenigingen Volunteer Team`."""
        company = get_eur_test_company()
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Test Expense Team {frappe.generate_hash(length=6)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Team", team.name, priority=3)
        employee = self._employee(company)
        claim = self._expense_claim(
            employee, company, custom_organization_type="Team", custom_team=team.name
        )

        row = self._claim_row(claim.name)
        self.assertEqual(row["organization_type"], "Team")
        self.assertEqual(row["organization_name"], team.team_name)

    def test_volunteer_name_comes_from_the_volunteer_not_the_employee(self):
        """The swallowed third site: `except Exception: pass` left this at the employee name."""
        company = get_eur_test_company()
        member = self.create_test_member(first_name="Expense", last_name="Claimant")
        volunteer = self.create_test_volunteer(member=member.name)
        employee = self._employee(company)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee.name)
        volunteer.reload()
        claim = self._expense_claim(employee, company, custom_organization_type="National")

        row = self._claim_row(claim.name)
        self.assertEqual(
            row["volunteer_name"],
            volunteer.volunteer_name,
            "the volunteer linked by employee_id must name the row, not the Employee",
        )
        self.assertNotEqual(
            row["volunteer_name"],
            employee.employee_name,
            "control: the Employee fallback and the Volunteer name must be distinguishable, "
            "or this test cannot tell the fix from the bug",
        )
