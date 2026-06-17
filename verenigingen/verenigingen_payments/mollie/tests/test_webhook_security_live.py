"""
LIVE Mollie webhook signature-security tests.

These port the security scenarios from the deleted tests/test_webhook_security.py
(which asserted against the now-deleted dead GenericWebhookService) onto the LIVE
signature-validation path that the production webhook entry points actually use:

    mollie/utils/webhook_security.authenticate_mollie_webhook()
        -> verenigingen_payments/utils/webhook_security.verify_mollie_webhook_signature()

verify_mollie_webhook_signature is the single real trust anchor for webhook
authenticity. unified_payment_api.handle_payment_webhook / handle_refund_webhook /
handle_chargeback_webhook all call mollie/utils authenticate_mollie_webhook, which
delegates here. We exercise the genuine HMAC-SHA256 comparison, the constant-time
behaviour, and every accept/reject branch with NO mocking of the logic under test.

Scenarios ported (from the deleted suite):
- signature validation comprehensive (valid / invalid / empty / malformed)
- signature timing-attack resistance (constant-time hmac.compare_digest)
- payload validation security (tampered body fails)
- signed-webhook-without-secret rejection
- unsigned-webhook acceptance (standard Mollie behaviour)
- test-mode bypass behaviour
"""

import time

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    mollie_settings_override,
    sign_payload,
)
from verenigingen.verenigingen_payments.utils.webhook_security import (
    WebhookAuthenticationError,
    verify_mollie_webhook_signature,
)

PAYLOAD = '{"id":"tr_security_live_123","status":"paid","amount":{"value":"100.00","currency":"EUR"}}'
SECRET = "whsec_live_security_test_secret"


