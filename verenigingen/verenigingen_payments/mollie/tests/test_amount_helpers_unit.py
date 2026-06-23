"""
Tier-1 unit tests for the pure Mollie SDK amount helpers.

Covers:
  verenigingen/verenigingen_payments/mollie/utils/amount_helpers.py
    - extract_amount_value()      (SDK v3+ dict / legacy object / None)
    - extract_amount_currency()   (currency extraction + EUR default)
    - extract_amount_float()      (string -> float, malformed -> 0.0)
    - format_amount_display()     ("VALUE CURRENCY" rendering)
    - create_amount_dict()        (Mollie-shaped amount dict, 2dp formatting)

These functions are the canonical amount-normalisation layer used live by
core/client.py, services/payment_service.py and the webhook handlers. They are
pure functions over plain data (dicts / SimpleNamespace SDK stubs), so no Frappe
internals are mocked. The whole module had no dedicated direct test before this.
"""

from types import SimpleNamespace

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.utils.amount_helpers import (
    create_amount_dict,
    extract_amount_currency,
    extract_amount_float,
    extract_amount_value,
    format_amount_display,
)


class TestExtractAmountValue(EnhancedTestCase):
    """extract_amount_value — value as string across all supported shapes."""

    def test_sdk_v3_dict_format(self):
        self.assertEqual(extract_amount_value({"value": "10.00", "currency": "EUR"}), "10.00")

    def test_dict_missing_value_defaults_to_zero(self):
        self.assertEqual(extract_amount_value({"currency": "EUR"}), "0.00")

    def test_none_returns_zero_string(self):
        self.assertEqual(extract_amount_value(None), "0.00")

    def test_legacy_object_with_value_attr(self):
        self.assertEqual(extract_amount_value(SimpleNamespace(value="42.50")), "42.50")

    def test_legacy_object_with_amount_attr(self):
        # No .value, but has .amount -> use .amount (second legacy fallback branch)
        obj = SimpleNamespace(amount="7.99")
        self.assertEqual(extract_amount_value(obj), "7.99")

    def test_value_attr_takes_priority_over_amount_attr(self):
        obj = SimpleNamespace(value="1.00", amount="2.00")
        self.assertEqual(extract_amount_value(obj), "1.00")

    def test_unrecognised_object_returns_zero_string(self):
        # An object with neither .value nor .amount falls through to "0.00".
        self.assertEqual(extract_amount_value(SimpleNamespace(currency="EUR")), "0.00")

    def test_numeric_dict_value_is_stringified(self):
        # Mollie always sends strings, but a non-string value is coerced via str().
        self.assertEqual(extract_amount_value({"value": 12.5}), "12.5")


class TestExtractAmountCurrency(EnhancedTestCase):
    """extract_amount_currency — currency code with EUR default."""

    def test_dict_currency(self):
        self.assertEqual(extract_amount_currency({"value": "10.00", "currency": "USD"}), "USD")

    def test_dict_missing_currency_defaults_eur(self):
        self.assertEqual(extract_amount_currency({"value": "10.00"}), "EUR")

    def test_none_defaults_eur(self):
        self.assertEqual(extract_amount_currency(None), "EUR")

    def test_legacy_object_currency_attr(self):
        self.assertEqual(extract_amount_currency(SimpleNamespace(currency="GBP")), "GBP")

    def test_unrecognised_object_defaults_eur(self):
        self.assertEqual(extract_amount_currency(SimpleNamespace(value="1.00")), "EUR")


class TestExtractAmountFloat(EnhancedTestCase):
    """extract_amount_float — float conversion with safe fallback."""

    def test_dict_value_to_float(self):
        self.assertEqual(extract_amount_float({"value": "10.00", "currency": "EUR"}), 10.0)

    def test_none_returns_zero_float(self):
        self.assertEqual(extract_amount_float(None), 0.0)

    def test_legacy_object_to_float(self):
        self.assertEqual(extract_amount_float(SimpleNamespace(value="3.25")), 3.25)

    def test_malformed_value_returns_zero_float(self):
        # A non-numeric string flows through extract_amount_value and trips the
        # ValueError guard -> 0.0 (rather than raising).
        self.assertEqual(extract_amount_float({"value": "not-a-number"}), 0.0)

    def test_returns_python_float_type(self):
        result = extract_amount_float({"value": "5.00"})
        self.assertIsInstance(result, float)


class TestFormatAmountDisplay(EnhancedTestCase):
    """format_amount_display — 'VALUE CURRENCY' string for display."""

    def test_dict_display(self):
        self.assertEqual(format_amount_display({"value": "10.00", "currency": "EUR"}), "10.00 EUR")

    def test_none_display_uses_defaults(self):
        self.assertEqual(format_amount_display(None), "0.00 EUR")

    def test_legacy_object_display(self):
        obj = SimpleNamespace(value="25.00", currency="USD")
        self.assertEqual(format_amount_display(obj), "25.00 USD")


class TestCreateAmountDict(EnhancedTestCase):
    """create_amount_dict — produce a Mollie-shaped amount dict."""

    def test_float_formatted_to_two_decimals(self):
        self.assertEqual(create_amount_dict(10.5), {"value": "10.50", "currency": "EUR"})

    def test_string_value_with_explicit_currency(self):
        self.assertEqual(create_amount_dict("25.00", "USD"), {"value": "25.00", "currency": "USD"})

    def test_int_value(self):
        self.assertEqual(create_amount_dict(7), {"value": "7.00", "currency": "EUR"})

    def test_rounds_to_two_decimal_places(self):
        # 19.999 -> "20.00" via f"{:.2f}" rounding.
        self.assertEqual(create_amount_dict(19.999)["value"], "20.00")

    def test_round_trips_through_extract_float(self):
        # The dict produced here is the same shape the extract helpers consume,
        # so a round trip must preserve the numeric value.
        d = create_amount_dict("42.00", "EUR")
        self.assertEqual(extract_amount_float(d), 42.0)
        self.assertEqual(extract_amount_currency(d), "EUR")
