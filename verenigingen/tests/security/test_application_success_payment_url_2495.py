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

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_bench_path

# "{host}" is the hostname of get_url() and "{site}" its origin, resolved INSIDE the probe process:
# CI's site config sets host_name (http://test_site:8000), a dev bench has none (request host).
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
    "/\t/evil.example.invalid/pay",
    "/\n/evil.example.invalid/pay",
    "https://{host}.evil.example.invalid/pay",
    "https://{host}@evil.example.invalid/pay",
    "https://x@{host}/pay",
    "pay/relative",
]
SAME_SITE = [
    "/payment/membership/MEMBER-1/INV-1",
    "{site}/payment/membership/MEMBER-1/INV-1",
]


class TestApplicationSuccessPaymentUrl2495(IntegrationTestCase):
    def _probe(self, templates):
        script = textwrap.dedent(
            f"""
            import json, re
            from urllib.parse import quote, urlsplit
            import frappe
            SITE = {frappe.local.site!r}
            frappe.init(site=SITE)
            frappe.connect()
            origin = frappe.utils.get_url()
            host = urlsplit(origin).hostname
            frappe.destroy()
            import frappe.app
            from werkzeug.test import Client
            client = Client(frappe.app.application, use_cookies=False)
            out = {{}}
            for template in json.loads({json.dumps(json.dumps(templates))}):
                url = template.format(host=host, site=origin)
                target = "/application_success?id=MEMBER-1&payment_url=" + quote(url, safe="")
                # Without host_name, get_url() inside a request is the request's own Host; send the
                # probe's origin as Host so both sides agree (CI sets host_name and ignores it).
                r = client.get(target, base_url=origin, headers={{"X-Frappe-Site-Name": SITE}})
                body = r.get_data(as_text=True)
                out[template] = {{"url": url, "status": r.status_code,
                    "has_marker": bool(re.search(r'<a [^>]*btn-lg', body)),
                    "hrefs": re.findall(r'href="([^"]*)"', body)}}
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
        out = self._probe(HOSTILE)
        for template in HOSTILE:
            with self.subTest(url=template):
                row = out[template]
                self.assertEqual(row["status"], 200)
                self.assertFalse(row["has_marker"], f"{row['url']!r} rendered the Complete Payment button")
                self.assertNotIn(row["url"], row["hrefs"])

    def test_same_site_url_still_renders_as_the_link(self):
        """Control: the guard must not refuse the legitimate shape (control for the hostile test)."""
        out = self._probe(SAME_SITE)
        for template in SAME_SITE:
            with self.subTest(url=template):
                row = out[template]
                self.assertTrue(row["has_marker"], row)
                self.assertIn(row["url"], row["hrefs"])
