"""
Second coverage sweep for payment_gateways.py.

Targets the branches the existing six suites
(test_payment_gateways.py / _unit.py / _endpoints.py / _coverage.py /
_sepa_ponto_coverage.py / _subscription_sweep.py) do NOT already drive:

    - MollieGateway.handle_webhook: no-payment-id ignored, no-metadata ignored,
      paid (marks the real Donation paid + fires on_payment_authorized),
      failed/cancelled, pending, and the exception path.
    - MollieGateway.process_payment: recurring-payment sequenceType branch,
      billingAddress-from-email branch, and the no-checkout-url error path.
    - MollieGateway subscription error/edge branches: get_subscription_status
      exception, cancel_subscription success + exception, create_subscription
      member-without-IBAN (consumerAccount None) + exception.
    - Trivial gateway methods with no live API: SEPAGateway.handle_webhook /
      get_payment_status, CashGateway.get_payment_status.
    - SEPAGateway.process_payment mandate-creation failure (donor lookup raises ->
      _create_sepa_mandate returns None -> "Failed to create SEPA mandate").
    - _activate_direct_subscription_after_first_payment: quarterly start-date calc
      + donation persistence, and the exception path.
    - _activate_donation_subscription_after_first_payment: missing-customer-id and
      exception paths.
    - Whitelisted endpoints' success/gateway-routing paths: get_payment_status
      (routes to gateway), manual_payment_confirmation, create_member_subscription
      success, get_member_subscription_status success,
      update_mollie_subscription_amount success (incl. linked-donation amount
      update), manual_subscription_retry, mollie_webhook delegation.
    - _find_member_for_subscription (customer found, no member) and
      _update_subscription_status (canceled-date + error branches).

Only the external Mollie SDK / settings boundary is stubbed (each stub is
annotated). All gateway + helper + endpoint business logic runs for real against
real Member / Donation / Donor / Customer / Sales Invoice documents.
"""

import types
import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


# ---------------------------------------------------------------------------
# Boundary stubs - minimal stand-ins for the Mollie SDK objects (HTTP boundary).
# ---------------------------------------------------------------------------
class _StubAmount:
    def __init__(self, value="10.00", currency="EUR"):
        self.value = value
        self.currency = currency


class _WebhookPayment:
    """Rich Mollie-payment stand-in for handle_webhook (status predicates)."""

    def __init__(self, *, id="tr_wh", metadata=None, state="paid"):
        self.id = id
        self.status = state
        self.amount = _StubAmount()
        self.metadata = metadata if metadata is not None else {}
        self.description = "desc"
        self.method = "ideal"
        self.created_at = None
        self.paid_at = None
        self.checkout_url = "https://mollie.test/checkout"
        self._state = state

    def is_paid(self):
        return self._state == "paid"

    def is_canceled(self):
        return self._state == "canceled"

    def is_expired(self):
        return self._state == "expired"

    def is_failed(self):
        return self._state == "failed"

    def is_pending(self):
        return self._state == "pending"

    def is_open(self):
        return self._state == "open"


class _ProcessPayment:
    """Stub Mollie payment returned by client.payments.create()."""

    def __init__(self, **kw):
        self.id = kw.get("id", "tr_proc")
        self.status = "open"
        self.checkout_url = kw.get("checkout_url", "https://mollie.test/pay")
        self.expires_at = kw.get("expires_at")
        self._links = kw.get("_links")


class _Payments:
    def __init__(self, *, created=None, gotten=None, raise_on_get=None):
        self._created = created
        self._gotten = gotten
        self._raise_on_get = raise_on_get
        self.last_create_data = None

    def create(self, data=None, idempotency_key="", **params):
        self.last_create_data = data
        return self._created

    def get(self, payment_id):
        if self._raise_on_get:
            raise self._raise_on_get
        return self._gotten


class _Subscription:
    def __init__(self, id="sub_stub"):
        self.id = id


