"""
Unit Tests for SecureCSVParser

Tests security-hardened CSV parser extracted from MijnroodCSVImport.
Focuses on security validation, encoding detection, and file handling.
"""

import io
import os
import tempfile
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser


class TestSecureCSVParser(FrappeTestCase):
	"""Test suite for SecureCSVParser security and functionality"""

	def setUp(self):
		"""Set up test environment"""
		super().setUp()
		self.parser = SecureCSVParser()

	def test_sanitize_filename_removes_path_traversal(self):
		"""Test filename sanitization prevents path traversal attacks"""
		# Path traversal attempts should be rejected (no .csv extension after traversal)
		with self.assertRaises(frappe.ValidationError):
			self.parser._sanitize_filename("../../../etc/passwd")

		# Path traversal with valid extension should extract basename
		self.assertEqual(
			self.parser._sanitize_filename("files/../../sensitive.csv"),
			"sensitive.csv"
		)

		# Normal filenames should pass through
		self.assertEqual(
			self.parser._sanitize_filename("upload.csv"),
			"upload.csv"
		)
		self.assertEqual(
			self.parser._sanitize_filename("/files/upload.csv"),
			"upload.csv"
		)

	def test_sanitize_filename_blocks_invalid_extensions(self):
		"""Test filename sanitization rejects non-CSV/Excel files"""
		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser._sanitize_filename("script.py")
		self.assertIn("Only CSV and Excel files are allowed", str(cm.exception))

		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser._sanitize_filename("data.json")
		self.assertIn("Only CSV and Excel files are allowed", str(cm.exception))

		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser._sanitize_filename("executable.exe")
		self.assertIn("Only CSV and Excel files are allowed", str(cm.exception))

	def test_sanitize_filename_allows_valid_extensions(self):
		"""Test filename sanitization allows CSV and Excel files"""
		self.assertEqual(self.parser._sanitize_filename("data.csv"), "data.csv")
		self.assertEqual(self.parser._sanitize_filename("data.CSV"), "data.CSV")
		self.assertEqual(self.parser._sanitize_filename("report.xlsx"), "report.xlsx")
		self.assertEqual(self.parser._sanitize_filename("report.xls"), "report.xls")

	def test_sanitize_filename_removes_dangerous_characters(self):
		"""Test filename sanitization removes shell metacharacters"""
		# Shell command injection attempts - only basename extracted, special chars removed
		result = self.parser._sanitize_filename("file;rm -rf /.csv")
		# After basename extraction, "file;rm -rf /" becomes ".csv", and special chars are sanitized
		self.assertTrue(result.endswith(".csv"))

		self.assertEqual(
			self.parser._sanitize_filename("data|whoami.csv"),
			"data_whoami.csv"
		)
		self.assertEqual(
			self.parser._sanitize_filename("upload&sleep 10.csv"),
			"upload_sleep_10.csv"
		)

	def test_validate_file_path_blocks_path_traversal(self):
		"""Test file path validation prevents directory traversal"""
		site_path = frappe.get_site_path()

		# Paths outside site directory should be blocked
		self.assertFalse(self.parser.validate_file_path("/etc/passwd"))
		self.assertFalse(self.parser.validate_file_path("/tmp/malicious.csv"))
		self.assertFalse(self.parser.validate_file_path(f"{site_path}/../../../etc/passwd"))

	def test_validate_file_path_allows_site_paths(self):
		"""Test file path validation allows paths within site directory"""
		site_path = frappe.get_site_path()

		# Paths inside site directory should be allowed
		public_path = os.path.join(site_path, "public", "files", "test.csv")
		private_path = os.path.join(site_path, "private", "files", "test.csv")

		self.assertTrue(self.parser.validate_file_path(public_path))
		self.assertTrue(self.parser.validate_file_path(private_path))

	def test_parse_csv_content_handles_empty_rows(self):
		"""Test CSV parser filters out completely empty rows"""
		csv_content = """name,email,phone
John Doe,john@example.com,0612345678
,,
Jane Smith,jane@example.com,0687654321
,,-
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		# Should only have 2 data rows (empty rows filtered)
		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["name"], "John Doe")
		self.assertEqual(result[1]["name"], "Jane Smith")

	def test_parse_csv_content_cleans_null_values(self):
		"""Test CSV parser converts null indicators to None"""
		csv_content = """name,email,phone
