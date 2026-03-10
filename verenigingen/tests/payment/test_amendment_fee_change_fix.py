"""
Test for the contribution amendment request fee change history fix.
Ensures that field name mapping is correct and financial history manager is used.
"""

import unittest
from unittest.mock import Mock, patch
import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen.doctype.member.member import Member


class TestAmendmentFeeChangeFix(FrappeTestCase):
    """Test the amendment fee change history fixes"""

    def test_record_fee_change_field_mapping(self):
        """Test that record_fee_change correctly maps field names"""

        # Create a mock member document
        member = frappe.new_doc("Member")
        member.name = "TEST-MEMBER-001"

        # Mock the fee change history manager
        mock_manager = Mock()
        mock_manager.add_or_update_entry.return_value = True

        with patch('verenigingen.utils.member_financial_history_manager.get_fee_change_history_manager', return_value=mock_manager):
            # Test data with amendment request name for idempotency
            change_data = {
                "change_date": "2023-01-15",
                "old_amount": 25.0,
                "new_amount": 30.0,
                "reason": "Amendment AMEND-2023-00001: Membership fee increase",
                "changed_by": "test@example.com",
                "dues_schedule_name": "DUES-001",
                "amendment_request_name": "AMEND-2023-00001"
            }

            # Call the method
            result = member.record_fee_change(change_data)

            # Verify the manager was called
            self.assertTrue(result)
            mock_manager.add_or_update_entry.assert_called_once()

            # Get the call arguments
            call_args, call_kwargs = mock_manager.add_or_update_entry.call_args

            # Verify entry_id uses amendment name for idempotency
            entry_id = call_kwargs.get("entry_id")
            self.assertEqual(entry_id, "amendment_AMEND-2023-00001")

            # Verify id_field_name is set to amendment_request for proper lookup
            self.assertEqual(call_kwargs["id_field_name"], "amendment_request")

            # Test the entry builder function
            entry_builder = call_kwargs["entry_builder"]
            entry_data = entry_builder()

            # Verify correct field mapping (this was the original bug)
            self.assertEqual(entry_data["old_dues_rate"], 25.0)  # Should be old_dues_rate, not old_amount
            self.assertEqual(entry_data["new_dues_rate"], 30.0)  # Should be new_dues_rate, not new_amount
            self.assertEqual(entry_data["change_type"], "Fee Adjustment")
            self.assertEqual(entry_data["reason"], "Amendment AMEND-2023-00001: Membership fee increase")
            self.assertEqual(entry_data["changed_by"], "test@example.com")
            self.assertEqual(entry_data["dues_schedule"], "DUES-001")
            self.assertEqual(entry_data["amendment_request"], "AMEND-2023-00001")

    def test_record_fee_change_without_amendment(self):
        """Test record_fee_change for non-amendment changes (manual, system, etc.)"""

        member = frappe.new_doc("Member")
        member.name = "TEST-MEMBER-002"

        mock_manager = Mock()
        mock_manager.add_or_update_entry.return_value = True

        with patch('verenigingen.utils.member_financial_history_manager.get_fee_change_history_manager', return_value=mock_manager):
            # Test data without amendment request name
            change_data = {
                "change_date": "2023-02-01",
                "old_amount": 20.0,
                "new_amount": 25.0,
                "reason": "Manual fee adjustment",
                "changed_by": "admin@example.com",
                "dues_schedule_action": "Manual update"
            }

            result = member.record_fee_change(change_data)

            self.assertTrue(result)

            call_args, call_kwargs = mock_manager.add_or_update_entry.call_args

            # Verify entry_id uses date-based format for non-amendment changes
            entry_id = call_kwargs.get("entry_id")
            self.assertEqual(entry_id, "2023-02-01_Manual update")

            # Verify id_field_name uses dues_schedule for non-amendment lookups
            self.assertEqual(call_kwargs["id_field_name"], "dues_schedule")

            # Test entry data
            entry_data = call_kwargs["entry_builder"]()
            self.assertEqual(entry_data["old_dues_rate"], 20.0)
            self.assertEqual(entry_data["new_dues_rate"], 25.0)
            self.assertNotIn("amendment_request", entry_data)  # Should not be set for non-amendments

    def test_fee_change_history_manager_factory(self):
        """Test that the fee change history manager factory is properly configured"""

        from verenigingen.utils.member_financial_history_manager import get_fee_change_history_manager

        mock_member = Mock()
        manager = get_fee_change_history_manager(mock_member)

        # Verify it's configured for fee change history with proper limits
        self.assertEqual(manager.member, mock_member)
        self.assertEqual(manager.history_field, "fee_change_history")
        self.assertEqual(manager.max_entries, 50)  # Fee changes get more entries than payments

    def test_idempotency_with_amendment_requests(self):
        """Test that the same amendment can be applied multiple times without duplicate entries"""

        member = frappe.new_doc("Member")
        member.name = "TEST-MEMBER-003"

        # Mock manager that returns True (no changes) for duplicate entries
        mock_manager = Mock()
        mock_manager.add_or_update_entry.return_value = True  # Idempotent - no actual changes

        with patch('verenigingen.utils.member_financial_history_manager.get_fee_change_history_manager', return_value=mock_manager):
            change_data = {
                "change_date": "2023-03-01",
                "old_amount": 30.0,
                "new_amount": 35.0,
                "reason": "Amendment AMEND-2023-00005: Rate adjustment",
                "changed_by": "system@example.com",
                "dues_schedule_name": "DUES-005",
                "amendment_request_name": "AMEND-2023-00005"
            }

            # Call multiple times (simulating repeated amendment application)
            result1 = member.record_fee_change(change_data)
            result2 = member.record_fee_change(change_data)
            result3 = member.record_fee_change(change_data)

            # All should succeed (idempotent behavior)
            self.assertTrue(result1)
            self.assertTrue(result2)
            self.assertTrue(result3)

            # Manager should be called with same entry_id each time
            self.assertEqual(mock_manager.add_or_update_entry.call_count, 3)

            # All calls should use the same amendment-based entry_id
            for call in mock_manager.add_or_update_entry.call_args_list:
                call_args, call_kwargs = call
                self.assertEqual(call_kwargs.get("entry_id"), "amendment_AMEND-2023-00005")


if __name__ == '__main__':
    unittest.main()