"""
Integration coverage for verenigingen/services/mollie_debug_service.py.

MollieDebugService is the admin/debug console service over Mollie. It mixes two
concerns:

  1. Calls to the Mollie HTTP SDK (the EXTERNAL boundary) - reached either via
     the MollieClient wrapper methods (get_customer / create_subscription / ...)
     or via the raw ``self.mollie_client.sdk_client`` (customers/payments/
     subscriptions/mandates ...).
  2. Real Frappe DocType reads/writes - Member, Donor, Sales Invoice, Membership -
     plus its own input validation, limit clamping, and confirmation gates.

Test philosophy (this repo runs an aggressive test-quality-enforcer):
  - ONLY the Mollie SDK boundary is faked. ``FakeSDKClient`` records the calls
    made against it and returns realistic Mollie-shaped objects (cst_*/tr_*/
    mdt_*/sub_* ids). No network is touched and no live Mollie credentials are
    needed - the same proven seam used by
    ``tests/payment/test_mollie_subscription_consolidation.py``: patch
    ``MollieSettings.get_mollie_client`` (so ``sdk_client`` is the fake) and
    ``MollieClient._get_api_key``.
  - Everything below the SDK runs for real. The DB-side reconciliation in
    ``debug_customer`` and ``sync_membership_end_dates_from_mollie`` is exercised
    against REAL Member/Donor records, and the assertions check the actual
    observable effects (correct records matched, Member.member_end_date written),
    not merely "a dict came back".

Hence the integration ``test_mollie_debug_service.py`` name (no ``_unit`` suffix).
"""

from datetime import date, datetime
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# ---------------------------------------------------------------------------
# Patch seam (proven). MollieClient.__init__ reads the API key directly, and
# ``sdk_client`` lazily calls MollieSettings.get_mollie_client(); patching both
# lets a real MollieClient be constructed wired to the fake SDK.
# ---------------------------------------------------------------------------
_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"

_VALID_IBAN = "NL91ABNA0417164300"  # ABN AMRO test IBAN (passes validate_iban)


# ---------------------------------------------------------------------------
# Fake Mollie SDK.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API; it cannot run in tests. This fake mimics only the small slice of
# the SDK surface MollieDebugService touches and records calls for assertion.
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.customers_fetched = []
        self.customers_listed = []
        self.customers_deleted = []
        self.payments_fetched = []
        self.payments_listed = []
        self.mandates_created = []


class _Sub:
    def __init__(
        self,
        sub_id="sub_FAKE0001",
        status="active",
        canceled_at=None,
        amount=None,
        interval="1 month",
        description="Fake subscription",
    ):
        self.id = sub_id
        self.status = status
        self.amount = amount if amount is not None else {"value": "25.00", "currency": "EUR"}
        self.interval = interval
        self.description = description
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.canceled_at = canceled_at
        self.next_payment_date = None
        self.customer_id = None


class _Mandate:
    def __init__(self, mandate_id="mdt_FAKE0001", status="valid", method="directdebit"):
        self.id = mandate_id
        self.status = status
        self.method = method
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.signature_date = "2024-12-31"
        self.mandate_reference = "REF-001"
        self.consumer_name = "Jan Tester"
        self.consumer_account = _VALID_IBAN
        self.details = {
            "consumerName": "Jan Tester",
            "consumerAccount": _VALID_IBAN,
            "consumerBic": "ABNANL2A",
        }


class _Payment:
    def __init__(self, payment_id="tr_FAKE0001", status="paid", amount=None):
        self.id = payment_id
        self.status = status
        self.amount = amount if amount is not None else {"value": "25.00", "currency": "EUR"}
        self.description = "Membership dues"
        self.method = "directdebit"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.customer_id = "cst_FAKE0001"
        self.subscription_id = "sub_FAKE0001"

    @property
    def refunds(self):
        return _EmptyList()

    @property
    def chargebacks(self):
        return _EmptyList()


