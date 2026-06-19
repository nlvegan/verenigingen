"""
Coverage-extension tests for payment_gateways.py.

Complements the existing trio (test_payment_gateways.py / _unit.py / _endpoints.py)
by driving the larger uncovered blocks WITHOUT a live Mollie / Ponto / bank API.
Only the external SDK / HTTP boundary is stubbed (each stub annotated); all gateway
and helper business logic runs for real.

Covers (previously-uncovered) blocks of
verenigingen/verenigingen_payments/utils/payment_gateways.py:
    - MollieGateway.process_payment: success (checkout_url + _links fallback +
      subscription-setup metadata) and the exception/error branch
    - MollieGateway.create_new_payment_for_cancelled
    - MollieGateway.create_subscription: subscriptions-disabled early return
    - MollieGateway.get_subscription_status: success + not-found mapping
    - MollieGateway.cancel_subscription: no-subscription early return
    - MollieGateway.update_subscription: success path (customers/subscriptions stub)
    - PontoGateway.process_payment: missing-IBAN error branch + status mapping
      success (Executed -> paid) against a real Ponto Payment Link document
    - _activate_subscription_after_first_payment: success path
    - _activate_direct_subscription_after_first_payment: success path
    - _activate_donation_subscription_after_first_payment: skip-without-agreement
    - retry_failed_subscription_activations: no-payments summary
    - _create_webhook_processing_log: real Webhook Processing Log insert
    - _find_member_for_subscription: found + not-found branches
    - _update_subscription_status: member field update from subscription status
    - _process_subscription_payment: real Payment Entry creation against a real
      Sales Invoice, plus the duplicate / not-paid / no-invoice branches
"""

import types
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


# ---------------------------------------------------------------------------
# Boundary stubs - minimal stand-ins for the Mollie SDK objects. They model the
# external HTTP/SDK boundary only; everything they feed into is real code.
# ---------------------------------------------------------------------------
class _StubAmount:
    def __init__(self, value="10.00", currency="EUR"):
        self.value = value
        self.currency = currency


class _StubPayment:
    def __init__(self, **kw):
        self.id = kw.get("id", "tr_stub123")
        self.status = kw.get("status", "open")
        self.amount = kw.get("amount", _StubAmount())
        self.metadata = kw.get("metadata", {})
        self.customer_id = kw.get("customer_id")
        self.sequence_type = kw.get("sequence_type", "oneoff")
        self.checkout_url = kw.get("checkout_url", "https://mollie.test/checkout")
        self.expires_at = kw.get("expires_at")
        self._links = kw.get("_links")
        self._paid = kw.get("paid", False)

    def is_paid(self):
        return self._paid


class _CreatePayments:
    """Stub for client.payments with create() and get()."""

    def __init__(self, created=None, gotten=None, raise_on_create=None):
        self._created = created
        self._gotten = gotten
        self._raise_on_create = raise_on_create
        self.last_create_data = None

    def create(self, data):
        self.last_create_data = data
        if self._raise_on_create:
            raise self._raise_on_create
        return self._created

    def get(self, payment_id):
        return self._gotten


class _StubSubscription:
    def __init__(self, **kw):
        self.id = kw.get("id", "sub_stub")
        self.status = kw.get("status", "active")
        self.amount = kw.get("amount", _StubAmount("25.00"))
        self.next_payment_date = kw.get("next_payment_date")

    def update(self, data):
        # Return self with applied amount (Mollie returns the updated resource)
        return self


class _StubSubscriptions:
    def __init__(self, sub=None):
        self._sub = sub or _StubSubscription()

    def get(self, subscription_id):
        return self._sub

    def create(self, data=None):
        return self._sub


class _StubCustomer:
    def __init__(self, sub=None):
        self.subscriptions = _StubSubscriptions(sub)


class _StubCustomers:
    def __init__(self, customer=None):
        self._customer = customer or _StubCustomer()

    def get(self, customer_id):
        return self._customer


class _StubClient:
    def __init__(self, payments=None, customers=None):
        self.payments = payments or _CreatePayments()
        self.customers = customers or _StubCustomers()


