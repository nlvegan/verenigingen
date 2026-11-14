"""
#1891: the two chapter-join pages read ``frappe.form_dict.get(k, "").strip()``.
A JSON POST body ``{"introduction": null}`` makes ``form_dict[k]`` None (frappe's
``make_form_dict`` orjson-loads it), so ``.strip()`` raised AttributeError and
the member was shown "'NoneType' object has no attribute 'strip'" instead of
the page's own "... is required" refusal.

Drives the real ``get_context`` (the only caller of the handler) with a POST.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _FakeRequest:
    method = "POST"


class _JoinNullBase(EnhancedTestCase):
    PAGE = None

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        self._original_request = getattr(frappe.local, "request", None)
        self.chapter = self.create_test_chapter(
            chapter_name=f"TEST JN Chapter {frappe.generate_hash()[:6]}", region="Test Region JN"
        )
        self.email = f"joinnull-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Join", last_name="Nullval", email=self.email, birth_date="1990-01-01"
        )
        self.member.db_set("status", "Active")
        if not frappe.db.exists("User", self.email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.email,
                    "first_name": "Join",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        self.member.db_set("user", self.email)

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        frappe.local.request = self._original_request
        super().tearDown()

    def _post(self, **fields):
        import importlib

        page = importlib.import_module(self.PAGE)
        frappe.form_dict = frappe._dict(chapter=self.chapter.name, name=self.chapter.name, **fields)
        frappe.local.request = _FakeRequest()
        ctx = frappe._dict()
        with self.as_user(self.email):
            page.get_context(ctx)
        return ctx


class TestChapterJoinNull1891(_JoinNullBase):
    PAGE = "verenigingen.templates.pages.chapter_join"

    def test_null_introduction_gets_the_required_message(self):
        ctx = self._post(introduction=None)
        self.assertEqual(ctx.get("join_error"), "Introduction is required")


class TestJoinChapterNull1891(_JoinNullBase):
    PAGE = "verenigingen.templates.pages.verenigingen.join_chapter"

    def test_null_introduction_gets_the_required_message(self):
        ctx = self._post(website_url="https://example.org", introduction=None)
        self.assertEqual(ctx.get("join_error"), "Introduction is required")

    def test_null_website_url_gets_the_required_message(self):
        ctx = self._post(website_url=None, introduction="Hello")
        self.assertEqual(ctx.get("join_error"), "Website URL is required")
