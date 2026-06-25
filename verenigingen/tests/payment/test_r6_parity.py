"""
Task R6 parity regression tests.

Verifies that refactored response-builders, HMAC helpers, and sliding-window
counters produce IDENTICAL output to the original code they replaced.

Seven parity sites (per the R6 brief):
  1. webhook_error_handler.handle_validation_error
  2. webhook_error_handler.handle_business_logic_error
  3. webhook_error_handler.handle_system_error
  4. webhook_error_handler.handle_external_api_error
  5. webhook_error_handler.create_success_response (flat-merge)
  6. refund_utility._create_error_response
  7. refund_utility._create_success_response

Plus:
  8. HMAC byte-equality (webhook_security compute_hmac_signature)
  9. SlidingWindowCounter decision-parity vs original deque loop
"""

import hashlib
import hmac
import time

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.shared.responses import (
    ResponseBuilder,
    compute_hmac_signature,
)
from verenigingen.verenigingen_payments.utils.shared.sliding_window import SlidingWindowCounter
from verenigingen.verenigingen_payments.utils.webhook_error_handler import WebhookErrorHandler


# -----------------------------------------------------------------------
# Helper: original response builders (inline, as they were before R6)
# -----------------------------------------------------------------------


def _orig_validation_error(handler, error_message, details=None):
    """Reproduce the ORIGINAL handle_validation_error dict."""
    from frappe.utils import now

    return {
        "status": "validation_error",
        "message": error_message,
        "correlation_id": handler.correlation_id,
        "timestamp": now(),
        "details": details or {},
    }


def _orig_business_error(handler, error_message, details=None):
    """Reproduce the ORIGINAL handle_business_logic_error dict."""
    from frappe.utils import now

    return {
        "status": "business_error",
        "message": error_message,
        "correlation_id": handler.correlation_id,
        "timestamp": now(),
        "details": details or {},
    }


def _orig_system_error(handler, error_message):
    """Reproduce the ORIGINAL handle_system_error dict (developer_mode=0 path)."""
    from frappe.utils import now

    return {
        "status": "system_error",
        "message": "Internal processing error occurred",
        "correlation_id": handler.correlation_id,
        "timestamp": now(),
        "internal_message": None,  # non-dev mode
    }


def _orig_external_api_error(handler, api_name, error_message):
    """Reproduce the ORIGINAL handle_external_api_error dict."""
    from frappe.utils import now

    return {
        "status": "external_api_error",
        "message": f"External service ({api_name}) error occurred",
        "correlation_id": handler.correlation_id,
        "timestamp": now(),
        "api_name": api_name,
    }


def _orig_success_response(handler, message, data=None):
    """Reproduce the ORIGINAL create_success_response dict (flat-merge style)."""
    from frappe.utils import now

    resp = {
        "status": "success",
        "message": message,
        "correlation_id": handler.correlation_id,
        "timestamp": now(),
    }
    if data:
        resp.update(data)
    return resp


def _orig_error_response(message, error_code=None, details=None):
    """Reproduce the ORIGINAL refund_utility._create_error_response dict."""
    from frappe.utils import now_datetime

    return {
        "status": "error",
        "message": message,
        "error_code": error_code,
        "details": details,
        "timestamp": now_datetime().isoformat(),
    }


def _orig_success_response_ru(message, data=None):
    """Reproduce the ORIGINAL refund_utility._create_success_response dict."""
    from frappe.utils import now_datetime

    return {
        "status": "success",
        "message": message,
        "data": data,
        "timestamp": now_datetime().isoformat(),
    }