class _StubSettings:
    """Stand-in for Mollie Settings - only the surface the gateway touches."""

    def __init__(self, enable_subscriptions=True):
        self.enable_subscriptions = enable_subscriptions
        self._subscription = None

    def validate_transaction_currency(self, currency):
        return True

    def get_redirect_url(self, doctype, docname):
        return f"https://app.test/{doctype}/{docname}"

    def get_webhook_url(self):
        return "https://app.test/webhook"

    def get_subscription_webhook_url(self):
        return "https://app.test/sub-webhook"

    def get_subscription(self, customer_id, subscription_id):
        return self._subscription


def _bare_gateway(client=None, settings=None):
    """Build a MollieGateway without __init__ (which needs live settings).

    Bypassing __init__ + injecting a stubbed client/settings is the SDK boundary.
    """
    gw = pg.MollieGateway.__new__(pg.MollieGateway)
    gw.gateway_name = "Default"
    gw.client = client or _StubClient()
    gw.settings = settings or _StubSettings()
    return gw


# ===========================================================================
# MollieGateway.process_payment
# ===========================================================================
class TestMollieProcessPayment(EnhancedTestCase):
    def _donation(self, amount=15.0):
        return self.create_test_donation(amount=amount, mode_of_payment="Mollie", paid=0)

    def test_process_payment_success_with_checkout_url(self):
        donation = self._donation(amount=42.0)
        # Mock justified: client.payments.create is the outbound Mollie HTTP call.
        created = _StubPayment(id="tr_ok", checkout_url="https://mollie.test/pay/abc")
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(created=created)))

        result = gw.process_payment(donation, {})

        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_url"], "https://mollie.test/pay/abc")
        self.assertEqual(result["payment_id"], "tr_ok")
        # Real payment_data assembly: amount is formatted as a Mollie amount dict.
        sent = gw.client.payments.last_create_data
        self.assertEqual(sent["amount"], {"value": "42.00", "currency": "EUR"})
        self.assertEqual(sent["metadata"]["reference_doctype"], "Donation")
        # db_set persisted the Mollie payment id on the donation.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "payment_id"), "tr_ok")

    def test_process_payment_uses_links_checkout_fallback(self):
        donation = self._donation()
        links = types.SimpleNamespace(checkout=types.SimpleNamespace(href="https://mollie.test/links/xyz"))
        created = _StubPayment(id="tr_links", _links=links)
        # Delete checkout_url so the _links fallback branch is taken.
        del created.checkout_url
        # Mock justified: outbound Mollie payment-create HTTP call.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(created=created)))

        result = gw.process_payment(donation, {})
        self.assertEqual(result["payment_url"], "https://mollie.test/links/xyz")

    def test_process_payment_subscription_setup_metadata(self):
        donation = self._donation(amount=20.0)
        created = _StubPayment(id="tr_sub")
        # Mock justified: outbound Mollie payment-create HTTP call.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(created=created)))

        gw.process_payment(
            donation,
            {
                "subscription_setup": True,
                "subscription_interval": "3 months",
                "customer_id": "cst_99",
            },
        )
        sent = gw.client.payments.last_create_data
        self.assertEqual(sent["sequenceType"], "first")
        self.assertEqual(sent["customerId"], "cst_99")
        self.assertEqual(sent["metadata"]["subscription_setup"], "true")
        self.assertEqual(sent["metadata"]["subscription_interval"], "3 months")

    def test_process_payment_error_branch(self):
        donation = self._donation()
        # Mock justified: simulate the outbound Mollie call failing (HTTP/SDK error).
        gw = _bare_gateway(
            client=_StubClient(payments=_CreatePayments(raise_on_create=RuntimeError("mollie down")))
        )
        result = gw.process_payment(donation, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("Payment setup failed", result["message"])

    def test_create_new_payment_for_cancelled_clears_and_recreates(self):
        donation = self._donation()
        donation.db_set("payment_id", "tr_old")
        created = _StubPayment(id="tr_new")
        # Mock justified: outbound Mollie payment-create HTTP call.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(created=created)))

        result = gw.create_new_payment_for_cancelled(donation, {})
        self.assertEqual(result["status"], "redirect_required")
        self.assertEqual(result["payment_id"], "tr_new")
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "payment_id"), "tr_new")


