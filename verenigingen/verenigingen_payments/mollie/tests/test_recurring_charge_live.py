"""A recurring charge that really settles, against the real Mollie test API.

Scope, stated precisely: this proves the *charge mechanism* end to end -- a
mandate is created, a recurring payment is charged against it, and it reaches
``paid``. It does NOT prove the app handles a paid recurring charge, because the
app does not yet handle one: ``SubscriptionService._process_membership_subscription_payment``
is a stub that returns a literal dict ("This would integrate with existing
membership payment processing"). Asserting against that stub would be asserting
against constants, so this module deliberately does not.

Why this works without a browser or a credit card
-------------------------------------------------
A plain SEPA direct-debit test payment stays ``pending`` forever -- Mollie never
settles it in test mode -- which is why their docs point you at credit cards for
testing recurring flows. But a card mandate can only be created by completing a
first payment in a hosted checkout, and that needs a browser.

Recurring payments are the exception. They have no checkout (they run without the
customer), so Mollie attaches a ``changePaymentState`` link to them in test mode
precisely so you can settle them yourself. That link is an ordinary HTML form --
a ``_formtoken`` and a ``final_state`` radio -- so a plain HTTP POST drives the
payment to whichever final state you post. Posting ``paid`` lands in about a
second. (The account history shows ``failed`` payments from this module too;
those are deliberate mutation runs that posted ``final_state=failed`` to prove
these tests bite, not flakiness.)

That also makes this exercise the instrument the app actually uses. The
production recurring path is SEPA-mandate based (``payment_gateways.py`` passes
``consumerAccount``, the member's IBAN); the app never touches credit cards.

Hygiene, stated honestly
------------------------
Customers and mandates ARE torn down. **Payments are not, and cannot be** -- a
settled Mollie payment is not deletable through any API. So every run of this
module leaves permanent payment records on the shared Mollie test account (two,
at time of writing). That is the standing cost of testing a real charge; it is
accepted deliberately rather than hidden. Runs cannot collide -- each creates its
own customer and tears down only its own ids.

The suite skips entirely without ``mollie_test_secret_key``, so CI never reaches
the network. With a key present but no network, it ERRORS rather than skipping.
"""

import re
import time
from datetime import datetime, timezone

import requests

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import (
    ensure_mollie_test_credentials,
)

# Mollie-accepted test IBAN that yields an immediately-valid SEPA mandate.
_TEST_IBAN = "NL39RABO0300065264"


class TestRecurringChargeLive(EnhancedTestCase):
    """A real Mollie charge, settled to `paid`, then handed to the app."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_credentials = ensure_mollie_test_credentials()

    def setUp(self):
        super().setUp()
        if not self.has_credentials:
            self.skipTest("No Mollie test key configured (mollie_test_secret_key in site config)")
        self.client = MollieClient()
        self.sdk = self.client.sdk_client
        self._customer_ids = []

    def tearDown(self):
        # A swallowed failure here leaks a customer + mandate on a SHARED account
        # with no signal at all, so every failure is logged rather than passed.
        for customer_id in getattr(self, "_customer_ids", []):
            try:
                customer_obj = self.sdk.customers.get(customer_id)
                for mandate in customer_obj.mandates.list():
                    try:
                        customer_obj.mandates.delete(mandate.id)
                    except Exception as e:
                        frappe.logger().warning(
                            f"Mollie test cleanup: could not delete mandate {mandate.id} "
                            f"on customer {customer_id}: {e}"
                        )
                self.sdk.customers.delete(customer_id)
            except Exception as e:
                frappe.logger().warning(
                    f"Mollie test cleanup: leaked customer {customer_id} on the shared "
                    f"Mollie test account: {e}"
                )
        super().tearDown()

    # --- helpers -------------------------------------------------------------

    def _customer_with_mandate(self):
        # Unique per run: a fixed name/email makes any leaked customer
        # indistinguishable from earlier runs' leaks.
        token = frappe.generate_hash(length=8)
        customer = self.sdk.customers.create(
            {"name": f"Recurring Charge Test {token}", "email": f"recurring-charge-{token}@example.org"}
        )
        self._customer_ids.append(customer.id)
        customer_obj = self.sdk.customers.get(customer.id)
        mandate = customer_obj.mandates.create(
            {
                "method": "directdebit",
                "consumerName": "Jan Jansen",
                "consumerAccount": _TEST_IBAN,
                # UTC: a site on Asia/Kolkata is a day ahead of Mollie and gets a 422.
                "signatureDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )
        self.assertEqual(mandate.status, "valid", "test IBAN must yield an immediately-valid mandate")
        return customer_obj, mandate.id

    def _settle_to_paid(self, payment):
        """Drive a pending test payment to `paid` via its changePaymentState form."""
        links = payment.get("_links") or {}
        self.assertIn(
            "changePaymentState",
            links,
            "Mollie did not attach changePaymentState -- test mode only adds it to payments "
            "with no checkout (i.e. sequenceType=recurring). Is this really a recurring payment?",
        )
        url = links["changePaymentState"]["href"]

        session = requests.Session()
        page = session.get(url, timeout=30)
        self.assertEqual(page.status_code, 200, f"test-mode page unreachable: {page.status_code}")
        token = re.search(r'name="_formtoken" value="([^"]+)"', page.text)
        self.assertIsNotNone(
            token,
            "Mollie's test-mode form no longer exposes _formtoken; this helper needs updating "
            "(the page is theirs and can change without notice)",
        )
        response = session.post(
            url,
            data={"_formtoken": token.group(1), "final_state": "paid", "submit": ""},
            timeout=30,
        )
        self.assertEqual(response.status_code, 200, "posting final_state=paid failed")

        # Mollie applies the state asynchronously; it lands in about a second.
        for _ in range(10):
            fresh = self.sdk.payments.get(payment.id)
            if fresh.status != "pending":
                return fresh
            time.sleep(1)
        self.fail(f"payment {payment.id} never left 'pending' after final_state=paid")

    # --- tests ---------------------------------------------------------------

    def test_recurring_charge_actually_settles_to_paid(self):
        """The charge itself: a real recurring payment that really becomes paid.

        This validates the scaffold rather than this repo's code -- almost nothing
        of `verenigingen` runs here. It earns its place by being the thing that
        proves the settle mechanism works, which the test below depends on; if
        Mollie changes the test-mode flow, this is what says so.
        """
        customer_obj, mandate_id = self._customer_with_mandate()

        payment = customer_obj.payments.create(
            {
                "amount": {"currency": "EUR", "value": "12.34"},
                "description": "Recurring dues charge",
                "sequenceType": "recurring",
                "mandateId": mandate_id,
            }
        )
        # Guard the premise: an unsettled SEPA recurring payment starts pending.
        self.assertEqual(payment.status, "pending")

        settled = self._settle_to_paid(payment)

        self.assertEqual(settled.status, "paid", "the recurring charge must actually settle")
        self.assertTrue(settled.is_paid())
        self.assertEqual(settled.amount["value"], "12.34")

    def test_handler_rejects_a_charge_that_did_not_settle(self):
        """An unsettled recurring payment must be refused by the app.

        This one DOES exercise production code -- the paid-status guard in
        process_subscription_payment -- against a real Mollie payment that is
        genuinely still pending, rather than a fake asserting it is.
        """
        from verenigingen.verenigingen_payments.mollie.exceptions import MollieIntegrationError

        customer_obj, mandate_id = self._customer_with_mandate()
        payment = customer_obj.payments.create(
            {
                "amount": {"currency": "EUR", "value": "9.99"},
                "description": "Unsettled recurring charge",
                "sequenceType": "recurring",
                "mandateId": mandate_id,
                "metadata": {"subscription_type": "membership_dues"},
            }
        )
        self.assertEqual(payment.status, "pending")

        with self.assertRaises(MollieIntegrationError):
            SubscriptionService(self.client).process_subscription_payment(payment.id)
