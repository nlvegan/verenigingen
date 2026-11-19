"""brand_css cache/content-type headers reach the wire, not the body (#2779).

Measured on develop through the real WSGI app, as a guest:
- ``/api/method/...serve_brand_css`` wrote ``frappe.response.headers[...]`` and
  ``frappe.response.content_type``; ``frappe.response`` is serialised into the JSON body, so
  ``{"content_type": ..., "headers": {...}}`` leaked into the body and no Pragma/Expires header
  was sent.
- the www pages ``/brand_css`` and ``/brand_css_disabled`` wrote the same dict, which the website
  renderer ignores: the CSS was served as ``text/html`` with no Pragma/Expires.

The probe runs in a SUBPROCESS (``frappe.app.application`` destroys ``frappe.local`` per
request). Guest only, so it writes nothing and commits nothing.
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

_PROBE_2779 = r"""
import json, sys
import frappe
SITE = sys.argv[1]
# The subprocess must exercise the tree under test, not the installed one: fail loudly if not.
import os, verenigingen
_got = os.path.realpath(os.path.dirname(verenigingen.__file__))
if _got != os.path.realpath(sys.argv[2]):
    sys.exit("subprocess imported verenigingen from %s, expected %s" % (_got, sys.argv[2]))
frappe.init(site=SITE)
frappe.connect()
import frappe.app
from werkzeug.test import Client
H = {"X-Frappe-Site-Name": SITE}
c = Client(frappe.app.application, use_cookies=False)
out = {}
for key, path in (
    ("page", "/brand_css"),
    ("disabled", "/brand_css_disabled"),
    ("api", "/api/method/verenigingen.templates.pages.brand_css.serve_brand_css"),
):
    r = c.get(path, headers=H)
    out[key] = {
        "status": r.status_code,
        "headers": {k.lower(): v for k, v in r.headers},
        "body": r.get_data(as_text=True),
    }
print("RESULT" + json.dumps(out))
"""

_NO_CACHE = "no-cache, no-store, must-revalidate"


class TestBrandCssResponseHeaders2779(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_static_brand_css()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _PROBE_2779,
                frappe.local.site,
                os.path.dirname(verenigingen.__file__),
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
    def _ensure_static_brand_css(cls):
        """Guarantee the static brand CSS file the routes serve, and undo it afterwards.

        Sites that never saved Brand Settings have no ``brand_colors.css``; for a guest the
        routes then fall back to ``get_single("Brand Settings")``, which is refused (403 page,
        fallback CSS; filed as #2900), so the probe would measure site state, not the header fix. A file write
        only: no DB row, no commit.
        """
        path = get_brand_css_file_path()
        if os.path.exists(path):
            return
        with open(path, "w") as f:
            f.write(":root { --brand-primary: #cf3131; }\n")
        cls.addClassCleanup(os.remove, path)

    def test_control_all_three_routes_answer_for_a_guest(self):
        for key, resp in self.out.items():
            self.assertEqual(resp["status"], 200, key)
            self.assertIn("--brand-primary", resp["body"], key)

    def test_pages_serve_text_css_with_no_cache_headers(self):
        for key in ("page", "disabled"):
            h = self.out[key]["headers"]
            self.assertEqual(h["content-type"], "text/css; charset=utf-8", key)
            self.assertEqual(h["cache-control"], _NO_CACHE, key)
            self.assertEqual(h["pragma"], "no-cache", key)
            self.assertEqual(h["expires"], "0", key)

    def test_api_sends_no_cache_headers_on_the_wire(self):
        h = self.out["api"]["headers"]
        self.assertEqual(h["cache-control"], _NO_CACHE)
        self.assertEqual(h["pragma"], "no-cache")
        self.assertEqual(h["expires"], "0")
        # JSON envelope: Content-Type must stay JSON so frappe.call can parse it.
        self.assertTrue(h["content-type"].startswith("application/json"), h["content-type"])

    def test_api_body_carries_neither_headers_nor_content_type_keys(self):
        body = json.loads(self.out["api"]["body"])
        self.assertNotIn("headers", body)
        self.assertNotIn("content_type", body)
        self.assertIn("/* Generated at", body["message"])

    def test_pages_bodies_are_bare_css(self):
        for key in ("page", "disabled"):
            body = self.out[key]["body"]
            self.assertNotIn("Cache-Control", body, key)
            self.assertFalse(body.lstrip().startswith("{"), key)