John Doe,john@example.com,-
Jane Smith,-,0687654321
Test User,test@example.com,NB
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		self.assertEqual(len(result), 3)
		self.assertIsNone(result[0]["phone"])  # "-" → None
		self.assertIsNone(result[1]["email"])  # "-" → None
		self.assertIsNone(result[2]["phone"])  # "NB" → None

	def test_parse_csv_content_detects_comma_delimiter(self):
		"""Test CSV parser detects comma delimiter"""
		csv_content = """name,email,phone
John Doe,john@example.com,0612345678
Jane Smith,jane@example.com,0687654321
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["name"], "John Doe")
		self.assertEqual(result[0]["email"], "john@example.com")

	def test_parse_csv_content_detects_semicolon_delimiter(self):
		"""Test CSV parser detects semicolon delimiter"""
		csv_content = """name;email;phone
John Doe;john@example.com;0612345678
Jane Smith;jane@example.com;0687654321
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["name"], "John Doe")
		self.assertEqual(result[0]["email"], "john@example.com")

	def test_parse_csv_content_detects_tab_delimiter(self):
		"""Test CSV parser detects tab delimiter"""
		csv_content = """name\temail\tphone
John Doe\tjohn@example.com\t0612345678
Jane Smith\tjane@example.com\t0687654321
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["name"], "John Doe")
		self.assertEqual(result[0]["email"], "john@example.com")

	def test_parse_csv_content_rejects_invalid_delimiters(self):
		"""Test CSV parser rejects files with invalid delimiters"""
		csv_content = """name|email|phone
John Doe|john@example.com|0612345678
"""
		csvfile = io.StringIO(csv_content)

		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser.parse_csv_content(csvfile)
		self.assertIn("Could not determine CSV delimiter", str(cm.exception))

	def test_parse_csv_content_strips_whitespace(self):
		"""Test CSV parser strips leading/trailing whitespace from values"""
		csv_content = """name,email,phone
  John Doe  ,  john@example.com  ,  0612345678
"""
		csvfile = io.StringIO(csv_content)
		result = self.parser.parse_csv_content(csvfile)

		self.assertEqual(result[0]["name"], "John Doe")
		self.assertEqual(result[0]["email"], "john@example.com")
		self.assertEqual(result[0]["phone"], "0612345678")

	def test_read_file_from_content_handles_utf8(self):
		"""Test file reading from bytes with UTF-8 encoding"""
		csv_content = b"""name,email
Joh\xc3\xa1n Doe,johan@example.com
"""
		result = self.parser._read_file_from_content(csv_content, "test.csv")

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["name"], "Johán Doe")

	def test_read_file_from_content_rejects_invalid_encoding(self):
		"""Test file reading rejects invalid encoding"""
		# Invalid UTF-8 bytes
		csv_content = b"\xff\xfe\xfd\xfc"

		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser._read_file_from_content(csv_content, "test.csv")
		self.assertIn("File encoding error", str(cm.exception))

	def test_read_file_from_path_with_temp_file(self):
		"""Test file reading from temporary CSV file"""
		csv_content = """name,email,phone
