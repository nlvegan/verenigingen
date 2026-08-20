"""
Tests for the chapter board dashboard page controller
(verenigingen.templates.pages.chapter_dashboard).

Covers get_context (login + board-membership gating, chapter selection),
get_user_board_chapters / get_user_board_role (admin vs board-member vs none),
the pure get_role_permissions mapping, and the data-assembly helpers
(_get_chapter_dashboard_data_internal + access gating, get_chapter_basic_info,
get_chapter_key_metrics) against real chapter/member/board data.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageChapterDashboard(EnhancedTestCase):
    """Real-data tests for the chapter dashboard."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict

        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST Dash Chapter {frappe.generate_hash()[:6]}",
            region="Test Region Dash",
        )

        # A board member: member -> volunteer -> Chapter Board Member row.
        # Trailing digit is load-bearing - see test_chapter_board_chapters.setUp.
        # EnhancedTestDataFactory.create_member() rewrites a supplied email unless the
        # last 5 characters of the local part contain a digit, so a bare hex run-id
        # diverges Member.email from the login user on ~1 run in 135. That divergence
        # is what made test_board_member_sees_their_chapter fail intermittently; it is
        # exercised deliberately in
        # test_board_role_resolves_when_member_email_differs_from_login_user instead.
        self.board_email = f"board-{frappe.generate_hash()[:8]}0@example.com"
        self.board_member = self.create_test_member(
            first_name="Board",
            last_name="Member",
            email=self.board_email,
            birth_date="1985-01-01",
        )
        self.board_member.db_set("status", "Active")
        self.board_user = self._ensure_user(self.board_email, "Board")
        self.board_member.db_set("user", self.board_user)
        self.volunteer = self.create_test_volunteer(member_name=self.board_member.name)

        self._ensure_chapter_role("Chapter Head")
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": self.volunteer.name,
                "chapter_role": "Chapter Head",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        super().tearDown()

    def _ensure_user(self, email, first_name):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": first_name,
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _ensure_chapter_role(self, role_name):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert(
                ignore_permissions=True
            )

    # ----- get_role_permissions (pure) ---------------------------------

    def test_get_role_permissions_known_roles(self):
        from verenigingen.templates.pages.chapter_dashboard import get_role_permissions

        head = get_role_permissions("Chapter Head")
        self.assertTrue(head["can_manage_board"])
        self.assertEqual(head["expense_limit"], 1000)

        treasurer = get_role_permissions("Treasurer")
        self.assertTrue(treasurer["can_view_finances"])
        self.assertFalse(treasurer["can_manage_board"])

        secretary = get_role_permissions("Secretary")
        self.assertTrue(secretary["can_approve_members"])
        self.assertFalse(secretary["can_view_finances"])

    def test_get_role_permissions_unknown_role_defaults(self):
        from verenigingen.templates.pages.chapter_dashboard import get_role_permissions

        perms = get_role_permissions("Some Unknown Role")
        self.assertFalse(perms["can_approve_members"])
        self.assertEqual(perms["expense_limit"], 0)

    # ----- get_user_board_chapters / get_user_board_role ---------------

    def test_board_member_sees_their_chapter(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            get_user_board_chapters,
            get_user_board_role,
        )

        with self.as_user(self.board_user):
            chapters = get_user_board_chapters()
            self.assertTrue(any(c["chapter_name"] == self.chapter.name for c in chapters))

            role = get_user_board_role(self.chapter.name)
            self.assertEqual(role["role"], "Chapter Head")
            self.assertTrue(role["permissions"]["can_manage_board"])

    def test_board_role_resolves_when_member_email_differs_from_login_user(self):
        """The board-role gate must resolve the member by user, not by email alone.

        get_user_board_role() used to query Member.email only, which disagreed with
        both assign_chapter_board_role() and the sibling get_user_board_chapters():
        a board member whose login user differs from their contact email was granted
        the role and then read here as having none. That gates board mutations, so it
        is an access-control answer, not a display detail.

        This is also the mechanism behind the intermittent board-chapter failures.
        EnhancedTestDataFactory.create_member() appends a unique suffix to a supplied
        email unless the last 5 characters of the local part contain a digit, so a
        test using a hex run-id silently produced Member.email != Member.user on about
        1 run in 135 - and only on those runs did the two helpers disagree. This test
        forces that divergence instead of waiting for the lottery.
        """
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_role

        contact_email = f"contact-{frappe.generate_hash()[:8]}@example.com"
        self.board_member.db_set("email", contact_email)
        self.assertNotEqual(
            frappe.db.get_value("Member", self.board_member.name, "email"),
            frappe.db.get_value("Member", self.board_member.name, "user"),
            "the divergence under test must actually be in place",
        )

        with self.as_user(self.board_user):
            role = get_user_board_role(self.chapter.name)

        self.assertIsNotNone(
            role,
            "Board role resolved to None because the member was looked up by email "
            "alone; it must fall back through Member.user like the rest of the app.",
        )
        self.assertEqual(role["role"], "Chapter Head")

    def test_non_board_user_sees_no_chapters(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            get_user_board_chapters,
            get_user_board_role,
        )

        other_email = f"plain-{frappe.generate_hash()[:8]}@example.com"
        plain_member = self.create_test_member(
            first_name="Plain",
            last_name="User",
            email=other_email,
            birth_date="1990-01-01",
        )
        plain_member.db_set("user", self._ensure_user(other_email, "Plain"))

        with self.as_user(other_email):
            self.assertEqual(get_user_board_chapters(), [])
            self.assertIsNone(get_user_board_role(self.chapter.name))

    def test_admin_sees_all_chapters_with_admin_role(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            get_user_board_chapters,
            get_user_board_role,
        )

        admin = self.ensure_test_admin_user()
        with self.as_user(admin.email):
            chapters = get_user_board_chapters()
            self.assertTrue(any(c["chapter_name"] == self.chapter.name for c in chapters))
            role = get_user_board_role(self.chapter.name)
            self.assertEqual(role["role"], "System Administrator")

    # ----- get_context -------------------------------------------------

    def test_context_rejected_for_non_board_member(self):
        from verenigingen.templates.pages.chapter_dashboard import get_context

        other_email = f"plain2-{frappe.generate_hash()[:8]}@example.com"
        plain_member = self.create_test_member(
            first_name="Plain2",
            last_name="User",
            email=other_email,
            birth_date="1990-01-01",
        )
        plain_member.db_set("user", self._ensure_user(other_email, "Plain2"))

        frappe.form_dict = frappe._dict()
        with self.as_user(other_email):
            ctx = frappe._dict()
            ctx.no_cache = 0  # make hasattr(context, "no_cache") true (mimics page render)
            get_context(ctx)

        self.assertTrue(ctx.get("error_message"))
        self.assertIsNone(ctx.get("selected_chapter"))

    def test_context_board_member_happy_path(self):
        from verenigingen.templates.pages.chapter_dashboard import get_context

        frappe.form_dict = frappe._dict({"chapter": self.chapter.name})
        with self.as_user(self.board_user):
            ctx = frappe._dict()
            ctx.no_cache = 0
            get_context(ctx)

        self.assertEqual(ctx.selected_chapter, self.chapter.name)
        self.assertEqual(ctx.chapter_name, self.chapter.name)
        self.assertTrue(ctx.has_data)
        self.assertIsNotNone(ctx.dashboard_data)
        self.assertEqual(ctx.user_board_role["role"], "Chapter Head")

    def test_context_invalid_chapter_falls_back_to_first(self):
        from verenigingen.templates.pages.chapter_dashboard import get_context

        # Request a chapter the user has no access to -> falls back to user's first.
        frappe.form_dict = frappe._dict({"chapter": "Not-A-Real-Chapter"})
        with self.as_user(self.board_user):
            ctx = frappe._dict()
            ctx.no_cache = 0
            get_context(ctx)

        self.assertEqual(ctx.selected_chapter, self.chapter.name)

    # ----- data-assembly internals -------------------------------------

    def test_internal_data_denies_chapter_without_access(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            _get_chapter_dashboard_data_internal,
        )

        # A second chapter the board user is NOT on.
        other_chapter = self.create_test_chapter(
            chapter_name=f"TEST Dash Other {frappe.generate_hash()[:6]}",
            region="Test Region Dash2",
        )
        with self.as_user(self.board_user):
            with self.assertRaises(frappe.ValidationError):
                _get_chapter_dashboard_data_internal(other_chapter.name)

    def test_internal_data_full_payload_for_board_chapter(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            _get_chapter_dashboard_data_internal,
        )

        with self.as_user(self.board_user):
            data = _get_chapter_dashboard_data_internal(self.chapter.name)

        for key in (
            "chapter_info",
            "key_metrics",
            "member_overview",
            "pending_actions",
            "financial_summary",
            "dues_payment_status",
            "board_info",
            "recent_activity",
            "last_updated",
        ):
            self.assertIn(key, data)

        # Board info should include our board member.
        self.assertEqual(data["board_info"]["total_count"], 1)
        self.assertEqual(data["chapter_info"]["name"], self.chapter.name)

    def test_get_chapter_key_metrics_counts_members(self):
        from verenigingen.templates.pages.chapter_dashboard import get_chapter_key_metrics

        # Use a dedicated chapter so board-member auto-sync doesn't collide with
        # the explicit chapter-member row we add here.
        chapter = self.create_test_chapter(
            chapter_name=f"TEST Metrics Chapter {frappe.generate_hash()[:6]}",
            region="Test Region Metrics",
        )
        extra_email = f"cmember-{frappe.generate_hash()[:8]}@example.com"
        extra_member = self.create_test_member(
            first_name="Chapter",
            last_name="Member",
            email=extra_email,
            birth_date="1992-01-01",
        )
        extra_member.db_set("status", "Active")

        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "members",
            {
                "member": extra_member.name,
                "chapter_join_date": frappe.utils.today(),
                "enabled": 1,
                "status": "Active",
            },
        )
        chapter_doc.save()

        metrics = get_chapter_key_metrics(chapter.name)
        self.assertEqual(metrics["members"]["total"], 1)
        self.assertEqual(metrics["members"]["active"], 1)
        self.assertIn("expenses", metrics)


