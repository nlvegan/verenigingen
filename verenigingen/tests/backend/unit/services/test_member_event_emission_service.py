# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberEventEmissionService

Tests the member event emission service to ensure:
- Events are skipped during bulk operations, imports, and tests
- Application status change events are emitted correctly
- Membership status change events are emitted correctly
- Notifications are sent for membership status changes
- Errors don't block member updates

Extracted from Member.on_update() method.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe


class TestMemberEventEmissionServiceSkipCheck(unittest.TestCase):
    """Test should_skip_event_emission() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )
        self.service = get_member_event_emission_service()

    def test_skip_when_bulk_operations_flag_set(self):
        """Test that events are skipped when bulk_member_operations flag is set"""
        original_flag = getattr(frappe.flags, "bulk_member_operations", None)
        frappe.flags.bulk_member_operations = True

        try:
            result = self.service.should_skip_event_emission()
            self.assertTrue(result)
        finally:
            if original_flag is None:
                try:
                    delattr(frappe.flags, "bulk_member_operations")
                except (KeyError, AttributeError):
                    pass
            else:
                frappe.flags.bulk_member_operations = original_flag

    def test_skip_when_bulk_import_flag_set(self):
        """Test that events are skipped when in_bulk_import flag is set"""
        original_flag = getattr(frappe.flags, "in_bulk_import", None)
        frappe.flags.in_bulk_import = True

        try:
            result = self.service.should_skip_event_emission()
            self.assertTrue(result)
        finally:
            if original_flag is None:
                try:
                    delattr(frappe.flags, "in_bulk_import")
                except (KeyError, AttributeError):
                    pass
            else:
                frappe.flags.in_bulk_import = original_flag

    def test_skip_when_in_test_flag_set(self):
        """Test that events are skipped when in_test flag is set"""
        # Note: in_test is usually True during tests, so this verifies the behavior
        original_flag = getattr(frappe.flags, "in_test", None)
        frappe.flags.in_test = True

        try:
            result = self.service.should_skip_event_emission()
            self.assertTrue(result)
        finally:
            if original_flag is not None:
                frappe.flags.in_test = original_flag


class TestMemberEventEmissionServiceEmitEvents(unittest.TestCase):
    """Test emit_status_change_events() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )
        self.service = get_member_event_emission_service()

    def test_skips_when_should_skip(self):
        """Test that events are skipped when skip flag is set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        original_flag = getattr(frappe.flags, "in_test", None)
        frappe.flags.in_test = True

        try:
            result = self.service.emit_status_change_events(mock_member)
            self.assertTrue(result["skipped"])
            self.assertFalse(result["application_status_event"])
            self.assertFalse(result["membership_status_event"])
        finally:
            if original_flag is not None:
                frappe.flags.in_test = original_flag

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    def test_emits_application_status_event(self, mock_frappe):
        """Test that application status change event is emitted"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.has_value_changed.side_effect = lambda x: x == "application_status"
        mock_member.get_db_value.return_value = "Pending"
        mock_member.application_status = "Approved"

        # Clear the skip flags
        mock_frappe.flags = MagicMock()
        mock_frappe.flags.bulk_member_operations = False
        mock_frappe.flags.in_bulk_import = False
        mock_frappe.flags.in_test = False

        with patch.object(self.service, "should_skip_event_emission", return_value=False):
            with patch("verenigingen.events.member_events.emit_member_status_changed") as mock_emit:
                result = self.service.emit_status_change_events(mock_member)

                self.assertTrue(result["application_status_event"])
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                self.assertEqual(call_args[0][0], "MEM-001")
                self.assertEqual(call_args[0][1]["status_type"], "application")

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    def test_emits_membership_status_event(self, mock_frappe):
        """Test that membership status change event is emitted"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.has_value_changed.side_effect = lambda x: x == "status"
        mock_member.get_db_value.return_value = "Pending"
        mock_member.status = "Active"

        mock_frappe.flags = MagicMock()
        mock_frappe.flags.bulk_member_operations = False
        mock_frappe.flags.in_bulk_import = False
        mock_frappe.flags.in_test = False

        with patch.object(self.service, "should_skip_event_emission", return_value=False):
            with patch("verenigingen.events.member_events.emit_member_lifecycle_changed") as mock_emit:
                result = self.service.emit_status_change_events(mock_member)

                self.assertTrue(result["membership_status_event"])
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                self.assertEqual(call_args[0][0], "MEM-001")
                self.assertEqual(call_args[0][1]["status_type"], "membership")

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    def test_sends_notification_on_membership_status_change(self, mock_frappe):
        """Test that notification is sent on membership status change"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.has_value_changed.side_effect = lambda x: x == "status"
        mock_member.get_db_value.return_value = "Pending"
        mock_member.status = "Active"

        mock_frappe.flags = MagicMock()
        mock_frappe.flags.bulk_member_operations = False
        mock_frappe.flags.in_bulk_import = False
        mock_frappe.flags.in_test = False

        with patch.object(self.service, "should_skip_event_emission", return_value=False):
            with patch("verenigingen.events.member_events.emit_member_lifecycle_changed"):
                result = self.service.emit_status_change_events(mock_member)

                self.assertTrue(result["notification_sent"])
                mock_member._send_member_status_notification.assert_called_once_with(
                    "Pending", "Active"
                )

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    def test_no_events_when_no_status_changes(self, mock_frappe):
        """Test that no events are emitted when status hasn't changed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.has_value_changed.return_value = False

        mock_frappe.flags = MagicMock()
        mock_frappe.flags.bulk_member_operations = False
        mock_frappe.flags.in_bulk_import = False
        mock_frappe.flags.in_test = False

        with patch.object(self.service, "should_skip_event_emission", return_value=False):
            result = self.service.emit_status_change_events(mock_member)

            self.assertFalse(result["skipped"])
            self.assertFalse(result["application_status_event"])
            self.assertFalse(result["membership_status_event"])
            self.assertFalse(result["notification_sent"])


class TestMemberEventEmissionServiceErrorHandling(unittest.TestCase):
    """Test error handling in event emission"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )
        self.service = get_member_event_emission_service()

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    def test_errors_logged_not_raised(self, mock_frappe):
        """Test that errors are logged but don't block member updates"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.has_value_changed.side_effect = Exception("Test error")

        mock_frappe.flags = MagicMock()
        mock_frappe.flags.bulk_member_operations = False
        mock_frappe.flags.in_bulk_import = False
        mock_frappe.flags.in_test = False

        with patch.object(self.service, "should_skip_event_emission", return_value=False):
            # Should not raise
            result = self.service.emit_status_change_events(mock_member)

            self.assertIn("Test error", result["errors"][0])
            mock_frappe.log_error.assert_called_once()


class TestMemberEventEmissionServiceApplicationStatus(unittest.TestCase):
    """Test _emit_application_status_event() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )
        self.service = get_member_event_emission_service()

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    @patch("verenigingen.events.member_events.emit_member_status_changed")
    def test_emits_correct_event_data(self, mock_emit, mock_frappe):
        """Test that correct event data is emitted"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.get_db_value.return_value = "Pending"
        mock_member.application_status = "Under Review"

        self.service._emit_application_status_event(mock_member)

        mock_emit.assert_called_once_with(
            "MEM-001",
            {"old_status": "Pending", "new_status": "Under Review", "status_type": "application"},
        )


class TestMemberEventEmissionServiceMembershipStatus(unittest.TestCase):
    """Test _emit_membership_status_event() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )
        self.service = get_member_event_emission_service()

    @patch("verenigingen.services.member.lifecycle.member_event_emission_service.frappe")
    @patch("verenigingen.events.member_events.emit_member_lifecycle_changed")
    def test_emits_correct_event_data(self, mock_emit, mock_frappe):
        """Test that correct event data is emitted"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.get_db_value.return_value = "Active"
        mock_member.status = "Suspended"

        self.service._emit_membership_status_event(mock_member)

        mock_emit.assert_called_once_with(
            "MEM-001",
            {"old_status": "Active", "new_status": "Suspended", "status_type": "membership"},
        )


if __name__ == "__main__":
    unittest.main()
