# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Unit coverage for the member-portal Mollie SUBSCRIPTION-QUERY endpoints — no
Mollie key, no network.

Companion to test_mollie_portal_endpoints_unit.py (which covers
``update_mollie_bank_account``). This file drives the two remaining endpoints in
``verenigingen/api/mollie_payment.py`` PAST their early-return guards into the
SubscriptionService seam:

- get_subscription_details      -> shaping active/canceled subscriptions, mandate
                                   validity, customer-only entries, list errors,
                                   per-customer query failure, and the live-query
                                   fallback to the last-known Member status.
- cancel_specific_subscription  -> success path with Member-record cleanup, the
                                   donor-customer-id authorization branch, and the
                                   service-error path.

Only the Mollie SDK / SubscriptionService boundary is mocked — the external HTTP
client. All app business logic (member resolution, ownership checks, shaping,
db_set cleanup) runs for real. The endpoints are invoked as a logged-in plain
member so the @self_service_api tier gate is exercised exactly as in production.
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.api import mollie_payment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.security.types import EnvironmentLevel

# Path where the endpoints import SubscriptionService at call time; patching here
# swaps the class the endpoint instantiates (same seam as the sibling unit test).
_SUBSCRIPTION_SERVICE = (
    "verenigingen.verenigingen_payments.mollie.services.subscription_service.SubscriptionService"
)

# update_*/get_* endpoints carry a @self_service_api profile restricted to the
# development environment; a fresh CI site reports PRODUCTION and would reject the
# call before any business logic. Force DEVELOPMENT at the environment boundary.
_ENV_DETECT = "verenigingen.utils.security.environment_validator.EnvironmentValidator.get_current_environment"


def _mandate(status):
    """A SDK mandate stub with the given .status."""
    m = MagicMock()
    m.status = status
    return m


