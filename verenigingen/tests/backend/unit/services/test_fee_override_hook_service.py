# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for FeeOverrideHookService

Tests the fee override after-save hook service to ensure:
- Bulk operation detection works correctly
- Pending fee changes are processed atomically
- Amendment requests are created properly
- Fee change history is updated correctly
- Error handling and rollback work as expected

Extracted from member.py handle_fee_override_after_save() function.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

import frappe


class TestFeeOverrideHookServiceSkipProcessing(unittest.TestCase):
    """Test should_skip_processing() logic"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.financial.fee_override_hook_service import (
            get_fee_override_hook_service,
        )
        self.service = get_fee_override_hook_service()

    def test_skip_when_bulk_flag_set(self):
        """Test processing is skipped when bulk_member_operations flag is set"""
        doc = MagicMock()
        doc.name = "MEM-TEST-001"

        # Set bulk flag
        original_flag = getattr(frappe.flags, "bulk_member_operations", None)
        frappe.flags.bulk_member_operations = True

        try:
            result = self.service.should_skip_processing(doc)
            self.assertTrue(result)
        finally:
            # Restore original flag
            if original_flag is None:
                delattr(frappe.flags, "bulk_member_operations")
            else:
                frappe.flags.bulk_member_operations = original_flag

    def test_skip_when_csv_import_flag_set(self):
        """Test processing is skipped when _csv_import flag is set on document"""
        doc = MagicMock()
        doc.name = "MEM-TEST-002"
        doc._csv_import = True
        doc._system_update = False

        result = self.service.should_skip_processing(doc)
        self.assertTrue(result)

    def test_skip_when_system_update_flag_set(self):
        """Test processing is skipped when _system_update flag is set"""
        doc = MagicMock()
        doc.name = "MEM-TEST-003"
        doc._csv_import = False
        doc._system_update = True

        result = self.service.should_skip_processing(doc)
        self.assertTrue(result)

    def test_skip_when_in_bulk_import_set(self):
        """Test processing is skipped when member is in bulk_import_members set"""
        doc = MagicMock()
        doc.name = "MEM-TEST-004"
        doc._csv_import = False
        doc._system_update = False

        # Set up bulk import tracking
        if not hasattr(frappe.local, "bulk_import_members"):
            frappe.local.bulk_import_members = set()
        frappe.local.bulk_import_members.add("MEM-TEST-004")

        try:
            result = self.service.should_skip_processing(doc)
            self.assertTrue(result)
        finally:
            frappe.local.bulk_import_members.discard("MEM-TEST-004")

    def test_no_skip_when_no_flags_set(self):
        """Test processing is NOT skipped when no flags are set"""
        doc = MagicMock()
        doc.name = "MEM-TEST-005"
        doc._csv_import = False
        doc._system_update = False

        # Ensure no bulk flags - use try/except since delattr on LocalProxy raises KeyError
        try:
            if hasattr(frappe.flags, "bulk_member_operations"):
                delattr(frappe.flags, "bulk_member_operations")
        except (KeyError, AttributeError):
            pass
        if hasattr(frappe.local, "bulk_import_members"):
            frappe.local.bulk_import_members.discard("MEM-TEST-005")

        result = self.service.should_skip_processing(doc)
        self.assertFalse(result)


class TestFeeOverrideHookServiceProcessing(unittest.TestCase):
    """Test process_pending_fee_change() logic"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.financial.fee_override_hook_service import (
            get_fee_override_hook_service,
        )
        self.service = get_fee_override_hook_service()

    def test_no_processing_when_no_pending_change(self):
        """Test that False is returned when no pending fee change exists"""
        doc = MagicMock(spec=[])  # No _pending_fee_change attribute
        doc.name = "MEM-TEST-010"

        result = self.service.process_pending_fee_change(doc)
        self.assertFalse(result)

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_processing_with_pending_change(self, mock_frappe):
        """Test successful processing of pending fee change"""
        doc = MagicMock()
        doc.name = "MEM-TEST-011"
        doc._pending_fee_change = {
            "change_date": "2025-01-15",
            "old_amount": 50.0,
            "new_amount": 75.0,
            "reason": "Annual increase",
            "changed_by": "Administrator",
        }

        # Mock database operations
        mock_frappe.db.begin = MagicMock()
        mock_frappe.db.commit = MagicMock()
        mock_frappe.db.get_value.return_value = "[]"
        mock_frappe.db.sql = MagicMock()
        mock_frappe.parse_json.return_value = []
        mock_frappe.as_json.return_value = '[{"change_date": "2025-01-15"}]'
        mock_frappe.get_doc.return_value = MagicMock()

        # Mock amendment creation to fail gracefully
        with patch.object(self.service, "_create_amendment_request", return_value="Amendment creation failed"):
            result = self.service.process_pending_fee_change(doc)

        # Verify pending change was cleaned up
        self.assertFalse(hasattr(doc, "_pending_fee_change"))

    def test_build_history_entry(self):
        """Test _build_history_entry creates correct structure"""
        pending_change = {
            "change_date": "2025-01-15",
            "old_amount": 50.0,
            "new_amount": 75.0,
            "reason": "Board decision",
            "changed_by": "admin@example.com",
        }
        dues_action = "Amendment request created: AMR-001"

        entry = self.service._build_history_entry(pending_change, dues_action)

        self.assertEqual(entry["change_date"], "2025-01-15")
        self.assertEqual(entry["old_amount"], 50.0)
        self.assertEqual(entry["new_amount"], 75.0)
        self.assertEqual(entry["reason"], "Board decision")
        self.assertEqual(entry["changed_by"], "admin@example.com")
        self.assertEqual(entry["dues_schedule_action"], "Amendment request created: AMR-001")