class TestR6ResponseParity(VereningingenTestCase):
    """Parity: refactored dicts have IDENTICAL keys/structure (excluding timestamp) to originals."""

    def _keys_match(self, new_resp, orig_resp):
        """Assert same top-level keys in both dicts."""
        self.assertEqual(set(new_resp.keys()), set(orig_resp.keys()), "Key sets differ")

    def _values_match_except_timestamp(self, new_resp, orig_resp):
        """Assert same values for all keys except timestamp (which changes per-call)."""
        for k in orig_resp:
            if k == "timestamp":
                continue
            self.assertEqual(new_resp[k], orig_resp[k], f"Value mismatch for key '{k}'")

    # -- Site 1: handle_validation_error ----------------------------------
    def test_parity_validation_error(self):
        handler = WebhookErrorHandler(webhook_type="test", correlation_id="parity01")
        details = {"field": "amount"}

        new_resp = handler.handle_validation_error("bad amount", details)
        orig_resp = _orig_validation_error(handler, "bad amount", details)

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)
        self.assertIn("timestamp", new_resp)

    # -- Site 2: handle_business_logic_error ------------------------------
    def test_parity_business_error(self):
        handler = WebhookErrorHandler(correlation_id="parity02")
        new_resp = handler.handle_business_logic_error("permission denied")
        orig_resp = _orig_business_error(handler, "permission denied")

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)

    # -- Site 3: handle_system_error (non-dev mode) -----------------------
    def test_parity_system_error(self):
        import frappe

        handler = WebhookErrorHandler(correlation_id="parity03")
        orig_dev = frappe.conf.get("developer_mode")
        try:
            frappe.conf["developer_mode"] = 0
            new_resp = handler.handle_system_error("db crashed")
            orig_resp = _orig_system_error(handler, "db crashed")
        finally:
            if orig_dev is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = orig_dev

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)

    # -- Site 4: handle_external_api_error --------------------------------
    def test_parity_external_api_error(self):
        handler = WebhookErrorHandler(correlation_id="parity04")
        new_resp = handler.handle_external_api_error("Mollie", "timeout")
        orig_resp = _orig_external_api_error(handler, "Mollie", "timeout")

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)

    # -- Site 5: create_success_response (flat-merge) --------------------
    def test_parity_success_response_flat_merge(self):
        handler = WebhookErrorHandler(correlation_id="parity05")
        data = {"payment_entry": "PE-001", "refund_id": "re_abc"}
        new_resp = handler.create_success_response("done", data)
        orig_resp = _orig_success_response(handler, "done", data)

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)
        # Verify flat merge: data keys appear at top level, NOT nested
        self.assertNotIn("data", new_resp)
        self.assertEqual(new_resp["payment_entry"], "PE-001")

    # -- Site 6: refund_utility._create_error_response -------------------
    def test_parity_refund_error_response(self):
        from verenigingen.verenigingen_payments.utils.payment_services.refund_utility import (
            _create_error_response,
        )

        new_resp = _create_error_response("not found", error_code="NOT_FOUND", details={"x": 1})
        orig_resp = _orig_error_response("not found", error_code="NOT_FOUND", details={"x": 1})

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)
        self.assertIn("timestamp", new_resp)

    # -- Site 7: refund_utility._create_success_response -----------------
    def test_parity_refund_success_response(self):
        from verenigingen.verenigingen_payments.utils.payment_services.refund_utility import (
            _create_success_response,
        )

        data = {"refund_id": "re_123", "amount": 50.0}
        new_resp = _create_success_response("ok", data)
        orig_resp = _orig_success_response_ru("ok", data)

        self._keys_match(new_resp, orig_resp)
        self._values_match_except_timestamp(new_resp, orig_resp)
        # success response nests data under "data" key (not flat)
        self.assertEqual(new_resp["data"], data)


class TestR6HMACParity(VereningingenTestCase):
    """Parity: compute_hmac_signature produces byte-identical output to the original hmac.new(...).hexdigest()."""

    def test_hmac_byte_equal_to_original_pattern(self):
        secret = "whsec_test_key_12345"
        payload = '{"id": "tr_abc123", "status": "paid"}'

        # Original pattern (webhook_security.py before R6)
        original = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

        # New shared helper
        new = compute_hmac_signature(secret, payload)

        self.assertEqual(new, original, "HMAC hex digests must be byte-identical")
        self.assertEqual(len(new), 64)  # sha256 hex = 64 chars

    def test_hmac_parity_with_real_webhook_security_path(self):
        """Verify the full signature verification path in webhook_security.py still works correctly."""
        from types import SimpleNamespace
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.utils.webhook_security import (
            verify_mollie_webhook_signature,
        )

        secret = "whsec_integration_parity"
        payload = '{"id": "tr_parity_test"}'

        # Compute signature using compute_hmac_signature (the new path in webhook_security.py)
        digest = compute_hmac_signature(secret, payload)
        header = f"sha256={digest}"

        settings = SimpleNamespace(
            test_mode=False,
            get_webhook_secret=lambda: secret,
        )

        with patch("frappe.get_single", return_value=settings):
            result = verify_mollie_webhook_signature(payload, header)

        self.assertTrue(result, "Signature computed via compute_hmac_signature must verify correctly")

    def test_ing_generate_signature_parity(self):
        """Verify ING generate_signature now uses compute_hmac_signature and produces the same hex digest."""
        import json

        from verenigingen.verenigingen_payments.utils.webhook.testing import INGCheckoutWebhookTestHelper

        helper = INGCheckoutWebhookTestHelper()
        payload = {"order_id": "EX-test123", "status": "PAID", "amount": 2500}
        secret = "ing_webhook_secret_abc"

        payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True)

        # Original pattern
        original = hmac.new(secret.encode("utf-8"), payload_str.encode("utf-8"), hashlib.sha256).hexdigest()

        # New via helper (which now calls compute_hmac_signature internally)
        new = helper.generate_signature(payload, secret)

        self.assertEqual(new, original, "ING generate_signature must be byte-identical to original")


