"""
Tests for the Mollie subscription create/cancel consolidation (Phase 1).

Phase 1 collapses the two bottom-level subscription implementations onto a
single SDK path (``MollieClient``). See
``docs/plans/2026-05-18-mollie-subscription-consolidation-design.md``.

The Mollie SDK is the external boundary; it is replaced here by ``FakeSDKClient``
so tests never touch the live Mollie API. Everything below the SDK is exercised
for real.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError
from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
    CompletePaymentService,
)

# ---------------------------------------------------------------------------
# Fake Mollie SDK client
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API. It cannot be exercised in tests. This fake records the calls
# made against it so behaviour can be asserted; it mimics only the small slice
# of the SDK surface the subscription code touches.
# ---------------------------------------------------------------------------


class _Recorder:
    """Collects the SDK calls made during a test."""

    def __init__(self):
        self.customers_created = []
        self.customers_fetched = []
        self.mandates_created = []
        self.subscriptions_created = []
        self.subscriptions_deleted = []


class _FakeMandate:
    def __init__(self, mandate_id="mdt_FAKE", status="valid"):
        self.id = mandate_id
        self.status = status


class _FakeSubscription:
    def __init__(self, subscription_id="sub_FAKE", status="active",
                 next_payment_date="2026-06-01"):
        self.id = subscription_id
        self.status = status
        self.next_payment_date = next_payment_date
        self.canceled_at = None
        self.cancelled_at = None


class _FakeMandates:
    def __init__(self, recorder, raises=False):
        self._recorder = recorder
        self._raises = raises

    def create(self, data=None):
        if self._raises:
            raise RuntimeError("simulated Mollie mandate failure")
        self._recorder.mandates_created.append(data)
        return _FakeMandate()

    def list(self):
        return []


class _FakeSubscriptions:
    def __init__(self, recorder, sub_status):
        self._recorder = recorder
        self._sub_status = sub_status

    def create(self, data=None):
        self._recorder.subscriptions_created.append(data)
        return _FakeSubscription(status=self._sub_status)

    def delete(self, subscription_id):
        self._recorder.subscriptions_deleted.append(subscription_id)
        return _FakeSubscription(subscription_id=subscription_id, status="canceled")


class _FakeCustomer:
    def __init__(self, recorder, customer_id, sub_status, mandate_raises):
        self.id = customer_id
        self.mandates = _FakeMandates(recorder, raises=mandate_raises)
        self.subscriptions = _FakeSubscriptions(recorder, sub_status)


class _FakeCustomers:
    def __init__(self, recorder, sub_status, mandate_raises):
        self._recorder = recorder
        self._sub_status = sub_status
        self._mandate_raises = mandate_raises
        self._counter = 0

    def create(self, data=None):
        self._recorder.customers_created.append(data)
        self._counter += 1
        return _FakeCustomer(
            self._recorder, f"cst_FAKE{self._counter}", self._sub_status, self._mandate_raises
        )

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        return _FakeCustomer(self._recorder, customer_id, self._sub_status, self._mandate_raises)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, sub_status="active", mandate_raises=False):
        self.recorder = _Recorder()
        self.customers = _FakeCustomers(self.recorder, sub_status, mandate_raises)


class _RaisingCustomers:
    def get(self, customer_id):
        raise RuntimeError("simulated Mollie API failure")

    def create(self, data=None):
        raise RuntimeError("simulated Mollie API failure")


class RaisingSDKClient:
    """Fake SDK whose every call raises, to test error wrapping."""

    def __init__(self):
        self.customers = _RaisingCustomers()


def _make_mollie_client(sdk):
    """Build a MollieClient wired to a fake SDK (no live credentials needed)."""
    client = MollieClient(api_key="test_fake")
    client._mollie_client = sdk
    return client


def _unique_email():
    return f"mollie-consolidation-{frappe.generate_hash(length=10)}@example.com"


class TestMollieClient(EnhancedTestCase):
    """Phase 1, step 1 - MollieClient.create_mandate / cancel_subscription."""

    def test_create_mandate_wraps_sdk_customer_mandates_create(self):
        sdk = FakeSDKClient()
        client = _make_mollie_client(sdk)

        mandate_data = {
            "method": "directdebit",
            "consumerName": "Jane Doe",
            "consumerAccount": "NL39RABO0300065264",
        }
        result = client.create_mandate("cst_123", mandate_data)

        self.assertEqual(sdk.recorder.customers_fetched, ["cst_123"])
        self.assertEqual(sdk.recorder.mandates_created, [mandate_data])
        self.assertEqual(result.id, "mdt_FAKE")

    def test_create_mandate_wraps_sdk_errors_in_mollie_payment_error(self):
        client = _make_mollie_client(RaisingSDKClient())

        with self.assertRaises(MolliePaymentError):
            client.create_mandate("cst_123", {"method": "directdebit"})

    def test_cancel_subscription_wraps_sdk_errors_in_mollie_payment_error(self):
        """MollieGateway.cancel_subscription relies on cancel_subscription
        raising (rather than returning a falsy value) on SDK failure."""
        client = _make_mollie_client(RaisingSDKClient())

        with self.assertRaises(MolliePaymentError):
            client.cancel_subscription("cst_123", "sub_123")


class TestCompletePaymentServiceSubscription(EnhancedTestCase):
    """Phase 1, step 2 - CompletePaymentService.create_customer_subscription."""

    def test_create_customer_subscription_accepts_mollie_amount_dict_no_mandate(self):
        """A {"value","currency"} amount (the shape Mollie's API requires) must
        validate, and without an IBAN no mandate is provisioned."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        result = service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_status"], "active")
        self.assertEqual(sdk.recorder.mandates_created, [])
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)

    def test_create_customer_subscription_strips_falsy_consumer_account(self):
        """A falsy consumerAccount (e.g. a member without an IBAN) provisions
        no mandate and must still be stripped from the subscription payload -
        Mollie's subscription API rejects an unknown consumerAccount key."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": None,
            },
        )

        self.assertEqual(sdk.recorder.mandates_created, [])
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)
        self.assertNotIn("consumerAccount", sdk.recorder.subscriptions_created[0])

    def test_create_customer_subscription_provisions_mandate_from_consumer_account(self):
        """When a consumerAccount (IBAN) is supplied, a SEPA mandate is
        provisioned before the subscription and consumerAccount is stripped."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        result = service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": "NL39RABO0300065264",
            },
        )

        self.assertEqual(result["status"], "success")

        self.assertEqual(len(sdk.recorder.mandates_created), 1)
        mandate = sdk.recorder.mandates_created[0]
        self.assertEqual(mandate["method"], "directdebit")
        self.assertEqual(mandate["consumerName"], "Jane Doe")
        self.assertEqual(mandate["consumerAccount"], "NL39RABO0300065264")
        self.assertIn("signatureDate", mandate)
        self.assertIn("mandateReference", mandate)

        # consumerAccount is mandate-only; it must not leak into the
        # subscription create payload (Mollie's API rejects it there).
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)
        self.assertNotIn("consumerAccount", sdk.recorder.subscriptions_created[0])

    def test_create_customer_subscription_propagates_mandate_failure(self):
        """If mandate provisioning fails, the original mandate error must
        surface (not be relabelled "Failed to create subscription"), and the
        subscription must not be attempted."""
        sdk = FakeSDKClient(mandate_raises=True)
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        with self.assertRaises(MolliePaymentError) as ctx:
            service.create_customer_subscription(
                {"name": "Jane Doe", "email": _unique_email()},
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                    "consumerAccount": "NL39RABO0300065264",
                },
            )

        message = str(ctx.exception)
        self.assertIn("mandate", message)
        self.assertNotIn("Failed to create subscription", message)
        self.assertEqual(sdk.recorder.subscriptions_created, [])