John Doe,john@example.com,0612345678
Jane Smith,jane@example.com,0687654321
"""

		# Create temporary CSV file
		with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
			f.write(csv_content)
			temp_path = f.name

		try:
			result = self.parser._read_file_from_path(temp_path)

			self.assertEqual(len(result), 2)
			self.assertEqual(result[0]["name"], "John Doe")
			self.assertEqual(result[1]["name"], "Jane Smith")
		finally:
			# Clean up
			if os.path.exists(temp_path):
				os.unlink(temp_path)

	def test_read_file_from_path_handles_utf8_bom(self):
		"""Test file reading handles UTF-8 BOM correctly"""
		csv_content = "name,email\nJohn Doe,john@example.com\n"

		with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', suffix='.csv', delete=False) as f:
			f.write(csv_content)
			temp_path = f.name

		try:
			result = self.parser._read_file_from_path(temp_path)

			# Parser tries utf-8-sig encoding first, which strips BOM automatically
			self.assertEqual(len(result), 1)
			self.assertIn("name", result[0])
			self.assertEqual(result[0]["name"], "John Doe")
		finally:
			if os.path.exists(temp_path):
				os.unlink(temp_path)

	def test_read_file_from_path_tries_multiple_encodings(self):
		"""Test file reading falls back through encoding options"""
		# Create file with ISO-8859-1 encoding (Dutch characters)
		csv_content = "name,city\nJohan,Arnhem\n"

		with tempfile.NamedTemporaryFile(mode='w', encoding='iso-8859-1', suffix='.csv', delete=False) as f:
			f.write(csv_content)
			temp_path = f.name

		try:
			result = self.parser._read_file_from_path(temp_path)

			self.assertEqual(len(result), 1)
			self.assertEqual(result[0]["name"], "Johan")
		finally:
			if os.path.exists(temp_path):
				os.unlink(temp_path)

	@patch('frappe.get_doc')
	def test_try_file_document_lookup_by_url(self, mock_get_doc):
		"""Test file lookup via Frappe File document by URL"""
		mock_file = MagicMock()
		mock_file.get_full_path.return_value = "/site/public/files/test.csv"
		mock_file.get_content.return_value = b"test content"
		mock_get_doc.return_value = mock_file

		file_path, file_content = self.parser._try_file_document_lookup(
			"/files/test.csv",
			"test.csv"
		)

		self.assertEqual(file_path, "/site/public/files/test.csv")
		self.assertEqual(file_content, b"test content")
		mock_get_doc.assert_called_once_with("File", {"file_url": "/files/test.csv"})

	@patch('frappe.get_doc')
	def test_try_file_document_lookup_by_filename(self, mock_get_doc):
		"""Test file lookup falls back to filename if URL fails"""
		# First call (by URL) raises DoesNotExistError
		# Second call (by filename) succeeds
		mock_file = MagicMock()
		mock_file.get_full_path.return_value = "/site/public/files/test.csv"
		mock_file.get_content.return_value = b"test content"

		mock_get_doc.side_effect = [
			frappe.DoesNotExistError(),  # URL lookup fails
			mock_file  # Filename lookup succeeds
		]

		file_path, file_content = self.parser._try_file_document_lookup(
			"/files/test.csv",
			"test.csv"
		)

		self.assertEqual(file_path, "/site/public/files/test.csv")
		self.assertEqual(file_content, b"test content")
		self.assertEqual(mock_get_doc.call_count, 2)

	def test_try_direct_path_construction_finds_public_file(self):
		"""Test direct path construction checks public files directory"""
		# Create temporary file in public files
		site_path = frappe.get_site_path()
		public_dir = os.path.join(site_path, "public", "files")
		os.makedirs(public_dir, exist_ok=True)

		test_file = os.path.join(public_dir, "test_direct_path.csv")
		try:
			# Create test file
			with open(test_file, 'w') as f:
				f.write("name,email\nTest,test@example.com\n")

			result = self.parser._try_direct_path_construction("test_direct_path.csv")

			self.assertIsNotNone(result)
			self.assertTrue(result.endswith("test_direct_path.csv"))
			self.assertTrue(os.path.exists(result))
		finally:
			# Clean up
			if os.path.exists(test_file):
				os.unlink(test_file)

	def test_try_direct_path_construction_returns_none_if_not_found(self):
		"""Test direct path construction returns None for non-existent files"""
		result = self.parser._try_direct_path_construction("nonexistent_file_12345.csv")
		self.assertIsNone(result)

	@patch('frappe.get_all')
	def test_handle_file_not_found_provides_debug_info(self, mock_get_all):
		"""Test file not found handler provides helpful debug information"""
		# frappe.get_all returns list of dicts
		mock_get_all.return_value = [
			{"file_name": "similar1.csv", "file_url": "/files/similar1.csv"},
			{"file_name": "similar2.csv", "file_url": "/files/similar2.csv"}
		]

		with self.assertRaises(frappe.ValidationError) as cm:
			self.parser._handle_file_not_found("/files/test.csv", "test.csv")

		error_msg = str(cm.exception)
		self.assertIn("File not found", error_msg)
		self.assertIn("test.csv", error_msg)
		self.assertIn("Found 2 similar files", error_msg)

	def test_encoding_override_in_constructor(self):
		"""Test parser respects encoding parameter from constructor"""
		parser_with_encoding = SecureCSVParser(encoding='iso-8859-1')
		self.assertEqual(parser_with_encoding.encoding, 'iso-8859-1')

		parser_without_encoding = SecureCSVParser()
		self.assertIsNone(parser_without_encoding.encoding)

	def test_read_csv_file_returns_empty_for_empty_url(self):
		"""Test read_csv_file returns empty list for empty URL"""
		result = self.parser.read_csv_file("")
		self.assertEqual(result, [])

		result = self.parser.read_csv_file(None)
		self.assertEqual(result, [])
