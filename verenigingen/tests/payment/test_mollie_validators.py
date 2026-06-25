# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for the Mollie integration validators.

Target module:
    verenigingen.verenigingen_payments.mollie.utils.validators

These validators are pure-Python (no network, no DB) except
``validate_dutch_postal_code`` which delegates to the shared postal-code
validator. The tests therefore use plain ``unittest.TestCase`` and assert
real behaviour for valid, invalid and boundary inputs.

Real, verifiable IBANs used:
    - NL91ABNA0417164300 (valid Dutch IBAN)
    - DE89370400440532013000 (valid German IBAN)
    - GB82WEST12345698765432 (valid UK IBAN)
"""

import unittest
from decimal import Decimal

from verenigingen.verenigingen_payments.mollie.utils.validators import (
    BusinessRuleValidator,
    IBANValidator,
    PaymentDataValidator,
    format_iban as module_format_iban,
    validate_iban as module_validate_iban,
)

# Well-known valid IBANs (verified mod-97 = 1)
VALID_NL = "NL91ABNA0417164300"
VALID_DE = "DE89370400440532013000"
VALID_GB = "GB82WEST12345698765432"


class TestIBANValidator(unittest.TestCase):
    """Tests for IBANValidator.validate_iban / _validate_checksum."""

    def test_valid_nl_iban(self):
        self.assertTrue(IBANValidator.validate_iban(VALID_NL))

    def test_valid_de_iban(self):
        self.assertTrue(IBANValidator.validate_iban(VALID_DE))

    def test_valid_gb_iban(self):
        self.assertTrue(IBANValidator.validate_iban(VALID_GB))

    def test_spaced_input_is_normalized(self):
        spaced = "NL91 ABNA 0417 1643 00"
        self.assertTrue(IBANValidator.validate_iban(spaced))

    def test_lowercase_input_is_normalized(self):
        self.assertTrue(IBANValidator.validate_iban(VALID_NL.lower()))

    def test_mixed_case_and_spaces(self):
        self.assertTrue(IBANValidator.validate_iban("nl91 abna 0417 1643 00"))

    def test_empty_string_is_invalid(self):
        self.assertFalse(IBANValidator.validate_iban(""))

    def test_none_is_invalid(self):
        self.assertFalse(IBANValidator.validate_iban(None))

    def test_too_short_is_invalid(self):
        self.assertFalse(IBANValidator.validate_iban("NL9"))

    def test_unknown_country_code_is_invalid(self):
        # ZZ is not a recognised IBAN country code
        self.assertFalse(IBANValidator.validate_iban("ZZ91ABNA0417164300"))

    def test_wrong_length_for_country_is_invalid(self):
        # NL must be 18 chars; this is one short
        self.assertFalse(IBANValidator.validate_iban("NL91ABNA041716430"))
        # ...and one long
        self.assertFalse(IBANValidator.validate_iban("NL91ABNA04171643000"))

    def test_bad_format_letters_where_digits_expected(self):
        # Positions 3-4 must be digits (check digits); put letters there
        candidate = "NLABABNA0417164300"
        self.assertEqual(len(candidate), 18)  # right length, wrong format
        self.assertFalse(IBANValidator.validate_iban(candidate))

    def test_bad_checksum_is_invalid(self):
        # Tamper a single digit of a valid IBAN -> checksum must fail.
        # NL91ABNA0417164300 -> change trailing 0 to 1
        tampered = "NL91ABNA0417164301"
        self.assertEqual(len(tampered), len(VALID_NL))
        self.assertFalse(IBANValidator.validate_iban(tampered))

    def test_checksum_directly_known_good(self):
        # _validate_checksum expects a normalized (no spaces, upper) IBAN
        self.assertTrue(IBANValidator._validate_checksum(VALID_NL))
        self.assertTrue(IBANValidator._validate_checksum(VALID_DE))

    def test_checksum_directly_tampered(self):
        self.assertFalse(IBANValidator._validate_checksum("NL92ABNA0417164300"))


class TestIBANFormat(unittest.TestCase):
    """Tests for IBANValidator.format_iban."""

    def test_groups_every_four_chars(self):
        self.assertEqual(
            IBANValidator.format_iban(VALID_NL),
            "NL91 ABNA 0417 1643 00",
        )

    def test_empty_returns_empty(self):
        self.assertEqual(IBANValidator.format_iban(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(IBANValidator.format_iban(None), "")

    def test_strips_existing_spaces_and_regroups(self):
        self.assertEqual(
            IBANValidator.format_iban("NL91 ABNA 0417 1643 00"),
            "NL91 ABNA 0417 1643 00",
        )

    def test_uppercases(self):
        self.assertEqual(
            IBANValidator.format_iban(VALID_NL.lower()),
            "NL91 ABNA 0417 1643 00",
        )


class TestIBANExtractBankInfo(unittest.TestCase):
    """Tests for IBANValidator.extract_bank_info."""

    def test_invalid_iban_returns_empty_dict(self):
        self.assertEqual(IBANValidator.extract_bank_info("not-an-iban"), {})

    def test_empty_returns_empty_dict(self):
        self.assertEqual(IBANValidator.extract_bank_info(""), {})

    def test_valid_nl_iban_components(self):
        info = IBANValidator.extract_bank_info(VALID_NL)
        self.assertEqual(info["country_code"], "NL")
        self.assertEqual(info["check_digits"], "91")
        self.assertEqual(info["bank_identifier"], "ABNA")
        self.assertEqual(info["account_number"], "0417164300")

    def test_handles_spaced_input(self):
        info = IBANValidator.extract_bank_info("NL91 ABNA 0417 1643 00")
        self.assertEqual(info["country_code"], "NL")
        self.assertEqual(info["bank_identifier"], "ABNA")


class TestValidateAmount(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_amount."""

    def test_valid_amount_string(self):
        self.assertTrue(PaymentDataValidator.validate_amount("10.00"))

    def test_valid_amount_float(self):
        self.assertTrue(PaymentDataValidator.validate_amount(10.0))

    def test_min_boundary_inclusive(self):
        self.assertTrue(PaymentDataValidator.validate_amount("0.01"))

    def test_below_min_is_invalid(self):
        # 0.009 is below MIN (0.01) AND has 3 decimal places
        self.assertFalse(PaymentDataValidator.validate_amount("0.009"))

    def test_just_below_min_two_decimals(self):
        # 0.00 has exactly 2 decimals but is <= 0
        self.assertFalse(PaymentDataValidator.validate_amount("0.00"))

    def test_max_boundary_inclusive(self):
        self.assertTrue(PaymentDataValidator.validate_amount("10000.00"))

    def test_above_max_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount("10000.01"))

    def test_zero_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount("0"))

    def test_negative_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount("-5.00"))

    def test_more_than_two_decimals_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount("1.001"))

    def test_non_numeric_string_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount("abc"))

    def test_none_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_amount(None))

    def test_decimal_input(self):
        self.assertTrue(PaymentDataValidator.validate_amount(Decimal("25.50")))


