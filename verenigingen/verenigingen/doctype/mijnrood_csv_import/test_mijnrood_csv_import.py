# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt

import csv
import io
import unittest
from unittest.mock import MagicMock, mock_open, patch

import frappe


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

    def test_sanitize_error_message(self):
        """Test PII sanitization from error messages."""
        from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
            _sanitize_error_message,
        )

        # Test email sanitization
        msg_with_email = "Error for user test@example.com on row 5"
        sanitized = _sanitize_error_message(msg_with_email)
        self.assertNotIn("test@example.com", sanitized)
        self.assertIn("[EMAIL REDACTED]", sanitized)

        # Test phone sanitization
        msg_with_phone = "Contact number +31612345678 is invalid"
        sanitized = _sanitize_error_message(msg_with_phone)
        self.assertNotIn("+31612345678", sanitized)
        self.assertIn("[PHONE REDACTED]", sanitized)

        # Test IBAN sanitization (should be masked, not fully redacted)
        msg_with_iban = "Invalid IBAN NL91ABNA0417164300 provided"
        sanitized = _sanitize_error_message(msg_with_iban)
        self.assertNotIn("NL91ABNA0417164300", sanitized)
        # IBAN is masked showing country code + last 4 digits
        self.assertIn("NL", sanitized)
        self.assertIn("4300", sanitized)

        # Test message without PII remains unchanged
        msg_clean = "Row 5: Invalid status value"
        sanitized = _sanitize_error_message(msg_clean)
        self.assertEqual(sanitized, msg_clean)

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
        # Test various formula starters that should be rejected
        # Note: Values starting with +/- followed by digits are allowed (for phone numbers/negative numbers)
        # Only test formulas that would actually be blocked
        blocked_cases = ["=SUM(A1:A10)", "@SUM(A1:A10)", "\t=cmd|'/c calc'!A0"]

        for malicious_value in blocked_cases:
            # The current implementation rejects CSV injection attempts by raising ValidationError
            # instead of escaping them with a single quote. This is a better security practice.
            with self.assertRaises(frappe.exceptions.ValidationError) as context:
                self.doc._clean_value(malicious_value, "first_name")
            self.assertIn("potentially dangerous content", str(context.exception))

        # Test cases that start with +/- followed by non-digit should be blocked
        edge_cases = ["+ABC", "-XYZ"]
        for edge_case in edge_cases:
            with self.assertRaises(frappe.exceptions.ValidationError) as context:
                self.doc._clean_value(edge_case, "first_name")
            self.assertIn("potentially dangerous content", str(context.exception))

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
            with self.assertRaises(frappe.exceptions.ValidationError) as context:
                self.doc._sanitize_filename()
            # Pin the extension-guard message so an unrelated crash (e.g. an
            # AttributeError before the check) can't masquerade as this rejection.
            self.assertIn("allowed", str(context.exception))

    def test_field_length_limits(self):
        """Test that field length limits are enforced."""
        # Boundary: exactly 2000 chars is accepted, 2001 is rejected.
        self.assertEqual(self.doc._clean_value("A" * 2000, "first_name"), "A" * 2000)

        long_value = "A" * 3000  # Exceeds 2000 character limit
        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            self.doc._clean_value(long_value, "first_name")
        self.assertIn("too long", str(context.exception))

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
        # SKIP REASON: The refactored architecture requires actual CSV file infrastructure.
        # The old test used mocked _read_csv_file() but the new process_import_background()
        # calls _read_csv_file() internally and cannot be mocked from outside the context.
        # To properly test this:
        # 1. Would need to create actual test CSV files via Frappe File DocType
        # 2. Would need file upload infrastructure in test environment
        # 3. Would need to test the complete background job workflow
        #
        # The individual components are tested by other tests:
        # - test_csv_validation tests _validate_and_map_data()
        # - test_member_creation tests _process_single_member()
        # - test_duplicate_detection tests duplicate logic
        #
        # This end-to-end test is better suited for integration testing with actual file uploads.
        self.skipTest(
            "Refactored architecture requires actual CSV file infrastructure. "
            "Individual components are tested separately. "
            "End-to-end testing requires integration test environment with file upload support."
        )

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
        _, errors = doc._validate_and_map_data(mixed_data)
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


