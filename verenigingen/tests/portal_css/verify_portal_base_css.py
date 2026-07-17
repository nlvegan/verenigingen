"""Re-runnable verification for portal_base.css (TPL-1/3/4 slice).

Run:  bench --site veg11.veganisme.org execute \
      verenigingen.tests.portal_css.verify_portal_base_css.run
"""
import glob
import os
import re

import frappe
from frappe.utils import get_html_for_route

PORTAL_CSS_LINK = "/assets/verenigingen/css/portal_base.css"

# (route, who) — who in {"admin","member","guest"}
PAGES = [
    ("member_portal", "member"),
    ("chapter_dashboard", "admin"),
    ("mollie_payments_debug", "admin"),
    ("mollie_payment_processing", "admin"),
    ("ponto_api_debug", "admin"),
    ("admin_tools", "admin"),
    ("board/document_upload", "admin"),
    ("board/document_browser", "admin"),
    ("volunteer/dashboard", "member"),
    ("address_change", "member"),
    ("contact_request", "member"),
    ("my_teams", "member"),
    ("mollie_bulk_payment_creation", "admin"),
    ("mollie_subscription_recreation", "admin"),
    ("volunteer/expenses", "member"),
    ("volunteer/expense_claim_new", "member"),
]

# Framework/Bootstrap class names that must never appear in portal_base.css.
FRAMEWORK = {
    "btn", "btn-primary", "btn-secondary", "btn-success", "btn-danger", "btn-warning",
    "btn-info", "btn-default", "btn-link", "btn-sm", "btn-lg", "btn-block", "btn-group",
    "form-group", "form-control", "form-label", "form-check", "form-select", "form-row",
    "form-text", "alert", "alert-success", "alert-danger", "alert-warning", "alert-info",
    "alert-primary", "card", "card-body", "card-header", "card-footer", "card-title",
    "container", "row", "col", "badge", "table", "nav", "navbar", "modal", "dropdown",
    "list-group", "page-header", "page-content", "input-group", "text-muted", "d-flex",
    "d-none", "d-block", "hidden", "loading",
}


def _member_user():
    rows = frappe.get_all("Member", filters={"user": ["!=", ""]}, fields=["user"], limit=1)
    return rows[0].user if rows else "Administrator"


def _render_with_user(route, who):
    user = {"admin": "Administrator", "guest": "Guest", "member": _member_user()}[who]
    frappe.set_user(user)
    try:
        return get_html_for_route(route)
    finally:
        frappe.set_user("Administrator")


def _sheet_selectors():
    path = frappe.get_app_path("verenigingen", "public", "css", "portal_base.css")
    css = open(path, encoding="utf-8").read()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(re.findall(r"\.([A-Za-z][\w-]*)\s*\{", css)) | set(
        re.findall(r"\.([A-Za-z][\w-]*)[\s,:]", css)
    )


def _frappe_website_classes():
    base = os.path.join(frappe.utils.get_bench_path(), "sites", "assets", "frappe", "dist", "css")
    classes = set()
    for f in glob.glob(os.path.join(base, "website.bundle.*.css")):
        css = open(f, encoding="utf-8", errors="replace").read()
        classes |= set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    return classes


def run():
    errors = []

    # Outside a real HTTP request, frappe.local.session_obj is never populated
    # (it's only set by the cookie-based auth flow in frappe.auth.LoginManager).
    # Several admin pages' get_context() call frappe.sessions.get_csrf_token(),
    # which — when the token isn't cached yet — calls
    # frappe.local.session_obj.update(force=True) and raises AttributeError.
    # Frappe's route resolver swallows that into a generic "Server Error" page
    # instead of propagating it here. _render_with_user() calls
    # frappe.set_user() before every render, which resets local.session.data
    # (wiping any cached token) but does NOT touch local.session_obj — so a
    # single harmless stub with a no-op update() installed once, up front,
    # satisfies every subsequent get_csrf_token() call for the rest of the run.
    class _NoopSessionObj:
        def update(self, *args, **kwargs):
            pass

    frappe.local.session_obj = _NoopSessionObj()

    # --- B. Bleed disjointness (static) ---
    sel = _sheet_selectors()
    print("portal_base.css selectors:", sorted(sel))
    hits = sel & FRAMEWORK
    if hits:
        errors.append(f"BLEED: framework-named selectors in portal_base.css: {sorted(hits)}")
    fw = _frappe_website_classes()
    if fw:
        overlap = sel & fw
        if overlap:
            errors.append(f"BLEED: selectors also used by frappe website.bundle.css: {sorted(overlap)}")
    else:
        print("WARN: frappe website.bundle.*.css not found; skipped compiled-CSS overlap check")

    # --- B. Guest/non-portal page must not contain any sheet selector as a class ---
    login_html = _render_with_user("login", "guest")
    login_classes = set(re.findall(r'class="([^"]*)"', login_html))
    login_tokens = set(tok for c in login_classes for tok in c.split())
    guest_hits = sel & login_tokens
    if guest_hits:
        errors.append(f"BLEED: /login uses sheet selectors: {sorted(guest_hits)}")

    # --- A. Render assertions on portal pages ---
    print(f"\n{'route':32} {'ok':>3} {'sheet':>6} {'inlineWrap':>10}")
    for route, who in PAGES:
        try:
            html = _render_with_user(route, who)
            ok = "<head" in html.lower() and len(html) > 2000
        except Exception as e:  # noqa: BLE001
            print(f"{route:32} {'ERR':>3}  ({type(e).__name__}: {e})")
            errors.append(f"RENDER: {route} raised {type(e).__name__}: {e}")
            continue
        has_sheet = PORTAL_CSS_LINK in html
        if ok and route in ("admin_tools", "mollie_payments_debug",
                            "mollie_payment_processing", "ponto_api_debug"):
            if html.count("/css/brand_colors.css") != 1:
                errors.append(f"BRAND: {route} brand_colors.css link count != 1")
        if ok and route in ("address_change", "contact_request", "my_teams", "volunteer/dashboard"):
            if len(re.findall(r'<link[^>]+tailwind\.css', html)) != 1:
                errors.append(f"TAILWIND: {route} tailwind link count != 1")
        inline_wrap = ".wide-layout-wrapper" in html and "<style" in html and \
            bool(re.search(r"<style[^>]*>[^<]*\.wide-layout-wrapper", html, re.S))
        print(f"{route:32} {str(ok):>3} {str(has_sheet):>6} {str(inline_wrap):>10}")
        if not ok:
            errors.append(f"RENDER: {route} did not render a full page")
        if ok and not has_sheet:
            errors.append(f"INJECT: {route} missing {PORTAL_CSS_LINK}")
        if ok and inline_wrap:
            errors.append(f"WRAPPER: {route} still defines .wide-layout-wrapper inline")

    if errors:
        raise AssertionError("VERIFY FAILED:\n  " + "\n  ".join(errors))
    print("\nVERIFY OK")
