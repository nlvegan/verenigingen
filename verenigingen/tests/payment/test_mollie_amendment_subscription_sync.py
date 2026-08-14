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


class TestAmendmentSyncPatchPath(EnhancedTestCase):
    """Amount-only amendments PATCH the live subscription; drifted
    description/webhookUrl are repaired in the same call."""

    def _member_with_subscription(self, mandate_id=None):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Patch",
            last_name=f"Sync{token}",
            email=f"patch-{token}@example.com",
            birth_date="1990-01-01",
        )
        values = {
            "mollie_customer_id": "cst_SYNC",
            "mollie_subscription_id": "sub_LIVE",
        }
        if mandate_id:
            values["mollie_mandate_id"] = mandate_id
        frappe.db.set_value("Member", member.name, values, update_modified=False)
        member.reload()
        membership = self.create_test_membership(member_name=member.name)
        # Membership.after_insert creates an ANNUAL dues schedule, while every fake
        # live subscription in this class is "1 month". That combination is not
        # amount-only: the service correctly cancels and replaces on an interval
        # change, so these tests would assert the wrong path. They only ever passed
        # because _get_membership_dues_schedule filtered on docstatus=1 and returned
        # None, pinning the interval to "1 month" by accident. Align the fixture so
        # an amount-only amendment really is amount-only.
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": ["in", ["Active", "Scheduled"]]},
            pluck="name",
        ):
            frappe.db.set_value(
                "Membership Dues Schedule", name, "billing_frequency", "Monthly", update_modified=False
            )
        return member, membership

    def _fee_change_amendment(self, membership, member, amount=26.5):
        return frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": amount,
                "status": "Applied",
            }
        )

    def _canonical_pair(self, member):
        settings = frappe.get_single("Mollie Settings")
        return get_member_subscription_description(member), settings.get_subscription_webhook_url()

    def test_amount_only_amendment_patches_without_replacing(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()  # NO mandate id: gate must not skip
        canonical_desc, canonical_hook = self._canonical_pair(member)
        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                interval="1 month",
                description=canonical_desc,
                webhook_url=canonical_hook,
                mandate_id="mdt_LIVE",
            )
        )
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_LIVE")
        # PATCH happened; nothing was created or canceled.
        self.assertEqual(len(sdk.subscriptions_updated), 1)
        self.assertEqual(sdk.subscriptions_created, [])
        self.assertEqual(sdk.subscriptions_deleted, [])
        sub_id, payload = sdk.subscriptions_updated[0]
        self.assertEqual(sub_id, "sub_LIVE")
        # No drift -> amount is the only key.
        self.assertEqual(payload, {"amount": {"value": "26.50", "currency": "EUR"}})
        # Member keeps the same subscription id.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_LIVE"
        )

    def test_patch_repairs_drifted_description_and_webhook(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()
        canonical_desc, canonical_hook = self._canonical_pair(member)
        sdk = FakeSDKClient(
            live_subscription=_FakeSubscription(
                interval="1 month",
                description="Membership dues - Stale Format",
                webhook_url="https://dev.veganisme.net/api/method/old.path?env=test",
                mandate_id="mdt_LIVE",
            )
        )
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "success")
        _, payload = sdk.subscriptions_updated[0]
        self.assertEqual(payload["description"], canonical_desc)
        self.assertEqual(payload["webhookUrl"], canonical_hook)

    def test_interval_change_takes_replacement_path(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription(mandate_id="mdt_LIVE")
        # Live interval differs from the computed "1 month" -> replacement.
        sdk = FakeSDKClient(live_subscription=_FakeSubscription(interval="3 months"))
        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        # Replacement created a new subscription and never PATCHed.
        self.assertEqual(len(sdk.subscriptions_created), 1)
        self.assertEqual(sdk.subscriptions_updated, [])
        self.assertIn(result["status"], ("success", "warning"))

    def test_patch_amount_mismatch_returns_warning(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription()
        canonical_desc, canonical_hook = self._canonical_pair(member)
        live = _FakeSubscription(
            interval="1 month",
            description=canonical_desc,
            webhook_url=canonical_hook,
        )
        sdk = FakeSDKClient(live_subscription=live)

        # Make the fake's update() echo a WRONG amount back.
        class _WrongAmountSubscriptions(_FakeSubscriptions):
            def update(self, subscription_id, data=None):
                self._sdk.subscriptions_updated.append((subscription_id, data))
                return _FakeSubscription(
                    subscription_id=subscription_id,
                    amount={"value": "99.99", "currency": "EUR"},
                    interval="1 month",
                )

        class _WrongAmountCustomer(_FakeCustomer):
            def __init__(self, sdk):
                super().__init__(sdk)
                self.subscriptions = _WrongAmountSubscriptions(sdk)

        sdk.customers.get = lambda cid: _WrongAmountCustomer(sdk)

        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))
        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["requires_admin_review"])

    def test_member_without_subscription_id_is_skipped(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="NoSub",
            last_name=f"Sync{token}",
            email=f"nosub-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_SYNC", update_modified=False
        )
        member.reload()
        membership = self.create_test_membership(member_name=member.name)
        service = MollieSubscriptionSyncService(client=_make_mollie_client(FakeSDKClient()))

        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_mollie_subscription")

    def test_replacement_mandate_resolves_from_subscription_first(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        service = MollieSubscriptionSyncService(client=_make_mollie_client(FakeSDKClient()))
        member = frappe._dict(mollie_mandate_id="mdt_FIELD")

        self.assertEqual(
            service._mandate_id_for_replacement(member, {"mandate_id": "mdt_SUB"}), "mdt_SUB"
        )
        self.assertEqual(
            service._mandate_id_for_replacement(member, {"mandate_id": None}), "mdt_FIELD"
        )

    def test_replacement_blocked_when_mandate_invalid(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription(mandate_id="mdt_LIVE")
        # Interval differs -> replacement path; mandate comes back revoked.
        sdk = FakeSDKClient(live_subscription=_FakeSubscription(interval="3 months"))

        class _RevokedMandates(_FakeMandates):
            def get(self, mandate_id):
                return _FakeMandate(mandate_id=mandate_id, status="revoked")

        class _RevokedCustomer(_FakeCustomer):
            def __init__(self, inner_sdk):
                super().__init__(inner_sdk)
                self.mandates = _RevokedMandates()

        sdk.customers.get = lambda cid: _RevokedCustomer(sdk)

        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))
        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "invalid_mandate")
        self.assertTrue(result["requires_admin_review"])
        self.assertEqual(sdk.subscriptions_created, [])

    def test_replacement_blocked_when_mandate_lookup_fails(self):
        from verenigingen.verenigingen_payments.mollie.services.mollie_subscription_sync_service import (
            MollieSubscriptionSyncService,
        )

        member, membership = self._member_with_subscription(mandate_id="mdt_LIVE")
        sdk = FakeSDKClient(live_subscription=_FakeSubscription(interval="3 months"))

        class _BrokenMandates(_FakeMandates):
            def get(self, mandate_id):
                raise RuntimeError("simulated mandate lookup failure")

        class _BrokenCustomer(_FakeCustomer):
            def __init__(self, inner_sdk):
                super().__init__(inner_sdk)
                self.mandates = _BrokenMandates()

        sdk.customers.get = lambda cid: _BrokenCustomer(sdk)

        service = MollieSubscriptionSyncService(client=_make_mollie_client(sdk))
        result = service.sync_subscription_for_amendment(
            self._fee_change_amendment(membership, member)
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "mandate_validation_failed")
        self.assertTrue(result["requires_admin_review"])
        self.assertEqual(sdk.subscriptions_created, [])


