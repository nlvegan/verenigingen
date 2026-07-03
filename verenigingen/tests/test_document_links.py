"""
Real integration coverage for ``verenigingen/setup/document_links.py``.

The module wires an Expense Claim back to a Member. The meatiest function is
``get_member_from_expense_claim(expense_claim)`` which resolves a Member two ways:

  1. via the ``custom_volunteer`` Custom Field on the Expense Claim
     (Expense Claim.custom_volunteer -> Volunteer.member), checked FIRST, and
  2. via the standard ``employee`` field
     (Expense Claim.employee -> Member.employee), as a legacy fallback.

These tests build real Member / Volunteer / Employee / Expense Claim documents
(no business-logic mocking) and drive both the "found" branches (including the
custom_volunteer-over-employee priority) and every "not found" branch.

The whitelisted helpers are called through their real security-decorated
wrappers. Several are @development_only_api, whose environment gate only passes
in DEVELOPMENT; CI runs without developer_mode (→ PRODUCTION), so setUp enables
developer_mode for the duration of each test and restores it in tearDown.
"""

import frappe
from frappe.utils import today

from verenigingen.setup import document_links as dl
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDocumentLinks(VereningingenTestCase):
    """Integration coverage for setup/document_links.py."""

    _orig_developer_mode = False  # sentinel: "not set"

    def setUp(self):
        super().setUp()
        # Several helpers under test are @development_only_api; their environment
        # gate only passes in DEVELOPMENT. CI runs without developer_mode.
        self._orig_developer_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

    def tearDown(self):
        if self._orig_developer_mode is not False:
            if self._orig_developer_mode is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = self._orig_developer_mode
            self._orig_developer_mode = False
        super().tearDown()

    # ----------------------------------------------------------------- helpers
    def _company(self):
        company = (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        if not company:
            self.skipTest("No Company available")
        return company

    def _accounts(self, company):
        """Return (expense_account, payable_account) for building an Expense Claim."""
        expense = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"root_type": "Expense", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        if not expense or not payable:
            self.skipTest("No expense/payable accounts available for company")
        return expense, payable

    def _expense_type(self):
        return (
            "Food"
            if frappe.db.exists("Expense Claim Type", "Food")
            else (frappe.get_all("Expense Claim Type", limit=1, pluck="name") or [None])[0]
        )

    def _make_employee(self, company):
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"DL{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Employee", emp.name)
        return emp

    def _make_expense_claim(self, employee, company, custom_volunteer=None):
        expense_acct, payable = self._accounts(company)
        expense_type = self._expense_type()
        if not expense_type:
            self.skipTest("No Expense Claim Type available")
        data = {
            "doctype": "Expense Claim",
            "employee": employee.name,
            "company": company,
            "posting_date": today(),
            "currency": "EUR",
            "exchange_rate": 1,
            "payable_account": payable,
            "expenses": [
                {
                    "expense_type": expense_type,
                    "amount": 12.5,
                    "sanctioned_amount": 12.5,
                    "expense_date": today(),
                    "default_account": expense_acct,
                }
            ],
        }
        if custom_volunteer:
            data["custom_volunteer"] = custom_volunteer
        ec = frappe.get_doc(data).insert(ignore_permissions=True)
        self.track_doc("Expense Claim", ec.name)
        return ec

    def _member_with_employee(self, employee):
        member = self.create_test_member()
        member.db_set("employee", employee.name, update_modified=False)
        return member

    # ============================================================ custom_volunteer
    def test_resolves_member_via_custom_volunteer(self):
        """custom_volunteer -> Volunteer.member is the direct resolution path."""
        company = self._company()
        emp = self._make_employee(company)
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=member.name)
        ec = self._make_expense_claim(emp, company, custom_volunteer=volunteer.name)

        result = dl.get_member_from_expense_claim(ec.name)
        self.assertEqual(result, member.name)

    def test_custom_volunteer_takes_priority_over_employee(self):
        """When BOTH links exist, the custom_volunteer path wins over employee.

        The Expense Claim's employee maps (via Member.employee) to `emp_member`,
        while its custom_volunteer maps to `vol_member`. The function must return
        the volunteer's member, proving the ordering in the source.
        """
        company = self._company()
        emp = self._make_employee(company)
        emp_member = self._member_with_employee(emp)  # reachable via employee branch

        vol_member = self.create_test_member()
        volunteer = self.create_test_volunteer(member=vol_member.name)

        ec = self._make_expense_claim(emp, company, custom_volunteer=volunteer.name)

        result = dl.get_member_from_expense_claim(ec.name)
        self.assertEqual(result, vol_member.name)
        self.assertNotEqual(result, emp_member.name)

    def test_custom_volunteer_without_member_falls_through_to_employee(self):
        """A volunteer with no linked member falls through to the employee lookup."""
        company = self._company()
        emp = self._make_employee(company)
        member = self._member_with_employee(emp)
        # Volunteer with NO member link (member field is optional on Volunteer).
        volunteer = self.create_test_volunteer(member=None)
        volunteer.db_set("member", "", update_modified=False)

        ec = self._make_expense_claim(emp, company, custom_volunteer=volunteer.name)

        result = dl.get_member_from_expense_claim(ec.name)
        self.assertEqual(result, member.name)

    # ================================================================== employee
    def test_resolves_member_via_employee_fallback(self):
        """With no custom_volunteer, resolution falls back to Member.employee."""
        company = self._company()
        emp = self._make_employee(company)
        member = self._member_with_employee(emp)
        ec = self._make_expense_claim(emp, company)  # no custom_volunteer

        result = dl.get_member_from_expense_claim(ec.name)
        self.assertEqual(result, member.name)

    def test_returns_none_when_employee_has_no_member(self):
        """An Expense Claim whose employee is not linked to any Member -> None."""
        company = self._company()
        emp = self._make_employee(company)  # no Member points at this employee
        ec = self._make_expense_claim(emp, company)

        self.assertIsNone(dl.get_member_from_expense_claim(ec.name))

    # ============================================================= edge / errors
    def test_returns_none_for_empty_input(self):
        self.assertIsNone(dl.get_member_from_expense_claim(None))
        self.assertIsNone(dl.get_member_from_expense_claim(""))

    def test_returns_none_for_nonexistent_expense_claim(self):
        """A bogus Expense Claim name is swallowed (DoesNotExistError) -> None + log."""
        self.expectErrorLog("Document Links Error")
        result = dl.get_member_from_expense_claim("EXP-CLAIM-DOES-NOT-EXIST-9999")
        self.assertIsNone(result)

    # ============================================================ setup / wiring
    def test_setup_custom_document_links_runs_cleanly(self):
        """The boot-hook entrypoint runs without raising and returns None."""
        with self.assertNoErrorLog():
            self.assertIsNone(dl.setup_custom_document_links())

    def test_add_member_ledger_link_is_idempotent(self):
        """Adding the Member ledger link twice does not raise (safe to re-run)."""
        with self.assertNoErrorLog():
            self.assertIsNone(dl.add_member_ledger_link_to_expense_claim())
            self.assertIsNone(dl.add_member_ledger_link_to_expense_claim())

    # ============================================================ test_document_links
    def test_test_document_links_reports_a_real_resolution(self):
        """The whitelisted diagnostic helper returns a well-formed dict.

        We seed a Member <- Employee <- Expense Claim chain so at least one
        Expense-Claim-with-employee exists, then assert the returned dict shape.
        The helper picks an arbitrary such claim, so we only assert the contract,
        not a specific member.
        """
        company = self._company()
        emp = self._make_employee(company)
        self._member_with_employee(emp)
        self._make_expense_claim(emp, company)

        result = dl.test_document_links()
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)
        if result["success"]:
            for key in ("expense_claim", "employee", "member_found", "message"):
                self.assertIn(key, result)
