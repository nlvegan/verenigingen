import os
import re

import frappe
from frappe.utils import get_html_for_route

OUT = "/tmp/portal_css_shots"
# Site-specific — dev screenshot helper only, not used by the verify harness or CI.
BASE = "https://veg11.veganisme.org"
# (route, who) — widened pages, representative pages, a Case-A page, and guest bleed page
TARGETS = [
    ("board/document_upload", "admin"), ("board/document_browser", "admin"),
    ("ponto_api_debug", "admin"), ("mollie_bulk_payment_creation", "admin"),
    ("mollie_payments_debug", "admin"),
    ("member_portal", "member"), ("chapter_dashboard", "admin"),
    ("volunteer/dashboard", "member"), ("address_change", "member"),
    ("login", "guest"),
]


def _user(who):
    if who == "member":
        r = frappe.get_all("Member", filters={"user": ["!=", ""]}, fields=["user"], limit=1)
        return r[0].user if r else "Administrator"
    return {"admin": "Administrator", "guest": "Guest"}[who]


def _render_with_user(route, who):
    """Render a route as the given user, always restoring Administrator after.

    Same helper name/pattern as verify_portal_base_css.py._render_with_user.
    """
    frappe.set_user(_user(who))
    try:
        return get_html_for_route(route)
    finally:
        frappe.set_user("Administrator")


def run():
    os.makedirs(OUT, exist_ok=True)

    # Outside a real HTTP request, frappe.local.session_obj is never populated,
    # so some admin/debug pages' get_context() -> get_csrf_token() raises
    # AttributeError, which the route resolver swallows into a generic
    # "Server Error" page. Same workaround as verify_portal_base_css.py.
    class _NoopSessionObj:
        def update(self, *args, **kwargs):
            pass

    frappe.local.session_obj = _NoopSessionObj()

    for route, who in TARGETS:
        html = _render_with_user(route, who)
        # rewrite root-relative asset URLs to absolute so file:// can load them
        html = re.sub(r'(href|src)="(/[^"]*)"', rf'\1="{BASE}\2"', html)
        name = route.replace("/", "_") + ".html"
        open(os.path.join(OUT, name), "w", encoding="utf-8").write(html)
        print("wrote", name)
