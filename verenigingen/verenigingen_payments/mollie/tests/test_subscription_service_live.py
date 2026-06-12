"""
Live integration coverage for SubscriptionService against Mollie's REAL test API.

These exercise the paths the unit tests can only fake — list_subscriptions,
admin_cancel_subscription and update_subscription_mandate — by creating real
customers, mandates and subscriptions in Mollie's test environment and asserting
the service returns the expected structured data.

Gating: the suite needs a Mollie TEST secret key. It is read from site config
(``mollie_test_secret_key`` / ``mollie_test_profile_id`` in common_site_config.json,
never committed) by ensure_mollie_test_credentials(). When no key is configured —
e.g. CI without the secret — every test skips, so the module stays green.

Hygiene: every Mollie object created is tracked and torn down (subscriptions
cancelled, customers deleted) best-effort in tearDown, so the test account does not
accumulate state.
"""

from datetime import datetime, timezone

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import ensure_mollie_test_credentials

# Mollie-accepted test IBAN that yields an immediately-valid SEPA direct-debit mandate.
_TEST_IBAN = "NL39RABO0300065264"


class TestSubscriptionServiceLive(EnhancedTestCase):
    """SubscriptionService against the real Mollie test API (skips without a key)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Commits the test key into Mollie Settings once for the whole class.
        cls.has_credentials = ensure_mollie_test_credentials()

    def setUp(self):
        super().setUp()
        if not self.has_credentials:
            self.skipTest("No Mollie test key configured (mollie_test_secret_key in site config)")
        self.client = MollieClient()
        self.service = SubscriptionService(self.client)
        self._customer_ids = []

    def tearDown(self):
        # Best-effort cleanup: cancel each customer's subscriptions, then delete it.
        for customer_id in getattr(self, "_customer_ids", []):
            try:
                customer_obj = self.client.sdk_client.customers.get(customer_id)
                for sub in customer_obj.subscriptions.list():
                    if sub.status == "active":
                        try:
                            customer_obj.subscriptions.delete(sub.id)
                        except Exception:
                            pass
                self.client.sdk_client.customers.delete(customer_id)
            except Exception:
                pass
        super().tearDown()

    # --- helpers -------------------------------------------------------------

    def _new_customer(self):
        customer = self.client.sdk_client.customers.create(
            {"name": "Live Integration Test", "email": "live-int@example.org"}
        )
        self._customer_ids.append(customer.id)
        return customer.id

    def _new_mandate(self, customer_id, consumer_name="Jan Jansen"):
        customer_obj = self.client.sdk_client.customers.get(customer_id)
        mandate = customer_obj.mandates.create(
            {
                "method": "directdebit",
                "consumerName": consumer_name,
                "consumerAccount": _TEST_IBAN,
                # UTC date: site-local today() can be a day ahead of Mollie's clock
                # (e.g. on an Asia/Kolkata test site) and Mollie 422s a future date.
                "signatureDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )
        return mandate.id

    def _new_subscription(self, customer_id, mandate_id, value="10.00"):
        customer_obj = self.client.sdk_client.customers.get(customer_id)
        sub = customer_obj.subscriptions.create(
            {
                "amount": {"currency": "EUR", "value": value},
                "interval": "1 month",
                "description": "Live integration subscription",
                "mandateId": mandate_id,
            }
        )
        return sub.id

    # --- tests ---------------------------------------------------------------

    def test_list_subscriptions_empty_for_new_customer(self):
        """A brand-new customer has no subscriptions; list returns cleanly (no error)."""
        customer_id = self._new_customer()

        result = self.service.list_subscriptions(customer_id, active_only=False)

        self.assertIsNone(result["error"])
        self.assertEqual(result["total_found"], 0)
        self.assertEqual(result["subscriptions"], [])

    def test_list_subscriptions_returns_structured_amount(self):
        """list_subscriptions reports a real active subscription with a structured
        amount_value/currency (the #5 fix) — verified end-to-end against Mollie."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id, value="12.50")

        result = self.service.list_subscriptions(customer_id, active_only=False)

        self.assertIsNone(result["error"])
        self.assertEqual(result["total_found"], 1)
        sub = result["subscriptions"][0]
        self.assertEqual(sub["id"], subscription_id)
        self.assertEqual(sub["status"], "active")
        self.assertEqual(sub["amount_value"], 12.5)  # structured float, not a parsed string
        self.assertEqual(sub["currency"], "EUR")
        self.assertEqual(sub["amount"], "EUR 12.50")  # display string preserved

    def test_active_only_filtering_live(self):
        """active_only=True hides a cancelled subscription that active_only=False shows."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id)

        # Cancel it, then confirm the filter behaviour.
        cancel_result = self.service.admin_cancel_subscription(
            customer_id, subscription_id, reason="active_only filter test"
        )
        self.assertEqual(cancel_result.get("status"), "success")

        active = self.service.list_subscriptions(customer_id, active_only=True)
        self.assertEqual(active["total_found"], 0)

        every = self.service.list_subscriptions(customer_id, active_only=False)
        self.assertEqual(every["total_found"], 1)
        self.assertEqual(every["subscriptions"][0]["status"], "canceled")

    def test_admin_cancel_subscription_live(self):
        """admin_cancel_subscription cancels a real subscription and reports success."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id)

        result = self.service.admin_cancel_subscription(
            customer_id, subscription_id, reason="integration cancel"
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result["subscription_id"], subscription_id)

        # Mollie now reports the subscription as canceled.
        status = self.service.get_subscription_status(customer_id, subscription_id)
        self.assertTrue(status["is_canceled"])

    def test_admin_cancel_already_cancelled_is_graceful(self):
        """Cancelling an already-cancelled subscription returns a warning, not an error."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id)

        first = self.service.admin_cancel_subscription(customer_id, subscription_id, reason="first")
        self.assertEqual(first.get("status"), "success")

        second = self.service.admin_cancel_subscription(customer_id, subscription_id, reason="second")
        self.assertEqual(second.get("status"), "warning")

    def test_update_subscription_mandate_live(self):
        """update_subscription_mandate switches a subscription to a new mandate."""
        customer_id = self._new_customer()
        mandate_one = self._new_mandate(customer_id, consumer_name="Jan Jansen")
        subscription_id = self._new_subscription(customer_id, mandate_one)
        mandate_two = self._new_mandate(customer_id, consumer_name="Piet Pietersen")

        result = self.service.update_subscription_mandate(
            customer_id, subscription_id, mandate_two, reason="integration mandate switch"
        )

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result["new_mandate_id"], mandate_two)

    def test_update_subscription_patches_amount_description_webhook_live(self):
        """One PATCH carrying amount + description + webhookUrl — the exact call
        shape the amendment-sync drift repair issues — lands all three on the
        real subscription, with id and mandate untouched."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id, value="10.00")

        updated = self.client.update_subscription(
            customer_id,
            subscription_id,
            {
                "amount": {"currency": "EUR", "value": "26.50"},
                "description": "Contribution payment for member LIVE-1",
                "webhookUrl": "https://example.org/api/method/mollie-live-test",
            },
        )
        self.assertEqual(updated.id, subscription_id)

        status = self.service.get_subscription_status(customer_id, subscription_id)
        self.assertEqual(status["amount"], 26.5)
        self.assertEqual(status["description"], "Contribution payment for member LIVE-1")
        self.assertEqual(status["webhook_url"], "https://example.org/api/method/mollie-live-test")
        self.assertEqual(status["mandate_id"], mandate_id)
        self.assertEqual(status["status"], "active")

    def test_update_subscription_amount_only_preserves_other_fields_live(self):
        """An amount-only PATCH (the no-drift case) leaves description, webhook,
        mandate and the billing cycle (next_payment_date) untouched at Mollie."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id, value="10.00")
        before = self.service.get_subscription_status(customer_id, subscription_id)

        self.client.update_subscription(
            customer_id, subscription_id, {"amount": {"currency": "EUR", "value": "11.00"}}
        )

        after = self.service.get_subscription_status(customer_id, subscription_id)
        self.assertEqual(after["amount"], 11.0)
        self.assertEqual(after["description"], before["description"])
        self.assertEqual(after["webhook_url"], before["webhook_url"])
        self.assertEqual(after["mandate_id"], mandate_id)
        self.assertEqual(after["next_payment_date"], before["next_payment_date"])
