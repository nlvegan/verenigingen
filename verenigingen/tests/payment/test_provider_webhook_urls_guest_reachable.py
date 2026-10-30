"""
Every webhook URL this app hands a payment provider must be reachable by the
provider, which calls without credentials, i.e. as Guest (#1771).

Frappe gates whitelisted methods only at DISPATCH (``frappe.handler.execute_cmd`` ->
``frappe.is_whitelisted``): an internal call never consults ``frappe.guest_methods``,
so a webhookUrl on a non-guest function looks fine in every unit test and is refused
for every real notification. That is exactly how ``get_subscription_webhook_url()``
pointed Mollie at ``payment_gateways.mollie_subscription_webhook`` (whitelisted,
not allow_guest) for every member-dues subscription.
"""

from urllib.parse import urlparse

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _dotted_method(url: str) -> str:
    path = urlparse(url).path
    assert "/api/method/" in path, f"not a method URL: {url}"
    return path.split("/api/method/", 1)[1]


def _inline(method: str) -> str:
    return frappe.utils.get_url(f"/api/method/{method}")


def _provider_urls() -> dict:
    """Every producer of a provider-facing webhook URL, by name.

    Census (grep ``webhookUrl|exchangeUrl|webhook_url|get_.*webhook_url``): Mollie
    Settings (4), MollieClient, PaymentService, the bulk-payment page, Ponto Settings,
    ING Checkout Settings and the ING mandate service (2 types). A new producer is not
    covered until it is added here.
    """
    from verenigingen.templates.pages.mollie_bulk_payment_creation import get_webhook_url as bulk_url
    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import MandateService
    from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
    from verenigingen.verenigingen_payments.mollie.services.payment_service import PaymentService
    from verenigingen.verenigingen_payments.ponto.services.oauth2_service import PontoOAuth2Service

    mollie = frappe.get_single("Mollie Settings")
    ponto = frappe.new_doc("Ponto Settings")
    ponto.enable_webhooks = 1
    ponto.update_webhook_url()
    ing = frappe.new_doc("ING Checkout Settings")
    ing._generate_webhook_url()
    mandates = MandateService()
    return {
        "Mollie Settings.get_webhook_url": mollie.get_webhook_url(),
        "Mollie Settings.get_test_webhook_url": mollie.get_test_webhook_url(),
        "Mollie Settings.get_live_webhook_url": mollie.get_live_webhook_url(),
        "Mollie Settings.get_subscription_webhook_url": mollie.get_subscription_webhook_url(),
        "MollieClient.get_webhook_url": MollieClient().get_webhook_url(),
        "PaymentService._get_webhook_url": PaymentService()._get_webhook_url(),
        "mollie_bulk_payment_creation.get_webhook_url": bulk_url(),
        "Ponto Settings.webhook_url": ponto.webhook_url,
        "ING Checkout Settings.webhook_url": ing.webhook_url,
        "ING MandateService mandate": mandates._get_webhook_url("mandate"),
        "ING MandateService direct_debit": mandates._get_webhook_url("direct_debit"),
        # Inline producers (the URL is built inside a function, so these two are the
        # literal paths copied from ing_checkout/api/payment.py and
        # ponto/services/oauth2_service.py::_get_redirect_uri; the latter is the OAuth
        # redirect a browser lands on, not a server-to-server webhook).
        "ING payment.py inline webhook_url": _inline(
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment"
        ),
        "Ponto oauth2 redirect": PontoOAuth2Service()._get_redirect_uri(),
    }


