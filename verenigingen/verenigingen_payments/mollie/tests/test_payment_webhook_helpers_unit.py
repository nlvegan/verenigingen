"""
Tier-1 unit tests for the pure helper functions in the Mollie payment webhook
handler and the webhook utilities module.

Covers:
  verenigingen/verenigingen_payments/mollie/api/payment_webhook.py
    - _determine_recurring_status()       (priority-ordered recurring detection)
    - extract_mollie_payment_data()       (SDK -> dict normalisation)
    - _extract_record_reference_from_mollie_data()
    - _validate_payment_amount()          (amount validation / range checks)

  verenigingen/verenigingen_payments/mollie/utils/webhook_utilities.py
    - safe_extract_amount()
    - safe_extract_date()
    - extract_webhook_ids()
    - standardized_webhook_response()

These are pure functions over plain data. Mollie payment objects are stood in
with SimpleNamespace stubs (the SDK boundary). _validate_payment_amount uses
frappe.throw for invalid input, so those branches are asserted via the real
frappe.ValidationError — no frappe internals are mocked.
"""

import unittest
from types import SimpleNamespace

import frappe

from verenigingen.verenigingen_payments.mollie.api.payment_webhook import (
    _determine_recurring_status,
    _extract_record_reference_from_mollie_data,
    _validate_payment_amount,
    extract_mollie_payment_data,
)
from verenigingen.verenigingen_payments.mollie.utils.webhook_utilities import (
    extract_webhook_ids,
    safe_extract_amount,
    safe_extract_date,
    standardized_webhook_response,
)


class TestDetermineRecurringStatus(unittest.TestCase):
    """_determine_recurring_status — priority-ordered recurring detection."""

    def setUp(self):
        # A donation stub whose .status/.get() the lowest-priority branch reads.
        self.donation = SimpleNamespace(status="One-time", get=lambda k: None)

    def test_sequence_type_recurring_wins(self):
        self.assertTrue(_determine_recurring_status(self.donation, {"sequence_type": "recurring"}))

    def test_sequence_type_first_is_recurring(self):
        self.assertTrue(_determine_recurring_status(self.donation, {"sequence_type": "first"}))

    def test_sequence_type_oneoff_is_one_time(self):
        # oneoff overrides even a subscription_id below it
        data = {"sequence_type": "oneoff", "subscription_id": "sub_1"}
        self.assertFalse(_determine_recurring_status(self.donation, data))

    def test_metadata_explicit_false_override(self):
        data = {"metadata": {"subscription_setup": "false"}, "subscription_id": "sub_1"}
        self.assertFalse(_determine_recurring_status(self.donation, data))

    def test_metadata_explicit_true_override(self):
        self.assertTrue(
            _determine_recurring_status(self.donation, {"metadata": {"subscription_setup": "true"}})
        )

    def test_subscription_id_implies_recurring(self):
        self.assertTrue(_determine_recurring_status(self.donation, {"subscription_id": "sub_1"}))

    def test_mandate_plus_customer_implies_recurring(self):
        data = {"mandate_id": "mdt_1", "customer_id": "cst_1"}
        self.assertTrue(_determine_recurring_status(self.donation, data))

    def test_subscription_metadata_indicators(self):
        data = {"metadata": {"subscription_interval": "1 month"}}
        self.assertTrue(_determine_recurring_status(self.donation, data))

    def test_legacy_json_description_recurring(self):
        data = {"description": '{"type": "recurring"}'}
        self.assertTrue(_determine_recurring_status(self.donation, data))

    def test_existing_recurring_donation_status_preserved(self):
        donation = SimpleNamespace(status="Recurring", get=lambda k: "Recurring" if k == "status" else None)
        self.assertTrue(_determine_recurring_status(donation, {}))

    def test_default_is_one_time(self):
        self.assertFalse(_determine_recurring_status(self.donation, {}))

    def test_mandate_without_customer_is_not_enough(self):
        self.assertFalse(_determine_recurring_status(self.donation, {"mandate_id": "mdt_1"}))


class TestExtractMolliePaymentData(unittest.TestCase):
    """extract_mollie_payment_data — normalise SDK payment to flat dict."""

    def test_dict_amount_format(self):
        payment = SimpleNamespace(
            id="tr_1",
            status="paid",
            amount={"value": "10.00", "currency": "EUR"},
            method="ideal",
            customer_id="cst_1",
            mandate_id=None,
            subscription_id="sub_1",
            created_at="2024-01-01",
            paid_at="2024-01-02",
            description="hi",
            metadata={"k": "v"},
            sequence_type="recurring",
        )
        data = extract_mollie_payment_data(payment)
        self.assertEqual(data["payment_id"], "tr_1")
        self.assertEqual(data["amount"], "10.00")
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["method"], "ideal")
        self.assertEqual(data["subscription_id"], "sub_1")
        self.assertEqual(data["sequence_type"], "recurring")
        self.assertEqual(data["metadata"], {"k": "v"})

    def test_object_amount_format(self):
        payment = SimpleNamespace(
            id="tr_2",
            status="paid",
            amount=SimpleNamespace(value="5.50", currency="USD"),
            method="creditcard",
        )
        data = extract_mollie_payment_data(payment)
        self.assertEqual(data["amount"], "5.50")
        self.assertEqual(data["currency"], "USD")
        # missing optional attrs default sensibly
        self.assertIsNone(data["customer_id"])
        self.assertEqual(data["metadata"], {})

    def test_none_amount(self):
        # Real Mollie SDK payment objects always carry an `amount` attribute;
        # when it is None (e.g. not yet populated), value/currency fall back to None.
        payment = SimpleNamespace(id="tr_3", status="open", amount=None)
        data = extract_mollie_payment_data(payment)
        self.assertIsNone(data["amount"])
        self.assertIsNone(data["currency"])

    def test_amount_attribute_absent_does_not_raise(self):
        # A payment object with NO `amount` attribute at all must not raise — the
        # extractor reads it via getattr(..., None). (Previously payment.amount was
        # dereferenced before the hasattr guard, raising AttributeError.)
        payment = SimpleNamespace(id="tr_4", status="open")
        self.assertFalse(hasattr(payment, "amount"))
        data = extract_mollie_payment_data(payment)
        self.assertIsNone(data["amount"])
        self.assertIsNone(data["currency"])