class TestMolliePortalSubscriptionQueryUnit(PortalSelfServiceTestMixin, EnhancedTestCase):
    """get_subscription_details / cancel_specific_subscription, without touching Mollie."""

    def setUp(self):
        super().setUp()
        self._env_patch = patch(_ENV_DETECT, return_value=EnvironmentLevel.DEVELOPMENT)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        super().tearDown()

    def _member_with_mollie(self, **mollie_fields):
        """Member linked to a plain-member User, optionally carrying Mollie id
        fields so the endpoint clears its 'no subscription' guard."""
        member = self.create_test_member(birth_date="1990-01-01")
        user = self._link_member_to_user(member)
        if mollie_fields:
            frappe.db.set_value("Member", member.name, mollie_fields)
            member.reload()
        return member, user

    def _wire_customer(self, MockService, *, mandates=None):
        """Return (service, customer_obj) with the customers.get(...).mandates.list()
        seam wired. `mandates` is the list returned by mandate enumeration."""
        service = MockService.return_value
        customer_obj = service.client.sdk_client.customers.get.return_value
        customer_obj.mandates.list.return_value = mandates if mandates is not None else []
        return service, customer_obj

    # ==================================================================
    # get_subscription_details
    # ==================================================================
    def test_active_subscription_is_shaped_with_valid_mandate(self):
        """A customer with one active subscription and a valid mandate yields a
        fully-shaped entry: amount/currency from structured fields, is_active True,
        mandate_valid True."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            subscription_status="active",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService, mandates=[_mandate("valid")])
            service.list_subscriptions.return_value = {
                "error": None,
                "subscriptions": [
                    {
                        "id": "sub_aaaaaaaaaa",
                        "status": "active",
                        "amount_value": 25.0,
                        "currency": "EUR",
                        "interval": "1 month",
                        "next_payment_date": "2026-07-01",
                        "description": "Membership dues",
                    }
                ],
            }
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_customers"], 1)
        self.assertEqual(len(result["subscriptions"]), 1)
        entry = result["subscriptions"][0]
        self.assertEqual(entry["customer_id"], "cst_aaaaaaaaaa")
        self.assertEqual(entry["source"], "member")
        self.assertTrue(entry["mandate_valid"])
        self.assertEqual(entry["mandate_status"], "valid")
        sub = entry["subscription"]
        self.assertEqual(sub["id"], "sub_aaaaaaaaaa")
        self.assertEqual(sub["amount"], 25.0)
        self.assertEqual(sub["currency"], "EUR")
        self.assertTrue(sub["is_active"])
        self.assertFalse(sub["is_canceled"])
        self.assertEqual(sub["description"], "Membership dues")
        # Member-record status echoed back.
        self.assertEqual(entry["member_status"]["local_status"], "active")

    def test_canceled_subscription_flags_is_canceled(self):
        """A canceled subscription shapes is_canceled True / is_active False; a
        non-valid mandate (e.g. only a pending one) yields mandate_valid False but
        carries the first non-valid status seen."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_bbbbbbbbbb",
            mollie_subscription_id="sub_bbbbbbbbbb",
            subscription_status="canceled",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService, mandates=[_mandate("pending")])
            service.list_subscriptions.return_value = {
                "error": None,
                "subscriptions": [
                    {"id": "sub_bbbbbbbbbb", "status": "canceled", "amount_value": 10.0, "currency": "EUR"}
                ],
            }
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        entry = result["subscriptions"][0]
        self.assertFalse(entry["subscription"]["is_active"])
        self.assertTrue(entry["subscription"]["is_canceled"])
        self.assertFalse(entry["mandate_valid"])
        # First non-valid mandate status is remembered.
        self.assertEqual(entry["mandate_status"], "pending")

    def test_shape_defaults_amount_and_currency_when_absent(self):
        """Missing amount_value/currency fall back to 0.0 / EUR (defensive defaults
        in _shape_subscription)."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_cccccccccc",
            mollie_subscription_id="sub_cccccccccc",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService, mandates=[])
            service.list_subscriptions.return_value = {
                "error": None,
                "subscriptions": [{"id": "sub_cccccccccc", "status": "active"}],
            }
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        sub = result["subscriptions"][0]["subscription"]
        self.assertEqual(sub["amount"], 0.0)
        self.assertEqual(sub["currency"], "EUR")

    def test_customer_with_no_subscriptions_returns_customer_only_entry(self):
        """A customer that exists but has no subscriptions yields a single
        customer-only entry (subscription None, has_customer_only True) carrying the
        mandate validity that was checked."""
        _, user = self._member_with_mollie(mollie_customer_id="cst_dddddddddd")

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService, mandates=[_mandate("valid")])
            service.list_subscriptions.return_value = {"error": None, "subscriptions": []}
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "success")
        entry = result["subscriptions"][0]
        self.assertIsNone(entry["subscription"])
        self.assertTrue(entry["has_customer_only"])
        self.assertTrue(entry["mandate_valid"])
        self.assertEqual(entry["mandate_status"], "valid")
        self.assertEqual(entry["note"], "Customer found but no subscriptions")

    def test_list_error_returns_customer_only_entry_with_error(self):
        """When list_subscriptions reports an error, the customer degrades to a
        customer-only entry carrying that error and NO mandate_status key (validity
        was never checked on the error path)."""
        _, user = self._member_with_mollie(mollie_customer_id="cst_eeeeeeeeee")

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService)
            service.list_subscriptions.return_value = {"error": "Mollie said no", "subscriptions": []}
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        entry = result["subscriptions"][0]
        self.assertIsNone(entry["subscription"])
        self.assertTrue(entry["has_customer_only"])
        self.assertEqual(entry["error"], "Mollie said no")
        self.assertFalse(entry["mandate_valid"])
        # mandate_status is omitted entirely on the list-error path.
        self.assertNotIn("mandate_status", entry)

    def test_per_customer_query_exception_degrades_to_error_entry(self):
        """If list_subscriptions raises, the per-customer failure degrades to an
        error entry rather than aborting the whole response."""
        _, user = self._member_with_mollie(mollie_customer_id="cst_ffffffffff")

        self.expectErrorLog("Mollie Subscription Query")
        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.list_subscriptions.side_effect = Exception("boom")
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "success")
        entry = result["subscriptions"][0]
        self.assertIsNone(entry["subscription"])
        self.assertEqual(entry["error"], "Could not fetch subscription data")

    def test_no_customer_id_returns_no_subscription(self):
        """A member with no Mollie customer id returns the 'no_subscription'
        early result before any service is built."""
        _, user = self._member_with_mollie()
        with self._as_user(user.name):
            result = mollie_payment.get_subscription_details()
        self.assertEqual(result["status"], "no_subscription")

    def test_multiple_comma_separated_customer_ids_are_all_queried(self):
        """A member with two comma-separated customer ids produces one entry per
        customer and total_customers == 2."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa,cst_bbbbbbbbbb",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service, _customer = self._wire_customer(MockService, mandates=[])
            service.list_subscriptions.return_value = {"error": None, "subscriptions": []}
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_customers"], 2)
        queried = {e["customer_id"] for e in result["subscriptions"]}
        self.assertEqual(queried, {"cst_aaaaaaaaaa", "cst_bbbbbbbbbb"})

    def test_subscription_service_construction_failure_falls_back(self):
        """If building the SubscriptionService itself raises (outer try), the
        endpoint falls back to the last-known Member-record status rather than
        erroring."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            subscription_status="active",
        )

        self.expectErrorLog("Mollie Subscription API", "Subscription Data Fetch")
        with patch(_SUBSCRIPTION_SERVICE, side_effect=Exception("cannot build service")):
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["subscription"]["status"], "active")
        self.assertEqual(result["member_status"]["local_status"], "active")
        self.assertIn("last known status", result["message"])

    def test_mandate_enumeration_failure_yields_invalid_unknown(self):
        """If customers.get(...).mandates.list() raises (no mandates found), mandate
        validity degrades to (False, None) without aborting subscription shaping."""
        _, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.client.sdk_client.customers.get.side_effect = Exception("no mandates")
            service.list_subscriptions.return_value = {
                "error": None,
                "subscriptions": [{"id": "sub_aaaaaaaaaa", "status": "active", "amount_value": 5.0}],
            }
            with self._as_user(user.name):
                result = mollie_payment.get_subscription_details()

        entry = result["subscriptions"][0]
        self.assertFalse(entry["mandate_valid"])
        self.assertIsNone(entry["mandate_status"])

    # ==================================================================
    # cancel_specific_subscription
    # ==================================================================
    def test_cancel_success_clears_member_subscription_fields(self):
        """A successful cancel of the member's OWN subscription clears
        mollie_subscription_id and sets subscription_status='canceled' on the
        Member record."""
        member, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            subscription_status="active",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.admin_cancel_subscription.return_value = {"status": "success"}
            with self._as_user(user.name):
                result = mollie_payment.cancel_specific_subscription(
                    customer_id="cst_aaaaaaaaaa", subscription_id="sub_aaaaaaaaaa"
                )

        self.assertEqual(result["status"], "success")
        # admin_cancel_subscription was called with the member's ids.
        service.admin_cancel_subscription.assert_called_once()
        kwargs = service.admin_cancel_subscription.call_args.kwargs
        self.assertEqual(kwargs["customer_id"], "cst_aaaaaaaaaa")
        self.assertEqual(kwargs["subscription_id"], "sub_aaaaaaaaaa")
        # Member record cleaned up.
        member.reload()
        self.assertIn(member.mollie_subscription_id, (None, ""))
        self.assertEqual(member.subscription_status, "canceled")

    def test_cancel_success_for_non_member_subscription_leaves_record(self):
        """Cancelling an authorized customer's subscription whose id does NOT match
        the member's own subscription id succeeds but does not touch the Member
        record (the matching guard is skipped)."""
        member, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_member0001",
            subscription_status="active",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.admin_cancel_subscription.return_value = {"status": "success"}
            with self._as_user(user.name):
                result = mollie_payment.cancel_specific_subscription(
                    customer_id="cst_aaaaaaaaaa", subscription_id="sub_otherone99"
                )

        self.assertEqual(result["status"], "success")
        member.reload()
        # The member's own subscription id is untouched.
        self.assertEqual(member.mollie_subscription_id, "sub_member0001")
        self.assertEqual(member.subscription_status, "active")

    def test_cancel_authorizes_via_donor_customer_id(self):
        """A customer id that lives on the member's linked Donor record (not the
        Member record) is authorized for cancellation — the endpoint aggregates
        Member + Donor customer ids."""
        member, user = self._member_with_mollie(mollie_customer_id="cst_membercid0")

        # Real Donor linked to the member, carrying a different Mollie customer id.
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Donor {member.name}"
        donor.donor_type = "Individual"
        donor.donor_email = f"donor-{member.name}@example.com"
        donor.member = member.name
        donor.mollie_customer_id = "cst_donorcid01"
        donor.insert()
        self.track_doc("Donor", donor.name)

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.admin_cancel_subscription.return_value = {"status": "success"}
            with self._as_user(user.name):
                result = mollie_payment.cancel_specific_subscription(
                    customer_id="cst_donorcid01", subscription_id="sub_donorsub01"
                )

        # Donor customer id was accepted as authorized -> reached the service.
        self.assertEqual(result["status"], "success")
        service.admin_cancel_subscription.assert_called_once()

    def test_cancel_reads_ids_from_form_dict_when_args_omitted(self):
        """When called with no positional ids, the endpoint reads customer_id /
        subscription_id from frappe.local.form_dict (the HTTP-form transport)."""
        member, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            subscription_status="active",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.admin_cancel_subscription.return_value = {"status": "success"}
            with self._as_user(user.name):
                frappe.local.form_dict["customer_id"] = "cst_aaaaaaaaaa"
                frappe.local.form_dict["subscription_id"] = "sub_aaaaaaaaaa"
                try:
                    result = mollie_payment.cancel_specific_subscription()
                finally:
                    frappe.local.form_dict.pop("customer_id", None)
                    frappe.local.form_dict.pop("subscription_id", None)

        self.assertEqual(result["status"], "success")
        kwargs = service.admin_cancel_subscription.call_args.kwargs
        self.assertEqual(kwargs["customer_id"], "cst_aaaaaaaaaa")
        self.assertEqual(kwargs["subscription_id"], "sub_aaaaaaaaaa")
        member.reload()
        self.assertEqual(member.subscription_status, "canceled")

    def test_cancel_service_error_is_returned_as_error_dict(self):
        """When admin_cancel_subscription raises, the endpoint catches it and
        returns a status=error dict (and the Member record is NOT mutated)."""
        member, user = self._member_with_mollie(
            mollie_customer_id="cst_aaaaaaaaaa",
            mollie_subscription_id="sub_aaaaaaaaaa",
            subscription_status="active",
        )

        with patch(_SUBSCRIPTION_SERVICE) as MockService:
            service = MockService.return_value
            service.admin_cancel_subscription.side_effect = Exception("mollie down")
            self.expectErrorLog("Mollie Subscription Cancel")
            with self._as_user(user.name):
                result = mollie_payment.cancel_specific_subscription(
                    customer_id="cst_aaaaaaaaaa", subscription_id="sub_aaaaaaaaaa"
                )

        self.assertEqual(result["status"], "error")
        self.assertIn("mollie down", result["message"])
        member.reload()
        # Cleanup did not run; the record is unchanged.
        self.assertEqual(member.mollie_subscription_id, "sub_aaaaaaaaaa")
        self.assertEqual(member.subscription_status, "active")

    def test_cancel_missing_ids_raises_required_error(self):
        """Calling without customer_id / subscription_id (and none in form_dict)
        throws the 'required' validation, which the endpoint catches and returns as
        an error dict."""
        _, user = self._member_with_mollie(mollie_customer_id="cst_aaaaaaaaaa")
        self.expectErrorLog("Mollie Subscription Cancel")
        with self._as_user(user.name):
            result = mollie_payment.cancel_specific_subscription(
                customer_id="cst_aaaaaaaaaa", subscription_id=None
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["message"].lower())
