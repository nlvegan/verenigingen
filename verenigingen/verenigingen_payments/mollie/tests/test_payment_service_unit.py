"""
Integration tests (Tier-2) for the credential-free, client-driven logic in
PaymentService (verenigingen/verenigingen_payments/mollie/services/payment_service.py).

LIVE: PaymentService is instantiated in api/sync.py (get_payment_status,
process_payment_completion). Those two methods, plus the metadata/webhook
helpers, are exercised here.

Credential-free pattern (matches test_dues_payment_processor_integration.py):
    PaymentService.__init__ builds a real MollieClient (needs Mollie Settings
    keys) and emits a DeprecationWarning. The methods under test only touch
    self.client (the SDK boundary) and frappe — never the real HTTP client. So
    we bypass __init__ via object.__new__() and attach a SimpleNamespace fake
    client whose get_payment() returns a SimpleNamespace payment. No mocking of
    the logic under test; only the Mollie SDK boundary is stubbed.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError
from verenigingen.verenigingen_payments.mollie.services.payment_service import PaymentService


def _payment(**kwargs):
    """Build a Mollie SDK-shaped payment stub (amount as the v3+ dict)."""
    defaults = dict(
        id="tr_ps_test",
        status="paid",
        amount={"value": "25.00", "currency": "EUR"},
        description="Test payment",
        paid_at="2025-01-01T00:00:00+00:00",
        created_at="2025-01-01T00:00:00+00:00",
        method="ideal",
        metadata={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _service(payment=None, *, raise_on_get=None):
    """PaymentService without __init__; self.client is a SimpleNamespace fake.

    get_payment(payment_id) returns the supplied payment stub (or raises the
    supplied exception). No real MollieClient is constructed.
    """
    svc = object.__new__(PaymentService)

    def get_payment(payment_id):
        if raise_on_get is not None:
            raise raise_on_get
        return payment

    svc.client = SimpleNamespace(get_payment=get_payment)
    return svc


class TestGetPaymentStatus(EnhancedTestCase):
    """PaymentService.get_payment_status — status flag derivation from SDK payment."""

    def test_paid_payment_flags(self):
        svc = _service(_payment(id="tr_paid", status="paid"))
        result = svc.get_payment_status("tr_paid")

        self.assertEqual(result["id"], "tr_paid")
        self.assertEqual(result["status"], "paid")
        self.assertTrue(result["is_paid"])
        self.assertFalse(result["is_pending"])
        self.assertFalse(result["is_failed"])
        self.assertEqual(result["amount"], 25.0)
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["method"], "ideal")

    def test_open_payment_is_pending(self):
        svc = _service(_payment(status="open"))
        result = svc.get_payment_status("tr_open")
        self.assertFalse(result["is_paid"])
        self.assertTrue(result["is_pending"])
        self.assertFalse(result["is_failed"])

    def test_canceled_payment_is_failed(self):
        svc = _service(_payment(status="canceled"))
        result = svc.get_payment_status("tr_cancel")
        self.assertFalse(result["is_paid"])
        self.assertFalse(result["is_pending"])
        self.assertTrue(result["is_failed"])


class TestProcessPaymentCompletion(EnhancedTestCase):
    """PaymentService.process_payment_completion — type dispatch + guards."""

    def test_unpaid_payment_raises(self):
        svc = _service(_payment(status="open"))
        with self.assertRaises(MollieIntegrationError):
            svc.process_payment_completion("tr_open")

    def test_donation_payment_dispatch(self):
        svc = _service(_payment(metadata={"payment_type": "donation", "donor_id": "DONOR-001"}))
        result = svc.process_payment_completion("tr_don")
        self.assertEqual(result["type"], "donation")
        self.assertEqual(result["donor_id"], "DONOR-001")
        self.assertTrue(result["processed"])
        self.assertEqual(result["amount"], 25.0)

    def test_donation_without_donor_id_raises(self):
        svc = _service(_payment(metadata={"payment_type": "donation"}))
        with self.assertRaises(MollieIntegrationError):
            svc.process_payment_completion("tr_don_nodonor")

    def test_membership_payment_dispatch(self):
        svc = _service(_payment(metadata={"payment_type": "membership_dues", "member_id": "MEM-001"}))
        result = svc.process_payment_completion("tr_mem")
        self.assertEqual(result["type"], "membership_dues")
        self.assertEqual(result["member_id"], "MEM-001")
        self.assertTrue(result["processed"])

    def test_membership_without_member_id_raises(self):
        svc = _service(_payment(metadata={"payment_type": "membership_dues"}))
        with self.assertRaises(MollieIntegrationError):
            svc.process_payment_completion("tr_mem_nomember")

    def test_unknown_type_returns_unprocessed(self):
        # Unknown payment_type: logs an error but does NOT raise; the base
        # result {processed: False} is returned unchanged.
        svc = _service(_payment(metadata={"payment_type": "something_else"}))
        result = svc.process_payment_completion("tr_unknown")
        self.assertEqual(result["payment_id"], "tr_unknown")
        self.assertFalse(result["processed"])
        self.assertNotIn("type", result)


class TestBuildPaymentMetadata(EnhancedTestCase):
    """PaymentService._build_payment_metadata — webhook description JSON builder."""

    def _make_donation(self, amount=30.0):
        member = self.create_test_member(
            first_name="PS",
            last_name=f"Meta{frappe.generate_hash()[:8]}",
            email=f"ps.meta.{frappe.generate_hash()[:6]}@example.com",
        )
        return self.create_test_donation(donor_email=member.email, amount=amount)

    def test_single_metadata_shape(self):
        svc = object.__new__(PaymentService)
        donation = self._make_donation(amount=42.0)

        metadata = svc._build_payment_metadata(donation, {}, is_recurring=False)

        self.assertEqual(metadata["type"], "single")
        self.assertEqual(metadata["record_id"], donation.name)
        self.assertEqual(metadata["amount"], 42.0)
        self.assertEqual(metadata["customer_id"], donation.donor)
        # Single payments carry no interval key.
        self.assertNotIn("interval", metadata)

    def test_recurring_metadata_abbreviates_month(self):
        svc = object.__new__(PaymentService)
        donation = self._make_donation()

        metadata = svc._build_payment_metadata(
            donation, {"subscription_interval": "1 month"}, is_recurring=True
        )

        self.assertEqual(metadata["type"], "recurring")
        # "month" abbreviated to "m"; "day" is deliberately left intact.
        self.assertEqual(metadata["interval"], "1 m")

    def test_recurring_keeps_day_interval(self):
        svc = object.__new__(PaymentService)
        donation = self._make_donation()

        metadata = svc._build_payment_metadata(
            donation, {"subscription_interval": "1 day"}, is_recurring=True
        )
        # Mollie requires the literal "1 day" — must not abbreviate to "1 d".
        self.assertEqual(metadata["interval"], "1 day")


class TestWebhookUrl(EnhancedTestCase):
    """PaymentService._get_webhook_url — points at the unified webhook endpoint."""

    def test_webhook_url_targets_unified_endpoint(self):
        svc = object.__new__(PaymentService)
        url = svc._get_webhook_url()
        self.assertIn(
            "verenigingen.verenigingen_payments.mollie.api.webhooks.handle_mollie_payment_webhook",
            url,
        )
        self.assertTrue(url.startswith("http"))