class TestValidateCurrency(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_currency.

    NOTE: validate_currency returns ``currency and currency.upper() in ...``.
    For an empty string this returns the empty string "" (falsy) rather than a
    strict ``False``. Callers use ``if not validate_currency(...)`` so behaviour
    is correct, but the return type is not a clean bool. Asserted via
    truthiness (assertFalse / assertTrue), not identity. Flagged in report.
    """

    def test_eur_is_valid(self):
        self.assertTrue(PaymentDataValidator.validate_currency("EUR"))

    def test_lowercase_usd_is_valid(self):
        self.assertTrue(PaymentDataValidator.validate_currency("usd"))

    def test_gbp_is_valid(self):
        self.assertTrue(PaymentDataValidator.validate_currency("GBP"))

    def test_jpy_is_unsupported(self):
        self.assertFalse(PaymentDataValidator.validate_currency("JPY"))

    def test_empty_is_falsy(self):
        self.assertFalse(PaymentDataValidator.validate_currency(""))


class TestValidatePaymentType(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_payment_type."""

    def test_donation_lowercase(self):
        self.assertTrue(PaymentDataValidator.validate_payment_type("donation"))

    def test_donation_uppercase_normalized(self):
        self.assertTrue(PaymentDataValidator.validate_payment_type("DONATION"))

    def test_membership_dues(self):
        self.assertTrue(PaymentDataValidator.validate_payment_type("membership_dues"))

    def test_garbage_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_payment_type("garbage"))

    def test_empty_is_falsy(self):
        self.assertFalse(PaymentDataValidator.validate_payment_type(""))


