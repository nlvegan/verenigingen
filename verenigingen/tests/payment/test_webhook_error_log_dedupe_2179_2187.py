"""Guest webhook floods must not write an Error Log row per rejected request (#2179, #2187).

The shared ``WebhookRateLimiter`` wrote one row per rejection, in swapped (message, title)
order, and the two Mollie guest wrappers wrote one per failing request with an unbounded
f-string of the exception. #2136 closed the same shape for the Mollie handlers.

The limiter is driven through the REAL WSGI app (a werkzeug Client against
``frappe.app.application``, in a subprocess because the app destroys the request-local state),
with the limiter's allowance lowered inside that process so requests are rejected as they would
be in a flood. Rows are counted by the title the row would carry before the fix (the swapped
message) as well as after it, so the same count is red before and green after.
"""

import json
import os
import subprocess
import sys
import textwrap
from unittest.mock import patch

import frappe
from frappe.utils import get_bench_path
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import webhooks

_API = "/api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook"
_ID_LENGTH = 900


def _run_floods() -> dict:
    script = textwrap.dedent(
        f"""
        import json, uuid
        import frappe

        SITE = {frappe.local.site!r}
        URL = {_API!r}
        ID_LENGTH = {_ID_LENGTH}

        import frappe.app
        from werkzeug.test import Client
        from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import get_webhook_rate_limiter

        client = Client(frappe.app.application, use_cookies=False)
        # The limiter reads frappe.conf when first built, so build it while a site is bound.
        frappe.init(site=SITE); frappe.connect()
        limiter = get_webhook_rate_limiter()
        frappe.destroy()

        def now_mark():
            frappe.init(site=SITE); frappe.connect()
            mark = frappe.utils.now_datetime()
            frappe.destroy()
            return mark

        def rows_since(mark, *prefixes):
            frappe.init(site=SITE); frappe.connect()
            rows = frappe.db.sql(
                "select method, error from `tabError Log` where creation >= %s", (mark,), as_dict=True
            )
            frappe.destroy()
            return [
                r for r in rows
                if any((r["method"] or "").startswith(p) for p in prefixes)
            ]

        def flood(ids, **limits):
            limiter.ip_requests.clear(); limiter.ip_penalties.clear(); limiter.webhook_requests.clear()
            limiter.global_requests = type(limiter.global_requests)(limiter.time_window)
            limiter.ip_limit = limits.get("ip_limit", 1000)
            limiter.webhook_id_limit = limits.get("webhook_id_limit", 1000)
            limiter.global_limit = limits.get("global_limit", 1000)
            statuses = []
            for wid in ids:
                r = client.post(URL, data={{"id": wid}}, headers={{"X-Frappe-Site-Name": SITE}})
                statuses.append(r.status_code)
            return statuses

        def long_id():
            return ("tr_" + uuid.uuid4().hex).ljust(ID_LENGTH, "x")

        out = {{}}
        mark = now_mark()
        statuses = flood([long_id() for _ in range(6)], ip_limit=1)
        out["ip"] = {{"statuses": statuses, "rows": rows_since(mark, "Webhook Rate Limiting", "IP rate limit exceeded")}}

        mark = now_mark()
        statuses = flood([long_id() for _ in range(6)], global_limit=1)
        out["global"] = {{"statuses": statuses, "rows": rows_since(mark, "Webhook DDoS Protection", "Global webhook rate limit")}}

        mark = now_mark()
        ids = [long_id() for _ in range(3)]
        statuses = flood([i for i in ids for _ in range(2)], webhook_id_limit=1)
        out["webhook_id"] = {{"statuses": statuses, "rows": rows_since(mark, "Webhook Duplicate Protection", "Webhook ID rate limit exceeded")}}
        out["id_prefix"] = "x" * (ID_LENGTH - 200)
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


class TestLimiterRejectionsAreDeduped(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.cache.delete_keys("webhook_error_log_once:")
        cls.out = _run_floods()

    def _check(self, kind, minimum_rejections, expected_title):
        got = self.out[kind]
        # Control: the flood really was rejected, so a count of 1 is dedupe and not "nothing happened".
        self.assertGreaterEqual(got["statuses"].count(429), minimum_rejections, got["statuses"])
        self.assertEqual(len(got["rows"]), 1, [r["method"][:60] for r in got["rows"]])
        self.assertEqual(got["rows"][0]["method"], expected_title)
        for row in got["rows"]:
            self.assertNotIn(self.out["id_prefix"], row["error"] or "")

    def test_ip_limit_flood_writes_one_row(self):
        self._check("ip", 4, "Webhook Rate Limiting")

    def test_global_limit_flood_writes_one_row(self):
        self._check("global", 4, "Webhook DDoS Protection")

    def test_webhook_id_flood_writes_one_row_across_three_distinct_ids(self):
        """Three ids each rejected once: a dedupe keyed on the (caller-chosen) id would write three."""
        self._check("webhook_id", 3, "Webhook Duplicate Protection")


class TestMollieWrapperRowsAreDeduped(EnhancedTestCase):
    """The wrappers' except branch (#2187). The failure is injected at the unified handler boundary."""

    def setUp(self):
        super().setUp()
        frappe.cache.delete_keys("webhook_error_log_once:")
        self.mark = frappe.utils.now_datetime()

    def _rows(self, title, old_message_prefix):
        """Rows under the title, or (before the fix) under the swapped message that became the title."""
        rows = frappe.get_all(
            "Error Log", filters={"creation": [">=", self.mark]}, fields=["name", "method", "error"]
        )
        return [r for r in rows if r.method.startswith((title, old_message_prefix))]

    def _flood(self, endpoint, title, old_message_prefix):
        # Mock justified: injects an unexpected exception at the service boundary
        with patch(
            "verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_payment_webhook"
        ) as handler:
            for i in range(5):
                handler.side_effect = RuntimeError(f"boom {i} " + "z" * 20000)
                self.assertEqual(endpoint(), {"status": "error"})  # control: still 5xx ack
                self.assertEqual(frappe.response.http_status_code, 500)
            handler.side_effect = KeyError("other class")
            endpoint()
        rows = self._rows(title, old_message_prefix)
        # One row for RuntimeError x5, one for the different class (a control that the key is
        # the class and not constant).
        self.assertEqual(len(rows), 2, [r.name for r in rows])
        self.assertTrue(all(len(r.error or "") < 4500 for r in rows))

    def test_payment_wrapper(self):
        self.expectErrorLog("Mollie Webhook API", "Webhook endpoint error")
        self._flood(webhooks.handle_mollie_payment_webhook.__wrapped__, "Mollie Webhook API", "Webhook endpoint error")

    def test_unified_wrapper(self):
        self.expectErrorLog("Mollie Webhook Error", "Unexpected error in unified")
        original = getattr(frappe.local, "request", None)
        self.addCleanup(setattr, frappe.local, "request", original)
        frappe.local.request = Request(EnvironBuilder(method="POST", data=b"{}").get_environ())
        self._flood(webhooks.handle_unified_webhook.__wrapped__, "Mollie Webhook Error", "Unexpected error in unified")
