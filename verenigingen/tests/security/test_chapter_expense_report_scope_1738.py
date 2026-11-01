"""The Chapter Expense Report must not list Expense Claims the caller could not ``get_list``
(#1738; same rule as the dashboard, #1701, and the #1606 ruling).

The report read every claim with ``frappe.get_all`` and filtered by
``get_user_accessible_chapters()`` with its DEFAULT admin roles, which include Verenigingen
Staff -> ``None`` -> "all chapters". So Staff who also holds the Chapter Board Member role
(the only way a Staff user may open the report) saw every chapter's claims.

Real users from the shipped Role Profiles, real Expense Claims, real board seats, the report's
real ``execute()``. The oracle is ``frappe.get_list`` as that user.

Probe shortcut, stated: the claims' ``custom_organization_type`` is set to "Chapter" directly
on insert (the report only reads it); approval is not driven.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.security.test_staff_expense_approval_1606 import (
    StaffExpenseBase,
    _roles_shipped_for_profile,
)
from verenigingen.verenigingen.report.chapter_expense_report import chapter_expense_report as report


class TestChapterExpenseReportScope(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.set_national(None)
        emp = self.volunteer_emp
        self.a_claims = [self._chapter_claim(emp, self.chapter_a) for _ in range(2)]
        self.b_claims = [self._chapter_claim(emp, self.chapter_b) for _ in range(2)]

        # Staff + Chapter Board Member role, seated on chapter A only (the issue's attacker)
        self.staff_board = self.create_test_user(
            email=f"x1738-sb-{self.token}@test.com",
            roles=_roles_shipped_for_profile("Verenigingen Staff") + ["Verenigingen Chapter Board Member"],
        )
        self._staffexp_employee(self.staff_board)
        self._seat_financial_1738(self.staff_board, self.chapter_a, "sb")
        self.keep_fixture_roles(
            self.staff_board, _roles_shipped_for_profile("Verenigingen Staff") + ["Verenigingen Chapter Board Member"]
        )

        # A board member with no wide role at all
        self.plain_board = self.create_test_user(
            email=f"x1738-pb-{self.token}@test.com",
            roles=_roles_shipped_for_profile("Verenigingen Chapter Board Member"),
        )
        self._staffexp_employee(self.plain_board)
        self._seat_financial_1738(self.plain_board, self.chapter_a, "pb")
        self.keep_fixture_roles(self.plain_board, _roles_shipped_for_profile("Verenigingen Chapter Board Member"))

    def _seat_financial_1738(self, user, chapter, tag):
        """A Financial seat on ``chapter`` (own Chapter Role: staff_boards() reuses one name)."""
        member = self.create_test_member(first_name="Brd", last_name=tag, email=user.name, user=user.name)
        volunteer = self.create_test_volunteer(member.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Rep Fin {tag} {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        ).insert()
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()

    def _chapter_claim(self, employee, chapter):
        claim = self.claim(employee, chapter=chapter)
        frappe.db.set_value("Expense Claim", claim.name, "custom_organization_type", "Chapter")
        return claim

    def _report_ids(self, user):
        def run():
            _cols, data = report.execute({})[:2]
            return {row["name"] for row in data}

        return self.act_as(user, run)

    def test_staff_with_board_role_sees_only_their_chapter_in_the_report(self):
        ids = self._report_ids(self.staff_board)
        for c in self.b_claims:
            self.assertNotIn(c.name, ids)
        # control: the seat on A is real and the report really lists A's claims
        for c in self.a_claims:
            self.assertIn(c.name, ids)

    def test_plain_board_member_sees_only_their_chapter_in_the_report(self):
        ids = self._report_ids(self.plain_board)
        for c in self.b_claims:
            self.assertNotIn(c.name, ids)
        for c in self.a_claims:
            self.assertIn(c.name, ids)

    def test_report_is_a_subset_of_the_callers_list(self):
        mine = {*(c.name for c in self.a_claims), *(c.name for c in self.b_claims)}
        for user in (self.staff_board, self.plain_board, self.treasurer, self.admin):
            with self.subTest(user=user.name):
                self.assertLessEqual(self._report_ids(user) & mine, self.visible_to(user) & mine)

    def test_full_access_roles_still_see_every_chapter(self):
        """Control: scoping must not under-report a Treasurer / Administrator."""
        mine = {*(c.name for c in self.a_claims), *(c.name for c in self.b_claims)}
        for user in (self.treasurer, self.admin):
            with self.subTest(user=user.name):
                self.assertEqual(self._report_ids(user) & mine, mine)

    def test_seat_holder_without_expense_claim_read_gets_an_empty_report_not_an_error(self):
        """A Financial seat on A but roles that carry no Expense Claim read right: get_list would
        refuse, so the report lists nothing (and does not raise). A get_all read would list A."""
        user = self.create_test_user(email=f"x1738-nr-{self.token}@test.com", roles=["Verenigingen Member"])
        self._seat_financial_1738(user, self.chapter_a, "nr")
        self.keep_fixture_roles(user, ["Verenigingen Member"])  # the seat's flush gave the board roles
        self.assertFalse(self.act_as(user, lambda: frappe.has_permission("Expense Claim", "read")))
        self.assertEqual(self._report_ids(user), set())