# ===========================================================================
# MollieGateway subscription methods (no live API)
# ===========================================================================
class TestMollieSubscriptionMethods(EnhancedTestCase):
    def test_create_subscription_disabled_returns_error(self):
        member = self.create_test_member(first_name="SubDisabled")
        gw = _bare_gateway(settings=_StubSettings(enable_subscriptions=False))
        result = gw.create_subscription(member, {"amount": 25.0, "interval": "1 month"})
        self.assertEqual(result["status"], "error")
        self.assertIn("not enabled", result["message"])

    def test_get_subscription_status_success(self):
        settings = _StubSettings()
        settings._subscription = {"id": "sub_1", "status": "active"}
        gw = _bare_gateway(settings=settings)
        result = gw.get_subscription_status("cst_1", "sub_1")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription"]["status"], "active")

    def test_get_subscription_status_not_found(self):
        settings = _StubSettings()
        settings._subscription = None  # get_subscription returns None -> error
        gw = _bare_gateway(settings=settings)
        result = gw.get_subscription_status("cst_1", "sub_missing")
        self.assertEqual(result["status"], "error")

    def test_cancel_subscription_no_active_returns_error(self):
        member = self.create_test_member(first_name="NoActiveSub")
        # member has no mollie_customer_id / mollie_subscription_id
        gw = _bare_gateway()
        result = gw.cancel_subscription(member)
        self.assertEqual(result["status"], "error")
        self.assertIn("No active subscription", result["message"])

    def test_update_subscription_success(self):
        sub = _StubSubscription(id="sub_up", status="active")
        # Mock justified: customers/subscriptions are the outbound Mollie SDK surface.
        gw = _bare_gateway(client=_StubClient(customers=_StubCustomers(_StubCustomer(sub))))
        result = gw.update_subscription("cst_1", "sub_up", {"amount": {"value": "30.00", "currency": "EUR"}})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription"]["id"], "sub_up")

    def test_update_subscription_error_branch(self):
        class _BoomCustomers:
            def get(self, _):
                raise RuntimeError("no such customer")

        # Mock justified: simulate the outbound Mollie customers.get failing.
        gw = _bare_gateway(client=_StubClient(customers=_BoomCustomers()))
        result = gw.update_subscription("cst_x", "sub_x", {})
        self.assertEqual(result["status"], "error")


# ===========================================================================
# PontoGateway.process_payment
# ===========================================================================
class TestPontoGatewayProcessPayment(EnhancedTestCase):
    def test_process_payment_missing_company_iban(self):
        # Mode of payment is irrelevant to PontoGateway; use a valid one so the
        # donation can be created. The gateway reads only settings + donation.amount.
        donation = self.create_test_donation(amount=10.0, mode_of_payment="Bank Transfer", paid=0)
        # Force the company IBAN empty so the early-return error branch is hit.
        # Mock justified: get_payments_settings reads settings; we patch only the
        # settings read so the IBAN-missing branch is reachable deterministically.
        from unittest.mock import patch

        with patch.object(pg, "get_payments_settings", return_value=types.SimpleNamespace(company_iban="")):
            result = pg.PontoGateway().process_payment(donation, {})
        self.assertEqual(result["status"], "error")
        self.assertIn("IBAN not configured", result["message"])

    def test_get_payment_status_executed_maps_to_paid(self):
        # Build a real Ponto Payment Link doc (not submitted -> no API call) and
        # set status=Executed, then verify the gateway maps it to "paid".
        link = self._make_ponto_link(status="Executed")
        result = pg.PontoGateway().get_payment_status(link.name)
        self.assertEqual(result["status"], "paid")
        self.assertEqual(result["ponto_status"], "Executed")

    def test_get_payment_status_rejected_maps_to_failed(self):
        link = self._make_ponto_link(status="Rejected")
        result = pg.PontoGateway().get_payment_status(link.name)
        self.assertEqual(result["status"], "failed")

    def _make_ponto_link(self, status="Draft"):
        return self._insert_ponto_link(status)

    def _insert_ponto_link(self, status):
        doc = frappe.new_doc("Ponto Payment Link")
        doc.payment_type = "One-Time"
        doc.amount = 12.50
        doc.currency = "EUR"
        doc.description = "Coverage test link"
        doc.creditor_name = "Test Org"
        doc.creditor_iban = "NL39RABO0300065264"
        doc.status = status
        doc.insert()
        self.track_doc("Ponto Payment Link", doc.name)
        return doc


