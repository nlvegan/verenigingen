"""
Regression test for the broken Mollie amendment-subscription sync.

``MollieSubscriptionSyncService.sync_subscription_for_amendment`` called
``MollieClient.create_subscription`` with keyword arguments (``amount=``,
``interval=``, ``webhook_url=``, ``start_date=`` …) that did not match its
``(customer_id, subscription_data)`` signature, so every amendment-triggered
sync raised ``TypeError``. The create call now goes through
``_create_replacement_subscription``, covered here.

The Mollie SDK is the external boundary; it is replaced by a fake so the test
never touches the live Mollie API.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
    MollieSubscriptionSyncService,
)


# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API and cannot run in tests. This fake records the subscription
# payload so the call shape can be asserted.
class _FakeSubscription:
    def __init__(self, subscription_id="sub_FAKE"):
        self.id = subscription_id
        self.status = "active"
        self.next_payment_date = "2026-07-01"


class _FakeSubscriptions:
    def __init__(self, recorder):
        self._recorder = recorder

    def create(self, data=None):
        self._recorder.append(data)
        return _FakeSubscription()


class _FakeCustomer:
    def __init__(self, recorder):
        self.subscriptions = _FakeSubscriptions(recorder)


class _FakeCustomers:
    def __init__(self, recorder):
        self._recorder = recorder
        self.fetched = []

    def get(self, customer_id):
        self.fetched.append(customer_id)
        return _FakeCustomer(self._recorder)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self):
        self.subscriptions_created = []
        self.customers = _FakeCustomers(self.subscriptions_created)


def _make_mollie_client(sdk):
    """Build a MollieClient wired to a fake SDK (no live credentials needed)."""
    client = MollieClient(api_key="test_fake")
    client._mollie_client = sdk
    return client


class TestAmendmentSubscriptionSync(EnhancedTestCase):
    """Regression coverage for the amendment-sync subscription-create call."""

    def _make_member(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Sync",
            last_name=f"Member{token}",
            email=f"sync-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_SYNC", update_modified=False
        )
        member.reload()
        return member

    def test_create_replacement_subscription_passes_subscription_data_dict(self):
        sdk = FakeSDKClient()
        member = self._make_member()
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service._create_replacement_subscription(
            member=member,
            amount=17.5,
            interval="3 months",
            start_date="2026-07-01",
            amendment_name="AMEND-TEST-001",
            previous_subscription_id="sub_OLD",
        )

        self.assertEqual(sdk.customers.fetched, ["cst_SYNC"])
        self.assertEqual(len(sdk.subscriptions_created), 1)
        payload = sdk.subscriptions_created[0]
        self.assertEqual(payload["amount"], {"value": "17.50", "currency": "EUR"})
        self.assertEqual(payload["interval"], "3 months")
        self.assertEqual(payload["startDate"], "2026-07-01")
        self.assertEqual(payload["metadata"]["member_id"], member.name)
        self.assertEqual(payload["metadata"]["amendment_id"], "AMEND-TEST-001")
        self.assertEqual(payload["metadata"]["previous_subscription_id"], "sub_OLD")
        self.assertEqual(payload["metadata"]["subscription_type"], "membership_dues")
        self.assertEqual(result.id, "sub_FAKE")

    def test_create_replacement_subscription_omits_start_date_when_absent(self):
        sdk = FakeSDKClient()
        member = self._make_member()
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        service._create_replacement_subscription(
            member=member,
            amount=10.0,
            interval="1 month",
            start_date=None,
            amendment_name="AMEND-TEST-002",
            previous_subscription_id="sub_OLD",
        )

        self.assertNotIn("startDate", sdk.subscriptions_created[0])
