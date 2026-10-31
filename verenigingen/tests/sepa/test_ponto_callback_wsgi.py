"""
#1883 / #1875: the Ponto guest callbacks through the REAL WSGI app.

``frappe.handler.execute_cmd`` (used by test_ponto_callback_guest_status) has no
``sync_database``. A real GET goes through ``frappe/app.py::sync_database``, which ROLLS BACK
every request whose method is not unsafe unless ``frappe.local.flags.commit`` is set. So a
write that looks persistent in-process can vanish in production, and an in-process test
cannot tell. These tests therefore drive ``werkzeug.test.Client(frappe.app.application)``
and read the row back on a FRESH connection (a new ``frappe.init`` + ``connect`` after the
request), which cannot see uncommitted data.

Run as a SUBPROCESS: frappe.app.application calls frappe.destroy()/init() per request, which
would tear down this test's own frappe.local (same approach and reason as
test_core_client_permission_oracle). The subprocess owns every row it commits and deletes
them, and restores the webhook_user setting, in a ``finally``. The test process commits
nothing.

Usage:
    bench --site test_site_10 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_callback_wsgi
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SCRIPT = textwrap.dedent(
    """
    import json, re
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()

    from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN
    from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token as gen
    from verenigingen.verenigingen_payments.ponto.api import betaalverzoek_callback as link_cb
    from verenigingen.verenigingen_payments.ponto.api import payment_callback as req_cb

    EMAIL = "ponto-wsgi-1883@example.com"
    SETTINGS = "Verenigingen Payments Settings"
    created = []
    previous_webhook_user = frappe.db.get_single_value(SETTINGS, "webhook_user")
    out = {{}}

    def fresh():
        # a new process-local connection: sees committed data only
        frappe.destroy()
        frappe.init(site=SITE)
        frappe.connect()

    def status_of(doctype, name):
        fresh()
        return frappe.db.get_value(doctype, name, "status")

    def counts():
        fresh()
        return {{
            t: frappe.db.count(t)
            for t in ("Error Log", "Version", "Comment", "Activity Log", "Access Log")
        }}

    try:
        frappe.set_user("Administrator")
        if not frappe.db.exists("User", EMAIL):
            user = frappe.new_doc("User")
            user.email = EMAIL
            user.first_name = "PontoWsgi"
            user.send_welcome_email = 0
            user.append("roles", {{"role": "Verenigingen Webhook User"}})
            user.insert(ignore_permissions=True)
        frappe.db.set_value("User", EMAIL, "enabled", 1)
        frappe.db.set_single_value(SETTINGS, "webhook_user", EMAIL)

        def make_link(status="Pending Authorization", description="WSGI-1883-DESC"):
            d = frappe.new_doc("Ponto Payment Link")
            d.payment_type = "One-Time"
            d.amount = 25
            d.currency = "EUR"
            d.description = description
            d.creditor_name = "Org"
            d.creditor_iban = TestIBAN.ABN_AMRO_1
            d.status = status
            d.ponto_request_id = "wsgi-1883"
            d.redirect_link = "https://x/y"
            d.insert()
            created.append(("Ponto Payment Link", d.name))
            return d.name

        def make_request(status="Pending"):
            d = frappe.new_doc("Ponto Payment Request")
            d.ponto_account = "wsgi-acc"
            d.amount = 20
            d.currency = "EUR"
            d.creditor_name = "Org"
            d.creditor_iban = TestIBAN.ABN_AMRO_1
            d.remittance_info = "ref"
            d.status = status
            d.ponto_payment_id = "wsgi-1883"
            d.insert()
            created.append(("Ponto Payment Request", d.name))
            return d.name

        link_name, link_other = make_link(), make_link()
        req_name, req_other = make_request(), make_request()
        link_done = make_link("Executed", "WSGI-1883-RETURN-DETAILS")
        frappe.db.commit()

        tok = {{
            "link_cancel": gen(link_cb.CANCEL_TOKEN_PURPOSE, link_name),
            "link_other_cancel": gen(link_cb.CANCEL_TOKEN_PURPOSE, link_other),
            "link_return": gen(link_cb.RETURN_PROOF_PURPOSE, link_done),
            "req_cancel": gen(req_cb.CANCEL_TOKEN_PURPOSE, req_name),
            "req_other_cancel": gen(req_cb.CANCEL_TOKEN_PURPOSE, req_other),
        }}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client

        client = Client(frappe.app.application)
        headers = {{"X-Frappe-Site-Name": SITE}}
        LINK = "/api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback"
        REQ = "/api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback.payment_callback"

        def get(path):
            return client.get(path, headers=headers)

        before = counts()
        # control rows: none of these may persist anything
        get(f"{{LINK}}?payment_link={{link_name}}&error=access_denied")
        get(f"{{LINK}}?payment_link={{link_name}}&error=access_denied&cancel_token={{tok['link_other_cancel']}}")
        get(f"{{LINK}}?payment_link={{link_name}}&error=server_error&cancel_token={{tok['link_cancel']}}")
        get(f"{{REQ}}?payment_request={{req_name}}&error=access_denied")
        get(f"{{REQ}}?payment_request={{req_name}}&error=access_denied&cancel_token={{tok['req_other_cancel']}}")
        get(f"{{REQ}}?payment_request={{req_name}}&error=server_error&cancel_token={{tok['req_cancel']}}")
        out["control_link"] = status_of("Ponto Payment Link", link_name)
        out["control_request"] = status_of("Ponto Payment Request", req_name)
        after_controls = counts()

        # the proved cancels
        r1 = get(f"{{LINK}}?payment_link={{link_name}}&error=access_denied&cancel_token={{tok['link_cancel']}}")
        r2 = get(f"{{REQ}}?payment_request={{req_name}}&error=access_denied&cancel_token={{tok['req_cancel']}}")
        out["proved_link_code"] = r1.status_code
        out["proved_request_code"] = r2.status_code
        out["proved_link"] = status_of("Ponto Payment Link", link_name)
        out["proved_request"] = status_of("Ponto Payment Request", req_name)
        after_proved = counts()
        out["delta_controls"] = {{k: after_controls[k] - before[k] for k in before}}
        out["delta_proved"] = {{k: after_proved[k] - after_controls[k] for k in before}}

        # the legitimate return: follow the redirect the callback ACTUALLY returns
        r = get(f"{{LINK}}?payment_link={{link_done}}&return_proof={{tok['link_return']}}")
        loc = r.headers.get("Location") or ""
        path = re.sub(r"^https?://[^/]+", "", loc)
        out["return_location_path"] = path.split("?")[0]
        page = get(path)
        body = page.get_data(as_text=True)
        out["return_page_status"] = page.status_code
        out["return_page_has_details"] = "WSGI-1883-RETURN-DETAILS" in body
        # a guest who only knows the name is sent to /app/home and gets no token
        r = get(f"{{LINK}}?payment_link={{link_done}}")
        out["name_only_location_path"] = re.sub(r"^https?://[^/]+", "", r.headers.get("Location") or "")
    finally:
        frappe.destroy()
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        for doctype, name in created:
            frappe.db.delete(doctype, {{"name": name}})
        frappe.db.set_single_value(SETTINGS, "webhook_user", previous_webhook_user)
        frappe.db.commit()
        out["cleaned"] = not any(frappe.db.exists(d, n) for d, n in created)
    print("RESULT" + json.dumps(out))
    """
)


class TestPontoCallbackOverRealWsgi(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sites_dir = os.path.join(get_bench_path(), "sites")
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT.format(site=frappe.local.site)],
            cwd=sites_dir,
            capture_output=True,
            text=True,
            timeout=240,
        )
        cls.stderr = result.stderr[-3000:]
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    def test_subprocess_cleaned_up_its_committed_rows(self):
        self.assertTrue(self.out["cleaned"])

    def test_a_token_proved_cancel_persists_for_a_payment_link(self):
        self.assertEqual(self.out["proved_link"], "Cancelled")

    def test_a_token_proved_cancel_persists_for_a_payment_request(self):
        self.assertEqual(self.out["proved_request"], "Cancelled")

    def test_without_a_valid_cancel_token_nothing_persists(self):
        """Control rows: no token, another row's token, and a valid token with another
        error. All over the real app, read back on a fresh connection."""
        self.assertEqual(self.out["control_link"], "Pending Authorization")
        self.assertEqual(self.out["control_request"], "Pending")

    def test_committing_the_cancel_persists_no_unrelated_rows(self):
        """Measured side effects of the commit: the controls (rolled back) add no rows to
        these tables, and the proved cancels add only what the save itself writes."""
        self.assertEqual(self.out["delta_controls"], {k: 0 for k in self.out["delta_controls"]})
        delta = self.out["delta_proved"]
        self.assertEqual(delta["Error Log"], 0, delta)
        self.assertEqual(delta["Access Log"], 0, delta)
        self.assertEqual(delta["Comment"], 0, delta)

    def test_the_return_redirect_lands_on_a_page_with_the_details(self):
        """#1875: the URL the callback returns must render OUR page. At the hyphen route the
        payments app serves a 500 for these args."""
        self.assertEqual(self.out["return_location_path"], "/payment_success")
        self.assertEqual(self.out["return_page_status"], 200)
        self.assertTrue(self.out["return_page_has_details"])

    def test_a_name_only_guest_is_not_given_the_page(self):
        self.assertEqual(self.out["name_only_location_path"], "/app/home")
