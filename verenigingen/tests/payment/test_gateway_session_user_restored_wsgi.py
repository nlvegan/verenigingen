"""
#2515: a gateway webhook (or the audit-trail flush) must not leave ``session.user`` switched
once its request is done.

``frappe.set_user`` rewrites the live session, and ``frappe/app.py::sync_database`` queues
``Session.update`` after the response; that writes the CURRENT user's ``last_active`` /
``last_ip`` unless that user is Guest (#2275 measured this for the Ponto guest callbacks).
The Mollie and ING Checkout handlers authenticate by ``set_user(<webhook user>)`` and PROCESS the
payment as that user, so the user has to stay switched while they work; it is put back when the
handler returns. The audit-trail flush switches to Administrator for one insert and used to
"restore" to the audit entry's user instead of the caller's.

Driven through the REAL WSGI app (``werkzeug.test.Client(frappe.app.application)``, buffered so
the after-response hooks run) in a SUBPROCESS, as ``test_ponto_callback_wsgi`` does, because
frappe.app.application destroys/re-inits ``frappe.local`` per request. A spy on
``Session.update`` records which user each queued update really saw (proof the hook ran) and the
``User`` row's ``last_ip`` / ``last_active`` is read back on a fresh connection.

Stand-ins, stated: signature verification is patched (an auth boundary with its own suites); the
payment-processing services are patched to record ``frappe.session.user`` and return success; the
audit-trail case flushes a buffer holding an entry for ANOTHER user from inside an otherwise
untouched Ponto guest request (a real buffer holds entries of earlier requests, the same way).
The Ponto request path is measured too: it never calls ``set_user`` (its two ``set_user`` calls
are RQ-job entry points), and the control asserts it is Guest throughout.

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_gateway_session_user_restored_wsgi
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
    import itertools, json, uuid
    from unittest import mock
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()

    EMAIL = "gateway-session-2515@example.com"
    OTHER = "Administrator"
    SETTINGS = "Verenigingen Payments Settings"
    user_created = False
    previous_webhook_user = frappe.db.get_single_value(SETTINGS, "webhook_user")
    previous_ponto_webhooks = frappe.db.get_single_value("Ponto Settings", "enable_webhooks")
    out = {{}}
    started = frappe.db.sql("select now(6)")[0][0]

    def fresh():
        frappe.destroy()
        frappe.init(site=SITE)
        frappe.connect()

    def trail(user):
        fresh()
        row = frappe.db.get_value("User", user, ["last_active", "last_ip"], as_dict=True)
        return {{k: str(v) for k, v in row.items()}}

    try:
        frappe.set_user("Administrator")
        user_created = not frappe.db.exists("User", EMAIL)
        if user_created:
            user = frappe.new_doc("User")
            user.email = EMAIL
            user.first_name = "GatewaySession"
            user.send_welcome_email = 0
            user.append("roles", {{"role": "Verenigingen Webhook User"}})
            user.insert(ignore_permissions=True)
        frappe.db.set_value("User", EMAIL, "enabled", 1)
        frappe.db.set_single_value(SETTINGS, "webhook_user", EMAIL)
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", 1)
        frappe.db.commit()
        frappe.destroy()

        import frappe.app
        import frappe.sessions as fs
        from werkzeug.test import Client
        from verenigingen.verenigingen_payments.mollie.api import unified_payment_api as mollie_api
        from verenigingen.verenigingen_payments.mollie.services import webhook_wrapper_service_unified as mw
        from verenigingen.verenigingen_payments.ing_checkout.api import webhook as ing_webhook
        from verenigingen.verenigingen_payments.ponto.api import webhook as ponto_webhook
        from verenigingen.verenigingen_payments.core.compliance import audit_trail as at

        client = Client(frappe.app.application)
        seq = itertools.count(1)
        base = uuid.uuid4().int

        update_seen = []
        real_update = fs.Session.update

        def spy_update(self, force=False):
            update_seen.append(frappe.session.user)
            return real_update(self, force)

        fs.Session.update = spy_update

        def post(path, payload, headers=None):
            n = base + next(seq)
            ip = f"10.{{(n >> 16) % 250 + 1}}.{{(n >> 8) % 250 + 1}}.{{n % 250 + 1}}"
            del update_seen[:]
            resp = client.post(
                path,
                data=json.dumps(payload),
                content_type="application/json",
                headers={{"X-Frappe-Site-Name": SITE, **(headers or {{}})}},
                buffered=True,
                environ_base={{"REMOTE_ADDR": ip}},
            )
            return {{
                "code": resp.status_code,
                "ip": ip,
                "updates": list(update_seen),
                "body": resp.get_data(as_text=True)[:300],
            }}

        def recorder(result):
            seen = []

            def record(*args, **kwargs):
                seen.append(frappe.session.user)
                return result

            return seen, record

        MOLLIE = "/api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api."
        sig = mock.patch(
            "verenigingen.utils.webhook_security.verify_mollie_webhook_signature", return_value=True
        )

        trails_before = {{EMAIL: trail(EMAIL), OTHER: trail(OTHER)}}

        # (1) Mollie payment webhook
        seen, record = recorder({{"status": "success"}})
        service = mock.Mock()
        service.process_payment_webhook.side_effect = record
        with sig, mock.patch.object(mollie_api, "get_unified_webhook_service", return_value=service):
            out["mollie_payment"] = post(MOLLIE + "handle_payment_webhook?id=tr_2515", {{"id": "tr_2515"}})
        out["mollie_payment"]["during"] = seen

        # (4) ING Checkout payment webhook, Payment Plan Payment branch (the only authenticate_webhook caller)
        seen, record = recorder({{"status": "success"}})
        order = "ord-2515-" + uuid.uuid4().hex[:8]
        with mock.patch.object(ing_webhook, "verify_ing_checkout_webhook"), mock.patch.object(
            ing_webhook, "_parse_reference", return_value=("Payment Plan Payment", "PPP-2515")
        ), mock.patch(
            "verenigingen.verenigingen_payments.services.payment_plan_finalization.finalize_payment_plan_installment",
            side_effect=record,
        ):
            out["ing_payment"] = post(
                "/api/method/verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment",
                {{
                    "id": order,
                    "object": {{
                        "reference": "PPP:PPP-2515",
                        "status": {{"code": 100, "action": "PAID"}},
                        "amount": {{"value": 4000, "currency": "EUR"}},
                    }},
                }},
            )
        out["ing_payment"]["during"] = seen

        # (5) Ponto signed webhook: the real handler, enqueue recorded instead of queued
        queued = []
        ponto_event = {{
            "data": {{
                "id": "evt-2515-" + uuid.uuid4().hex[:8],
                "type": "pontoConnect.synchronization.succeeded",
                "attributes": {{"accountId": "acct-2515"}},
            }}
        }}
        seen_in_ponto = []
        real_process = ponto_webhook.process_webhook_event

        def process_spy(event_type, event_data):
            seen_in_ponto.append(frappe.session.user)
            return real_process(event_type, event_data)

        with mock.patch.object(ponto_webhook, "verify_ponto_webhook", return_value={{"sub": "x"}}), mock.patch.object(
            ponto_webhook, "process_webhook_event", side_effect=process_spy
        ), mock.patch("frappe.enqueue", side_effect=lambda *a, **kw: queued.append(a[0] if a else kw)):
            out["ponto"] = post(
                "/api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook",
                ponto_event,
                headers={{"Signature": "x"}},
            )
        out["ponto"]["during"] = seen_in_ponto
        out["ponto"]["queued"] = [str(q) for q in queued]

        # (6) audit-trail flush inside an otherwise untouched Ponto guest request
        flushed = []

        def flush_a_buffer_holding_another_users_entry(event_type, event_data):
            flushed.append(frappe.session.user)  # who the request is when the flush starts
            trail_obj = at.ImmutableAuditTrail()
            trail_obj.buffer = []
            trail_obj.log_event(
                event_type=at.AuditEventType.PAYMENT_CREATED,
                severity=at.AuditSeverity.INFO,
                description="2515 audit flush probe",
                user=OTHER,
            )
            trail_obj._flush_buffer()
            flushed.append(frappe.session.user)  # who the request is when the flush is done
            return {{"handled": True}}

        with mock.patch.object(ponto_webhook, "verify_ponto_webhook", return_value={{"sub": "x"}}), mock.patch.object(
            ponto_webhook, "process_webhook_event", side_effect=flush_a_buffer_holding_another_users_entry
        ):
            out["audit_flush"] = post(
                "/api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook",
                ponto_event,
                headers={{"Signature": "x"}},
            )
        out["audit_flush"]["around_flush"] = flushed

        fs.Session.update = real_update
        out["trails_before"] = trails_before
        out["trails_after"] = {{EMAIL: trail(EMAIL), OTHER: trail(OTHER)}}
    finally:
        frappe.destroy()
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        frappe.db.set_single_value(SETTINGS, "webhook_user", previous_webhook_user)
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", previous_ponto_webhooks)
        frappe.db.delete("Mollie Audit Log", {{"description": "2515 audit flush probe"}})
        frappe.db.delete("Webhook Processing Log", {{"creation": [">=", started]}})
        frappe.db.delete("Error Log", {{"creation": [">=", started]}})
        if user_created:
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
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
    print("RESULT" + json.dumps(out))
    """
)

