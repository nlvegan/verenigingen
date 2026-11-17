"""The volunteer expense portal reads Expense Claims through ``get_list`` (#1819).

``get_volunteer_expenses_from_claims`` and both ``get_volunteer_expense_statistics`` variants
took the claims of ``Volunteer.employee_id`` with ``frappe.get_all`` / raw SQL, i.e. WITHOUT the
Expense Claim permission query. The page resolves the caller's own volunteer, so the only way to see someone else's claims
is a volunteer whose ``employee_id`` points at an Employee that is not the caller's own. A real
flow produces that: a board member (shipped role, Volunteer write) can set ``employee_id`` to
another person's Employee with an ordinary ``save()`` / REST PUT, because ``read_only`` is not
enforced server-side (the repoint itself is filed as #2752). Such a volunteer must not read
that Employee's claims.

Users are built from the shipped ``Verenigingen Volunteer`` Role Profile (no blanket Expense
Claim access) and the entry points are the real page ``get_context`` functions.

Probe shortcut, stated: the mis-linked volunteer's ``employee_id`` is set with
``frappe.db.set_value`` as a stand-in for that REST write (the repoint flow is #2752's, not
driven here). The owner's own link is the real one.
"""

import importlib

import frappe

from verenigingen.services.volunteer import (
    volunteer_expense_portal_utils as portal,
    volunteer_statistics as stats,
)
from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase

# the page directory is hyphenated, so it cannot be imported by name
new_page = importlib.import_module("verenigingen.templates.pages.volunteer-portal.expense_claim_new")


class TestVolunteerClaimReadScope(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.owner, self.owner_vol, self.owner_emp = self._volunteer_user("own")
        self.victim, self.victim_vol, self.victim_emp = self._volunteer_user("vic")
        self.owner_claims = [self.claim(self.owner_emp) for _ in range(2)]
        self.victim_claims = [self.claim(self.victim_emp) for _ in range(3)]

        # The repointed shape (probe shortcut, see module docstring): a volunteer pointing at the
        # victim's Employee while logged in as somebody else.
        self.mislinked, self.mislinked_vol, _emp = self._volunteer_user("mis")
        frappe.db.set_value("Volunteer", self.mislinked_vol.name, "employee_id", self.victim_emp.name)

    def _volunteer_user(self, tag):
        user = self._staffexp_user("Verenigingen Volunteer", f"v1819{tag}")
        member = self.create_test_member(first_name="Vol", last_name=tag, email=user.name, user=user.name)
        volunteer = self.create_test_volunteer(member.name)
        employee = self._staffexp_employee(user)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee.name)
        return user, volunteer, employee

    def _page_context(self, user):
        return self.act_as(user, lambda: portal.build_base_expense_context(frappe._dict()))

    # ------------------------------------------------------------ preconditions
    def test_control_the_volunteer_user_has_no_blanket_claim_access(self):
        self.assertFalse(
            self.act_as(
                self.mislinked,
                lambda: frappe.has_permission("Expense Claim", "read", doc=self.victim_claims[0].name),
            ),
            "control: the caller cannot read the victim's claim",
        )
        self.assertTrue(
            self.act_as(
                self.owner,
                lambda: frappe.has_permission("Expense Claim", "read", doc=self.owner_claims[0].name),
            ),
            "control: the owner can read their own claim (so get_list is not trivially empty)",
        )

    # ------------------------------------------------------------ the owner keeps their view
    def test_owner_still_sees_own_claims_in_list_stats_and_pages(self):
        listed = self.act_as(
            self.owner, lambda: portal.get_volunteer_expenses_from_claims(self.owner_vol.name)
        )
        self.assertEqual(len(listed), len(self.owner_claims))
        stat_page, _dbg = self.act_as(
            self.owner, lambda: portal.get_volunteer_expense_statistics(self.owner_vol.name)
        )
        self.assertEqual(stat_page["total_count"], len(self.owner_claims))
        stat_svc = self.act_as(
            self.owner, lambda: stats.get_volunteer_expense_statistics(self.owner_vol.name)
        )
        self.assertEqual(stat_svc["total_count"], len(self.owner_claims))
        ctx = self._page_context(self.owner)
        self.assertEqual(len(ctx.recent_expenses), len(self.owner_claims))
        self.assertEqual(ctx.expense_stats["total_count"], len(self.owner_claims))
        new_ctx = self.act_as(self.owner, lambda: new_page.get_context(frappe._dict()))
        self.assertEqual(new_ctx.expense_stats["total_count"], len(self.owner_claims))

    # ------------------------------------------------------------ the mis-linked caller does not
    def test_list_refuses_the_other_employees_claims(self):
        listed = self.act_as(
            self.mislinked, lambda: portal.get_volunteer_expenses_from_claims(self.mislinked_vol.name)
        )
        self.assertEqual(listed, [])

    def test_portal_statistics_do_not_count_the_other_employees_claims(self):
        stat, _dbg = self.act_as(
            self.mislinked, lambda: portal.get_volunteer_expense_statistics(self.mislinked_vol.name)
        )
        self.assertEqual(stat["total_count"], 0)
        self.assertEqual(stat["total_submitted"], 0)

    def test_service_statistics_do_not_count_the_other_employees_claims(self):
        stat = self.act_as(
            self.mislinked, lambda: stats.get_volunteer_expense_statistics(self.mislinked_vol.name)
        )
        self.assertEqual(stat["total_count"], 0)
        summary = self.act_as(
            self.mislinked, lambda: stats.get_volunteer_expense_summary(self.mislinked_vol.name)
        )
        self.assertEqual(summary["recent_count"], 0)

    def test_real_page_contexts_show_nothing_of_the_other_employee(self):
        ctx = self._page_context(self.mislinked)
        self.assertEqual(ctx.recent_expenses, [])
        self.assertEqual(ctx.expense_stats["total_count"], 0)
        new_ctx = self.act_as(self.mislinked, lambda: new_page.get_context(frappe._dict()))
        self.assertEqual(new_ctx.expense_stats["total_count"], 0)
