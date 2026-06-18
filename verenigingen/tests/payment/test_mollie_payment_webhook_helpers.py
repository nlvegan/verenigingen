"""
Tests for the legacy helper functions in payment_webhook.py.

Target: verenigingen/verenigingen_payments/mollie/api/payment_webhook.py

These functions are largely pure logic operating on Mollie payment objects /
dicts; they are tested directly with SimpleNamespace payment doubles. The
amount-validation function (_validate_payment_amount) raises frappe.throw for
invalid amounts, which is real business behaviour we assert on.
"""

import unittest
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.mollie.api import payment_webhook as pw


def _payment(**kwargs):
    defaults = dict(
        id="tr_test",
        status="paid",
        amount={"value": "25.00", "currency": "EUR"},
        method="ideal",
        customer_id=None,
        mandate_id=None,
        subscription_id=None,
        created_at=None,
        paid_at=None,
        description=None,
        metadata={},
        sequence_type=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestExtractMolliePaymentData(FrappeTestCase):
    def test_dict_amount(self):
        data = pw.extract_mollie_payment_data(_payment(amount={"value": "10.50", "currency": "EUR"}))
        self.assertEqual(data["payment_id"], "tr_test")
        self.assertEqual(data["amount"], "10.50")
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["status"], "paid")

    def test_object_amount(self):
        amt = SimpleNamespace(value="99.99", currency="USD")
        data = pw.extract_mollie_payment_data(_payment(amount=amt))
        self.assertEqual(data["amount"], "99.99")
        self.assertEqual(data["currency"], "USD")

    def test_missing_amount_does_not_raise(self):
        # Regression: an amount-less payment object must not raise AttributeError.
        p = _payment()
        delattr(p, "amount")
        data = pw.extract_mollie_payment_data(p)
        self.assertIsNone(data["amount"])
        self.assertIsNone(data["currency"])

    def test_sequence_type_carried_through(self):
        data = pw.extract_mollie_payment_data(_payment(sequence_type="recurring"))
        self.assertEqual(data["sequence_type"], "recurring")


class TestDetermineRecurringStatus(FrappeTestCase):
    def setUp(self):
        self.donation = SimpleNamespace(status="One-time", get=lambda k: None)

    def test_sequence_type_recurring(self):
        self.assertTrue(pw._determine_recurring_status(self.donation, {"sequence_type": "recurring"}))

    def test_sequence_type_first(self):
        self.assertTrue(pw._determine_recurring_status(self.donation, {"sequence_type": "first"}))

    def test_sequence_type_oneoff(self):
        self.assertFalse(pw._determine_recurring_status(self.donation, {"sequence_type": "oneoff"}))

    def test_metadata_explicit_false_overrides(self):
        data = {"metadata": {"subscription_setup": "false"}, "subscription_id": "sub_1"}
        self.assertFalse(pw._determine_recurring_status(self.donation, data))

    def test_metadata_explicit_true(self):
        self.assertTrue(
            pw._determine_recurring_status(self.donation, {"metadata": {"subscription_setup": "true"}})
        )

    def test_subscription_id_recurring(self):
        self.assertTrue(pw._determine_recurring_status(self.donation, {"subscription_id": "sub_9"}))

    def test_mandate_plus_customer_recurring(self):
        data = {"mandate_id": "mdt_1", "customer_id": "cst_1"}
        self.assertTrue(pw._determine_recurring_status(self.donation, data))

    def test_subscription_metadata_indicators(self):
        data = {"metadata": {"subscription_interval": "1 month"}}
        self.assertTrue(pw._determine_recurring_status(self.donation, data))

    def test_legacy_json_description_recurring(self):
        data = {"description": '{"type": "recurring"}'}
        self.assertTrue(pw._determine_recurring_status(self.donation, data))

    def test_legacy_json_description_non_recurring(self):
        data = {"description": '{"type": "one-time"}'}
        self.assertFalse(pw._determine_recurring_status(self.donation, data))

    def test_invalid_json_description_ignored(self):
        data = {"description": "not json"}
        self.assertFalse(pw._determine_recurring_status(self.donation, data))

    def test_existing_donation_status_recurring(self):
        donation = SimpleNamespace(status="Recurring", get=lambda k: "Recurring")
        self.assertTrue(pw._determine_recurring_status(donation, {}))

    def test_default_one_time(self):
        self.assertFalse(pw._determine_recurring_status(self.donation, {}))


class TestExtractRecordReference(FrappeTestCase):
    def test_metadata_record_id(self):
        p = SimpleNamespace(metadata={"record_id": "DON-123"}, description=None)
        self.assertEqual(pw._extract_record_reference_from_mollie_data(p, "tr_x"), "DON-123")

    def test_description_json_record_id(self):
        p = SimpleNamespace(metadata=None, description='{"record_id": "DON-456"}')
        self.assertEqual(pw._extract_record_reference_from_mollie_data(p, "tr_x"), "DON-456")

    def test_dict_metadata_record_id(self):
        d = {"metadata": {"record_id": "DON-789"}}
        self.assertEqual(pw._extract_record_reference_from_mollie_data(d, "tr_x"), "DON-789")

    def test_fallback_to_payment_id(self):
        d = {"metadata": {}}
        self.assertEqual(pw._extract_record_reference_from_mollie_data(d, "tr_fallback"), "tr_fallback")


class TestValidatePaymentAmount(FrappeTestCase):
    def test_valid_dict_amount(self):
        self.assertEqual(pw._validate_payment_amount(_payment(amount={"value": "42.00"})), 42.0)

    def test_valid_object_amount(self):
        amt = SimpleNamespace(value="13.37")
        self.assertEqual(pw._validate_payment_amount(_payment(amount=amt)), 13.37)

    def test_none_payment_returns_zero(self):
        self.assertEqual(pw._validate_payment_amount(None), 0.0)

    def test_missing_amount_returns_zero(self):
        p = _payment(amount=None)
        self.assertEqual(pw._validate_payment_amount(p), 0.0)

    def test_zero_amount_raises(self):
        with self.assertRaises(frappe.ValidationError):
            pw._validate_payment_amount(_payment(amount={"value": "0.00"}))

    def test_negative_amount_raises(self):
        with self.assertRaises(frappe.ValidationError):
            pw._validate_payment_amount(_payment(amount={"value": "-5.00"}))

    def test_unknown_amount_format_returns_zero(self):
        p = _payment(amount=object())
        self.assertEqual(pw._validate_payment_amount(p), 0.0)

    def test_large_amount_still_processed(self):
        # Over MAX_REASONABLE_AMOUNT logs a warning but still returns the value.
        self.assertEqual(pw._validate_payment_amount(_payment(amount={"value": "250000.00"})), 250000.0)


class TestGetSubscriptionFailureCountSafe(FrappeTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def test_zero_for_unknown_subscription(self):
        # No history rows -> count 0 (also exercises the safe path).
        count = pw._get_subscription_failure_count("NONEXISTENT-MEMBER", "sub_zzz")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
