"""
Coverage sweep for verenigingen_payments/mollie/api/payment_webhook.py

Targets the two highest-value uncovered clusters:

1. ``_validate_webhook_signature()`` -- the STRICT HMAC-SHA256 webhook signature
   validator. This is security-critical: a test that passes regardless of the
   signature would be worthless, so every assertion below pins a real
   accept/reject decision against a genuine HMAC computed with the configured
   webhook secret (no mocking of the comparison logic).

2. ``process_failed_payment()`` -- failure recording for donations and member
   subscriptions, including the member non-subscription commit path, the
   "no associated record" warning path, and the outer error-handling path.

Only true external boundaries are stubbed (the HTTP request context via the
shared ``install_fake_request`` fixture, and the Mollie Settings secret via
``mollie_settings_override``). The signature logic and the failure-handling
logic themselves run for real.

We deliberately do NOT re-test the member subscription-failure early-return path
(payment.status == "failed" + subscription_id), which is already covered by
test_failed_payment_processing.TestFailedPaymentProcessing.test_real_failed_payment_workflow.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
    _validate_webhook_signature,
    process_failed_payment,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.webhook_fixtures import (
    install_fake_request,
    make_webhook_payload,
    mollie_settings_override,
    sign_payload,
)

SECRET = "whsec_payment_webhook_sweep_secret"


class _FakePayment:
    """Minimal Mollie payment stand-in (the webhook code only reads attributes)."""

    def __init__(self, payment_id, status="failed", amount="25.00", **extra):
        self.id = payment_id
        self.status = status
        self.amount = {"value": amount, "currency": "EUR"}
        self.method = "directdebit"
        self.created_at = "2024-01-15T10:00:00+00:00"
        for k, v in extra.items():
            setattr(self, k, v)


class TestValidateWebhookSignature(EnhancedTestCase):
    """Real HMAC-SHA256 validation of the STRICT _validate_webhook_signature path.

    This validator REQUIRES a signature header (unlike the lenient live path) and
    raises frappe.PermissionError on any failure. We assert the genuine
    accept/reject decision for valid, missing, unconfigured-secret, wrong-secret,
    tampered, and prefix-less-but-valid signatures.
    """

    PAYLOAD = make_webhook_payload("tr_sig_sweep_123", status="paid", amount="100.00")

    def setUp(self):
        super().setUp()
        # On a long-lived local site Mollie Settings may carry stale Account link
        # values (mollie_bank_account / clearing / fees) that no longer resolve,
        # tripping LinkValidationError when mollie_settings_override re-saves the
        # single. These fields are irrelevant to signature validation, so clear
        # them via db.set_value (no link checks). Rolled back per test by
        # EnhancedTestCase; on a fresh CI site they are already empty.
        for fieldname in (
            "mollie_bank_account",
            "mollie_clearing_account",
            "payment_processing_fees_account",
        ):
            frappe.db.set_value("Mollie Settings", "Mollie Settings", fieldname, "", update_modified=False)

    def test_valid_signature_accepted(self):
        """A correctly computed sha256=<hmac> header is accepted (no raise)."""
        sig = sign_payload(self.PAYLOAD, SECRET)
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, sig):
                # Returns None and does not raise.
                self.assertIsNone(_validate_webhook_signature())

    def test_signature_without_sha256_prefix_accepted(self):
        """A bare hex digest (no 'sha256=' prefix) that matches is still accepted.

        Exercises the else-branch that uses the header value verbatim.
        """
        full = sign_payload(self.PAYLOAD, SECRET)
        bare = full[len("sha256=") :]
        self.assertFalse(bare.startswith("sha256="))
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, bare):
                self.assertIsNone(_validate_webhook_signature())

    def test_missing_signature_header_rejected(self):
        """No X-Mollie-Signature header => hard reject (PermissionError)."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, signature=None):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_no_secret_configured_rejected(self):
        """Signature present but NO webhook secret configured => hard reject.

        Accepting a signed webhook we cannot verify would be a silent hole.
        """
        sig = sign_payload(self.PAYLOAD, SECRET)
        with mollie_settings_override(test_mode=True, webhook_secret=""):
            with install_fake_request(self.PAYLOAD, sig):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_wrong_secret_signature_rejected(self):
        """A signature computed with the wrong secret is rejected, not accepted."""
        wrong = sign_payload(self.PAYLOAD, "a_totally_different_secret")
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, wrong):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_tampered_body_rejected(self):
        """A signature valid for the original body fails once the body is tampered.

        The HMAC binds the exact bytes: flipping a single field invalidates an
        otherwise-valid header. This is the core integrity guarantee.
        """
        sig = sign_payload(self.PAYLOAD, SECRET)
        tampered = self.PAYLOAD.replace('"100.00"', '"999.00"')
        self.assertNotEqual(tampered, self.PAYLOAD)
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(tampered, sig):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_garbage_signature_rejected(self):
        """A non-hex / structurally wrong signature value is rejected."""
        with mollie_settings_override(test_mode=True, webhook_secret=SECRET):
            with install_fake_request(self.PAYLOAD, "sha256=not-a-real-digest"):
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()