# ===========================================================================
# Module-level subscription activation success paths
# ===========================================================================
class TestSubscriptionActivationSuccess(EnhancedTestCase):
    def test_activate_subscription_success_with_dues_schedule(self):
        member = self.create_test_member(first_name="ActivateOk", iban="NL39RABO0300065264")
        # Dues schedule creation requires an active membership for the member.
        self.create_test_membership(member_name=member.name)
        # A real, active, auto-generating dues schedule so the helper's
        # frappe.get_all lookup finds one and builds subscription_data from it.
        # (No commit: stays within the test transaction so FrappeTestCase rolls
        # it back cleanly without leaving a dangling current_dues_schedule link.)
        self.create_test_dues_schedule(member.name, amount=15.0, frequency="monthly")

        # create_subscription is invoked for real on the gateway; stub it at the
        # outbound boundary by replacing CompletePaymentService's network call.
        # Mock justified: CompletePaymentService.create_customer_subscription is the
        # outbound Mollie provisioning call. We return a real-shaped success dict so
        # the gateway + _activate_* result plumbing runs for real.
        from unittest.mock import patch

        fake = {
            "customer_id": "cst_ok",
            "subscription_id": "sub_ok",
            "subscription_status": "active",
            "next_payment_date": "2026-07-01",
        }
        gw = _bare_gateway()
        with patch.object(pg, "CompletePaymentService") as svc:
            svc.return_value.create_customer_subscription.return_value = fake
            result = pg._activate_subscription_after_first_payment(gw, member.name, "cst_ok", "tr_first")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_ok")

    def test_activate_direct_subscription_success(self):
        gw = _bare_gateway()
        payment = _StubPayment(
            id="tr_direct",
            customer_id="cst_direct",
            metadata={
                "subscription_setup": "true",
                "subscription_interval": "1 month",
                "subscription_amount": "10.00",
                "subscription_currency": "EUR",
            },
        )
        result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_stub")
        self.assertEqual(result["customer_id"], "cst_direct")

    def test_activate_donation_subscription_skips_without_donation_id(self):
        # The supported early-return: no donation_id in metadata.
        gw = _bare_gateway()
        payment = _StubPayment(metadata={})
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("No donation ID", result["reason"])

    def test_activate_donation_subscription_success_persists_id_on_donation(self):
        """Fixed bug: the helper now sources the subscription from the Donation
        itself (amount + recurring_frequency) and stores the Mollie subscription id
        on donation.mollie_subscription_id. Previously it read a nonexistent
        `donation.donation_agreement` / "Donation Agreement" doctype and always
        errored, so recurring-donation subscriptions were never created.

        No subscription_interval in metadata here -> the recurring_frequency ->
        Mollie-interval conversion branch is exercised.
        """
        donor = self.create_test_donor(donor_name="Recurring Donor")
        donation = self.create_test_donation(
            amount=12.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        donation.db_set("recurring_frequency", "Monthly")

        gw = _bare_gateway()
        payment = _StubPayment(customer_id="cst_donation", metadata={"donation_id": donation.name})
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_stub")
        self.assertEqual(result["customer_id"], "cst_donation")
        self.assertEqual(result["donation_id"], donation.name)
        # The subscription id is persisted on the donation that owns the field.
        donation.reload()
        self.assertEqual(donation.mollie_subscription_id, "sub_stub")

    def test_activate_donation_subscription_falls_back_to_donation_customer(self):
        """When the payment has no customer_id, the donation's mollie_customer_id
        is used; the metadata subscription_interval takes precedence over the
        donation frequency when present."""
        donor = self.create_test_donor(donor_name="Customerless Payment Donor")
        donation = self.create_test_donation(
            amount=20.0, mode_of_payment="Bank Transfer", donor=donor.name, paid=0
        )
        donation.db_set("mollie_customer_id", "cst_from_donation")

        gw = _bare_gateway()
        payment = _StubPayment(metadata={"donation_id": donation.name, "subscription_interval": "3 months"})
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["customer_id"], "cst_from_donation")


