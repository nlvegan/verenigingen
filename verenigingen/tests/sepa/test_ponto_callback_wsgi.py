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
them, restores the webhook_user setting, and removes the test user and the orphan
Comment/Version rows its writes left behind, in a ``finally``. The test process commits
nothing. Risk: if the subprocess is KILLED (not merely failing) the ``finally`` does not run,
webhook_user stays pointed at the test user and its rows stay; re-running the module
repairs both (it reuses the user and restores the setting recorded at the start of that run).
Every request carries its own REMOTE_ADDR, so the per-IP rate-limit bucket (30 per 5 min,
shared by all clients with no address) is never exhausted by repeated runs.

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
    user_created = False
    previous_webhook_user = frappe.db.get_single_value(SETTINGS, "webhook_user")
    out = {{}}
    TABLES = ("User", "Has Role", "Contact", "Notification Settings", "Version", "Comment",
              "Ponto Payment Link", "Ponto Payment Request", "Deleted Document")

    def table_counts():
        return {{t: frappe.db.count(t) for t in TABLES}}

    out["leak_before"] = table_counts()

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
        user_created = not frappe.db.exists("User", EMAIL)
        if user_created:
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

        # REALLY submitted rows (README rule 22): the submit lifecycle runs, so docstatus is 1 and
        # #1907's guard plus the docstatus 1 -> 1 permission check apply to the callback's save.
        # Only the Ponto HTTP client is stubbed. The Request also needs its payment-entry
        # prerequisites (a mapped bank account) checked at submit; that one method is stubbed
        # here because building a bank/company fixture inside a committing subprocess is out of
        # proportion. Nothing the callback does depends on it.
        from unittest.mock import MagicMock, patch
        from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
            PontoPaymentRequest,
        )

        def make_submitted_link():
            d = frappe.new_doc("Ponto Payment Link")
            d.payment_type = "One-Time"
            d.amount = 25
            d.currency = "EUR"
            d.description = "WSGI-1883-SUBMITTED"
            d.creditor_name = "Org"
            d.creditor_iban = TestIBAN.ABN_AMRO_1
            d.insert()
            created.append(("Ponto Payment Link", d.name))
            client = MagicMock()
            client.create_payment_request.return_value = MagicMock(id="wsgi-sub-link", redirect_link="https://x/y")
            with patch(
                "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client",
                return_value=client,
            ):
                d.submit()
            assert (d.docstatus, d.status) == (1, "Pending Authorization"), (d.docstatus, d.status)
            return d.name

        def make_submitted_request():
            d = frappe.new_doc("Ponto Payment Request")
            d.ponto_account = "wsgi-acc"
            d.amount = 20
            d.currency = "EUR"
            d.creditor_name = "Org"
            d.creditor_iban = TestIBAN.ABN_AMRO_1
            d.remittance_info = "ref"
            d.insert()
            created.append(("Ponto Payment Request", d.name))
            client = MagicMock()
            client.create_payment.return_value = MagicMock(id="wsgi-sub-req", redirect_link="https://x/y")
            with patch.object(PontoPaymentRequest, "_validate_payment_entry_prerequisites"), patch(
                "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client",
                return_value=client,
            ):
                d.submit()
            assert (d.docstatus, d.status) == (1, "Pending"), (d.docstatus, d.status)
            return d.name

        sub_link, sub_link_ctl = make_submitted_link(), make_submitted_link()
        sub_req, sub_req_ctl = make_submitted_request(), make_submitted_request()
        # rows for the short /ponto-return route
        short_ok, short_ctl, short_post = make_submitted_link(), make_submitted_link(), make_submitted_link()
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
            "sub_link_cancel": gen(link_cb.CANCEL_TOKEN_PURPOSE, sub_link),
            "sub_req_cancel": gen(req_cb.CANCEL_TOKEN_PURPOSE, sub_req),
            "short_ok_cancel": gen(link_cb.CANCEL_TOKEN_PURPOSE, short_ok),
            "short_ctl_wrong": gen(link_cb.CANCEL_TOKEN_PURPOSE, short_ok),
            "short_post_cancel": gen(link_cb.CANCEL_TOKEN_PURPOSE, short_post),
            "sub_link_ctl_wrong": gen(link_cb.CANCEL_TOKEN_PURPOSE, sub_link),
            "sub_req_ctl_wrong": gen(req_cb.CANCEL_TOKEN_PURPOSE, sub_req),
        }}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client

        client = Client(frappe.app.application)
        headers = {{"X-Frappe-Site-Name": SITE}}
        LINK = "/api/method/verenigingen.verenigingen_payments.ponto.api.betaalverzoek_callback.payment_link_callback"
        REQ = "/api/method/verenigingen.verenigingen_payments.ponto.api.payment_callback.payment_callback"

        import itertools, uuid
        seq = itertools.count(1)
        base = uuid.uuid4().int

        def get(path):
            n = base + next(seq)
            addr = f"10.{{(n >> 16) % 250 + 1}}.{{(n >> 8) % 250 + 1}}.{{n % 250 + 1}}"
            return client.get(path, headers=headers, environ_base={{"REMOTE_ADDR": addr}})

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

        # the same, on really submitted rows. Controls first: a token minted for ANOTHER row.
        get(f"{{LINK}}?payment_link={{sub_link_ctl}}&error=access_denied&cancel_token={{tok['sub_link_ctl_wrong']}}")
        get(f"{{REQ}}?payment_request={{sub_req_ctl}}&error=access_denied&cancel_token={{tok['sub_req_ctl_wrong']}}")
        out["sub_control_link"] = status_of("Ponto Payment Link", sub_link_ctl)
        out["sub_control_request"] = status_of("Ponto Payment Request", sub_req_ctl)
        get(f"{{LINK}}?payment_link={{sub_link}}&error=access_denied&cancel_token={{tok['sub_link_cancel']}}")
        get(f"{{REQ}}?payment_request={{sub_req}}&error=access_denied&cancel_token={{tok['sub_req_cancel']}}")
        fresh()
        out["sub_link"] = frappe.db.get_value("Ponto Payment Link", sub_link, ["status", "docstatus"])
        out["sub_request"] = frappe.db.get_value("Ponto Payment Request", sub_req, ["status", "docstatus"])

        # #1833 short route /ponto-return, same logic through the real app. The URL under test is
        # the one the doctype mints (build_return_url), not a hand-built one.
        def short(name, cancel=None, proof=None):
            return link_cb.build_return_url(name, cancel or "x", proof or "x")

        SHORT = link_cb.PONTO_RETURN_ROUTE

        def path_of(resp):
            return re.sub(r"^https?://[^/]+", "", resp.headers.get("Location") or "")

        # controls: another row's token on a submitted link; a POST carrying a VALID token
        # for its own row (the /api endpoint is GET-only, so is this); error other than access_denied
        rc = get(short(short_ctl, tok["short_ctl_wrong"]).replace("?", "?error=access_denied&", 1))
        rp = client.post(
            short(short_post, tok["short_post_cancel"]).replace("?", "?error=access_denied&", 1),
            headers=headers, environ_base={{"REMOTE_ADDR": "10.9.9.9"}},
        )
        out["short_control_wrong_token"] = status_of("Ponto Payment Link", short_ctl)
        out["short_control_post"] = status_of("Ponto Payment Link", short_post)
        out["short_control_post_location"] = path_of(rp)
        # the proved cancel on a really submitted row, persisted on a fresh connection
        rs = get(short(short_ok, tok["short_ok_cancel"]).replace("?", "?error=access_denied&", 1))
        out["short_proved_code"] = rs.status_code
        fresh()
        out["short_proved"] = frappe.db.get_value("Ponto Payment Link", short_ok, ["status", "docstatus"])
        out["short_proved_location"] = path_of(rs)
        # return: proof present, proof absent on a known name, unknown name
        done_url = link_cb.build_return_url(link_done, "x", tok["link_return"])
        rr = get(re.sub(r"^https?://[^/]+", "", done_url))
        out["short_return_code"] = rr.status_code
        out["short_return_path"] = path_of(rr).split("?")[0]
        page = get(path_of(rr))
        out["short_return_page_has_details"] = "WSGI-1883-RETURN-DETAILS" in page.get_data(as_text=True)
        rk = get(f"{{SHORT}}?l={{link_done}}")
        ru = get(f"{{SHORT}}?l=PONTO-LINK-NOPE-0000")
        out["short_known_no_proof"] = (rk.status_code, path_of(rk))
        out["short_unknown"] = (ru.status_code, path_of(ru))
        out["short_known_no_proof_body"] = rk.get_data(as_text=True)
        out["short_unknown_body"] = ru.get_data(as_text=True)

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
            frappe.db.delete("Comment", {{"reference_doctype": doctype, "reference_name": name}})
            frappe.db.delete("Version", {{"ref_doctype": doctype, "docname": name}})
        frappe.db.set_single_value(SETTINGS, "webhook_user", previous_webhook_user)
        if user_created:
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
            # delete_doc leaves its own audit trail for exactly what it deleted: a Deleted
            # Document row and a "Deleted" Comment (subject "<doctype> <name>", reference_name
            # NULL) for the User and for its Notification Settings. Remove those and nothing
            # else: no time-window delete, so audit rows written by anything else survive.
            for deleted_doctype in ("User", "Notification Settings"):
                frappe.db.delete(
                    "Deleted Document", {{"deleted_doctype": deleted_doctype, "deleted_name": EMAIL}}
                )
                frappe.db.delete(
                    "Comment",
                    {{
                        "comment_type": "Deleted",
                        "reference_doctype": deleted_doctype,
                        "subject": f"{{deleted_doctype}} {{EMAIL}}",
                    }},
                )
            frappe.db.delete("Version", {{"ref_doctype": "User", "docname": EMAIL}})
            frappe.db.delete("Comment", {{"reference_doctype": "User", "reference_name": EMAIL}})
        frappe.db.commit()
        out["cleaned"] = not any(frappe.db.exists(d, n) for d, n in created)
        out["leak_after"] = table_counts()
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
        """Row counts in the tables the run touches are identical before and after, so the
        test user (Has Role, Contact, Notification Settings, Version) and the orphan Comment
        and Version rows on the deleted Ponto rows are gone too."""
        self.assertTrue(self.out["cleaned"])
        self.assertEqual(self.out["leak_after"], self.out["leak_before"])

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
        self.assertEqual(delta["Activity Log"], 0, delta)
        self.assertEqual(delta["Comment"], 0, delta)
        # exactly one Version per proved cancel (one link, one request): the save itself
        self.assertEqual(delta["Version"], 2, delta)

    def test_the_return_redirect_lands_on_a_page_with_the_details(self):
        """#1875: the URL the callback returns must render OUR page. At the hyphen route the
        payments app serves a 500 for these args."""
        self.assertEqual(self.out["return_location_path"], "/payment_success")
        self.assertEqual(self.out["return_page_status"], 200)
        self.assertTrue(self.out["return_page_has_details"])

    def test_a_name_only_guest_is_not_given_the_page(self):
        self.assertEqual(self.out["name_only_location_path"], "/app/home")

    def test_a_token_proved_cancel_persists_on_really_submitted_rows(self):
        """README rules 21 and 22 together: real WSGI request, fresh-connection read, and rows
        that went through submit(). A plain save is refused by #1907's guard, the flag alone by
        the webhook user's missing submit right (#1920); only flag + ignore_permissions persists."""
        self.assertEqual(self.out["sub_link"], ["Cancelled", 1])
        self.assertEqual(self.out["sub_request"], ["Cancelled", 1])

    def test_a_token_for_another_row_does_not_cancel_a_submitted_row(self):
        """Control: real submitted rows to get wrong, a real (other) token."""
        self.assertEqual(self.out["sub_control_link"], "Pending Authorization")
        self.assertEqual(self.out["sub_control_request"], "Pending")

    # ---- #1833: the short guest return route /ponto-return -------------------------------

    def test_short_route_proved_cancel_persists_on_a_really_submitted_row(self):
        self.assertEqual(self.out["short_proved"], ["Cancelled", 1])
        self.assertEqual(self.out["short_proved_code"], 302)

    def test_short_route_refuses_another_rows_token_and_a_post(self):
        """Controls: a token minted for another row, and a POST with a valid token for its own."""
        self.assertEqual(self.out["short_control_wrong_token"], "Pending Authorization")
        self.assertEqual(self.out["short_control_post"], "Pending Authorization")
        self.assertEqual(self.out["short_control_post_location"], "/app/home")

    def test_short_route_return_lands_on_the_details_page(self):
        self.assertEqual(self.out["short_return_code"], 302)
        self.assertEqual(self.out["short_return_path"], "/payment_success")
        self.assertTrue(self.out["short_return_page_has_details"])

    def test_short_route_known_name_without_proof_answers_like_an_unknown_name(self):
        self.assertEqual(self.out["short_known_no_proof"], [302, "/app/home"])
        self.assertEqual(self.out["short_known_no_proof"], self.out["short_unknown"])
        self.assertEqual(self.out["short_known_no_proof_body"], self.out["short_unknown_body"])
