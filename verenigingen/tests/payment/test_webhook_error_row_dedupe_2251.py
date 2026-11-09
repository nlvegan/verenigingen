"""ING Checkout and Ponto guest webhooks: one Error Log row per failure kind, not per request (#2251).

``WebhookErrorHandler.log_error`` titled each row ``<Type> Error [<correlation id>]`` and the id is
minted per request, so every failing anonymous request wrote its own row; the ING "no valid security
layer" rejection did the same. The endpoints are driven through the REAL WSGI app (a werkzeug Client
in a subprocess, because the app destroys the request-local state), with a bad signature, and rows are
counted on a fresh connection. Rows are counted by the title prefix they carry before the fix as well
as after it, so the same count is red before and green after.
"""

import json
import os
import subprocess
import sys
import textwrap
from unittest.mock import patch

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import webhook_error_handler as handler_module
from verenigingen.verenigingen_payments.utils.webhook_error_handler import WebhookErrorHandler

_BASE = "/api/method/verenigingen.verenigingen_payments."
_REQUESTS = 4
_IP_ONE = "203.0.113.41"
_IP_TWO = "203.0.113.42"
_IP_SIGNED = "203.0.113.43"
# What the handler used to put in the title, and what it puts there now.
_TITLE_PREFIXES = ("Ing_Checkout_Payment Error", "Ing_Checkout_Mandate Error", "Ing_Checkout_Direct_Debit Error")