# Patch target for the Mollie SDK boundary: every code path under test
# ultimately gets its SDK client from MollieSettings.get_mollie_client().
_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
# MollieClient.__init__ reads the API key directly (a separate path from
# get_mollie_client), so it is patched too - keeps the tests independent of
# whatever Mollie credentials happen to be configured on the test site.
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"


def _patch_sdk(sdk):
    """Context manager that routes every Mollie SDK access to ``sdk``."""
    return _MultiPatch(
        patch(_GET_MOLLIE_CLIENT, return_value=sdk),
        patch(_GET_API_KEY, return_value="test_fake"),
    )


class _MultiPatch:
    """Apply several patch() context managers as one."""

    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


class TestMollieGatewaySubscription(EnhancedTestCase):
    """Phase 1, steps 3-4 - MollieGateway.create_subscription / cancel_subscription.

    These exercise the gateway end-to-end against a fake Mollie SDK. They are
    characterization tests: confirmed green against the legacy MollieSettings
    path before the Phase 1 refactor, and required to stay green after it.
    """

    def _make_member(self, **kwargs):
        token = frappe.generate_hash(length=8)
        return self.create_test_member(
            first_name="Mollie",
            last_name=f"Subscriber{token}",
            email=f"mollie-gw-{token}@example.com",
            birth_date="1990-01-01",
            **kwargs,
        )

    def test_create_subscription_without_iban_provisions_no_mandate(self):
        member = self._make_member()
        sdk = FakeSDKClient()

        with _patch_sdk(sdk):
            from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

            gateway = MollieGateway()
            result = gateway.create_subscription(
                member, {"amount": 15.0, "interval": "1 month"}
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_status"], "active")
        self.assertEqual(sdk.recorder.mandates_created, [])
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_FAKE"
        )
        # Customer metadata must reach Mollie (legacy parity - the old path
        # passed the whole customer_data dict, including metadata, to the SDK).
        self.assertEqual(
            sdk.recorder.customers_created[0]["metadata"]["member_id"], member.name
        )

    def test_create_subscription_with_iban_provisions_mandate(self):
        member = self._make_member()
        frappe.db.set_value(
            "Member", member.name, "iban", "NL39RABO0300065264", update_modified=False
        )
        member.reload()
        sdk = FakeSDKClient()

        with _patch_sdk(sdk):
            from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

            gateway = MollieGateway()
            result = gateway.create_subscription(
                member, {"amount": 15.0, "interval": "1 month"}
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(sdk.recorder.mandates_created), 1)
        self.assertEqual(
            sdk.recorder.mandates_created[0]["consumerAccount"], "NL39RABO0300065264"
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )

    def test_cancel_subscription_cancels_at_mollie_and_updates_member(self):
        member = self._make_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_LIVE", "mollie_subscription_id": "sub_LIVE"},
            update_modified=False,
        )
        member.reload()
        sdk = FakeSDKClient()

        with _patch_sdk(sdk):
            from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

            gateway = MollieGateway()
            result = gateway.cancel_subscription(member)

        self.assertEqual(result["status"], "success")
        self.assertEqual(sdk.recorder.subscriptions_deleted, ["sub_LIVE"])
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "canceled"
        )

    def test_create_subscription_failure_returns_error_and_leaves_member_untouched(self):
        member = self._make_member()

        with _patch_sdk(RaisingSDKClient()):
            from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

            gateway = MollieGateway()
            result = gateway.create_subscription(
                member, {"amount": 15.0, "interval": "1 month"}
            )

        self.assertEqual(result["status"], "error")
        self.assertFalse(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id")
        )
        self.assertFalse(
            frappe.db.get_value("Member", member.name, "subscription_status")
        )

    def test_cancel_subscription_failure_returns_error_and_leaves_member_untouched(self):
        member = self._make_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "mollie_customer_id": "cst_LIVE",
                "mollie_subscription_id": "sub_LIVE",
                "subscription_status": "active",
            },
            update_modified=False,
        )
        member.reload()

        with _patch_sdk(RaisingSDKClient()):
            from verenigingen.verenigingen_payments.utils.payment_gateways import MollieGateway

            gateway = MollieGateway()
            result = gateway.cancel_subscription(member)

        self.assertEqual(result["status"], "error")
        # The cancel failed at Mollie, so the member status must NOT flip.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )
