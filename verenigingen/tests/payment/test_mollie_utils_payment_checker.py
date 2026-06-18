"""
Coverage for verenigingen_payments/mollie/utils/payment_checker.py.

This module exposes two whitelisted FINANCIAL endpoints used by Mollie debug
tooling (mollie_debug_service / mollie_payments_debug page /
mollie_bulk_payment_discovery page):

* check_subscription_payments - finds "Emma van Subscription", reads her
  customer/subscription ids, fetches the subscription + payments from Mollie,
  and returns the payments related to her.
* list_all_mollie_payments - lists the last 20 Mollie payments.

The Mollie boundary is reached via PaymentGatewayFactory.get_gateway(...).client,
which is patched with a fake gateway so no live Mollie API is touched. The error
branches (member not found, gateway error) are exercised against real Frappe.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.utils import payment_checker

_GET_GATEWAY = (
    "verenigingen.verenigingen_payments.mollie.utils.payment_checker.PaymentGatewayFactory.get_gateway"
)


def _payment(pid, status="paid", value="25.00", customer_id=None, subscription_id=None, member_id=None):
    return SimpleNamespace(
        id=pid,
        status=status,
        amount={"value": value, "currency": "EUR"},
        created_at="2026-06-10T10:00:00+00:00",
        description="Membership dues",
        method="directdebit",
        customer_id=customer_id,
        subscription_id=subscription_id,
        metadata={"member_id": member_id} if member_id else {},
    )


class _FakeSubscriptions:
    def __init__(self, subscription):
        self._subscription = subscription

    def get(self, subscription_id):
        return self._subscription


class _FakeMollieCustomer:
    def __init__(self, subscription):
        self.subscriptions = _FakeSubscriptions(subscription)


class _FakeCustomers:
    def __init__(self, subscription):
        self._subscription = subscription

    def get(self, customer_id):
        return _FakeMollieCustomer(self._subscription)


class _FakePayments:
    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=None):
        return self._payments


class _FakeClient:
    def __init__(self, subscription, payments):
        self.customers = _FakeCustomers(subscription)
        self.payments = _FakePayments(payments)


class _FakeGateway:
    def __init__(self, subscription=None, payments=None):
        self.client = _FakeClient(subscription, payments or [])


class _RaisingGateway:
    @property
    def client(self):
        raise RuntimeError("gateway exploded")


def _subscription(status="active"):
    return SimpleNamespace(
        status=status,
        next_payment_date="2026-07-01",
        amount={"value": "25.00", "currency": "EUR"},
    )


class TestCheckSubscriptionPayments(EnhancedTestCase):
    def _make_emma(self):
        """Create a member with the EXACT name 'Emma van Subscription' (the
        endpoint queries first_name/last_name verbatim) plus a Customer carrying
        the Mollie custom fields it reads.

        The shared factory appends a uniqueness suffix to last_name, which would
        break the endpoint's exact-name lookup, so the Member is inserted
        directly here with the literal name.
        """
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Emma {frappe.generate_hash(length=6)}",
                "customer_type": "Individual",
                "custom_mollie_customer_id": "cst_emmaSUB000001",
                "custom_mollie_subscription_id": "sub_emmaSUB000001",
            }
        ).insert()
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Emma",
                "last_name": "van Subscription",
                "email": f"emma-{frappe.generate_hash(length=8)}@example.com",
                "birth_date": "1990-01-01",
                "customer": customer.name,
            }
        ).insert()
        return member

    def test_member_not_found_returns_error(self):
        # No "Emma van Subscription" -> error branch. Guard against a stray one
        # left by a prior test by asserting only when truly absent.
        existing = frappe.get_all(
            "Member", filters={"first_name": "Emma", "last_name": "van Subscription"}, limit=1
        )
        if existing:
            self.skipTest("An Emma van Subscription already exists on this site")
        result = payment_checker.check_subscription_payments()
        self.assertIn("error", result)

    def test_returns_related_payments(self):
        self._make_emma()
        related = _payment("tr_related", customer_id="cst_emmaSUB000001")
        unrelated = _payment("tr_other", customer_id="cst_OTHER")
        gateway = _FakeGateway(subscription=_subscription(), payments=[related, unrelated])

        with patch(_GET_GATEWAY, return_value=gateway):
            result = payment_checker.check_subscription_payments()

        self.assertTrue(result["success"])
        self.assertEqual(result["customer_id"], "cst_emmaSUB000001")
        self.assertEqual(result["subscription_status"], "active")
        ids = [p["id"] for p in result["subscription_payments"]]
        self.assertIn("tr_related", ids)
        self.assertNotIn("tr_other", ids)

    def test_matches_by_subscription_id(self):
        self._make_emma()
        by_sub = _payment("tr_sub", subscription_id="sub_emmaSUB000001")
        gateway = _FakeGateway(subscription=_subscription(), payments=[by_sub])

        with patch(_GET_GATEWAY, return_value=gateway):
            result = payment_checker.check_subscription_payments()

        self.assertEqual([p["id"] for p in result["subscription_payments"]], ["tr_sub"])

    def test_no_related_payments(self):
        self._make_emma()
        gateway = _FakeGateway(subscription=_subscription(), payments=[_payment("tr_x", customer_id="cst_Z")])

        with patch(_GET_GATEWAY, return_value=gateway):
            result = payment_checker.check_subscription_payments()

        self.assertTrue(result["success"])
        self.assertEqual(result["subscription_payments"], [])

    def test_gateway_error_returns_error(self):
        self._make_emma()
        with patch(_GET_GATEWAY, return_value=_RaisingGateway()):
            result = payment_checker.check_subscription_payments()
        self.assertIn("error", result)


class TestListAllMolliePayments(EnhancedTestCase):
    def test_lists_payments(self):
        payments = [_payment("tr_1"), _payment("tr_2", status="open")]
        gateway = _FakeGateway(payments=payments)

        with patch(_GET_GATEWAY, return_value=gateway):
            result = payment_checker.list_all_mollie_payments()

        self.assertTrue(result["success"])
        self.assertEqual(len(result["payments"]), 2)
        self.assertEqual(result["payments"][0]["id"], "tr_1")
        self.assertEqual(result["payments"][0]["amount"], "EUR 25.00")

    def test_gateway_error_returns_error(self):
        with patch(_GET_GATEWAY, return_value=_RaisingGateway()):
            result = payment_checker.list_all_mollie_payments()
        self.assertIn("error", result)
