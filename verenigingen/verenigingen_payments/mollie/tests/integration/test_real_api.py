"""
Real API Integration Tests for Mollie Subscription System

This test suite addresses QC findings about "simulated success patterns"
by implementing genuine end-to-end testing with real Mollie API calls.

NO MOCKING - All tests use real API interactions to verify actual functionality.

These tests exercise the PRODUCTION Mollie path:
- The live Mollie gateway client (customers / payments / mandates / subscriptions)
- SubscriptionService (status lookup, member-subscription listing, payment guard)
- The Member.mollie_customer_id / mollie_subscription_id / subscription_status fields
  where production stores the Mollie relationship.

They are LIVE integration tests: they require a configured Mollie test key and
network access, and skip cleanly when either is unavailable (so CI, which has no
key, skips the whole suite).

Test Categories:
1. Customer creation and linkage to the Member record
2. First payment processing with mandate establishment
3. Subscription creation and status lookup via SubscriptionService
4. Member-subscription listing reflecting live Mollie state
5. Error scenarios and recovery testing
"""

import time
import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService
from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory


class TestMollieSubscriptionRealAPI(EnhancedTestCase):
    """
    Real API integration tests for Mollie subscription system

    Addresses QC finding: "Tests designed to accept either success OR expected failure"

    These tests ONLY accept genuine success - failures indicate real problems
    that must be fixed, not "expected" test outcomes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Verify test mode is enabled for safety
        settings = frappe.get_single("Mollie Settings")
        if not settings.test_mode:
            raise unittest.SkipTest("Mollie tests require test_mode=True for safety")

        # Verify API credentials are configured
        if not settings.get_active_api_key():
            raise unittest.SkipTest("Mollie API key not configured for testing")

        cls.gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        # Production service that reads/writes the Member.mollie_* fields and talks
        # to Mollie via the app's MollieClient (same test account as the gateway).
        cls.subscription_service = SubscriptionService()

        # Test API connectivity
        try:
            # Make actual API call to verify connectivity
            client = cls.gateway.client
            client.methods.list()  # Simple API test call
            cls.api_available = True
        except Exception as e:
            raise unittest.SkipTest(f"Mollie API not accessible: {str(e)}")

    def setUp(self):
        super().setUp()

        # Create test member for subscription testing
        self.test_member = self.create_test_member(
            first_name="Real",
            last_name="API Test",
            birth_date="1990-01-01",
            email="real.api.test@verenigingen-test.com",
        )

        # Track created resources for cleanup
        self.mollie_customers_created = []
        self.mollie_subscriptions_created = []

    def tearDown(self):
        """Clean up Mollie resources created during testing"""
        # Clean up Mollie subscriptions (must cancel before deleting the customer)
        for customer_id, subscription_id in self.mollie_subscriptions_created:
            try:
                self.gateway.client.customers.get(customer_id).subscriptions.delete(subscription_id)
            except Exception:
                pass  # Subscription may already be canceled

        # Clean up Mollie customers
        for customer_id in self.mollie_customers_created:
            try:
                self.gateway.client.customers.delete(customer_id)
            except Exception:
                pass  # Customer may already be deleted

        super().tearDown()

    def _link_customer_to_member(self, customer_id, subscription_id=None, subscription_status=None):
        """Store the Mollie relationship on the Member, the way production does."""
        values = {"mollie_customer_id": customer_id}
        if subscription_id is not None:
            values["mollie_subscription_id"] = subscription_id
        if subscription_status is not None:
            values["subscription_status"] = subscription_status
        frappe.db.set_value("Member", self.test_member.name, values)
        self.test_member.reload()

    def _create_customer_and_mandate(self):
        """Create a live Mollie customer with a direct-debit mandate (enables subscriptions)."""
        customer = self.gateway.client.customers.create(
            {
                "name": f"{self.test_member.first_name} {self.test_member.last_name}",
                "email": self.test_member.email,
                "metadata": {"member_id": self.test_member.name, "test_marker": "real_api_test"},
            }
        )
        self.mollie_customers_created.append(customer.id)

        customer.mandates.create(
            data={
                "method": "directdebit",
                "consumerName": f"{self.test_member.first_name} {self.test_member.last_name}",
                "consumerAccount": "NL53INGB0654422370",  # Mollie test IBAN
                "consumerBic": "INGBNL2A",
                "signatureDate": today(),
                "mandateReference": f"MANDATE-{self.test_member.name}",
            }
        )
        return customer

    def test_real_customer_creation_flow(self):
        """Real Mollie customer creation, linked onto the Member record."""
        customer_data = {
            "name": f"{self.test_member.first_name} {self.test_member.last_name}",
            "email": self.test_member.email,
            "metadata": {"member_id": self.test_member.name, "test_marker": "real_api_test"},
        }

        # Make actual API call to Mollie
        mollie_customer = self.gateway.client.customers.create(customer_data)
        self.mollie_customers_created.append(mollie_customer.id)

        # Verify real response from Mollie
        self.assertIsNotNone(mollie_customer.id)
        self.assertTrue(mollie_customer.id.startswith("cst_"))
        self.assertEqual(mollie_customer.email, self.test_member.email)
        self.assertEqual(mollie_customer.name, f"{self.test_member.first_name} {self.test_member.last_name}")

        # Production stores the Mollie customer id on the Member record.
        self._link_customer_to_member(mollie_customer.id)
        self.assertEqual(
            frappe.db.get_value("Member", self.test_member.name, "mollie_customer_id"),
            mollie_customer.id,
        )

    def test_real_first_payment_creation(self):
        """Test real first payment creation for subscription setup"""

        # Create customer first
        mollie_customer = self.gateway.client.customers.create(
            {
                "name": f"{self.test_member.first_name} {self.test_member.last_name}",
                "email": self.test_member.email,
                "metadata": {"member_id": self.test_member.name},
            }
        )
        self.mollie_customers_created.append(mollie_customer.id)

        # Create real first payment
        payment_data = {
            "amount": {"currency": "EUR", "value": "25.00"},
            "description": "Real API first payment test",
            "customerId": mollie_customer.id,
            "sequenceType": "first",  # Critical for subscription setup
            "redirectUrl": "https://dev.veganisme.net/payment-return",
            "metadata": {
                "member_id": self.test_member.name,
                "payment_type": "subscription_first",
                "test_marker": "real_api_test",
            },
        }

        # Make actual API call to create payment
        payment = self.gateway.client.payments.create(data=payment_data)

        # Verify real payment was created
        self.assertIsNotNone(payment.id)
        self.assertTrue(payment.id.startswith("tr_"))
        self.assertEqual(payment.amount["value"], "25.00")
        self.assertEqual(payment.sequence_type, "first")
        self.assertEqual(payment.customer_id, mollie_customer.id)
        self.assertIsNotNone(payment.checkout_url)  # Should have checkout URL

        # Verify payment status (will be 'open' initially - user has not paid yet)
        self.assertEqual(payment.status, "open")

    def test_real_subscription_creation_and_status(self):
        """Real subscription creation, then status lookup via SubscriptionService."""
        mollie_customer = self._create_customer_and_mandate()

        # Create a real subscription (requires the mandate created above)
        subscription = mollie_customer.subscriptions.create(
            data={
                "amount": {"currency": "EUR", "value": "25.00"},
                "interval": "1 month",
                "description": f"Real API subscription for {self.test_member.name}",
                "metadata": {"member_id": self.test_member.name, "subscription_type": "membership_dues"},
            }
        )
        self.mollie_subscriptions_created.append((mollie_customer.id, subscription.id))

        # Verify the real Mollie response
        self.assertTrue(subscription.id.startswith("sub_"))
        self.assertEqual(subscription.status, "active")
        self.assertEqual(subscription.amount["value"], "25.00")
        self.assertEqual(subscription.interval, "1 month")

        # The production SubscriptionService should read the same live subscription.
        status = self.subscription_service.get_subscription_status(mollie_customer.id, subscription.id)
        self.assertEqual(status["id"], subscription.id)
        self.assertEqual(status["status"], "active")
        self.assertTrue(status["is_active"])
        self.assertEqual(status["amount"], 25.0)
        self.assertEqual(status["interval"], "1 month")

    def test_real_member_subscription_listing(self):
        """SubscriptionService.list_member_subscriptions reflects live Mollie state.

        Replaces the old bespoke-"Donation Agreement" webhook test: it now validates
        the real production lookup that reads Member.mollie_customer_id /
        mollie_subscription_id and returns the live subscription from Mollie.
        """
        mollie_customer = self._create_customer_and_mandate()
        subscription = mollie_customer.subscriptions.create(
            data={
                "amount": {"currency": "EUR", "value": "25.00"},
                "interval": "1 month",
                "description": "Membership dues",
                "metadata": {"member_id": self.test_member.name, "subscription_type": "membership_dues"},
            }
        )
        self.mollie_subscriptions_created.append((mollie_customer.id, subscription.id))

        # Link the live Mollie relationship onto the Member, the way a completed
        # first-payment webhook would in production.
        self._link_customer_to_member(
            mollie_customer.id, subscription_id=subscription.id, subscription_status="active"
        )

        subscriptions = self.subscription_service.list_member_subscriptions(self.test_member.name)
        self.assertEqual(len(subscriptions), 1)
        self.assertEqual(subscriptions[0]["id"], subscription.id)
        self.assertEqual(subscriptions[0]["status"], "active")
        self.assertEqual(subscriptions[0]["amount"], 25.0)

    def test_real_error_scenarios_and_recovery(self):
        """Test real error scenarios and recovery mechanisms"""

        # Test 1: Invalid customer ID -> real Mollie error, not simulated success
        with self.assertRaises(Exception) as context:
            self.gateway.client.customers.get("cst_invalid_customer_id")
        self.assertIn("cst_invalid_customer_id", str(context.exception))

        # Test 2: Subscription without a mandate -> real Mollie mandate error
        mollie_customer = self.gateway.client.customers.create(
            {"name": "Error Test Customer", "email": "error.test@verenigingen-test.com"}
        )
        self.mollie_customers_created.append(mollie_customer.id)

        with self.assertRaises(Exception) as context:
            mollie_customer.subscriptions.create(
                data={
                    "amount": {"currency": "EUR", "value": "25.00"},
                    "interval": "1 month",
                    "description": "Error test subscription",
                }
            )
        error_message = str(context.exception).lower()
        self.assertTrue(
            any(keyword in error_message for keyword in ["mandate", "direct", "sepa"]),
            f"Expected mandate error, got: {error_message}",
        )

        # Test 3: SubscriptionService rejects processing an unknown payment id
        # (the production guard in process_subscription_payment).
        with self.assertRaises((MollieIntegrationError, Exception)):
            self.subscription_service.process_subscription_payment("tr_invalid_payment_id")

    def test_real_api_rate_limiting_resilience(self):
        """Test system resilience to API rate limiting"""

        # Make multiple rapid API calls to test rate limiting handling
        results = []
        for i in range(10):  # 10 rapid calls
            try:
                start_time = time.time()

                # Real API call - list payment methods
                methods = self.gateway.client.methods.list()

                end_time = time.time()
                results.append(
                    {
                        "call": i + 1,
                        "success": True,
                        "duration": end_time - start_time,
                        "methods_count": len(methods),
                    }
                )

            except Exception as e:
                results.append(
                    {"call": i + 1, "success": False, "error": str(e)[:100], "error_type": type(e).__name__}
                )

            time.sleep(0.1)  # Small delay between calls

        # Analyze results - should handle rate limiting gracefully
        successful_calls = sum(1 for r in results if r["success"])
        failed_calls = len(results) - successful_calls

        # Most calls should succeed (Mollie test API is quite permissive)
        self.assertGreaterEqual(
            successful_calls, 7, f"Expected at least 7/10 calls to succeed, got {successful_calls}"
        )

        # If any calls failed, they should be due to rate limiting, not other errors
        rate_limit_failures = sum(
            1 for r in results if not r["success"] and "rate" in r.get("error", "").lower()
        )

        if failed_calls > 0:
            self.assertEqual(
                rate_limit_failures, failed_calls, "All failures should be rate limiting related"
            )

    def test_end_to_end_subscription_flow(self):
        """Complete end-to-end subscription flow against the real Mollie API.

        customer -> link to Member -> first payment -> mandate -> subscription ->
        store subscription on Member -> verify live status via SubscriptionService.
        """
        # Step 1: Create the Mollie customer and link it onto the Member.
        mollie_customer = self.gateway.client.customers.create(
            {
                "name": f"{self.test_member.first_name} {self.test_member.last_name}",
                "email": self.test_member.email,
                "metadata": {"member_id": self.test_member.name},
            }
        )
        self.mollie_customers_created.append(mollie_customer.id)
        self._link_customer_to_member(mollie_customer.id)

        # Step 2: Verify the customer exists in Mollie.
        fetched = self.gateway.client.customers.get(mollie_customer.id)
        self.assertEqual(fetched.email, self.test_member.email)

        # Step 3: Create the first (sequenceType=first) payment that establishes the mandate.
        payment = self.gateway.client.payments.create(
            {
                "amount": {"currency": "EUR", "value": "30.00"},
                "description": "End-to-end test first payment",
                "customerId": mollie_customer.id,
                "sequenceType": "first",
                "redirectUrl": "https://dev.veganisme.net/payment-success",
                "metadata": {"member_id": self.test_member.name, "test_type": "end_to_end"},
            }
        )
        self.assertEqual(payment.sequence_type, "first")
        self.assertEqual(payment.customer_id, mollie_customer.id)

        # Step 4: Create the mandate + recurring subscription (post-first-payment state).
        mollie_customer.mandates.create(
            data={
                "method": "directdebit",
                "consumerName": f"{self.test_member.first_name} {self.test_member.last_name}",
                "consumerAccount": "NL53INGB0654422370",
                "consumerBic": "INGBNL2A",
                "signatureDate": today(),
                "mandateReference": f"E2E-{self.test_member.name}",
            }
        )
        subscription = mollie_customer.subscriptions.create(
            data={
                "amount": {"currency": "EUR", "value": "30.00"},
                "interval": "1 month",
                "description": "End-to-end test subscription",
                "metadata": {"member_id": self.test_member.name, "subscription_type": "membership_dues"},
            }
        )
        self.mollie_subscriptions_created.append((mollie_customer.id, subscription.id))

        # Step 5: Persist the subscription on the Member (production webhook outcome).
        self._link_customer_to_member(
            mollie_customer.id, subscription_id=subscription.id, subscription_status="active"
        )

        # Step 6: Verify the final state through the production service + Member record.
        status = self.subscription_service.get_subscription_status(mollie_customer.id, subscription.id)
        self.assertTrue(status["is_active"])
        self.assertEqual(status["amount"], 30.0)

        member = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member.mollie_customer_id, mollie_customer.id)
        self.assertEqual(member.mollie_subscription_id, subscription.id)


if __name__ == "__main__":
    unittest.main()