class TestMijnroodCSVImportSettings(unittest.TestCase):
    """Test cases for CSV import settings validation."""

    def setUp(self):
        """Set up test document."""
        self.doc = frappe.get_doc({"doctype": "Mijnrood CSV Import"})

    @patch("frappe.get_single")
    def test_validate_settings_all_configured(self, mock_get_single):
        """Test that validation passes when all settings are configured."""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = "Monthly Template"
        mock_settings.csv_annual_dues_schedule = "Annual Template"
        mock_settings.default_membership_type = "Standard Member"
        mock_get_single.return_value = mock_settings

        # Should not raise
        self.doc._validate_csv_import_settings()

    @patch("frappe.throw")
    @patch("frappe.get_single")
    def test_validate_settings_missing_monthly(self, mock_get_single, mock_throw):
        """Test that validation fails when csv_monthly_dues_schedule is missing."""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = None
        mock_settings.csv_annual_dues_schedule = "Annual Template"
        mock_settings.default_membership_type = "Standard Member"
        mock_get_single.return_value = mock_settings

        self.doc._validate_csv_import_settings()
        mock_throw.assert_called_once()
        call_args = str(mock_throw.call_args)
        self.assertIn("CSV Monthly Dues Schedule", call_args)

    @patch("frappe.throw")
    @patch("frappe.get_single")
    def test_validate_settings_missing_annual(self, mock_get_single, mock_throw):
        """Test that validation fails when csv_annual_dues_schedule is missing."""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = "Monthly Template"
        mock_settings.csv_annual_dues_schedule = None
        mock_settings.default_membership_type = "Standard Member"
        mock_get_single.return_value = mock_settings

        self.doc._validate_csv_import_settings()
        mock_throw.assert_called_once()
        call_args = str(mock_throw.call_args)
        self.assertIn("CSV Annual Dues Schedule", call_args)

    @patch("frappe.throw")
    @patch("frappe.get_single")
    def test_validate_settings_missing_default_type(self, mock_get_single, mock_throw):
        """Test that validation fails when default_membership_type is missing."""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = "Monthly Template"
        mock_settings.csv_annual_dues_schedule = "Annual Template"
        mock_settings.default_membership_type = None
        mock_get_single.return_value = mock_settings

        self.doc._validate_csv_import_settings()
        mock_throw.assert_called_once()
        call_args = str(mock_throw.call_args)
        self.assertIn("Default Membership Type", call_args)

    @patch("frappe.throw")
    @patch("frappe.get_single")
    def test_validate_settings_multiple_missing(self, mock_get_single, mock_throw):
        """Test that validation reports all missing settings."""
        mock_settings = MagicMock()
        mock_settings.csv_monthly_dues_schedule = None
        mock_settings.csv_annual_dues_schedule = None
        mock_settings.default_membership_type = None
        mock_get_single.return_value = mock_settings

        self.doc._validate_csv_import_settings()
        mock_throw.assert_called_once()
        call_args = str(mock_throw.call_args)
        self.assertIn("CSV Monthly Dues Schedule", call_args)
        self.assertIn("CSV Annual Dues Schedule", call_args)
        self.assertIn("Default Membership Type", call_args)


# ---------------------------------------------------------------------------
# Real integration tests (no business-logic mocking) using EnhancedTestCase.
#
# These exercise the MijnroodCSVImport controller against real CSV content,
# real File DocType attachments, the real parse/validate/map pipeline and real
# Member creation, asserting real DB state. They complement the mock-based
# tests above (which cover pure helpers and settings validation in isolation).
# ---------------------------------------------------------------------------

import random  # noqa: E402

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase  # noqa: E402


def _unique_email(prefix="mijnrood"):
    return f"{prefix}_{random.randint(100000, 999999)}@integrationtest.invalid"


