"""A Guest gets real brand CSS on a site with no static brand_colors.css (#2900).

Measured on test_site_7 (no static file) through the real WSGI app, as Guest, before the fix:
``/brand_css`` was a 403 "Not Permitted" page and ``serve_brand_css`` returned the hard-coded
"Fallback brand CSS". The refusal is NOT ``frappe.get_single("Brand Settings")`` (a Guest can
call that: ``get_doc`` checks nothing): both routes fell back to ``generate_brand_css()``, which
is ``@high_security_api(ADMIN)`` and refuses a Guest. ``apply_for_membership`` reads the same
Single directly and was never refused (200 as Guest).

The probe runs in a SUBPROCESS (``frappe.app.application`` destroys ``frappe.local`` per
request). It must write DISTINCT colours to Brand Settings and COMMIT, because the WSGI request
uses its own DB connection; the colours are restored in a ``finally``. Probe shortcut: the colours
are written with ``set_single_value`` (no controller hooks, so no static file is generated) and the
logged-in control uses a session created with ``Session(...)`` rather than the login form.
"""

import json
import os
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

import verenigingen
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.brand_css_generator import get_brand_css_file_path

_PROBE_2900 = r"""
import json, os, sys
import frappe
SITE, PKG, COLOURS = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
RESTORE_ONLY = len(sys.argv) > 4 and sys.argv[4] == "restore"
import verenigingen
_got = os.path.realpath(os.path.dirname(verenigingen.__file__))
if _got != os.path.realpath(PKG):
    sys.exit("subprocess imported verenigingen from %s, expected %s" % (_got, PKG))
frappe.init(site=SITE)
frappe.connect()
import frappe.app
from werkzeug.test import Client, EnvironBuilder
from werkzeug.wrappers import Request
from frappe.sessions import Session, delete_session

ORIGINAL = {f: frappe.db.get_single_value("Brand Settings", f) for f in COLOURS}
if RESTORE_ONLY:
    for f, v in COLOURS.items():
        frappe.db.set_single_value("Brand Settings", f, v)
    frappe.db.commit()
    frappe.cache().delete_value("brand_settings_css")
    sys.exit(0)
CACHE_KEYS = ("brand_settings_css", "active_brand_settings")
def _drop_caches():
    for k in CACHE_KEYS:
        frappe.cache().delete_value(k)
out = {}
sid = None
try:
    for f, v in COLOURS.items():
        frappe.db.set_single_value("Brand Settings", f, v)
    frappe.db.commit()
    _drop_caches()
    frappe.local.request = Request(EnvironBuilder(path="/").get_environ())
    frappe.local.form_dict = frappe._dict()
    frappe.local.request_ip = "127.0.0.1"
    sid = Session("Administrator", resume=False).sid
    H = {"X-Frappe-Site-Name": SITE}
    c = Client(frappe.app.application, use_cookies=False)
    for who, extra in (("guest", {}), ("user", {"Cookie": "sid=" + sid})):
        for key, path in (
            ("page", "/brand_css"),
            ("api", "/api/method/verenigingen.templates.pages.brand_css.serve_brand_css"),
        ):
            _drop_caches()
            r = c.get(path, headers={**H, **extra})
            out[who + "_" + key] = {
                "status": r.status_code,
                "headers": {k.lower(): v for k, v in r.headers},
                "body": r.get_data(as_text=True),
            }
    _drop_caches()
    r = c.get(
        "/api/method/verenigingen.verenigingen.doctype.brand_settings.brand_settings.generate_brand_css",
        headers=H,
    )
    out["guest_admin_only"] = {"status": r.status_code, "body": r.get_data(as_text=True)}
finally:
    frappe.init(site=SITE)
    frappe.connect()
    if sid:
        delete_session(sid)
    for f, v in ORIGINAL.items():
        frappe.db.set_single_value("Brand Settings", f, v)
    frappe.db.commit()
    _drop_caches()
print("RESULT" + json.dumps(out))
"""

_NO_CACHE = "no-cache, no-store, must-revalidate"
# Distinct, non-default colours, so neither the model default nor the hard-coded fallback can match.
_TEST_COLOURS_2900 = {
    "primary_color": "#0a1b2c",
    "secondary_color": "#3c4d5e",
    "accent_color": "#6f7081",
    "primary_hover_color": "#92a3b4",
    "text_primary_color": "#c5d6e7",
}
# Written with set_single_value, which skips validate_colors: a hostile value a Guest must never see.
_HOSTILE_2900 = "red; } body { background: url(http://evil/x) } :root { --x: 1"
_HOSTILE_FIELD_2900 = "error_color"
_HOSTILE_DEFAULT_2900 = "#dc3545"


