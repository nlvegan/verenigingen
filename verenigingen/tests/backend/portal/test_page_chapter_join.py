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
        def __init__(self, method):
            self.method = method

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

    def test_post_join_adds_chapter_member(self):
        from verenigingen.templates.pages.chapter_join import get_context

        frappe.form_dict = frappe._dict(
            {"chapter": self.chapter.name, "introduction": "I want to help out locally."}
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.get("join_success"))
        # Side effect: Chapter Member row now exists.
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )

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

        frappe.form_dict = frappe._dict({"chapter": self.chapter.name, "introduction": "Joining again"})
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertTrue(ctx.get("already_member"))
        self.assertTrue(ctx.get("join_error"))

    def test_post_join_ignores_attacker_supplied_member(self):
        """IDOR guard: the joined member is ALWAYS the session-derived record,
        never a `member` value smuggled in via form_dict. A regression that read
        the member from form input would add the foreign member and fail here."""
        from verenigingen.templates.pages.chapter_join import get_context

        other_email = f"chapjoin-other-{frappe.generate_hash()[:8]}@example.com"
        other = self.create_test_member(
            first_name="Other", last_name="Member", email=other_email, birth_date="1985-01-01"
        )

        frappe.form_dict = frappe._dict(
            {
                "chapter": self.chapter.name,
                "introduction": "Joining as myself.",
                "member": other.name,  # attacker-controlled — must be ignored
            }
        )
        frappe.local.request = self._FakeRequest("POST")
        with self.as_user(self.user):
            get_context(frappe._dict())

        # The SESSION member was added; the smuggled member was NOT.
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"member": self.member.name, "parent": self.chapter.name})
        )
        self.assertFalse(
            frappe.db.exists("Chapter Member", {"member": other.name, "parent": self.chapter.name})
        )

    def test_post_join_terminated_member_added_disabled(self):
        """A non-Active member who still has a login joins disabled/Inactive
        (mirrors ChapterMemberManager.add_member) so they cannot self-re-enable."""
        from verenigingen.templates.pages.chapter_join import get_context

        self.member.db_set("status", "Terminated")

        frappe.form_dict = frappe._dict(
            {"chapter": self.chapter.name, "introduction": "Rejoining after termination."}
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

    def test_has_website_permission_guest_denied(self):
        from verenigingen.templates.pages.chapter_join import has_website_permission

        self.assertFalse(has_website_permission(None, "read", "Guest"))
        self.assertTrue(has_website_permission(None, "read", self.user))
