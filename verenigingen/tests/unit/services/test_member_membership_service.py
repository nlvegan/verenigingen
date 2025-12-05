# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe
from verenigingen.services.member.core.member_membership_service import MemberMembershipService


class TestMemberMembershipService(unittest.TestCase):
    def setUp(self):
        self.service = MemberMembershipService()

    @patch("verenigingen.services.member.core.member_membership_service.get_active_membership_for_member")
    @patch("frappe.get_doc")
    def test_get_active_membership_found(self, mock_get_doc, mock_get_active):
        # Setup
        member_name = "MEM-001"
        membership_name = "MEM-SHIP-001"
        mock_get_active.return_value = {"name": membership_name}
        
        mock_doc = MagicMock()
        mock_doc.name = membership_name
        mock_get_doc.return_value = mock_doc

        # Execute
        result = self.service.get_active_membership(member_name)

        # Verify
        self.assertEqual(result, mock_doc)
        mock_get_active.assert_called_once()
        mock_get_doc.assert_called_with("Membership", membership_name)

    @patch("verenigingen.services.member.core.member_membership_service.get_active_membership_for_member")
    def test_get_active_membership_not_found(self, mock_get_active):
        # Setup
        member_name = "MEM-001"
        mock_get_active.return_value = None

        # Execute
        result = self.service.get_active_membership(member_name)

        # Verify
        self.assertIsNone(result)
        mock_get_active.assert_called_once()

    @patch("verenigingen.services.member.core.member_membership_service.get_active_membership_for_member")
    @patch("frappe.get_doc")
    def test_get_active_membership_error(self, mock_get_doc, mock_get_active):
        # Setup
        member_name = "MEM-001"
        membership_name = "MEM-SHIP-001"
        mock_get_active.return_value = {"name": membership_name}
        mock_get_doc.side_effect = Exception("Database error")

        # Execute
        result = self.service.get_active_membership(member_name)

        # Verify
        self.assertIsNone(result)
        # Should log error but return None, handled by service

    def test_get_active_membership_for_member_doc(self):
        # Setup
        mock_member_doc = MagicMock()
        mock_member_doc.name = "MEM-001"
        
        # Patch the instance method
        with patch.object(self.service, 'get_active_membership') as mock_get_active:
            mock_return = MagicMock()
            mock_get_active.return_value = mock_return

            # Execute
            result = self.service.get_active_membership_for_member_doc(mock_member_doc)

            # Verify
            self.assertEqual(result, mock_return)
            mock_get_active.assert_called_with("MEM-001")
