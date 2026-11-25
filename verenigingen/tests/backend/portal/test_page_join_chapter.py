"""
Tests for the /verenigingen/join-chapter portal page
(verenigingen.templates.pages.verenigingen.join_chapter).

This is a distinct page from /chapter_join: it requires BOTH a website_url and an
introduction. Since #3273 a POST files a Pending Chapter Join Request through
api.chapter_join.join_chapter (board approval applies); it never adds the Chapter Member row.
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

    def _join_requests_3273(self, member=None):
        return frappe.get_all(
            "Chapter Join Request",
            filters={"member": member or self.member.name, "chapter": self.chapter.name},
            fields=["name", "status", "docstatus"],
        )

    def _chapter_member_rows_3273(self, member=None):
        return frappe.db.exists(
            "Chapter Member", {"member": member or self.member.name, "parent": self.chapter.name}
        )

    def _post_3273(self, user=None, **form):
        from verenigingen.templates.pages.verenigingen.join_chapter import get_context

        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "I would like to contribute.",
                "website_url": "https://example.com",
                **form,
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        ctx = frappe._dict()
        with self.as_user(user or self.user):
            get_context(ctx)
        return ctx

    class _FakeRequest:
        """A real werkzeug Request: join_chapter's security decorators read headers/IP."""

        def __new__(cls, method):
            from werkzeug.test import EnvironBuilder
            from werkzeug.wrappers import Request

            return Request(EnvironBuilder(method=method, path="/chapter_join").get_environ())

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
        """IDOR guard: only the session-derived member gets a request, never a `member`
        smuggled via form_dict."""
        other = self.create_test_member(
            first_name="Other",
            last_name="JC",
            email=f"joinchap-other-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1985-01-01",
        )
        other.db_set("status", "Active")
        self._post_3273(member=other.name)  # must be ignored

        self.assertEqual(len(self._join_requests_3273()), 1)
        self.assertEqual(self._join_requests_3273(other.name), [])
        self.assertFalse(self._chapter_member_rows_3273(other.name))

    def test_post_join_non_active_member_is_refused(self):
        """A non-Active member gets neither a request nor a Chapter Member row (#2021)."""
        self.member.db_set("status", "Terminated")
        self.expectErrorLog("Error in chapter join request")
        self.expectErrorLog("Chapter Join Request Error")
        ctx = self._post_3273()
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(ctx.get("join_success"))
        self.assertEqual(self._join_requests_3273(), [])
        self.assertFalse(self._chapter_member_rows_3273())

    def test_post_join_files_pending_request_not_chapter_member(self):
        """#3273: the POST files a Pending, submitted Chapter Join Request for the session
        member and this chapter, and adds NO Chapter Member row (board approval applies)."""
        ctx = self._post_3273()

        self.assertTrue(ctx.get("join_success"), msg=ctx.get("join_error"))
        requests = self._join_requests_3273()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].status, "Pending")
        self.assertEqual(requests[0].docstatus, 1)
        self.assertFalse(self._chapter_member_rows_3273())
        intro = frappe.db.get_value("Chapter Join Request", requests[0].name, "introduction")
        self.assertIn("I would like to contribute.", intro)
        self.assertIn("https://example.com", intro)

    def test_post_join_twice_is_refused_by_the_api_rule(self):
        """An existing Pending request refuses the second POST with the API's own message."""
        self.assertTrue(self._post_3273().get("join_success"))
        self.expectErrorLog("Chapter Join Request Error")
        ctx = self._post_3273()
        self.assertFalse(ctx.get("join_success"))
        self.assertIn("Unable to submit chapter join request", ctx.get("join_error") or "")
        self.assertEqual(len(self._join_requests_3273()), 1)

    def test_post_join_inactive_chapter_is_refused_by_the_api_rule(self):
        self.chapter.db_set("status", "Inactive")
        self.expectErrorLog("Chapter Join Request Error")
        ctx = self._post_3273()
        self.assertFalse(ctx.get("join_success"))
        self.assertIn("Unable to submit chapter join request", ctx.get("join_error") or "")
        self.assertEqual(self._join_requests_3273(), [])
        self.assertFalse(self._chapter_member_rows_3273())

    def test_guest_post_files_nothing(self):
        ctx = self._post_3273(user="Guest")
        self.assertNotIn("join_success", ctx)
        self.assertEqual(self._join_requests_3273(), [])
        self.assertFalse(self._chapter_member_rows_3273())