class TestBrandCssGuestNoStaticFile2900(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._move_static_brand_css_aside_2900()
        cls._restore_original_colours_on_cleanup_2900()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _PROBE_2900,
                frappe.local.site,
                os.path.dirname(verenigingen.__file__),
                json.dumps({**_TEST_COLOURS_2900, _HOSTILE_FIELD_2900: _HOSTILE_2900}),
            ],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        line = next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))
        cls.out = json.loads(line[len("RESULT") :])

    @classmethod
    def _restore_original_colours_on_cleanup_2900(cls):
        """Crash-safe restore: the probe child's own ``finally`` never runs if it is killed."""
        originals = {
            f: frappe.db.get_single_value("Brand Settings", f)
            for f in [*_TEST_COLOURS_2900, _HOSTILE_FIELD_2900]
        }

        def restore():
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _PROBE_2900,
                    frappe.local.site,
                    os.path.dirname(verenigingen.__file__),
                    json.dumps(originals),
                    "restore",
                ],
                cwd=os.path.join(get_bench_path(), "sites"),
                check=True,
                capture_output=True,
                timeout=120,
            )

        cls.addClassCleanup(restore)

    @classmethod
    def _move_static_brand_css_aside_2900(cls):
        """The bug exists only when the static file is absent: take it away, put it back after."""
        path = get_brand_css_file_path()
        if os.path.exists(path):
            os.rename(path, path + ".aside2900")
            cls.addClassCleanup(os.rename, path + ".aside2900", path)
        cls.assertFalse(cls, os.path.exists(path))

    def _css_2900(self, key):
        resp = self.out[key]
        body = resp["body"]
        if key.endswith("_api"):
            body = json.loads(body)["message"]
        return resp, body

    def test_every_caller_gets_200_css_carrying_the_configured_colours(self):
        for key in ("guest_page", "guest_api", "user_page", "user_api"):
            resp, css = self._css_2900(key)
            self.assertEqual(resp["status"], 200, key)
            self.assertNotIn("Fallback brand CSS", css, key)
            for field, colour in _TEST_COLOURS_2900.items():
                self.assertIn(colour, css, f"{key}: {field}")

    def test_guest_page_is_bare_text_css_with_no_cache_headers(self):
        for key in ("guest_page", "user_page"):
            h = self.out[key]["headers"]
            self.assertEqual(h["content-type"], "text/css; charset=utf-8", key)
            self.assertEqual(h["cache-control"], _NO_CACHE, key)
            self.assertEqual(h["pragma"], "no-cache", key)
            self.assertEqual(h["expires"], "0", key)

    def test_guest_api_sends_no_cache_headers(self):
        for key in ("guest_api", "user_api"):
            h = self.out[key]["headers"]
            self.assertEqual(h["cache-control"], _NO_CACHE, key)
            self.assertEqual(h["pragma"], "no-cache", key)
            self.assertEqual(h["expires"], "0", key)

    def test_guest_and_user_get_the_same_colours(self):
        _, guest = self._css_2900("guest_api")
        _, user = self._css_2900("user_api")
        strip = lambda s: "\n".join(x for x in s.splitlines() if "Generated at" not in x)  # noqa: E731
        self.assertEqual(strip(guest), strip(user))

    def test_public_colour_allowlist_is_colour_fields_only(self):
        """Guest reads only what the CSS needs; every allowlisted field must be a Color field."""
        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
            PUBLIC_BRAND_COLOUR_FIELDS,
        )

        meta = frappe.get_meta("Brand Settings")
        self.assertTrue(PUBLIC_BRAND_COLOUR_FIELDS)
        for fieldname in PUBLIC_BRAND_COLOUR_FIELDS:
            self.assertEqual(meta.get_field(fieldname).fieldtype, "Color", fieldname)

    def test_hostile_stored_value_never_reaches_a_guest(self):
        for key in ("guest_page", "guest_api"):
            _, css = self._css_2900(key)
            self.assertNotIn("evil", css, key)
            self.assertNotIn(_HOSTILE_2900, css, key)
            self.assertIn(f"--brand-error: {_HOSTILE_DEFAULT_2900};", css, key)

    def test_generate_brand_css_stays_admin_only_for_a_guest(self):
        self.assertEqual(self.out["guest_admin_only"]["status"], 403)
        self.assertNotIn("brand-primary", self.out["guest_admin_only"]["body"])

    def test_public_read_requests_exactly_the_allowlisted_fields(self):
        from unittest.mock import patch

        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
            PUBLIC_BRAND_COLOUR_FIELDS,
            get_public_brand_colours,
        )

        real = frappe.db.get_value
        asked = []

        def spy(doctype, filters=None, fieldname="name", *args, **kwargs):
            if doctype == "Brand Settings":
                asked.append(fieldname)
            return real(doctype, filters, fieldname, *args, **kwargs)

        # Mock justified: a pass-through spy, not a stub; the real read still happens.
        with patch.object(frappe.db, "get_value", spy):
            get_public_brand_colours()
        self.assertEqual(len(asked), 1)
        self.assertEqual(set(asked[0]), set(PUBLIC_BRAND_COLOUR_FIELDS))
