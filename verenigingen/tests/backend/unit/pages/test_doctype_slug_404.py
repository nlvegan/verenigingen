"""GET /<lowercase doctype>/<anything> must be a 404, not an ImportError 500 (#2308).

Frappe's PrintPage accepts any "<x>/<y>" whose first part case-insensitively names a
DocType, then printview calls get_lazy_doc("<x>") with the lowercase slug and
import_controller raises ImportError. Stock doctypes (/user/xyz, /todo/xyz) fail the
same way, so the fix is an app page_renderer that answers 404 for that exact shape.
"""

import frappe
from frappe.website.serve import get_response
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.base import VereningingenUnitTestCase


class TestDoctypeSlug404(VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.set_user(self._previous_user)
        super().tearDown()

    def _get(self, path, user="Guest"):
        frappe.local.request = Request(EnvironBuilder(path=f"/{path}").get_environ())
        # NotFoundPage caches 404s per URL when the website cache is on (developer_mode=0);
        # cheap insurance for running the module without a cache clear.
        frappe.cache.hdel("website_404", frappe.local.request.url)
        frappe.set_user(user)
        try:
            return get_response(path)
        finally:
            frappe.set_user(self._previous_user)

    def test_lowercase_doctype_slug_is_404(self):
        # app doctypes and stock doctypes alike
        for path in ("member/xyz", "chapter/xyz", "volunteer/xyz", "user/xyz", "todo/xyz"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path).status_code, 404)

    def test_lowercase_doctype_slug_is_404_for_a_logged_in_user(self):
        for path in ("member/xyz", "volunteer/xyz"):
            with self.subTest(path=path):
                self.assertEqual(self._get(path, user="Administrator").status_code, 404)

    def test_unknown_first_segment_is_still_404(self):
        self.assertEqual(self._get("zzz/xyz").status_code, 404)

    def test_exact_case_print_route_is_not_claimed(self):
        # Control: the real /<DocType>/<name> print route must still reach PrintPage,
        # i.e. the new renderer must not answer for it.
        from verenigingen.utils.doctype_slug_renderer import DoctypeSlugNotFound

        frappe.local.request = Request(EnvironBuilder(path="/Member/xyz").get_environ())
        self.assertFalse(DoctypeSlugNotFound("Member/xyz").can_render())
        self.assertTrue(DoctypeSlugNotFound("member/xyz").can_render())

    def test_real_template_routes_are_not_claimed(self):
        # Control: /chapter (www/chapter.py) and a one-segment path are unaffected.
        from verenigingen.utils.doctype_slug_renderer import DoctypeSlugNotFound

        frappe.local.request = Request(EnvironBuilder(path="/chapter").get_environ())
        self.assertFalse(DoctypeSlugNotFound("chapter").can_render())
        self.assertFalse(DoctypeSlugNotFound("zzz/xyz").can_render())

    def test_existing_volunteer_template_pages_are_not_claimed(self):
        # Control: templates/pages/volunteer/*.html are real pages under a lowercase
        # doctype slug; a bare "doctype matches" rule would 404 them.
        from verenigingen.utils.doctype_slug_renderer import DoctypeSlugNotFound

        for page in ("apply", "dashboard", "skills", "expenses", "profile"):
            with self.subTest(page=page):
                frappe.local.request = Request(EnvironBuilder(path=f"/volunteer/{page}").get_environ())
                self.assertFalse(DoctypeSlugNotFound(f"volunteer/{page}").can_render())
                self.assertNotEqual(self._get(f"volunteer/{page}").status_code, 404)

    def test_web_form_route_under_a_doctype_slug_is_not_claimed(self):
        # Control: Web Form "addresses" has route "address" (DocType Address), so
        # /address/new is a lowercase-slug path that WebFormPage serves.
        from verenigingen.utils.doctype_slug_renderer import DoctypeSlugNotFound

        self.assertTrue(frappe.db.exists("Web Form", {"route": "address", "published": 1}))
        frappe.local.request = Request(EnvironBuilder(path="/address/new").get_environ())
        self.assertFalse(DoctypeSlugNotFound("address/new").can_render())
        self.assertEqual(self._get("address/new", user="Administrator").status_code, 200)

    def create_test_data(self, route):
        """Fixture: a published Web Page at `route`, made as Administrator (tearDown restores the user)."""
        frappe.set_user("Administrator")
        page = frappe.get_doc(
            {
                "doctype": "Web Page",
                "title": route,
                "route": route,
                "published": 1,
                "content_type": "Rich Text",
                "main_section": "x",
            }
        ).insert()
        self.addCleanup(frappe.delete_doc, "Web Page", page.name, force=True)

    def test_document_webview_route_under_a_doctype_slug_is_not_claimed(self):
        # Control: a published Web Page (has_web_view) at "member/<x>" is served by DocumentPage.
        from verenigingen.utils.doctype_slug_renderer import DoctypeSlugNotFound

        route = f"member/ctrl-{frappe.generate_hash(length=6)}"
        self.create_test_data(route)
        frappe.local.request = Request(EnvironBuilder(path=f"/{route}").get_environ())
        self.assertFalse(DoctypeSlugNotFound(route).can_render())
        self.assertEqual(self._get(route).status_code, 200)
