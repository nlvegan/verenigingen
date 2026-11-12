"""#1714: a Team expense claim filed through the volunteer portal carries its team's chapter.

The claim is filed through the REAL portal endpoint
(``templates.pages.volunteer.expenses.submit_expense``) as a plain volunteer who holds only the
roles of the shipped Volunteer profile. A chapter Financial seat then looks at it through the
real list query and the doc-level permission, which scope on ``custom_chapter``.

Probe shortcuts, stated: the volunteer's Employee is created up front and linked on
``Volunteer.employee_id`` (the service otherwise creates it itself; that step is not under
test); ``Verenigingen Settings.company`` is set with ``set_single_value`` (the production
reader is the same Single).
"""

import json

import frappe
from frappe.utils import today

from verenigingen.permissions import get_expense_claim_permission_query, has_expense_claim_permission
from verenigingen.templates.pages.volunteer import expenses
from verenigingen.tests.security.test_expense_approval_limits_1651 import LimitBase


class TestPortalTeamExpenseChapter(LimitBase):
    def setUp(self):
        super().setUp()
        self.set_limits(self.chapter, 0, 0)
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        self.category = self._expense_category()
        self.user = self._staffexp_user("Verenigingen Volunteer", "portal")
        self.employee = self._staffexp_employee(self.user)
        member = self.create_test_member(first_name="Por", last_name="Tal", email=self.user.name, user=self.user.name)
        self.volunteer = self.create_test_volunteer(member.name)
        frappe.db.set_value(
            "Volunteer", self.volunteer.name, {"email": self.user.name, "employee_id": self.employee.name}
        )

    def _expense_category(self):
        cat = frappe.new_doc("Expense Category")
        cat.category_name = f"Travel 1714 {self.token}"
        cat.is_active = 1
        cat.expense_account = self.expense_account
        cat.insert()
        self._track_test_document("Expense Category", cat.name, priority=0)
        # The portal files the category NAME as the claim line's Expense Claim Type
        claim_type = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": cat.name,
                "accounts": [{"company": self.company, "default_account": self.expense_account}],
            }
        ).insert()
        self._track_test_document("Expense Claim Type", claim_type.name, priority=1)
        return cat.name

    def _team(self, chapter):
        team = self.create_test_team(chapter=chapter.name if chapter else None)
        self.create_test_team_member(team.name, self.volunteer.name)
        return team

    def _file_through_portal(self, **org):
        payload = {
            "description": "Train ticket",
            "amount": 12.5,
            "expense_date": today(),
            "category": self.category,
            "volunteer": self.volunteer.name,
        }
        payload.update(org)
        original = frappe.session.user
        frappe.set_user(self.user.name)
        try:
            result = expenses.submit_expense(json.dumps(payload))
        finally:
            frappe.set_user(original)
        self.assertTrue(result["success"], result)
        return frappe.get_doc("Expense Claim", result["expense_claim_name"])

    def _sees(self, user, claim):
        original = frappe.session.user
        frappe.set_user(user.name)
        try:
            listed = claim.name in frappe.get_list("Expense Claim", pluck="name", limit_page_length=0)
            return listed, has_expense_claim_permission(claim, user.name)
        finally:
            frappe.set_user(original)

    def _desk_claim_data(self, **fields):
        data = {
            "doctype": "Expense Claim",
            "employee": self.employee.name,
            "company": self.company,
            "posting_date": today(),
            "currency": "EUR",
            "exchange_rate": 1,
            "payable_account": self.payable_account,
            "cost_center": self.cost_center,
            "approval_status": "Draft",
            "expenses": [
                {
                    "expense_type": self.category,
                    "amount": 5,
                    "sanctioned_amount": 5,
                    "expense_date": today(),
                    "default_account": self.expense_account,
                    "cost_center": self.cost_center,
                }
            ],
        }
        data.update(fields)
        return data

    def _insert_as_volunteer(self, **fields):
        original = frappe.session.user
        frappe.set_user(self.user.name)
        try:
            return frappe.get_doc(self._desk_claim_data(**fields)).insert()
        finally:
            frappe.set_user(original)

    def test_a_team_claim_carries_the_teams_chapter_and_its_seat_sees_it(self):
        claim = self._file_through_portal(organization_type="Team", team=self._team(self.chapter).name)
        self.assertEqual(claim.custom_chapter, self.chapter.name)
        self.assertEqual(self._sees(self.fin_user, claim), (True, True))
        self.assertEqual(self._sees(self.user, claim), (True, True), "the filer still sees their claim")

    def test_a_seat_of_another_chapter_does_not_see_the_claim(self):
        other_user, _vol = self.seat_holder("othr", self.chapter_a, "Financial")
        claim = self._file_through_portal(organization_type="Team", team=self._team(self.chapter).name)
        self.assertEqual(self._sees(other_user, claim), (False, False))
        # control: the same seat does see a claim of ITS chapter
        mine = self._file_through_portal(organization_type="Team", team=self._team(self.chapter_a).name)
        self.assertEqual(self._sees(other_user, mine), (True, True))

    def test_the_grouped_portal_endpoint_attributes_team_claims_too(self):
        team = self._team(self.chapter)
        original = frappe.session.user
        frappe.set_user(self.user.name)
        try:
            result = expenses.submit_multiple_expenses(
                json.dumps(
                    [
                        {
                            "description": "Train",
                            "amount": 7,
                            "expense_date": today(),
                            "category": self.category,
                            "organization_type": "Team",
                            "team": team.name,
                        }
                    ]
                )
            )
        finally:
            frappe.set_user(original)
        self.assertTrue(result["success"], result)
        name = result["created_claims"][0]["expense_claim_name"]
        self.assertEqual(frappe.db.get_value("Expense Claim", name, "custom_chapter"), self.chapter.name)

    def test_a_team_without_a_chapter_still_files_and_stays_unattributed(self):
        claim = self._file_through_portal(organization_type="Team", team=self._team(None).name)
        self.assertFalse(claim.custom_chapter)
        self.assertEqual(self._sees(self.fin_user, claim), (False, False))

    def test_the_filer_can_save_the_attributed_claim_again(self):
        claim = self._file_through_portal(organization_type="Team", team=self._team(self.chapter).name)
        original = frappe.session.user
        frappe.set_user(self.user.name)
        try:
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.remark = "edited"
            doc.save()
        finally:
            frappe.set_user(original)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "remark"), "edited")

    def test_the_chapter_gate_still_refuses_a_chapter_that_is_not_the_teams(self):
        """The exemption is for the team's OWN chapter only: a volunteer without a seat on
        chapter_a still cannot file against it, with or without a team of another chapter."""
        team = self._team(self.chapter)
        with self.assertRaises(frappe.exceptions.ValidationError) as raised:
            self._insert_as_volunteer(custom_chapter=self.chapter_a.name, custom_team=team.name)
        self.assertIn("any chapter", str(raised.exception))
        with self.assertRaises(frappe.exceptions.ValidationError):
            self._insert_as_volunteer(custom_chapter=self.chapter_a.name)
        # control: the team's own chapter is accepted
        self.assertTrue(self._insert_as_volunteer(custom_chapter=self.chapter.name, custom_team=team.name).name)