class _EmptyList:
    def list(self):
        return []


class _SubCollection:
    def __init__(self, subs):
        self._subs = subs

    def list(self, limit=None):
        return list(self._subs)

    def get(self, subscription_id):
        for s in self._subs:
            if s.id == subscription_id:
                return s
        return _Sub(sub_id=subscription_id)

    def delete(self, subscription_id):
        return _Sub(sub_id=subscription_id, status="canceled")


class _MandateCollection:
    def __init__(self, recorder, mandates):
        self._recorder = recorder
        self._mandates = mandates

    def list(self):
        return list(self._mandates)

    def get(self, mandate_id):
        for m in self._mandates:
            if m.id == mandate_id:
                return m
        return _Mandate(mandate_id=mandate_id)

    def create(self, data=None):
        self._recorder.mandates_created.append(data)
        return _Mandate()


class _PaymentCollection:
    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=None):
        return list(self._payments)


class _FakeCustomer:
    def __init__(self, recorder, customer_id, subs, mandates, payments):
        self.id = customer_id
        self.name = "Test Customer"
        self.email = "customer@example.com"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.mode = "test"
        self.subscriptions = _SubCollection(subs)
        self.mandates = _MandateCollection(recorder, mandates)
        self.payments = _PaymentCollection(payments)


class _FakeCustomers:
    def __init__(self, recorder, subs, mandates, payments, not_found_ids):
        self._recorder = recorder
        self._subs = subs
        self._mandates = mandates
        self._payments = payments
        self._not_found_ids = not_found_ids or set()

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        if customer_id in self._not_found_ids:
            raise RuntimeError(f"No customer exists with token {customer_id}")
        return _FakeCustomer(self._recorder, customer_id, self._subs, self._mandates, self._payments)

    def list(self, limit=None):
        self._recorder.customers_listed.append(limit)
        return [_FakeCustomer(self._recorder, "cst_FAKE0001", self._subs, self._mandates, self._payments)]

    def delete(self, customer_id):
        self._recorder.customers_deleted.append(customer_id)
        return {"deleted": True}


class _FakePayments:
    def __init__(self, recorder, payments, not_found_ids):
        self._recorder = recorder
        self._payments = payments
        self._not_found_ids = not_found_ids or set()

    def get(self, payment_id):
        self._recorder.payments_fetched.append(payment_id)
        if payment_id in self._not_found_ids:
            raise RuntimeError(f"No payment exists with token {payment_id}")
        for p in self._payments:
            if p.id == payment_id:
                return p
        return _Payment(payment_id=payment_id)

    def list(self, **params):
        self._recorder.payments_listed.append(params)
        return list(self._payments)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(
        self,
        subs=None,
        mandates=None,
        payments=None,
        customer_not_found_ids=None,
        payment_not_found_ids=None,
    ):
        self.recorder = _Recorder()
        subs = subs if subs is not None else [_Sub()]
        mandates = mandates if mandates is not None else [_Mandate()]
        payments = payments if payments is not None else [_Payment()]
        self.customers = _FakeCustomers(self.recorder, subs, mandates, payments, customer_not_found_ids)
        self.payments = _FakePayments(self.recorder, payments, payment_not_found_ids)


class _MultiPatch:
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


def _patch_sdk(sdk):
    """Route every Mollie SDK access through ``sdk`` (no live credentials)."""
    return _MultiPatch(
        patch(_GET_MOLLIE_CLIENT, return_value=sdk),
        patch(_GET_API_KEY, return_value="test_fake"),
    )


def _make_service():
    """Construct MollieDebugService (call only inside a ``_patch_sdk`` block)."""
    from verenigingen.services.mollie_debug_service import MollieDebugService

    return MollieDebugService()


