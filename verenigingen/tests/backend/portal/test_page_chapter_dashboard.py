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
        self.board_email = f"board-{frappe.generate_hash()[:8]}@example.com"
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
