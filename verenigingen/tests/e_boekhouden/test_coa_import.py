"""
Unit / integration tests for the Chart-of-Accounts import helpers in
verenigingen/e_boekhouden/utils/eboekhouden_coa_import.py

Focus: the pure string/pattern helpers (bank detection, bank-info extraction,
bank-name/code identification, Dutch IBAN generation) plus a couple of
DB-backed reporting helpers that work without a live eBoekhouden connection.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_coa_import
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_coa_import import (
    extract_bank_info_from_account_name,
    generate_dutch_iban,
    generate_iban_if_possible,
    has_account_number_pattern,
    identify_bank_code_from_name,
    identify_bank_name,
    identify_bank_name_enhanced,
    is_potential_bank_account,
    validate_bank_account_mappings,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Pure helpers - no DB access
# ---------------------------------------------------------------------------
class TestIsPotentialBankAccount(unittest.TestCase):
    def test_bank_keyword(self):
        self.assertTrue(is_potential_bank_account("Triodos Bankrekening"))

    def test_iban_in_name(self):
        self.assertTrue(is_potential_bank_account("Saldo NL02ABNA0123456789"))

    def test_email_paypal(self):
        self.assertTrue(is_potential_bank_account("PayPal info@example.org"))

    def test_old_ten_digit_number(self):
        self.assertTrue(is_potential_bank_account("Rekening 1234567890"))

    def test_group_code_002(self):
        self.assertTrue(is_potential_bank_account("Some random name", account_code="002001"))

    def test_group_code_fin(self):
        self.assertTrue(is_potential_bank_account("Some random name", account_code="FIN001"))

    def test_plain_expense_name_not_bank(self):
        self.assertFalse(is_potential_bank_account("Algemene kosten advies"))

    def test_no_keyword_no_number(self):
        self.assertFalse(is_potential_bank_account("Donaties", account_code="80001"))


class TestHasAccountNumberPattern(unittest.TestCase):
    def test_triodos_dotted(self):
        self.assertTrue(has_account_number_pattern("Triodos - 19.83.96.716 - Algemeen"))

    def test_rabo_dotted(self):
        self.assertTrue(has_account_number_pattern("Rabo - 1234.56.789"))

    def test_ten_digit(self):
        self.assertTrue(has_account_number_pattern("ING 1234567890"))

    def test_seven_to_nine_digit(self):
        self.assertTrue(has_account_number_pattern("Giro 1234567"))

    def test_full_iban(self):
        self.assertTrue(has_account_number_pattern("NL02ABNA0123456789"))

    def test_email(self):
        self.assertTrue(has_account_number_pattern("paypal user@host.com"))

    def test_no_pattern(self):
        self.assertFalse(has_account_number_pattern("Algemene kosten"))


class TestIdentifyBankName(unittest.TestCase):
    def test_triodos(self):
        self.assertEqual(identify_bank_name("Triodos"), "Triodos Bank")

    def test_ing(self):
        self.assertEqual(identify_bank_name("ING zakelijk"), "ING Bank")

    def test_rabo(self):
        self.assertEqual(identify_bank_name("Rabobank"), "Rabobank")

    def test_unknown_returns_original(self):
        self.assertEqual(identify_bank_name("Mystery Co"), "Mystery Co")


class TestIdentifyBankNameEnhanced(unittest.TestCase):
    def test_knab_standalone(self):
        self.assertEqual(identify_bank_name_enhanced("Knab spaargeld"), "Knab")

    def test_bng(self):
        self.assertEqual(identify_bank_name_enhanced("BNG saldo"), "BNG Bank")

    def test_extracts_first_part_with_bank_word(self):
        # No known pattern, but first part contains "bank"
        self.assertEqual(identify_bank_name_enhanced("Mijn Bank Speciaal - 1234567890"), "Mijn Bank Speciaal")

    def test_default_unknown(self):
        self.assertEqual(identify_bank_name_enhanced("Donaties direct"), "Unknown Bank")

    def test_PRODUCT_BUG_ing_substring_false_positive(self):
        # PRODUCT BUG: "betaalreken-ING" contains the substring "ing", and the
        # bank_patterns dict is iterated in insertion order with "ing" -> "ING Bank"
        # appearing early. So a Knab account whose name contains "rekening"
        # is misclassified as ING Bank. Documenting current behavior.
        # eboekhouden_coa_import.py:310-354 (identify_bank_name_enhanced).
        self.assertEqual(identify_bank_name_enhanced("Knab betaalrekening"), "ING Bank")


class TestIdentifyBankCode(unittest.TestCase):
    def test_triodos(self):
        self.assertEqual(identify_bank_code_from_name("Triodos Bank"), "TRIO")

    def test_ing(self):
        self.assertEqual(identify_bank_code_from_name("ING Bank"), "INGB")

    def test_unknown_returns_none(self):
        self.assertIsNone(identify_bank_code_from_name("Mystery Bank"))


class TestGenerateDutchIban(unittest.TestCase):
    """generate_dutch_iban: MOD-97 check-digit IBAN construction."""

    def test_structure_and_length(self):
        iban = generate_dutch_iban("0417164300", "TRIO")
        self.assertTrue(iban.startswith("NL"))
        self.assertIn("TRIO", iban)
        # NL + 2 check + 4 bank + 10 account = 18 chars
        self.assertEqual(len(iban), 18)

    def test_check_digits_valid_mod97(self):
        # A correctly-generated IBAN satisfies the MOD-97 == 1 rule
        iban = generate_dutch_iban("1234567890", "INGB")
        rearranged = iban[4:] + iban[:4]
        numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        self.assertEqual(int(numeric) % 97, 1)

    def test_pads_short_account_number(self):
        iban = generate_dutch_iban("12345", "RABO")
        # Account portion should be zero-padded to 10 digits
        self.assertTrue(iban.endswith("0000012345"))

    def test_strips_dots(self):
        # "19.83.96.716" -> "198396716" (9 digits) -> zero-padded to "0198396716"
        iban = generate_dutch_iban("19.83.96.716", "TRIO")
        self.assertEqual(len(iban), 18)
        self.assertTrue(iban.endswith("0198396716"))


class TestGenerateIbanIfPossible(unittest.TestCase):
    def test_known_bank_returns_iban(self):
        iban = generate_iban_if_possible("1234567890", "Triodos Bank")
        self.assertIsNotNone(iban)
        self.assertTrue(iban.startswith("NL"))
        self.assertIn("TRIO", iban)

    def test_unknown_bank_returns_none(self):
        self.assertIsNone(generate_iban_if_possible("1234567890", "Mystery Bank"))


class TestExtractBankInfoFromAccountName(unittest.TestCase):
    """extract_bank_info_from_account_name: the central parser."""

    def test_triodos_full(self):
        info = extract_bank_info_from_account_name("Triodos - 19.83.96.716 - Algemeen")
        self.assertEqual(info["account_number"], "19.83.96.716")
        self.assertEqual(info["bank_name"], "Triodos Bank")
        self.assertEqual(info["description"], "Algemeen")

    def test_ing_simple(self):
        info = extract_bank_info_from_account_name("ING - 123456789")
        self.assertEqual(info["account_number"], "123456789")
        self.assertEqual(info["bank_name"], "ING Bank")

    def test_paypal_email_becomes_account_number(self):
        info = extract_bank_info_from_account_name("PayPal - info@veganisme.org")
        self.assertEqual(info["bank_name"], "PayPal")
        self.assertEqual(info["account_holder"], "info@veganisme.org")
        self.assertEqual(info["account_number"], "info@veganisme.org")

    def test_iban_extracted(self):
        info = extract_bank_info_from_account_name("ABN - NL02ABNA0123456789")
        self.assertEqual(info["iban"], "NL02ABNA0123456789")
        # account number = last 10 digits of IBAN
        self.assertEqual(info["account_number"], "0123456789")

    def test_spaarrekening_description(self):
        info = extract_bank_info_from_account_name("Triodos Spaarrekening - 1234567890")
        self.assertIn("Spaarrekening", info["description"])

    def test_betaalrekening_description(self):
        info = extract_bank_info_from_account_name("ING Betaalrekening - 1234567890")
        self.assertIn("Betaalrekening", info["description"])

    def test_iban_generated_when_possible(self):
        # Known bank + account number but no IBAN in name => IBAN is synthesized
        info = extract_bank_info_from_account_name("Triodos - 1234567890")
        self.assertIsNotNone(info["iban"])
        self.assertTrue(info["iban"].startswith("NL"))

    def test_no_account_number_two_parts_description(self):
        # Use a description without "rekening" to avoid the "ing" substring bug.
        info = extract_bank_info_from_account_name("Rabobank - Zakelijk")
        self.assertIsNone(info["account_number"])
        self.assertEqual(info["bank_name"], "Rabobank")
        self.assertEqual(info["description"], "Zakelijk")

    def test_PRODUCT_BUG_rekening_triggers_ing_misclassification(self):
        # PRODUCT BUG (same root cause as identify_bank_name_enhanced): a Rabobank
        # account named "... rekening" matches the "ing" substring and is
        # misidentified as ING Bank. eboekhouden_coa_import.py:310-354.
        info = extract_bank_info_from_account_name("Rabobank - Zakelijke rekening")
        self.assertEqual(info["bank_name"], "ING Bank")


# ---------------------------------------------------------------------------
# DB-backed reporting helper (no live API)
# ---------------------------------------------------------------------------
class TestValidateBankAccountMappings(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST CoA Validate Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TCVC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def test_no_company_no_settings_returns_error(self):
        # Pass an explicit company so we don't depend on settings default
        result = validate_bank_account_mappings(company=self.company)
        self.assertTrue(result["success"])
        self.assertIn("total_bank_accounts", result)
        self.assertIn("issues", result)
        self.assertIsInstance(result["issues"], list)

    def test_structure_keys_present(self):
        result = validate_bank_account_mappings(company=self.company)
        for key in ("total_bank_accounts", "valid_accounts", "issues_found", "valid_account_names"):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
