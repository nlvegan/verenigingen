"""#2495: /application_success must not render a guest-supplied ``payment_url`` as a link unless it
points at this site.

Driven through the real WSGI app as Guest (separate process, no fixtures: the page reads only the
query string), reading the rendered HTML, so a controller-only fix that the template bypasses fails.
Only same-site URLs may become the "Complete Payment" button (the ``btn-lg`` anchor; the words
also appear as a step heading, so they are not the marker); ``javascript:``, foreign hosts,
protocol-relative and backslash/whitespace tricks must not.
"""

import json
import os
import subprocess
import sys
import textwrap
from urllib.parse import quote

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_bench_path

HOSTILE = [
    "javascript:alert(document.domain)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "\tjavascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "https://evil.example.invalid/pay",
    "http://evil.example.invalid/pay",
    "//evil.example.invalid/pay",
    "///evil.example.invalid/pay",
    "/\\evil.example.invalid/pay",
    "\\\\evil.example.invalid/pay",
    "https://localhost.evil.example.invalid/pay",
    "https://user@evil.example.invalid/pay",
    "https://localhost@evil.example.invalid/pay",
    "pay/relative",
]
SAME_SITE = [
    "/payment/membership/MEMBER-1/INV-1",
    "http://localhost/payment/membership/MEMBER-1/INV-1",
]


class TestApplicationSuccessPaymentUrl2495(IntegrationTestCase):
    def _probe(self, urls):
        script = textwrap.dedent(
            f"""
            import json, re
            import frappe
            SITE = {frappe.local.site!r}
            frappe.init(site=SITE)
            frappe.connect()
            frappe.destroy()
            import frappe.app
            from werkzeug.test import Client
            client = Client(frappe.app.application, use_cookies=False)
            out = {{}}
            for url, target in json.loads({json.dumps(json.dumps([[u, "/application_success?id=MEMBER-1&payment_url=" + quote(u, safe="")] for u in urls]))}):
                r = client.get(target, headers={{"X-Frappe-Site-Name": SITE}})
                body = r.get_data(as_text=True)
                out[url] = {{"status": r.status_code, "has_marker": bool(re.search(r'<a [^>]*btn-lg', body)),
                    "hrefs": re.findall(r'href="([^"]*)"', body), "body_len": len(body)}}
            print("RESULT" + json.dumps(out))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        line = next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))
        return json.loads(line[len("RESULT"):])

    def test_hostile_urls_never_render_as_a_link(self):
        out = self._probe(HOSTILE + SAME_SITE)
        for url in HOSTILE:
            with self.subTest(url=url):
                self.assertEqual(out[url]["status"], 200)
                self.assertFalse(out[url]["has_marker"], f"{url!r} rendered the Complete Payment button")
                self.assertFalse(
                    [h for h in out[url]["hrefs"] if "evil" in h or "javascript" in h.lower() or "data:" in h],
                    out[url]["hrefs"],
                )

    def test_same_site_url_still_renders_as_the_link(self):
        """Control: the guard must not refuse the legitimate shape (control for the hostile test)."""
        out = self._probe(SAME_SITE)
        for url in SAME_SITE:
            with self.subTest(url=url):
                self.assertTrue(out[url]["has_marker"], out[url])
                self.assertIn(url, out[url]["hrefs"])
