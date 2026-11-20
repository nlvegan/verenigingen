"""``/volunteer`` and ``/volunteer/index`` redirect to the volunteer dashboard instead of a 500 (#2263).

``templates/pages/volunteer/index.py`` only redirects, but it had no template beside it. Frappe's
``TemplatePage`` needs a template file to claim a route, so it declined ``/volunteer/index``; the
resolver then fell through to ``PrintPage`` (``/<doctype>/<name>`` print view, here doctype
"volunteer", name "index"), whose controller lookup raised ``ImportError: volunteer`` -> HTTP 500.
``/volunteer`` itself was a 404 for the same reason (no folder index to serve).

The request is a real WSGI GET (``werkzeug.test.Client(frappe.app.application)``) run in a
subprocess, because the app re-inits ``frappe.local`` and would tear down the test's own context.
The logged-in case uses a Sessions row made by ``frappe.sessions.Session`` (no password involved),
removed again in the subprocess. Only the redirect is asserted for both user classes; what the
dashboard itself then answers is the dashboard's business (#2207).
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_bench_path

PATHS = ["/volunteer", "/volunteer/", "/volunteer/index"]


class TestVolunteerIndexRoute(IntegrationTestCase):
    def test_volunteer_routes_redirect_to_the_dashboard_for_guest_and_logged_in(self):
        script = textwrap.dedent(
            f"""
            import json, frappe
            from werkzeug.test import Client
            frappe.init(site={frappe.local.site!r}, sites_path={frappe.local.sites_path!r})
            frappe.connect()
            import frappe.app
            from frappe.sessions import Session
            frappe.local.request = frappe._dict(cookies={{}}, environ={{}}, headers={{}}, remote_addr="127.0.0.1")
            frappe.local.form_dict = frappe._dict()
            frappe.local.request_ip = "127.0.0.1"
            sid = Session("Administrator", resume=False, full_name="Administrator", user_type="System User").sid
            frappe.db.commit()
            site = {frappe.local.site!r}
            out = {{}}
            try:
                for label in ("guest", "user"):
                    client = Client(frappe.app.application, use_cookies=False)
                    headers = {{"Cookie": "sid=" + sid}} if label == "user" else {{}}
                    who = client.get(
                        "/api/method/frappe.client.get_count?doctype=User", base_url="http://" + site, headers=headers
                    )
                    out[label + ":who"] = who.status_code
                    for path in {PATHS!r}:
                        r = client.get(path, base_url="http://" + site, headers=headers)
                        out[label + ":" + path] = [r.status_code, r.headers.get("Location")]
            finally:
                frappe.init(site=site, sites_path={frappe.local.sites_path!r})
                frappe.connect()
                frappe.db.delete("Sessions", {{"sid": sid}})
                frappe.db.commit()
                frappe.destroy()
            print("RESULT" + json.dumps(out))
            """
        )
        result = subprocess.run(
            [sys.executable, "-W", "ignore", "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        line = next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))
        out = json.loads(line[len("RESULT") :])

        # Control: the two requests really are different user classes.
        self.assertEqual(out["guest:who"], 403, "a Guest may not count Users")
        self.assertEqual(out["user:who"], 200, "the session cookie was not honoured")
        for label in ("guest", "user"):
            for path in PATHS:
                with self.subTest(user=label, path=path):
                    status, location = out[f"{label}:{path}"]
                    self.assertIn(status, (301, 302, 303), f"{path} answered {status}")
                    self.assertTrue(location.endswith("/volunteer/dashboard"), location)