class TestProcessFailedPayment(EnhancedTestCase):
    """Failure-recording side effects of process_failed_payment()."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="FailSweep",
            last_name="Member",
            email="failsweep.member@example.com",
            payment_method="Mollie",
        )
        self.member.mollie_customer_id = "cst_fail_sweep_001"
        self.member.mollie_subscription_id = "sub_fail_sweep_001"
        self.member.save()

    def _make_draft_donation(self, payment_id, amount=25.0):
        """Insert a NON-submitted Donation carrying the given Mollie payment_id.

        A draft is required because process_failed_payment appends to the
        Donation 'payments' child table and saves; that table is not
        allow_on_submit, so the side effect is only observable on a draft doc.
        """
        donor = self.create_test_donor(donor_name="Fail Sweep Donor")
        company = frappe.get_list("Company", limit=1)[0].name
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "company": company,
                "donor": donor.name,
                "amount": amount,
                "donation_date": frappe.utils.today(),
                "currency": "EUR",
                "paid": 0,
                "mode_of_payment": "Bank Transfer",
                "payment_id": payment_id,
            }
        )
        donation.insert()
        self.factory.track_document("Donation", donation.name, priority=4)
        return donation

    def test_failed_payment_recorded_on_donation(self):
        """A failed payment matched to a donation appends a Cancelled history row."""
        payment_id = "tr_fail_donation_001"
        donation = self._make_draft_donation(payment_id, amount=42.0)
        # No customer_id/subscription_id => no member match, isolate the donation path.
        payment = _FakePayment(payment_id, status="failed", amount="42.00")

        result = process_failed_payment(payment_id, payment)

        self.assertEqual(result["payment_id"], payment_id)
        self.assertEqual(result["status"], "failed")
        donation_records = [r for r in result["processed_records"] if r["type"] == "donation"]
        self.assertEqual(len(donation_records), 1)
        self.assertEqual(donation_records[0]["id"], donation.name)
        self.assertEqual(donation_records[0]["status"], "failed_payment_recorded")

        # Verify the real side effect persisted on the donation child table.
        donation.reload()
        cancelled = [
            p
            for p in (donation.payments or [])
            if p.get("mollie_payment_id") == payment_id and p.get("payment_status") == "Cancelled"
        ]
        self.assertEqual(len(cancelled), 1, "Expected exactly one Cancelled payment history row")

    def test_failed_payment_recorded_on_member_non_subscription(self):
        """A non-subscription failure matched only to a member commits via the
        second save path (not the subscription early-return) and records history."""
        payment_id = "tr_fail_member_nonsub_001"
        # customer_id matches the member; NO subscription_id attribute at all so the
        # subscription branch is skipped and the trailing member.save()+commit runs.
        payment = _FakePayment(
            payment_id,
            status="expired",
            amount="25.00",
            customer_id=self.member.mollie_customer_id,
        )
        self.assertFalse(hasattr(payment, "subscription_id"))

        result = process_failed_payment(payment_id, payment)

        member_records = [r for r in result["processed_records"] if r["type"] == "member"]
        self.assertEqual(len(member_records), 1)
        self.assertEqual(member_records[0]["id"], self.member.name)
        self.assertEqual(member_records[0]["status"], "failed_payment_recorded")

        # Real side effect: a Cancelled subscription-payment history row exists.
        self.member.reload()
        cancelled = [
            h
            for h in (self.member.payment_history or [])
            if h.get("payment_status") == "Cancelled" and payment_id in (h.get("notes") or "")
        ]
        self.assertEqual(len(cancelled), 1)

    def test_no_associated_record_warning(self):
        """A failed payment matching neither donation nor member yields a warning."""
        payment_id = "tr_fail_orphan_001"
        payment = _FakePayment(payment_id, status="failed", amount="10.00")

        result = process_failed_payment(payment_id, payment)

        self.assertEqual(result["processed_records"], [])
        self.assertEqual(result["warning"], "No associated record found")
        self.assertEqual(result["status"], "failed")

    def test_processing_error_path_returns_acknowledgement(self):
        """An unexpected error is caught and acknowledged (so Mollie won't retry).

        We trigger it by passing a payment object missing the .status attribute,
        which raises inside results-dict construction. The handler must return a
        processing_error envelope rather than propagate.
        """

        class StatuslessPayment:
            def __init__(self, payment_id):
                self.id = payment_id
                self.amount = {"value": "25.00", "currency": "EUR"}

        payment_id = "tr_fail_error_001"
        # The handler logs the failure to Error Log by design; mark it expected.
        self.expectErrorLog("Failed Payment Processing")

        result = process_failed_payment(payment_id, StatuslessPayment(payment_id))

        self.assertEqual(result["payment_id"], payment_id)
        self.assertEqual(result["status"], "processing_error")
        self.assertIn("error", result)
        self.assertIn("manual review", result["message"])