class _Subscriptions:
    def __init__(self, sub=None, raise_on_create=None):
        self._sub = sub or _Subscription()
        self._raise_on_create = raise_on_create

    def create(self, data=None, idempotency_key="", **params):
        if self._raise_on_create:
            raise self._raise_on_create
        return self._sub


class _Customer:
    def __init__(self, sub=None, raise_on_create=None):
        self.subscriptions = _Subscriptions(sub, raise_on_create)


class _Customers:
    def __init__(self, customer=None, raise_on_get=None):
        self._customer = customer or _Customer()
        self._raise_on_get = raise_on_get

    def get(self, customer_id):
        if self._raise_on_get:
            raise self._raise_on_get
        return self._customer


class _Client:
    def __init__(self, payments=None, customers=None):
        self.payments = payments or _Payments()
        self.customers = customers or _Customers()


class _Settings:
    def __init__(self, *, enable_subscriptions=True, subscription=None, raise_on_get_subscription=None):
        self.enable_subscriptions = enable_subscriptions
        self._subscription = subscription
        self._raise = raise_on_get_subscription

    def validate_transaction_currency(self, currency):
        return True

    def get_redirect_url(self, doctype, docname):
        return f"https://app.test/{doctype}/{docname}"

    def get_webhook_url(self):
        return "https://app.test/webhook"

    def get_subscription_webhook_url(self):
        return "https://app.test/sub-webhook"

    def get_subscription(self, customer_id, subscription_id):
        if self._raise:
            raise self._raise
        return self._subscription


def _bare_gateway(client=None, settings=None):
    """MollieGateway without __init__ (SDK boundary); stubbed client/settings."""
    gw = pg.MollieGateway.__new__(pg.MollieGateway)
    gw.gateway_name = "Default"
    gw.client = client or _Client()
    gw.settings = settings or _Settings()
    return gw


