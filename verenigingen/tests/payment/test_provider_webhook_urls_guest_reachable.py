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


class TestSubscriptionWebhookDispatch(EnhancedTestCase):
    """Behavioural: an anonymous Mollie-shaped POST must get past dispatch."""

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