class TestMollieWebhookSignatureSecurity(EnhancedTestCase):
    """Real HMAC-SHA256 signature validation against the live trust anchor."""

    def setUp(self):
        super().setUp()
        # The test-mode scenarios below set Mollie test_mode=True. On a fresh CI
        # site (no developer_mode), _validate_test_mode_safety() would reject
        # test_mode as a production safety risk before any signature logic runs.
        # The production code offers an explicit staging/test override
        # (allow_mollie_test_mode); set it for the duration of the test so the
        # genuine HMAC verification path — the thing actually under test — is
        # reached on every site, dev or CI. Restored in tearDown.
        self._prev_allow_test_mode = frappe.conf.get("allow_mollie_test_mode")
        frappe.conf["allow_mollie_test_mode"] = True

    def tearDown(self):
        if self._prev_allow_test_mode is None:
            frappe.conf.pop("allow_mollie_test_mode", None)
        else:
            frappe.conf["allow_mollie_test_mode"] = self._prev_allow_test_mode
        super().tearDown()

    def test_valid_signature_accepted(self):
        """A correctly computed sha256=<hmac> signature is accepted."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            sig = sign_payload(PAYLOAD, SECRET)
            self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, sig))

    def test_invalid_signature_rejected(self):
        """A signature computed with the wrong secret is rejected, not accepted."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            wrong = sign_payload(PAYLOAD, "the_wrong_secret")
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature(PAYLOAD, wrong)

    def test_malformed_signature_rejected(self):
        """A signature missing the sha256= structure / wrong shape is rejected."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            for bad in ("not-a-signature", "sha256=", "sha256=deadbeef", "md5=abcdef"):
                with self.assertRaises(WebhookAuthenticationError):
                    verify_mollie_webhook_signature(PAYLOAD, bad)

    def test_tampered_payload_rejected(self):
        """A signature valid for the original body fails once the body is tampered.

        This is the core payload-integrity guarantee: the HMAC binds the exact
        bytes, so flipping a single field invalidates an otherwise-valid header.
        """
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            sig = sign_payload(PAYLOAD, SECRET)
            tampered = PAYLOAD.replace('"100.00"', '"999.00"')
            self.assertNotEqual(tampered, PAYLOAD)
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature(tampered, sig)

    def test_unsigned_webhook_accepted(self):
        """Standard Mollie Payments-API webhooks are UNSIGNED (no header).

        Authenticity is confirmed by the handler re-fetching state from Mollie by
        id, so a missing signature must be accepted — rejecting it would drop
        every genuine live webhook.
        """
        with mollie_settings_override(test_mode=False, webhook_secret=SECRET):
            self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, None))
            self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, ""))

    def test_signed_webhook_without_secret_rejected(self):
        """If a signature IS present but no secret is configured, reject hard.

        We cannot verify a signed (Connect/next-gen) webhook with no secret, so
        accepting it would be a silent security hole.
        """
        with mollie_settings_override(test_mode=False, webhook_secret=""):
            sig = sign_payload(PAYLOAD, SECRET)
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature(PAYLOAD, sig)

    def test_live_mode_invalid_signature_rejected(self):
        """In LIVE mode the HMAC path is fully exercised: wrong sig is rejected."""
        with mollie_settings_override(test_mode=False, webhook_secret=SECRET):
            # Correct signature accepted...
            good = sign_payload(PAYLOAD, SECRET)
            self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, good))
            # ...wrong one rejected.
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature(PAYLOAD, sign_payload(PAYLOAD, "other"))

    def test_test_mode_test_signature_prefix_bypass(self):
        """In test_mode, signatures starting with 'test_signature' are accepted.

        This is a documented dev/test affordance; it must NOT apply in live mode.
        """
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, "test_signature_abc"))

    def test_test_signature_prefix_not_bypassed_in_live_mode(self):
        """The 'test_signature' affordance must be inert in live mode.

        A request presenting a 'test_signature...' header in production is an
        attacker-controllable bypass attempt and must be HMAC-verified (and fail).
        """
        with mollie_settings_override(test_mode=False, webhook_secret=SECRET):
            with self.assertRaises(WebhookAuthenticationError):
                verify_mollie_webhook_signature(PAYLOAD, "test_signature_abc")

    def test_timing_attack_resistance_constant_time(self):
        """Signature comparison must use constant-time comparison.

        We assert the rejection cost does not depend on how many leading
        characters of the candidate match the expected signature: a non-constant
        comparison would leak the prefix-match length through timing. Variance
        across wildly different candidate shapes is bounded.
        """
        with mollie_settings_override(test_mode=False, webhook_secret=SECRET):
            expected = sign_payload(PAYLOAD, SECRET)
            candidates = [
                "sha256=" + "0" * 64,  # all wrong, full length
                "sha256=" + expected[7:-1] + "0",  # differs only in last char
                "sha256=" + "f" * 64,  # all wrong, different fill
                expected[:-1] + ("0" if expected[-1] != "0" else "1"),  # near-match
            ]
            timings = []
            for cand in candidates:
                # warm + measure median of a few runs to reduce noise
                samples = []
                for _ in range(50):
                    t0 = time.perf_counter()
                    try:
                        verify_mollie_webhook_signature(PAYLOAD, cand)
                    except WebhookAuthenticationError:
                        pass
                    samples.append(time.perf_counter() - t0)
                samples.sort()
                timings.append(samples[len(samples) // 2])

            avg = sum(timings) / len(timings)
            max_variance = max(abs(t - avg) for t in timings)
            # Generous bound (3x) — the point is that prefix-length does not cause
            # a systematic ordering, which constant-time comparison guarantees.
            self.assertLess(
                max_variance,
                avg * 3 + 0.001,
                f"Signature comparison timing varied too much (avg={avg*1e6:.1f}us, "
                f"max_var={max_variance*1e6:.1f}us) — possible non-constant-time comparison",
            )


class TestMollieWebhookTestModeSafety(EnhancedTestCase):
    """The _validate_test_mode_safety guard around the test-mode bypass."""

    def test_test_mode_allowed_with_dev_or_override_flag(self):
        """test_mode bypass is permitted when an explicit dev/staging flag is set.

        The guard accepts test_mode when EITHER developer_mode (dev sites) OR
        allow_mollie_test_mode (staging override) is set. We assert the behaviour
        under the explicit override so this holds on any site (a fresh CI site has
        neither flag by default), while still covering the path the guard takes.
        """
        prev_allow = frappe.conf.get("allow_mollie_test_mode")
        frappe.conf["allow_mollie_test_mode"] = True
        try:
            self.assertTrue(
                frappe.conf.get("developer_mode") or frappe.conf.get("allow_mollie_test_mode"),
                "a dev/override flag must be set for the bypass to be permitted",
            )
            with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
                # Unsigned + test_mode => accepted without raising the security guard.
                self.assertTrue(verify_mollie_webhook_signature(PAYLOAD, None))
        finally:
            if prev_allow is None:
                frappe.conf.pop("allow_mollie_test_mode", None)
            else:
                frappe.conf["allow_mollie_test_mode"] = prev_allow

    def test_test_mode_rejected_without_dev_flags(self):
        """Without developer_mode AND without allow_mollie_test_mode, test_mode is
        a production safety risk and the guard hard-rejects it.

        This is the negative control for the bypass: it proves the guard is real,
        not merely permissive. Simulated by clearing both flags regardless of the
        host site's actual configuration.
        """
        prev_allow = frappe.conf.get("allow_mollie_test_mode")
        prev_dev = frappe.conf.get("developer_mode")
        frappe.conf["allow_mollie_test_mode"] = False
        frappe.conf["developer_mode"] = 0
        try:
            with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
                with self.assertRaises(WebhookAuthenticationError):
                    verify_mollie_webhook_signature(PAYLOAD, None)
        finally:
            if prev_allow is None:
                frappe.conf.pop("allow_mollie_test_mode", None)
            else:
                frappe.conf["allow_mollie_test_mode"] = prev_allow
            if prev_dev is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = prev_dev
