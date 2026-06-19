"""
Real-integration tests for the refund utility (refund_utility.py).

Complements verenigingen_payments/mollie/tests/test_refund_chargeback.py (which
covers the happy-path refund/chargeback webhook flow) by exercising the
UNCOVERED validation helpers and error-branch surface of:
    initiate_refund, get_payment_refund_info, get_donation_refund_info,
    initiate_donation_refund, validate_refund_permissions.

Most branches need NO Mollie HTTP at all (they reject before the API call).
The one place a Mollie call would happen, the outbound MolliePaymentService is
mocked at the seam used by the production test suite.

Mock justified: MolliePaymentService.create_refund() performs an outbound HTTP
call to Mollie. It is patched only where the refund path would actually invoke
it; all validation/aggregation logic under test runs for real against the DB.
"""

import math
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.tests.mollie_test_helper import (
    ensure_mollie_reversal_accounts,
)
from verenigingen.verenigingen_payments.utils.payment_services.refund_utility import (
    get_donation_refund_info,
    get_payment_refund_info,
    initiate_donation_refund,
    initiate_refund,
    validate_refund_permissions,
)

REFUND_MODULE = "verenigingen.verenigingen_payments.utils.payment_services.refund_utility"


def _make_supplier(test_case):
    """Create a real Supplier party for Pay-type reversal Payment Entries."""
    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = f"Refund Test Supplier {frappe.generate_hash(length=6)}"
    supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
    supplier.save()
    test_case.track_doc("Supplier", supplier.name)
    return supplier.name


class TestRefundUtilityValidation(EnhancedTestCase):
    """Validation-helper and early-return branches that need no Mollie API."""

    def test_missing_payment_entry_name(self):
        result = initiate_refund(payment_entry_name="")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "MISSING_PAYMENT_ENTRY")

    def test_payment_entry_not_found(self):
        result = initiate_refund(payment_entry_name="PE-DOES-NOT-EXIST-9999")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "PAYMENT_ENTRY_NOT_FOUND")

    def test_nan_amount_rejected(self):
        # _validate_float_amount runs before fetching the document
        result = initiate_refund(payment_entry_name="PE-X", amount=float("nan"))
        self.assertEqual(result["error_code"], "INVALID_AMOUNT_VALUE")

    def test_infinite_amount_rejected(self):
        result = initiate_refund(payment_entry_name="PE-X", amount=math.inf)
        self.assertEqual(result["error_code"], "INVALID_AMOUNT_VALUE")

    def test_reason_too_long_rejected(self):
        result = initiate_refund(payment_entry_name="PE-X", amount=10.0, reason="z" * 300)
        self.assertEqual(result["error_code"], "DESCRIPTION_TOO_LONG")

    def test_non_receive_payment_rejected(self):
        # A "Pay" type payment cannot be refunded
        pe = self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=50.0,
            reference_no="tr_some_payment",
            party_type="Supplier",
            party=_make_supplier(self),
        )
        result = initiate_refund(payment_entry_name=pe.name)
        self.assertEqual(result["error_code"], "INVALID_PAYMENT_TYPE")

    def test_non_mollie_reference_rejected(self):
        pe = self.create_test_payment_entry(
            payment_type="Receive", paid_amount=50.0, reference_no="BANK-12345"
        )
        result = initiate_refund(payment_entry_name=pe.name)
        self.assertEqual(result["error_code"], "NOT_MOLLIE_PAYMENT")

    def test_amount_exceeds_payment_rejected(self):
        pe = self.create_test_payment_entry(
            payment_type="Receive", paid_amount=50.0, reference_no="tr_test_exceed"
        )
        result = initiate_refund(payment_entry_name=pe.name, amount=999.0)
        self.assertEqual(result["error_code"], "AMOUNT_EXCEEDS_PAYMENT")

    def test_amount_below_minimum_rejected(self):
        pe = self.create_test_payment_entry(
            payment_type="Receive", paid_amount=50.0, reference_no="tr_test_min"
        )
        result = initiate_refund(payment_entry_name=pe.name, amount=0.0)
        # 0.0 is below MIN_REFUND_AMOUNT (0.01)
        self.assertEqual(result["error_code"], "INVALID_AMOUNT")


