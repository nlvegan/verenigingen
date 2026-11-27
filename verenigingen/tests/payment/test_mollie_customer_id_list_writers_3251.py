"""
#3251 (sibling of #2675): the Mollie API callers that took the WHOLE ``mollie_customer_id`` field
value ("cst_a, cst_b") as a customer id must work per listed id, and must not overwrite a list.

Sites: ``update_mollie_subscription_amount``, ``CompletePaymentService._create_owner_subscription``
(idempotency lookup, customer resolution, write-back) and ``_resolve_customer_by_email`` (Donor).

Stub boundary: ``MollieSettings.get_mollie_client`` -- BELOW ``MollieClient`` and ``MollieGateway`` --
returns a fake SDK. Real Mollie was never probed for what it answers to "cst_a, cst_b"; the fake
models the safe assumption (it knows exact ids only, so a whole-list id is refused). The test proves
the code asks per id, not what Mollie does.

Probe shortcut, stated: lists are put on rows with ``db.set_value`` (as the #2675 module does); no
writer is driven here. ``enable_subscriptions`` is set on the Mollie Settings single for the test.

Run with:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_2 \\
        verenigingen.tests.payment.test_mollie_customer_id_list_writers_3251
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.payment.test_mollie_multi_id_customer_lists_2675 import MultiIdBase
from verenigingen.verenigingen_payments.mollie.services.complete_payment_service import (
    CompletePaymentService,
)
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


class _FakeSubscription:
    def __init__(self, owner, subscription_id):
        self.owner, self.id = owner, subscription_id
        self.status, self.next_payment_date, self.mandate_id, self.amount = "active", None, None, None

    def update(self, data):
        self.owner.updates.append((self.owner.id, self.id, data))
        self.amount = data.get("amount")
        return self


class _FakeSubscriptions:
    def __init__(self, owner, held):
        self.owner, self.held = owner, held

    def get(self, subscription_id):
        if subscription_id not in self.held:
            raise RuntimeError(f"subscription {subscription_id} not under {self.owner.id}")
        return _FakeSubscription(self.owner, subscription_id)

    def create(self, data):
        subscription_id = f"sub_new{frappe.generate_hash(length=8)}"
        self.held.add(subscription_id)
        return _FakeSubscription(self.owner, subscription_id)


class _FakeCustomer:
    def __init__(self, customer_id, held, updates):
        self.id, self.updates = customer_id, updates
        self.subscriptions = _FakeSubscriptions(self, held)


class FakeMollieSdk:
    """``customers.get`` knows exact ids only: anything else (a whole "a, b" list) is refused."""

    def __init__(self, customers):
        self.asked, self.created, self.updates = [], [], []
        self._customers = {cid: _FakeCustomer(cid, held, self.updates) for cid, held in customers.items()}
        self.customers = self

    def get(self, customer_id):
        self.asked.append(customer_id)
        if customer_id not in self._customers:
            raise RuntimeError(f"Mollie: no customer {customer_id!r}")
        return self._customers[customer_id]

    def create(self, data):
        fresh = _FakeCustomer(f"cst_new{frappe.generate_hash(length=8)}", set(), self.updates)
        self._customers[fresh.id] = fresh
        self.created.append(fresh.id)
        return fresh


class Writers3251Base(MultiIdBase):
    def setUp(self):
        super().setUp()
        self.expectErrorLog("Mollie Client", "Mollie Subscription Update")
        self.sub_id = f"sub_{frappe.generate_hash(length=10)}"

    def _sdk_3251(self, customers):
        sdk = FakeMollieSdk(customers)
        from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import MollieSettings

        # Mock justified: the Mollie SDK is the external boundary, stubbed BELOW MollieClient/MollieGateway.
        patcher = patch.object(MollieSettings, "get_mollie_client", lambda _self: sdk)
        patcher.start()
        self.addCleanup(patcher.stop)
        return sdk

    def _field_3251(self, doctype, name):
        return frappe.db.get_value(doctype, name, "mollie_customer_id")


class TestUpdateSubscriptionAmountPerId(Writers3251Base):
    def _member_with_3251(self, *ids):
        member = self.members[0]
        self._set("Member", member.name, "mollie_customer_id", ", ".join(ids))
        self._set("Member", member.name, "mollie_subscription_id", self.sub_id)
        return member

    def test_subscription_under_the_second_listed_id_is_updated(self):
        self._member_with_3251(self.id_a, self.id_b)
        sdk = self._sdk_3251({self.id_a: set(), self.id_b: {self.sub_id}})
        result = pg.update_mollie_subscription_amount(self.sub_id, 12.5)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual([u[:2] for u in sdk.updates], [(self.id_b, self.sub_id)])
        self.assertNotIn(f"{self.id_a}, {self.id_b}", sdk.asked)

    def test_control_single_id_still_updates(self):
        self._member_with_3251(self.id_a)
        sdk = self._sdk_3251({self.id_a: {self.sub_id}})
        result = pg.update_mollie_subscription_amount(self.sub_id, 12.5)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual([u[:2] for u in sdk.updates], [(self.id_a, self.sub_id)])

    def test_control_subscription_under_no_listed_id_is_an_error_and_updates_nothing(self):
        self._member_with_3251(self.id_a, self.id_b)
        # The subscription sits under a customer the member does not list: a real candidate for a
        # pick-first / always-success wrong fix to wrongly touch.
        sdk = self._sdk_3251({self.id_a: set(), self.id_b: set(), self.id_c: {self.sub_id}})
        result = pg.update_mollie_subscription_amount(self.sub_id, 12.5)
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(sdk.updates, [])


class TestOwnerSubscriptionPerId(Writers3251Base):
    def setUp(self):
        super().setUp()
        original = frappe.db.get_single_value("Mollie Settings", "enable_subscriptions")
        frappe.db.set_single_value("Mollie Settings", "enable_subscriptions", 1)
        self.addCleanup(frappe.db.set_single_value, "Mollie Settings", "enable_subscriptions", original)

    def _create_sub_3251(self, owner_doctype, owner):
        customer_data = {
            "email": f"w3251.{frappe.generate_hash(length=6)}@example.com",
            "name": "W3251",
            "owner_doctype": owner_doctype,
            "owner_name": owner.name,
        }
        subscription_data = {
            "amount": {"value": "10.00", "currency": "EUR"},
            "interval": "1 month",
            "description": "w3251",
        }
        return CompletePaymentService().create_customer_subscription(customer_data, subscription_data)

    def _owner_with_3251(self, *ids, subscription=None):
        member = self.members[0]
        self._set("Member", member.name, "mollie_customer_id", ", ".join(ids))
        self._set("Member", member.name, "mollie_subscription_id", subscription)
        return member

    def test_live_subscription_under_the_second_listed_id_is_returned_not_duplicated(self):
        member = self._owner_with_3251(self.id_a, self.id_b, subscription=self.sub_id)
        sdk = self._sdk_3251({self.id_a: set(), self.id_b: {self.sub_id}})
        result = self._create_sub_3251("Member", member)
        self.assertEqual(result["message"], "Subscription already exists", result)
        self.assertEqual(result["customer_id"], self.id_b)
        self.assertEqual(sdk.created, [], "a duplicate Mollie customer was created")

    def test_stale_first_id_resolves_to_the_listed_second_id_and_keeps_the_list(self):
        member = self._owner_with_3251(self.id_a, self.id_b)
        sdk = self._sdk_3251({self.id_b: set()})
        result = self._create_sub_3251("Member", member)
        self.assertEqual(result["customer_id"], self.id_b, result)
        self.assertEqual(sdk.created, [], "a fresh customer was created although id_b resolves")
        self.assertEqual(self._field_3251("Member", member.name), f"{self.id_a}, {self.id_b}")

    def test_all_listed_ids_stale_creates_a_customer_and_appends_it_to_the_list(self):
        member = self._owner_with_3251(self.id_a, self.id_b)
        sdk = self._sdk_3251({})
        result = self._create_sub_3251("Member", member)
        self.assertEqual(sdk.created, [result["customer_id"]])
        self.assertEqual(
            self._field_3251("Member", member.name), f"{self.id_a}, {self.id_b}, {result['customer_id']}"
        )

    def test_control_single_stale_id_is_still_replaced_by_the_fresh_customer(self):
        member = self._owner_with_3251(self.id_a)
        sdk = self._sdk_3251({})
        result = self._create_sub_3251("Member", member)
        self.assertEqual(sdk.created, [result["customer_id"]])
        self.assertEqual(self._field_3251("Member", member.name), result["customer_id"])

    def test_control_single_id_resolves_and_is_unchanged(self):
        member = self._owner_with_3251(self.id_a)
        sdk = self._sdk_3251({self.id_a: set()})
        result = self._create_sub_3251("Member", member)
        self.assertEqual(result["customer_id"], self.id_a)
        self.assertEqual(sdk.created, [])
        self.assertEqual(self._field_3251("Member", member.name), self.id_a)


class TestDonorResolutionPerId(Writers3251Base):
    def _resolve_3251(self, donor):
        email = frappe.db.get_value("Donor", donor.name, "donor_email")
        return CompletePaymentService()._resolve_customer_by_email({"email": email, "name": "W3251"})

    def test_stale_first_id_resolves_to_the_listed_second_id(self):
        donor = self.donors[0]
        self._set("Donor", donor.name, "mollie_customer_id", f"{self.id_a}, {self.id_b}")
        sdk = self._sdk_3251({self.id_b: set()})
        result = self._resolve_3251(donor)
        self.assertEqual(result, {"status": "found", "customer_id": self.id_b})
        self.assertEqual(sdk.created, [])
        self.assertEqual(self._field_3251("Donor", donor.name), f"{self.id_a}, {self.id_b}")

    def test_all_listed_ids_stale_creates_a_customer_and_appends_it(self):
        donor = self.donors[0]
        self._set("Donor", donor.name, "mollie_customer_id", f"{self.id_a}, {self.id_b}")
        sdk = self._sdk_3251({})
        result = self._resolve_3251(donor)
        self.assertEqual(result["status"], "created")
        self.assertEqual(sdk.created, [result["customer_id"]])
        self.assertEqual(
            self._field_3251("Donor", donor.name), f"{self.id_a}, {self.id_b}, {result['customer_id']}"
        )

    def test_control_single_stale_id_is_still_replaced(self):
        donor = self.donors[0]
        self._set("Donor", donor.name, "mollie_customer_id", self.id_a)
        sdk = self._sdk_3251({})
        result = self._resolve_3251(donor)
        self.assertEqual(self._field_3251("Donor", donor.name), result["customer_id"])
        self.assertEqual(sdk.created, [result["customer_id"]])

    def test_control_single_id_found(self):
        donor = self.donors[0]
        self._set("Donor", donor.name, "mollie_customer_id", self.id_a)
        sdk = self._sdk_3251({self.id_a: set()})
        self.assertEqual(self._resolve_3251(donor), {"status": "found", "customer_id": self.id_a})
        self.assertEqual(sdk.created, [])
