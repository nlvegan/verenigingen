# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for MemberCleanupService - Focus on cascade deletion logic

Tests verify that all related records are properly cleaned up when a Member
is deleted, including smart Customer handling and Address unlinking.
"""

import unittest
from unittest.mock import Mock, patch, call

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.lifecycle.member_cleanup_service import (
    MemberCleanupService,
)


class TestMemberCleanupService(FrappeTestCase):
    """Test suite for MemberCleanupService"""

    def test_membership_deletion_cancels_submitted(self):
        """Test that submitted Memberships are cancelled before deletion"""
        member_doc = Mock()
        member_doc.name = "Test-Member-001"
        member_doc.customer = None
        member_doc.primary_address = None

        # Mock submitted membership
        submitted_membership = Mock()
        submitted_membership.docstatus = 1  # Submitted
        submitted_membership.cancel = Mock()

        with patch("frappe.get_all", return_value=["Membership-001"]):
            with patch("frappe.get_doc", return_value=submitted_membership):
                with patch("frappe.delete_doc") as mock_delete:
                    with patch("frappe.logger") as mock_logger:
                        with patch("frappe.db.sql"):
                            with patch("frappe.db.table_exists", return_value=False):
                                MemberCleanupService.handle_member_deletion(member_doc)

        # Verify submitted membership was cancelled
        submitted_membership.cancel.assert_called_once()
        # Verify membership was deleted
        mock_delete.assert_any_call("Membership", "Membership-001", force=True)

    def test_dues_schedule_deletion(self):
        """Test that Membership Dues Schedules are force deleted"""
        member_doc = Mock()
        member_doc.name = "Test-Member-002"
        member_doc.customer = None
        member_doc.primary_address = None

        def mock_get_all(doctype, filters, pluck):
            if doctype == "Membership Dues Schedule":
                return ["Schedule-001", "Schedule-002"]
            return []

        with patch("frappe.get_all", side_effect=mock_get_all):
            with patch("frappe.delete_doc") as mock_delete:
                with patch("frappe.logger"):
                    with patch("frappe.db.sql"):
                        with patch("frappe.db.table_exists", return_value=False):
                            MemberCleanupService.handle_member_deletion(member_doc)

        # Verify both schedules were deleted
        mock_delete.assert_any_call("Membership Dues Schedule", "Schedule-001", force=True)
        mock_delete.assert_any_call("Membership Dues Schedule", "Schedule-002", force=True)

    def test_sales_invoice_reference_clearing(self):
        """Test that Sales Invoice member references are cleared (not deleted)"""
        member_doc = Mock()
        member_doc.name = "Test-Member-003"
        member_doc.customer = None
        member_doc.primary_address = None

        with patch("frappe.get_all", return_value=[]):
            with patch("frappe.db.sql") as mock_sql:
                with patch("frappe.logger"):
                    with patch("frappe.db.table_exists", return_value=False):
                        MemberCleanupService.handle_member_deletion(member_doc)

        # Verify SQL update was called to clear references
        sql_calls = [call for call in mock_sql.call_args_list if "UPDATE" in str(call)]
        self.assertTrue(len(sql_calls) > 0, "Should update Sales Invoices")

    def test_customer_preserved_if_has_transactions(self):
        """Test that Customer is preserved when it has transactions"""
        member_doc = Mock()
        member_doc.name = "Test-Member-004"
        member_doc.customer = "Customer-001"
        member_doc.primary_address = None

        with patch("frappe.get_all", return_value=[]):
            with patch("frappe.db.count", return_value=5):  # Has transactions
                with patch("frappe.db.sql"):
                    with patch("frappe.logger") as mock_logger:
                        with patch("frappe.db.table_exists", return_value=False):
                            with patch.object(
                                MemberCleanupService, "_unlink_member_from_customer"
                            ) as mock_unlink:
                                MemberCleanupService.handle_member_deletion(member_doc)

        # Verify customer was unlinked, not deleted
        mock_unlink.assert_called_once_with(member_doc)
        # Verify logged that customer was preserved
        self.assertTrue(mock_logger.return_value.info.called)

    def test_customer_deleted_if_no_transactions(self):
        """Test that Customer is deleted when it has no transactions"""
        member_doc = Mock()
        member_doc.name = "Test-Member-005"
        member_doc.customer = "Customer-002"
        member_doc.primary_address = None

        with patch("frappe.get_all", return_value=[]):
            with patch("frappe.db.count", return_value=0):  # No transactions
                with patch("frappe.delete_doc") as mock_delete:
                    with patch("frappe.db.sql"):
                        with patch("frappe.logger"):
                            with patch("frappe.db.table_exists", return_value=False):
                                MemberCleanupService.handle_member_deletion(member_doc)

        # Verify customer was deleted
        mock_delete.assert_any_call("Customer", "Customer-002", force=True)

    def test_address_unlinking(self):
        """Test that Address is unlinked but not deleted"""
        member_doc = Mock()
        member_doc.name = "Test-Member-006"
        member_doc.customer = None
        member_doc.primary_address = "Address-001"

        with patch("frappe.get_all", return_value=[]):
            with patch("frappe.db.sql"):
                with patch("frappe.logger"):
                    with patch("frappe.db.table_exists", return_value=False):
                        with patch.object(
                            MemberCleanupService, "_unlink_member_from_address"
                        ) as mock_unlink:
                            MemberCleanupService.handle_member_deletion(member_doc)

        # Verify address was unlinked, not deleted
        mock_unlink.assert_called_once_with(member_doc, "Address-001")

    def test_child_table_cleanup(self):
        """Test that child tables are cleaned up via SQL"""
        member_doc = Mock()
        member_doc.name = "Test-Member-007"
        member_doc.customer = None
        member_doc.primary_address = None

        with patch("frappe.get_all", return_value=[]):
            with patch("frappe.db.sql") as mock_sql:
                with patch("frappe.logger"):
                    with patch("frappe.db.table_exists", return_value=True):
                        MemberCleanupService.handle_member_deletion(member_doc)

        # Verify child table deletion SQL was called for multiple tables
        delete_calls = [
            call for call in mock_sql.call_args_list
            if "DELETE FROM" in str(call) and "WHERE parent = " in str(call)
        ]
        # Should have multiple child table deletion calls
        self.assertGreater(len(delete_calls), 3, "Should clean up multiple child tables")

    def test_unlink_from_customer_removes_links(self):
        """Test that _unlink_member_from_customer removes Dynamic Links"""
        member_doc = Mock()
        member_doc.name = "Test-Member-008"
        member_doc.customer = "Customer-003"

        # Mock customer with dynamic links
        customer_doc = Mock()
        link1 = Mock(link_doctype="Member", link_name="Test-Member-008")
        link2 = Mock(link_doctype="Other", link_name="Other-001")
        customer_doc.get = Mock(return_value=[link1, link2])
        customer_doc.remove = Mock()
        customer_doc.save = Mock()

        with patch("frappe.get_doc", return_value=customer_doc):
            MemberCleanupService._unlink_member_from_customer(member_doc)

        # Verify link1 was removed (matches Member)
        customer_doc.remove.assert_called_once_with(link1)
        # Verify customer was saved
        customer_doc.save.assert_called_once_with(ignore_permissions=True)

    def test_unlink_from_address_removes_links(self):
        """Test that _unlink_member_from_address removes links"""
        member_doc = Mock()
        member_doc.name = "Test-Member-009"

        # Mock address with links
        address_doc = Mock()
        link1 = Mock(link_doctype="Member", link_name="Test-Member-009")
        link2 = Mock(link_doctype="Other", link_name="Other-002")
        address_doc.get = Mock(return_value=[link1, link2])
        address_doc.remove = Mock()
        address_doc.save = Mock()

        with patch("frappe.get_doc", return_value=address_doc):
            MemberCleanupService._unlink_member_from_address(member_doc, "Address-002")

        # Verify link1 was removed (matches Member)
        address_doc.remove.assert_called_once_with(link1)
        # Verify address was saved
        address_doc.save.assert_called_once_with(ignore_permissions=True)

    def test_error_handling_in_deletion_loops(self):
        """Test that errors during deletion are logged but don't stop cleanup"""
        member_doc = Mock()
        member_doc.name = "Test-Member-010"
        member_doc.customer = None
        member_doc.primary_address = None

        # Mock membership that will fail to delete
        failing_membership = Mock()
        failing_membership.docstatus = 0  # Draft

        def mock_delete_doc(doctype, name, force=False):
            if doctype == "Membership":
                raise Exception("Delete failed")

        with patch("frappe.get_all", return_value=["Membership-001"]):
            with patch("frappe.get_doc", return_value=failing_membership):
                with patch("frappe.delete_doc", side_effect=mock_delete_doc):
                    with patch("frappe.logger") as mock_logger:
                        with patch("frappe.db.sql"):
                            with patch("frappe.db.table_exists", return_value=False):
                                # Should not raise, logs error and continues
                                MemberCleanupService.handle_member_deletion(member_doc)

        # Verify error was logged
        self.assertTrue(mock_logger.return_value.error.called)


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
