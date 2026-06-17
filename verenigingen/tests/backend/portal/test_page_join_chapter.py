"""
Tests for the /verenigingen/join-chapter portal page
(verenigingen.templates.pages.verenigingen.join_chapter).

This is a distinct page from /chapter_join: it requires BOTH a website_url and an
introduction and adds the member through chapter_doc.member_manager.add_member()
rather than a direct secure_document_operation save.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageJoinChapter(EnhancedTestCase):
    """Real-data tests for the nested verenigingen/join_chapter page handler."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self._original_request = getattr(frappe.local, "request", None)

        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST JC Chapter {frappe.generate_hash()[:6]}",
            region="Test Region JC",
        )

        self.email = f"joinchap-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Join",
            last_name="Chapter",
            email=self.email,
            birth_date="1990-01-01",
        )
        # Member must be Active for member_manager to enable the chapter row.
        self.member.db_set("status", "Active")
        self.user = self._ensure_member_user(self.email)
        self.member.db_set("user", self.user)

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        frappe.local.request = self._original_request
        super().tearDown()

    def _ensure_member_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Join",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    class _FakeRequest:
        def __init__(self, method):
            self.method = method

    def test_no_chapter_specified_raises(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict()
        frappe.local.request = self._FakeRequest("GET")
        with self.assertRaises(frappe.DoesNotExistError):
            get_context(frappe._dict())

    def test_guest_context_short_circuits(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict({"name": self.chapter.name})
        frappe.local.request = self._FakeRequest("GET")
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertIn(self.chapter.name, ctx.title)
        self.assertNotIn("already_member", ctx)

    def test_logged_in_not_yet_member(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict({"chapter": self.chapter.name})
        frappe.local.request = self._FakeRequest("GET")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertFalse(ctx.already_member)

    def test_post_join_requires_website_url(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict(
            {"chapter": self.chapter.name, "introduction": "Hi there", "website_url": ""}
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

    def test_post_join_requires_introduction(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "",
                "website_url": "https://example.com",
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

    def test_post_join_ignores_attacker_supplied_member(self):
        """IDOR guard: only the session-derived member is added, never a `member`
        smuggled via form_dict."""
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        other = self.create_test_member(
            first_name="Other",
            last_name="JC",
            email=f"joinchap-other-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1985-01-01",
        )
        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "Joining as myself.",
                "website_url": "https://example.com",
                "member": other.name,  # must be ignored
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            get_context(frappe._dict())

        self.assertTrue(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": other.name, "parent": self.chapter.name})
        )

    def test_post_join_terminated_member_added_disabled(self):
        """A non-Active member self-joins disabled/Inactive (cannot self-re-enable)."""
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        self.member.db_set("status", "Terminated")
        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "Rejoining.",
                "website_url": "https://example.com",
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            get_context(frappe._dict())

        row = frappe.db.get_value(
            "Chapter Member",
            {"member": self.member.name, "parent": self.chapter.name},
            ["enabled", "status"],
            as_dict=True,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.enabled, 0)
        self.assertEqual(row.status, "Inactive")

    def test_post_join_adds_chapter_member(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "I would like to contribute.",
                "website_url": "https://example.com",
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.get("join_success"))
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

    def test_has_website_permission(self):
        from verenigingen.templates.pages.verenigingen.join_chapter import has_website_permission

        self.assertFalse(has_website_permission(None, "read", "Guest"))
        self.assertTrue(has_website_permission(None, "read", self.user))
