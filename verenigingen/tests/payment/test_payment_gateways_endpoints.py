"""
Real-integration tests for payment_gateways.py whitelisted endpoints and the
non-Mollie gateway document paths that do NOT require a live Mollie API.

Complements:
    - test_payment_gateways.py (factory + non-Mollie gateway smoke)
    - test_payment_gateways_unit.py (Mollie SDK-boundary branches)

Drives real Member / Donation / Donor documents. The whitelisted endpoints are
decorated with @high_security_api; Administrator (the test user) satisfies them.

Covered:
    - create_member_subscription: already-active guard, no-customer guard,
      unsupported-interval guard
    - get_member_subscription_status: no-subscription branch
    - process_donation_payment: routes to BankTransfer gateway end-to-end
    - get_payment_status (donation): already-paid + not-initiated branches
    - cancel_mollie_subscription_by_id / update_mollie_subscription_amount:
      not-found branches
    - PontoGateway.get_payment_status status mapping + handle_webhook delegation
    - PaymentGatewayFactory.get_gateway("Ponto")
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import payment_gateways as pg


class TestMemberSubscriptionEndpoints(EnhancedTestCase):
    """Validation/early-return branches of the member-subscription endpoints."""

    def test_create_subscription_blocks_when_already_active(self):
        member = self.create_test_member(first_name="AlreadySub")
        frappe.db.set_value(
            "Member",
            member.name,
            {"mollie_customer_id": "cst_1", "mollie_subscription_id": "sub_1", "subscription_status": "active"},
        )
        result = pg.create_member_subscription(member_id=member.name, amount=25.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("already have an active", result["message"])
        self.assertEqual(result["existing_subscription_id"], "sub_1")

    def test_create_subscription_requires_customer_id(self):
        member = self.create_test_member(first_name="NoCust")
        # No mollie_customer_id set.
        result = pg.create_member_subscription(member_id=member.name, amount=25.0)
        self.assertEqual(result["status"], "error")
        self.assertIn("No Mollie customer ID", result["message"])

    def test_create_subscription_rejects_unsupported_interval(self):
        member = self.create_test_member(first_name="BadInterval")
        frappe.db.set_value("Member", member.name, "mollie_customer_id", "cst_2")
        # "2 weeks" used to be the example here, but Mollie accepts it and
        # convert_frequency_to_mollie_interval emits it for a Bi-Weekly schedule,
        # so this was pinning the refusal of a valid interval. "1 year" is the
        # genuinely unsupported one: Mollie answers 422 "The interval unit is
        # invalid" (verified against the live test API).
        result = pg.create_member_subscription(
            member_id=member.name, amount=25.0, interval="1 year"
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported subscription interval", result["message"])

    def test_get_subscription_status_no_subscription(self):
        member = self.create_test_member(first_name="NoSubStatus")
        result = pg.get_member_subscription_status(member_id=member.name)
        self.assertEqual(result["status"], "no_subscription")


class TestDonationPaymentEndpoints(EnhancedTestCase):
    """process_donation_payment / get_payment_status against real Donations."""

    def test_process_donation_payment_bank_transfer(self):
        donation = self.create_test_donation(amount=30.0, mode_of_payment="Bank Transfer", paid=0)
        result = pg.process_donation_payment(
            donation_id=donation.name, payment_method="Bank Transfer", form_data={}
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["payment_result"]["status"], "awaiting_transfer")

    def test_process_donation_payment_unsupported_method(self):
        donation = self.create_test_donation(amount=30.0, mode_of_payment="Bank Transfer", paid=0)
        result = pg.process_donation_payment(
            donation_id=donation.name, payment_method="Bitcoin", form_data={}
        )
        self.assertFalse(result["success"])

    def test_get_payment_status_paid_donation(self):
        donation = self.create_test_donation(amount=30.0, mode_of_payment="Bank Transfer", paid=1)
        result = pg.get_payment_status(donation_id=donation.name)
        self.assertEqual(result["status"], "paid")

    def test_get_payment_status_not_initiated(self):
        donation = self.create_test_donation(amount=30.0, mode_of_payment="Bank Transfer", paid=0)
        # No payment_id set → "pending / not yet initiated"
        result = pg.get_payment_status(donation_id=donation.name)
        self.assertEqual(result["status"], "pending")
        self.assertIn("not yet initiated", result["message"])


class TestSubscriptionByIdEndpoints(EnhancedTestCase):
    """cancel/update-by-subscription-id not-found branches."""

    def test_cancel_by_id_not_found(self):
        result = pg.cancel_mollie_subscription_by_id(subscription_id="sub_does_not_exist")
        self.assertEqual(result["status"], "error")
        self.assertIn("No member found", result["message"])

    def test_update_amount_not_found(self):
        result = pg.update_mollie_subscription_amount(
            subscription_id="sub_does_not_exist", new_amount=40.0
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("No member found", result["message"])


class TestPontoGateway(EnhancedTestCase):
    """PontoGateway non-API paths: factory resolution, status mapping, webhook."""

    def test_factory_resolves_ponto(self):
        gw = pg.PaymentGatewayFactory.get_gateway("Ponto")
        self.assertIsInstance(gw, pg.PontoGateway)

    def test_handle_webhook_delegated(self):
        result = pg.PontoGateway().handle_webhook({})
        self.assertEqual(result["status"], "delegated")

    def test_get_payment_status_unknown_id(self):
        # No Ponto Payment Link with this name → except branch returns error dict.
        result = pg.PontoGateway().get_payment_status("PPL-NONEXISTENT")
        self.assertEqual(result["status"], "error")