# ===========================================================================
# retry_failed_subscription_activations
# ===========================================================================
class TestRetryFailedActivations(EnhancedTestCase):
    def test_retry_with_no_recent_payments(self):
        # No Mollie Payment Entries in the window -> empty summary, gateway is
        # built but its client is never called.
        # Mock justified: the factory builds a real MollieGateway which needs live
        # settings; replace only the gateway construction (SDK boundary).
        from unittest.mock import patch

        with patch.object(pg.PaymentGatewayFactory, "get_gateway", return_value=_bare_gateway()):
            with patch.object(frappe, "get_all", wraps=frappe.get_all) as ga:
                # Force the Payment Entry query to return nothing deterministically.
                orig = frappe.get_all

                def fake_get_all(doctype, *a, **k):
                    if doctype == "Payment Entry":
                        return []
                    return orig(doctype, *a, **k)

                ga.side_effect = fake_get_all
                result = pg.retry_failed_subscription_activations()

        self.assertEqual(result["total_payments_checked"], 0)
        self.assertEqual(result["successful_activations"], 0)


# ===========================================================================
# _create_webhook_processing_log
# ===========================================================================
class TestWebhookProcessingLog(EnhancedTestCase):
    def test_creates_log_record(self):
        before = frappe.db.count("Webhook Processing Log")
        pg._create_webhook_processing_log(
            webhook_id="tr_log123",
            webhook_type="payment",
            status="success",
            payload={"id": "tr_log123", "amount": "10.00"},
            processing_result={"ok": True},
        )
        after = frappe.db.count("Webhook Processing Log")
        self.assertEqual(after, before + 1)
        log = frappe.get_all(
            "Webhook Processing Log",
            filters={"webhook_id": "tr_log123"},
            fields=["name", "status", "webhook_type"],
            limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log[0]["status"], "success")
        self.assertEqual(log[0]["webhook_type"], "payment")
        self.track_doc("Webhook Processing Log", log[0]["name"])

    def test_bytes_payload_serialized_safely(self):
        pg._create_webhook_processing_log(
            webhook_id="tr_bytes",
            webhook_type="payment",
            status="ignored",
            payload=b'{"id": "tr_bytes"}',
        )
        log = frappe.get_all(
            "Webhook Processing Log",
            filters={"webhook_id": "tr_bytes"},
            fields=["name", "raw_payload"],
            limit=1,
        )
        self.assertTrue(log)
        self.assertIn("tr_bytes", log[0]["raw_payload"])
        self.track_doc("Webhook Processing Log", log[0]["name"])


# ===========================================================================
# Webhook helper functions
# ===========================================================================
class TestSubscriptionWebhookHelpers(EnhancedTestCase):
    def test_find_member_not_found(self):
        result = pg._find_member_for_subscription("sub_no_such_thing")
        self.assertEqual(result, (None, None, None))

    def test_find_member_found(self):
        member = self.create_test_member(first_name="WebhookFind")
        # Ensure the member has a Customer, then tag it with the subscription id.
        member.reload()
        if not member.customer:
            member.create_customer()
            member.reload()
        frappe.db.set_value(
            "Customer",
            member.customer,
            {
                "custom_mollie_subscription_id": "sub_findme",
                "custom_mollie_customer_id": "cst_findme",
            },
        )
        member_name, customer_name, customer_id = pg._find_member_for_subscription("sub_findme")
        self.assertEqual(member_name, member.name)
        self.assertEqual(customer_name, member.customer)
        self.assertEqual(customer_id, "cst_findme")

    def test_update_subscription_status_writes_member_fields(self):
        member = self.create_test_member(first_name="StatusUpdate")
        settings = _StubSettings()
        settings._subscription = {
            "id": "sub_upd",
            "status": "active",
            "next_payment_date": "2026-08-01",
        }
        gw = _bare_gateway(settings=settings)
        result = {"actions": []}
        pg._update_subscription_status(gw, "cst_1", "sub_upd", member.name, result)
        self.assertEqual(result["subscription_status"], "active")
        self.assertIn("status_updated", result["actions"])
        self.assertEqual(frappe.db.get_value("Member", member.name, "subscription_status"), "active")


