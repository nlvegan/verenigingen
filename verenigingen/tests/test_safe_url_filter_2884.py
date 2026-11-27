"""``|safe_url`` blocks script-scheme URLs in the templates that print a user-settable URL (#2884).

``|e`` stops an attribute breakout, not ``javascript:``/``data:``. Three template sites print a value
a non-staff user can write: ``Member.image`` (Verenigingen Member has write if_owner on Member) and
``Organization Document.document_file`` (Chapter Board Member / Team Lead create rows), the latter in
member_portal.html and chapter_dashboard.html.

Declared shortcuts: the page contexts are hand-built (the real ``get_context`` needs a logged-in
member / board role), so these prove the TEMPLATE neutralises a hostile value, not that a given
caller passes one. Only the ``page_content`` block is rendered (the base layout needs a full website
context and none of the values under test is printed outside it).

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.test_safe_url_filter_2884
"""

import frappe
from markupsafe import escape
from frappe.tests import IntegrationTestCase

HOSTILE = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "  javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "//evil.test/x.png",
    "/\\evil.test/x.png",
    "\\\\evil.test\\x.png",
]
ALLOWED = [
    "/files/a.png",
    "/private/files/a b.pdf",
    "files/a.png",
    "https://example.org/a.png",
    "http://example.org/a.png",
    "mailto:a@example.org",
]
FRAPPE_STUB = {"form_dict": {}, "utils": frappe.utils, "format": frappe.format}


def render_page_content_2884(path, context):
    template = frappe.get_template(path)
    return "".join(template.blocks["page_content"](template.new_context(context)))


def member_stub_2884(image):
    return frappe._dict(
        name="MEM-2884", full_name="A B", first_name="A", last_name="B", image=image, status="Active"
    )


class TestSafeUrlFilter2884(IntegrationTestCase):
    def _filter(self):
        return frappe.get_jenv().filters["safe_url"]

    def test_filter_is_registered_through_the_jinja_hook(self):
        self.assertIn("safe_url", frappe.get_jenv().filters)

    def test_every_hostile_shape_is_refused(self):
        safe_url = self._filter()
        for value in HOSTILE:
            with self.subTest(value=value):
                self.assertEqual(safe_url(value), "")

    def test_non_strings_are_refused(self):
        safe_url = self._filter()
        for value in (None, 0, 12, ["/files/a.png"], {"u": "/files/a.png"}):
            with self.subTest(value=value):
                self.assertEqual(safe_url(value), "")

    def test_control_real_file_urls_and_allowed_schemes_pass_unchanged(self):
        safe_url = self._filter()
        for value in ALLOWED:
            with self.subTest(value=value):
                self.assertEqual(safe_url(value), value)


class TestHostileValueInRealTemplates2884(IntegrationTestCase):
    def _personal_details(self, image):
        return render_page_content_2884(
            "verenigingen/templates/pages/personal_details.html",
            {
                "member": member_stub_2884(image),
                "frappe": FRAPPE_STUB,
                "csrf_token": "x",
                "success_messages": [],
                "countries": [],
                "address_data": {},
                "current_address": {},
            },
        )

    def _member_portal(self, document_file):
        chapter = frappe._dict(
            chapter_name="Ch",
            board_members=[],
            documents=frappe._dict(
                total_count=1,
                category_icons=None,
                by_type_and_year={
                    "Policy": {
                        "2026": [frappe._dict(document_name="Doc 2884", document_file=document_file)]
                    }
                },
            ),
        )
        return render_page_content_2884(
            "verenigingen/templates/pages/member_portal.html",
            {
                "member": member_stub_2884(None),
                "chapters_info": [chapter],
                "no_member_record": False,
                "frappe": FRAPPE_STUB,
            },
        )

    def _chapter_dashboard(self, document_file):
        documents = {"Policy": {"2026": [frappe._dict(document_name="Doc 2884", document_file=document_file)]}}
        return render_page_content_2884(
            "verenigingen/templates/pages/chapter_dashboard.html",
            {
                "dashboard_data": frappe._dict(
                    board_documents=frappe._dict(
                        total_count=1, category_icons=None, by_type_and_year=documents
                    )
                ),
                "has_data": True,
                "format_date": frappe.utils.formatdate,
                "user_board_role": frappe._dict(permissions=frappe._dict()),
                "frappe": FRAPPE_STUB,
            },
        )

    def test_member_image_scheme_is_neutralised_and_real_url_survives(self):
        for hostile in HOSTILE:
            with self.subTest(value=hostile):
                html = self._personal_details(hostile)
                self.assertIn('class="current-image"', html)
                self.assertNotIn("javascript:", html.lower())
                self.assertNotIn(str(escape(hostile)), html)
                self.assertNotIn("evil.test", html)
        self.assertIn('src="/files/me.png"', self._personal_details("/files/me.png"))

    def test_member_portal_document_link_is_neutralised_and_real_url_survives(self):
        for hostile in HOSTILE:
            with self.subTest(value=hostile):
                html = self._member_portal(hostile)
                self.assertIn("Doc 2884", html)
                self.assertNotIn("javascript:", html.lower())
                self.assertNotIn(str(escape(hostile)), html)
                self.assertNotIn("evil.test", html)
        self.assertIn('href="/files/d.pdf"', self._member_portal("/files/d.pdf"))

    def test_chapter_dashboard_document_link_is_neutralised_and_real_url_survives(self):
        for hostile in HOSTILE:
            with self.subTest(value=hostile):
                html = self._chapter_dashboard(hostile)
                self.assertIn("Doc 2884", html)
                self.assertNotIn("javascript:", html.lower())
                self.assertNotIn(str(escape(hostile)), html)
                self.assertNotIn("evil.test", html)
        self.assertIn('href="/files/d.pdf"', self._chapter_dashboard("/files/d.pdf"))
