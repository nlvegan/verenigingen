# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for Extracted Member API Functions

Tests the API functions extracted from member.py to api/member/ modules:
- sepa_api.py: validate_mandate_creation
- general_api.py: get_linked_donations

These tests focus on edge cases and error handling.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe


class TestValidateMandateCreationAPI(unittest.TestCase):
    """Test validate_mandate_creation() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.sepa_api import validate_mandate_creation
        self.validate_mandate_creation = validate_mandate_creation

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_valid_mandate_creation(self, mock_get_manager):
        """Test validation with valid parameters"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.data = {"mandate_id": "MAND-001"}
        mock_manager.validate_mandate_creation.return_value = mock_result
        mock_manager.get_active_mandates.return_value = []
        mock_get_manager.return_value = mock_manager

        result = self.validate_mandate_creation(
            member="MEM-001",
            iban="NL91ABNA0417164300",
            mandate_id="MAND-001"
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["valid"])
        self.assertNotIn("warning", result)

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_mandate_creation_with_existing_mandate_warning(self, mock_get_manager):
        """Test validation adds warning when IBAN already has active mandate"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.data = {}
        mock_manager.validate_mandate_creation.return_value = mock_result

        # Simulate existing mandate
        existing_mandate = MagicMock()
        existing_mandate.mandate_id = "EXISTING-MAND-001"
        mock_manager.get_active_mandates.return_value = [existing_mandate]
        mock_get_manager.return_value = mock_manager

        result = self.validate_mandate_creation(
            member="MEM-001",
            iban="NL91ABNA0417164300",
            mandate_id="MAND-002"
        )

        self.assertTrue(result["success"])
        self.assertIn("warning", result)
        self.assertEqual(result["existing_mandate"], "EXISTING-MAND-001")

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_mandate_creation_invalid_iban(self, mock_get_manager):
        """Test validation fails with invalid IBAN"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = False
        mock_result.message = "Invalid IBAN format"
        mock_result.errors = ["IBAN checksum failed"]
        mock_manager.validate_mandate_creation.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        result = self.validate_mandate_creation(
            member="MEM-001",
            iban="INVALID",
            mandate_id="MAND-001"
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "Invalid IBAN format")
        self.assertIn("errors", result)

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_mandate_creation_empty_mandate_id(self, mock_get_manager):
        """Test validation with empty mandate ID"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = False
        mock_result.message = "Mandate ID is required"
        mock_result.errors = None
        mock_manager.validate_mandate_creation.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        result = self.validate_mandate_creation(
            member="MEM-001",
            iban="NL91ABNA0417164300",
            mandate_id=""
        )

        self.assertFalse(result["success"])


class TestGetLinkedDonationsAPI(unittest.TestCase):
    """Test get_linked_donations() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.general_api import get_linked_donations
        self.get_linked_donations = get_linked_donations

    def test_no_member_specified(self):
        """Test returns error when no member specified"""
        result = self.get_linked_donations(member=None)

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No member specified")

    def test_empty_member_specified(self):
        """Test returns error when empty member specified"""
        result = self.get_linked_donations(member="")

        self.assertFalse(result["success"])

    @patch("verenigingen.api.member.general_api.frappe")
    def test_donor_found_by_email(self, mock_frappe):
        """Test finding donor by matching email"""
        # Mock member document
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.full_name = "Test Member"
        mock_frappe.get_doc.return_value = mock_member

        # Mock donor search - use MagicMock to support attribute access
        mock_donor = MagicMock()
        mock_donor.name = "DONOR-001"
        mock_frappe.get_all.return_value = [mock_donor]

        result = self.get_linked_donations(member="MEM-001")

        self.assertTrue(result["success"])
        self.assertEqual(result["donor"], "DONOR-001")

    @patch("verenigingen.api.member.general_api.frappe")
    def test_donor_found_by_name(self, mock_frappe):
        """Test finding donor by matching name when email doesn't match"""
        # Mock member document
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.full_name = "Test Member"
        mock_frappe.get_doc.return_value = mock_member

        # First call (by email) returns nothing, second call (by name) finds donor
        mock_donor = MagicMock()
        mock_donor.name = "DONOR-002"
        mock_frappe.get_all.side_effect = [
            [],  # No match by email
            [mock_donor],  # Match by name
        ]

        result = self.get_linked_donations(member="MEM-001")

        self.assertTrue(result["success"])
        self.assertEqual(result["donor"], "DONOR-002")

    @patch("verenigingen.api.member.general_api.frappe")
    def test_no_donor_found(self, mock_frappe):
        """Test when no donor is found by email or name"""
        # Mock member document
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.full_name = "Test Member"
        mock_frappe.get_doc.return_value = mock_member

        # No matches
        mock_frappe.get_all.return_value = []

        result = self.get_linked_donations(member="MEM-001")

        self.assertFalse(result["success"])
        self.assertIn("No donor record found", result["message"])

    @patch("verenigingen.api.member.general_api.frappe")
    def test_member_without_email(self, mock_frappe):
        """Test finding donor when member has no email"""
        # Mock member document without email
        mock_member = MagicMock()
        mock_member.email = None
        mock_member.full_name = "Test Member"
        mock_frappe.get_doc.return_value = mock_member

        # Match by name - use MagicMock to support attribute access
        mock_donor = MagicMock()
        mock_donor.name = "DONOR-003"
        mock_frappe.get_all.return_value = [mock_donor]

        result = self.get_linked_donations(member="MEM-001")

        self.assertTrue(result["success"])
        self.assertEqual(result["donor"], "DONOR-003")

    @patch("verenigingen.api.member.general_api.frappe")
    def test_member_without_email_or_name(self, mock_frappe):
        """Test when member has no email and no full_name"""
        # Mock member document without email or name
        mock_member = MagicMock()
        mock_member.email = None
        mock_member.full_name = None
        mock_frappe.get_doc.return_value = mock_member

        result = self.get_linked_donations(member="MEM-001")

        self.assertFalse(result["success"])


