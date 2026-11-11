"""The Mollie guest webhook answers an unknown payment id exactly like a known one (#1805).

Residual of #1781: a payment id Mollie 404s used to answer 503 + ``Retry-After`` while a known
id answered 200, so an anonymous caller could probe which ``tr_`` ids exist. Maintainer ruling
2026-11-11: ONLY Mollie's ``NotFoundError`` (404) is permanent -> answered like a known id, an
Error Log row and a staff alert (``mollie_payment_not_found``) say so. Timeouts, 5xx and every
other fetch failure keep 503 + Retry-After, because that retry books a real payment after an
outage.

The probe runs in a SUBPROCESS (``frappe.app.application`` destroys ``frappe.local`` per request,
which would pull this test's own out from under it) through the real WSGI app as Guest.
Only the Mollie HTTP layer (``requests.Session.request`` for api.mollie.com URLs) is stubbed, so
the REAL Mollie SDK turns 404/500 into its own exception types and every client in the app
(router, idempotency manager, wrapper) is exercised. Two shortcuts, stated: signature
verification (an auth boundary with its own tests) and the API-key lookup are patched, and a
probe webhook user is committed and removed again. The "known id" is a Mollie payment carrying
``Payment Plan Payment`` metadata, which the webhook finalises to a 200 ack without booking.
"""

import json
import os
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_PROBE = r"""
import itertools, json, re, sys, uuid
from unittest.mock import patch
import frappe, requests

SITE = sys.argv[1]
SETTINGS = "Verenigingen Payments Settings"
EMAIL = "mollie-1805-probe@example.com"
frappe.init(site=SITE)
frappe.connect()
created = []
user_created = False
previous_user = frappe.db.get_single_value(SETTINGS, "webhook_user")
out = {}
try:
    frappe.set_user("Administrator")
    user_created = not frappe.db.exists("User", EMAIL)
    if user_created:
        u = frappe.new_doc("User")
        u.email, u.first_name, u.send_welcome_email = EMAIL, "Mollie1805", 0
        u.append("roles", {"role": "Verenigingen Webhook User"})
        u.insert(ignore_permissions=True)
    frappe.db.set_value("User", EMAIL, "enabled", 1)
    frappe.db.set_single_value(SETTINGS, "webhook_user", EMAIL)
    from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
    ensure_notification_registry_rows()
    ppp = frappe.get_doc({"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 5.0,
        "currency": "EUR", "status": "Pending"})
    ppp.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
    created.append(("Payment Plan Payment", ppp.name))
    frappe.db.commit()
    frappe.destroy()

    import frappe.app
    from werkzeug.test import Client
    from frappe.database.database import Database
    client = Client(frappe.app.application, use_cookies=False)
    H = {"X-Frappe-Site-Name": SITE}
    URL = "/api/method/verenigingen.verenigingen_payments.mollie.api.webhooks.mollie_payment_webhook"
    seq = itertools.count(1)
    base = uuid.uuid4().int

    def addr():
        n = base + next(seq)
        return f"10.{(n >> 16) % 250 + 1}.{(n >> 8) % 250 + 1}.{n % 250 + 1}"

    # --- the Mollie HTTP layer ------------------------------------------------------------
    plan = {"v": None}
    def resp(code, payload):
        r = requests.Response()
        r.status_code = code
        r._content = json.dumps(payload).encode()
        r.headers["Content-Type"] = "application/hal+json"
        return r
    def payment_json(pid):
        return {"resource": "payment", "id": pid, "status": "open", "mode": "test",
                "amount": {"value": "5.00", "currency": "EUR"}, "description": "x",
                "metadata": {"reference_doctype": "Payment Plan Payment", "reference_docname": ppp.name},
                "_links": {}}
    NOT_FOUND = {"status": 404, "title": "Not Found", "detail": "No payment exists with token x",
                 "_links": {}}
    real_request = requests.Session.request
    calls = {"n": 0}
    def fake_request(self, method=None, url=None, **kw):
        if "api.mollie.com" not in (url or ""):
            return real_request(self, method=method, url=url, **kw)
        calls["n"] += 1
        pid = url.rsplit("/", 1)[-1]
        mode = plan["v"]
        if mode == "known":
            return resp(200, payment_json(pid))
        if mode == "404":
            return resp(404, NOT_FOUND)
        if mode == "500":
            return resp(500, {"status": 500, "title": "Internal Server Error", "detail": "x", "_links": {}})
        if mode == "401":
            return resp(401, {"status": 401, "title": "Unauthorized Request", "detail": "x", "_links": {}})
        if mode == "timeout":
            raise requests.exceptions.ConnectTimeout("timed out")
        if mode == "chargebacks_404":
            # payments.get and the refunds list succeed; only the chargebacks list 404s
            if url.endswith("/refunds"):
                return resp(200, {"count": 0, "_embedded": {"refunds": []}, "_links": {}})
            if url.endswith("/chargebacks"):
                return resp(404, NOT_FOUND)
            body = payment_json(pid)
            body["metadata"] = {}
            return resp(200, body)
        if mode == "found_then_404":
            # the payment GET succeeds once (classification), then Mollie 404s every later call
            if plan.setdefault("seen", set()) is not None and pid not in plan["seen"]:
                plan["seen"].add(pid)
                body = payment_json(pid)
                body["metadata"] = {}
                return resp(200, body)
            return resp(404, NOT_FOUND)
        raise AssertionError("no plan: " + str(mode))

    real_sql = Database.sql
    counter = {"n": 0}
    def counting_sql(self, *a, **kw):
        counter["n"] += 1
        return real_sql(self, *a, **kw)

    def snapshot():
        frappe.init(site=SITE); frappe.connect()
        errs = {r[0]: (r[1] or "", r[2] or "") for r in frappe.db.sql("select name, method, error from `tabError Log`")}
        notes = {r[0] for r in frappe.db.sql(
            "select name from `tabNotification Log` where subject like '%Mollie webhook for a payment id%'")}
        frappe.destroy()
        return errs, notes

    VOLATILE = {"date", "content-length", "x-frappe-request-id", "x-ratelimit-remaining", "x-ratelimit-reset",
                "x-ratelimit-limit", "x-request-id", "server"}
    def post(pid, mode, ip=None, extra=None):
        plan["v"] = mode
        before_errs, before_notes = snapshot()
        counter["n"] = 0
        patches = [
            patch("verenigingen.utils.webhook_security.verify_mollie_webhook_signature"),
            patch("verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
                  "MollieSettings.get_active_api_key", return_value="test_" + "a" * 30),
            patch("verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key",
                  return_value="test_" + "a" * 30),
            patch.object(requests.Session, "request", fake_request),
            patch.object(Database, "sql", counting_sql),
        ] + (extra or [])
        for p in patches: p.start()
        try:
            r = client.post(URL, data={"id": pid}, headers=H, environ_base={"REMOTE_ADDR": ip or addr()})
        finally:
            for p in reversed(patches): p.stop()
        errs, notes = snapshot()
        body = r.get_data(as_text=True)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {}
        # The rate-limit counters legitimately differ per request; everything else in the body
        # (including the "Retry-After" key frappe puts there, see the test below) is compared.
        for counter_key in ("X-RateLimit-Remaining", "X-RateLimit-Reset"):
            (parsed.get("headers") or {}).pop(counter_key, None)
        norm = lambda s: re.sub(r"[0-9a-f]{40,}", "<ID>", (s or "").replace(pid, "<ID>"))
        # "Webhook Permissions Error" is the probe user's own role gap, logged on EVERY delivery
        # (known ones too); it says nothing about the payment id.
        new_errs = sorted((norm(m), norm(e)) for k, (m, e) in errs.items()
                          if k not in before_errs and m != "Webhook Permissions Error")
        return {
            "status": r.status_code,
            "headers": sorted((k.lower(), re.sub(r"Expires=[^;]+", "Expires=<T>", v))
                              for k, v in r.headers if k.lower() not in VOLATILE),
            "body": norm(json.dumps(parsed, sort_keys=True)),
            "server_messages": norm(parsed.get("_server_messages") or ""),
            "error_logs": new_errs,
            "notifications": len(notes - before_notes),
            "queries": counter["n"],
        }

    tid = lambda: "tr_" + uuid.uuid4().hex[:10]
    # warm every cache the measured cases touch
    for mode in ("known", "404", "500"):
        post(tid(), mode)
    out["known"] = post(tid(), "known")
    ip_a = addr()
    out["unknown_404"] = post(tid(), "404", ip=ip_a)
    out["unknown_404_same_ip_other_id"] = post(tid(), "404", ip=ip_a)
    out["unknown_404_other_ip"] = post(tid(), "404")
    out["found_then_404"] = post(tid(), "found_then_404")
    out["transient_500"] = post(tid(), "500")
    out["transient_timeout"] = post(tid(), "timeout")
    out["auth_401"] = post(tid(), "401")
    out["chargebacks_list_404"] = post(tid(), "chargebacks_404")
    ip6 = "2001:db8:%x:%x" % (base % 65535, (base >> 16) % 65535)
    out["ipv6_first"] = post(tid(), "404", ip=ip6 + "::1")
    out["ipv6_same_64"] = post(tid(), "404", ip=ip6 + "::2")
    out["ipv6_other_64"] = post(tid(), "404", ip="2001:db8:%x:%x::1" % ((base >> 8) % 65535, (base >> 24) % 65535))
    ip_b = addr()
    out["notify_fails_first"] = post(tid(), "404", ip=ip_b, extra=[patch(
        "verenigingen.utils.notification_helpers.notify_administrators", side_effect=RuntimeError("mail down"))])
    out["retry_after_failed_alert"] = post(tid(), "404", ip=ip_b)
    out["after_delivered_alert"] = post(tid(), "404", ip=ip_b)
    boom = patch("verenigingen.utils.notification_helpers.notify_administrators", side_effect=RuntimeError("mail down"))
    out["unknown_404_notify_fails"] = post(tid(), "404", extra=[boom])
    print("RESULT" + json.dumps(out))
finally:
    frappe.init(site=SITE)
    frappe.connect()
    for dt, name in created:
        try:
            frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            print("CLEANUP_FAILED " + dt + " " + str(e))
    frappe.db.set_single_value(SETTINGS, "webhook_user", previous_user)
    if user_created:
        try:
            frappe.delete_doc("User", EMAIL, force=True, ignore_permissions=True)
        except Exception as e:
            print("CLEANUP_FAILED User " + str(e))
    frappe.db.commit()
    left = [(dt, n) for dt, n in created if frappe.db.exists(dt, n)]
    left += [("User", EMAIL)] if user_created and frappe.db.exists("User", EMAIL) else []
    print("LEFTOVER" + json.dumps(left))
    frappe.destroy()
"""


