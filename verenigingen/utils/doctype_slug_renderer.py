"""Answer 404 for /<doctype slug>/<anything> instead of Frappe's ImportError 500 (#2308)."""

import frappe
from frappe.website.page_renderers.document_page import DocumentPage
from frappe.website.page_renderers.not_found_page import NotFoundPage
from frappe.website.page_renderers.static_page import StaticPage
from frappe.website.page_renderers.template_page import TemplatePage
from frappe.website.page_renderers.web_form import WebFormPage


class DoctypeSlugNotFound(NotFoundPage):
    """Claim "<x>/<y>" when <x> only matches a DocType name case-insensitively.

    PrintPage's can_render looks the DocType up with MariaDB's case-insensitive
    collation, so /member/xyz is accepted, but printview then loads the controller
    for the literal "member" and import_controller raises ImportError (a 500). The
    exact-case route /Member/<name> is a legitimate print view and is left alone, as
    is anything another renderer can serve.

    Known theoretical limit (not reproduced; no such route exists today): a
    permission-dependent has_web_view document route "<lowercase doctype>/..." that is
    refused for Guest would be answered by this renderer, and NotFoundPage caches that
    404 per URL (website_404), so it would stay a 404 for logged-in users too.
    """

    def __init__(self, path=None, http_status_code=None):
        # NotFoundPage rewrites self.path to "404"; keep the requested one to inspect.
        self.requested_path = (path or "").strip("/ ")
        # PathResolver builds renderers with the request's default status (200); a
        # NotFoundPage must answer 404, which PathResolver gets by passing none.
        super().__init__(path, 404)

    def can_render(self):
        parts = self.requested_path.split("/", 1)
        if len(parts) != 2:
            return False
        # cache=True, as PrintPage does: no extra query per multi-segment request.
        canonical = frappe.db.exists("DocType", parts[0], cache=True)
        if not canonical or canonical == parts[0]:
            return False
        return not self._another_renderer_serves()

    def _another_renderer_serves(self):
        # StaticPage has no control test: it serves files from an app's www/public
        # tree, and no file lives under a lowercase DocType slug here.
        for renderer in (StaticPage, WebFormPage, DocumentPage, TemplatePage):
            if renderer(self.requested_path, self.http_status_code).can_render():
                return True
        return False