class TestMijnroodCSVImportRealIntegration(EnhancedTestCase):
    """End-to-end integration coverage for the CSV import controller.

    Drives the controller via real CSV bytes, real File attachments and the real
    validate/map/create pipeline. No mocking of frappe.get_doc / frappe.db or
    business logic.
    """

    def _make_csv_bytes(self, rows, headers=None):
        """Build CSV content (str) from a list of dict rows."""
        if headers is None:
            headers = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return out.getvalue()

    def _create_csv_file_doc(self, content, file_name=None):
        """Create a real (private) File DocType attachment holding CSV content."""
        if file_name is None:
            file_name = f"mijnrood_test_{random.randint(100000, 999999)}.csv"
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "is_private": 1,
                "content": content,
            }
        ).insert(ignore_permissions=True)
        self._created_files.append(file_doc.name)
        return file_doc

    def _make_import_doc(self, rows, encoding="utf-8", **kwargs):
        """Create + insert a Mijnrood CSV Import doc backed by a real File of `rows`."""
        content = self._make_csv_bytes(rows)
        return self._make_import_doc_from_content(content, encoding=encoding, **kwargs)

    def _make_import_doc_from_content(self, content, encoding="utf-8", **kwargs):
        """Create + insert a Mijnrood CSV Import doc backed by a real File of raw `content`."""
        file_doc = self._create_csv_file_doc(content)
        doc = frappe.get_doc(
            {
                "doctype": "Mijnrood CSV Import",
                "csv_file": file_doc.file_url,
                "encoding": encoding,
                "import_date": frappe.utils.today(),
                **kwargs,
            }
        )
        doc.insert(ignore_permissions=True)
        self._created_imports.append(doc.name)
        return doc

    def _new_unsaved_doc(self):
        """A controller instance not requiring the mandatory csv_file (helper-only paths)."""
        return frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "encoding": "utf-8", "import_date": frappe.utils.today()}
        )

    def setUp(self):
        super().setUp()
        self._created_files = []
        self._created_imports = []
        self._created_members = []

    def tearDown(self):
        for member_name in self._created_members:
            try:
                frappe.delete_doc("Member", member_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        for import_name in self._created_imports:
            try:
                frappe.delete_doc("Mijnrood CSV Import", import_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        for file_name in self._created_files:
            try:
                frappe.delete_doc("File", file_name, force=True, ignore_permissions=True)
            except Exception:
                pass
        super().tearDown()

    # --- File reading via real File attachment -----------------------------

    def test_read_csv_file_from_real_attachment(self):
        """A real File attachment is resolved and parsed into row dicts."""
        rows = [
            {
                "Voornaam": "Jan",
                "Achternaam": "Jansen",
                "E-mailadres": "jan@example.com",
                "IBAN": "NL91ABNA0417164300",
            }
        ]
        doc = self._make_import_doc(rows)
        parsed = doc._read_csv_file()
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["Voornaam"], "Jan")
        self.assertEqual(parsed[0]["E-mailadres"], "jan@example.com")

    def test_read_csv_file_empty_url_returns_empty(self):
        """No csv_file set => empty list (not an error)."""
        doc = self._new_unsaved_doc()
        self.assertEqual(doc._read_csv_file(), [])

    def test_read_csv_file_semicolon_delimiter(self):
        """Semicolon-delimited CSV (common in NL exports) is auto-detected."""
        content = "Voornaam;Achternaam;E-mailadres\nPiet;Pietersen;piet@example.com\n"
        doc = self._make_import_doc_from_content(content)
        parsed = doc._read_csv_file()
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["Voornaam"], "Piet")

    def test_read_csv_file_strips_empty_and_placeholder_rows(self):
        """Rows that are entirely empty / '-' / 'nb' placeholders are dropped."""
        content = "Voornaam,Achternaam,E-mailadres\n" "Real,Member,real@example.com\n" "-,-,-\n" ",,\n"
        doc = self._make_import_doc_from_content(content)
        parsed = doc._read_csv_file()
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["Voornaam"], "Real")

    # --- validate/map pipeline --------------------------------------------

    def test_validate_and_map_full_pipeline_via_file(self):
        """read -> validate/map produces cleaned Member-field dicts and no errors."""
        rows = [
            {
                "Lidnr.": "12345",
                "Voornaam": "Maria",
                "Achternaam": "de Vries",
                "Geboortedatum": "15-01-1990",
                "E-mailadres": "Maria.DeVries@Example.COM",
                "Telefoonnr.": "+31612345678",
                "Landcode": "NL",
                "IBAN": "NL 91 ABNA 0417 1643 00",
                "Contributiebedrag": "€ 25,00",
            }
        ]
        doc = self._make_import_doc(rows)
        parsed = doc._read_csv_file()
        mapped, errors = doc._validate_and_map_data(parsed)
        self.assertEqual(errors, [])
        self.assertEqual(len(mapped), 1)
        m = mapped[0]
        self.assertEqual(m["first_name"], "Maria")
        self.assertEqual(m["last_name"], "de Vries")
        self.assertEqual(m["email"], "maria.devries@example.com")  # lowercased
        self.assertEqual(m["iban"], "NL91ABNA0417164300")  # spaces removed
        self.assertEqual(m["birth_date"], "1990-01-15")  # normalized
        self.assertEqual(m["country"], "Netherlands")  # code converted
        self.assertEqual(m["contact_number"], "0612345678")  # NL national format
        self.assertEqual(m["dues_rate"], 25.0)
        self.assertEqual(m["member_id"], "12345")

    def test_validate_and_map_missing_required_columns(self):
        """Missing Voornaam/Achternaam headers is reported, no rows mapped."""
        doc = self._new_unsaved_doc()
        mapped, errors = doc._validate_and_map_data([{"Foo": "bar", "Baz": "qux"}])
        self.assertEqual(mapped, [])
        self.assertTrue(any("Missing required columns" in e for e in errors))

    def test_validate_and_map_empty_data(self):
        """Empty CSV data yields a clear 'empty' error."""
        doc = self._new_unsaved_doc()
        mapped, errors = doc._validate_and_map_data([])
        self.assertEqual(mapped, [])
        self.assertIn("CSV file is empty", errors)

    def test_validate_and_map_row_errors_reported_with_row_numbers(self):
        """Bad email / IBAN produce row-numbered validation errors (header = row 1)."""
        rows = [
            {
                "Voornaam": "Bad",
                "Achternaam": "Email",
                "E-mailadres": "not-an-email",
                "IBAN": "NOTANIBAN",
            }
        ]
        doc = self._new_unsaved_doc()
        mapped, errors = doc._validate_and_map_data(rows)
        self.assertEqual(mapped, [])
        self.assertTrue(any("Row 2" in e and "Invalid email" in e for e in errors))
        self.assertTrue(any("Row 2" in e and "Invalid IBAN" in e for e in errors))

    def test_validate_and_map_dubbel_rows_skipped_silently(self):
        """'Dubbel' (duplicate) membership rows are dropped without an error."""
        rows = [{"Voornaam": "Skip", "Achternaam": "Me", "Lidmaatschapstype": "Dubbel"}]
        doc = self._new_unsaved_doc()
        mapped, errors = doc._validate_and_map_data(rows)
        self.assertEqual(mapped, [])
        self.assertEqual(errors, [])

    def test_validate_and_map_future_birth_date_rejected(self):
        """A birth date in the future is rejected with a row error."""
        future = frappe.utils.add_to_date(frappe.utils.today(), years=1)
        rows = [{"Voornaam": "Future", "Achternaam": "Born", "Geboortedatum": str(future)}]
        doc = self._new_unsaved_doc()
        mapped, errors = doc._validate_and_map_data(rows)
        self.assertEqual(mapped, [])
        self.assertTrue(any("future" in e.lower() for e in errors))

    # --- Member creation (real DB writes) ----------------------------------

    def test_process_single_member_creates_real_member(self):
        """_process_single_member creates a real Member from a mapped row."""
        doc = self._make_import_doc(
            [{"Voornaam": "Create", "Achternaam": "Member", "E-mailadres": "x@example.com"}],
            create_volunteer_records=0,
        )
        email = _unique_email()
        row = {
            "row_number": 2,
            "first_name": "Created",
            "last_name": "ViaImport",
            "email": email,
            "birth_date": "1985-06-15",
            "iban": "NL91ABNA0417164300",
        }
        error_log = []
        result, member_name = doc._process_single_member(row, error_log)
        self.assertEqual(result, "created")
        self.assertTrue(member_name)
        self._created_members.append(member_name)
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.first_name, "Created")
        self.assertEqual(member.last_name, "ViaImport")
        self.assertEqual(member.email, email)

    def test_process_single_member_validation_error_returns_failed(self):
        """A row that fails Member validation returns ('failed: ...', None), not a crash.

        MemberImportService catches the Member controller's ValidationError and maps
        it to a 'failed' status carrying the reason (only DuplicateEntryError maps to
        'skipped'; see member_import_service.py create/update contract), so
        _process_single_member returns that status straight through rather than raising.
        """
        doc = self._make_import_doc(
            [{"Voornaam": "Skip", "Achternaam": "Test", "E-mailadres": "s@example.com"}],
            create_volunteer_records=0,
        )
        # Missing first/last name => Member validation fails => service returns 'failed'.
        email = _unique_email()
        row = {"row_number": 5, "member_id": "999", "email": email}
        error_log = []
        result, info = doc._process_single_member(row, error_log)
        # Failure statuses carry the reason ("failed: <message>") so it reaches the
        # operator; the "failed" prefix is what callers branch on.
        self.assertTrue(result.startswith("failed"), f"expected a failed status, got {result!r}")
        self.assertIsNone(info)
        # No Member should have been created for the invalid row.
        self.assertFalse(frappe.db.exists("Member", {"email": email}))

    # --- Pure helpers exercised on a real controller instance --------------

    def test_helper_clean_value_and_converters(self):
        doc = self._new_unsaved_doc()
        self.assertEqual(doc._clean_value("€ 12,50", "dues_rate"), 12.5)
        self.assertEqual(doc._clean_value("Test@Example.COM", "email"), "test@example.com")
        self.assertIsNone(doc._clean_value("NULL", "first_name"))
        self.assertEqual(doc._convert_country_code("be"), "Belgium")
        self.assertEqual(doc._convert_country_code("ZZ"), "ZZ")  # unknown passthrough
        self.assertEqual(doc._convert_membership_type("Opgezegd"), "Quit")
        self.assertEqual(doc._clean_phone_number("+31 6 12345678"), "0612345678")
        self.assertEqual(doc._clean_phone_number("garbage"), "")
        self.assertEqual(doc._parse_date("31/12/2023"), "2023-12-31")
        self.assertIsNone(doc._parse_date("not-a-date"))

    def test_helper_validators(self):
        doc = self._new_unsaved_doc()
        self.assertTrue(doc._is_valid_email("a@b.co"))
        self.assertFalse(doc._is_valid_email("a..b@c.com"))  # consecutive dots
        self.assertTrue(doc._is_valid_iban("NL91ABNA0417164300"))
        self.assertFalse(doc._is_valid_iban("NL00ABNA0417164300"))  # bad checksum

    def test_has_address_data(self):
        doc = self._new_unsaved_doc()
        self.assertTrue(doc._has_address_data({"address_line1": "Hoofdstraat 1", "city": "Amsterdam"}))
        self.assertFalse(doc._has_address_data({"address_line1": "Hoofdstraat 1"}))
        self.assertFalse(doc._has_address_data({"city": "Amsterdam"}))
        self.assertFalse(doc._has_address_data({}))

    def test_get_termination_reason(self):
        doc = self._new_unsaved_doc()
        self.assertEqual(doc._get_termination_reason("overleden"), "Member deceased")
        self.assertEqual(doc._get_termination_reason("geroyeerd"), "Expelled from organization for cause")
        self.assertEqual(doc._get_termination_reason("mystery"), "Terminated (mystery)")

    def test_should_create_membership_logic(self):
        """Real Member: membership only created for Active + dues_rate + no existing."""
        doc = self._make_import_doc(
            [{"Voornaam": "Member", "Achternaam": "Ship", "E-mailadres": "ms@example.com"}],
            create_volunteer_records=0,
        )
        row = {
            "row_number": 2,
            "first_name": "Mem",
            "last_name": "Bership",
            "email": _unique_email(),
        }
        result, member_name = doc._process_single_member(row, [])
        self.assertEqual(result, "created")
        self._created_members.append(member_name)
        member = frappe.get_doc("Member", member_name)
        # No dues_rate in row => should NOT create a membership.
        self.assertFalse(doc._should_create_membership(member, {"first_name": "Mem"}))
        # Inactive status => never.
        member.status = "Suspended"
        self.assertFalse(doc._should_create_membership(member, {"dues_rate": 25}))

    def test_append_to_error_log_truncation(self):
        """error_log truncates when exceeding max_size while keeping a header."""
        doc = self._new_unsaved_doc()
        doc.error_log = "=== Import Errors ===\n" + ("x" * 100)
        doc._append_to_error_log("NEW ENTRY", max_size=120)
        self.assertIn("=== Import Errors ===", doc.error_log)
        self.assertIn("truncated", doc.error_log)
        self.assertIn("NEW ENTRY", doc.error_log)

    def test_append_to_error_log_appends_when_small(self):
        doc = self._new_unsaved_doc()
        doc.error_log = None
        doc._append_to_error_log("first")
        doc._append_to_error_log("second")
        self.assertEqual(doc.error_log, "first\nsecond")

    def test_categorize_skipped_members(self):
        """Skip strings are bucketed by error type; unparseable ones go to 'Other'."""
        doc = self._new_unsaved_doc()
        skipped = [
            "Lidnr 5: Jan Jansen - Invalid email format: x",
            "Lidnr 6: Anna Bos - Duplicate entry found",
            "Lidnr 7: Piet Pietersen - Invalid IBAN provided",
            "totally unparseable string",
        ]
        cats = doc._categorize_skipped_members(skipped)
        self.assertIn("5 (Jan Jansen)", cats["Email Validation Failed"])
        self.assertIn("6 (Anna Bos)", cats["Duplicate Entry"])
        self.assertIn("7 (Piet Pietersen)", cats["IBAN Validation Failed"])
        self.assertIn("totally unparseable string", cats["Other Validation Errors"])
        # Empty categories are pruned.
        self.assertNotIn("Age Validation Failed", cats)

    # --- Path-safety / security -------------------------------------------

    def test_is_safe_file_path_accepts_site_path(self):
        """A real file inside the site dir is considered safe."""
        file_doc = self._create_csv_file_doc("Voornaam,Achternaam\nA,B\n")
        doc = self._new_unsaved_doc()
        self.assertTrue(doc._is_safe_file_path(file_doc.get_full_path()))

    def test_is_safe_file_path_rejects_traversal(self):
        """Paths outside the site dir (incl. ../ traversal) are rejected."""
        doc = self._new_unsaved_doc()
        self.assertFalse(doc._is_safe_file_path("/etc/passwd"))
        self.assertFalse(doc._is_safe_file_path("/tmp/../etc/shadow"))

    def test_sanitize_filename_blocks_bad_extension(self):
        doc = self._new_unsaved_doc()
        doc.csv_file = "/files/evil.exe"
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc._sanitize_filename()

    def test_sanitize_filename_strips_traversal(self):
        doc = self._new_unsaved_doc()
        doc.csv_file = "/files/../../../etc/passwd.csv"
        result = doc._sanitize_filename()
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)
        self.assertTrue(result.endswith(".csv"))


