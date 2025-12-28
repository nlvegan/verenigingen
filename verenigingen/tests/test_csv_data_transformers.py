"""
Unit Tests for CSV Data Transformers

Tests pure functions extracted from MijnroodCSVImport for data cleaning and transformation.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from unittest.mock import MagicMock, patch

from verenigingen.utils.csv.data_transformers import (
    clean_phone_number,
    clean_value,
    convert_country_code,
    convert_membership_type,
    determine_membership_type_for_csv_import,
    get_dues_schedule_template_from_payment_period,
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


class TestMembershipTypeForCSVImport(FrappeTestCase):
    """Test suite for membership type determination based on Lidmaatschapstype"""

    def _create_mock_settings(self, default_type="Standard Member", aspirant_type="Aspirant Member"):
        """Create a mock settings object"""
        mock_settings = MagicMock()
        mock_settings.default_membership_type = default_type
        mock_settings.default_aspirant_membership_type = aspirant_type
        return mock_settings

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_regular_member_uses_default_type(self, mock_frappe):
        """Test that regular members (Lid) use default_membership_type"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True

        row_data = {"membership_type": "Lid"}
        result = determine_membership_type_for_csv_import(row_data)

        self.assertEqual(result, "Standard Member")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_aspirant_member_uses_aspirant_type(self, mock_frappe):
        """Test that aspirant members use default_aspirant_membership_type"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True

        row_data = {"membership_type": "Aspirant"}
        result = determine_membership_type_for_csv_import(row_data)

        self.assertEqual(result, "Aspirant Member")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_aspirant_case_insensitive(self, mock_frappe):
        """Test that aspirant detection is case-insensitive"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True

        # Test various case combinations
        for membership_type in ["aspirant", "ASPIRANT", "Aspirant", "aspirant-lid"]:
            row_data = {"membership_type": membership_type}
            result = determine_membership_type_for_csv_import(row_data)
            self.assertEqual(result, "Aspirant Member", f"Failed for: {membership_type}")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_empty_membership_type_uses_default(self, mock_frappe):
        """Test that empty membership_type uses default_membership_type"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True

        row_data = {"membership_type": ""}
        result = determine_membership_type_for_csv_import(row_data)

        self.assertEqual(result, "Standard Member")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_missing_default_type_throws(self, mock_frappe):
        """Test that missing default_membership_type throws error"""
        mock_settings = MagicMock()
        mock_settings.default_membership_type = None
        mock_settings.default_aspirant_membership_type = None
        mock_frappe.get_single.return_value = mock_settings

        row_data = {"membership_type": "Lid", "member_id": "12345"}
        with self.assertRaises(Exception):
            mock_frappe.throw.side_effect = frappe.ValidationError("No default membership type")
            determine_membership_type_for_csv_import(row_data)


class TestDuesScheduleTemplateFromPaymentPeriod(FrappeTestCase):
    """Test suite for dues schedule template lookup from payment period"""

    def _create_mock_settings(self, monthly="Monthly Template", quarterly="Quarterly Template", annual="Annual Template"):
        """Create a mock settings object"""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = monthly
        mock_settings.csv_quarterly_dues_schedule = quarterly
        mock_settings.csv_annual_dues_schedule = annual
        return mock_settings

    def _create_mock_template(self, is_template=True):
        """Create a mock template document"""
        mock_doc = MagicMock()
        mock_doc.is_template = is_template
        return mock_doc

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_monthly_payment_period(self, mock_frappe):
        """Test that Maandelijks maps to csv_monthly_dues_schedule"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True
        mock_frappe.get_doc.return_value = self._create_mock_template()

        for period in ["Maandelijks", "maandelijks", "Monthly", "per maand"]:
            row_data = {"payment_period": period}
            result = get_dues_schedule_template_from_payment_period(row_data)
            self.assertEqual(result, "Monthly Template", f"Failed for: {period}")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_quarterly_payment_period(self, mock_frappe):
        """Test that Kwartaal maps to csv_quarterly_dues_schedule"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True
        mock_frappe.get_doc.return_value = self._create_mock_template()

        for period in ["Kwartaal", "kwartaal", "Quarterly", "per kwartaal", "driemaandelijks"]:
            row_data = {"payment_period": period}
            result = get_dues_schedule_template_from_payment_period(row_data)
            self.assertEqual(result, "Quarterly Template", f"Failed for: {period}")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_annual_payment_period(self, mock_frappe):
        """Test that Jaarlijks maps to csv_annual_dues_schedule"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True
        mock_frappe.get_doc.return_value = self._create_mock_template()

        for period in ["Jaarlijks", "jaarlijks", "Annual", "per jaar", "jaar"]:
            row_data = {"payment_period": period}
            result = get_dues_schedule_template_from_payment_period(row_data)
            self.assertEqual(result, "Annual Template", f"Failed for: {period}")

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_missing_payment_period_throws(self, mock_frappe):
        """Test that missing payment_period throws error"""
        mock_frappe.throw.side_effect = frappe.ValidationError("Payment period required")

        row_data = {"payment_period": ""}
        with self.assertRaises(frappe.ValidationError):
            get_dues_schedule_template_from_payment_period(row_data)

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_unknown_payment_period_throws(self, mock_frappe):
        """Test that unknown payment_period throws error"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.throw.side_effect = frappe.ValidationError("Unknown payment period")

        row_data = {"payment_period": "Unknown Period"}
        with self.assertRaises(frappe.ValidationError):
            get_dues_schedule_template_from_payment_period(row_data)

    @patch("verenigingen.utils.csv.data_transformers.frappe")
    def test_non_template_throws(self, mock_frappe):
        """Test that non-template dues schedule throws error"""
        mock_settings = self._create_mock_settings()
        mock_frappe.get_single.return_value = mock_settings
        mock_frappe.db.exists.return_value = True
        mock_frappe.get_doc.return_value = self._create_mock_template(is_template=False)
        mock_frappe.throw.side_effect = frappe.ValidationError("Not a template")

        row_data = {"payment_period": "Maandelijks"}
        with self.assertRaises(frappe.ValidationError):
            get_dues_schedule_template_from_payment_period(row_data)