class TestGatewayDescriptionDefault(EnhancedTestCase):
    """MollieGateway.create_subscription defaults the description to the
    canonical helper output instead of a hardcoded format."""

    def test_gateway_defaults_description_to_canonical_helper(self):
        from unittest.mock import MagicMock, patch

        from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Gateway",
            last_name=f"Desc{token}",
            email=f"gateway-{token}@example.com",
            birth_date="1990-01-01",
        )

        captured = {}

        def _fake_create_customer_subscription(customer_data, subscription_data):
            captured["subscription_data"] = subscription_data
            return {
                "status": "success",
                "customer_id": "cst_CAP",
                "subscription_id": "sub_CAP",
                "subscription_status": "active",
            }

        # CompletePaymentService() __init__ calls MollieClient() which loads live
        # credentials — skip it by patching the whole class with a MagicMock whose
        # create_customer_subscription captures the payload we want to assert on.
        fake_service_instance = MagicMock()
        fake_service_instance.create_customer_subscription.side_effect = (
            _fake_create_customer_subscription
        )
        fake_service_class = MagicMock(return_value=fake_service_instance)

        gateway = MollieGateway.__new__(MollieGateway)  # skip __init__ (loads live settings)
        with patch(
            "verenigingen.verenigingen_payments.utils.payment_gateways.CompletePaymentService",
            fake_service_class,
        ):
            gateway.settings = MagicMock()
            gateway.settings.enable_subscriptions = True
            gateway.settings.get_subscription_webhook_url.return_value = "https://x.example/hook"
            gateway.create_subscription(member, {"amount": 15.0, "interval": "1 month"})

        self.assertEqual(
            captured["subscription_data"]["description"],
            get_member_subscription_description(member),
        )


class TestSyncResultStatusMapping(EnhancedTestCase):
    """Every sync outcome maps to a visible mollie_sync_status."""

    def test_status_mapping(self):
        from verenigingen.verenigingen_payments.mollie.events.amendment_events import (
            _sync_status_update_for_result,
        )

        self.assertEqual(
            _sync_status_update_for_result({"status": "success"}), ("Completed", 1, False)
        )
        self.assertEqual(
            _sync_status_update_for_result({"status": "skipped", "reason": "x"}),
            ("Skipped", 0, False),
        )
        self.assertEqual(
            _sync_status_update_for_result(
                {"status": "warning", "requires_admin_review": True}
            ),
            ("Needs Review", 0, True),
        )
        # error notifies admins even without the explicit review flag
        self.assertEqual(
            _sync_status_update_for_result({"status": "error"}), ("Failed", 0, True)
        )
        # warning without the review flag: visible status, no notification
        self.assertEqual(
            _sync_status_update_for_result({"status": "warning"}),
            ("Needs Review", 0, False),
        )


class TestStuckAmendmentPartition(EnhancedTestCase):
    """Repair patch re-syncs only the latest stuck amendment per member."""

    def test_partition_keeps_latest_per_member(self):
        from verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs import (
            partition_stuck_amendments,
        )

        rows = [  # already in ascending creation order, as execute() queries
            frappe._dict(name="AMEND-1", member="M-A"),
            frappe._dict(name="AMEND-2", member="M-B"),
            frappe._dict(name="AMEND-3", member="M-A"),
        ]

        resync, skip = partition_stuck_amendments(rows)

        self.assertEqual(sorted(resync), ["AMEND-2", "AMEND-3"])
        self.assertEqual(skip, ["AMEND-1"])

    def test_partition_empty(self):
        from verenigingen.patches.v2_2.resync_stuck_mollie_amendment_syncs import (
            partition_stuck_amendments,
        )

        self.assertEqual(partition_stuck_amendments([]), ([], []))