# ===========================================================================
# MollieGateway.handle_webhook
# ===========================================================================
class TestMollieHandleWebhook(EnhancedTestCase):
    def _donation(self, amount=15.0):
        return self.create_test_donation(amount=amount, mode_of_payment="Mollie", paid=0)

    def _ref_metadata(self, donation):
        return {
            "reference_doctype": "Donation",
            "reference_docname": donation.name,
            "donation_id": donation.name,
        }

    def test_no_payment_id_ignored(self):
        gw = _bare_gateway()
        result = gw.handle_webhook({})
        self.assertEqual(result["status"], "ignored")
        self.assertIn("No payment ID", result["reason"])

    def test_no_reference_metadata_ignored(self):
        payment = _WebhookPayment(id="tr_nometa", metadata={}, state="paid")
        gw = _bare_gateway(client=_Client(payments=_Payments(gotten=payment)))
        result = gw.handle_webhook({"id": "tr_nometa"})
        self.assertEqual(result["status"], "ignored")
        self.assertIn("No reference document", result["reason"])

    def test_paid_marks_donation_paid_and_fires_hook(self):
        donation = self._donation()
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 0)
        payment = _WebhookPayment(id="tr_paid", metadata=self._ref_metadata(donation), state="paid")
        gw = _bare_gateway(client=_Client(payments=_Payments(gotten=payment)))

        result = gw.handle_webhook({"id": "tr_paid"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "completed")
        # The real Donation was marked paid (db_set + on_payment_authorized hook).
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 1)

    def test_failed_payment_processed_as_failed(self):
        donation = self._donation()
        payment = _WebhookPayment(id="tr_fail", metadata=self._ref_metadata(donation), state="failed")
        gw = _bare_gateway(client=_Client(payments=_Payments(gotten=payment)))
        result = gw.handle_webhook({"id": "tr_fail"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "failed")
        # A failed webhook must NOT mark the donation paid.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 0)

    def test_pending_payment_processed_as_pending(self):
        donation = self._donation()
        payment = _WebhookPayment(id="tr_pend", metadata=self._ref_metadata(donation), state="open")
        gw = _bare_gateway(client=_Client(payments=_Payments(gotten=payment)))
        result = gw.handle_webhook({"id": "tr_pend"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "pending")
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 0)

    def test_exception_returns_error_response(self):
        self.expectErrorLog("Mollie Webhook Processing")
        gw = _bare_gateway(
            client=_Client(payments=_Payments(raise_on_get=RuntimeError("mollie 500")))
        )
        result = gw.handle_webhook({"id": "tr_boom"})
        self.assertEqual(result["status"], "error")


# ===========================================================================
# MollieGateway.process_payment - remaining branches
# ===========================================================================
class TestProcessPaymentBranches(EnhancedTestCase):
    def _donation(self, amount=15.0):
        return self.create_test_donation(amount=amount, mode_of_payment="Mollie", paid=0)

    def test_recurring_payment_sets_recurring_sequence(self):
        donation = self._donation()
        created = _ProcessPayment(id="tr_rec")
        gw = _bare_gateway(client=_Client(payments=_Payments(created=created)))
        gw.process_payment(donation, {"recurring_payment": True, "customer_id": "cst_rec"})
        sent = gw.client.payments.last_create_data
        self.assertEqual(sent["sequenceType"], "recurring")
        self.assertEqual(sent["customerId"], "cst_rec")

    def test_billing_email_from_form_data(self):
        donation = self._donation()
        created = _ProcessPayment(id="tr_email")
        gw = _bare_gateway(client=_Client(payments=_Payments(created=created)))
        gw.process_payment(donation, {"email": "giver@example.org"})
        sent = gw.client.payments.last_create_data
        self.assertEqual(sent["billingAddress"], {"email": "giver@example.org"})

    def test_no_checkout_url_returns_error(self):
        donation = self._donation()
        created = _ProcessPayment(id="tr_nourl")
        # Neither checkout_url nor _links present -> raises -> error response.
        del created.checkout_url
        created._links = None
        gw = _bare_gateway(client=_Client(payments=_Payments(created=created)))
        self.expectErrorLog("Mollie Payment Error")
        result = gw.process_payment(donation, {})
        self.assertEqual(result["status"], "error")


# ===========================================================================
# MollieGateway subscription error / edge branches
# ===========================================================================
class TestMollieSubscriptionEdges(EnhancedTestCase):
    def test_get_subscription_status_exception(self):
        self.expectErrorLog("Mollie Subscription Status Retrieval")
        settings = _Settings(raise_on_get_subscription=RuntimeError("api down"))
        gw = _bare_gateway(settings=settings)
        result = gw.get_subscription_status("cst_1", "sub_1")
        self.assertEqual(result["status"], "error")

    def test_cancel_subscription_success_delegates(self):
        member = self.create_test_member(first_name="CancelOk")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_c", "mollie_subscription_id": "sub_c"},
        )
        member.reload()
        gw = _bare_gateway()
        # Mock justified: CompletePaymentService.cancel_subscription is the outbound
        # Mollie cancel + Member-status update; return its standard result shape.
        with patch.object(pg, "CompletePaymentService") as svc:
            svc.return_value.cancel_subscription.return_value = {
                "status": "success",
                "message": "cancelled",
            }
            result = gw.cancel_subscription(member)
        self.assertEqual(result["status"], "success")
        # The owner was passed through so the service updates THIS member.
        _, kwargs = svc.return_value.cancel_subscription.call_args
        self.assertEqual(kwargs["owner_doctype"], "Member")
        self.assertEqual(kwargs["owner_name"], member.name)

    def test_cancel_subscription_exception(self):
        self.expectErrorLog("Mollie Subscription Cancellation")
        member = self.create_test_member(first_name="CancelErr")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_e", "mollie_subscription_id": "sub_e"},
        )
        member.reload()
        gw = _bare_gateway()
        with patch.object(pg, "CompletePaymentService") as svc:
            svc.return_value.cancel_subscription.side_effect = RuntimeError("cancel boom")
            result = gw.cancel_subscription(member)
        self.assertEqual(result["status"], "error")

    def test_create_subscription_member_without_iban_passes_none_account(self):
        # A member with no IBAN -> consumerAccount None is sent to the service
        # (the `member.iban else None` branch), and the success result is returned.
        member = self.create_test_member(first_name="NoIbanSub")
        frappe.db.set_value("Member", member.name, "iban", "")
        member.reload()
        gw = _bare_gateway(settings=_Settings(enable_subscriptions=True))
        captured = {}

        def _create(customer_data, sub_data):
            captured["consumerAccount"] = sub_data.get("consumerAccount")
            return {
                "customer_id": "cst_n",
                "subscription_id": "sub_n",
                "subscription_status": "active",
                "next_payment_date": "2026-07-01",
            }

        # Mock justified: CompletePaymentService.create_customer_subscription is the
        # outbound Mollie provisioning call.
        with patch.object(pg, "CompletePaymentService") as svc:
            svc.return_value.create_customer_subscription.side_effect = _create
            result = gw.create_subscription(member, {"amount": 25.0, "interval": "1 month"})
        self.assertEqual(result["status"], "success")
        self.assertIsNone(captured["consumerAccount"])

    def test_create_subscription_exception(self):
        self.expectErrorLog("Mollie Subscription Error")
        member = self.create_test_member(first_name="SubBoom")
        gw = _bare_gateway(settings=_Settings(enable_subscriptions=True))
        with patch.object(pg, "CompletePaymentService") as svc:
            svc.return_value.create_customer_subscription.side_effect = RuntimeError("svc boom")
            result = gw.create_subscription(member, {"amount": 25.0, "interval": "1 month"})
        self.assertEqual(result["status"], "error")


