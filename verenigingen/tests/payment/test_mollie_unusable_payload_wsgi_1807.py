"""
A Mollie refund/chargeback notification with no usable ids is refused with a real HTTP 400
and the bare ack, and never echoes the caller's payload (#1807).

Driven through the REAL WSGI app (``werkzeug.test.Client(frappe.app.application)``) in a
SUBPROCESS, because frappe.app.application destroys/re-inits frappe.local per request.
The HTTP status is the property under test, and only the real app turns
``frappe.response.http_status_code`` into a status line. Signature verification is
stubbed (an auth boundary with its own suite); the control row posts a well-formed refund
with the booking service stubbed, and must come back 200 ``ok``, so a 400 cannot be
a side effect of the harness.
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
    started = frappe.db.sql("select now(6)")[0][0]
    frappe.destroy()

    import frappe.app
    from werkzeug.test import Client
    from verenigingen.verenigingen_payments.mollie.services import webhook_wrapper_service_unified as mw

    API = "/api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api."
    MARKER = "echo-1807-marker"
    client = Client(frappe.app.application)

    def post(endpoint, payload, ip):
        frappe.init(site=SITE); frappe.connect()
        for key in frappe.cache.keys(f"cor_rate_limit:{{SITE}}:*{{endpoint}}*"):
            frappe.cache.delete(key)
        frappe.cache.delete_keys("mollie_webhook_failure:")
        frappe.destroy()
        with mock.patch(
            "verenigingen.verenigingen_payments.mollie.utils.webhook_security.authenticate_mollie_webhook"
        ), mock.patch.object(
            mw.UnifiedWebhookWrapperService, "process_reversal_webhook", return_value={{"status": "success"}}
        ):
            resp = client.post(
                API + endpoint,
                data=json.dumps(payload),
                content_type="application/json",
                headers={{"X-Frappe-Site-Name": SITE}},
                environ_overrides={{"REMOTE_ADDR": ip}},
            )
        return {{"code": resp.status_code, "body": resp.get_data(as_text=True)}}

    out = {{
        "refund": post("handle_refund_webhook", {{"resource": "refund", "note": MARKER}}, "198.51.100.71"),
        "chargeback": post("handle_chargeback_webhook", {{"status": "charged_back", "note": MARKER}}, "198.51.100.72"),
        "control": post(
            "handle_refund_webhook",
            {{"resource": "refund", "id": "re_1807", "status": "refunded", "payment_id": "tr_1807", "note": MARKER}},
            "198.51.100.73",
        ),
    }}
    # The two refusals each leave an Error Log row (committed by the real request): remove them.
    frappe.init(site=SITE); frappe.connect()
    frappe.db.delete("Error Log", {{"method": "Mollie Webhook Processing Error", "creation": [">=", started]}})
    frappe.db.commit()
    print("RESULT" + json.dumps(out))
    """
)


def _ack(resp):
    """The handler's return value; the public_api decorator wraps it as {headers, message}."""
    return json.loads(resp["body"])["message"]


class TestUnusablePayloadIsRefusedOverHttp(EnhancedTestCase):
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

    def test_missing_ids_are_a_400_with_only_the_ack(self):
        for endpoint in ("refund", "chargeback"):
            with self.subTest(endpoint=endpoint):
                resp = self.out[endpoint]
                self.assertEqual(resp["code"], 400, resp["body"])
                self.assertEqual(_ack(resp), {"status": "error"})
                self.assertNotIn("echo-1807-marker", resp["body"])

    def test_control_a_well_formed_refund_is_still_a_200_ok(self):
        resp = self.out["control"]
        self.assertEqual(resp["code"], 200, resp["body"])
        self.assertEqual(_ack(resp), {"status": "ok"})
