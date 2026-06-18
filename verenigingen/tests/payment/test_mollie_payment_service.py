"""
Tests for the (deprecated-but-live) Mollie PaymentService.

Covers ``verenigingen_payments/mollie/services/payment_service.py``. This service
is documented as deprecated for webhook processing, but several methods remain
in use for direct payment / customer operations. We exercise the pure and
client-delegating surface:
- _build_payment_metadata (single vs recurring, interval abbreviation)
- get_payment_status (maps a Mollie payment object to a status dict)
- process_payment_completion (routes by payment_type, raises on non-paid)
- _process_donation_payment / _process_membership_payment (metadata guards)
- _get_webhook_url, _is_test_mode
- _create_or_get_mollie_customer: existing-customer fast path + create path
  (real Donor row, fake SDK client)

Instances are built via object.__new__ to bypass the deprecated __init__ (which
constructs a real MollieClient and warns). The Mollie client/gateway are test
doubles, so no live Mollie call is ever made.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_payment_service
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError
from verenigingen.verenigingen_payments.mollie.services.payment_service import PaymentService


def _bare_service(client=None, gateway=None):
    svc = object.__new__(PaymentService)
    svc.client = client or SimpleNamespace()
    svc.gateway = gateway
    svc.validator = None
    return svc


def _mollie_payment(**kwargs):
    kwargs.setdefault("id", "tr_TEST")
    kwargs.setdefault("status", "paid")
    kwargs.setdefault("amount", {"value": "30.00", "currency": "EUR"})
    kwargs.setdefault("paid_at", "2025-04-01T10:00:00+00:00")
    kwargs.setdefault("created_at", "2025-03-30T10:00:00+00:00")
    kwargs.setdefault("method", "ideal")
    kwargs.setdefault("description", "Test payment")
    kwargs.setdefault("metadata", {})
    return SimpleNamespace(**kwargs)


class TestBuildPaymentMetadata(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.svc = _bare_service()
        self.donor = self.create_test_donor(
            donor_name="Meta Donor",
            donor_email=f"meta.{frappe.generate_hash(length=6)}@example.com",
        )
        self.donation = self.create_test_donation(donor=self.donor.name, amount=40.0)

    def test_single_metadata(self):
        donation_doc = frappe.get_doc("Donation", self.donation.name)
        meta = self.svc._build_payment_metadata(donation_doc, {}, is_recurring=False)
        self.assertEqual(meta["type"], "single")
        self.assertEqual(meta["record_id"], self.donation.name)
        self.assertEqual(meta["customer_id"], self.donor.name)
        self.assertEqual(meta["amount"], donation_doc.amount)
        self.assertNotIn("interval", meta)

    def test_recurring_metadata_abbreviates_month(self):
        donation_doc = frappe.get_doc("Donation", self.donation.name)
        meta = self.svc._build_payment_metadata(
            donation_doc, {"subscription_interval": "1 month"}, is_recurring=True
        )
        self.assertEqual(meta["type"], "recurring")
        self.assertEqual(meta["interval"], "1 m")

    def test_recurring_metadata_keeps_day(self):
        donation_doc = frappe.get_doc("Donation", self.donation.name)
        meta = self.svc._build_payment_metadata(
            donation_doc, {"subscription_interval": "1 day"}, is_recurring=True
        )
        # 'day' must NOT be abbreviated (Mollie requires '1 day')
        self.assertEqual(meta["interval"], "1 day")


class TestGetPaymentStatus(EnhancedTestCase):
    def test_maps_paid_payment(self):
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: _mollie_payment(status="paid")))
        status = svc.get_payment_status("tr_X")
        self.assertEqual(status["id"], "tr_TEST")
        self.assertEqual(status["status"], "paid")
        self.assertTrue(status["is_paid"])
        self.assertFalse(status["is_pending"])
        self.assertFalse(status["is_failed"])
        self.assertEqual(status["amount"], 30.0)
        self.assertEqual(status["currency"], "EUR")

    def test_maps_pending_payment(self):
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: _mollie_payment(status="open")))
        status = svc.get_payment_status("tr_X")
        self.assertTrue(status["is_pending"])
        self.assertFalse(status["is_paid"])

    def test_maps_failed_payment(self):
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: _mollie_payment(status="expired")))
        status = svc.get_payment_status("tr_X")
        self.assertTrue(status["is_failed"])


class TestProcessPaymentCompletion(EnhancedTestCase):
    def test_raises_when_not_paid(self):
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: _mollie_payment(status="open")))
        with self.assertRaises(MollieIntegrationError):
            svc.process_payment_completion("tr_X")

    def test_routes_donation(self):
        payment = _mollie_payment(status="paid", metadata={"payment_type": "donation", "donor_id": "D-1"})
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: payment))
        result = svc.process_payment_completion("tr_X")
        self.assertEqual(result["type"], "donation")
        self.assertEqual(result["donor_id"], "D-1")
        self.assertTrue(result["processed"])

    def test_routes_membership(self):
        payment = _mollie_payment(
            status="paid", metadata={"payment_type": "membership_dues", "member_id": "M-1"}
        )
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: payment))
        result = svc.process_payment_completion("tr_X")
        self.assertEqual(result["type"], "membership_dues")
        self.assertEqual(result["member_id"], "M-1")

    def test_unknown_type_not_processed(self):
        payment = _mollie_payment(status="paid", metadata={"payment_type": "other"})
        svc = _bare_service(client=SimpleNamespace(get_payment=lambda pid: payment))
        result = svc.process_payment_completion("tr_X")
        # No type-specific update; 'processed' stays False
        self.assertFalse(result["processed"])

    def test_process_donation_payment_requires_donor_id(self):
        svc = _bare_service()
        with self.assertRaises(MollieIntegrationError):
            svc._process_donation_payment(_mollie_payment(metadata={}))

    def test_process_membership_payment_requires_member_id(self):
        svc = _bare_service()
        with self.assertRaises(MollieIntegrationError):
            svc._process_membership_payment(_mollie_payment(metadata={}))


class TestWebhookUrlAndTestMode(EnhancedTestCase):
    def test_webhook_url_uses_unified_endpoint(self):
        svc = _bare_service()
        url = svc._get_webhook_url()
        self.assertIn("/api/method/", url)
        self.assertIn("handle_mollie_payment_webhook", url)

    def test_is_test_mode_from_client(self):
        svc = _bare_service(client=SimpleNamespace(test_mode=True))
        self.assertTrue(svc._is_test_mode())

    def test_is_test_mode_defaults_true_on_error(self):
        # client has no test_mode and no gateway -> safe default True
        class _NoTestMode:
            @property
            def test_mode(self):
                raise RuntimeError("nope")

        svc = _bare_service(client=_NoTestMode(), gateway=None)
        self.assertTrue(svc._is_test_mode())


class TestCreateOrGetMollieCustomer(EnhancedTestCase):
    def test_existing_customer_id_short_circuits(self):
        donor = self.create_test_donor(
            donor_name="Existing Cust Donor",
            donor_email=f"existing.{frappe.generate_hash(length=6)}@example.com",
        )
        frappe.db.set_value("Donor", donor.name, "mollie_customer_id", "cst_existing", update_modified=False)
        frappe.db.commit()

        svc = _bare_service()
        donation_doc = SimpleNamespace(donor=donor.name)
        result = svc._create_or_get_mollie_customer(donation_doc, {})
        self.assertEqual(result["status"], "existing")
        self.assertEqual(result["customer_id"], "cst_existing")

    def test_creates_customer_via_gateway_client(self):
        donor = self.create_test_donor(
            donor_name="New Cust Donor",
            donor_email=f"newcust.{frappe.generate_hash(length=6)}@example.com",
        )
        frappe.db.commit()

        created = SimpleNamespace(id="cst_new_created")
        fake_customers = SimpleNamespace(create=lambda data: created)
        gateway = SimpleNamespace(client=SimpleNamespace(customers=fake_customers))
        svc = _bare_service(gateway=gateway)

        donation_doc = SimpleNamespace(donor=donor.name)
        result = svc._create_or_get_mollie_customer(donation_doc, {})
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["customer_id"], "cst_new_created")
        # Persisted on the donor
        self.assertEqual(
            frappe.db.get_value("Donor", donor.name, "mollie_customer_id"), "cst_new_created"
        )

    def test_customer_create_api_failure_returns_error(self):
        donor = self.create_test_donor(
            donor_name="Fail Cust Donor",
            donor_email=f"failcust.{frappe.generate_hash(length=6)}@example.com",
        )
        frappe.db.commit()

        def _boom(data):
            raise RuntimeError("mollie down")

        gateway = SimpleNamespace(client=SimpleNamespace(customers=SimpleNamespace(create=_boom)))
        svc = _bare_service(gateway=gateway)
        donation_doc = SimpleNamespace(donor=donor.name)
        result = svc._create_or_get_mollie_customer(donation_doc, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("failed", result["message"].lower())