# ===========================================================================
# Trivial / no-API gateway methods
# ===========================================================================
class TestTrivialGatewayMethods(EnhancedTestCase):
    def test_sepa_handle_webhook_not_applicable(self):
        self.assertEqual(pg.SEPAGateway().handle_webhook({})["status"], "not_applicable")

    def test_sepa_get_payment_status_pending(self):
        result = pg.SEPAGateway().get_payment_status("anything")
        self.assertEqual(result["status"], "pending")
        self.assertIn("SEPA collection", result["message"])

    def test_cash_get_payment_status_pending(self):
        result = pg.CashGateway().get_payment_status("anything")
        self.assertEqual(result["status"], "pending")
        self.assertIn("Manual verification", result["message"])

    def test_cash_handle_webhook_not_applicable(self):
        self.assertEqual(pg.CashGateway().handle_webhook({})["status"], "not_applicable")


# ===========================================================================
# SEPAGateway.process_payment - mandate creation failure
# ===========================================================================
class TestSEPAMandateFailure(EnhancedTestCase):
    def test_mandate_creation_failure_returns_error(self):
        # Point the donation at a non-existent donor so _create_sepa_mandate's
        # frappe.get_doc("Donor", ...) raises -> returns None -> process_payment
        # returns the "Failed to create SEPA mandate" error.
        self.expectErrorLog("SEPA Gateway Error")
        donor = self.create_test_donor(donor_name="Doomed Donor")
        donation = self.create_test_donation(
            amount=10.0, mode_of_payment="SEPA Direct Debit", donor=donor.name, paid=0
        )
        frappe.db.set_value("Donation", donation.name, "donor", "Donor-NONEXISTENT-XYZ")
        donation.reload()
        result = pg.SEPAGateway().process_payment(
            donation, {"donor_iban": "NL39RABO0300065264", "donor_name": "x"}
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to create SEPA mandate", result["message"])


# ===========================================================================
# _activate_direct_subscription_after_first_payment - extra branches
# ===========================================================================
class TestActivateDirectExtra(EnhancedTestCase):
    def test_quarterly_calculates_start_date_and_persists_on_donation(self):
        donation = self.create_test_donation(amount=10.0, mode_of_payment="Mollie", paid=0)
        gw = _bare_gateway(client=_Client(customers=_Customers(_Customer(_Subscription("sub_q")))))
        payment = types.SimpleNamespace(
            id="tr_q",
            customer_id="cst_q",
            # A real Mollie payment carries paidAt; the start date is anchored to
            # it so two attempts for the same payment build the same payload.
            paid_at="2026-04-10T09:00:00+00:00",
            metadata={
                "subscription_setup": "true",
                "subscription_interval": "3 months",
                "subscription_amount": "30.00",
                "subscription_currency": "EUR",
                "donation_id": donation.name,
            },
        )
        # Mock justified: Mollie Settings start-date calc is a config-boundary read.
        # The stub mirrors the real signature INCLUDING `anchor`, and records it:
        # the start date must be computed from the payment, not the clock, or two
        # webhook attempts for one payment send different payloads and Mollie 400s
        # the retry instead of replaying it (see the startDate comment in
        # _activate_direct_subscription_after_first_payment). A stub narrower than
        # the method it fakes hides that -- as this one did.
        seen_anchor = {}

        def fake_next_payment_date(min_months_ahead=2, anchor=None):
            seen_anchor["anchor"] = anchor
            return "2026-09-01"

        fake_settings = types.SimpleNamespace(
            get_next_payment_date_for_scheduled_months=fake_next_payment_date,
            quarterly_yearly_payment_months="9,12",
            # The subscription payload also carries a webhookUrl (#345); a stub
            # narrower than the object it fakes turns that into an "error" result
            # that reads as a start-date failure.
            get_webhook_url=lambda: "https://example.invalid/webhook?env=test",
        )
        with patch.object(frappe, "get_single", return_value=fake_settings):
            result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_q")
        # subscription id is persisted on the donation that owns the field.
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "mollie_subscription_id"), "sub_q"
        )
        # The start date must be anchored to the PAYMENT. Anchoring to the clock
        # makes the payload differ between two attempts for the same payment, and
        # Mollie answers a reused idempotency key with changed parameters with a
        # 400 rather than replaying the original create.
        self.assertEqual(
            seen_anchor.get("anchor"),
            frappe.utils.getdate("2026-04-10T09:00:00+00:00"),
            "the subscription start date must be computed from the payment's own "
            "timestamp, not from today",
        )

    def test_exception_path_returns_error(self):
        self.expectErrorLog("Mollie Direct Subscription Creation")
        gw = _bare_gateway(
            client=_Client(customers=_Customers(raise_on_get=RuntimeError("no customer")))
        )
        payment = types.SimpleNamespace(
            id="tr_de",
            customer_id="cst_de",
            metadata={
                "subscription_setup": "true",
                "subscription_interval": "1 month",
                "subscription_amount": "10.00",
                "subscription_currency": "EUR",
                "donation_id": None,
            },
        )
        result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "error")


