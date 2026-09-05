"""
Live coverage for SubscriptionService.cancel_subscription()'s member/donor
bookkeeping, against Mollie's REAL test API.

Why this file and not another entry in test_subscription_service_live.py
-------------------------------------------------------------------------
That file's `test_admin_cancel_subscription_live` exercises
`admin_cancel_subscription()` -- but that method's own docstring says it is
"distinct from `cancel_subscription` (which derives member/donor updates from
Mollie metadata)" and that admin-cancel callers "own any local record
updates". So nothing in this repo's live suite ever drove Mollie's real
`DELETE subscription` through `cancel_subscription()` (subscription_service.py:83)
-- the metadata-driven path #290 names explicitly:
"including the member/donor bookkeeping in `_update_member_subscription_canceled`
/ `_update_donor_subscription_canceled`".

What this proves, precisely
----------------------------
A real Mollie subscription, carrying metadata that names a real Member or
Donor, is genuinely cancelled through `SubscriptionService.cancel_subscription()`
-- confirmed both by the method's own return value and, independently, by
reading the subscription back from Mollie afterwards
(`get_subscription_status` / `is_canceled`). That is the e2e claim #290 asks
for: a real recurring payment (here, its governing subscription) is cancelled
against Mollie's live test API, not a mock.

What is NOT proven -- a documented existing bug, not a gap in this test
-------------------------------------------------------------------------
`_update_member_subscription_canceled` sets `member.subscription_cancel_reason`
and `member.subscription_canceled_at`. Neither is a declared field on Member
(verified 2026-09-05 on test_site_8 via
`frappe.get_meta("Member").has_field(...)` -> False for both; `subscription_status`
-> True). Frappe silently drops an assignment to an undeclared field on
`.save()`, so only `subscription_status` actually persists.
`_update_donor_subscription_canceled` is worse: Donor has NONE of
`subscription_status` / `subscription_cancel_reason` / `subscription_canceled_at`
declared (same verification), so that whole method is a no-op beyond bumping
`modified`. Fixing either requires either renaming the Member call site to the
field that already exists (`subscription_cancelled_date`) or adding fields to
both doctypes -- a schema change out of scope for a test-only branch. Filed as
#873 rather than fixed here, per this branch's own "new test files only"
territory.

Gating / hygiene: identical to test_subscription_service_live.py -- every test
skips cleanly without a configured `mollie_test_secret_key` (e.g. plain CI).
Every Mollie customer created is tracked and torn down (subscriptions
cancelled, customers deleted) best-effort in tearDown.
"""

from datetime import datetime, timezone

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.services.subscription_service import SubscriptionService
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import ensure_mollie_test_credentials

# Mollie-accepted test IBAN that yields an immediately-valid SEPA direct-debit mandate.
_TEST_IBAN = "NL39RABO0300065264"


class TestSubscriptionCancelBookkeepingLive(EnhancedTestCase):
    """cancel_subscription()'s member/donor bookkeeping against the real Mollie test API."""

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

    def _new_customer(self, name):
        token = frappe.generate_hash(length=8)
        customer = self.client.sdk_client.customers.create(
            {"name": name, "email": f"bookkeeping-cancel-{token}@example.org"}
        )
        self._customer_ids.append(customer.id)
        return customer.id

    def _new_subscription_with_metadata(self, customer_id, metadata, value="10.00"):
        customer_obj = self.client.sdk_client.customers.get(customer_id)
        mandate = customer_obj.mandates.create(
            {
                "method": "directdebit",
                "consumerName": "Jan Jansen",
                "consumerAccount": _TEST_IBAN,
                # UTC date: site-local today() can be a day ahead of Mollie's clock
                # (e.g. on an Asia/Kolkata test site) and Mollie 422s a future date.
                "signatureDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )
        sub = customer_obj.subscriptions.create(
            {
                "amount": {"currency": "EUR", "value": value},
                "interval": "1 month",
                "description": "Live bookkeeping-cancel subscription",
                "mandateId": mandate.id,
                "metadata": metadata,
            }
        )
        return sub.id

    # --- tests ---------------------------------------------------------------

    def test_cancel_subscription_membership_dues_cancels_at_mollie_and_updates_member(self):
        """cancel_subscription() with membership_dues metadata: Mollie really
        cancels the subscription, and the one Member field that actually
        persists (subscription_status) reflects it."""
        member = self.create_test_member(first_name="MollieCancel", last_name="BookkeepingLive")
        customer_id = self._new_customer("Bookkeeping Cancel Member")
        subscription_id = self._new_subscription_with_metadata(
            customer_id,
            {"subscription_type": "membership_dues", "member_id": member.name},
        )

        result = self.service.cancel_subscription(
            customer_id, subscription_id, reason="live bookkeeping test cancellation"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], subscription_id)

        # Independent proof: Mollie itself now reports the subscription cancelled,
        # read back fresh rather than trusting the call's own return value.
        status = self.service.get_subscription_status(customer_id, subscription_id)
        self.assertTrue(status["is_canceled"])

        # The one piece of the local bookkeeping that actually persists today.
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")

        # Documented existing bug (see module docstring and #873):
        # subscription_cancel_reason and subscription_canceled_at are not
        # declared Member fields, so Document.save() drops both assignments
        # silently. Asserted here (rather than left unchecked) so a future
        # half-fix doesn't silently regress this test's understanding of what
        # is actually persisted.
        self.assertIsNone(getattr(member, "subscription_cancel_reason", None))
        self.assertIsNone(getattr(member, "subscription_canceled_at", None))

    def test_cancel_subscription_recurring_donation_cancels_at_mollie(self):
        """cancel_subscription() with recurring_donation metadata against a real
        Donor: Mollie really cancels the subscription. The Donor-side bookkeeping
        call (_update_donor_subscription_canceled) is a documented no-op today --
        Donor declares none of the three fields it tries to set -- see module
        docstring; asserting against them here would assert against fields that
        do not exist."""
        donor = self.create_test_donor(
            donor_name="Bookkeeping Cancel Donor",
            donor_email=f"bookkeeping-cancel-donor-{frappe.generate_hash(length=8)}@example.org",
            donor_type="Individual",
        )

        customer_id = self._new_customer("Bookkeeping Cancel Donor")
        subscription_id = self._new_subscription_with_metadata(
            customer_id,
            {"subscription_type": "recurring_donation", "donor_id": donor.name},
        )

        result = self.service.cancel_subscription(
            customer_id, subscription_id, reason="live bookkeeping test cancellation"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], subscription_id)

        status = self.service.get_subscription_status(customer_id, subscription_id)
        self.assertTrue(status["is_canceled"])
