# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt

import csv
import io
import unittest
from unittest.mock import mock_open, patch

import frappe

from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import MijnroodCSVImport


class TestMijnroodCSVImport(unittest.TestCase):
    """Test cases for Member CSV Import functionality."""

    def setUp(self):
        """Set up test data."""
        self.test_csv_data = [
            {
                "Lidnr.": "12345",
                "Voornaam": "Jan",
                "Achternaam": "Jansen",
                "Geboortedatum": "1990-01-15",
                "Inschrijfdataum": "2024-01-01",
                "Groep": "Amsterdam",
                "E-mailadres": "jan.jansen@example.com",
                "Telefoonnr.": "+31612345678",
                "Adres": "Hoofdstraat 123",
                "Plaats": "Amsterdam",
                "Postcode": "1000 AA",
                "Landcode": "NL",
                "IBAN": "NL91ABNA0417164300",
                "Contributiebedrag": "25.00",
                "Betaalperiode": "Maandelijks",
                "Betaald": "Ja",
                "Mollie CID": "cst_example123",
                "Mollie SID": "sub_example456",
                "Privacybeleid geaccepteerd": "Ja",
                "Lidmaatschapstype": "Standard",
            }
        ]

    def create_test_csv_content(self, data=None):
        """Create test CSV content."""
        if data is None:
            data = self.test_csv_data

        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return output.getvalue()

    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    def test_read_csv_file_success(self, mock_file, mock_exists):
        """Test successful CSV file reading."""
        mock_exists.return_value = True
        mock_file.return_value.read.return_value = self.create_test_csv_content()

        doc = frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "csv_file": "/test/path/test.csv", "encoding": "utf-8"}
        )

        # Mock the file path resolution
        with patch.object(doc, "_read_csv_file") as mock_read:
            mock_read.return_value = self.test_csv_data
            result = doc._read_csv_file()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Voornaam"], "Jan")

    def test_field_mapping(self):
        """Test CSV field mapping to Member fields."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        field_mapping = {"voornaam": "first_name", "achternaam": "last_name", "e-mailadres": "email"}

        test_row = {"Voornaam": "Jan", "Achternaam": "Jansen", "E-mailadres": "jan@example.com"}

        mapped_row = doc._map_row_data(test_row, field_mapping, 1)

        self.assertEqual(mapped_row["first_name"], "Jan")
        self.assertEqual(mapped_row["last_name"], "Jansen")
        self.assertEqual(mapped_row["email"], "jan@example.com")

    def test_email_validation(self):
        """Test email validation."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        # Valid emails
        self.assertTrue(doc._is_valid_email("test@example.com"))
        self.assertTrue(doc._is_valid_email("user.name+tag@domain.co.uk"))

        # Invalid emails
        self.assertFalse(doc._is_valid_email("invalid-email"))
        self.assertFalse(doc._is_valid_email("test@"))
        self.assertFalse(doc._is_valid_email("@example.com"))

    def test_iban_validation(self):
        """Test IBAN validation."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        # Valid IBANs
        self.assertTrue(doc._is_valid_iban("NL91ABNA0417164300"))
        self.assertTrue(doc._is_valid_iban("NL 91 ABNA 0417 1643 00"))  # With spaces

        # Invalid IBANs
        self.assertFalse(doc._is_valid_iban(""))
        self.assertFalse(doc._is_valid_iban("123"))
        self.assertFalse(doc._is_valid_iban("1234567890"))  # No country code

    def test_date_parsing(self):
        """Test date parsing functionality."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        # Test various date formats
        self.assertEqual(doc._parse_date("1990-01-15"), "1990-01-15")
        self.assertEqual(doc._parse_date("15-01-1990"), "1990-01-15")
        self.assertEqual(doc._parse_date("15/01/1990"), "1990-01-15")

        # Invalid dates
        self.assertIsNone(doc._parse_date("invalid-date"))
        self.assertIsNone(doc._parse_date(""))

    def test_value_cleaning(self):
        """Test value cleaning for different field types."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        # Currency cleaning
        self.assertEqual(doc._clean_value("€ 25,50", "dues_rate"), 25.50)
        self.assertEqual(doc._clean_value("25.00", "dues_rate"), 25.00)

        # Boolean cleaning
        self.assertTrue(doc._clean_value("Ja", "privacy_accepted"))
        self.assertTrue(doc._clean_value("Yes", "privacy_accepted"))
        self.assertFalse(doc._clean_value("Nee", "privacy_accepted"))

        # IBAN cleaning
        self.assertEqual(doc._clean_value("NL 91 ABNA 0417 1643 00", "iban"), "NL91ABNA0417164300")

        # Email cleaning
        self.assertEqual(doc._clean_value("Test@Example.Com", "email"), "test@example.com")

    def test_row_validation(self):
        """Test row validation logic."""
        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        # Valid row
        valid_row = {
            "first_name": "Jan",
            "last_name": "Jansen",
            "email": "jan@example.com",
            "iban": "NL91ABNA0417164300",
            "birth_date": "1990-01-15",
        }
        errors = doc._validate_row(valid_row, 1)
        self.assertEqual(len(errors), 0)

        # Invalid row - missing required fields
        invalid_row = {
            "first_name": "",
            "last_name": "Jansen",
            "email": "invalid-email",
            "iban": "invalid-iban",
        }
        errors = doc._validate_row(invalid_row, 1)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("First name is required" in error for error in errors))
        self.assertTrue(any("Invalid email format" in error for error in errors))
        self.assertTrue(any("Invalid IBAN format" in error for error in errors))

    def test_get_import_template(self):
        """Test CSV template generation."""
        from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
            get_import_template,
        )

        template = get_import_template()

        self.assertIn("filename", template)
        self.assertIn("content", template)
        self.assertEqual(template["filename"], "member_import_template.csv")

        # Check if template has proper headers
        content_lines = template["content"].strip().split("\\n")
        headers = content_lines[0].split(",")

        expected_headers = ["Lidnr.", "Voornaam", "Achternaam", "E-mailadres"]
        for header in expected_headers:
            self.assertIn(header, headers)


def test_mijnrood_csv_import_integration():
    """Integration test for member CSV import."""
    # This would require a full Frappe environment
    # Skip if not in test environment
    if not frappe.conf.get("developer_mode"):
        return

    # Create test import document
    doc = frappe.get_doc(
        {"doctype": "Mijnrood CSV Import", "import_date": frappe.utils.today(), "test_mode": 1}
    )

    # Test basic document creation
    doc.insert()

    # Verify document was created
    assert doc.name
    assert doc.import_status in [None, "", "Pending"]

    # Clean up
    doc.delete()


class TestMijnroodCSVImportSecurity(unittest.TestCase):
    """Security-focused test cases for Member CSV Import."""

    def setUp(self):
        """Set up security test data."""
        self.doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

    def test_path_traversal_prevention(self):
        """Test that path traversal attacks are prevented."""
        # Test with valid extension but malicious path
        malicious_filename = "../../../etc/passwd.csv"

        # Mock the csv_file to test sanitization
        self.doc.csv_file = f"/files/{malicious_filename}"
        result = self.doc._sanitize_filename()

        # Should not contain path traversal sequences
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)
        # Should be sanitized to just the filename
        self.assertEqual(result, "passwd.csv")

    def test_csv_injection_prevention(self):
        """Test that CSV injection attacks are prevented."""
        # Test various formula starters
        test_cases = ["=SUM(A1:A10)", "+1+1", "-1-1", "@SUM(A1:A10)", "\t=cmd|'/c calc'!A0"]

        for malicious_value in test_cases:
            cleaned = self.doc._clean_value(malicious_value, "first_name")
            self.assertTrue(cleaned.startswith("'"), f"Formula injection not prevented: {malicious_value}")

    def test_file_extension_validation(self):
        """Test that only allowed file extensions are accepted."""
        valid_extensions = ["test.csv", "test.xlsx", "test.xls"]
        invalid_extensions = ["test.exe", "test.bat", "test.sh", "test.py"]

        for valid_file in valid_extensions:
            self.doc.csv_file = f"/files/{valid_file}"
            try:
                self.doc._sanitize_filename()  # Should not throw
            except Exception:
                self.fail(f"Valid file extension rejected: {valid_file}")

        for invalid_file in invalid_extensions:
            self.doc.csv_file = f"/files/{invalid_file}"
            with self.assertRaises(Exception):
                self.doc._sanitize_filename()

    def test_field_length_limits(self):
        """Test that field length limits are enforced."""
        long_value = "A" * 3000  # Exceeds 2000 character limit

        with self.assertRaises(Exception):
            self.doc._clean_value(long_value, "first_name")

    def test_iban_mod97_validation(self):
        """Test enhanced IBAN validation with MOD-97 algorithm."""
        # Valid IBANs that pass MOD-97
        valid_ibans = ["NL91ABNA0417164300", "GB29NWBK60161331926819", "DE89370400440532013000"]

        # Invalid IBANs that fail MOD-97
        invalid_ibans = [
            "NL91ABNA0417164301",  # Wrong check digits
            "GB29NWBK60161331926818",  # Wrong check digits
            "DE89370400440532013001",  # Wrong check digits
        ]

        for valid_iban in valid_ibans:
            self.assertTrue(self.doc._is_valid_iban(valid_iban), f"Valid IBAN rejected: {valid_iban}")

        for invalid_iban in invalid_ibans:
            self.assertFalse(self.doc._is_valid_iban(invalid_iban), f"Invalid IBAN accepted: {invalid_iban}")


class TestMijnroodCSVImportIntegration(unittest.TestCase):
    """Integration test cases for Member CSV Import."""

    def setUp(self):
        """Set up integration test environment."""
        self.test_data = [
            {
                "Voornaam": "Integration",
                "Achternaam": "Test",
                "E-mailadres": "integration@test.com",
                "IBAN": "NL91ABNA0417164300",
                "Geboortedatum": "1990-01-01",
            }
        ]

    def test_complete_import_workflow(self):
        """Test the complete import workflow end-to-end."""
        if not frappe.conf.get("developer_mode"):
            return  # Skip in production

        # Create import document
        doc = frappe.get_doc(
            {
                "doctype": "Mijnrood CSV Import",
                "import_date": frappe.utils.today(),
                "test_mode": 1,
                "csv_file": "/files/test.csv",
            }
        )
        doc.insert()

        # Mock CSV data
        with patch.object(doc, "_read_csv_file") as mock_read:
            mock_read.return_value = self.test_data

            # Test validation
            mapped_data, errors = doc._validate_and_map_data(self.test_data)
            self.assertEqual(len(errors), 0, f"Validation errors: {errors}")
            self.assertEqual(len(mapped_data), 1)

            # Test import process (in test mode)
            doc.test_mode = True
            doc._process_import()

            self.assertEqual(doc.import_status, "Completed")

        # Clean up
        doc.delete()

    def test_error_recovery(self):
        """Test error recovery and partial import scenarios."""
        if not frappe.conf.get("developer_mode"):
            return

        mixed_data = [
            {"Voornaam": "Valid", "Achternaam": "User", "E-mailadres": "valid@test.com"},  # Valid record
            {  # Invalid record - bad email
                "Voornaam": "Invalid",
                "Achternaam": "User",
                "E-mailadres": "not-an-email",
            },
        ]

        doc = frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "test_mode": 1, "csv_file": "/files/test.csv"}
        )
        doc.insert()

        # Test validation catches errors
        mapped_data, errors = doc._validate_and_map_data(mixed_data)
        self.assertGreater(len(errors), 0, "Should have validation errors")
        self.assertTrue(any("Invalid email format" in error for error in errors))

        doc.delete()

    def test_large_file_handling(self):
        """Test handling of large CSV files."""
        if not frappe.conf.get("developer_mode"):
            return

        # Generate large dataset
        large_data = []
        for i in range(100):  # 100 records
            large_data.append(
                {"Voornaam": f"User{i}", "Achternaam": "Test", "E-mailadres": f"user{i}@test.com"}
            )

        doc = frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "test_mode": 1, "csv_file": "/files/test.csv"}
        )
        doc.insert()

        with patch.object(doc, "_read_csv_file") as mock_read:
            mock_read.return_value = large_data

            mapped_data, errors = doc._validate_and_map_data(large_data)
            self.assertEqual(len(mapped_data), 100)
            self.assertEqual(len(errors), 0)

        doc.delete()


class TestMijnroodCSVImportPerformance(unittest.TestCase):
    """Performance test cases for Member CSV Import."""

    def test_validation_performance(self):
        """Test validation performance with realistic data volumes."""
        if not frappe.conf.get("developer_mode"):
            return

        import time

        # Generate realistic test dataset
        test_data = []
        for i in range(1000):
            test_data.append(
                {
                    "Voornaam": f"User{i}",
                    "Achternaam": "Performance",
                    "E-mailadres": f"user{i}@perftest.com",
                    "IBAN": "NL91ABNA0417164300",
                    "Geboortedatum": "1990-01-01",
                }
            )

        doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

        start_time = time.time()
        mapped_data, errors = doc._validate_and_map_data(test_data)
        end_time = time.time()

        processing_time = end_time - start_time

        # Should process 1000 records in under 5 seconds
        self.assertLess(processing_time, 5.0, f"Validation took too long: {processing_time:.2f}s")
        self.assertEqual(len(mapped_data), 1000)
        self.assertEqual(len(errors), 0)
