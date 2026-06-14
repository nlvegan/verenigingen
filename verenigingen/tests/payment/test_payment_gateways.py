"""
Real tests for the payment-gateway abstraction layer.

Exercises the gateway factory and the non-Mollie gateway implementations against
real Donation / Donor documents (no mocking). The Mollie gateway requires live
API credentials so it is only smoke-checked for class resolution, not driven.

Covers verenigingen/verenigingen_payments/utils/payment_gateways.py:
    - PaymentGatewayFactory.get_gateway / get_supported_methods
    - BankTransferGateway.process_payment / handle_webhook / get_payment_status
    - CashGateway.process_payment / handle_webhook / get_payment_status
    - SEPAGateway.process_payment (IBAN-required + invalid-IBAN guard),
      _validate_iban, _calculate_collection_date
"""

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    BankTransferGateway,
    CashGateway,
    PaymentGatewayFactory,
    SEPAGateway,
)


class TestPaymentGatewayFactory(EnhancedTestCase):
    """Factory resolution of payment methods."""

    def test_supported_methods_list(self):
        methods = PaymentGatewayFactory.get_supported_methods()
        for expected in ("Bank Transfer", "Mollie", "Ponto", "SEPA Direct Debit", "Cash"):
            self.assertIn(expected, methods)

    def test_get_non_mollie_gateways(self):
        self.assertIsInstance(PaymentGatewayFactory.get_gateway("Bank Transfer"), BankTransferGateway)
        self.assertIsInstance(PaymentGatewayFactory.get_gateway("Cash"), CashGateway)
        self.assertIsInstance(PaymentGatewayFactory.get_gateway("SEPA Direct Debit"), SEPAGateway)

    def test_unsupported_method_raises(self):
        with self.assertRaises(ValueError):
            PaymentGatewayFactory.get_gateway("Bitcoin")


class TestBankTransferGateway(EnhancedTestCase):
    """BankTransferGateway generates transfer instructions on a real Donation."""

    def _make_donation(self, amount=50.0):
        return self.create_test_donation(amount=amount, mode_of_payment="Bank Transfer")

    def test_process_payment_returns_transfer_instructions(self):
        donation = self._make_donation(amount=42.0)
        result = BankTransferGateway().process_payment(donation, {})
        self.assertEqual(result["status"], "awaiting_transfer")
        self.assertTrue(result["payment_reference"].startswith(f"DON-{donation.name}-"))
        self.assertEqual(result["bank_details"]["amount"], donation.amount)
        # The payment reference must have been persisted on the donation.
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "payment_id"),
            result["payment_reference"],
        )

    def test_webhook_not_applicable(self):
        self.assertEqual(BankTransferGateway().handle_webhook({}), {"status": "not_applicable"})

    def test_get_payment_status_pending(self):
        status = BankTransferGateway().get_payment_status("anything")
        self.assertEqual(status["status"], "pending")


class TestCashGateway(EnhancedTestCase):
    """CashGateway registration response."""

    def test_process_payment_cash_pending(self):
        donation = self.create_test_donation(amount=10.0, mode_of_payment="Cash")
        result = CashGateway().process_payment(donation, {})
        self.assertEqual(result["status"], "cash_pending")
        self.assertIn("instructions", result)

    def test_reference_interpolates_donation_name(self):
        """CashGateway.process_payment builds the reference as an f-string, so the
        donation name is interpolated into "CASH-<name>" (previously a plain string
        literal left the template uninterpolated).
        """
        donation = self.create_test_donation(amount=10.0, mode_of_payment="Cash")
        result = CashGateway().process_payment(donation, {})
        self.assertEqual(result["reference"], f"CASH-{donation.name}")
        self.assertIn(donation.name, result["reference"])
        self.assertNotIn("{donation.name}", result["reference"])

    def test_webhook_not_applicable(self):
        self.assertEqual(CashGateway().handle_webhook({}), {"status": "not_applicable"})


class TestSEPAGatewayValidation(EnhancedTestCase):
    """SEPAGateway IBAN validation and collection-date logic."""

    def test_validate_iban_accepts_valid(self):
        self.assertTrue(SEPAGateway()._validate_iban("NL02ABNA0123456789"))

    def test_validate_iban_rejects_invalid(self):
        self.assertFalse(SEPAGateway()._validate_iban("NL00BANK0000000000"))
        self.assertFalse(SEPAGateway()._validate_iban("GARBAGE"))

    def test_collection_date_is_t_plus_two(self):
        from frappe.utils import add_to_date

        expected = getdate(add_to_date(getdate(), days=2))
        self.assertEqual(getdate(SEPAGateway()._calculate_collection_date(None)), expected)

    def test_process_payment_requires_iban(self):
        donation = self.create_test_donation(amount=20.0, mode_of_payment="SEPA Direct Debit")
        result = SEPAGateway().process_payment(donation, {})
        # create_error_response returns {"status": "error", "message": ...}.
        self.assertEqual(result["status"], "error")
        self.assertIn("IBAN is required", result["message"])

    def test_process_payment_rejects_invalid_iban(self):
        donation = self.create_test_donation(amount=20.0, mode_of_payment="SEPA Direct Debit")
        result = SEPAGateway().process_payment(donation, {"donor_iban": "NL00BANK0000000000"})
        self.assertEqual(result["status"], "error")
        self.assertIn("IBAN", result["message"])


class TestSEPAGatewayMandateCreation(EnhancedTestCase):
    """SEPAGateway end-to-end mandate creation against a real Donor/Donation.

    Regression coverage for the field-name fix in _create_sepa_mandate: it used
    to write `signature_date` (no such field) instead of the required `sign_date`,
    so every mandate insert failed with a MandatoryError and process_payment
    returned "Failed to create SEPA mandate". It also wrote a nonexistent
    `payment_method` field on the Donation, which raised on db_set.
    """

    def test_process_payment_creates_mandate_and_links_donation(self):
        donor = self.create_test_donor(donor_name="SEPA Gateway Donor")
        donation = self.create_test_donation(
            amount=20.0, mode_of_payment="SEPA Direct Debit", donor=donor.name, paid=0
        )
        result = SEPAGateway().process_payment(
            donation, {"donor_iban": "NL39RABO0300065264", "donor_name": "SEPA Gateway Donor"}
        )
        self.assertEqual(result["status"], "mandate_created")
        mandate_name = result["mandate_id"]
        self.assertTrue(frappe.db.exists("SEPA Mandate", mandate_name))
        # The mandate carries the required sign_date and the donation links to it.
        self.assertTrue(frappe.db.get_value("SEPA Mandate", mandate_name, "sign_date"))
        self.assertEqual(
            frappe.db.get_value("Donation", donation.name, "sepa_mandate"), mandate_name
        )

    def test_recurring_donation_yields_rcur_mandate(self):
        donor = self.create_test_donor(donor_name="Recurring SEPA Donor")
        donation = self.create_test_donation(
            amount=30.0, mode_of_payment="SEPA Direct Debit", donor=donor.name, paid=0, status="Recurring"
        )
        result = SEPAGateway().process_payment(
            donation, {"donor_iban": "NL39RABO0300065264", "donor_name": "Recurring SEPA Donor"}
        )
        self.assertEqual(result["status"], "mandate_created")
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate", result["mandate_id"], "mandate_type"), "RCUR"
        )
