"""
Gap-fill coverage for verenigingen_payments/utils/payment_gateways.py
whitelisted endpoints and helper paths NOT exercised by the existing
test_payment_gateways*.py suite.

Complements (does NOT duplicate):
    - test_payment_gateways_endpoints.py (create/get/cancel/update subscription
      validation branches, process_donation_payment bank-transfer route)
    - test_payment_gateways_coverage.py / _unit.py (Mollie SDK-boundary branches)
    - test_payment_gateways_sepa_ponto_coverage.py (SEPA/Ponto document paths)

Covered here (all real-DB, no business-logic mocks):
    - manual_payment_confirmation: nonexistent-donation failure branch, and the
      happy path on a submitted donation (regression guard for the db_set fix)
    - cancel_member_subscription: ownership-validation throw for a foreign member
    - get_member_subscription_status: gateway-construction failure converted to a
      structured error response (no live Mollie settings)
    - _authenticate_and_parse_subscription_payload: unsigned/garbage payload
      returns an error tuple (auth short-circuit) via a real frappe.request

FIXED BUG (regression-guarded below): manual_payment_confirmation
(payment_gateways.py:2160) previously did `donation.paid = 1; donation.save()`.
Neither paid nor payment_id is allow_on_submit, so for a *submitted* donation
(the normal post-creation state — there are submitted donations in production)
save() raised "Not allowed to change ... after submission" and the endpoint
silently returned {"success": False}. Now uses db_set (the controller's own
canonical pattern) so it works regardless of docstatus.

Mollie HTTP calls are OUT OF SCOPE (no live token) so subscription-creation
success paths are not driven here.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


class TestManualPaymentConfirmation(EnhancedTestCase):
    """manual_payment_confirmation observable branches (real Donation docs)."""

    def test_confirmation_nonexistent_donation_returns_failure(self):
        # get_doc raises DoesNotExistError -> caught -> {"success": False}
        self.expectErrorLog("Payment Confirmation")
        result = pg.manual_payment_confirmation(
            donation_id="Donation-DOES-NOT-EXIST",
            payment_reference="X",
        )
        self.assertFalse(result["success"])

    def test_confirmation_on_submitted_donation_succeeds_and_persists(self):
        # Regression guard for the db_set fix: the factory produces a SUBMITTED
        # donation (docstatus=1), the normal production state. manual confirmation
        # must succeed and persist paid + payment_id (previously save() threw
        # "after submission" and the endpoint silently returned success:False).
        donation = self.create_test_donation(paid=0, mode_of_payment="Bank Transfer")
        result = pg.manual_payment_confirmation(
            donation_id=donation.name,
            payment_reference="MANUAL-REF-001",
            notes="paid via bank transfer",
        )
        self.assertTrue(result["success"])
        # Persisted to the DB despite the submitted state.
        self.assertEqual(frappe.db.get_value("Donation", donation.name, "paid"), 1)
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "payment_id"), "MANUAL-REF-001"
        )


class TestCancelMemberSubscriptionOwnership(EnhancedTestCase):
    """cancel_member_subscription enforces self-service ownership."""

    def test_cancel_foreign_member_blocked_by_ownership(self):
        member = self.create_test_member(first_name="OwnedSub")
        other = self.create_test_member(first_name="OtherUser")
        if not other.user:
            self.skipTest("test member has no linked user to assert ownership against")
        # Acting as a different member's user must not be allowed to cancel
        # someone else's subscription (validate_member_ownership throws).
        with self.as_user(other.user):
            with self.assertRaises(frappe.PermissionError):
                pg.cancel_member_subscription(member_id=member.name)


class TestGetMemberSubscriptionStatusGatewayError(EnhancedTestCase):
    """
    get_member_subscription_status with subscription ids set but no usable Mollie
    settings hits the gateway-construction failure path, which the endpoint
    converts into a structured error response (never raises).
    """

    def test_status_with_ids_but_no_live_gateway_returns_error_dict(self):
        member = self.create_test_member(first_name="StatusMember")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_x", "mollie_subscription_id": "sub_x"},
        )
        self.expectErrorLog("Member Subscription Status", "Mollie")
        result = pg.get_member_subscription_status(member_id=member.name)
        self.assertIsInstance(result, dict)
        # Must hit the gateway-construction error branch specifically (not the
        # no_subscription branch — ids ARE set here).
        self.assertEqual(result.get("status"), "error")

    def test_status_without_subscription_returns_no_subscription(self):
        member = self.create_test_member(first_name="NoSubMember")
        result = pg.get_member_subscription_status(member_id=member.name)
        self.assertEqual(result["status"], "no_subscription")


class TestSubscriptionPayloadParsing(EnhancedTestCase):
    """
    _authenticate_and_parse_subscription_payload short-circuits with an error
    tuple when the webhook cannot be authenticated. Driven through a real
    frappe.request so authenticate_mollie_webhook reads genuine bytes (no Mollie
    HTTP involved).
    """

    def _set_request(self, body: bytes):
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        builder = EnvironBuilder(method="POST", data=body)
        frappe.local.request = Request(builder.get_environ())

    def test_unsigned_payload_returns_error_tuple(self):
        self._set_request(b"not a json or form payload at all")
        self.expectErrorLog("Webhook", "Mollie", "Subscription")
        parsed, error_response = pg._authenticate_and_parse_subscription_payload()
        self.assertIsNone(parsed)
        self.assertIsInstance(error_response, dict)
