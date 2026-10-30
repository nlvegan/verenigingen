"""The chapter dashboard page/endpoint must not show Expense Claim figures or rows the
caller could not ``get_list`` (#1701; same rule as the number cards, #1666 / #1606).

Real users from the shipped Role Profiles, real Expense Claims, real board seats. The oracle
is ``frappe.get_list`` as that user (``get_expense_claim_permission_query``).

Probe shortcut, stated: claims' ``approval_status`` is inserted directly (Approved) rather
than driven through the approval flow; the dashboard reads that field only.
"""

import frappe
from frappe.utils import flt, today

from verenigingen.templates.pages import chapter_dashboard as page
from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase

AMOUNT = 12.5


class TestDashboardExpenseScope(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.set_national(None)
        emp = self.volunteer_emp
        self.a_drafts = [self.claim(emp, chapter=self.chapter_a) for _ in range(2)]
        self.b_drafts = [self.claim(emp, chapter=self.chapter_b) for _ in range(2)]
        self.b_approved = self.claim(emp, chapter=self.chapter_b, approval_status="Approved")

    def _dash_1701(self, user, chapter):
        return self.act_as(user, lambda: page._get_chapter_dashboard_data_internal(chapter.name))

    def _oracle_pending(self, user, chapter):
        return self.act_as(
            user,
            lambda: frappe.get_list(
                "Expense Claim",
                filters={"custom_chapter": chapter.name, "approval_status": "Draft", "docstatus": 0},
                pluck="name",
                limit_page_length=0,
            ),
        )

    def _pending_names_1701(self, data):
        return [r["name"] for r in data["pending_actions"]["expense_approvals"]]

    # ---------------------------------------------------------------- premise
    def test_staff_without_a_seat_on_the_chapter_sees_none_of_its_claims(self):
        """Staff boards A only. The page gate still opens B (ADMIN_ROLES)."""
        data = self._dash_1701(self.staff, self.chapter_b)  # control: the gate really admits Staff
        self.assertEqual(self._pending_names_1701(data), [])
        self.assertEqual(data["pending_actions"]["total_pending"], len(data["pending_actions"]["membership_applications"]))
        exp = data["key_metrics"]["expenses"]
        self.assertEqual((exp["pending_count"], exp["pending_amount"]), (0, 0))
        self.assertEqual(exp["ytd_total"], 0)
        self.assertEqual(exp["this_month"], 0)
        fin = data["financial_summary"]
        self.assertEqual(fin["this_month"]["expenses_submitted"], 0)
        self.assertEqual(fin["this_month"]["expenses_approved"], 0)
        self.assertEqual(fin["this_month"]["pending_approval"], 0)
        self.assertEqual(fin["this_month"]["claims_count"], 0)
        self.assertEqual((fin["ytd"]["total_expenses"], fin["ytd"]["total_claims"]), (0, 0))
        self.assertNotIn("error", exp)
        self.assertNotIn("error", fin)

    def test_staff_still_sees_their_own_chapter(self):
        data = self._dash_1701(self.staff, self.chapter_a)
        self.assertCountEqual(self._pending_names_1701(data), [c.name for c in self.a_drafts])
        self.assertEqual(data["key_metrics"]["expenses"]["pending_count"], 2)
        self.assertEqual(flt(data["key_metrics"]["expenses"]["pending_amount"]), 2 * AMOUNT)

    def test_full_access_role_still_sees_every_chapter(self):
        """Control: the scoping must not under-report a Treasurer."""
        data = self._dash_1701(self.treasurer, self.chapter_b)
        self.assertCountEqual(self._pending_names_1701(data), [c.name for c in self.b_drafts])
        self.assertEqual(data["key_metrics"]["expenses"]["pending_count"], 2)
        fin = data["financial_summary"]
        self.assertEqual(flt(fin["this_month"]["expenses_approved"]), AMOUNT)
        self.assertEqual(fin["ytd"]["total_claims"], 1)
        self.assertEqual(flt(fin["this_month"]["expenses_submitted"]), 2 * AMOUNT)

    def test_dashboard_equals_the_callers_list_for_every_role(self):
        for user in (self.staff, self.treasurer, self.admin, self.nbm):
            for chapter in (self.chapter_a, self.chapter_b):
                with self.subTest(user=user.name, chapter=chapter.name):
                    data = self._dash_1701(user, chapter)
                    oracle = self._oracle_pending(user, chapter)
                    self.assertCountEqual(self._pending_names_1701(data), oracle)
                    self.assertEqual(data["key_metrics"]["expenses"]["pending_count"], len(oracle))

    # ---------------------------------------------------------------- cache
    def test_a_warm_cache_from_a_wide_caller_does_not_leak_to_staff(self):
        """The payload sits behind a shared TTL cache: a Treasurer warming chapter B must not
        hand Staff the Treasurer's figures."""

        # The endpoint's body, minus the security-tier decorators these fixture users do not
        # clear (that gate is not what is under test): the cached payload read.
        def call(user):
            return self.act_as(user, lambda: page._cached_chapter_dashboard_payload(self.chapter_b.name))

        wide = call(self.treasurer)
        self.assertEqual(len(self._pending_names_1701(wide)), 2, "control: the warm-up caller sees B's claims")
        narrow = call(self.staff)
        self.assertEqual(self._pending_names_1701(narrow), [])
        self.assertEqual(narrow["key_metrics"]["expenses"]["pending_count"], 0)

    # ---------------------------------------------------------------- page size
    def test_more_than_one_default_page_of_claims_is_counted(self):
        """frappe.get_list pages at 20 by default; get_all did not. 21 claims must all count."""
        extra = [self.claim(self.volunteer_emp, chapter=self.chapter_a) for _ in range(19)]
        data = self._dash_1701(self.treasurer, self.chapter_a)
        self.assertEqual(len(self._pending_names_1701(data)), 2 + len(extra))
        self.assertEqual(data["key_metrics"]["expenses"]["pending_count"], 21)
        self.assertEqual(flt(data["key_metrics"]["expenses"]["pending_amount"]), 21 * AMOUNT)

    # ---------------------------------------------------------------- no read right
    def test_board_member_without_read_right_on_expense_claim_gets_zeros_not_an_error(self):
        """A seat holder whose roles carry no Expense Claim read right: ``get_list`` would
        refuse, so the dashboard shows nothing for claims and NOT the "--" error tile."""
        user = self.create_test_user(
            email=f"x1701-noread-{self.token}@test.com", roles=["Verenigingen Member"]
        )
        member = self.create_test_member(first_name="Brd", last_name="Only", email=user.name, user=user.name)
        volunteer = self.create_test_volunteer(member.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Exp Fin1701 {self.token}",
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
        can_read = self.act_as(user, lambda: frappe.has_permission("Expense Claim", "read"))
        self.assertFalse(can_read, "control: this user really lacks the read right")
        data = self._dash_1701(user, self.chapter_a)  # control: the seat opens the dashboard
        self.assertEqual(self._pending_names_1701(data), [])
        self.assertEqual(data["key_metrics"]["expenses"]["pending_count"], 0)
        self.assertNotIn("error", data["key_metrics"]["expenses"])
        self.assertNotIn("error", data["financial_summary"])
