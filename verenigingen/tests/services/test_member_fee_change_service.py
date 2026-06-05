# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for MemberFeeChangeService - Focus on optimization and UX improvements

Tests verify:
1. DB query optimization (get_doc_before_save() usage)
2. User feedback for failures (frappe.msgprint() called)
3. CSV import bypass logic
4. Deferred processing pattern
"""

import unittest
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.core.member_fee_change_service import (
    MemberFeeChangeService,
    get_member_fee_change_service,
)


class TestMemberFeeChangeService(FrappeTestCase):
    """Test suite for MemberFeeChangeService"""

    def test_csv_import_skips_processing(self):
        """Test that CSV imports bypass fee override handling"""
        class SimpleMemberDoc:
            name = "Test-Member-001"
            _csv_import = True  # Flag set
            dues_rate = 50.0

            def is_new(self):
                return False

            def validate_fee_override_permissions(self):
                raise Exception("Should not be called")

        member_doc = SimpleMemberDoc()

        # Should return early without calling validation
        get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify no pending change created
        self.assertFalse(hasattr(member_doc, "_pending_fee_change"))

    def test_system_update_skips_processing(self):
        """Test that system updates bypass fee override handling"""
        class SimpleMemberDoc:
            name = "Test-Member-002"
            _system_update = True  # Flag set
            dues_rate = 50.0

            def is_new(self):
                return False

            def validate_fee_override_permissions(self):
                raise Exception("Should not be called")

        member_doc = SimpleMemberDoc()

        # Should return early without calling validation
        get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify no pending change created
        self.assertFalse(hasattr(member_doc, "_pending_fee_change"))

    def test_new_document_skips_change_tracking(self):
        """Test that new documents don't create pending changes"""
        class SimpleMemberDoc:
            name = None
            dues_rate = 50.0
            fee_override_reason = "Initial setup"
            fee_override_date = None
            fee_override_by = None
            _csv_import = False
            _system_update = False

            def is_new(self):
                return True

            def validate_fee_override_permissions(self):
                pass

            def _validate_fee_override_amount(self, amount):
                pass

            def _validate_fee_override_reason(self):
                pass

        member_doc = SimpleMemberDoc()

        with patch("frappe.session") as mock_session:
            mock_session.user = "Administrator"

            get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify audit fields set but no change tracking
        self.assertIsNotNone(member_doc.fee_override_date)
        self.assertIsNotNone(member_doc.fee_override_by)
        self.assertFalse(hasattr(member_doc, "_pending_fee_change"))

    def test_change_detection_creates_pending_change(self):
        """Test that actual fee changes are queued for processing"""
        class SimpleMemberDoc:
            name = "Test-Member-003"
            dues_rate = 100.0
            fee_override_reason = "Rate increase"
            _csv_import = False
            _system_update = False

            def is_new(self):
                return False

            def get_doc_before_save(self):
                return {"dues_rate": 75.0}  # Old value different from new

        member_doc = SimpleMemberDoc()

        # Mock validation service factory function to bypass permission checks in test
        mock_validation_service = Mock()
        with patch("verenigingen.services.member.core.member_fee_change_service.get_member_fee_validation_service", return_value=mock_validation_service):
            with patch("frappe.session") as mock_session:
                mock_session.user = "test@example.com"
                get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify pending change was created
        self.assertTrue(hasattr(member_doc, "_pending_fee_change"))
        self.assertEqual(member_doc._pending_fee_change["old_amount"], 75.0)
        self.assertEqual(member_doc._pending_fee_change["new_amount"], 100.0)

    def test_no_change_when_values_equal(self):
        """Test that no change is tracked when old equals new"""
        class SimpleMemberDoc:
            name = "Test-Member-004"
            dues_rate = 50.0
            _csv_import = False
            _system_update = False

            def is_new(self):
                return False

            def get_doc_before_save(self):
                return {"dues_rate": 50.0}  # Same as current

            def validate_fee_override_permissions(self):
                pass

        member_doc = SimpleMemberDoc()

        get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify no pending change (no actual change)
        self.assertFalse(hasattr(member_doc, "_pending_fee_change"))

    def test_exception_handling_notifies_user(self):
        """Test that exceptions result in user notification"""
        class SimpleMemberDoc:
            name = "Test-Member-005"
            dues_rate = 100.0
            _csv_import = False
            _system_update = False

            def is_new(self):
                return False

            def get_doc_before_save(self):
                raise Exception("Database error")

            def validate_fee_override_permissions(self):
                pass

        member_doc = SimpleMemberDoc()

        with patch("frappe.msgprint") as mock_msgprint:
            with patch("frappe._", return_value="Fee change saved but audit tracking failed. Please contact administrator."):
                get_member_fee_change_service().handle_fee_override_changes(member_doc)

        # Verify user was notified
        # (Error is logged via self.logger.error which is part of StatelessService)
        mock_msgprint.assert_called_once()

    def test_record_fee_change_uses_history_manager(self):
        """Test that record_fee_change delegates to the FeeChangeRecordingService."""
        member_doc = Mock()
        member_doc.name = "Test-Member-006"

        change_data = {
            "change_date": "2024-01-15",
            "old_amount": 50.0,
            "new_amount": 75.0,
            "reason": "Annual increase",
            "changed_by": "Administrator",
            "billing_frequency": "Monthly",
        }

        # record_fee_change now delegates to
        # FeeChangeRecordingService.record() (imported lazily inside the method).
        with patch(
            "verenigingen.services.member.financial.fee_change_recording_service"
            ".get_fee_change_recording_service"
        ) as mock_get_service:
            mock_service = Mock()
            mock_service.record = Mock(return_value={"success": True})
            mock_get_service.return_value = mock_service

            result = get_member_fee_change_service().record_fee_change(member_doc, change_data)

        # Verify the recording service was invoked with the mapped arguments.
        mock_service.record.assert_called_once()
        call_kwargs = mock_service.record.call_args.kwargs
        self.assertEqual(call_kwargs["member"], member_doc)
        self.assertEqual(call_kwargs["old_amount"], 50.0)
        self.assertEqual(call_kwargs["new_amount"], 75.0)
        self.assertEqual(call_kwargs["billing_frequency"], "Monthly")

        # Verify return value
        self.assertEqual(result, {"success": True})


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