class TestExtractRecordReference(unittest.TestCase):
    """_extract_record_reference_from_mollie_data — origin-agnostic title source."""

    def test_from_metadata_attr(self):
        payment = SimpleNamespace(metadata={"record_id": "DON-0001"}, description=None)
        self.assertEqual(_extract_record_reference_from_mollie_data(payment, "tr_x"), "DON-0001")

    def test_from_description_json(self):
        payment = SimpleNamespace(metadata=None, description='{"record_id": "MEM-0002"}')
        self.assertEqual(_extract_record_reference_from_mollie_data(payment, "tr_x"), "MEM-0002")

    def test_from_dict_metadata(self):
        data = {"metadata": {"record_id": "DON-0003"}}
        self.assertEqual(_extract_record_reference_from_mollie_data(data, "tr_x"), "DON-0003")

    def test_fallback_to_payment_id(self):
        payment = SimpleNamespace(metadata={}, description="not json")
        self.assertEqual(_extract_record_reference_from_mollie_data(payment, "tr_fallback"), "tr_fallback")


class TestValidatePaymentAmount(unittest.TestCase):
    """_validate_payment_amount — extraction + range validation."""

    def test_valid_dict_amount(self):
        payment = SimpleNamespace(id="tr_1", amount={"value": "12.34", "currency": "EUR"})
        self.assertEqual(_validate_payment_amount(payment), 12.34)

    def test_valid_object_amount(self):
        payment = SimpleNamespace(id="tr_1", amount=SimpleNamespace(value="9.99"))
        self.assertEqual(_validate_payment_amount(payment), 9.99)

    def test_none_payment_returns_zero(self):
        self.assertEqual(_validate_payment_amount(None), 0.0)

    def test_missing_amount_returns_zero(self):
        payment = SimpleNamespace(id="tr_1", amount=None)
        self.assertEqual(_validate_payment_amount(payment), 0.0)

    def test_zero_amount_raises(self):
        payment = SimpleNamespace(id="tr_1", amount={"value": "0.00", "currency": "EUR"})
        with self.assertRaises(frappe.ValidationError):
            _validate_payment_amount(payment)

    def test_negative_amount_raises(self):
        payment = SimpleNamespace(id="tr_1", amount={"value": "-5.00", "currency": "EUR"})
        with self.assertRaises(frappe.ValidationError):
            _validate_payment_amount(payment)

    def test_large_amount_processed(self):
        # > €100,000 is logged but still returned (not rejected)
        payment = SimpleNamespace(id="tr_big", amount={"value": "150000.00", "currency": "EUR"})
        self.assertEqual(_validate_payment_amount(payment), 150000.0)


class TestSafeExtractAmount(unittest.TestCase):
    def test_dict_value(self):
        self.assertEqual(safe_extract_amount({"amount": {"value": "42.00"}}), 42.0)

    def test_scalar_value(self):
        self.assertEqual(safe_extract_amount({"amount": "7.50"}), 7.5)

    def test_missing_uses_default(self):
        self.assertEqual(safe_extract_amount({}), 0.0)
        self.assertEqual(safe_extract_amount({}, default=1.0), 1.0)

    def test_bad_value_uses_default(self):
        self.assertEqual(safe_extract_amount({"amount": {"value": "notanumber"}}, default=3.0), 3.0)


class TestSafeExtractDate(unittest.TestCase):
    def test_extracts_date_prefix(self):
        self.assertEqual(safe_extract_date({"created_at": "2024-06-01T12:00:00Z"}), "2024-06-01")

    def test_custom_field(self):
        self.assertEqual(safe_extract_date({"paid_at": "2024-07-02T00:00:00Z"}, "paid_at"), "2024-07-02")

    def test_missing_field_returns_none(self):
        self.assertIsNone(safe_extract_date({}))

    def test_short_value_returns_none(self):
        self.assertIsNone(safe_extract_date({"created_at": "2024"}))


class TestExtractWebhookIds(unittest.TestCase):
    def test_payment_id_from_nested(self):
        ids = extract_webhook_ids({"payment": {"id": "tr_1"}})
        self.assertEqual(ids["payment_id"], "tr_1")

    def test_payment_id_flat(self):
        ids = extract_webhook_ids({"payment_id": "tr_2"})
        self.assertEqual(ids["payment_id"], "tr_2")

    def test_refund_id_by_resource(self):
        ids = extract_webhook_ids({"resource": "refund", "id": "re_1"})
        self.assertEqual(ids["refund_id"], "re_1")

    def test_chargeback_id_by_resource(self):
        ids = extract_webhook_ids({"resource": "chargeback", "id": "chb_1"})
        self.assertEqual(ids["chargeback_id"], "chb_1")


class TestStandardizedWebhookResponse(unittest.TestCase):
    def test_basic_shape(self):
        resp = standardized_webhook_response("success", "done", payment_id="tr_1")
        self.assertEqual(resp["status"], "success")
        self.assertEqual(resp["message"], "done")
        self.assertEqual(resp["payment_id"], "tr_1")
        self.assertIn("timestamp", resp)


if __name__ == "__main__":
    unittest.main()