class TestChapterDashboardPendingExpenseApprovals(EnhancedTestCase):
    """get_pending_expense_approvals + its wiring into get_pending_actions.

    Builds real ERPNext Expense Claim documents (no mocks); skips only when the
    site lacks the Company/accounts needed to construct one. Previously the
    dashboard hardcoded expense_approvals=[] so the "Expense Approvals (N)"
    header always showed 0.
    """

    def setUp(self):
        super().setUp()
        # Inserting an Expense Claim enqueues a member-history update on a
        # process-global batch queue. Clear it before/after so this test's
        # (rolled-back) claims can't be re-processed by a later test ->
        # DoesNotExistError -> swallowed log_error -> Error-Log guard trip.
        from verenigingen.utils.financial_history_batch_processor import (
            FinancialHistoryBatchProcessor,
        )

        self._batch = FinancialHistoryBatchProcessor
        self._batch._expense_queue.clear()

    def tearDown(self):
        self._batch._expense_queue.clear()
        super().tearDown()

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

    def _make_draft_expense_claim(self, company, chapter_name, amount=12.5):
        """A Draft (docstatus=0, approval_status=Draft) Expense Claim on chapter_name."""
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        employee = self._make_employee(company)
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
                "custom_organization_type": "Chapter",
                "custom_chapter": chapter_name,
                # HRMS defaults approval_status to "Draft" on a real request; the
                # test harness skips that field default, so set it explicitly to
                # reflect the production state a pending claim actually has.
                "approval_status": "Draft",
                "posting_date": frappe.utils.today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": amount,
                        "sanctioned_amount": amount,
                        "expense_date": frappe.utils.today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        ).insert(ignore_permissions=True)
        # Drained highest-first. Cancelling a submitted Expense Claim reads its
        # employee as the GL party, so the claim must outrank the Employee (2)
        # it points at -- see DRAIN_PRIORITY_BY_DOCTYPE.
        self._track_test_document("Expense Claim", ec.name, priority=6)
        return ec

    # ------------------------------------------------------------------ tests
    def test_returns_draft_claim_for_chapter_with_fields(self):
        from verenigingen.templates.pages.chapter_dashboard import get_pending_expense_approvals

        company = self._company()
        if not company:
            self.skipTest("No Company available")
        chapter = self.create_test_chapter()
        ec = self._make_draft_expense_claim(company, chapter.name, amount=12.5)

        rows = get_pending_expense_approvals(chapter.name)
        matched = [r for r in rows if r["name"] == ec.name]
        self.assertEqual(len(matched), 1, "draft claim for this chapter should be listed")
        self.assertEqual(matched[0]["total_claimed_amount"], 12.5)
        # Fields the template renders must be present.
        for field in ("name", "employee_name", "custom_volunteer", "posting_date"):
            self.assertIn(field, matched[0])

    def test_excludes_other_chapter_and_non_draft(self):
        from verenigingen.templates.pages.chapter_dashboard import get_pending_expense_approvals

        company = self._company()
        if not company:
            self.skipTest("No Company available")
        chapter = self.create_test_chapter()
        other_chapter = self.create_test_chapter()

        # Claim on a different chapter -> must not leak in.
        other_claim = self._make_draft_expense_claim(company, other_chapter.name)
        # Claim on our chapter but no longer Draft -> excluded by approval_status filter.
        approved_claim = self._make_draft_expense_claim(company, chapter.name)
        frappe.db.set_value("Expense Claim", approved_claim.name, "approval_status", "Approved")

        names = [r["name"] for r in get_pending_expense_approvals(chapter.name)]
        self.assertNotIn(other_claim.name, names)
        self.assertNotIn(approved_claim.name, names)

    def test_wired_into_get_pending_actions(self):
        from verenigingen.templates.pages.chapter_dashboard import (
            get_pending_actions,
            get_pending_expense_approvals,
        )

        company = self._company()
        if not company:
            self.skipTest("No Company available")
        chapter = self.create_test_chapter()
        ec = self._make_draft_expense_claim(company, chapter.name)

        actions = get_pending_actions(chapter.name)
        approval_names = [r["name"] for r in actions["expense_approvals"]]
        self.assertIn(
            ec.name,
            approval_names,
            "get_pending_actions must surface real pending claims (was hardcoded [])",
        )
        # total_pending must account for the expense approvals it reports.
        self.assertEqual(
            actions["total_pending"],
            len(actions["membership_applications"])
            + len(actions["expense_approvals"])
            + len(actions["board_tasks"]),
        )
        self.assertEqual(len(actions["expense_approvals"]), len(get_pending_expense_approvals(chapter.name)))
