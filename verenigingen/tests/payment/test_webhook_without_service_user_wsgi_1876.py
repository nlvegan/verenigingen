"""
#1876: with no usable webhook user the gateway webhooks REFUSE (5xx, so the gateway
redelivers), write nothing, leave an Error Log row and say nothing about why; with the
configured user the same delivery is processed, as that user.

Driven through the REAL WSGI app (``werkzeug.test.Client(frappe.app.application)``, README
rule 21) in a SUBPROCESS, because frappe.app.application destroys/re-inits frappe.local per
request. State is read back on a FRESH connection. Only the gateway boundary and the
heavy business service are stubbed, each stub records the session user it ran as:

* Mollie  - ``UnifiedWebhookWrapperService.process_payment_webhook`` (the Mollie API fetch
  and the booking are covered by their own suites; the permission side is measured in the
  PR description, not here).
* ING     - ``verify_ing_checkout_webhook`` (signature) and the payment-plan finalizer.
* Ponto   - ``frappe.enqueue`` (recorded, not queued); the link status write is REAL.

Usage:
    scripts/testing/run_without_credentials.sh test_site_3 \
        verenigingen.tests.payment.test_webhook_without_service_user_wsgi_1876
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
    import json
    from unittest import mock
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()

    from verenigingen.tests.fixtures.ponto_test_data_factory import TestIBAN

    SETTINGS = "Verenigingen Payments Settings"
    API = "/api/method/verenigingen.verenigingen_payments."
    MOLLIE = API + "mollie.api.webhooks.handle_mollie_payment_webhook"
    ING = API + "ing_checkout.api.webhook.handle_payment"
    PONTO = API + "ponto.api.webhook.handle_ponto_webhook"
    out, created, ing_ids = {{}}, [], []
    calls = {{"mollie": [], "ing": [], "enqueue": []}}

    def fresh():
        frappe.destroy(); frappe.init(site=SITE); frappe.connect()

    def counts():
        fresh()
        c = {{t: frappe.db.count(t) for t in ("Error Log",)}}
        # scoped to the ING delivery: Ponto's generic error path writes its own rows
        c["ing_rows"] = frappe.db.count("Webhook Processing Log", {{"webhook_id": "EX-1876"}})
        return c

    def link_status(name):
        fresh()
        return frappe.db.get_value("Ponto Payment Link", name, "status")

    def set_user_setting(value):
        fresh(); frappe.set_user("Administrator")
        frappe.db.set_single_value(SETTINGS, "webhook_user", value)
        frappe.db.commit()

    previous = frappe.db.get_single_value(SETTINGS, "webhook_user")
    ponto_prev = {{k: frappe.db.get_single_value("Ponto Settings", k) for k in ("enable_webhooks", "require_webhook_signature")}}
    try:
        frappe.set_user("Administrator")
        if not previous:
            from verenigingen.setup.webhook_user_setup import setup_webhook_user
            assert setup_webhook_user()["success"]
            previous = frappe.db.get_single_value(SETTINGS, "webhook_user")
        out["configured_user"] = previous
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", 1)
        frappe.db.set_single_value("Ponto Settings", "require_webhook_signature", 0)
        d = frappe.new_doc("Ponto Payment Link")
        d.payment_type = "One-Time"; d.amount = 25; d.currency = "EUR"; d.description = "wsgi-1876"
        d.creditor_name = "Org"; d.creditor_iban = TestIBAN.ABN_AMRO_1
        d.status = "Pending Authorization"; d.ponto_request_id = "wsgi-1876"; d.redirect_link = "https://x/y"
        d.insert(); created.append(("Ponto Payment Link", d.name)); link = d.name

        # a real Payment Plan Payment: _parse_reference only recognises an EXISTING document
        from frappe.utils import today
        m = frappe.new_doc("Member")
        m.first_name = "Wsgi1876"; m.last_name = "Member"; m.email = "wsgi1876@example.com"
        m.member_since = today(); m.save(ignore_permissions=True)
        p = frappe.new_doc("Payment Plan")
        p.member = m.name; p.plan_type = "Equal Installments"; p.total_amount = 120.0
        p.number_of_installments = 3; p.frequency = "Monthly"; p.start_date = today()
        p.status = "Active"; p.reason = "test"; p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        i = frappe.get_doc({{"doctype": "Payment Plan Payment", "payment_plan": p.name,
            "installment_number": 1, "amount": 40.0, "currency": "EUR", "member": m.name,
            "gateway": "Pay.nl", "status": "Pending", "payment_id": "EX-1876"}}).insert(ignore_permissions=True)
        created += [("Payment Plan Payment", i.name), ("Payment Plan", p.name), ("Member", m.name)]
        frappe.db.commit()
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        from verenigingen.verenigingen_payments.mollie.services import webhook_wrapper_service_unified as mw
        from verenigingen.verenigingen_payments.ing_checkout.api import webhook as ingwh
        client = Client(frappe.app.application)
        H = {{"X-Frappe-Site-Name": SITE}}

        def mollie_stub(self, payment_id, data):
            calls["mollie"].append(frappe.session.user)
            return {{"status": "success"}}

        def ing_finalizer(name, payment_reference=None, status=None):
            calls["ing"].append(frappe.session.user)
            return {{"status": "success"}}

        def enqueue(*a, **k):
            calls["enqueue"].append(a[0] if a else k.get("method"))

        limiter = mock.MagicMock(); limiter.check_rate_limit.return_value = (True, None)
        ing_body = json.dumps({{"id": "EX-1876", "object": {{"reference": "PPP:" + i.name,
            "status": {{"code": 100}}, "amount": {{"value": 4000, "currency": "EUR"}}}}}})
        sync_body = json.dumps({{"data": {{"type": "pontoConnect.synchronization.succeeded", "id": "ev-sync-1876",
            "relationships": {{"account": {{"data": {{"id": "acc-1876"}}}}}}}}}})
        link_body = json.dumps({{"data": {{"type": "pontoConnect.paymentInitiationRequest.statusUpdated",
            "id": "wsgi-1876", "attributes": {{"status": "executed"}}}}}})

        # TEST-ONLY: today a Guest cannot insert a Webhook Processing Log (permission denied,
        # swallowed -- #1814), so a refusal routed through ING's generic `except` would write no
        # dedup row either way and the "no dedup row" control could never fail. Let the Guest
        # insert succeed so the row WOULD exist if the refusal went through that path.
        from frappe.model.document import Document
        _insert = Document.insert

        def insert_logs_ignoring_permissions(self, *a, **k):
            if self.doctype == "Webhook Processing Log":
                k["ignore_permissions"] = True
            return _insert(self, *a, **k)

        unhandled_body = json.dumps({{"data": {{"type": "pontoConnect.organization.blocked", "id": "ev-org-1876"}}}})

        def post(path, **kw):
            with mock.patch.object(Document, "insert", insert_logs_ignoring_permissions), \
                 mock.patch.object(mw.UnifiedWebhookWrapperService, "process_payment_webhook", mollie_stub), \\
                 mock.patch.object(ingwh, "verify_ing_checkout_webhook", return_value=True), \\
                 mock.patch.object(ingwh, "get_webhook_rate_limiter", return_value=limiter), \\
                 mock.patch("verenigingen.verenigingen_payments.services.payment_plan_finalization."
                            "finalize_payment_plan_installment", ing_finalizer), \\
                 mock.patch("verenigingen.verenigingen_payments.utils.webhook_security._validate_test_mode_safety"), \\
                 mock.patch("frappe.enqueue", enqueue):
                return client.post(path, headers=H, **kw)

        def leaks(resp):
            body = resp.get_data(as_text=True)
            # Only OUR reason is asserted absent. The generic error path of the ING and Ponto
            # handlers still puts an unrelated Guest-permission message into _server_messages;
            # PR #1827 (webhook_ack) closes that, and it is not this change's to close.
            return [w for w in ("webhook_user", "Administrator", "no usable", "fallback") if w in body]

        def run_all(tag):
            for k in calls: calls[k].clear()
            before = counts()
            # each endpoint has a per-IP hourly budget (Critical Operation Rule); this test
            # posts several times per run, so start every round from an empty bucket
            for op in ("handle_ponto_webhook", "handle_payment", "handle_mollie_payment_webhook"):
                for key in frappe.cache.keys(f"cor_rate_limit:{{SITE}}:*{{op}}*"):
                    frappe.cache.delete(key)
            r = {{}}
            resp = post(MOLLIE, data={{"id": "tr_1876" + tag}})
            r["mollie"] = {{"code": resp.status_code, "leaks": leaks(resp)}}
            resp = post(ING, data=ing_body, content_type="application/json")
            r["ing"] = {{"code": resp.status_code, "leaks": leaks(resp)}}
            resp = post(PONTO, data=sync_body, content_type="application/json")
            r["ponto_sync"] = {{"code": resp.status_code, "leaks": leaks(resp)}}
            resp = post(PONTO, data=link_body, content_type="application/json")
            r["ponto_link"] = {{"code": resp.status_code, "leaks": leaks(resp)}}
            resp = post(PONTO, data=unhandled_body, content_type="application/json")
            r["ponto_unhandled"] = {{"code": resp.status_code}}
            after = counts()
            r["calls"] = {{k: list(v) for k, v in calls.items()}}
            r["link_status"] = link_status(link)
            r["delta"] = {{k: after[k] - before[k] for k in before}}
            return r

        for state, arrange in (("unset", None), ("disabled", "disable"), ("nonexistent", "ghost")):
            fresh(); frappe.set_user("Administrator")
            if arrange == "disable":
                frappe.db.set_value("User", previous, "enabled", 0)
                frappe.db.set_single_value(SETTINGS, "webhook_user", previous)
            elif arrange == "ghost":
                frappe.db.set_single_value(SETTINGS, "webhook_user", "ghost-1876@example.com")
            else:
                frappe.db.set_single_value(SETTINGS, "webhook_user", None)
            frappe.db.commit()
            out["refused_" + state] = run_all(state)
            fresh(); frappe.set_user("Administrator")
            frappe.db.set_value("User", previous, "enabled", 1)
            frappe.db.commit()

        # redelivery after the operator fixes the user: ING must NOT have been deduped
        set_user_setting(previous)
        fresh()
        frappe.db.set_value("User", previous, "enabled", 1); frappe.db.commit()
        out["configured"] = run_all("ok")
    finally:
        fresh(); frappe.set_user("Administrator")
        frappe.db.set_value("User", previous, "enabled", 1) if previous and frappe.db.exists("User", previous) else None
        frappe.db.set_single_value(SETTINGS, "webhook_user", previous)
        for k, v in ponto_prev.items():
            frappe.db.set_single_value("Ponto Settings", k, v)
        for doctype, name in created:
            if doctype in ("Member", "Payment Plan", "Payment Plan Payment"):
                frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
            else:
                frappe.db.delete(doctype, {{"name": name}})
        frappe.db.delete("Webhook Processing Log", {{"webhook_id": ["in", ["EX-1876", "ev-sync-1876", "wsgi-1876", "ev-org-1876"]]}})
        frappe.db.commit()
    print("RESULT" + json.dumps(out))
    """
)


