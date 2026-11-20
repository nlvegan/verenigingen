"""A bogus X-Mollie-Signature must not write an Error Log row per request (#2136).

Unsigned Mollie webhooks are accepted, so the guest endpoints are reachable by anyone; a
present-but-wrong signature used to step around the deduped, truncated path of #1822 and write
up to three untruncated rows per request. These tests drive the REAL WSGI app (a werkzeug
Client against ``frappe.app.application``, in a subprocess because the app destroys the
request-local state) and count Error Log rows created by the requests.

Nothing is stubbed. No fixture is created: the request fails at authentication, before any
document is read, so the subprocess commits nothing but the Error Log rows it is counting
(``tabError Log`` is MyISAM, so they are written either way).
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    mollie_settings_override,
)
from verenigingen.verenigingen_payments.utils.webhook_security import (
    WebhookAuthenticationError,
    _validate_test_mode_safety,
)

_API = "/api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api."
_ID_LENGTH = 900


def _run_requests() -> dict:
    script = textwrap.dedent(
        f"""
        import json, uuid
        import frappe

        SITE = {frappe.local.site!r}
        API = {_API!r}
        ID_LENGTH = {_ID_LENGTH}
        frappe.init(site=SITE)
        frappe.connect()
        start = frappe.utils.now_datetime()
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        client = Client(frappe.app.application, use_cookies=False)
        headers = {{"X-Frappe-Site-Name": SITE, "X-Mollie-Signature": "sha256=" + "0" * 64}}
        ids = []

        def post(endpoint):
            marker = uuid.uuid4().hex
            ids.append(marker)
            long_id = ("tr_" + marker).ljust(ID_LENGTH, "x")
            if endpoint == "handle_payment_webhook":
                r = client.post(API + endpoint, data={{"id": long_id}}, headers=headers)
            else:
                body = json.dumps({{"paymentId": long_id, "id": "re_" + marker}})
                r = client.post(API + endpoint, data=body, headers={{**headers, "Content-Type": "application/json"}})
            return r.status_code, r.get_data(as_text=True)

        def rows_since(mark):
            frappe.init(site=SITE)
            frappe.connect()
            rows = frappe.db.sql(
                "select method, error from `tabError Log` where creation >= %s", (mark,), as_dict=True
            )
            frappe.destroy()
            return rows

        out = {{"scenarios": {{}}}}
        for endpoint in ("handle_payment_webhook", "handle_refund_webhook", "handle_chargeback_webhook"):
            mark = None
            frappe.init(site=SITE); frappe.connect()
            mark = frappe.utils.now_datetime()
            frappe.destroy()
            responses = [post(endpoint) for _ in range(3)]
            rows = rows_since(mark)
            out["scenarios"][endpoint] = {{
                "statuses": [r[0] for r in responses],
                "bodies": [r[1] for r in responses],
                "titles": [r["method"] for r in rows],
                "max_error_len": max([len(r["error"] or "") for r in rows] or [0]),
                "rows_holding_a_full_id": sum(1 for r in rows if "x" * (ID_LENGTH - 200) in (r["error"] or "")),
            }}

        # Rate-limit rejections: the IP allowance drops to 1, so requests 2..4 are refused (429).
        from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import get_webhook_rate_limiter
        limiter = get_webhook_rate_limiter()
        limiter.ip_limit = 1
        limiter.ip_requests.clear()
        limiter.ip_penalties.clear()
        frappe.init(site=SITE); frappe.connect()
        mark = frappe.utils.now_datetime()
        frappe.destroy()
        responses = [post("handle_payment_webhook") for _ in range(4)]
        rows = rows_since(mark)
        out["rate_limited"] = {{
            "statuses": [r[0] for r in responses],
            "titles": [r["method"] for r in rows],
            "rows_holding_a_full_id": sum(1 for r in rows if "x" * (ID_LENGTH - 200) in (r["error"] or "")),
        }}
        print("RESULT" + json.dumps(out, default=str))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.join(get_bench_path(), "sites"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    line = next(x for x in result.stdout.splitlines() if x.startswith("RESULT"))
    return json.loads(line[len("RESULT") :])


class TestBogusSignatureErrorLog(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The subprocess runs a real WSGI app; the rows it writes live in the shared site DB,
        # so drop any cached dedupe state from earlier runs first.
        frappe.cache.delete_keys("webhook_error_log_once:")
        frappe.cache.delete_keys("mollie_webhook_failure:")
        frappe.cache.delete_keys("mollie_signature_failed:")
        cls.out = _run_requests()

    def test_three_bogus_signature_requests_write_a_bounded_number_of_rows(self):
        """3 requests per endpoint used to write ~9 rows; the cap is per failure kind, not per request."""
        for endpoint, got in self.out["scenarios"].items():
            with self.subTest(endpoint=endpoint):
                # Control: the requests really were refused at authentication, not accepted.
                self.assertEqual(got["statuses"], [500, 500, 500], got)
                self.assertLessEqual(len(got["titles"]), 3, f"{endpoint}: {got['titles']}")
                # The ids differ per request, so a dedupe keyed on the id would pass the cap
                # above; the handler's own row must be written once for the three requests.
                word = {"handle_refund_webhook": "refund", "handle_chargeback_webhook": "chargeback"}.get(
                    endpoint, "processing error"
                )
                own = [t for t in got["titles"] if word in t.lower() and "error" in t.lower()]
                self.assertEqual(len(own), 1, f"{endpoint}: {got['titles']}")

    def test_no_row_holds_the_callers_whole_id(self):
        for endpoint, got in self.out["scenarios"].items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(got["rows_holding_a_full_id"], 0, got)
                self.assertLess(got["max_error_len"], 4500, got)

    def test_the_caller_still_gets_only_the_ack(self):
        for endpoint, got in self.out["scenarios"].items():
            with self.subTest(endpoint=endpoint):
                for body in got["bodies"]:
                    self.assertEqual(json.loads(body)["message"], {"status": "error"})

    def test_rate_limit_rejections_write_one_row_not_one_per_rejection(self):
        got = self.out["rate_limited"]
        self.assertEqual(got["statuses"][1:], [429, 429, 429], got)
        self.assertLessEqual(sum(1 for t in got["titles"] if t.lower().startswith("mollie webhook rate limit")), 1, got["titles"])
        self.assertEqual(got["rows_holding_a_full_id"], 0, got)


class TestTestModeCriticalRowIsDeduped(EnhancedTestCase):
    """Mollie test_mode on a site that is not a development site refuses every webhook (#2136).

    ``_validate_test_mode_safety`` returns early on a developer_mode site, which is what the test
    sites are, so the branch is forced here: developer_mode off, test_mode on, no staging override.
    Both conf keys are restored afterwards.
    """

    def test_repeated_refusals_write_one_critical_row(self):
        saved = {k: frappe.conf.get(k) for k in ("developer_mode", "allow_mollie_test_mode")}
        frappe.conf["developer_mode"] = 0
        frappe.conf.pop("allow_mollie_test_mode", None)
        frappe.cache.delete_keys("webhook_error_log_once:")
        mark = frappe.utils.now_datetime()
        try:
            with mollie_settings_override(test_mode=True):
                for _ in range(3):
                    # Control: the refusal itself still happens on every call.
                    with self.assertRaises(WebhookAuthenticationError):
                        _validate_test_mode_safety()
        finally:
            for key, value in saved.items():
                if value is None:
                    frappe.conf.pop(key, None)
                else:
                    frappe.conf[key] = value
        rows = frappe.get_all(
            "Error Log",
            filters={"method": "Mollie Security - CRITICAL", "creation": [">=", mark]},
            pluck="name",
        )
        self.assertEqual(len(rows), 1, rows)
