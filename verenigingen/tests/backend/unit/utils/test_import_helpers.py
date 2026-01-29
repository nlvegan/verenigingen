"""
Tests for import_helpers utility functions.

Tests cover:
- Error log persistence with size/line caps
- Filename uniqueness
- Truncation for UI display
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.import_helpers import (
    persist_full_error_log,
    truncate_error_log_for_display,
)


class TestPersistFullErrorLog(EnhancedTestCase):
    """Test persist_full_error_log function"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        # Create a test document to attach files to
        self.test_doctype = "ToDo"
        self.test_doc = frappe.get_doc(
            {"doctype": self.test_doctype, "description": "Test import helper attachment"}
        )
        self.test_doc.insert()
        frappe.db.commit()

    def tearDown(self):
        """Clean up test fixtures"""
        # Delete attached files
        frappe.db.delete("File", {"attached_to_name": self.test_doc.name})
        # Delete test document
        frappe.delete_doc(self.test_doctype, self.test_doc.name, force=True)
        frappe.db.commit()
        super().tearDown()

    def test_persist_empty_error_log_returns_empty_string(self):
        """Empty error log should return empty string without creating file"""
        result = persist_full_error_log([], self.test_doctype, self.test_doc.name)
        self.assertEqual(result, "")

        # Verify no file was created
        files = frappe.get_all(
            "File", filters={"attached_to_name": self.test_doc.name}, fields=["name"]
        )
        self.assertEqual(len(files), 0)

    def test_persist_creates_file_attachment(self):
        """Should create a file attachment with error log content"""
        error_log = ["Error 1: Something went wrong", "Error 2: Another issue"]

        filename = persist_full_error_log(error_log, self.test_doctype, self.test_doc.name)

        # Verify filename returned
        self.assertTrue(filename.startswith("import_errors_"))
        self.assertTrue(filename.endswith(".txt"))

        # Verify file was created
        files = frappe.get_all(
            "File",
            filters={"attached_to_name": self.test_doc.name, "file_name": filename},
            fields=["name", "is_private"],
        )
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].is_private, 1)

    def test_persist_filename_has_unique_suffix(self):
        """Filename should include random suffix for uniqueness"""
        error_log = ["Error 1"]

        filename1 = persist_full_error_log(error_log, self.test_doctype, self.test_doc.name)
        filename2 = persist_full_error_log(error_log, self.test_doctype, self.test_doc.name)

        # Filenames should be different due to unique suffix
        self.assertNotEqual(filename1, filename2)

    def test_persist_truncates_at_max_lines(self):
        """Should truncate error log at max_lines limit"""
        # Create error log with more than custom max_lines
        max_lines = 10
        error_log = [f"Error {i}" for i in range(20)]

        filename = persist_full_error_log(
            error_log, self.test_doctype, self.test_doc.name, max_lines=max_lines
        )

        # Read the file content
        file_doc = frappe.get_doc("File", {"file_name": filename})
        content = file_doc.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        # Should contain truncation note
        self.assertIn("truncated 10 additional errors", content)
        self.assertIn(f"cap: {max_lines} lines", content)

    def test_persist_truncates_at_max_size(self):
        """Should truncate content at max_size limit"""
        # Create a large error log
        large_error = "X" * 1000  # 1KB per error
        error_log = [large_error for _ in range(100)]  # 100KB total

        # Use small max_size for testing
        max_size = 5000  # 5KB

        filename = persist_full_error_log(
            error_log, self.test_doctype, self.test_doc.name, max_size=max_size
        )

        # Read the file content
        file_doc = frappe.get_doc("File", {"file_name": filename})
        content = file_doc.get_content()
        if isinstance(content, str):
            content = content.encode("utf-8")

        # File should be at or under max_size
        self.assertLessEqual(len(content), max_size + 100)  # Allow small buffer for truncation message

    def test_persist_file_is_private(self):
        """Persisted file should be marked as private"""
        error_log = ["Error 1"]

        filename = persist_full_error_log(error_log, self.test_doctype, self.test_doc.name)

        file_doc = frappe.get_doc("File", {"file_name": filename})
        self.assertEqual(file_doc.is_private, 1)


class TestTruncateErrorLogForDisplay(unittest.TestCase):
    """Test truncate_error_log_for_display function"""

    def test_empty_error_log_returns_empty_string(self):
        """Empty error log should return empty string"""
        result = truncate_error_log_for_display([])
        self.assertEqual(result, "")

    def test_small_error_log_returns_all(self):
        """Error log under max_lines should return all entries"""
        error_log = ["Error 1", "Error 2", "Error 3"]
        result = truncate_error_log_for_display(error_log, max_lines=10)

        self.assertIn("Error 1", result)
        self.assertIn("Error 2", result)
        self.assertIn("Error 3", result)
        self.assertNotIn("... and", result)

    def test_large_error_log_truncates(self):
        """Error log over max_lines should be truncated with message"""
        error_log = [f"Error {i}" for i in range(20)]
        result = truncate_error_log_for_display(error_log, max_lines=10)

        # Should contain first 10 errors
        for i in range(10):
            self.assertIn(f"Error {i}", result)

        # Should not contain errors beyond max_lines
        self.assertNotIn("Error 10", result)
        self.assertNotIn("Error 19", result)

        # Should have truncation message
        self.assertIn("... and 10 more errors", result)

    def test_truncation_message_includes_filename(self):
        """Truncation message should reference attachment filename if provided"""
        error_log = [f"Error {i}" for i in range(20)]
        filename = "import_errors_20260129_120000_abc123.txt"

        result = truncate_error_log_for_display(error_log, max_lines=10, full_log_filename=filename)

        self.assertIn(f"see attached {filename}", result)

    def test_truncation_message_without_filename(self):
        """Truncation message should work without filename"""
        error_log = [f"Error {i}" for i in range(20)]

        result = truncate_error_log_for_display(error_log, max_lines=10, full_log_filename="")

        self.assertIn("... and 10 more errors", result)
        self.assertNotIn("see attached", result)


if __name__ == "__main__":
    unittest.main()