class TestGatewayWebhooksWithoutServiceUser(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sites_dir = os.path.join(get_bench_path(), "sites")
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT.format(site=frappe.local.site)],
            cwd=sites_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    STATES = ("unset", "disabled", "nonexistent")
    PATHS = ("mollie", "ing", "ponto_sync", "ponto_link")

    def test_every_path_answers_5xx_so_the_gateway_redelivers(self):
        for state in self.STATES:
            for path in self.PATHS:
                with self.subTest(state=state, path=path):
                    self.assertGreaterEqual(self.out[f"refused_{state}"][path]["code"], 500)

    def test_nothing_is_processed_and_nothing_queued_without_a_user(self):
        for state in self.STATES:
            with self.subTest(state=state):
                r = self.out[f"refused_{state}"]
                self.assertEqual(r["calls"], {"mollie": [], "ing": [], "enqueue": []})
                self.assertEqual(r["link_status"], "Pending Authorization")

    def test_ing_refusal_writes_no_dedup_row_so_the_retry_is_processed(self):
        for state in self.STATES:
            with self.subTest(state=state):
                self.assertEqual(self.out[f"refused_{state}"]["delta"]["ing_rows"], 0)
        ok = self.out["configured"]
        self.assertEqual(ok["ing"]["code"], 200)
        self.assertEqual(ok["calls"]["ing"], [self.out["configured_user"]])

    def test_an_event_with_no_handler_is_still_acked_without_a_user(self):
        """A no-op event must not become a retry loop just because the user is missing."""
        for state in self.STATES:
            with self.subTest(state=state):
                self.assertEqual(self.out[f"refused_{state}"]["ponto_unhandled"]["code"], 200)
        self.assertEqual(self.out["configured"]["ponto_unhandled"]["code"], 200)

    def test_an_error_log_row_is_left_for_every_refused_delivery(self):
        for state in self.STATES:
            with self.subTest(state=state):
                # 4 refused deliveries, each at least one row
                self.assertGreaterEqual(self.out[f"refused_{state}"]["delta"]["Error Log"], 4)

    def test_the_caller_learns_nothing_about_why(self):
        for state in self.STATES:
            for path in self.PATHS:
                with self.subTest(state=state, path=path):
                    self.assertEqual(self.out[f"refused_{state}"][path]["leaks"], [])

    def test_a_configured_user_is_processed_as_that_user(self):
        ok = self.out["configured"]
        user = self.out["configured_user"]
        for path in self.PATHS:
            with self.subTest(path=path):
                self.assertEqual(ok[path]["code"], 200)
        self.assertEqual(ok["calls"]["mollie"], [user])
        self.assertEqual(ok["calls"]["ing"], [user])
        self.assertEqual(ok["link_status"], "Executed")
        self.assertIn(
            "verenigingen.verenigingen_payments.ponto.api.webhook_handlers.import_transactions_job",
            ok["calls"]["enqueue"],
        )
