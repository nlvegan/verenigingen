"""
Coverage gap-fill for verenigingen_payments/core/compliance/financial_validator.py

Pure-logic validation tests (no DB fixtures required). Exercises:
- validate_amount (precision / min / max / None / "" / dict / NaN / neg-zero / bad format)
- validate_currency (ok / lowercase / wrong-length / unknown / empty)
- validate_transaction_reference (ok / empty / too-long / bad chars / custom pattern)
- validate_balance_consistency (balanced / debit-credit / tolerance / bad type / error)
- validate_settlement_data (valid / missing id / bad reference / bad amount / bad
  currency / bad period range warning / bad period dates error)
- validate_payment_data (valid / missing required fields / amount dict / currency from
  amount dict / IBAN warning / sensitive-key-in-metadata warning)
- get_validation_report

The deprecated validate_iban impl is intentionally NOT tested here (it only delegates
to the canonical iban_validator and emits a DeprecationWarning; out of scope).

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_financial_validator_coverage_b1
"""

import unittest
from decimal import Decimal

from verenigingen.verenigingen_payments.core.compliance.financial_validator import FinancialValidator


class TestValidateAmount(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_valid_simple_amount(self):
        ok, err = self.v.validate_amount("10.50")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_none_rejected(self):
        ok, err = self.v.validate_amount(None)
        self.assertFalse(ok)
        self.assertIn("None", err)

    def test_empty_string_rejected(self):
        ok, err = self.v.validate_amount("")
        self.assertFalse(ok)
        self.assertIn("empty", err)

    def test_dict_with_value_extracted(self):
        ok, err = self.v.validate_amount({"value": "12.34", "currency": "EUR"})
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_dict_missing_value_rejected(self):
        ok, err = self.v.validate_amount({"currency": "EUR"})
        self.assertFalse(ok)
        self.assertIn("missing 'value'", err)

    def test_precision_exceeded_rejected(self):
        ok, err = self.v.validate_amount("10.555")
        self.assertFalse(ok)
        self.assertIn("decimal places", err)

    def test_custom_precision_allows_more_places(self):
        ok, err = self.v.validate_amount("10.5550", precision=4)
        self.assertTrue(ok)

    def test_below_minimum_rejected(self):
        ok, err = self.v.validate_amount("0.001", min_amount=Decimal("0.01"), precision=3)
        self.assertFalse(ok)
        self.assertIn("at least", err)

    def test_above_maximum_rejected(self):
        ok, err = self.v.validate_amount("100.00", max_amount=Decimal("99.99"))
        self.assertFalse(ok)
        self.assertIn("not exceed", err)

    def test_within_min_and_max_accepted(self):
        ok, err = self.v.validate_amount("50.00", min_amount=Decimal("1"), max_amount=Decimal("100"))
        self.assertTrue(ok)

    def test_nan_rejected(self):
        ok, err = self.v.validate_amount("NaN")
        self.assertFalse(ok)
        self.assertIn("finite", err)

    def test_infinity_rejected(self):
        ok, err = self.v.validate_amount("Infinity")
        self.assertFalse(ok)
        self.assertIn("finite", err)

    def test_negative_zero_rejected(self):
        ok, err = self.v.validate_amount("-0.00")
        self.assertFalse(ok)
        self.assertIn("Negative zero", err)

    def test_garbage_format_rejected(self):
        ok, err = self.v.validate_amount("abc")
        self.assertFalse(ok)
        self.assertIn("Invalid amount format", err)


class TestValidateCurrency(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_valid_currency(self):
        ok, err = self.v.validate_currency("EUR")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_lowercase_normalized_and_accepted(self):
        ok, err = self.v.validate_currency("usd")
        self.assertTrue(ok)

    def test_empty_rejected(self):
        ok, err = self.v.validate_currency("")
        self.assertFalse(ok)
        self.assertIn("required", err)

    def test_wrong_length_rejected(self):
        ok, err = self.v.validate_currency("EURO")
        self.assertFalse(ok)
        self.assertIn("3 characters", err)

    def test_unknown_code_rejected(self):
        ok, err = self.v.validate_currency("XYZ")
        self.assertFalse(ok)
        self.assertIn("Invalid currency", err)


class TestValidateTransactionReference(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_valid_reference(self):
        ok, err = self.v.validate_transaction_reference("INV-2024/001")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_empty_rejected(self):
        ok, err = self.v.validate_transaction_reference("")
        self.assertFalse(ok)
        self.assertIn("required", err)

    def test_too_long_rejected(self):
        ok, err = self.v.validate_transaction_reference("A" * 141)
        self.assertFalse(ok)
        self.assertIn("too long", err)

    def test_invalid_chars_rejected(self):
        ok, err = self.v.validate_transaction_reference("ref#with*bad=chars")
        self.assertFalse(ok)
        self.assertIn("invalid characters", err)

    def test_custom_pattern_mismatch_rejected(self):
        ok, err = self.v.validate_transaction_reference("ABC123", pattern=r"^\d+$")
        self.assertFalse(ok)
        self.assertIn("required format", err)

    def test_custom_pattern_match_accepted(self):
        ok, err = self.v.validate_transaction_reference("12345", pattern=r"^\d+$")
        self.assertTrue(ok)


class TestValidateBalanceConsistency(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_balanced_credits_and_debits(self):
        txns = [
            {"amount": "100.00", "type": "credit"},
            {"amount": "30.00", "type": "debit"},
        ]
        ok, err = self.v.validate_balance_consistency(Decimal("0"), txns, Decimal("70.00"))
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_within_tolerance_accepted(self):
        txns = [{"amount": "10.00", "type": "credit"}]
        ok, err = self.v.validate_balance_consistency(
            Decimal("0"), txns, Decimal("10.005"), tolerance=Decimal("0.01")
        )
        self.assertTrue(ok)

    def test_mismatch_beyond_tolerance_rejected(self):
        txns = [{"amount": "10.00", "type": "credit"}]
        ok, err = self.v.validate_balance_consistency(Decimal("0"), txns, Decimal("20.00"))
        self.assertFalse(ok)
        self.assertIn("Balance mismatch", err)

    def test_invalid_transaction_type_rejected(self):
        txns = [{"amount": "10.00", "type": "weird"}]
        ok, err = self.v.validate_balance_consistency(Decimal("0"), txns, Decimal("10.00"))
        self.assertFalse(ok)
        self.assertIn("Invalid transaction type", err)

    def test_unparseable_amount_returns_error(self):
        txns = [{"amount": "not-a-number", "type": "credit"}]
        ok, err = self.v.validate_balance_consistency(Decimal("0"), txns, Decimal("0"))
        self.assertFalse(ok)
        self.assertIn("Balance validation error", err)


class TestValidateSettlementData(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_valid_settlement(self):
        settlement = {
            "id": "stl_123",
            "reference": "1234567.1809.03",
            "amount": {"value": "100.00", "currency": "EUR"},
            "currency": "EUR",
        }
        res = self.v.validate_settlement_data(settlement)
        self.assertTrue(res["valid"])
        self.assertEqual(res["errors"], [])

    def test_missing_id_invalid(self):
        res = self.v.validate_settlement_data({})
        self.assertFalse(res["valid"])
        self.assertTrue(any("Settlement ID" in e for e in res["errors"]))

    def test_bad_reference_invalid(self):
        res = self.v.validate_settlement_data({"id": "stl_1", "reference": "bad#ref"})
        self.assertFalse(res["valid"])
        self.assertTrue(any("Settlement reference" in e for e in res["errors"]))

    def test_bad_amount_invalid(self):
        res = self.v.validate_settlement_data({"id": "stl_1", "amount": "0.00"})
        self.assertFalse(res["valid"])
        self.assertTrue(any("Settlement amount" in e for e in res["errors"]))

    def test_bad_currency_invalid(self):
        res = self.v.validate_settlement_data({"id": "stl_1", "currency": "ZZZ"})
        self.assertFalse(res["valid"])
        self.assertTrue(any("Settlement currency" in e for e in res["errors"]))

    def test_inverted_period_range_warns(self):
        settlement = {
            "id": "stl_1",
            "periods": [{"from": "2024-02-01T00:00:00Z", "until": "2024-01-01T00:00:00Z"}],
        }
        res = self.v.validate_settlement_data(settlement)
        self.assertTrue(res["valid"])  # warning, not error
        self.assertTrue(any("Invalid period range" in w for w in res["warnings"]))

    def test_unparseable_period_dates_error(self):
        settlement = {"id": "stl_1", "periods": [{"from": "not-a-date", "until": "also-bad"}]}
        res = self.v.validate_settlement_data(settlement)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid period dates" in e for e in res["errors"]))


class TestValidatePaymentData(unittest.TestCase):
    def setUp(self):
        self.v = FinancialValidator()

    def test_valid_payment(self):
        payment = {
            "id": "tr_123",
            "amount": {"value": "25.00", "currency": "EUR"},
            "currency": "EUR",
            "status": "paid",
        }
        res = self.v.validate_payment_data(payment)
        self.assertTrue(res["valid"])
        self.assertEqual(res["errors"], [])

    def test_missing_required_fields_invalid(self):
        res = self.v.validate_payment_data({})
        self.assertFalse(res["valid"])
        # All four required fields flagged
        for field in ("id", "amount", "currency", "status"):
            self.assertTrue(
                any(f"Missing required field: {field}" in e for e in res["errors"]),
                f"expected missing-field error for {field}",
            )

    def test_scalar_amount_and_currency(self):
        payment = {"id": "tr_1", "amount": "10.00", "currency": "USD", "status": "paid"}
        res = self.v.validate_payment_data(payment)
        self.assertTrue(res["valid"])

    def test_amount_too_large_invalid(self):
        payment = {
            "id": "tr_1",
            "amount": {"value": "1000000.00", "currency": "EUR"},
            "currency": "EUR",
            "status": "paid",
        }
        res = self.v.validate_payment_data(payment)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Payment amount" in e for e in res["errors"]))

    def test_bad_currency_from_amount_dict_invalid(self):
        payment = {
            "id": "tr_1",
            "amount": {"value": "10.00", "currency": "ZZZ"},
            "currency": "EUR",
            "status": "paid",
        }
        res = self.v.validate_payment_data(payment)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Payment currency" in e for e in res["errors"]))

    def test_invalid_iban_produces_warning_not_error(self):
        payment = {
            "id": "tr_1",
            "amount": {"value": "10.00", "currency": "EUR"},
            "currency": "EUR",
            "status": "paid",
            "iban": "INVALID_IBAN",
        }
        res = self.v.validate_payment_data(payment)
        # IBAN issues are warnings; required fields present so still valid
        self.assertTrue(res["valid"])
        self.assertTrue(any("Payment IBAN" in w for w in res["warnings"]))

    def test_sensitive_metadata_key_warns(self):
        payment = {
            "id": "tr_1",
            "amount": {"value": "10.00", "currency": "EUR"},
            "currency": "EUR",
            "status": "paid",
            "metadata": {"user_password": "x", "harmless": "y"},
        }
        res = self.v.validate_payment_data(payment)
        self.assertTrue(any("sensitive data in metadata" in w for w in res["warnings"]))


class TestValidationReport(unittest.TestCase):
    def test_report_structure_and_truncation(self):
        v = FinancialValidator()
        v.validation_errors = [f"err{i}" for i in range(15)]
        v.validation_warnings = [f"warn{i}" for i in range(3)]
        report = v.get_validation_report()
        self.assertEqual(report["total_errors"], 15)
        self.assertEqual(report["total_warnings"], 3)
        self.assertEqual(len(report["errors"]), 10)  # last 10 only
        self.assertEqual(report["errors"][0], "err5")
        self.assertEqual(len(report["warnings"]), 3)
        self.assertIn("timestamp", report)


if __name__ == "__main__":
    unittest.main()
