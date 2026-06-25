import unittest
from decimal import ROUND_HALF_UP, Decimal

from verenigingen.verenigingen_payments.utils.shared.money import quantize_amount, safe_decimal


class TestSafeDecimal(unittest.TestCase):
    """Tests for safe_decimal — behavior must match _safe_decimal in bank_transaction_reconciliation."""

    # --- None ---

    def test_none_returns_zero(self):
        """None maps to Decimal('0')."""
        self.assertEqual(safe_decimal(None), Decimal("0"))

    # --- int / float ---

    def test_int_zero(self):
        self.assertEqual(safe_decimal(0), Decimal("0"))

    def test_int_positive(self):
        self.assertEqual(safe_decimal(42), Decimal("42"))

    def test_float_positive(self):
        self.assertEqual(safe_decimal(1.5), Decimal("1.5"))

    def test_float_negative(self):
        self.assertEqual(safe_decimal(-3.14), Decimal(str(-3.14)))

    # --- str: plain numbers ---

    def test_str_integer(self):
        self.assertEqual(safe_decimal("100"), Decimal("100"))

    def test_str_decimal(self):
        self.assertEqual(safe_decimal("12.34"), Decimal("12.34"))

    def test_str_negative(self):
        self.assertEqual(safe_decimal("-5.00"), Decimal("-5.00"))

    # --- str: currency symbols / separators stripped ---

    def test_str_euro_symbol_stripped(self):
        """'€ 1.234,56' — regex [^\d.-] strips '€ ' and ',' leaving '1.234.56'… verify exact original behavior."""
        # The original regex r"[^\d\.-]" keeps digits, '.', and '-'.
        # '€ 1.234,56' → '1.23456' after stripping '€', ' ', and ','
        result = safe_decimal("€1.234,56")
        # stripped: '1.23456' → Decimal('1.23456')
        self.assertEqual(result, Decimal("1.23456"))

    def test_str_dollar_symbol_stripped(self):
        """'$10.00' → '10.00'."""
        self.assertEqual(safe_decimal("$10.00"), Decimal("10.00"))

    def test_str_space_stripped(self):
        """' 99.99 ' → '99.99'."""
        self.assertEqual(safe_decimal(" 99.99 "), Decimal("99.99"))

    def test_str_comma_thousands_separator_stripped(self):
        """'1,000.00' → '1000.00'."""
        self.assertEqual(safe_decimal("1,000.00"), Decimal("1000.00"))

    def test_str_percentage_sign_stripped(self):
        """'50%' → '50'."""
        self.assertEqual(safe_decimal("50%"), Decimal("50"))

    # --- str: edge cases ---

    def test_str_empty_returns_zero(self):
        """Empty string after stripping → Decimal('0')."""
        self.assertEqual(safe_decimal(""), Decimal("0"))

    def test_str_all_symbols_returns_zero(self):
        """String with only strippable chars → Decimal('0')."""
        self.assertEqual(safe_decimal("€ "), Decimal("0"))

    def test_str_garbage_returns_default(self):
        """Non-numeric garbage → default."""
        self.assertEqual(safe_decimal("abc"), Decimal("0"))

    # --- Decimal passthrough ---

    def test_decimal_returned_as_is(self):
        d = Decimal("7.77")
        self.assertIs(safe_decimal(d), d)

    def test_decimal_zero(self):
        d = Decimal("0")
        self.assertIs(safe_decimal(d), d)

    # --- default parameter ---

    def test_custom_default_on_none(self):
        """None returns Decimal(default) when default is overridden."""
        self.assertEqual(safe_decimal(None, default="5"), Decimal("5"))

    def test_custom_default_on_garbage(self):
        """Garbage string returns Decimal(default)."""
        self.assertEqual(safe_decimal("abc", default="99"), Decimal("99"))

    # --- unexpected type returns default ---

    def test_list_returns_default(self):
        self.assertEqual(safe_decimal([1, 2], default="0"), Decimal("0"))

    def test_dict_returns_default(self):
        self.assertEqual(safe_decimal({}, default="0"), Decimal("0"))


class TestQuantizeAmount(unittest.TestCase):
    """Tests for quantize_amount."""

    def test_basic_two_decimal_places(self):
        self.assertEqual(quantize_amount(Decimal("1.234")), Decimal("1.23"))

    def test_half_up_boundary(self):
        """'1.005' should round up to '1.01' under HALF_UP."""
        self.assertEqual(quantize_amount(Decimal("1.005")), Decimal("1.01"))

    def test_half_up_round_down(self):
        """'1.004' → '1.00' under HALF_UP."""
        self.assertEqual(quantize_amount(Decimal("1.004")), Decimal("1.00"))

    def test_string_input(self):
        """Accepts a string value via safe_decimal coercion."""
        self.assertEqual(quantize_amount("2.555"), Decimal("2.56"))

    def test_integer_input(self):
        self.assertEqual(quantize_amount(10), Decimal("10.00"))

    def test_none_input(self):
        self.assertEqual(quantize_amount(None), Decimal("0.00"))

    def test_negative_half_up(self):
        """Negative HALF_UP: '-1.005' → '-1.01' (rounds away from zero)."""
        self.assertEqual(quantize_amount(Decimal("-1.005")), Decimal("-1.01"))

    def test_custom_places_zero(self):
        """places=0 rounds to integer."""
        self.assertEqual(quantize_amount(Decimal("1.5"), places=0), Decimal("2"))

    def test_custom_places_four(self):
        """places=4 keeps 4 decimal digits."""
        self.assertEqual(quantize_amount(Decimal("1.23456"), places=4), Decimal("1.2346"))

    def test_result_type_is_decimal(self):
        result = quantize_amount("3.14")
        self.assertIsInstance(result, Decimal)


if __name__ == "__main__":
    unittest.main()