class TestR6SlidingWindowDecisionParity(VereningingenTestCase):
    """
    Decision-parity: SlidingWindowCounter allow/deny decisions match original deque loop.

    Scripted sequence: 5 timestamps fed to both the original deque-based counter
    and the new SlidingWindowCounter. The allow/deny decision at each step must be
    identical.

    The original logic in _check_global_limit:
        while self.global_requests and current_time - self.global_requests[0] > self.time_window:
            self.global_requests.popleft()
        return len(self.global_requests) < self.global_limit

    Note: boundary semantics are `>` (strictly greater than), meaning an entry whose
    age equals the window is KEPT. SlidingWindowCounter.prune uses the same `>`.
    """

    def _original_check(self, deque_obj, current_time, window, limit):
        """Replicate the original _check_global_limit logic using a deque."""
        from collections import deque

        # prune
        while deque_obj and current_time - deque_obj[0] > window:
            deque_obj.popleft()
        return len(deque_obj) < limit

    def test_decision_parity_sequence(self):
        """Feed a scripted sequence and compare allow/deny between old and new."""
        from collections import deque

        window = 60  # seconds
        limit = 3
        t0 = 1_000_000.0  # arbitrary base timestamp

        # Timestamps: t0, t0+10, t0+20, t0+30, t0+65 (t0 has expired), t0+70
        timestamps = [
            t0,
            t0 + 10,
            t0 + 20,
            t0 + 30,
            t0 + 65,  # t0 should be pruned now (age=65>60)
            t0 + 70,  # t0+10 should be pruned (age=60, NOT pruned! boundary)
        ]

        orig_deque = deque()
        new_counter = SlidingWindowCounter(window)

        for ts in timestamps:
            # Original: record then check
            orig_deque.append(ts)
            orig_allowed = self._original_check(orig_deque, ts, window, limit)

            # New: add then count
            new_counter.add(ts)
            new_count = new_counter.count(ts)
            new_allowed = new_count < limit

            self.assertEqual(
                new_allowed,
                orig_allowed,
                f"Decision mismatch at ts={ts}: orig={orig_allowed}, new={new_allowed} "
                f"(orig_deque_size={len(orig_deque)}, new_count={new_count})",
            )

    def test_boundary_exactly_at_window_kept(self):
        """An entry exactly at the window boundary must be KEPT (strict > not >=)."""
        window = 60.0
        t0 = 500_000.0
        counter = SlidingWindowCounter(window)
        counter.add(t0)

        # Exactly at boundary: now - t0 == 60 (not > 60) -> kept
        now = t0 + window
        self.assertEqual(counter.count(now), 1, "Entry at exact boundary must be kept")

    def test_one_second_past_boundary_pruned(self):
        """An entry one second past the boundary is pruned."""
        window = 60.0
        t0 = 500_000.0
        counter = SlidingWindowCounter(window)
        counter.add(t0)

        # One second past: now - t0 == 61 (> 60) -> pruned
        now = t0 + window + 1
        self.assertEqual(counter.count(now), 0, "Entry one second past boundary must be pruned")

    def test_rate_limiter_allow_deny_scripted_sequence(self):
        """
        End-to-end decision-parity: run the same scripted sequence through
        the refactored WebhookRateLimiter and verify all expected decisions.
        """
        from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import WebhookRateLimiter

        limiter = WebhookRateLimiter()
        limiter.ip_limit = 3
        limiter.webhook_id_limit = 100
        limiter.global_limit = 100

        # Force a fixed "base" time by injecting timestamps directly
        # (we call check_rate_limit which uses time.time(), so we just
        # rely on the live behavior: 3 allowed, 4th denied)
        ip = "192.0.2.1"
        results = []
        for _ in range(4):
            allowed, _ = limiter.check_rate_limit(ip)
            results.append(allowed)

        # decisions: [True, True, True, False]
        self.assertEqual(results, [True, True, True, False])