HANDLER_USER = "gateway-session-2515@example.com"


class TestGatewaySessionUserRestoredOverRealWsgi(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT.format(site=frappe.local.site)],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    GATEWAY_REQUESTS = ("mollie_payment", "ing_payment")

    def test_each_gateway_handler_still_processes_as_the_webhook_user(self):
        """Control: the user switch is what processing relies on, so it must still happen."""
        for name in self.GATEWAY_REQUESTS:
            with self.subTest(request=name):
                self.assertEqual(self.out[name]["code"], 200, self.out[name]["body"])
                self.assertEqual(self.out[name]["during"], [HANDLER_USER], self.out[name])

    def test_the_queued_session_update_runs_as_guest_after_each_gateway_request(self):
        """One queued Session.update per request (proof the hook ran), and it saw Guest."""
        for name in self.GATEWAY_REQUESTS + ("ponto", "audit_flush"):
            with self.subTest(request=name):
                self.assertEqual(len(self.out[name]["updates"]), 1, self.out[name])
        for name in self.GATEWAY_REQUESTS:
            with self.subTest(request=name):
                self.assertEqual(self.out[name]["updates"], ["Guest"])

    def test_the_ponto_request_path_never_switches_user(self):
        """The Ponto webhook only queues its jobs; their set_user calls run in the RQ worker."""
        self.assertEqual(self.out["ponto"]["code"], 200, self.out["ponto"]["body"])
        self.assertEqual(self.out["ponto"]["during"], ["Guest"])
        self.assertEqual(self.out["ponto"]["updates"], ["Guest"])
        self.assertTrue(
            any("import_transactions_job" in q for q in self.out["ponto"]["queued"]), self.out["ponto"]
        )

    def test_a_service_users_last_ip_is_not_written_by_gateway_requests(self):
        self.assertEqual(self.out["trails_after"][HANDLER_USER], self.out["trails_before"][HANDLER_USER])

    def test_the_audit_flush_gives_the_request_back_to_its_own_user(self):
        self.assertEqual(self.out["audit_flush"]["code"], 200, self.out["audit_flush"]["body"])
        self.assertEqual(self.out["audit_flush"]["around_flush"], ["Guest", "Guest"])
        self.assertEqual(self.out["audit_flush"]["updates"], ["Guest"])
        self.assertEqual(self.out["trails_after"]["Administrator"], self.out["trails_before"]["Administrator"])
