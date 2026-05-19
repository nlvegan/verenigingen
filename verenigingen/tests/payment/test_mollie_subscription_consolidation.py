"""
Tests for the Mollie subscription create/cancel consolidation (Phases 1-3).

Phase 1 collapses the two bottom-level subscription implementations onto a
single SDK path (``MollieClient``); Phase 2 standardises the mid-level
create/cancel contract; Phase 3 routes the ``MollieDebugService`` admin
tooling through ``MollieClient`` so it can no longer reach the raw SDK. See
``docs/plans/2026-05-18-mollie-subscription-consolidation-design.md``.

The Mollie SDK is the external boundary; it is replaced here by ``FakeSDKClient``
so tests never touch the live Mollie API. Everything below the SDK is exercised
for real.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.exceptions import (
    MolliePaymentError,
    MollieValidationError,
)
from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
    CompletePaymentService,
)
from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
    SubscriptionService,
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
    def __init__(self, mandate_id="mdt_FAKE", status="valid", method="directdebit",
                 consumer_account=None):
        self.id = mandate_id
        self.status = status
        self.method = method
        # Mollie returns directdebit mandate bank details under `details`.
        self.details = {"consumerAccount": consumer_account} if consumer_account else {}


# Mollie paginates list endpoints at 50/page; a small page size here keeps
# the pagination tests legible (3 mandates already span two pages).
_FAKE_MANDATE_PAGE_SIZE = 2


class _FakePaginationList:
    """Stand-in for Mollie's ``PaginationList``: iterating yields only the
    *current* page, and ``get_next()`` returns the following page (or None).

    This deliberately mirrors the real SDK's non-auto-paginating behaviour so
    ``MollieClient.list_mandates`` is exercised against it - a plain list
    would silently hide the need to walk pages.
    """

    def __init__(self, items, page_size=_FAKE_MANDATE_PAGE_SIZE):
        self._items = list(items)
        self._page_size = page_size

    def __iter__(self):
        return iter(self._items[: self._page_size])

    def get_next(self):
        rest = self._items[self._page_size:]
        return _FakePaginationList(rest, self._page_size) if rest else None


class _FakeSubscription:
    def __init__(self, subscription_id="sub_FAKE", status="active",
                 next_payment_date="2026-06-01"):
        self.id = subscription_id
        self.status = status
        self.next_payment_date = next_payment_date
        self.canceled_at = None
        self.cancelled_at = None
        self.metadata = {}
        # The MollieDebugService success responses read these fields directly
        # (not via getattr), so the fake must carry them.
        self.amount = {"value": "15.00", "currency": "EUR"}
        self.interval = "1 month"
        self.description = "Fake subscription"


class _FakeMandates:
    def __init__(self, recorder, raises=False, existing=None, list_raises=False):
        self._recorder = recorder
        self._raises = raises
        self._existing = existing or []
        self._list_raises = list_raises

    def create(self, data=None):
        if self._raises:
            raise RuntimeError("simulated Mollie mandate failure")
        self._recorder.mandates_created.append(data)
        return _FakeMandate()

    def list(self):
        if self._list_raises:
            raise RuntimeError("simulated Mollie mandate list failure")
        # Return a paginating list, as the real SDK does, so list_mandates
        # has to walk pages rather than trust the first one.
        return _FakePaginationList(self._existing)


class _FakeSubscriptions:
    def __init__(self, recorder, sub_status):
        self._recorder = recorder
        self._sub_status = sub_status

    def create(self, data=None):
        self._recorder.subscriptions_created.append(data)
        return _FakeSubscription(status=self._sub_status)

    def get(self, subscription_id):
        return _FakeSubscription(subscription_id=subscription_id, status=self._sub_status)

    def delete(self, subscription_id):
        self._recorder.subscriptions_deleted.append(subscription_id)
        return _FakeSubscription(subscription_id=subscription_id, status="canceled")


class _FakeCustomer:
    def __init__(self, recorder, customer_id, sub_status, mandate_raises,
                 existing_mandates, mandate_list_raises):
        self.id = customer_id
        self.mandates = _FakeMandates(
            recorder, raises=mandate_raises, existing=existing_mandates,
            list_raises=mandate_list_raises,
        )
        self.subscriptions = _FakeSubscriptions(recorder, sub_status)


class _FakeCustomers:
    def __init__(self, recorder, sub_status, mandate_raises, stale_customer_id,
                 existing_mandates, mandate_list_raises):
        self._recorder = recorder
        self._sub_status = sub_status
        self._mandate_raises = mandate_raises
        self._stale_customer_id = stale_customer_id
        self._existing_mandates = existing_mandates
        self._mandate_list_raises = mandate_list_raises
        self._counter = 0

    def _build(self, customer_id):
        # Caveat: every customer this fake builds - including freshly
        # created()d ones - carries the same existing_mandates. A real new
        # Mollie customer has none. Tests here only ever resolve one
        # customer, so this is harmless; a future multi-customer test must
        # not rely on a created customer starting mandate-free.
        return _FakeCustomer(
            self._recorder, customer_id, self._sub_status, self._mandate_raises,
            self._existing_mandates, self._mandate_list_raises,
        )

    def create(self, data=None):
        self._recorder.customers_created.append(data)
        self._counter += 1
        return self._build(f"cst_FAKE{self._counter}")

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        # Only the designated "stale" id fails to resolve; freshly-created
        # customers (and every other id) resolve normally.
        if self._stale_customer_id and customer_id == self._stale_customer_id:
            raise RuntimeError("simulated stale/unknown Mollie customer")
        return self._build(customer_id)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, sub_status="active", mandate_raises=False, stale_customer_id=None,
                 existing_mandates=None, mandate_list_raises=False):
        self.recorder = _Recorder()
        self.customers = _FakeCustomers(
            self.recorder, sub_status, mandate_raises, stale_customer_id,
            existing_mandates, mandate_list_raises,
        )


class _RaisingCustomers:
    def get(self, customer_id):
        raise RuntimeError("simulated Mollie API failure")

    def create(self, data=None):
        raise RuntimeError("simulated Mollie API failure")


class RaisingSDKClient:
    """Fake SDK whose every call raises, to test error wrapping."""

    def __init__(self):
        self.customers = _RaisingCustomers()


class _AlreadyCancelledSubscriptions:
    def delete(self, subscription_id):
        # Mimics Mollie rejecting a delete for a subscription that is already
        # gone - the message carries a phrase MollieDebugService treats as a
        # tolerable "already cancelled" outcome.
        raise RuntimeError("Subscription not found or has been cancelled")


class _AlreadyCancelledCustomer:
    def __init__(self):
        self.subscriptions = _AlreadyCancelledSubscriptions()


class _AlreadyCancelledCustomers:
    def get(self, customer_id):
        return _AlreadyCancelledCustomer()


class AlreadyCancelledSDKClient:
    """Fake SDK whose subscription delete fails as 'already cancelled'."""

    def __init__(self):
        self.customers = _AlreadyCancelledCustomers()


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

    def test_list_mandates_wraps_sdk_customer_mandates_list(self):
        sdk = FakeSDKClient(existing_mandates=[_FakeMandate(mandate_id="mdt_X")])
        client = _make_mollie_client(sdk)

        mandates = client.list_mandates("cst_123")

        self.assertEqual([m.id for m in mandates], ["mdt_X"])
        self.assertEqual(sdk.recorder.customers_fetched, ["cst_123"])

    def test_list_mandates_wraps_sdk_errors_in_mollie_payment_error(self):
        client = _make_mollie_client(RaisingSDKClient())

        with self.assertRaises(MolliePaymentError):
            client.list_mandates("cst_123")


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

    def test_create_subscription_reuses_existing_mandate_for_same_iban(self):
        """A customer that already has a valid SEPA mandate for the same IBAN
        gets no second mandate provisioned - the subscription reuses it."""
        iban = "NL39RABO0300065264"
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(status="valid", method="directdebit", consumer_account=iban)
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        result = service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(result["status"], "success")
        # No duplicate mandate - the existing valid one is reused.
        self.assertEqual(sdk.recorder.mandates_created, [])
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)

    def test_create_subscription_reuses_existing_mandate_ignoring_iban_spacing(self):
        """IBAN comparison ignores spacing/case, so a spaced IBAN still
        matches an existing mandate stored without spaces."""
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(
                    status="valid", method="directdebit",
                    consumer_account="NL39RABO0300065264",
                )
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": "nl39 rabo 0300 0652 64",
            },
        )

        self.assertEqual(sdk.recorder.mandates_created, [])

    def test_create_subscription_provisions_mandate_when_iban_differs(self):
        """An existing mandate for a *different* IBAN does not block
        provisioning - the member may have changed banks."""
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(
                    status="valid", method="directdebit",
                    consumer_account="NL11INGB0001111111",
                )
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": "NL39RABO0300065264",
            },
        )

        self.assertEqual(len(sdk.recorder.mandates_created), 1)

    def test_create_subscription_provisions_mandate_when_existing_is_invalid(self):
        """An existing mandate that is not valid/pending (e.g. invalid) does
        not count - a fresh mandate is provisioned."""
        iban = "NL39RABO0300065264"
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(status="invalid", method="directdebit", consumer_account=iban)
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(len(sdk.recorder.mandates_created), 1)

    def test_create_subscription_provisions_mandate_when_mandate_listing_fails(self):
        """If the mandate lookup itself errors, provisioning falls back to
        creating a mandate (fail open) so the subscription still succeeds."""
        iban = "NL39RABO0300065264"
        sdk = FakeSDKClient(mandate_list_raises=True)
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        result = service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(sdk.recorder.mandates_created), 1)

    def test_create_subscription_reuses_pending_mandate(self):
        """A directdebit mandate still being established (status 'pending')
        counts as usable - provisioning a second one would duplicate it."""
        iban = "NL39RABO0300065264"
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(status="pending", method="directdebit", consumer_account=iban)
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(sdk.recorder.mandates_created, [])

    def test_create_subscription_provisions_when_only_creditcard_mandate(self):
        """A non-directdebit mandate (e.g. creditcard) for the IBAN does not
        count - a SEPA directdebit mandate is still provisioned."""
        iban = "NL39RABO0300065264"
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(status="valid", method="creditcard", consumer_account=iban)
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(len(sdk.recorder.mandates_created), 1)

    def test_create_subscription_finds_matching_mandate_on_a_later_page(self):
        """Mollie paginates the mandate list; the match must be found even
        when it sits beyond the first page."""
        iban = "NL39RABO0300065264"
        # Page size is 2, so a valid match in position 3 is on page 2.
        sdk = FakeSDKClient(
            existing_mandates=[
                _FakeMandate(mandate_id="mdt_1", status="invalid", method="directdebit"),
                _FakeMandate(mandate_id="mdt_2", status="valid", method="directdebit",
                             consumer_account="NL11INGB0001111111"),
                _FakeMandate(mandate_id="mdt_3", status="valid", method="directdebit",
                             consumer_account=iban),
            ]
        )
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        service.create_customer_subscription(
            {"name": "Jane Doe", "email": _unique_email()},
            {
                "amount": {"value": "15.00", "currency": "EUR"},
                "interval": "1 month",
                "description": "Membership dues",
                "consumerAccount": iban,
            },
        )

        self.assertEqual(sdk.recorder.mandates_created, [])

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
        self.assertEqual(result["subscription_id"], "sub_LIVE")
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

    def test_create_member_subscription_routes_through_gateway(self):
        """Phase 3 - the create_member_subscription endpoint delegates to
        MollieGateway, so CompletePaymentService owns the Member update:
        subscription_status lands on the Member, which the old
        MollieDebugService path never set. payment_method is not part of the
        contract the service owns, so the endpoint still sets it itself."""
        member = self._make_member()
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_MEMBER", update_modified=False
        )
        sdk = FakeSDKClient()

        with _patch_sdk(sdk):
            from verenigingen.verenigingen_payments.utils.payment_gateways import (
                create_member_subscription,
            )

            result = create_member_subscription(member.name, 15.0, interval="1 month")

        self.assertEqual(result["status"], "success")
        # The service owns the Member update - subscription_status is set.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_FAKE"
        )
        # payment_method is still set by create_member_subscription itself.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "payment_method"), "Mollie"
        )

    def test_create_member_subscription_blocks_existing_active_subscription(self):
        """The early guard must fire for a member who already has a live
        subscription. subscription_status is stored lowercase, so the guard
        compares against 'active'."""
        member = self._make_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "mollie_customer_id": "cst_MEMBER",
                "mollie_subscription_id": "sub_EXISTING",
                "subscription_status": "active",
            },
            update_modified=False,
        )

        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            create_member_subscription,
        )

        result = create_member_subscription(member.name, 15.0, interval="1 month")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["existing_subscription_id"], "sub_EXISTING")

    def test_create_member_subscription_rejects_unsupported_interval(self):
        """An interval the gateway does not support is rejected outright,
        rather than being silently coerced to monthly billing."""
        member = self._make_member()
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_MEMBER", update_modified=False
        )

        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            create_member_subscription,
        )

        result = create_member_subscription(member.name, 15.0, interval="12 months")

        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported", result["message"])


class TestMollieSubscriptionContract(EnhancedTestCase):
    """Phase 2 - standardised mid-level create/cancel contract."""

    def test_create_customer_subscription_rejected_when_subscriptions_disabled(self):
        """The enable_subscriptions gate is enforced inside the service, so no
        caller wired straight to CompletePaymentService can bypass it."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        # The gate raises MollieValidationError - and it must propagate as that
        # type (not be re-wrapped as MolliePaymentError), so the API layer can
        # surface the real "not enabled" message.
        with patch("frappe.db.get_single_value", return_value=0):
            with self.assertRaises(MollieValidationError) as ctx:
                service.create_customer_subscription(
                    {"name": "Jane Doe", "email": _unique_email()},
                    {
                        "amount": {"value": "15.00", "currency": "EUR"},
                        "interval": "1 month",
                        "description": "Membership dues",
                    },
                )

        self.assertIn("not enabled", str(ctx.exception))
        # The gate fires before any Mollie call.
        self.assertEqual(sdk.recorder.subscriptions_created, [])
        self.assertEqual(sdk.recorder.customers_created, [])

    def test_customer_resolution_is_owner_aware_for_member(self):
        """A membership subscription resolves the Mollie customer against the
        Member record. Even when a Donor shares the email address, the Donor's
        mollie_customer_id is left untouched."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))

        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Owner",
            last_name=f"Aware{token}",
            email=f"owner-aware-{token}@example.com",
            birth_date="1990-01-01",
        )
        donor = self.create_test_donor()
        frappe.db.set_value("Donor", donor.name, "donor_email", member.email, update_modified=False)

        # The owner-row lock uses frappe.db.begin/commit; neutralise the
        # transaction plumbing so the locking logic runs inside the test's
        # transaction (the pattern used by test_termination_execution_service).
        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = service.create_customer_subscription(
                {
                    "name": "Owner Aware",
                    "email": member.email,
                    "owner_doctype": "Member",
                    "owner_name": member.name,
                },
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                },
            )

        self.assertEqual(result["status"], "success")
        # The Mollie customer id is stored on the Member, not the Donor.
        self.assertTrue(frappe.db.get_value("Member", member.name, "mollie_customer_id"))
        self.assertFalse(frappe.db.get_value("Donor", donor.name, "mollie_customer_id"))

    def test_create_customer_subscription_updates_owning_member(self):
        """On a successful create the service writes the subscription back
        onto the owning Member - callers no longer do their own db_sets."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Update",
            last_name=f"Owner{token}",
            email=f"update-owner-{token}@example.com",
            birth_date="1990-01-01",
        )

        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = service.create_customer_subscription(
                {
                    "name": "Update Owner",
                    "email": member.email,
                    "owner_doctype": "Member",
                    "owner_name": member.name,
                },
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_FAKE"
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )
        self.assertEqual(
            str(frappe.db.get_value("Member", member.name, "next_payment_date")), "2026-06-01"
        )

    def test_update_owner_record_skips_fields_a_doctype_lacks(self):
        """_update_owner_record writes every applicable field to a Member but
        silently skips status fields on a Donor (which does not define them)."""
        service = CompletePaymentService(client=_make_mollie_client(FakeSDKClient()))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Record",
            last_name=f"Owner{token}",
            email=f"record-owner-{token}@example.com",
            birth_date="1990-01-01",
        )
        donor = self.create_test_donor()
        values = {
            "mollie_subscription_id": "sub_REC",
            "subscription_status": "active",
            "next_payment_date": "2026-07-01",
        }

        service._update_owner_record("Member", member.name, values)
        service._update_owner_record("Donor", donor.name, values)

        # Member defines all three fields.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_subscription_id"), "sub_REC"
        )
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "active"
        )
        # Donor defines mollie_subscription_id but not the status fields - the
        # absent fields are skipped without error.
        self.assertEqual(
            frappe.db.get_value("Donor", donor.name, "mollie_subscription_id"), "sub_REC"
        )

    def test_cancel_subscription_updates_owning_member(self):
        """cancel_subscription finds the owning Member by mollie_subscription_id
        and flips subscription_status to the valid 'canceled' value."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Cancel",
            last_name=f"Owner{token}",
            email=f"cancel-owner-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "mollie_customer_id": "cst_C",
                "mollie_subscription_id": "sub_C",
                "subscription_status": "active",
            },
            update_modified=False,
        )

        result = service.cancel_subscription("cst_C", "sub_C")

        self.assertEqual(result["status"], "success")
        # Standard cancel result shape - exactly these keys.
        self.assertEqual(set(result), {"status", "subscription_id", "message"})
        self.assertEqual(result["subscription_id"], "sub_C")
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"), "canceled"
        )
        self.assertTrue(frappe.db.get_value("Member", member.name, "subscription_cancelled_date"))

    def test_subscription_service_cancel_returns_standard_dict(self):
        """SubscriptionService.cancel_subscription returns the standard cancel
        result dict, not a raw Mollie subscription object."""
        sdk = FakeSDKClient()
        service = SubscriptionService(client=_make_mollie_client(sdk))

        result = service.cancel_subscription("cst_S", "sub_S")

        self.assertIsInstance(result, dict)
        self.assertEqual(set(result), {"status", "subscription_id", "message"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_S")

    def test_create_customer_subscription_is_idempotent_when_owner_has_subscription(self):
        """If the owning record already has an active subscription, create
        returns it rather than provisioning a duplicate at Mollie."""
        sdk = FakeSDKClient()
        service = CompletePaymentService(client=_make_mollie_client(sdk))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Idem",
            last_name=f"Potent{token}",
            email=f"idem-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_EXISTING", "mollie_subscription_id": "sub_EXISTING"},
            update_modified=False,
        )

        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = service.create_customer_subscription(
                {
                    "name": "Idem Potent",
                    "email": member.email,
                    "owner_doctype": "Member",
                    "owner_name": member.name,
                },
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_EXISTING")
        # No duplicate subscription was provisioned at Mollie.
        self.assertEqual(sdk.recorder.subscriptions_created, [])

    def test_create_subscription_recreates_when_stored_subscription_inactive(self):
        """An owner whose stored subscription is no longer live (e.g. cancelled)
        does not get the stale subscription back - a fresh one is provisioned."""
        sdk = FakeSDKClient(sub_status="canceled")
        service = CompletePaymentService(client=_make_mollie_client(sdk))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Stale",
            last_name=f"Sub{token}",
            email=f"stale-sub-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_OLD", "mollie_subscription_id": "sub_OLD"},
            update_modified=False,
        )

        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = service.create_customer_subscription(
                {
                    "name": "Stale Sub",
                    "email": member.email,
                    "owner_doctype": "Member",
                    "owner_name": member.name,
                },
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                },
            )

        self.assertEqual(result["status"], "success")
        # The cancelled stored subscription is not reused - a fresh one is made.
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)
        self.assertNotEqual(result["subscription_id"], "sub_OLD")

    def test_create_subscription_replaces_stale_customer_id(self):
        """When the owner's stored Mollie customer id no longer resolves, a
        fresh customer is created and recorded on the owner."""
        sdk = FakeSDKClient(stale_customer_id="cst_STALE")
        service = CompletePaymentService(client=_make_mollie_client(sdk))
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Stale",
            last_name=f"Cust{token}",
            email=f"stale-cust-{token}@example.com",
            birth_date="1990-01-01",
        )
        frappe.db.set_value(
            "Member", member.name, "mollie_customer_id", "cst_STALE", update_modified=False
        )

        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            result = service.create_customer_subscription(
                {
                    "name": "Stale Cust",
                    "email": member.email,
                    "owner_doctype": "Member",
                    "owner_name": member.name,
                },
                {
                    "amount": {"value": "15.00", "currency": "EUR"},
                    "interval": "1 month",
                    "description": "Membership dues",
                },
            )

        self.assertEqual(result["status"], "success")
        # A new customer replaced the stale id on the Member.
        new_customer_id = frappe.db.get_value("Member", member.name, "mollie_customer_id")
        self.assertTrue(new_customer_id)
        self.assertNotEqual(new_customer_id, "cst_STALE")


class _DelegationSpy:
    """Wrap a class method so its calls are recorded while the real method
    still runs. Used to assert MollieDebugService delegates to MollieClient
    rather than reaching the raw SDK directly.

    Mock justified: this is a spy, not a stub - the real wrapped method runs,
    the Mollie SDK stays the only faked boundary. It only records that the
    standardised MollieClient layer was the path taken, which is precisely
    the Phase 3 contract under test.
    """

    def __init__(self, cls, method_name):
        self._real = getattr(cls, method_name)
        self.calls = []

        def wrapper(inner_self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self._real(inner_self, *args, **kwargs)

        self._patch = patch.object(cls, method_name, wrapper)

    def __enter__(self):
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


class TestMollieDebugServiceSubscription(EnhancedTestCase):
    """Phase 3 - MollieDebugService subscription create/cancel route through
    MollieClient instead of the raw SDK."""

    def test_create_subscription_delegates_to_mollie_client(self):
        sdk = FakeSDKClient()

        with _patch_sdk(sdk), _DelegationSpy(MollieClient, "create_subscription") as spy:
            from verenigingen.services.mollie_debug_service import MollieDebugService

            service = MollieDebugService()
            result = service.create_subscription(
                customer_id="cst_DEBUG",
                amount=15.0,
                interval="1 month",
                description="Debug subscription",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_FAKE")
        # The create went through MollieClient, not the raw sdk_client.
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0][0][0], "cst_DEBUG")
        # And the SDK still received exactly one subscription create.
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)

    def test_create_subscription_failure_returns_sanitised_error(self):
        """An SDK failure surfaces as the debug error shape, not an exception."""
        with _patch_sdk(RaisingSDKClient()):
            from verenigingen.services.mollie_debug_service import MollieDebugService

            service = MollieDebugService()
            result = service.create_subscription(
                customer_id="cst_DEBUG",
                amount=15.0,
                interval="1 month",
                description="Debug subscription",
            )

        self.assertEqual(result["status"], "error")

    def test_create_scheduled_subscription_delegates_to_mollie_client(self):
        sdk = FakeSDKClient()

        with _patch_sdk(sdk), _DelegationSpy(MollieClient, "create_subscription") as spy:
            from verenigingen.services.mollie_debug_service import MollieDebugService

            service = MollieDebugService()
            result = service.create_scheduled_subscription(
                customer_id="cst_DEBUG",
                amount=15.0,
                interval_count=1,
                interval_unit="months",
                description="Debug scheduled subscription",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_FAKE")
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0][0][0], "cst_DEBUG")
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)

    def test_admin_cancel_subscription_delegates_to_mollie_client(self):
        sdk = FakeSDKClient()

        with _patch_sdk(sdk), _DelegationSpy(MollieClient, "cancel_subscription") as spy:
            from verenigingen.services.mollie_debug_service import MollieDebugService

            service = MollieDebugService()
            result = service.admin_cancel_subscription(
                customer_id="cst_DEBUG",
                subscription_id="sub_LIVE",
                reason="Test cancellation",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0][0], ("cst_DEBUG", "sub_LIVE"))
        self.assertEqual(sdk.recorder.subscriptions_deleted, ["sub_LIVE"])

    def test_admin_cancel_already_cancelled_returns_warning(self):
        """An already-cancelled subscription is tolerated (status 'warning'),
        even though MollieClient.cancel_subscription raises - the wrapped
        MolliePaymentError keeps the SDK's 'not found' phrasing."""
        with _patch_sdk(AlreadyCancelledSDKClient()), _DelegationSpy(
            MollieClient, "cancel_subscription"
        ) as spy:
            from verenigingen.services.mollie_debug_service import MollieDebugService

            service = MollieDebugService()
            result = service.admin_cancel_subscription(
                customer_id="cst_DEBUG",
                subscription_id="sub_GONE",
                reason="Test cancellation",
            )

        self.assertEqual(result["status"], "warning")
        self.assertEqual(len(spy.calls), 1)
