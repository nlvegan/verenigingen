"""
Live integration coverage for the member-portal Mollie endpoints against Mollie's
REAL test API.

These exercise the three whitelisted payment-dashboard endpoints in
``verenigingen/api/mollie_payment.py`` end-to-end — as a logged-in plain member,
against real Mollie customers / mandates / subscriptions — rather than the
isolated SubscriptionService methods (covered in test_subscription_service_live.py)
or the auth-gate-only smoke tests (test_member_portal_self_service.py):

- get_subscription_details          -> shape + mandate validity of a real subscription
- cancel_specific_subscription      -> real cancel + Member record cleanup
- update_mollie_bank_account        -> create mandate -> PATCH subscription -> revoke
                                       old mandate -> write Member.mollie_mandate_id
- update_mollie_bank_account (neg)  -> canceled subscription hits the "not active"
                                       guard before any Mollie write

These are MEMBER-subscription ("membership_dues") tests: the subscription lives on
the Member record. The parallel donor-subscription path (recurring donations on the
Donor record) is not covered here.

Gating: needs a Mollie TEST secret key, read from site config
(``mollie_test_secret_key`` / ``mollie_test_profile_id`` in common_site_config.json,
never committed) by ensure_mollie_test_credentials(). Without a key — e.g. CI — every
test skips, so the module stays green.

Hygiene: every Mollie object created is tracked and torn down (subscriptions
cancelled, customers deleted) best-effort in tearDown, so the test account does not
accumulate state.
"""

from datetime import datetime, timezone

import frappe

from verenigingen.api import mollie_payment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import ensure_mollie_test_credentials

# Mollie-accepted test IBAN that yields an immediately-valid SEPA direct-debit mandate
# (a valid mandate is a precondition for subscription creation, so its presence is
# implicitly asserted by every subscription this module builds).
_TEST_IBAN = "NL39RABO0300065264"


class TestMolliePortalEndpointsLive(EnhancedTestCase):
    """The payment-dashboard Mollie endpoints, end-to-end against Mollie's test API."""

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
        self._customer_ids = []

    def tearDown(self):
        # Best-effort cleanup: cancel each customer's active subscriptions, then delete it.
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

    # --- Mollie fixtures -----------------------------------------------------

    def _new_customer(self):
        customer = self.client.sdk_client.customers.create(
            {"name": "Portal Live Test", "email": "portal-live@example.org"}
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
                # (this test site runs Asia/Kolkata) and Mollie 422s a future date.
                "signatureDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )
        return mandate.id

    def _new_subscription(self, customer_id, mandate_id, value="15.00"):
        customer_obj = self.client.sdk_client.customers.get(customer_id)
        sub = customer_obj.subscriptions.create(
            {
                "amount": {"currency": "EUR", "value": value},
                "interval": "1 month",
                "description": "Portal live subscription",
                "mandateId": mandate_id,
                "metadata": {"subscription_type": "membership_dues"},
            }
        )
        return sub.id

    def _mollie_member(self, customer_id=None, subscription_id=None, mandate_id=None):
        """A Member linked to a plain-member User, with the live Mollie relationship
        stored the way a completed first-payment webhook would in production."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        values = {}
        if customer_id is not None:
            values["mollie_customer_id"] = customer_id
        if subscription_id is not None:
            values["mollie_subscription_id"] = subscription_id
            values["subscription_status"] = "active"
        if mandate_id is not None:
            values["mollie_mandate_id"] = mandate_id
        if values:
            frappe.db.set_value("Member", member.name, values)
        member.reload()
        return member, user

    # --- session / user helpers (mirror test_member_portal_self_service.py) ---

    def _link_member_to_user(self, member, roles=("Verenigingen Member",)):
        """Create a User carrying ONLY the Verenigingen Member role profile (LOW tier,
        what real members carry) and link it to the member via BOTH user and email."""
        user = self.factory.create_user_with_roles(
            email=f"mollie-portal-{member.name}-{self.uid}@example.com",
            roles=list(roles),
        )
        user.reload()
        user.set("role_profiles", [{"role_profile": "Verenigingen Member"}])
        user.save(ignore_permissions=True)

        member.reload()
        member.user = user.name
        member.email = user.name
        member.save(ignore_permissions=True)
        return user

    def _as_user(self, user_name):
        class _Switcher:
            def __enter__(self):
                self.original = frappe.session.user
                frappe.set_user(user_name)
                return self

            def __exit__(self, *_):
                frappe.set_user(self.original)

        return _Switcher()

    # --- tests: get_subscription_details -------------------------------------

    def test_get_subscription_details_returns_live_active_subscription(self):
        """get_subscription_details returns the member's real active subscription with
        a structured amount and a valid mandate."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id, value="15.00")
        _, user = self._mollie_member(customer_id, subscription_id, mandate_id)

        with self._as_user(user.name):
            result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_customers"], 1)

        entry = next(
            (e for e in result["subscriptions"] if e.get("subscription_id") == subscription_id),
            None,
        )
        self.assertIsNotNone(entry, f"subscription {subscription_id} not in {result['subscriptions']}")
        self.assertEqual(entry["subscription"]["status"], "active")
        self.assertTrue(entry["subscription"]["is_active"])
        self.assertEqual(entry["subscription"]["amount"], 15.0)
        self.assertEqual(entry["subscription"]["currency"], "EUR")
        # A subscription can only exist behind a valid mandate, so this must be valid.
        self.assertTrue(entry["mandate_valid"])
        self.assertEqual(entry["mandate_status"], "valid")

    # --- tests: cancel_specific_subscription ---------------------------------

    def test_cancel_specific_subscription_cancels_and_clears_member(self):
        """cancel_specific_subscription cancels the real subscription and clears the
        Mollie subscription id from the Member record."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id)
        member, user = self._mollie_member(customer_id, subscription_id, mandate_id)

        with self._as_user(user.name):
            result = mollie_payment.cancel_specific_subscription(
                customer_id=customer_id, subscription_id=subscription_id
            )

        self.assertEqual(result["status"], "success")

        # Mollie now reports the subscription as canceled...
        sub = self.client.sdk_client.customers.get(customer_id).subscriptions.get(subscription_id)
        self.assertEqual(sub.status, "canceled")

        # ...and the endpoint cleared the matching subscription id off the Member.
        member.reload()
        self.assertIsNone(member.mollie_subscription_id)
        self.assertEqual(member.subscription_status, "cancelled")

    # --- tests: update_mollie_bank_account -----------------------------------

    def test_update_bank_account_switches_mandate_end_to_end(self):
        """update_mollie_bank_account creates a new mandate, PATCHes the subscription
        onto it, revokes the old mandate, and persists the new mandate on the Member."""
        customer_id = self._new_customer()
        old_mandate_id = self._new_mandate(customer_id, consumer_name="Jan Jansen")
        subscription_id = self._new_subscription(customer_id, old_mandate_id)
        member, user = self._mollie_member(customer_id, subscription_id, old_mandate_id)

        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=_TEST_IBAN, account_holder_name="Piet Pietersen"
            )

        self.assertEqual(result["status"], "success", result)
        self.assertIn("masked_iban", result)

        # The Member now carries a different (new) mandate id.
        member.reload()
        self.assertTrue(member.mollie_mandate_id)
        self.assertNotEqual(member.mollie_mandate_id, old_mandate_id)
        new_mandate_id = member.mollie_mandate_id

        customer_obj = self.client.sdk_client.customers.get(customer_id)

        # The live subscription is attached to the new mandate and still active.
        # The SDK Subscription is a Mapping: mandateId is a dict key, not an attr.
        sub = customer_obj.subscriptions.get(subscription_id)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub["mandateId"], new_mandate_id)

        # The old mandate was revoked (best-effort step 5): it is no longer among the
        # customer's valid mandates, while the new one is. (Asserting the valid set,
        # not a GET on the old id, since a revoked test mandate may be removed rather
        # than tombstoned.)
        valid_mandate_ids = [m.id for m in customer_obj.mandates.list() if m.status == "valid"]
        self.assertIn(new_mandate_id, valid_mandate_ids)
        self.assertNotIn(old_mandate_id, valid_mandate_ids)

    def test_update_bank_account_rejects_canceled_subscription(self):
        """A canceled subscription hits the 'not active' guard before any Mollie write:
        no new mandate is created and the Member's mandate id is unchanged."""
        customer_id = self._new_customer()
        mandate_id = self._new_mandate(customer_id)
        subscription_id = self._new_subscription(customer_id, mandate_id)
        # Cancel it directly via the SDK so the endpoint sees a non-active subscription.
        self.client.sdk_client.customers.get(customer_id).subscriptions.delete(subscription_id)

        member, user = self._mollie_member(customer_id, subscription_id, mandate_id)

        with self._as_user(user.name):
            result = mollie_payment.update_mollie_bank_account(
                iban=_TEST_IBAN, account_holder_name="Piet Pietersen"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("not active", result["message"].lower())

        # The guard fired before creating a mandate, so the Member is untouched.
        member.reload()
        self.assertEqual(member.mollie_mandate_id, mandate_id)
