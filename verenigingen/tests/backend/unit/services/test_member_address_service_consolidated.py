# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberAddressService Consolidated Methods

Tests the consolidated error-handling methods added during member.py extraction:
- execute_address_field_update() - consolidated from _update_computed_address_fields
- get_other_members_at_address_safe() - consolidated from get_other_members_at_address

These methods wrap the existing service methods with comprehensive logging.
"""

import unittest
from unittest.mock import MagicMock, patch

from verenigingen.utils.operation_result import OperationResult


class TestMemberAddressServiceExecuteUpdate(unittest.TestCase):
    """Test execute_address_field_update() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.core.member_address_service import (
            get_member_address_service,
        )

        self.service = get_member_address_service()

    def test_execute_update_success(self):
        """Test successful address field update"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        with patch.object(
            self.service, "update_member_address_fields", return_value=OperationResult.ok("fingerprint123")
        ):
            # Should not raise
            self.service.execute_address_field_update(mock_member)

    @patch("verenigingen.services.member.core.member_address_service.frappe")
    def test_execute_update_logs_errors(self, mock_frappe):
        """Test that errors are logged when update fails"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        with patch.object(
            self.service,
            "update_member_address_fields",
            return_value=OperationResult.fail("Normalization failed", errors=["Error 1"]),
        ):
            self.service.execute_address_field_update(mock_member)

        mock_frappe.log_error.assert_called()

    @patch("verenigingen.services.member.core.member_address_service.frappe")
    def test_execute_update_handles_exception(self, mock_frappe):
        """Test that exceptions are caught and logged"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        with patch.object(
            self.service, "update_member_address_fields", side_effect=Exception("Database error")
        ):
            # Should not raise
            self.service.execute_address_field_update(mock_member)

        mock_frappe.log_error.assert_called()


class TestMemberAddressServiceGetOtherMembersSafe(unittest.TestCase):
    """Test get_other_members_at_address_safe() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.core.member_address_service import (
            get_member_address_service,
        )

        self.service = get_member_address_service()

    def test_returns_members_on_success(self):
        """Test successful retrieval of co-located members"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.primary_address = "ADDR-001"

        expected_members = [{"name": "MEM-002", "full_name": "John Doe"}]

        with patch.object(
            self.service, "get_colocated_members", return_value=OperationResult.ok(expected_members, count=1)
        ):
            result = self.service.get_other_members_at_address_safe(mock_member)

        self.assertEqual(result, expected_members)

    def test_returns_empty_list_on_failure(self):
        """Test that empty list is returned on failure"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.primary_address = "ADDR-001"

        with patch.object(
            self.service,
            "get_colocated_members",
            return_value=OperationResult.fail("Query failed", errors=["Error"]),
        ):
            result = self.service.get_other_members_at_address_safe(mock_member)

        self.assertEqual(result, [])

    @patch("verenigingen.services.member.core.member_address_service.frappe")
    def test_returns_empty_list_on_exception(self, mock_frappe):
        """Test that empty list is returned on exception"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.primary_address = "ADDR-001"

        with patch.object(self.service, "get_colocated_members", side_effect=Exception("Database error")):
            result = self.service.get_other_members_at_address_safe(mock_member)

        self.assertEqual(result, [])
        mock_frappe.log_error.assert_called()


if __name__ == "__main__":
    unittest.main()