class TestProviderWebhookUrlsGuestReachable(EnhancedTestCase):
    def test_every_provider_webhook_url_resolves_to_a_guest_method(self):
        for name, url in _provider_urls().items():
            with self.subTest(producer=name):
                self.assertTrue(url, f"{name} produced no URL")
                dotted = _dotted_method(url)
                # get_attr imports the module, which runs the whitelist decorator,
                # so membership cannot depend on import order.
                method = frappe.get_attr(dotted)
                self.assertIn(method, frappe.whitelisted, f"{dotted} ({name}) is not whitelisted")
                self.assertIn(
                    method,
                    frappe.guest_methods,
                    f"{dotted} ({name}) is not allow_guest: the provider's anonymous call is refused",
                )

    def test_the_membership_check_distinguishes_a_non_guest_function(self):
        """Control: a whitelisted-but-not-guest function is whitelisted and NOT in guest_methods."""

        @frappe.whitelist()
        def _members_only_probe():
            return None

        self.addCleanup(frappe.whitelisted.remove, _members_only_probe)
        self.assertIn(_members_only_probe, frappe.whitelisted)
        self.assertNotIn(_members_only_probe, frappe.guest_methods)


class _GuestDispatchMixin:
    """Posts a Mollie-shaped form body through Frappe's real dispatch gate as Guest."""

    def _post_as_guest(self, dotted: str, payment_id: str):
        from frappe.handler import execute_cmd

        environ = EnvironBuilder(
            method="POST",
            path="/",
            data={"id": payment_id},
            content_type="application/x-www-form-urlencoded",
        ).get_environ()
        old = (getattr(frappe.local, "request", None), frappe.local.form_dict, frappe.session.user)
        self.addCleanup(self._restore_guest_dispatch_state, old)
        frappe.local.request = Request(environ)
        # frappe.app.make_form_dict reads the body first and werkzeug caches it; the
        # webhook authenticators then read it back via get_data(). Mirror that, or the
        # body is reported empty.
        frappe.local.request.get_data(as_text=True)
        # set_user() resets form_dict, so it must come first.
        frappe.set_user("Guest")
        frappe.local.form_dict = frappe._dict(id=payment_id)
        return execute_cmd(dotted)

    @staticmethod
    def _restore_guest_dispatch_state(old):
        frappe.local.request, frappe.local.form_dict = old[0], old[1]
        frappe.set_user(old[2])


class TestSubscriptionWebhookDispatch(_GuestDispatchMixin, EnhancedTestCase):
    """Behavioural: an anonymous Mollie-shaped POST must get past dispatch."""

    def test_anonymous_post_to_the_subscription_webhook_url_is_not_refused_at_dispatch(self):
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.utils import webhook_security

        # The unknown payment id / unconfigured test site makes the handler log its own
        # refusal; that is the handler answering, which is what is being proven.
        self.expectErrorLog("Mollie", "Webhook Processing Error", "Security")
        url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()
        payment_id = f"tr_{frappe.generate_hash(length=10)}"

        # wraps= calls through: the spy only records that the handler Mollie reaches
        # authenticates the way the payment webhook does (it sets the webhook user).
        # Merely adding allow_guest to payment_gateways.mollie_subscription_webhook
        # would pass the dispatch gate but answer {"status": "ignored", "reason": "No
        # subscription ID in payload"} to a real ``id=tr_...`` body without ever
        # reaching this function, so being "not refused" alone is not enough.
        with patch.object(
            webhook_security, "authenticate_mollie_webhook", wraps=webhook_security.authenticate_mollie_webhook
        ) as authenticated:
            # The payment does not exist at Mollie (or there are no credentials): the
            # handler may answer with an error dict / 5xx, but it must be REACHED.
            # frappe.PermissionError is the dispatch refusal this test exists to catch.
            try:
                result = self._post_as_guest(_dotted_method(url), payment_id)
            except frappe.PermissionError as e:
                self.fail(f"Mollie's anonymous POST is refused at dispatch ({url}): {e}")

        authenticated.assert_called_once()
        self.assertIsInstance(result, dict)
        self.assertNotEqual(result.get("status"), "ignored", result)