def _run_floods() -> dict:
    script = textwrap.dedent(
        f"""
        import json
        import frappe, frappe.app
        from werkzeug.test import Client

        SITE = {frappe.local.site!r}
        BASE = {_BASE!r}
        client = Client(frappe.app.application, use_cookies=False)

        def connect():
            frappe.init(site=SITE); frappe.connect()

        def now_mark():
            connect(); mark = frappe.utils.now_datetime(); frappe.destroy(); return mark

        def rows_since(mark):
            connect()
            rows = frappe.db.sql(
                "select name, method, error from `tabError Log` where creation >= %s", (mark,), as_dict=True
            )
            frappe.destroy()
            return rows

        def flood(path, ip, **headers):
            statuses = []
            for i in range({_REQUESTS}):
                r = client.post(
                    BASE + path, data=b'{{"id": "x%d"}}' % i,
                    headers={{"X-Frappe-Site-Name": SITE, "Content-Type": "application/json", **headers}},
                    environ_base={{"REMOTE_ADDR": ip}},
                )
                statuses.append(r.status_code)
            return statuses

        out = {{}}
        ing = {{
            "payment": "ing_checkout.api.webhook.handle_payment",
            "mandate": "ing_checkout.api.webhook.handle_mandate",
            "direct_debit": "ing_checkout.api.webhook.handle_direct_debit",
        }}
        mark = now_mark()
        statuses = {{k: flood(v, {_IP_ONE!r}, Signature="bad") for k, v in ing.items()}}
        statuses["payment_other_ip"] = flood(ing["payment"], {_IP_TWO!r}, Signature="bad")
        connect()
        out["secret_was_set"] = bool(
            frappe.get_single("Verenigingen Payments Settings").get_password(
                "ing_checkout_webhook_secret", raise_exception=False
            )
        )
        frappe.destroy()
        out["ing"] = {{"statuses": statuses, "rows": rows_since(mark)}}

        # With a webhook secret configured (production) a bad signature reaches
        # log_signature_validation_failed too. Set one for the flood, then put the setting back.
        from frappe.utils.password import remove_encrypted_password, set_encrypted_password
        DT = "Verenigingen Payments Settings"
        connect()
        original_secret = frappe.get_single(DT).get_password("ing_checkout_webhook_secret", raise_exception=False)
        set_encrypted_password(DT, DT, "probe-secret", "ing_checkout_webhook_secret")
        frappe.db.commit(); frappe.destroy()
        try:
            mark = now_mark()
            statuses = flood(ing["payment"], {_IP_SIGNED!r}, Signature="bad")
            out["ing_signed"] = {{"statuses": statuses, "rows": rows_since(mark)}}
        finally:
            connect()
            if original_secret:
                set_encrypted_password(DT, DT, original_secret, "ing_checkout_webhook_secret")
            else:
                remove_encrypted_password(DT, DT, "ing_checkout_webhook_secret")
            frappe.db.commit(); frappe.destroy()

        # Ponto answers 200 and writes nothing while webhooks are disabled, so enable them for the
        # flood and put the setting back (committed, because the subprocess has its own connection).
        connect()
        original = frappe.db.get_single_value("Ponto Settings", "enable_webhooks")
        frappe.db.set_single_value("Ponto Settings", "enable_webhooks", 1)
        frappe.db.commit(); frappe.destroy()
        try:
            mark = now_mark()
            statuses = flood("ponto.api.webhook.handle_ponto_webhook", {_IP_ONE!r}, Signature="a.b.c")
            out["ponto"] = {{"statuses": statuses, "rows": rows_since(mark)}}
        finally:
            connect()
            frappe.db.set_single_value("Ponto Settings", "enable_webhooks", original or 0)
            frappe.db.commit(); frappe.destroy()
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


class TestGuestFloodsWriteOneRowPerKind(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.cache.delete_keys("webhook_error_log_once:")
        cls.out = _run_floods()
        # The subprocess committed these rows, so the in-process rollback cannot reach them.
        cls.flood_rows = [r["name"] for kind in ("ing", "ing_signed", "ponto") for r in cls.out[kind]["rows"]]

    def setUp(self):
        super().setUp()
        # Hand them to the harness drain (it deletes and commits); once per class.
        for name in type(self).flood_rows:
            self.track_doc("Error Log", name)
        type(self).flood_rows = []

    def _titled(self, kind, *prefixes):
        return [r for r in self.out[kind]["rows"] if (r["method"] or "").startswith(prefixes)]

    def test_ing_signature_failures_write_one_row_per_endpoint_and_ip(self):
        statuses = self.out["ing"]["statuses"]
        # Control: every request really was refused as a signature failure.
        for kind, codes in statuses.items():
            self.assertEqual(codes, [401] * _REQUESTS, (kind, codes))
        rows = self._titled("ing", *_TITLE_PREFIXES)
        by_prefix = {p: [r for r in rows if r["method"].startswith(p)] for p in _TITLE_PREFIXES}
        # payment is flooded from two IPs (one row each), mandate and direct debit from one.
        self.assertEqual(
            {p: len(v) for p, v in by_prefix.items()},
            {_TITLE_PREFIXES[0]: 2, _TITLE_PREFIXES[1]: 1, _TITLE_PREFIXES[2]: 1},
            [r["method"] for r in rows],
        )
        for row in rows:
            self.assertNotRegex(row["method"], r"\[[0-9a-f]{8}\]")
            self.assertIn("Traceback", row["error"] or "")

    def test_ing_no_valid_security_layer_rejection_writes_one_row_per_ip(self):
        if self.out["secret_was_set"]:
            self.skipTest("a webhook secret is configured here, so the fail-closed branch is not reached")
        # Control: the flood was refused as a signature failure (so the branch really ran).
        self.assertEqual(self.out["ing"]["statuses"]["payment_other_ip"], [401] * _REQUESTS)
        rows = self._titled("ing", "ING Checkout webhook rejected")
        # Payment is flooded from two IPs (mandate and direct debit share the first): one row per IP.
        self.assertEqual(len(rows), 2, [r["method"] for r in rows])
        self.assertEqual({_IP_ONE in r["error"] for r in rows}, {True, False})

    def test_ing_bad_signature_with_a_secret_writes_one_row_per_kind(self):
        """A configured secret adds log_signature_validation_failed: count ALL new rows, not by prefix."""
        got = self.out["ing_signed"]
        self.assertEqual(got["statuses"], [401] * _REQUESTS)
        titles = sorted(r["method"] for r in got["rows"])
        self.assertEqual(len(titles), 2, titles)
        self.assertTrue(titles[0].startswith("Ing_Checkout_Payment Error"), titles)
        self.assertIn("signature_validation_failed", titles[1])

    def test_ponto_signature_failures_write_one_row(self):
        self.assertEqual(self.out["ponto"]["statuses"], [401] * _REQUESTS)
        rows = self._titled("ponto", "Ponto Error")
        self.assertEqual(len(rows), 1, [r["method"] for r in rows])
        self.assertEqual(rows[0]["method"], "Ponto Error")


class TestHandlerRowKey(EnhancedTestCase):
    """What the dedupe key is, and is not, made of (in-process; no request involved)."""

    def setUp(self):
        super().setUp()
        frappe.cache.delete_keys("webhook_error_log_once:")
        self.mark = frappe.utils.now_datetime()
        self.expectErrorLog("Probe Error")

    def _rows(self):
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", self.mark], "method": ["like", "Probe Error%"]},
            fields=["name", "method", "error"],
        )

    def _fail(self, exc, ip="203.0.113.50", message="Boom happened"):
        handler = WebhookErrorHandler("probe")  # a fresh correlation id every time
        # Mock justified: execution context (the client address) of an anonymous caller
        with patch.object(handler_module, "get_client_ip", return_value=ip):
            try:
                raise exc
            except Exception as e:
                handler.log_error(message, e)
        return handler

    def test_new_correlation_id_and_new_exception_text_do_not_make_a_new_row(self):
        for i in range(5):
            self._fail(RuntimeError(f"boom {i} " + "z" * 20000))
        rows = self._rows()
        self.assertEqual(len(rows), 1, [r.name for r in rows])
        self.assertLess(len(rows[0].error), 4500)
        self.assertEqual(rows[0].method, "Probe Error")

    def test_exception_class_ip_and_failure_label_each_start_a_new_row(self):
        self._fail(RuntimeError("a"))
        self._fail(KeyError("a"))
        self._fail(RuntimeError("a"), ip="203.0.113.51")
        self._fail(RuntimeError("a"), message="Another failure")
        self._fail(RuntimeError("a"))  # repeat of the first: no row
        self.assertEqual(len(self._rows()), 4)

    def test_dynamic_text_after_the_label_is_not_part_of_the_key(self):
        for i in range(3):
            self._fail(RuntimeError("a"), message=f"Webhook processing error: caller-chosen {i}")
        self.assertEqual(len(self._rows()), 1)

    def test_file_logger_line_is_still_written_every_time(self):
        handler = WebhookErrorHandler("probe")
        # Mock justified: observing the logger the handler owns
        with patch.object(handler, "logger") as logger:
            for _ in range(3):
                try:
                    raise RuntimeError("a")
                except RuntimeError as e:
                    handler.log_error("Boom happened", e)
        self.assertEqual(logger.error.call_count, 3)