class _MollieDebugServiceTest(EnhancedTestCase):
    """Common base: administrator user + a fake SDK per test."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()


# ===========================================================================
# debug_customer - reads + reconciles against REAL Member/Donor records
# ===========================================================================
class TestDebugCustomer(_MollieDebugServiceTest):
    def _make_member_with_customer(self, customer_id, **kwargs):
        return self.create_test_member(mollie_customer_id=customer_id, **kwargs)

    def _make_donor(self, customer_id):
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": f"Donor {frappe.generate_hash(length=6)}",
                "donor_type": "Individual",
                "donor_email": f"donor-{frappe.generate_hash(length=6)}@example.com",
                "mollie_customer_id": customer_id,
            }
        )
        donor.insert(ignore_permissions=True)
        self.track_doc("Donor", donor.name)
        return donor

    def test_empty_customer_id_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.debug_customer("")

    def test_matches_member_and_donor_database_records(self):
        customer_id = "cst_DBMATCH01"
        member = self._make_member_with_customer(customer_id)
        donor = self._make_donor(customer_id)
        # A second member with a DIFFERENT customer id must NOT be matched.
        other = self._make_member_with_customer("cst_OTHER0002")

        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            result = service.debug_customer(customer_id)

        self.assertTrue(result["customer_found"])
        matched_members = [m["name"] for m in result["database_records"]["members"]]
        self.assertIn(member.name, matched_members)
        self.assertNotIn(other.name, matched_members)
        matched_donors = [d["name"] for d in result["database_records"]["donors"]]
        self.assertIn(donor.name, matched_donors)

    def test_customer_data_and_collections_populated_from_sdk(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            result = service.debug_customer("cst_FAKE0001")

        self.assertTrue(result["customer_found"])
        self.assertEqual(result["customer_data"]["id"], "cst_FAKE0001")
        self.assertEqual(len(result["subscriptions"]), 1)
        self.assertEqual(len(result["mandates"]), 1)
        self.assertIsNone(result["error"])

    def test_sdk_failure_is_captured_but_db_records_still_returned(self):
        customer_id = "cst_MISSING99"
        member = self._make_member_with_customer(customer_id)
        sdk = FakeSDKClient(customer_not_found_ids={customer_id})

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.debug_customer(customer_id)

        # The Mollie lookup failed (customer_found stays False, error captured)...
        self.assertFalse(result["customer_found"])
        self.assertIsNotNone(result["error"])
        # ...but the DB-side reconciliation still ran.
        self.assertIn(member.name, [m["name"] for m in result["database_records"]["members"]])


# ===========================================================================
# debug_payment / list_payments / list_customers - SDK read shaping
# ===========================================================================
class TestPaymentAndCustomerListing(_MollieDebugServiceTest):
    def test_debug_payment_requires_id(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.debug_payment("")

    def test_debug_payment_returns_shaped_data(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            result = service.debug_payment("tr_FAKE0001")

        self.assertTrue(result["payment_found"])
        self.assertEqual(result["payment_data"]["id"], "tr_FAKE0001")
        self.assertEqual(result["payment_data"]["amount"], "25.00 EUR")
        self.assertEqual(result["refunds"], [])
        self.assertEqual(result["chargebacks"], [])

    def test_debug_payment_sdk_failure_captured(self):
        sdk = FakeSDKClient(payment_not_found_ids={"tr_MISSING01"})
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.debug_payment("tr_MISSING01")
        self.assertFalse(result["payment_found"])
        self.assertIsNotNone(result["error"])

    def test_list_customers_clamps_invalid_limit_to_default(self):
        sdk = FakeSDKClient()
        with _patch_sdk(sdk):
            service = _make_service()
            # 99999 is out of [1,250] -> _sanitize_limit returns default 20.
            result = service.list_customers(limit=99999)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(sdk.recorder.customers_listed[-1], 20)
        self.assertEqual(len(result["customers"]), 1)

    def test_list_payments_without_customer_lists_all(self):
        sdk = FakeSDKClient()
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.list_payments(limit=10)
        self.assertEqual(len(result["payments"]), 1)
        # No customer_id -> top-level payments.list() was used.
        self.assertEqual(len(sdk.recorder.payments_listed), 1)
        self.assertEqual(sdk.recorder.payments_listed[0]["limit"], 10)

    def test_list_payments_with_customer_filters_by_status(self):
        # Two payments: one paid, one failed. status_filter='paid' keeps one.
        payments = [_Payment("tr_PAID0001", status="paid"), _Payment("tr_FAIL0001", status="failed")]
        sdk = FakeSDKClient(payments=payments)
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.list_payments(customer_id="cst_FAKE0001", status_filter="paid")
        ids = [p["id"] for p in result["payments"]]
        self.assertEqual(ids, ["tr_PAID0001"])


# ===========================================================================
# debug_subscription / debug_mandate - guards + SDK shaping
# ===========================================================================
class TestSubscriptionAndMandateDebug(_MollieDebugServiceTest):
    def test_debug_subscription_requires_both_ids(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.debug_subscription("", customer_id="cst_x")
            with self.assertRaises(ValueError):
                service.debug_subscription("sub_x", customer_id=None)

    def test_debug_subscription_returns_shaped_data(self):
        subs = [_Sub(sub_id="sub_FAKE0001", status="active")]
        with _patch_sdk(FakeSDKClient(subs=subs)):
            service = _make_service()
            result = service.debug_subscription("sub_FAKE0001", customer_id="cst_FAKE0001")
        self.assertTrue(result["subscription_found"])
        self.assertEqual(result["subscription_data"]["id"], "sub_FAKE0001")
        self.assertEqual(result["subscription_data"]["status"], "active")

    def test_debug_mandate_requires_both_ids(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.debug_mandate("", customer_id="cst_x")
            with self.assertRaises(ValueError):
                service.debug_mandate("mdt_x", customer_id=None)

    def test_debug_mandate_returns_shaped_data(self):
        mandates = [_Mandate(mandate_id="mdt_FAKE0001", status="valid")]
        with _patch_sdk(FakeSDKClient(mandates=mandates)):
            service = _make_service()
            result = service.debug_mandate("mdt_FAKE0001", customer_id="cst_FAKE0001")
        self.assertTrue(result["mandate_found"])
        self.assertEqual(result["mandate_data"]["id"], "mdt_FAKE0001")
        self.assertEqual(result["mandate_data"]["method"], "directdebit")


# ===========================================================================
# list_subscriptions - delegates to SubscriptionService; active_only filter
# ===========================================================================
class TestListSubscriptions(_MollieDebugServiceTest):
    def test_active_only_filters_out_canceled(self):
        subs = [
            _Sub(sub_id="sub_ACT0001", status="active"),
            _Sub(sub_id="sub_CAN0001", status="canceled"),
        ]
        with _patch_sdk(FakeSDKClient(subs=subs)):
            service = _make_service()
            result = service.list_subscriptions("cst_FAKE0001", active_only=True)
        ids = [s["id"] for s in result["subscriptions"]]
        self.assertEqual(ids, ["sub_ACT0001"])
        self.assertEqual(result["total_found"], 1)

    def test_active_only_false_returns_all(self):
        subs = [
            _Sub(sub_id="sub_ACT0001", status="active"),
            _Sub(sub_id="sub_CAN0001", status="canceled"),
        ]
        with _patch_sdk(FakeSDKClient(subs=subs)):
            service = _make_service()
            result = service.list_subscriptions("cst_FAKE0001", active_only=False)
        self.assertEqual(result["total_found"], 2)

    def test_out_of_range_limit_clamped_to_50(self):
        with _patch_sdk(FakeSDKClient(subs=[])):
            service = _make_service()
            result = service.list_subscriptions("cst_FAKE0001", limit=9999)
        self.assertEqual(result["limit"], 50)


# ===========================================================================
# create_subscription - input validation (no SDK call when invalid)
# ===========================================================================
class TestCreateSubscriptionValidation(_MollieDebugServiceTest):
    def test_missing_customer_id_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_subscription(customer_id="", amount=10.0, interval="1 month", description="x")

    def test_invalid_interval_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_subscription(
                    customer_id="cst_x", amount=10.0, interval="5 months", description="x"
                )

    def test_amount_over_cap_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_subscription(
                    customer_id="cst_x", amount=1001.0, interval="1 month", description="x"
                )

    def test_valid_inputs_create_subscription_via_client(self):
        # enable_subscriptions only gates the production SubscriptionService path;
        # create_subscription here goes straight through MollieClient.create_subscription,
        # which our fake SDK satisfies. Capture the forwarded payload so a regression
        # in amount formatting / interval / metadata is caught - not just the echoed id.
        captured = {}

        class _SubCreatingCustomers(_FakeCustomers):
            def get(self, customer_id):
                cust = super().get(customer_id)

                def _create(data=None):
                    captured["data"] = data
                    return _Sub(sub_id="sub_CREATED1", status="active")

                cust.subscriptions.create = _create
                return cust

        sdk = FakeSDKClient()
        sdk.customers = _SubCreatingCustomers(sdk.recorder, [_Sub()], [_Mandate()], [_Payment()], set())

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.create_subscription(
                customer_id="cst_FAKE0001",
                amount=15.0,
                interval="1 month",
                description="Debug subscription",
                mandate_id="mdt_FAKE0001",
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["subscription_id"], "sub_CREATED1")

        # The real payload-building logic ran: amount formatted to Mollie's
        # {currency, value} cents-string shape, interval + mandate forwarded.
        data = captured["data"]
        self.assertEqual(data["amount"], {"currency": "EUR", "value": "15.00"})
        self.assertEqual(data["interval"], "1 month")
        self.assertEqual(data["description"], "Debug subscription")
        self.assertEqual(data["mandateId"], "mdt_FAKE0001")
        # times not supplied -> the subscription is unlimited (key omitted).
        self.assertNotIn("times", data)


# ===========================================================================
# create_mandate - SEPA validation + masked-IBAN success path
# ===========================================================================
class TestCreateMandate(_MollieDebugServiceTest):
    def test_missing_consumer_name_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_mandate(customer_id="cst_x", consumer_name="", consumer_account=_VALID_IBAN)

    def test_invalid_iban_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_mandate(
                    customer_id="cst_x", consumer_name="Jan Tester", consumer_account="NL00BADIBAN"
                )

    def test_consumer_name_too_long_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.create_mandate(
                    customer_id="cst_x",
                    consumer_name="X" * 71,
                    consumer_account=_VALID_IBAN,
                )

    def test_valid_mandate_creates_and_masks_iban(self):
        sdk = FakeSDKClient()
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.create_mandate(
                customer_id="cst_FAKE0001",
                consumer_name="Jan Tester",
                consumer_account=_VALID_IBAN,
            )
        self.assertEqual(result["status"], "success")
        # IBAN was forwarded cleaned/upper-cased to the SDK create call.
        self.assertEqual(len(sdk.recorder.mandates_created), 1)
        self.assertEqual(sdk.recorder.mandates_created[0]["consumerAccount"], _VALID_IBAN)
        self.assertEqual(sdk.recorder.mandates_created[0]["method"], "directdebit")


# ===========================================================================
# admin_delete_customer - confirmation gate + cascade reporting
# ===========================================================================
class TestAdminDeleteCustomer(_MollieDebugServiceTest):
    def test_missing_customer_id_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.admin_delete_customer("", confirmation_text="DELETE CUSTOMER")

    def test_wrong_confirmation_text_raises(self):
        with _patch_sdk(FakeSDKClient()):
            service = _make_service()
            with self.assertRaises(ValueError):
                service.admin_delete_customer("cst_x", confirmation_text="delete")

    def test_correct_confirmation_deletes_and_reports_cascade(self):
        subs = [_Sub("sub_A"), _Sub("sub_B")]
        mandates = [_Mandate("mdt_A")]
        sdk = FakeSDKClient(subs=subs, mandates=mandates)
        with _patch_sdk(sdk):
            service = _make_service()
            result = service.admin_delete_customer(
                "cst_FAKE0001", reason="cleanup", confirmation_text="DELETE CUSTOMER"
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(sdk.recorder.customers_deleted, ["cst_FAKE0001"])
        self.assertEqual(result["cascaded_deletions"]["subscriptions_deleted"], 2)
        self.assertEqual(result["cascaded_deletions"]["mandates_deleted"], 1)


# ===========================================================================
# sync_membership_end_dates_from_mollie - REAL Member DB writes
# ===========================================================================
class TestSyncMembershipEndDates(_MollieDebugServiceTest):
    def _make_terminated_member(self, customer_id, status="Quit", member_end_date=None):
        kwargs = {"status": status, "mollie_customer_id": customer_id}
        if member_end_date is not None:
            kwargs["member_end_date"] = member_end_date
        return self.create_test_member(**kwargs)

    def _sdk_with_canceled_sub(self, canceled_at):
        sub = _Sub(sub_id="sub_CANCELED", status="canceled", canceled_at=canceled_at)
        return FakeSDKClient(subs=[sub])

    def test_dry_run_reports_but_does_not_write(self):
        cancel_date = date(2025, 6, 15)
        member = self._make_terminated_member("cst_SYNC0001")
        sdk = self._sdk_with_canceled_sub(datetime(2025, 6, 15, 10, 0, 0))

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.sync_membership_end_dates_from_mollie(dry_run=True)

        self.assertGreaterEqual(result["total_checked"], 1)
        self.assertGreaterEqual(result["updates_needed"], 1)
        self.assertEqual(result["updates_applied"], 0)
        # No write happened in dry-run.
        member.reload()
        self.assertNotEqual(str(member.member_end_date or ""), str(cancel_date))

    def test_live_run_writes_member_end_date_from_cancellation(self):
        cancel_date = date(2025, 7, 20)
        member = self._make_terminated_member("cst_SYNC0002", status="Banned")
        sdk = self._sdk_with_canceled_sub(datetime(2025, 7, 20, 9, 0, 0))

        with _patch_sdk(sdk):
            service = _make_service()
            result = service.sync_membership_end_dates_from_mollie(dry_run=False)

        self.assertGreaterEqual(result["updates_applied"], 1)
        # The REAL Member record was updated to the Mollie cancellation date.
        member.reload()
        self.assertEqual(str(member.member_end_date), str(cancel_date))

    def test_member_without_cancellation_is_not_updated(self):
        # Subscription has no canceled_at -> nothing to sync for this member.
        member = self._make_terminated_member("cst_SYNC0003", status="Suspended")
        sub = _Sub(sub_id="sub_ACTIVE", status="active", canceled_at=None)
        sdk = FakeSDKClient(subs=[sub])

        with _patch_sdk(sdk):
            service = _make_service()
            service.sync_membership_end_dates_from_mollie(dry_run=False)

        member.reload()
        self.assertFalse(member.member_end_date)


# ===========================================================================
# _sanitize_limit static helper - pure logic
# ===========================================================================
class TestSanitizeLimit(EnhancedTestCase):
    def test_valid_passthrough(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.assertEqual(MollieDebugService._sanitize_limit(42), 42)

    def test_out_of_range_returns_default(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.assertEqual(MollieDebugService._sanitize_limit(0), 20)
        self.assertEqual(MollieDebugService._sanitize_limit(9999), 20)

    def test_non_numeric_returns_default(self):
        from verenigingen.services.mollie_debug_service import MollieDebugService

        self.assertEqual(MollieDebugService._sanitize_limit("abc"), 20)