class TestValidateEmail(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_email."""

    def test_valid_email(self):
        self.assertTrue(PaymentDataValidator.validate_email("user@example.com"))

    def test_missing_at_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_email("userexample.com"))

    def test_missing_tld_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_email("user@example"))

    def test_empty_is_invalid(self):
        self.assertFalse(PaymentDataValidator.validate_email(""))


class TestValidateDutchPostalCode(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_dutch_postal_code (delegation)."""

    def test_valid_dutch_postal_code(self):
        self.assertTrue(PaymentDataValidator.validate_dutch_postal_code("1234 AB"))

    def test_invalid_dutch_postal_code(self):
        self.assertFalse(PaymentDataValidator.validate_dutch_postal_code("0000 AB"))


class TestValidateMemberData(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_member_data."""

    def _valid_member(self):
        return {
            "first_name": "Jan",
            "last_name": "Jansen",
            "email": "jan@example.com",
            "country": "NL",
            "postal_code": "1234 AB",
            "iban": VALID_NL,
        }

    def test_fully_valid_member_has_no_errors(self):
        self.assertEqual(PaymentDataValidator.validate_member_data(self._valid_member()), [])

    def test_missing_required_fields(self):
        errors = PaymentDataValidator.validate_member_data({})
        self.assertIn("Missing required field: first_name", errors)
        self.assertIn("Missing required field: last_name", errors)
        self.assertIn("Missing required field: email", errors)

    def test_invalid_email_reported(self):
        data = self._valid_member()
        data["email"] = "not-an-email"
        errors = PaymentDataValidator.validate_member_data(data)
        self.assertIn("Invalid email address format", errors)

    def test_invalid_dutch_postal_code_reported(self):
        data = self._valid_member()
        data["postal_code"] = "0000 AB"
        errors = PaymentDataValidator.validate_member_data(data)
        self.assertIn("Invalid Dutch postal code format", errors)

    def test_non_nl_country_skips_postal_validation(self):
        data = self._valid_member()
        data["country"] = "BE"
        data["postal_code"] = "0000 AB"  # would be invalid as NL, but ignored
        errors = PaymentDataValidator.validate_member_data(data)
        self.assertNotIn("Invalid Dutch postal code format", errors)

    def test_invalid_iban_reported(self):
        data = self._valid_member()
        data["iban"] = "NL00BADIBAN"
        errors = PaymentDataValidator.validate_member_data(data)
        self.assertIn("Invalid IBAN format", errors)


class TestValidatePaymentData(unittest.TestCase):
    """Tests for PaymentDataValidator.validate_payment_data."""

    def _valid_payment(self):
        return {
            "amount": "25.00",
            "currency": "EUR",
            "payment_type": "donation",
            "description": "Annual donation",
            "redirect_url": "https://example.com/return",
        }

    def test_fully_valid_payment_has_no_errors(self):
        self.assertEqual(PaymentDataValidator.validate_payment_data(self._valid_payment()), [])

    def test_missing_amount(self):
        data = self._valid_payment()
        del data["amount"]
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Payment amount is required", errors)

    def test_invalid_amount(self):
        data = self._valid_payment()
        data["amount"] = "999999.00"
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Invalid payment amount: 999999.00", errors)

    def test_unsupported_currency(self):
        data = self._valid_payment()
        data["currency"] = "JPY"
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Unsupported currency: JPY", errors)

    def test_invalid_payment_type(self):
        data = self._valid_payment()
        data["payment_type"] = "bribe"
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Invalid payment type: bribe", errors)

    def test_too_short_description(self):
        data = self._valid_payment()
        data["description"] = "x"
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Payment description must be at least 3 characters", errors)

    def test_bad_redirect_url(self):
        data = self._valid_payment()
        data["redirect_url"] = "ftp://example.com"
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertIn("Invalid redirect URL format", errors)

    def test_default_currency_is_eur_when_absent(self):
        data = self._valid_payment()
        del data["currency"]
        errors = PaymentDataValidator.validate_payment_data(data)
        self.assertNotIn("Unsupported currency: EUR", errors)


class TestBusinessRuleValidator(unittest.TestCase):
    """Tests for BusinessRuleValidator eligibility checks."""

    def test_under_16_is_ineligible(self):
        errors = BusinessRuleValidator.validate_membership_eligibility({"birth_date": "2020-01-01"})
        self.assertIn("Member must be at least 16 years old", errors)

    def test_16_plus_is_eligible(self):
        errors = BusinessRuleValidator.validate_membership_eligibility({"birth_date": "1980-01-01"})
        self.assertEqual(errors, [])

    def test_invalid_birth_date_reported(self):
        errors = BusinessRuleValidator.validate_membership_eligibility({"birth_date": "not-a-date"})
        self.assertIn("Invalid birth date format", errors)

    def test_no_birth_date_yields_no_errors(self):
        self.assertEqual(BusinessRuleValidator.validate_membership_eligibility({}), [])

    def test_volunteer_delegates_to_membership_eligibility(self):
        errors = BusinessRuleValidator.validate_volunteer_eligibility({"birth_date": "2020-01-01"})
        self.assertIn("Member must be at least 16 years old", errors)

    def test_volunteer_eligible_adult(self):
        self.assertEqual(
            BusinessRuleValidator.validate_volunteer_eligibility({"birth_date": "1980-01-01"}),
            [],
        )


class TestModuleLevelWrappers(unittest.TestCase):
    """Tests for module-level convenience wrappers."""

    def test_module_validate_iban_valid(self):
        self.assertTrue(module_validate_iban(VALID_NL))

    def test_module_validate_iban_invalid(self):
        self.assertFalse(module_validate_iban("garbage"))

    def test_module_format_iban(self):
        self.assertEqual(module_format_iban(VALID_NL), "NL91 ABNA 0417 1643 00")

    def test_module_format_iban_empty(self):
        self.assertEqual(module_format_iban(""), "")


class TestIBANValidatorParityWithCanonical(unittest.TestCase):
    """Parity characterization: IBANValidator.validate_iban must return the same bool
    after delegating to the canonical validator that it returned with the original
    length-table + mod-97 implementation.

    Inputs:
      valid NL, DE, GB IBANs          -> True
      spaced / lowercase NL           -> True
      empty string, None, too-short   -> False
      unknown country ZZ              -> False (canonical fallback also fails checksum)
      wrong length for NL             -> False
      tampered checksum               -> False
      unknown-in-IBAN_LENGTHS but valid GR IBAN -> True (canonical fallback accepts it)
      valid BE IBAN                   -> True
    """

    CASES = [
        (VALID_NL, True, "valid NL IBAN"),
        (VALID_DE, True, "valid DE IBAN"),
        (VALID_GB, True, "valid GB IBAN"),
        ("NL91 ABNA 0417 1643 00", True, "spaced NL IBAN"),
        ("nl91abna0417164300", True, "lowercase NL IBAN"),
        ("", False, "empty string"),
        (None, False, "None"),
        ("NL9", False, "too short"),
        ("ZZ91ABNA0417164300", False, "unknown country ZZ (also fails mod-97)"),
        ("NL91ABNA041716430", False, "NL wrong length (too short)"),
        ("NL91ABNA04171643001", False, "NL wrong length (too long)"),
        ("NL91ABNA0417164301", False, "tampered checksum"),
        ("NL00BADIBAN", False, "obviously bad IBAN"),
        ("GR9608100010000001234567890", True, "valid GR IBAN (canonical fallback)"),
        ("BE68539007547034", True, "valid BE IBAN"),
    ]

    def _run_case(self, iban, expected_valid, description):
        result = IBANValidator.validate_iban(iban)
        self.assertEqual(
            result,
            expected_valid,
            f"{description}: IBANValidator.validate_iban({iban!r}) returned {result}, expected {expected_valid}",
        )

    def test_parity_valid_nl(self):
        self._run_case(VALID_NL, True, "valid NL IBAN")

    def test_parity_valid_de(self):
        self._run_case(VALID_DE, True, "valid DE IBAN")

    def test_parity_valid_gb(self):
        self._run_case(VALID_GB, True, "valid GB IBAN")

    def test_parity_spaced_nl(self):
        self._run_case("NL91 ABNA 0417 1643 00", True, "spaced NL IBAN")

    def test_parity_lowercase_nl(self):
        self._run_case("nl91abna0417164300", True, "lowercase NL IBAN")

    def test_parity_empty(self):
        self._run_case("", False, "empty string")

    def test_parity_none(self):
        self._run_case(None, False, "None")

    def test_parity_too_short(self):
        self._run_case("NL9", False, "too short")

    def test_parity_unknown_country_zz(self):
        # ZZ not in IBAN_LENGTHS (mollie) -> False; also fails mod-97 (canonical) -> False
        self._run_case("ZZ91ABNA0417164300", False, "unknown country ZZ")

    def test_parity_nl_wrong_length_short(self):
        self._run_case("NL91ABNA041716430", False, "NL wrong length (too short)")

    def test_parity_nl_wrong_length_long(self):
        self._run_case("NL91ABNA04171643001", False, "NL wrong length (too long)")

    def test_parity_tampered_checksum(self):
        self._run_case("NL91ABNA0417164301", False, "tampered checksum")

    def test_parity_obviously_bad(self):
        self._run_case("NL00BADIBAN", False, "obviously bad IBAN")

    def test_parity_valid_gr_canonical_fallback(self):
        # GR is in mollie's IBAN_LENGTHS (27 chars); valid GR IBAN -> True in both
        self._run_case("GR9608100010000001234567890", True, "valid GR IBAN")

    def test_parity_valid_be(self):
        self._run_case("BE68539007547034", True, "valid BE IBAN")

    def test_checksum_method_still_works(self):
        """_validate_checksum is kept for existing callers; verify it still works."""
        self.assertTrue(IBANValidator._validate_checksum(VALID_NL))
        self.assertTrue(IBANValidator._validate_checksum(VALID_DE))
        self.assertFalse(IBANValidator._validate_checksum("NL92ABNA0417164300"))


if __name__ == "__main__":
    unittest.main()
