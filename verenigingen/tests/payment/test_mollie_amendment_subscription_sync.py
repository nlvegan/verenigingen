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
from verenigingen.verenigingen_payments.mollie.services.subscription_description import (
    get_member_subscription_description,
)


# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API and cannot run in tests. This fake records the subscription
# payload so the call shape can be asserted.
class _FakeSubscription:
    def __init__(
        self,
        subscription_id="sub_FAKE",
        status="active",
        amount=None,
        interval="1 month",
        description="",
        webhook_url="",
        mandate_id=None,
        next_payment_date="2026-07-01",
        customer_id=None,
    ):
        self.id = subscription_id
        self.status = status
        self.amount = amount or {"value": "25.50", "currency": "EUR"}
        self.interval = interval
        self.description = description
        self.webhook_url = webhook_url
        self.mandate_id = mandate_id
        self.next_payment_date = next_payment_date
        self.customer_id = customer_id
        self.metadata = {}


# Exercised by the replacement-path mandate validation (amount-PATCH sync tests).
class _FakeMandate:
    def __init__(self, mandate_id="mdt_FAKE", status="valid"):
        self.id = mandate_id
        self.status = status


class _FakeMandates:
    def get(self, mandate_id):
        return _FakeMandate(mandate_id=mandate_id)


class _FakeSubscriptions:
    def __init__(self, sdk):
        self._sdk = sdk

    def create(self, data=None):
        self._sdk.subscriptions_created.append(data)
        return _FakeSubscription(mandate_id=(data or {}).get("mandateId"))

    def get(self, subscription_id):
        live = self._sdk.live_subscription
        return _FakeSubscription(
            subscription_id=subscription_id,
            status=live.status,
            amount=live.amount,
            interval=live.interval,
            description=live.description,
            webhook_url=live.webhook_url,
            mandate_id=live.mandate_id,
            next_payment_date=live.next_payment_date,
        )

    def update(self, subscription_id, data=None):
        self._sdk.subscriptions_updated.append((subscription_id, data))
        live = self._sdk.live_subscription
        data = data or {}
        return _FakeSubscription(
            subscription_id=subscription_id,
            status=live.status,
            amount=data.get("amount", live.amount),
            interval=data.get("interval", live.interval),
            description=data.get("description", live.description),
            webhook_url=data.get("webhookUrl", live.webhook_url),
            mandate_id=data.get("mandateId", live.mandate_id),
            next_payment_date=data.get("startDate", live.next_payment_date),
        )

    def delete(self, subscription_id):
        self._sdk.subscriptions_deleted.append(subscription_id)
        return _FakeSubscription(subscription_id=subscription_id, status="canceled")


class _FakeCustomer:
    def __init__(self, sdk):
        self.subscriptions = _FakeSubscriptions(sdk)
        self.mandates = _FakeMandates()


class _FakeCustomers:
    def __init__(self, sdk):
        self._sdk = sdk
        self.fetched = []

    def get(self, customer_id):
        self.fetched.append(customer_id)
        return _FakeCustomer(self._sdk)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, live_subscription=None):
        self.subscriptions_created = []
        self.subscriptions_updated = []
        self.subscriptions_deleted = []
        self.live_subscription = live_subscription or _FakeSubscription()
        self.customers = _FakeCustomers(self)


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

    def test_client_update_subscription_patches_via_sdk(self):
        sdk = FakeSDKClient()
        client = _make_mollie_client(sdk)

        result = client.update_subscription(
            "cst_SYNC", "sub_LIVE", {"amount": {"value": "26.50", "currency": "EUR"}}
        )

        self.assertEqual(sdk.customers.fetched, ["cst_SYNC"])
        self.assertEqual(
            sdk.subscriptions_updated,
            [("sub_LIVE", {"amount": {"value": "26.50", "currency": "EUR"}})],
        )
        self.assertEqual(result.amount, {"value": "26.50", "currency": "EUR"})

    def test_get_subscription_status_exposes_webhook_and_mandate(self):
        from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
            SubscriptionService,
        )

        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                webhook_url="https://old.example/hook", mandate_id="mdt_LIVE"
            )
        )
        service = SubscriptionService(_make_mollie_client(sdk))

        status = service.get_subscription_status("cst_SYNC", "sub_LIVE")

        self.assertEqual(status["webhook_url"], "https://old.example/hook")
        self.assertEqual(status["mandate_id"], "mdt_LIVE")


class TestSubscriptionDescription(EnhancedTestCase):
    """Canonical member-subscription description from Verenigingen Payments Settings."""

    def setUp(self):
        super().setUp()
        original = frappe.db.get_single_value(
            "Verenigingen Payments Settings", "mollie_subscription_description_template"
        )
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Payments Settings",
            "mollie_subscription_description_template",
            original or "",
        )

    def _member(self):
        token = frappe.generate_hash(length=8)
        return self.create_test_member(
            first_name="Desc",
            last_name=f"Helper{token}",
            email=f"desc-{token}@example.com",
            birth_date="1990-01-01",
        )

    def test_description_uses_default_template(self):
        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "mollie_subscription_description_template", ""
        )
        member = self._member()
        self.assertEqual(
            get_member_subscription_description(member),
            f"Contribution payment for member {member.member_id}",
        )

    def test_description_substitutes_custom_template(self):
        frappe.db.set_single_value(
            "Verenigingen Payments Settings",
            "mollie_subscription_description_template",
            "Dues MEMBER_NAME (MEMBER_ID)",
        )
        member = self._member()
        self.assertEqual(
            get_member_subscription_description(member),
            f"Dues {member.full_name} ({member.member_id})",
        )