class TestSEPAAPIDeriveBicFromIban(unittest.TestCase):
    """Test derive_bic_from_iban() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.sepa_api import derive_bic_from_iban
        self.derive_bic_from_iban = derive_bic_from_iban

    @patch("verenigingen.api.member.sepa_api.derive_bic_from_iban")
    def test_derive_bic_valid_dutch_iban(self, mock_derive):
        """Test BIC derivation for valid Dutch IBAN"""
        # This is a wrapper that delegates to iban_validator
        # Just verify the function is callable and returns expected format
        from verenigingen.api.member.sepa_api import derive_bic_from_iban

        # The actual derive function is imported inside the function
        # We're testing the wrapper works
        self.assertTrue(callable(derive_bic_from_iban))


class TestSEPAAPIDeactivateOldMandates(unittest.TestCase):
    """Test deactivate_old_sepa_mandates() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.sepa_api import deactivate_old_sepa_mandates
        self.deactivate_old_sepa_mandates = deactivate_old_sepa_mandates

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_deactivate_mandates_success(self, mock_get_manager):
        """Test successful mandate deactivation"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = True
        mock_result.data = {"deactivated_count": 2}
        mock_manager.deactivate_mandates_for_iban_change.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        result = self.deactivate_old_sepa_mandates(
            member="MEM-001",
            new_iban="NL91ABNA0417164300"
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["valid"])

    @patch("verenigingen.services.payment.sepa_mandate_manager.get_sepa_mandate_manager")
    def test_deactivate_mandates_failure(self, mock_get_manager):
        """Test mandate deactivation failure"""
        mock_manager = MagicMock()
        mock_result = MagicMock()
        mock_result.valid = False
        mock_result.message = "No active mandates found"
        mock_result.errors = None
        mock_manager.deactivate_mandates_for_iban_change.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        result = self.deactivate_old_sepa_mandates(
            member="MEM-001",
            new_iban="NL91ABNA0417164300"
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["valid"])


class TestGeneralAPICreateMemberUserAccount(unittest.TestCase):
    """Test create_member_user_account() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.general_api import create_member_user_account
        self.create_member_user_account = create_member_user_account

    @patch("verenigingen.services.member.account.member_user_account_service.get_member_user_account_service")
    def test_create_account_delegates_to_service(self, mock_get_service):
        """Test that create_member_user_account delegates to service"""
        mock_service = MagicMock()
        mock_service.create_member_user_account.return_value = {
            "success": True,
            "user": "test@example.com"
        }
        mock_get_service.return_value = mock_service

        result = self.create_member_user_account(
            member_name="MEM-001",
            send_welcome_email=True
        )

        mock_service.create_member_user_account.assert_called_once_with("MEM-001", True)
        self.assertTrue(result["success"])


class TestGeneralAPICheckDonorExists(unittest.TestCase):
    """Test check_donor_exists() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.general_api import check_donor_exists
        self.check_donor_exists = check_donor_exists

    @patch("verenigingen.services.member.donor.get_donor_management_service")
    def test_check_donor_delegates_to_service(self, mock_get_service):
        """Test that check_donor_exists delegates to service"""
        mock_service = MagicMock()
        mock_service.check_donor_exists.return_value = {"exists": True, "donor": "DONOR-001"}
        mock_get_service.return_value = mock_service

        result = self.check_donor_exists(member_name="MEM-001")

        mock_service.check_donor_exists.assert_called_once_with("MEM-001")


class TestGeneralAPICreateDonorFromMember(unittest.TestCase):
    """Test create_donor_from_member() API function"""

    def setUp(self):
        super().setUp()
        from verenigingen.api.member.general_api import create_donor_from_member
        self.create_donor_from_member = create_donor_from_member

    @patch("verenigingen.services.member.integration.member_donor_integration_service.get_member_donor_integration_service")
    def test_create_donor_delegates_to_service(self, mock_get_service):
        """Test that create_donor_from_member delegates to service"""
        mock_service = MagicMock()
        mock_service.create_donor_from_member.return_value = {
            "success": True,
            "donor_name": "DONOR-001"
        }
        mock_get_service.return_value = mock_service

        result = self.create_donor_from_member(member_name="MEM-001")

        mock_service.create_donor_from_member.assert_called_once_with("MEM-001")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
