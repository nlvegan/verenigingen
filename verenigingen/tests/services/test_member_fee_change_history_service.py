# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for MemberFeeChangeHistoryService - Focus on DRY improvements

Tests verify that billing frequency validation works correctly and is
properly centralized to eliminate code duplication.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.history.member_fee_change_history_service import (
    MemberFeeChangeHistoryService,
    get_member_fee_change_history_service,
)


class TestMemberFeeChangeHistoryService(FrappeTestCase):
    """Test suite for MemberFeeChangeHistoryService"""

    def test_validate_billing_frequency_valid_values(self):
        """Test that valid billing frequencies are accepted"""
        valid_frequencies = ["Daily", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]

        for freq in valid_frequencies:
            result = get_member_fee_change_history_service()._validate_billing_frequency(freq)
            self.assertEqual(
                result, freq, f"Valid frequency '{freq}' should be returned as-is"
            )

    def test_validate_billing_frequency_invalid_value(self):
        """Test that invalid billing frequencies default to Custom"""
        invalid_frequencies = ["Weekly", "Biweekly", "InvalidValue", "random_string"]

        for freq in invalid_frequencies:
            result = get_member_fee_change_history_service()._validate_billing_frequency(freq)
            self.assertEqual(
                result,
                "Custom",
                f"Invalid frequency '{freq}' should return 'Custom'",
            )

    def test_validate_billing_frequency_none(self):
        """Test that None defaults to Custom"""
        result = get_member_fee_change_history_service()._validate_billing_frequency(None)
        self.assertEqual(result, "Custom", "None should return 'Custom'")

    def test_validate_billing_frequency_empty_string(self):
        """Test that empty string defaults to Custom"""
        result = get_member_fee_change_history_service()._validate_billing_frequency("")
        self.assertEqual(result, "Custom", "Empty string should return 'Custom'")

    def test_valid_billing_frequencies_constant(self):
        """Test that class constant contains expected values"""
        expected = ["Daily", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]
        self.assertEqual(
            MemberFeeChangeHistoryService.VALID_BILLING_FREQUENCIES,
            expected,
            "VALID_BILLING_FREQUENCIES constant should match expected values",
        )

    def test_add_fee_change_uses_validation_helper(self):
        """Test that add_fee_change_to_history uses the validation helper"""
        member_doc = Mock()
        member_doc.name = "Test-Member-001"
        member_doc.fee_change_history = []

        schedule_data = {
            "name": "Schedule-001",
            "change_date": "2024-01-15",
            "dues_rate": 50.0,
            "old_dues_rate": 25.0,
            "billing_frequency": "Weekly",  # Invalid - should become "Custom"
            "change_type": "Schedule Created",
            "reason": "Test schedule",
            "changed_by": "Administrator",
        }

        # Mock append to prevent actual database operations
        member_doc.append = Mock()

        get_member_fee_change_history_service().add_fee_change_to_history(member_doc, schedule_data)

        # Verify append was called
        member_doc.append.assert_called_once()

        # Get the entry_data that was passed to append
        call_args = member_doc.append.call_args
        entry_data = call_args[0][1]  # Second argument to append()

        # Verify billing frequency was normalized to "Custom"
        self.assertEqual(
            entry_data["billing_frequency"],
            "Custom",
            "Invalid billing frequency should be normalized to Custom",
        )

    def test_add_fee_change_history_deduplication(self):
        """Test that duplicate entries are updated instead of added"""
        member_doc = Mock()
        member_doc.name = "Test-Member-002"

        # Existing history entry
        existing_entry = Mock()
        existing_entry.dues_schedule = "Schedule-001"
        existing_entry.amendment_request = None
        member_doc.fee_change_history = [existing_entry]

        schedule_data = {
            "name": "Schedule-001",  # Same as existing
            "change_date": "2024-02-01",
            "dues_rate": 75.0,
            "old_dues_rate": 50.0,
            "billing_frequency": "Monthly",
            "change_type": "Fee Adjustment",
            "reason": "Updated schedule",
            "changed_by": "Administrator",
        }

        member_doc.append = Mock()

        get_member_fee_change_history_service().add_fee_change_to_history(member_doc, schedule_data)

        # Verify append was NOT called (existing entry should be updated)
        member_doc.append.assert_not_called()

        # Verify existing entry was updated
        self.assertEqual(existing_entry.new_dues_rate, 75.0)
        self.assertEqual(existing_entry.billing_frequency, "Monthly")

    def test_add_fee_change_history_50_entry_limit(self):
        """Test that history is limited to 50 entries"""
        member_doc = Mock()
        member_doc.name = "Test-Member-003"

        # Create 50 existing entries
        existing_entries = []
        for i in range(50):
            entry = Mock()
            entry.dues_schedule = f"Schedule-{i:03d}"
            entry.amendment_request = None
            existing_entries.append(entry)

        member_doc.fee_change_history = existing_entries

        schedule_data = {
            "name": "Schedule-NEW",  # New entry
            "change_date": "2024-03-01",
            "dues_rate": 100.0,
            "old_dues_rate": 75.0,
            "billing_frequency": "Annual",
            "change_type": "Schedule Created",
            "reason": "New schedule",
            "changed_by": "Administrator",
        }

        # Mock the list to allow slicing
        member_doc.append = lambda table_name, entry_data: member_doc.fee_change_history.append(
            entry_data
        )

        get_member_fee_change_history_service().add_fee_change_to_history(member_doc, schedule_data)

        # Verify history was truncated to 50 entries
        self.assertLessEqual(
            len(member_doc.fee_change_history),
            50,
            "History should be limited to 50 entries",
        )

    def test_update_fee_change_calls_add_if_not_found(self):
        """Test that update calls add if entry not found"""
        member_doc = Mock()
        member_doc.name = "Test-Member-004"
        member_doc.fee_change_history = []

        schedule_data = {
            "name": "Schedule-NEW",
            "change_date": "2024-04-01",
            "dues_rate": 125.0,
            "billing_frequency": "Quarterly",
            "change_type": "Schedule Created",
            "reason": "New schedule",
        }

        # Mock append
        member_doc.append = Mock()

        with patch(
            "verenigingen.services.member.history.member_fee_change_history_service.MemberFeeChangeHistoryService.add_fee_change_to_history"
        ) as mock_add:
            get_member_fee_change_history_service().update_fee_change_in_history(
                member_doc, schedule_data
            )

            # Verify add was called since entry not found
            mock_add.assert_called_once_with(member_doc, schedule_data)

    def test_class_constant_immutable(self):
        """Test that VALID_BILLING_FREQUENCIES is a list (can be referenced)"""
        # Verify it's accessible and has correct type
        frequencies = MemberFeeChangeHistoryService.VALID_BILLING_FREQUENCIES
        self.assertIsInstance(frequencies, list)
        self.assertEqual(len(frequencies), 6)


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