class TestMollieWebhookUnknownIdOracle(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            result = subprocess.run(
                [sys.executable, "-c", _PROBE, frappe.local.site],
                cwd=os.path.join(get_bench_path(), "sites"),
                capture_output=True,
                text=True,
                timeout=420,
            )
        except subprocess.TimeoutExpired as e:
            raise AssertionError(f"the WSGI probe did not finish in 420s; stdout: {e.stdout}") from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def test_control_a_known_id_is_a_plain_200_ack(self):
        known = self.out["known"]
        self.assertEqual(known["status"], 200)
        self.assertEqual(json.loads(known["body"])["message"], {"status": "ok"})
        self.assertNotIn("Retry-After", json.loads(known["body"]))
        self.assertNotIn("retry-after", dict(known["headers"]))

    def test_an_unknown_id_matches_a_known_one_on_status_headers_body_and_messages(self):
        known, unknown = self.out["known"], self.out["unknown_404"]
        for channel in ("status", "headers", "body", "server_messages"):
            with self.subTest(channel=channel):
                self.assertEqual(unknown[channel], known[channel])

    def test_an_unknown_id_is_loud_to_staff_but_a_known_one_is_not(self):
        known, unknown = self.out["known"], self.out["unknown_404"]
        self.assertEqual((known["error_logs"], known["notifications"]), ([], 0))
        self.assertEqual(len(unknown["error_logs"]), 1, unknown["error_logs"])
        self.assertIn("Payment Not Found", unknown["error_logs"][0][0])
        # One Notification Log per staff recipient: the control tests compare against this count.
        self.assertGreater(unknown["notifications"], 0)

    def test_a_repeat_404_from_the_same_caller_writes_no_second_row_or_alert(self):
        again = self.out["unknown_404_same_ip_other_id"]
        self.assertEqual((again["error_logs"], again["notifications"]), ([], 0))
        # still the same answer to the caller
        for channel in ("status", "headers", "body"):
            self.assertEqual(again[channel], self.out["known"][channel])

    def test_control_a_different_caller_is_not_silenced_by_the_first(self):
        other = self.out["unknown_404_other_ip"]
        self.assertEqual(len(other["error_logs"]), 1)
        self.assertGreater(other["notifications"], 0)
        self.assertEqual(other["notifications"], self.out["unknown_404"]["notifications"])

    def test_the_alert_says_further_ids_from_the_caller_are_not_listed(self):
        self.assertIn("NOT listed individually", self.out["unknown_404"]["error_logs"][0][1])

    def test_a_chargebacks_list_404_is_not_the_payment_being_unknown(self):
        """Only ``payments.get`` proves the id unknown; a failing sub-list keeps the retryable 503."""
        got = self.out["chargebacks_list_404"]
        self.assertEqual(got["status"], 503)
        self.assertEqual(json.loads(got["body"]).get("Retry-After"), "60")
        self.assertEqual(got["notifications"], 0)
        self.assertFalse([m for m, _ in got["error_logs"] if "Payment Not Found" in m], got["error_logs"])

    def test_an_ipv6_caller_is_deduped_on_its_64(self):
        first, same, other = (self.out[k] for k in ("ipv6_first", "ipv6_same_64", "ipv6_other_64"))
        self.assertEqual(len(first["error_logs"]), 1)
        self.assertGreater(first["notifications"], 0)
        self.assertEqual((same["error_logs"], same["notifications"]), ([], 0))
        # control: another /64 is another caller
        self.assertEqual(len(other["error_logs"]), 1)
        self.assertGreater(other["notifications"], 0)

    def test_a_failed_alert_does_not_use_up_the_dedupe_window(self):
        failed = self.out["notify_fails_first"]
        self.assertTrue(any("alert failed" in m for m, _ in failed["error_logs"]), failed["error_logs"])
        retry = self.out["retry_after_failed_alert"]
        self.assertGreater(retry["notifications"], 0, "the next delivery must try the alert again")
        self.assertTrue(any(m == "Mollie Webhook Payment Not Found" for m, _ in retry["error_logs"]))
        # control: once delivered, the window is used
        again = self.out["after_delivered_alert"]
        self.assertEqual((again["error_logs"], again["notifications"]), ([], 0))

    def test_a_failing_alert_does_not_turn_the_200_into_an_error(self):
        failed = self.out["unknown_404_notify_fails"]
        for channel in ("status", "headers", "body"):
            self.assertEqual(failed[channel], self.out["known"][channel])
        self.assertTrue(any("alert failed" in m for m, _ in failed["error_logs"]), failed["error_logs"])

    def test_a_404_after_the_id_was_found_is_answered_the_same_way(self):
        """The router GET succeeds, the idempotency check's GET 404s: STEP 1 must see the 404 too."""
        race = self.out["found_then_404"]
        for channel in ("status", "headers", "body"):
            self.assertEqual(race[channel], self.out["known"][channel])
        self.assertGreater(race["notifications"], 0)

    def test_control_every_other_fetch_failure_stays_retryable(self):
        for case in ("transient_500", "transient_timeout", "auth_401"):
            with self.subTest(case=case):
                got = self.out[case]
                self.assertEqual(got["status"], 503)
                # ``frappe.local.response["Retry-After"]`` lands as a BODY key, not an HTTP header
                # (measured here); the unknown-id answer carries neither.
                self.assertEqual(json.loads(got["body"]).get("Retry-After"), "60")
                self.assertEqual(got["notifications"], 0)


def _mollie_sdk_http_layer_1805(code, payload=None, raises=None):
    """Replace only the HTTP call the real Mollie SDK makes to api.mollie.com."""
    import requests

    real = requests.Session.request

    def fake(self, method=None, url=None, **kw):
        if "api.mollie.com" not in (url or ""):
            return real(self, method=method, url=url, **kw)
        if raises:
            raise raises
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(payload or {"status": code, "title": "x", "detail": "x"}).encode()
        response.headers["Content-Type"] = "application/hal+json"
        return response

    return fake


class TestUnknownIdOnTheDuesReversalPath(EnhancedTestCase):
    """``_book_dues_reversals`` re-asks Mollie after the router fetched the payment (#1805).

    An unknown id cannot reach it (dues classification needs the router's fetch to succeed), but
    Mollie can 404 between the two calls; it must then answer like STEP 1 does. Called directly
    with a payment that announces a refund: the booking step before it is not under test.
    """

    def _run(self, fake):
        from types import SimpleNamespace
        from unittest.mock import patch

        import requests

        from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
            get_unified_webhook_service,
        )

        self.expectErrorLog("Mollie", "Webhook")
        frappe.local.response.pop("http_status_code", None)
        frappe.local.response.pop("Retry-After", None)
        forward = {"status": "success"}
        refunded = SimpleNamespace(amount_refunded={"value": "5.00", "currency": "EUR"})
        unique_ip = f"10.{frappe.generate_hash(length=3)}"
        with patch.object(requests.Session, "request", fake), patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key",
            return_value="test_" + "a" * 30,
        ), patch(
            "verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings."
            "MollieSettings.get_active_api_key",
            return_value="test_" + "a" * 30,
        ), patch(
            "verenigingen.verenigingen_payments.mollie.services.unknown_payment_ack.get_client_ip",
            return_value=unique_ip,
        ):
            result = get_unified_webhook_service()._book_dues_reversals(
                f"tr_{frappe.generate_hash(length=10)}", refunded, forward
            )
        return result, forward

    def test_a_404_on_the_second_fetch_leaves_the_forward_result_and_asks_for_no_retry(self):
        before = frappe.db.count("Error Log", {"method": "Mollie Webhook Payment Not Found"})
        result, forward = self._run(_mollie_sdk_http_layer_1805(404))
        # Staff are told, as in STEP 1 (without the dues-path branch this was silent).
        self.assertEqual(
            frappe.db.count("Error Log", {"method": "Mollie Webhook Payment Not Found"}) - before, 1
        )
        self.assertIs(result, forward)
        self.assertEqual(result["status"], "success")
        self.assertIsNone(frappe.local.response.get("http_status_code"))
        self.assertNotIn("Retry-After", frappe.local.response)

    def test_control_a_5xx_on_the_second_fetch_still_asks_mollie_to_retry(self):
        result, _forward = self._run(_mollie_sdk_http_layer_1805(500))
        self.assertEqual(result["status"], "service_unavailable")
        self.assertEqual(frappe.local.response.get("http_status_code"), 503)
        self.assertEqual(frappe.local.response.get("Retry-After"), "60")