# ===========================================================================
# _activate_donation_subscription_after_first_payment - extra branches
# ===========================================================================
class TestActivateDonationExtra(EnhancedTestCase):
    def test_missing_customer_id_errors(self):
        donor = self.create_test_donor(donor_name="No Customer Donor")
        donation = self.create_test_donation(
            amount=12.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        # Payment has no customer_id and donation has no mollie_customer_id.
        gw = _bare_gateway()
        payment = types.SimpleNamespace(customer_id=None, metadata={"donation_id": donation.name})
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "missing_customer_id")

    def test_exception_path_returns_error(self):
        self.expectErrorLog("Mollie Donation Subscription Creation")
        donor = self.create_test_donor(donor_name="Boom Donation Donor")
        donation = self.create_test_donation(
            amount=12.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        donation.db_set("recurring_frequency", "Monthly")
        gw = _bare_gateway(
            client=_Client(customers=_Customers(_Customer(raise_on_create=RuntimeError("create boom"))))
        )
        payment = types.SimpleNamespace(
            customer_id="cst_boom", metadata={"donation_id": donation.name}
        )
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "error")


# ===========================================================================
# Whitelisted endpoints - success / gateway-routing paths
# ===========================================================================
class TestEndpointSuccessPaths(EnhancedTestCase):
    def test_get_payment_status_routes_to_gateway(self):
        # A non-Mollie donation with a payment_id routes to that gateway's
        # get_payment_status (no live API for Bank Transfer).
        donor = self.create_test_donor(donor_name="Routed Donor")
        donation = self.create_test_donation(
            amount=20.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        donation.db_set("payment_id", "DON-REF-1")
        result = pg.get_payment_status(donation_id=donation.name)
        # BankTransferGateway.get_payment_status -> pending / manual verification.
        self.assertEqual(result["status"], "pending")
        self.assertIn("Manual verification", result["message"])

    def test_manual_payment_confirmation_marks_paid(self):
        donor = self.create_test_donor(donor_name="Manual Confirm Donor")
        donation = self.create_test_donation(
            amount=40.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        result = pg.manual_payment_confirmation(
            donation_id=donation.name, payment_reference="BANK-REF-99", notes="received"
        )
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 1)
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "payment_id"), "BANK-REF-99")

    def test_create_member_subscription_success(self):
        member = self.create_test_member(first_name="CreateSubOk")
        frappe.db.set_value("Member", member.name, "mollie_customer_id", "cst_ok")
        member.reload()
        gw = _bare_gateway(settings=_Settings(enable_subscriptions=True))

        def _create(customer_data, sub_data):
            return {
                "status": "success",
                "customer_id": "cst_ok",
                "subscription_id": "sub_made",
                "subscription_status": "active",
                "next_payment_date": "2026-07-01",
            }

        # Mock justified: factory builds a real MollieGateway needing live API;
        # replace gateway construction (SDK boundary) + the outbound provisioning.
        with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw):
            with patch.object(pg, "CompletePaymentService") as svc:
                svc.return_value.create_customer_subscription.side_effect = _create
                result = pg.create_member_subscription(
                    member_id=member.name, amount=25.0, interval="1 month"
                )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_made")
        # On success the endpoint persists payment_method = Mollie.
        self.assertEqual(frappe.db.get_value("Member", member.name, "payment_method"), "Mollie")

    def test_get_member_subscription_status_success(self):
        member = self.create_test_member(first_name="GetSubStatusOk")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_s", "mollie_subscription_id": "sub_s"},
        )
        member.reload()
        gw = _bare_gateway(settings=_Settings(subscription={"id": "sub_s", "status": "active"}))
        with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw):
            result = pg.get_member_subscription_status(member_id=member.name)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription"]["status"], "active")

    def test_manual_subscription_retry_empty(self):
        gw = _bare_gateway()
        orig_get_all = frappe.get_all

        def fake_get_all(doctype, *a, **k):
            if doctype == "Payment Entry":
                return []
            return orig_get_all(doctype, *a, **k)

        with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw):
            with patch.object(frappe, "get_all", side_effect=fake_get_all):
                result = pg.manual_subscription_retry()
        self.assertEqual(result["total_payments_checked"], 0)

    def test_mollie_webhook_delegates_to_service_handler(self):
        # mollie_webhook forwards to the service-based payment webhook handler.
        # Regression guard for the import-path bug: this import previously pointed
        # at mollie.api.payment_webhook, where the function no longer exists, so
        # the guest endpoint raised ImportError on every call. It now resolves
        # from mollie.api.webhooks.
        target = "verenigingen.verenigingen_payments.mollie.api.webhooks.handle_mollie_payment_webhook"
        with patch(target, return_value={"status": "delegated_ok"}) as handler:
            result = pg.mollie_webhook()
        handler.assert_called_once()
        self.assertEqual(result["status"], "delegated_ok")


