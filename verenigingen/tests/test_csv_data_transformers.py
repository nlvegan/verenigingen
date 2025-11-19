"""
Unit Tests for CSV Data Transformers

Tests pure functions extracted from MijnroodCSVImport for data cleaning and transformation.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.csv.data_transformers import (
    clean_phone_number,
    clean_value,
    convert_country_code,
    convert_membership_type,
    parse_date,
)


class TestCSVDataTransformers(FrappeTestCase):
    """Test suite for CSV data transformation utilities"""

    def test_convert_country_code(self):
        """Test country code conversion"""
        # Standard codes
        self.assertEqual(convert_country_code("NL"), "Netherlands")
        self.assertEqual(convert_country_code("BE"), "Belgium")
        self.assertEqual(convert_country_code("DE"), "Germany")
        self.assertEqual(convert_country_code("GB"), "United Kingdom")
        self.assertEqual(convert_country_code("UK"), "United Kingdom")  # Alias

        # Case insensitive
        self.assertEqual(convert_country_code("nl"), "Netherlands")
        self.assertEqual(convert_country_code("Nl"), "Netherlands")

        # Unknown codes return original
        self.assertEqual(convert_country_code("XX"), "XX")
        self.assertEqual(convert_country_code("ZZ"), "ZZ")

    def test_clean_phone_number(self):
        """Test Dutch phone number cleaning and normalization"""
        # Dutch mobile numbers
        self.assertEqual(clean_phone_number("+31 6 12345678"), "0612345678")
        self.assertEqual(clean_phone_number("+31612345678"), "0612345678")
        self.assertEqual(clean_phone_number("06-1234-5678"), "0612345678")
        self.assertEqual(clean_phone_number("06 12 34 56 78"), "0612345678")

        # Dutch landline numbers
        self.assertEqual(clean_phone_number("+31 20 1234567"), "0201234567")
        self.assertEqual(clean_phone_number("+31301234567"), "0301234567")
        self.assertEqual(clean_phone_number("020-123-4567"), "0201234567")

        # International numbers (keep + prefix)
        self.assertEqual(clean_phone_number("+32 12 345678"), "+3212345678")
        self.assertEqual(clean_phone_number("+44 20 1234 5678"), "+442012345678")

        # Invalid numbers return empty string
        self.assertEqual(clean_phone_number("123"), "")
        self.assertEqual(clean_phone_number("invalid"), "")
        self.assertEqual(clean_phone_number(""), "")

    def test_convert_membership_type(self):
        """Test membership type conversion"""
        # Standard types
        self.assertEqual(convert_membership_type("lid"), "Standard")
        self.assertEqual(convert_membership_type("aspirant"), "Aspirant")
        self.assertEqual(convert_membership_type("overleden"), "Deceased")
        self.assertEqual(convert_membership_type("opgezegd"), "Terminated")
        self.assertEqual(convert_membership_type("geroyeerd"), "Expelled")
        self.assertEqual(convert_membership_type("dubbel"), "Duplicate")

        # Case insensitive
        self.assertEqual(convert_membership_type("LID"), "Standard")
        self.assertEqual(convert_membership_type("Lid"), "Standard")

        # Legacy types
        self.assertEqual(convert_membership_type("uitgeschreven"), "Terminated")
        self.assertEqual(convert_membership_type("geschorst"), "Suspended")

        # Unknown types return original
        self.assertEqual(convert_membership_type("unknown"), "unknown")
        self.assertEqual(convert_membership_type("custom"), "custom")

    def test_parse_date(self):
        """Test date parsing with multiple formats"""
        # ISO format
        self.assertEqual(parse_date("2023-12-31"), "2023-12-31")

        # Dutch format (DD-MM-YYYY)
        self.assertEqual(parse_date("31-12-2023"), "2023-12-31")

        # Dutch format with slashes
        self.assertEqual(parse_date("31/12/2023"), "2023-12-31")

        # US format (MM/DD/YYYY)
        self.assertEqual(parse_date("12/31/2023"), "2023-12-31")

        # Invalid dates return None
        self.assertIsNone(parse_date("invalid"))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date("99-99-9999"))

    def test_clean_value_dates(self):
        """Test clean_value with date fields"""
        self.assertEqual(clean_value("2023-12-31", "birth_date"), "2023-12-31")
        self.assertEqual(clean_value("31-12-2023", "member_since"), "2023-12-31")
        self.assertIsNone(clean_value("", "birth_date"))

    def test_clean_value_currency(self):
        """Test clean_value with currency fields"""
        self.assertEqual(clean_value("25.00", "dues_rate"), 25.0)
        self.assertEqual(clean_value("€ 25,50", "dues_rate"), 25.5)
        self.assertEqual(clean_value("25", "dues_rate"), 25.0)

    def test_clean_value_boolean(self):
        """Test clean_value with boolean fields"""
        # True values
        self.assertTrue(clean_value("ja", "privacy_accepted"))
        self.assertTrue(clean_value("yes", "privacy_accepted"))
        self.assertTrue(clean_value("1", "privacy_accepted"))
        self.assertTrue(clean_value("true", "privacy_accepted"))
        self.assertTrue(clean_value("waar", "privacy_accepted"))

        # False values
        self.assertFalse(clean_value("nee", "privacy_accepted"))
        self.assertFalse(clean_value("no", "privacy_accepted"))
        self.assertFalse(clean_value("0", "privacy_accepted"))

    def test_clean_value_iban(self):
        """Test clean_value with IBAN fields"""
        self.assertEqual(clean_value("NL91 ABNA 0417 1643 00", "iban"), "NL91ABNA0417164300")
        self.assertEqual(clean_value("nl91abna0417164300", "iban"), "NL91ABNA0417164300")

    def test_clean_value_email(self):
        """Test clean_value with email fields"""
        self.assertEqual(clean_value("Test@Example.COM", "email"), "test@example.com")
        self.assertEqual(clean_value("  user@domain.com  ", "email"), "user@domain.com")

    def test_clean_value_phone(self):
        """Test clean_value with phone number fields"""
        self.assertEqual(clean_value("+31 6 12345678", "contact_number"), "0612345678")
        self.assertEqual(clean_value("06-1234-5678", "contact_number"), "0612345678")

    def test_clean_value_country(self):
        """Test clean_value with country fields"""
        self.assertEqual(clean_value("NL", "country"), "Netherlands")
        self.assertEqual(clean_value("BE", "country"), "Belgium")

    def test_clean_value_membership_type(self):
        """Test clean_value with membership type fields"""
        self.assertEqual(clean_value("lid", "membership_type"), "Standard")
        self.assertEqual(clean_value("overleden", "membership_type"), "Deceased")

    def test_clean_value_empty_values(self):
        """Test clean_value handling of empty/null values"""
        # Empty strings return None
        self.assertIsNone(clean_value("", "any_field"))
        self.assertIsNone(clean_value("  ", "any_field"))

        # Common "no data" indicators return None
        self.assertIsNone(clean_value("-", "any_field"))
        self.assertIsNone(clean_value("N/A", "any_field"))
        self.assertIsNone(clean_value("n/a", "any_field"))
        self.assertIsNone(clean_value("NULL", "any_field"))
        self.assertIsNone(clean_value("null", "any_field"))
        self.assertIsNone(clean_value("UNKNOWN", "any_field"))
        self.assertIsNone(clean_value("?", "any_field"))

    def test_clean_value_security_csv_injection(self):
        """Test clean_value blocks CSV injection attacks"""
        with self.assertRaises(frappe.ValidationError):
            clean_value("=1+1", "any_field")

        with self.assertRaises(frappe.ValidationError):
            clean_value("@SUM(A1:A10)", "any_field")

        with self.assertRaises(frappe.ValidationError):
            clean_value("\t=cmd|'/c calc'!A1", "any_field")

        # But allow phone numbers with + prefix
        result = clean_value("+31612345678", "contact_number")
        self.assertEqual(result, "0612345678")

    def test_clean_value_security_length_limit(self):
        """Test clean_value enforces maximum field length"""
        # Very long string should be rejected
        long_value = "A" * 2001
        with self.assertRaises(frappe.ValidationError):
            clean_value(long_value, "any_field")

        # Exactly at limit should pass
        max_value = "A" * 2000
        result = clean_value(max_value, "text_field")
        self.assertEqual(len(result), 2000)

    def test_clean_value_default_behavior(self):
        """Test clean_value default behavior for unknown field types"""
        # Unknown field types just clean whitespace and return string
        self.assertEqual(clean_value("  test value  ", "unknown_field"), "test value")
        self.assertEqual(clean_value("123", "unknown_field"), "123")
