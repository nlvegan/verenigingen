# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberDurationService

Tests the member duration orchestration service to ensure:
- Cumulative duration is calculated correctly
- Force update sets flags and saves properly
- Update duration uses the utility service
- Error handling works correctly
- Years calculation is accurate

Extracted from Member.calculate_cumulative_membership_duration(),
force_update_membership_duration(), and update_membership_duration() methods.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMemberDurationServiceCalculate(unittest.TestCase):
    """Test calculate_cumulative_duration() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )
        self.service = get_member_duration_service()

    @patch("verenigingen.services.member.utils.member_duration_service.format_duration_human_readable")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_calculates_duration_successfully(self, mock_calc_days, mock_format):
        """Test successful duration calculation"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_calc_days.return_value = 730  # 2 years
        mock_format.return_value = "2 years"

        result = self.service.calculate_cumulative_duration(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["total_days"], 730)
        self.assertEqual(result["duration"], "2 years")
        self.assertAlmostEqual(result["duration_years"], 730 / 365.25, places=2)
        self.assertEqual(mock_member.cumulative_membership_duration, "2 years")

    @patch("verenigingen.services.member.utils.member_duration_service.format_duration_human_readable")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_handles_zero_days(self, mock_calc_days, mock_format):
        """Test calculation with zero membership days"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_calc_days.return_value = 0
        mock_format.return_value = "Less than 1 month"

        result = self.service.calculate_cumulative_duration(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["total_days"], 0)
        self.assertEqual(result["duration_years"], 0)

    @patch("verenigingen.services.member.utils.member_duration_service.frappe")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_handles_calculation_error(self, mock_calc_days, mock_frappe):
        """Test error handling during calculation"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_calc_days.side_effect = Exception("Database error")

        result = self.service.calculate_cumulative_duration(mock_member)

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertEqual(result["duration_years"], 0)
        self.assertEqual(mock_member.cumulative_membership_duration, "Error calculating duration")
        mock_frappe.log_error.assert_called_once()


class TestMemberDurationServiceForceUpdate(unittest.TestCase):
    """Test force_update_duration() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )
        self.service = get_member_duration_service()

    @patch("verenigingen.services.member.utils.member_duration_service.format_duration_human_readable")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_force_update_sets_flags_and_saves(self, mock_calc_days, mock_format):
        """Test that force update sets appropriate flags and saves"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_calc_days.return_value = 365
        mock_format.return_value = "1 year"

        result = self.service.force_update_duration(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Membership duration updated successfully")
        # Check flags were set
        self.assertTrue(mock_member.flags.ignore_version)
        self.assertTrue(mock_member.flags.ignore_links)
        self.assertTrue(mock_member.flags.ignore_validate_update_after_submit)
        mock_member.save.assert_called_once()

    @patch("verenigingen.services.member.utils.member_duration_service.frappe")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_force_update_handles_save_error(self, mock_calc_days, mock_frappe):
        """Test error handling when save fails"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_calc_days.return_value = 365
        mock_member.save.side_effect = Exception("Save failed")

        result = self.service.force_update_duration(mock_member)

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        mock_frappe.log_error.assert_called()

    @patch("verenigingen.services.member.utils.member_duration_service.format_duration_human_readable")
    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_force_update_clears_flag_in_finally(self, mock_calc_days, mock_format):
        """Test that _force_duration_update flag is cleared after operation"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_calc_days.return_value = 365
        mock_format.return_value = "1 year"
        # Simulate the flag being set
        mock_member._force_duration_update = True

        self.service.force_update_duration(mock_member)

        # The flag should have been deleted
        # Since we used MagicMock, check that delattr was attempted
        self.assertFalse(hasattr(mock_member, "_force_duration_update") and mock_member._force_duration_update)


class TestMemberDurationServiceUpdate(unittest.TestCase):
    """Test update_duration() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )
        self.service = get_member_duration_service()

    @patch("verenigingen.services.member.utils.member_duration_service.update_member_duration_fields")
    def test_update_duration_saves_on_success(self, mock_update_fields):
        """Test that update saves document when calculation succeeds"""
        from verenigingen.utils.operation_result import OperationResult

        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        # update_member_duration_fields returns an OperationResult, so the mock
        # must mirror that contract (the service reads result.success).
        mock_update_fields.return_value = OperationResult.ok({"total_days": 365})

        result = self.service.update_duration(mock_member)

        self.assertTrue(result.success)
        self.assertTrue(mock_member.flags.ignore_version)
        mock_member.save.assert_called_once()

    @patch("verenigingen.services.member.utils.member_duration_service.update_member_duration_fields")
    def test_update_duration_skips_save_on_failure(self, mock_update_fields):
        """Test that update does not save when calculation fails"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_update_fields.return_value = {"success": False, "error": "Calculation failed"}

        result = self.service.update_duration(mock_member)

        self.assertFalse(result["success"])
        mock_member.save.assert_not_called()

    @patch("verenigingen.services.member.utils.member_duration_service.frappe")
    @patch("verenigingen.services.member.utils.member_duration_service.update_member_duration_fields")
    def test_update_duration_handles_exception(self, mock_update_fields, mock_frappe):
        """Test error handling when exception occurs"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_update_fields.side_effect = Exception("Service error")

        result = self.service.update_duration(mock_member)

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        mock_frappe.log_error.assert_called_once()


class TestMemberDurationServiceGetYears(unittest.TestCase):
    """Test get_duration_years() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )
        self.service = get_member_duration_service()

    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_get_duration_years_calculates_correctly(self, mock_calc_days):
        """Test years calculation"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_calc_days.return_value = 730  # About 2 years

        result = self.service.get_duration_years(mock_member)

        self.assertAlmostEqual(result, 730 / 365.25, places=2)

    @patch("verenigingen.services.member.utils.member_duration_service.calculate_total_membership_days")
    def test_get_duration_years_returns_zero_for_no_days(self, mock_calc_days):
        """Test zero days returns zero years"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_calc_days.return_value = 0

        result = self.service.get_duration_years(mock_member)

        self.assertEqual(result, 0)


class TestMemberDurationServiceSingleton(unittest.TestCase):
    """Test singleton pattern"""

    def test_returns_same_instance(self):
        """Test that get_member_duration_service returns the same instance"""
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )

        service1 = get_member_duration_service()
        service2 = get_member_duration_service()

        self.assertIs(service1, service2)


if __name__ == "__main__":
    unittest.main()
