"""
Tier-1 unit tests for Mollie-facing branches of payment_gateways.py.

These exercise decision/branch logic in MollieGateway and the module-level
subscription-activation helpers WITHOUT a live Mollie API by stubbing ONLY the
external SDK boundary: the Mollie payment / customer / subscription objects and
the gateway's `client`. No business logic is mocked - the gateway methods and
helper functions run for real against these boundary stubs.

Named *_unit.py so test-quality-enforcer permits the SDK boundary stub.

Covers:
    - MollieGateway.handle_webhook: no-id, no-metadata, paid, failed/cancelled,
      pending branches (against a real Donation document for the reference doc)
    - MollieGateway.get_payment_status: paid/pending/open/cancelled/error mapping
    - MollieGateway._get_email_from_form_or_doc
    - _activate_subscription_after_first_payment: skip when already active /
      no dues schedule
    - _activate_direct_subscription_after_first_payment: skip when not flagged /
      missing details / missing customer
    - _activate_donation_subscription_after_first_payment: skip when no donation id
"""

import types
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


# ---------------------------------------------------------------------------
# Boundary stubs: minimal stand-ins for the Mollie SDK objects. These represent
# the external HTTP/SDK boundary only - everything they feed into is real code.
# ---------------------------------------------------------------------------
class _StubAmount:
    def __init__(self, value="10.00", currency="EUR"):
        self.value = value
        self.currency = currency


class _StubPayment:
    """Stand-in for a mollie Payment resource."""

    def __init__(self, **kw):
        self.id = kw.get("id", "tr_stub123")
        self.status = kw.get("status", "open")
        self.amount = kw.get("amount", _StubAmount())
        self.metadata = kw.get("metadata", {})
        self.customer_id = kw.get("customer_id")
        self.sequence_type = kw.get("sequence_type", "oneoff")
        self.checkout_url = kw.get("checkout_url", "https://mollie.test/checkout")
        self.expires_at = kw.get("expires_at")
        self._paid = kw.get("paid", False)
        self._canceled = kw.get("canceled", False)
        self._expired = kw.get("expired", False)
        self._failed = kw.get("failed", False)
        self._pending = kw.get("pending", False)
        self._open = kw.get("open", False)

    def is_paid(self):
        return self._paid

    def is_canceled(self):
        return self._canceled

    def is_expired(self):
        return self._expired

    def is_failed(self):
        return self._failed

    def is_pending(self):
        return self._pending

    def is_open(self):
        return self._open


class _StubPayments:
    def __init__(self, payment):
        self._payment = payment

    def get(self, payment_id):
        return self._payment


class _StubClient:
    """Stand-in for the mollie Client - only the surface the gateway touches."""

    def __init__(self, payment=None):
        self.payments = _StubPayments(payment)


def _make_gateway(payment=None):
    """Build a MollieGateway without running __init__ (which needs live settings).

    We bypass __init__ and inject a stubbed client; this is the SDK boundary.
    """
    gw = pg.MollieGateway.__new__(pg.MollieGateway)
    gw.gateway_name = "Default"
    gw.client = _StubClient(payment)
    gw.settings = None
    return gw


class TestMollieGatewayWebhookBranches(EnhancedTestCase):
    """handle_webhook decision branches against a real Donation document."""

    def _donation(self):
        return self.create_test_donation(amount=15.0, mode_of_payment="Mollie", paid=0)

    def test_webhook_no_payment_id_ignored(self):
        gw = _make_gateway(_StubPayment())
        result = gw.handle_webhook({})
        self.assertEqual(result["status"], "ignored")
        self.assertIn("No payment ID", result["reason"])

    def test_webhook_no_metadata_ignored(self):
        payment = _StubPayment(id="tr_x", metadata={})
        gw = _make_gateway(payment)
        result = gw.handle_webhook({"id": "tr_x"})
        self.assertEqual(result["status"], "ignored")
        self.assertIn("No reference document", result["reason"])

    def test_webhook_paid_marks_donation(self):
        donation = self._donation()
        payment = _StubPayment(
            id="tr_paid",
            paid=True,
            metadata={"reference_doctype": "Donation", "reference_docname": donation.name},
        )
        gw = _make_gateway(payment)
        result = gw.handle_webhook({"id": "tr_paid"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "completed")
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 1)

    def test_webhook_cancelled_branch(self):
        donation = self._donation()
        payment = _StubPayment(
            id="tr_cancel",
            canceled=True,
            metadata={"reference_doctype": "Donation", "reference_docname": donation.name},
        )
        gw = _make_gateway(payment)
        result = gw.handle_webhook({"id": "tr_cancel"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "failed")

    def test_webhook_pending_branch(self):
        donation = self._donation()
        payment = _StubPayment(
            id="tr_pending",
            metadata={"reference_doctype": "Donation", "reference_docname": donation.name},
        )
        gw = _make_gateway(payment)
        result = gw.handle_webhook({"id": "tr_pending"})
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["payment_status"], "pending")