# ===========================================================================
# update_mollie_subscription_amount - success + linked-donation update
# ===========================================================================
class TestUpdateSubscriptionAmount(EnhancedTestCase):
    """update_mollie_subscription_amount commits (it updates linked donations and
    calls frappe.db.commit()), so the linked Donation's amount change survives
    FrappeTestCase rollback; force-clean the touched donation in tearDown.
    """

    def setUp(self):
        super().setUp()
        self._committed_donations = []

    def tearDown(self):
        for name in self._committed_donations:
            if frappe.db.exists("Donation", name):
                doc = frappe.get_doc("Donation", name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Donation", name, force=True, ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def test_success_updates_linked_recurring_donation_amount(self):
        member = self.create_test_member(first_name="UpdAmount")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_u", "mollie_subscription_id": "sub_u"},
        )
        donor = self.create_test_donor(donor_name="Recurring Amount Donor")
        donation = self.create_test_donation(
            amount=15.0, mode_of_payment="Mollie", donor=donor.name, paid=0, status="Recurring"
        )
        frappe.db.set_value("Donation", donation.name, "mollie_subscription_id", "sub_u")
        self._committed_donations.append(donation.name)
        frappe.db.commit()

        # update_subscription walks customers.get(..).subscriptions.get(..).update(..);
        # build a stub chain that models exactly that outbound SDK surface.
        class _UpdatableSub:
            id = "sub_u"
            status = "active"
            amount = _StubAmount("40.00")

            def update(self, data):
                return self

        class _SubsWithGet:
            def get(self, subscription_id):
                return _UpdatableSub()

        class _CustWithSubs:
            subscriptions = _SubsWithGet()

        class _CustsWithGet:
            def get(self, customer_id):
                return _CustWithSubs()

        # Mock justified: factory builds a real MollieGateway needing live API;
        # replace it with a bare gateway whose customers stub is the SDK boundary.
        gw = _bare_gateway()
        gw.client = types.SimpleNamespace(customers=_CustsWithGet())

        with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=gw):
            result = pg.update_mollie_subscription_amount(subscription_id="sub_u", new_amount=40.0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["new_amount"], 40.0)
        # The linked recurring donation amount was updated and committed.
        self.assertEqual(float(frappe.db.get_value("Donation", donation.name, "amount")), 40.0)