# ===========================================================================
# _process_subscription_payment - real Payment Entry creation
# ===========================================================================
class TestProcessSubscriptionPayment(EnhancedTestCase):
    """_process_subscription_payment commits its Payment Entry (it owns a real
    transaction with begin()/commit()), so the PE survives FrappeTestCase's
    rollback. Each test uses a per-run unique reference_no and force-deletes the
    committed PE(s) in tearDown to keep the DB clean and avoid order-dependence.
    """

    def setUp(self):
        super().setUp()
        self._committed_pes = []

    def tearDown(self):
        for pe_name in self._committed_pes:
            if frappe.db.exists("Payment Entry", pe_name):
                doc = frappe.get_doc("Payment Entry", pe_name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", pe_name, force=True, ignore_permissions=True)
        frappe.db.commit()
        super().tearDown()

    def _member_with_customer(self, first_name):
        member = self.create_test_member(first_name=first_name)
        member.reload()
        if not member.customer:
            member.create_customer()
            member.reload()
        return member

    def test_creates_payment_entry_for_unpaid_invoice(self):
        member = self._member_with_customer("PaySub")
        # Factory builds + submits a complete invoice; status defaults to Unpaid.
        invoice = self.create_test_sales_invoice(customer=member.name, grand_total=10.0)
        # Flush setup writes: _process_subscription_payment calls frappe.db.begin()
        # which trips Frappe's implicit-commit guard if uncommitted writes remain.
        frappe.db.commit()

        ref_no = f"tr_pe_{frappe.generate_hash(length=8)}"
        # Mock justified: client.payments.get is the outbound Mollie fetch.
        payment = _StubPayment(
            id=ref_no,
            paid=True,
            amount=_StubAmount(value=str(invoice.grand_total)),
            sequence_type="recurring",
        )
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(gotten=payment)))

        result = pg._process_subscription_payment(gw, member.name, member.customer, ref_no, "sub_pe")
        self._committed_pes.append(result["payment_entry"])
        self.assertEqual(result["status"], "success")
        self.assertTrue(frappe.db.exists("Payment Entry", result["payment_entry"]))
        # The PE references the invoice and carries the Mollie payment id.
        pe = frappe.get_doc("Payment Entry", result["payment_entry"])
        self.assertEqual(pe.reference_no, ref_no)
        self.assertEqual(pe.references[0].reference_name, invoice.name)

    def test_not_paid_payment_ignored(self):
        member = self._member_with_customer("NotPaidSub")
        payment = _StubPayment(id="tr_unpaid", paid=False, status="open")
        # Mock justified: outbound Mollie payments.get.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(gotten=payment)))
        result = pg._process_subscription_payment(gw, member.name, member.customer, "tr_unpaid", "sub_x")
        self.assertEqual(result["status"], "ignored")

    def test_no_unpaid_invoice(self):
        member = self._member_with_customer("NoInvoiceSub")
        payment = _StubPayment(id="tr_noinv", paid=True, amount=_StubAmount("10.00"))
        # Mock justified: outbound Mollie payments.get.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(gotten=payment)))
        result = pg._process_subscription_payment(gw, member.name, member.customer, "tr_noinv", "sub_y")
        self.assertEqual(result["status"], "no_invoice")

    def test_duplicate_payment_returns_duplicate(self):
        member = self._member_with_customer("DupSub")
        # Invoice total (50) exceeds the partial payment (10), so the invoice stays
        # "Partly Paid" and is re-found on the second call -> the FOR UPDATE
        # idempotency guard sees the existing Payment Entry and returns "duplicate".
        invoice = self.create_test_sales_invoice(customer=member.name, grand_total=50.0)
        frappe.db.commit()

        ref_no = f"tr_dup_{frappe.generate_hash(length=8)}"
        payment = _StubPayment(id=ref_no, paid=True, amount=_StubAmount(value="10.00"))
        # Mock justified: outbound Mollie payments.get returns the same payment twice.
        gw = _bare_gateway(client=_StubClient(payments=_CreatePayments(gotten=payment)))

        first = pg._process_subscription_payment(gw, member.name, member.customer, ref_no, "sub_dup")
        self.assertEqual(first["status"], "success")
        self._committed_pes.append(first["payment_entry"])
        frappe.db.commit()

        second = pg._process_subscription_payment(gw, member.name, member.customer, ref_no, "sub_dup")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(second["payment_entry"], first["payment_entry"])


if __name__ == "__main__":
    unittest.main()
