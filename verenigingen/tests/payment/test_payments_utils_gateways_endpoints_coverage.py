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

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles
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

    def test_duplicate_reference_is_rejected_without_marking_the_donation_paid(self):
        """A repeated reference must fail cleanly, not half-commit.

        payment_id is unique (#345), so an operator reusing a reference now
        raises 1062 inside this endpoint. The bug this guards: with db_set("paid")
        running first, paid=1 was already written when the duplicate raised;
        MariaDB does not roll back on 1062 and the except-branch returns
        success:False without undoing it, so the request's own commit landed
        paid=1 on a donation the caller had been told failed.
        """
        self.expectErrorLog("Payment Confirmation")
        reference = f"MANUAL-DUP-{frappe.generate_hash(length=8)}"

        first = self.create_test_donation(paid=0, mode_of_payment="Bank Transfer")
        self.assertTrue(pg.manual_payment_confirmation(first.name, reference)["success"])

        second = self.create_test_donation(paid=0, mode_of_payment="Bank Transfer")
        result = pg.manual_payment_confirmation(second.name, reference)

        self.assertFalse(result["success"], "a reused payment reference must not report success")
        self.assertIn(first.name, result["message"], "the error should name the donation that owns it")

        # The point of the fix: nothing was written to the loser.
        self.assertEqual(
            frappe.db.get_value("Donation", second.name, "paid"),
            0,
            "paid must not be set when the reference was rejected",
        )
        self.assertIsNone(frappe.db.get_value("Donation", second.name, "payment_id"))
        # ...and the winner is untouched.
        self.assertEqual(frappe.db.get_value("Donation", first.name, "payment_id"), reference)


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


class TestUpdateSubscriptionAmountOwnership(EnhancedTestCase):
    """update_mollie_subscription_amount enforces ownership on subscription_id (#957).

    subscription_id is caller-supplied; get_member_by_subscription_id looks it
    up but performs no ownership check of its own. Per #965's role-profile
    measurement, the reachable population for this HIGH-level endpoint is
    board/staff/treasurer level, not only System-Manager-style admins, so the
    attacker here holds a real non-admin role profile ("Verenigingen Chapter
    Board Member") that clears the endpoint's security level but must still be
    refused someone else's subscription.
    """

    class _StubGateway:
        def update_subscription(self, customer_id, subscription_id, payload):
            return {"status": "success"}

    def _board_member_user(self):
        """A non-admin user whose Role Profile clears the HIGH security level.

        Mirrors payment_dashboard.py's own board-member probe added for the
        sibling #957-adjacent fix (PR #974): "Verenigingen Chapter Board
        Member" satisfies Rule 4 of the authorization policy (HIGH access via
        role profile) but holds none of Roles.ADMIN_ROLES, isolating the
        ownership check under test from the separate (already-covered)
        security-level gate.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        user_email = f"board.subprobe.{frappe.generate_hash(length=8)}@example.com".lower()
        frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Board",
                "last_name": "SubProbe",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        ).insert()
        grant_matching_role_profiles(user_email, "Verenigingen Chapter Board Member")

        attacker_member = self.create_test_member(
            first_name="Board", last_name="SubProbe", status="Active"
        )
        frappe.db.set_value("Member", attacker_member.name, "user", user_email)

        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: attacker must NOT hold an admin role",
        )
        return user_email, attacker_member.name

    def test_update_amount_refuses_foreign_subscription_for_non_admin_board_role(self):
        victim = self.create_test_member(first_name="SubAmtVictim")
        frappe.db.set_value(
            "Member",
            victim.name,
            {"mollie_customer_id": "cst_victim", "mollie_subscription_id": "sub_victim_amt"},
        )
        user_email, _attacker_member = self._board_member_user()

        with self.set_user(user_email):
            with self.assertRaises(frappe.PermissionError):
                pg.update_mollie_subscription_amount(
                    subscription_id="sub_victim_amt", new_amount=999.0
                )

        # The victim's subscription id is unchanged and no gateway call was
        # attempted on their behalf.
        self.assertEqual(
            frappe.db.get_value("Member", victim.name, "mollie_subscription_id"),
            "sub_victim_amt",
        )

    def test_update_amount_allows_own_subscription_for_non_admin_board_role(self):
        # Same non-admin board-profile user, managing THEIR OWN subscription,
        # must still succeed -- the ownership fix must not break self-service
        # for the population that legitimately reaches this endpoint.
        user_email, attacker_member = self._board_member_user()
        frappe.db.set_value(
            "Member",
            attacker_member,
            {"mollie_customer_id": "cst_self", "mollie_subscription_id": "sub_self_amt"},
        )
        with self.set_user(user_email):
            with patch.object(
                pg.PaymentGatewayFactory, "get_gateway", return_value=self._StubGateway()
            ):
                result = pg.update_mollie_subscription_amount(
                    subscription_id="sub_self_amt", new_amount=30.0
                )
        self.assertEqual(result["status"], "success", result)


class TestCancelByIdOwnership(EnhancedTestCase):
    """cancel_mollie_subscription_by_id (the #957 sibling #965 flagged) already
    delegates ownership enforcement to cancel_member_subscription()'s own
    validate_member_ownership() call -- confirmed empirically here rather than
    assumed from reading the code, since #965's own census claimed this
    function had "no ownership check" (it resolves subscription_id via the
    identical get_member_by_subscription_id lookup, same as
    update_mollie_subscription_amount). Reading the delegation
    (`return cancel_member_subscription(member_id)`) shows the check DOES run;
    this test is the control that proves it actually fires for this entry
    point, not just for direct calls to cancel_member_subscription().
    """

    def test_cancel_by_id_refuses_foreign_subscription_for_non_admin_board_role(self):
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        victim = self.create_test_member(first_name="SubCancelVictim")
        frappe.db.set_value(
            "Member",
            victim.name,
            {"mollie_customer_id": "cst_cvictim", "mollie_subscription_id": "sub_cvictim"},
        )

        user_email = f"board.cancelprobe.{frappe.generate_hash(length=8)}@example.com".lower()
        frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Board",
                "last_name": "CancelProbe",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        ).insert()
        grant_matching_role_profiles(user_email, "Verenigingen Chapter Board Member")
        attacker_member = self.create_test_member(
            first_name="Board", last_name="CancelProbe", status="Active"
        )
        frappe.db.set_value("Member", attacker_member.name, "user", user_email)

        with self.set_user(user_email):
            # Read roles AFTER the switch: a pre-switch read can resolve
            # through the stale cache of the previous session user
            # (cache-guard-validator).
            self.assertFalse(
                set(frappe.get_roles()) & Roles.ADMIN_ROLES,
                "test setup: attacker must NOT hold an admin role",
            )
            result = pg.cancel_mollie_subscription_by_id(subscription_id="sub_cvictim")

        # cancel_mollie_subscription_by_id's own except-Exception wrapper
        # catches the PermissionError raised deep inside
        # cancel_member_subscription() and turns it into an error dict rather
        # than letting it propagate -- so the observable contract here is
        # "not success", not a raised exception.
        self.assertEqual(result.get("status"), "error", result)


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