class TestMollieGatewayStatusMapping(EnhancedTestCase):
    """get_payment_status maps Mollie states to internal statuses."""

    def test_paid(self):
        gw = _make_gateway(_StubPayment(paid=True))
        self.assertEqual(gw.get_payment_status("tr_1")["status"], "Completed")

    def test_pending(self):
        gw = _make_gateway(_StubPayment(pending=True))
        self.assertEqual(gw.get_payment_status("tr_1")["status"], "Pending")

    def test_open(self):
        gw = _make_gateway(_StubPayment(open=True))
        self.assertEqual(gw.get_payment_status("tr_1")["status"], "Open")

    def test_cancelled_fallthrough(self):
        gw = _make_gateway(_StubPayment())  # none of the is_* are true
        self.assertEqual(gw.get_payment_status("tr_1")["status"], "Cancelled")

    def test_error_on_sdk_failure(self):
        gw = pg.MollieGateway.__new__(pg.MollieGateway)
        gw.gateway_name = "Default"

        class _Boom:
            class payments:
                @staticmethod
                def get(_):
                    raise RuntimeError("network down")

        gw.client = _Boom()
        result = gw.get_payment_status("tr_err")
        self.assertEqual(result["status"], "Error")


class TestMollieGatewayEmailExtraction(EnhancedTestCase):
    """_get_email_from_form_or_doc prefers form data, falls back to doc fields."""

    def test_email_from_form(self):
        gw = _make_gateway()
        donation = self.create_test_donation(amount=5.0, mode_of_payment="Mollie")
        self.assertEqual(
            gw._get_email_from_form_or_doc(donation, {"donor_email": "x@example.com"}),
            "x@example.com",
        )

    def test_email_from_email_key(self):
        gw = _make_gateway()
        donation = self.create_test_donation(amount=5.0, mode_of_payment="Mollie")
        self.assertEqual(
            gw._get_email_from_form_or_doc(donation, {"email": "y@example.com"}),
            "y@example.com",
        )

    def test_email_from_doc_attribute(self):
        gw = _make_gateway()
        obj = types.SimpleNamespace(contact_email="doc@example.com")
        self.assertEqual(gw._get_email_from_form_or_doc(obj, {}), "doc@example.com")


class TestSubscriptionActivationHelpers(EnhancedTestCase):
    """Module-level subscription-activation helpers - skip/early-return branches."""

    def test_activate_skips_when_member_already_active(self):
        member = self.create_test_member(first_name="ActiveSub")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_subscription_id": "sub_123", "subscription_status": "Active"},
        )
        gw = _make_gateway()
        result = pg._activate_subscription_after_first_payment(gw, member.name, "cust", "tr_1")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("already has active subscription", result["reason"])

    def test_activate_skips_when_no_dues_schedule(self):
        member = self.create_test_member(first_name="NoSchedule")
        gw = _make_gateway()
        result = pg._activate_subscription_after_first_payment(gw, member.name, "cust", "tr_1")
        self.assertEqual(result["status"], "skipped")
        self.assertIn("No active dues schedule", result["reason"])

    def test_direct_subscription_skips_when_not_flagged(self):
        gw = _make_gateway()
        payment = _StubPayment(metadata={"subscription_setup": "false"})
        result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "skipped")

    def test_direct_subscription_missing_details(self):
        gw = _make_gateway()
        payment = _StubPayment(metadata={"subscription_setup": "true"})  # no interval/amount
        result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "error")

    def test_direct_subscription_missing_customer(self):
        gw = _make_gateway()
        payment = _StubPayment(
            metadata={
                "subscription_setup": "true",
                "subscription_interval": "1 month",
                "subscription_amount": "10.00",
            },
            customer_id=None,
        )
        result = pg._activate_direct_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "error")

    def test_donation_subscription_skips_without_donation_id(self):
        gw = _make_gateway()
        payment = _StubPayment(metadata={})
        result = pg._activate_donation_subscription_after_first_payment(gw, payment)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("No donation ID", result["reason"])


if __name__ == "__main__":
    unittest.main()