class TestRefundUtilityInitiation(EnhancedTestCase):
    """Branches reaching (or guarding against) the Mollie create_refund call."""

    def setUp(self):
        super().setUp()
        ensure_mollie_reversal_accounts()
        self.payment_id = f"tr_init_{frappe.generate_hash(length=8)}"
        self.pe = self.create_test_payment_entry(
            payment_type="Receive", paid_amount=100.0, reference_no=self.payment_id
        )

    def test_successful_refund_initiation(self):
        with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie:
            mock_mollie.return_value.create_refund.return_value = {
                "status": "success",
                "refund_id": "re_test_123",
                "amount": 40.0,
            }
            result = initiate_refund(payment_entry_name=self.pe.name, amount=40.0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["refund_id"], "re_test_123")
        self.assertEqual(result["data"]["payment_entry"], self.pe.name)

    def test_default_amount_uses_full_payment(self):
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return {"status": "success", "refund_id": "re_full", "amount": kwargs["amount"]}

        with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie:
            mock_mollie.return_value.create_refund.side_effect = _capture
            result = initiate_refund(payment_entry_name=self.pe.name)  # no amount
        self.assertEqual(result["status"], "success")
        self.assertEqual(captured["amount"], 100.0)

    def test_mollie_failure_response_passed_through(self):
        with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie:
            mock_mollie.return_value.create_refund.return_value = {
                "status": "error",
                "message": "Mollie rejected",
            }
            result = initiate_refund(payment_entry_name=self.pe.name, amount=10.0)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Mollie rejected")

    def test_over_refund_blocked_by_existing_reversal(self):
        # Create a submitted Pay-type reversal consuming 70 of the 100
        self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=70.0,
            reference_no="re_existing_70",
            party_type="Supplier",
            party=_make_supplier(self),
            custom_original_payment_id=self.payment_id,
            custom_reversal_type="Refund",
            submit=True,
        )
        # Only 30 remains; requesting 50 must be blocked BEFORE any Mollie call
        with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie:
            result = initiate_refund(payment_entry_name=self.pe.name, amount=50.0)
            mock_mollie.return_value.create_refund.assert_not_called()
        self.assertEqual(result["error_code"], "INSUFFICIENT_REFUNDABLE_AMOUNT")
        self.assertEqual(result["details"]["total_reversed"], 70.0)


class TestPaymentRefundInfo(EnhancedTestCase):
    def test_payment_not_found(self):
        result = get_payment_refund_info("PE-MISSING-9999")
        self.assertEqual(result["error_code"], "PAYMENT_ENTRY_NOT_FOUND")

    def test_non_mollie_payment(self):
        pe = self.create_test_payment_entry(payment_type="Receive", paid_amount=50.0, reference_no="BANK-REF")
        result = get_payment_refund_info(pe.name)
        self.assertEqual(result["error_code"], "NOT_MOLLIE_PAYMENT")

    def test_refund_info_aggregation(self):
        payment_id = f"tr_info_{frappe.generate_hash(length=8)}"
        pe = self.create_test_payment_entry(
            payment_type="Receive", paid_amount=100.0, reference_no=payment_id
        )
        self.create_test_payment_entry(
            payment_type="Pay",
            paid_amount=20.0,
            reference_no="re_info_1",
            party_type="Supplier",
            party=_make_supplier(self),
            custom_original_payment_id=payment_id,
            custom_reversal_type="Refund",
            submit=True,
        )
        result = get_payment_refund_info(pe.name)
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertEqual(data["original_amount"], 100.0)
        self.assertEqual(data["total_refunded"], 20.0)
        self.assertEqual(data["available_amount"], 80.0)
        self.assertTrue(data["can_refund"])
        self.assertEqual(len(data["refund_history"]), 1)


class TestDonationRefundInfo(EnhancedTestCase):
    def test_donation_not_found(self):
        result = get_donation_refund_info("DONATION-MISSING-9999")
        self.assertEqual(result["error_code"], "DONATION_NOT_FOUND")

    def test_donation_with_no_payment_entries(self):
        donation = self.create_test_donation(amount=50.0)
        # Ensure no PE links to it
        result = get_donation_refund_info(donation.name)
        self.assertEqual(result["error_code"], "NO_PAYMENT_ENTRIES")

    def test_donation_refund_aggregation(self):
        donation = self.create_test_donation(amount=100.0)
        payment_id = f"tr_don_{frappe.generate_hash(length=8)}"
        self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no=payment_id,
            custom_donation=donation.name,
            submit=True,
        )
        result = get_donation_refund_info(donation.name)
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertEqual(data["total_paid"], 100.0)
        self.assertEqual(data["net_amount"], 100.0)
        self.assertTrue(data["can_refund"])  # mollie ref + positive net


class TestInitiateDonationRefund(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        ensure_mollie_reversal_accounts()

    def test_donation_not_refundable(self):
        # Donation whose only payment is non-Mollie -> can_refund False
        donation = self.create_test_donation(amount=100.0)
        self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no="BANK-NONMOLLIE",
            custom_donation=donation.name,
            submit=True,
        )
        result = initiate_donation_refund(donation.name)
        self.assertEqual(result["error_code"], "DONATION_NOT_REFUNDABLE")

    def test_donation_refund_routes_to_mollie(self):
        donation = self.create_test_donation(amount=100.0)
        payment_id = f"tr_dref_{frappe.generate_hash(length=8)}"
        self.create_test_payment_entry(
            payment_type="Receive",
            paid_amount=100.0,
            reference_no=payment_id,
            custom_donation=donation.name,
            submit=True,
        )
        with patch(f"{REFUND_MODULE}.MolliePaymentService") as mock_mollie:
            mock_mollie.return_value.create_refund.return_value = {
                "status": "success",
                "refund_id": "re_don_ok",
                "amount": 40.0,
            }
            result = initiate_donation_refund(donation.name, amount=40.0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["refund_id"], "re_don_ok")


class TestRefundPermissions(EnhancedTestCase):
    def test_administrator_can_refund(self):
        # Administrator has write on Payment Entry and admin roles -> True
        self.assertTrue(validate_refund_permissions("Administrator"))

    def test_guest_cannot_refund(self):
        self.assertFalse(validate_refund_permissions("Guest"))

    def test_defaults_to_session_user(self):
        # Running as Administrator in tests; no arg -> uses session user, who has
        # refund permission -> True (assertIsInstance(bool) would pass on False too).
        result = validate_refund_permissions()
        self.assertTrue(result)