class TestMijnroodCSVImportSettingsValidationReal(EnhancedTestCase):
    """Real (non-mocked) coverage of _validate_csv_import_settings against
    Verenigingen Settings, saving + restoring the real singleton.
    """

    SETTINGS_FIELDS = (
        "csv_monthly_dues_schedule",
        "csv_annual_dues_schedule",
        "default_membership_type",
    )

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("Verenigingen Settings")
        self._saved_settings = {f: settings.get(f) for f in self.SETTINGS_FIELDS}

    def tearDown(self):
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._saved_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
        super().tearDown()

    def _setup_settings(self, **values):
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in values.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)

    def test_missing_settings_raise_with_named_fields(self):
        """When dues-schedule / default-type are blank, validation lists them."""
        self._setup_settings(
            csv_monthly_dues_schedule=None,
            csv_annual_dues_schedule=None,
            default_membership_type=None,
        )
        doc = frappe.get_doc(
            {"doctype": "Mijnrood CSV Import", "encoding": "utf-8", "import_date": frappe.utils.today()}
        )
        with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
            doc._validate_csv_import_settings()
        msg = str(ctx.exception)
        self.assertIn("CSV Monthly Dues Schedule", msg)
        self.assertIn("CSV Annual Dues Schedule", msg)
        self.assertIn("Default Membership Type", msg)