class TestSubscriptionWebhookBooksTheDuesPayment(_GuestDispatchMixin, EnhancedTestCase):
    """The anonymous notification must actually BOOK the payment, not merely get past
    dispatch: a guest method that authenticates, swallows everything and answers ``ok``
    passes the dispatch test above and books nothing (reviewer's mutant on #1779).

    Only the Mollie fetch (``PaymentTypeRouter.fetch_payment``) is stubbed. Everything
    after it is real: classification by ``Member.mollie_subscription_id``,
    ``DuesPaymentProcessor`` and the Bank Transaction it writes.

    Not asserted: a SECOND identical delivery. It is not idempotent today (it posts an
    unallocated Payment Entry, "partial_processing"); that predates this change and is
    tracked in #1780. Pinning either behaviour here would be wrong.
    """

    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.mollie_account_fixtures import (
            ensure_bank_account_record,
            provisioned_mollie_settings,
        )

        self.company = "_Test Company"
        ctx = provisioned_mollie_settings(company=self.company)
        accounts = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        # The Bank Transaction is booked against the Bank Account of the clearing GL.
        ensure_bank_account_record(self.company, accounts["clearing_account"])

        self.member = self.create_test_member(
            first_name="SubHook",
            last_name="Member",
            email=f"subhook.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.customer = self.member.customer
        self.assertTrue(self.customer)
        self.subscription_id = f"sub_{frappe.generate_hash(length=8)}"
        self.mollie_customer_id = f"cst_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member",
            self.member.name,
            {"mollie_subscription_id": self.subscription_id, "mollie_customer_id": self.mollie_customer_id},
            update_modified=False,
        )
        self.invoice_name, self.invoice_total = self._unpaid_dues_invoice()

    def _unpaid_dues_invoice(self):
        income = frappe.get_value("Company", self.company, "default_income_account")
        item_code = f"Sub Hook Dues {frappe.generate_hash(length=5)}"
        item = frappe.new_doc("Item")
        item.item_code = item.item_name = item_code
        item.item_group = (
            "Services"
            if frappe.db.exists("Item Group", "Services")
            else frappe.get_value("Item Group", {"is_group": 0}, "name")
        )
        item.stock_uom = "Unit" if frappe.db.exists("UOM", "Unit") else frappe.get_value("UOM", {}, "name")
        item.is_stock_item = 0
        item.insert()

        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.customer
        invoice.company = self.company
        invoice.currency = frappe.get_value("Company", self.company, "default_currency")
        invoice.member = self.member.name
        invoice.is_membership_invoice = 1
        invoice.append("items", {"item_code": item_code, "qty": 1, "rate": 25, "income_account": income})
        invoice.insert()
        invoice.submit()
        return invoice.name, invoice.grand_total

    def test_anonymous_subscription_notification_books_a_bank_transaction_for_the_member(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from verenigingen.verenigingen_payments.mollie.services.payment_type_router import (
            PaymentTypeRouter,
        )

        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        # Amount derived from the fixture invoice, not hardcoded.
        payment = SimpleNamespace(
            id=payment_id,
            status="paid",
            # The company's own currency: the Bank Account's currency must match.
            amount={
                "value": f"{self.invoice_total:.2f}",
                "currency": frappe.get_value("Company", self.company, "default_currency"),
            },
            description="",
            subscription_id=self.subscription_id,
            customer_id=self.mollie_customer_id,
            paid_at="2025-04-10T09:00:00+00:00",
        )
        url = frappe.get_single("Mollie Settings").get_subscription_webhook_url()

        # developer_mode: the site's test_mode safety check refuses to authenticate a
        # test-mode webhook on a non-development site, before any booking.
        with patch.object(PaymentTypeRouter, "fetch_payment", return_value=payment), patch.dict(
            frappe.conf, {"developer_mode": 1}
        ):
            result = self._post_as_guest(_dotted_method(url), payment_id)

        rows = frappe.get_all(
            "Bank Transaction",
            filters={"reference_number": payment_id},
            fields=["name", "deposit", "party_type", "party", "custom_member"],
        )
        self.assertEqual(len(rows), 1, f"expected one Bank Transaction for {payment_id}; result: {result}")
        self.assertEqual(float(rows[0].deposit), float(self.invoice_total))
        self.assertEqual(rows[0].party_type, "Customer")
        self.assertEqual(rows[0].party, self.customer)
        self.assertEqual(rows[0].custom_member, self.member.name)