# ===========================================================================
# Subscription webhook helper branches
# ===========================================================================
class TestSubscriptionWebhookHelperBranches(EnhancedTestCase):
    def test_find_member_customer_without_member(self):
        # A Customer tagged with the subscription id but NOT linked to any member.
        self.expectErrorLog("Mollie Subscription Webhook")
        # The custom_mollie_* fields enforce Mollie's id format (prefix + 14 chars).
        sub_id = "sub_orphanXXXXXX"  # 14 chars after the underscore
        cst_id = "cst_orphanXXXXXX"
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Orphan Cust {frappe.generate_hash(length=6)}",
                "customer_type": "Individual",
                "custom_mollie_subscription_id": sub_id,
                "custom_mollie_customer_id": cst_id,
            }
        ).insert()
        self.track_doc("Customer", customer.name)
        result = pg._find_member_for_subscription(sub_id)
        self.assertEqual(result, (None, None, None))

    def test_update_subscription_status_canceled_sets_cancel_date(self):
        member = self.create_test_member(first_name="CanceledStatus")
        settings = _Settings(
            subscription={
                "id": "sub_cx",
                "status": "canceled",
                "canceled_at": "2026-06-30",
            }
        )
        gw = _bare_gateway(settings=settings)
        result = {"actions": []}
        pg._update_subscription_status(gw, "cst_cx", "sub_cx", member.name, result)
        self.assertEqual(result["subscription_status"], "canceled")
        self.assertEqual(
            str(frappe.db.get_value("Member", member.name, "subscription_cancelled_date")),
            "2026-06-30",
        )

    def test_update_subscription_status_error_branch(self):
        self.expectErrorLog("Mollie Subscription Webhook")
        member = self.create_test_member(first_name="StatusErr")
        # get_subscription returns None -> get_subscription_status -> error.
        gw = _bare_gateway(settings=_Settings(subscription=None))
        result = {"actions": []}
        pg._update_subscription_status(gw, "cst_err", "sub_err", member.name, result)
        self.assertIn("subscription_error", result)
        self.assertNotIn("status_updated", result["actions"])


if __name__ == "__main__":
    unittest.main()