class TestIsPaymentNotFound(EnhancedTestCase):
    """Only the SDK's 404 type counts, by TYPE and through wrapping; never by message text."""

    def test_the_sdk_404_counts_wrapped_or_not_and_nothing_else_does(self):
        from mollie.api.error import NotFoundError, ResponseError, UnauthorizedError

        from verenigingen.verenigingen_payments.mollie.exceptions import (
            MolliePaymentError,
            is_payment_not_found,
        )

        not_found = NotFoundError({"status": 404, "title": "Not Found", "detail": "x"})
        try:
            raise MolliePaymentError("Cannot fetch payment data", original_error=not_found) from not_found
        except MolliePaymentError as wrapped:
            self.assertTrue(is_payment_not_found(wrapped))
        self.assertTrue(is_payment_not_found(not_found))
        # Controls: a 404 SAID in text, other SDK errors, a timeout, nothing.
        self.assertFalse(is_payment_not_found(MolliePaymentError("404 not found")))
        self.assertFalse(is_payment_not_found(UnauthorizedError({"status": 401, "title": "x", "detail": "x"})))
        self.assertFalse(is_payment_not_found(ResponseError({"status": 500, "title": "x", "detail": "x"})))
        self.assertFalse(is_payment_not_found(TimeoutError("404")))
        self.assertFalse(is_payment_not_found(None))
        # Each link on its own: the matcher must follow BOTH, not just one of them.
        only_cause = MolliePaymentError("wrapped")
        only_cause.__cause__ = not_found
        self.assertTrue(is_payment_not_found(only_cause))
        only_original = MolliePaymentError("wrapped", original_error=not_found)
        self.assertIsNone(only_original.__cause__)
        self.assertTrue(is_payment_not_found(only_original))


class TestCallerBucket(EnhancedTestCase):
    def test_ipv6_callers_share_a_64_and_ipv4_is_unchanged(self):
        from verenigingen.verenigingen_payments.mollie.services.unknown_payment_ack import caller_bucket

        self.assertEqual(caller_bucket("2001:db8:1:2::1"), caller_bucket("2001:db8:1:2:ffff::9"))
        self.assertNotEqual(caller_bucket("2001:db8:1:2::1"), caller_bucket("2001:db8:1:3::1"))
        self.assertEqual(caller_bucket("203.0.113.7"), "203.0.113.7")
        self.assertNotEqual(caller_bucket("203.0.113.7"), caller_bucket("203.0.113.8"))
