# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberBeforeSaveService

Tests the member before-save orchestration service to ensure:
- All operations are executed in order
- Performance optimization is applied
- ID generation works correctly
- Chapter display updates when needed
- Address fields are updated
- Counter reset flag is cleared
- Application status defaults are set
- Errors in one operation don't block others

Extracted from Member.before_save() method.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMemberBeforeSaveServiceExecute(unittest.TestCase):
    """Test execute_before_save() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    def test_executes_all_operations(self):
        """Test that all operations are executed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = "M-001"
        mock_member._should_update_chapter_display.return_value = False
        mock_member.reset_counter_to = None

        with patch.object(self.service, "_apply_performance_optimization", return_value={"success": True}):
            with patch.object(self.service, "_set_application_status_defaults", return_value={"success": True}):
                result = self.service.execute_before_save(mock_member)

        # All operations should be in the result. execute_before_save returns an
        # OperationResult whose .data holds the per-operation results dict.
        operations = result.data
        self.assertIn("optimization", operations)
        self.assertIn("id_generation", operations)
        self.assertIn("chapter_display", operations)
        self.assertIn("address_fields", operations)
        self.assertIn("counter_reset", operations)
        self.assertIn("status_defaults", operations)

    def test_collects_errors(self):
        """Test that errors are collected from failed operations"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = "M-001"
        mock_member._should_update_chapter_display.return_value = True
        mock_member.update_current_chapter_display.side_effect = Exception("Chapter error")
        mock_member.reset_counter_to = None

        with patch.object(self.service, "_apply_performance_optimization", return_value={"success": True}):
            with patch.object(self.service, "_set_application_status_defaults", return_value={"success": True}):
                with patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe"):
                    result = self.service.execute_before_save(mock_member)

        self.assertFalse(result.success)
        self.assertTrue(len(result.errors) > 0)


class TestMemberBeforeSaveServiceOptimization(unittest.TestCase):
    """Test _apply_performance_optimization() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    @patch("verenigingen.utils.safe_member_optimizer.safe_member_optimizer")
    def test_applies_optimization(self, mock_optimizer, mock_frappe):
        """Test that optimization is applied"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        result = self.service._apply_performance_optimization(mock_member)

        self.assertTrue(result["success"])
        mock_optimizer.optimize_member_creation.assert_called_once_with(mock_member)

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    @patch("verenigingen.utils.safe_member_optimizer.safe_member_optimizer")
    def test_logs_error_but_continues(self, mock_optimizer, mock_frappe):
        """Test that optimization errors are logged but don't block"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_optimizer.optimize_member_creation.side_effect = Exception("Optimization failed")

        result = self.service._apply_performance_optimization(mock_member)

        self.assertFalse(result["success"])
        self.assertTrue(result["non_blocking"])
        mock_frappe.log_error.assert_called_once()


class TestMemberBeforeSaveServiceIdGeneration(unittest.TestCase):
    """Test _handle_id_generation() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    def test_skips_when_member_id_exists(self, mock_frappe):
        """Test that ID generation is skipped when member already has ID"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = "M-12345"

        result = self.service._handle_id_generation(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "already_has_member_id")

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    @patch("verenigingen.services.member.core.member_id_service.generate_member_id")
    def test_generates_member_id_when_should_have(self, mock_generate, mock_frappe):
        """Test that member ID is generated when should_have_member_id returns True"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = None
        mock_member.should_have_member_id.return_value = True
        mock_member.is_application_member.return_value = False
        mock_generate.return_value = "M-99999"

        result = self.service._handle_id_generation(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "generated_member_id")
        self.assertEqual(result["id_generated"], "M-99999")
        self.assertEqual(mock_member.member_id, "M-99999")

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    @patch("verenigingen.services.member.core.member_id_service.generate_application_id")
    def test_generates_application_id_for_applications(self, mock_generate, mock_frappe):
        """Test that application ID is generated for application members"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = None
        mock_member.application_id = None
        mock_member.should_have_member_id.return_value = False
        mock_member.is_application_member.return_value = True
        mock_generate.return_value = "APP-12345"

        result = self.service._handle_id_generation(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "generated_application_id")
        self.assertEqual(result["id_generated"], "APP-12345")

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    def test_no_id_generated_when_not_needed(self, mock_frappe):
        """Test that no ID is generated when not needed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.member_id = None
        mock_member.should_have_member_id.return_value = False
        mock_member.is_application_member.return_value = False

        result = self.service._handle_id_generation(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_id_needed")


class TestMemberBeforeSaveServiceChapterDisplay(unittest.TestCase):
    """Test _update_chapter_display_if_needed() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    def test_updates_when_needed(self):
        """Test that chapter display is updated when needed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._should_update_chapter_display.return_value = True

        result = self.service._update_chapter_display_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["updated"])
        mock_member.update_current_chapter_display.assert_called_once()

    def test_skips_when_not_needed(self):
        """Test that chapter display is skipped when not needed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._should_update_chapter_display.return_value = False

        result = self.service._update_chapter_display_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["updated"])
        mock_member.update_current_chapter_display.assert_not_called()


class TestMemberBeforeSaveServiceAddressFields(unittest.TestCase):
    """Test _update_address_fields() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    def test_updates_address_fields(self):
        """Test that address fields are updated"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        result = self.service._update_address_fields(mock_member)

        self.assertTrue(result["success"])
        mock_member._update_computed_address_fields.assert_called_once()

    @patch("verenigingen.services.member.lifecycle.member_before_save_service.frappe")
    def test_logs_error_on_failure(self, mock_frappe):
        """Test that errors are logged on failure"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._update_computed_address_fields.side_effect = Exception("Address error")

        result = self.service._update_address_fields(mock_member)

        self.assertFalse(result["success"])
        mock_frappe.log_error.assert_called_once()


class TestMemberBeforeSaveServiceCounterReset(unittest.TestCase):
    """Test _clear_counter_reset_flag() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    def test_clears_flag_when_set(self):
        """Test that counter reset flag is cleared when set"""
        mock_member = MagicMock()
        mock_member.reset_counter_to = 100

        result = self.service._clear_counter_reset_flag(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["cleared"])
        self.assertIsNone(mock_member.reset_counter_to)

    def test_no_action_when_flag_not_set(self):
        """Test that no action when flag is not set"""
        mock_member = MagicMock()
        mock_member.reset_counter_to = None

        result = self.service._clear_counter_reset_flag(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["cleared"])


class TestMemberBeforeSaveServiceStatusDefaults(unittest.TestCase):
    """Test _set_application_status_defaults() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )
        self.service = get_member_before_save_service()

    @patch("verenigingen.services.member.core.member_status_service.set_member_application_status_defaults")
    def test_sets_status_defaults(self, mock_set_defaults):
        """Test that status defaults are set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        result = self.service._set_application_status_defaults(mock_member)

        self.assertTrue(result["success"])
        mock_set_defaults.assert_called_once_with(mock_member)


if __name__ == "__main__":
    unittest.main()