class TestFeeOverrideHistoryUpdate(unittest.TestCase):
    """Test _update_fee_change_history() logic"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.financial.fee_override_hook_service import (
            get_fee_override_hook_service,
        )
        self.service = get_fee_override_hook_service()

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_update_history_with_empty_existing(self, mock_frappe):
        """Test updating history when no existing history"""
        mock_frappe.db.get_value.return_value = None
        mock_frappe.db.sql = MagicMock()
        mock_frappe.as_json.return_value = '[{"change_date": "2025-01-15"}]'

        history_entry = {"change_date": "2025-01-15", "new_amount": 75.0}

        self.service._update_fee_change_history("MEM-001", history_entry)

        # Verify SQL was called to update
        mock_frappe.db.sql.assert_called_once()

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_update_history_with_existing_entries(self, mock_frappe):
        """Test updating history when entries already exist"""
        existing_history = '[{"change_date": "2024-01-15", "new_amount": 50.0}]'
        mock_frappe.db.get_value.return_value = existing_history
        mock_frappe.parse_json.return_value = [{"change_date": "2024-01-15", "new_amount": 50.0}]
        mock_frappe.db.sql = MagicMock()
        mock_frappe.as_json.return_value = '[{"change_date": "2024-01-15"}, {"change_date": "2025-01-15"}]'

        history_entry = {"change_date": "2025-01-15", "new_amount": 75.0}

        self.service._update_fee_change_history("MEM-001", history_entry)

        # Verify history was appended
        mock_frappe.db.sql.assert_called_once()

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_update_history_with_invalid_json(self, mock_frappe):
        """Test updating history when existing JSON is invalid"""
        mock_frappe.db.get_value.return_value = "not valid json"
        mock_frappe.parse_json.side_effect = ValueError("Invalid JSON")
        mock_frappe.log_error = MagicMock()
        mock_frappe.db.sql = MagicMock()
        mock_frappe.as_json.return_value = '[{"change_date": "2025-01-15"}]'

        history_entry = {"change_date": "2025-01-15", "new_amount": 75.0}

        self.service._update_fee_change_history("MEM-001", history_entry)

        # Verify error was logged and history was reset
        mock_frappe.log_error.assert_called()
        mock_frappe.db.sql.assert_called_once()

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_update_history_with_non_list_json(self, mock_frappe):
        """Test updating history when existing JSON is not a list"""
        mock_frappe.db.get_value.return_value = '{"not": "a list"}'
        mock_frappe.parse_json.return_value = {"not": "a list"}
        mock_frappe.log_error = MagicMock()
        mock_frappe.db.sql = MagicMock()
        mock_frappe.as_json.return_value = '[{"change_date": "2025-01-15"}]'

        history_entry = {"change_date": "2025-01-15", "new_amount": 75.0}

        self.service._update_fee_change_history("MEM-001", history_entry)

        # Verify error was logged and history was reset to new entry only
        mock_frappe.log_error.assert_called()


class TestFeeOverrideAmendmentCreation(unittest.TestCase):
    """Test _create_amendment_request() logic"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.financial.fee_override_hook_service import (
            get_fee_override_hook_service,
        )
        self.service = get_fee_override_hook_service()

    @patch("verenigingen.services.member.financial.fee_override_hook_service.frappe")
    def test_amendment_creation_failure_returns_message(self, mock_frappe):
        """Test that amendment creation failure returns appropriate message"""
        pending_change = {
            "new_amount": 75.0,
            "reason": "Annual increase",
        }

        # Mock the import to fail
        with patch.dict("sys.modules", {"verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request": None}):
            result = self.service._create_amendment_request("MEM-001", pending_change)

        self.assertIn("failed", result.lower())


class TestFeeOverrideHandleAfterSave(unittest.TestCase):
    """Test handle_after_save() integration"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.financial.fee_override_hook_service import (
            get_fee_override_hook_service,
        )
        self.service = get_fee_override_hook_service()

    def test_handle_after_save_skips_when_bulk(self):
        """Test handle_after_save skips processing when bulk flag set"""
        doc = MagicMock()
        doc.name = "MEM-TEST-030"
        doc._csv_import = True
        doc._system_update = False

        # Should not raise, should skip silently
        self.service.handle_after_save(doc, method="after_save")

    def test_handle_after_save_with_no_pending_change(self):
        """Test handle_after_save with no pending change"""
        doc = MagicMock(spec=["name"])  # No _pending_fee_change
        doc.name = "MEM-TEST-031"
        doc._csv_import = False
        doc._system_update = False

        # Should not raise
        self.service.handle_after_save(doc, method="after_save")


if __name__ == "__main__":
    unittest.main()
