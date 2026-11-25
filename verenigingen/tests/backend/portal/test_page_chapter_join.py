"""
Tests for the /chapter_join portal page
(verenigingen.templates.pages.chapter_join).

get_context resolves the Chapter from form_dict (chapter | name), reports guest
vs logged-in, computes already_member, and on POST delegates to
handle_join_chapter_request which validates the introduction, guards duplicates,
and adds a Chapter Member via secure_document_operation.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageChapterJoin(EnhancedTestCase):
    """Real-data tests for the chapter_join page context handler."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self._original_request = getattr(frappe.local, "request", None)

        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST Join Chapter {frappe.generate_hash()[:6]}",
            region="Test Region Join",
        )

        self.email = f"chapjoin-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Chap",
            last_name="Joiner",
            email=self.email,
            birth_date="1990-01-01",
        )
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
                    "first_name": "Chap",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    class _FakeRequest:
        """A real werkzeug Request: join_chapter's security decorators read headers/IP."""

        def __new__(cls, method):
            from werkzeug.test import EnvironBuilder
            from werkzeug.wrappers import Request

            return Request(EnvironBuilder(method=method, path="/chapter_join").get_environ())

    # ----- get_context -------------------------------------------------

    def test_no_chapter_specified_raises(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict()
        frappe.local.request = self._FakeRequest("GET")
        with self.assertRaises(frappe.DoesNotExistError):
            get_context(frappe._dict())

    def test_unknown_chapter_raises(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict({"chapter": "NoSuchChapter-XYZ"})
        frappe.local.request = self._FakeRequest("GET")
        with self.assertRaises(frappe.DoesNotExistError):
            get_context(frappe._dict())

    def test_guest_context_short_circuits(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict({"chapter": self.chapter.name})
        frappe.local.request = self._FakeRequest("GET")
        with self.as_user("Guest"):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertIn(self.chapter.name, ctx.title)
        # Guest path returns before computing already_member.
        self.assertNotIn("already_member", ctx)

    def test_logged_in_not_yet_member(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict({"name": self.chapter.name})
        frappe.local.request = self._FakeRequest("GET")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertFalse(ctx.already_member)
        self.assertEqual(ctx.no_cache, 1)

    # ----- handle_join_chapter_request (via POST) ----------------------

    def _requests_3273(self, member=None):
        return frappe.get_all(
            "Chapter Join Request",
            filters={"member": member or self.member.name, "chapter": self.chapter.name},
            fields=["name", "status", "docstatus"],
        )

    def _post_3273(self, user=None, **form):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict(
            {"chapter": self.chapter.name, "introduction": "I want to help out locally.", **form}
        )
        frappe.local.request = self._FakeRequest("POST")
        ctx = frappe._dict()
        with self.as_user(user or self.user):
            get_context(ctx)
        return ctx

    def test_post_join_files_pending_request_not_chapter_member(self):
        """#3273: a POST files a Pending submitted Chapter Join Request for the session member
        and adds NO Chapter Member row (board approval applies)."""
        self.member.db_set("status", "Active")
        ctx = self._post_3273()

        self.assertTrue(ctx.get("join_success"), msg=ctx.get("join_error"))
        requests = self._requests_3273()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].status, "Pending")
        self.assertEqual(requests[0].docstatus, 1)
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

    def test_post_join_twice_is_refused_by_the_api_rule(self):
        self.member.db_set("status", "Active")
        self.assertTrue(self._post_3273().get("join_success"))
        self.expectErrorLog("Chapter Join Request Error")
        ctx = self._post_3273()
        self.assertFalse(ctx.get("join_success"))
        self.assertIn("Unable to submit chapter join request", ctx.get("join_error") or "")
        self.assertEqual(len(self._requests_3273()), 1)

    def test_guest_post_files_nothing(self):
        self.member.db_set("status", "Active")
        ctx = self._post_3273(user="Guest")
        self.assertNotIn("join_success", ctx)
        self.assertEqual(self._requests_3273(), [])

    def test_post_join_without_introduction_records_error(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict({"chapter": self.chapter.name, "introduction": "   "})
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        # Validation failure is caught and surfaced via join_error, no membership.
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

    def test_post_join_when_already_member_records_error(self):
        from verenigingen.templates.pages.chapter_join import get_context

        # Pre-add the member to the chapter.
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "members",
            {"member": self.member.name, "chapter_join_date": frappe.utils.today(), "enabled": 1},
        )
        chapter_doc.save()

        self.expectErrorLog("Chapter Join Request Error")
        frappe.form_dict = frappe._dict({"chapter": self.chapter.name, "introduction": "Joining again"})
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.get("already_member"))
        self.assertTrue(ctx.get("join_error"))

    def test_post_join_ignores_attacker_supplied_member(self):
        """IDOR guard: the request is ALWAYS for the session-derived member, never a `member`
        value smuggled in via form_dict."""
        self.member.db_set("status", "Active")
        other_email = f"chapjoin-other-{frappe.generate_hash()[:8]}@example.com"
        other = self.create_test_member(
            first_name="Other", last_name="Member", email=other_email, birth_date="1985-01-01"
        )
        other.db_set("status", "Active")

        self._post_3273(member=other.name)  # attacker-controlled, must be ignored

        self.assertEqual(len(self._requests_3273()), 1)
        self.assertEqual(self._requests_3273(other.name), [])
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": other.name, "parent": self.chapter.name})
        )

    def test_post_join_non_active_member_is_refused(self):
        """A non-Active member gets neither a request nor a Chapter Member row (#2021)."""
        self.member.db_set("status", "Terminated")
        self.expectErrorLog("Error in chapter join request")
        self.expectErrorLog("Chapter Join Request Error")
        ctx = self._post_3273(introduction="Rejoining after termination.")
        self.assertTrue(ctx.get("join_error"))
        self.assertFalse(ctx.get("join_success"))
        self.assertEqual(self._requests_3273(), [])
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )
