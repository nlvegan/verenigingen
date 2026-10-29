"""Chapter dashboard number cards must not count what the caller cannot list (#1666).

Real users built from the shipped Role Profiles, real Expense Claims in two chapters,
real board seats. The oracle for "what the caller may count" is ``frappe.get_list`` as
that user, i.e. ``get_expense_claim_permission_query`` (maintainer ruling on #1606).

Probe shortcuts, stated: the claims' ``approval_status`` is inserted directly (Approved /
Rejected) instead of being driven through the approval flow; the cards read that field
only, so the flow is not what is under test.
"""

import frappe
from frappe.utils import today

from verenigingen.api import chapter_dashboard_api as api
from verenigingen.tests.security.test_staff_expense_approval_1606 import (
    StaffExpenseBase,
    _roles_shipped_for_profile,
)


class TestDashboardClaimCounts(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.set_national(None)
        emp = self.volunteer_emp
        self.a_approved = self.claim(emp, chapter=self.chapter_a, approval_status="Approved")
        self.a_rejected = self.claim(emp, chapter=self.chapter_a, approval_status="Rejected")
        self.a_draft = self.claim(emp, chapter=self.chapter_a)
        self.b_approved = self.claim(emp, chapter=self.chapter_b, approval_status="Approved")
        self.b_rejected = self.claim(emp, chapter=self.chapter_b, approval_status="Rejected")
        self.national_approved = self.claim(emp, approval_status="Approved")
        self.board_only = self._board_only_user()

    def _board_only_user(self):
        """A chapter board member who is NOT Staff: holds a seat in chapter A only."""
        user = self.create_test_user(
            email=f"x1666-board-{self.token}@test.com",
            roles=_roles_shipped_for_profile("Verenigingen Chapter Board Member"),
        )
        member = self.create_test_member(
            first_name="Brd", last_name="Only", email=user.name, user=user.name
        )
        volunteer = self.create_test_volunteer(member.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Exp Fin1666 {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        ).insert()
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter_a.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()
        return user

    def _filed(self, user, chapter=None):
        return self.act_as(user, lambda: api.get_filed_expense_claims_count(chapter))["value"]

    def _approved(self, user, chapter=None):
        return self.act_as(user, lambda: api.get_approved_expense_claims_count(chapter))["value"]

    def _listable(self, user, chapter, **filters):
        """The oracle: what this user can list, in the card's scope."""
        filters["custom_chapter"] = chapter.name
        return len(
            self.act_as(
                user, lambda: frappe.get_list("Expense Claim", filters=filters, pluck="name", limit_page_length=0)
            )
        )

    # ---------------------------------------------------------------- tests
    def test_board_member_counts_own_chapter_only(self):
        # a_approved + a_rejected are filed, a_draft is not
        self.assertEqual(self._filed(self.board_only, self.chapter_a.name), 2)
        self.assertEqual(self._approved(self.board_only, self.chapter_a.name), 1)
        self.assertEqual(
            self._filed(self.board_only, self.chapter_a.name),
            self._listable(self.board_only, self.chapter_a, approval_status=["!=", "Draft"]),
        )

    def test_no_chapter_argument_equals_the_callers_list(self):
        """The card is the caller's own list: board-only, plain Staff (with a national claim
        it can list) and full-access roles."""
        self.set_national(self.chapter_a)  # Staff and the board member sit on A: national claim visible
        for user in (self.board_only, self.staff, self.treasurer, self.admin):
            with self.subTest(user=user.name):
                listed = lambda **f: len(  # noqa: E731
                    self.act_as(user, lambda: frappe.get_list("Expense Claim", filters=f, pluck="name"))
                )
                self.assertEqual(self._filed(user), listed(approval_status=["!=", "Draft"]))
                self.assertEqual(self._approved(user), listed(approval_status="Approved"))
        # controls: the oracle is not trivially equal everywhere
        self.assertEqual(self._filed(self.board_only), 3, "A (2) + the national claim")
        self.assertGreater(self._filed(self.treasurer), self._filed(self.board_only))

    def test_missing_custom_chapter_field_does_not_raise(self):
        meta = frappe.get_meta("Expense Claim")
        original = meta.has_field
        meta.has_field = lambda f: False if f == "custom_chapter" else original(f)  # Mock justified: simulates an unmigrated site
        try:
            self.assertEqual(self._filed(self.board_only, self.chapter_a.name), 0)
            self.assertEqual(self._filed(self.board_only), 0)
        finally:
            meta.has_field = original

    def test_plain_staff_count_follows_the_permission_query(self):
        # Staff boards chapter A: chapter B's claims are hidden from its list, so from its count
        self.assertEqual(self._filed(self.staff, self.chapter_a.name), 2)
        self.assertEqual(self._filed(self.staff, self.chapter_b.name), 0)
        self.assertEqual(self._approved(self.staff, self.chapter_b.name), 0)
        self.set_national(None)
        self.assertEqual(self._filed(self.staff), 2, "no chapter: still only claims Staff may list")

    def test_full_access_role_still_counts_every_chapter(self):
        # control: the scoping must not under-count a Treasurer, who may list all claims
        self.assertEqual(self._filed(self.treasurer, self.chapter_b.name), 2)
        self.assertEqual(self._approved(self.treasurer, self.chapter_b.name), 1)
        self.assertEqual(self._filed(self.treasurer, self.chapter_a.name), 2)

    def test_board_member_cannot_count_another_chapter(self):
        for fn in (api.get_filed_expense_claims_count, api.get_approved_expense_claims_count):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(frappe.PermissionError):
                    self.act_as(self.board_only, lambda: fn(self.chapter_b.name))

    def test_forbidden_and_unknown_chapter_are_indistinguishable(self):
        def probe(chapter_name):
            log_before = frappe.db.count("Error Log")
            frappe.local.message_log = []  # Mock justified: execution-context reset, not a stub
            try:
                self.act_as(self.board_only, lambda: api.get_filed_expense_claims_count(chapter_name))
            except Exception as e:
                outcome = (type(e).__name__, str(e))
            else:
                outcome = ("returned", None)
            log = [
                {k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log
            ]
            return outcome, log, frappe.db.count("Error Log") - log_before

        forbidden = probe(self.chapter_b.name)
        unknown = probe(f"No Such Chapter {self.token}")
        self.assertEqual(forbidden[0][0], "PermissionError", "control: the forbidden chapter is refused")
        self.assertEqual(forbidden, unknown)

    def test_sibling_member_cards_refuse_a_foreign_chapter(self):
        fns = (
            api.get_active_members_count,
            api.get_pending_applications_count,
            api.get_board_members_count,
            api.get_new_members_count,
        )
        for fn in fns:
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(frappe.PermissionError):
                    self.act_as(self.board_only, lambda: fn(self.chapter_b.name))
                # control: own chapter is answered
                res = self.act_as(self.board_only, lambda: fn(self.chapter_a.name))
                self.assertEqual(res["fieldtype"], "Data")

