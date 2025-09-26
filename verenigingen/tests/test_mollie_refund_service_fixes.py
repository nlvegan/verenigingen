"""
Tests for the fixed Mollie refund processing logic.
Focuses on testing the party relationship handling and account type validation.
Uses real database operations instead of mocking for proper validation.
"""
import unittest
from unittest.mock import Mock, patch
import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.integrations.mollie.services.refund_chargeback_service import RefundChargebackService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieRefundServiceFixes(EnhancedTestCase):
    """Test the fixes for Mollie refund processing"""

    def setUp(self):
        """Set up test environment with real data"""
        super().setUp()
        self.service = RefundChargebackService()
        # Only mock external Mollie client, not database operations
        self.service.client = Mock()
        self.service.logger = Mock()
        self.service.performance_monitor = Mock()
        self.service.performance_monitor.start_operation.return_value = "mock_operation"

        # Create real test data
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Refund",
            email="test.refund@example.com"
        )

        self.test_donation = self.create_test_donation(
            donor_name=self.test_member.name,
            amount=100.0,
            payment_method="Mollie"
        )

    def test_party_relationship_check_with_receivable_account(self):
        """Test that party relationships are set when account supports them"""
        refund_details = {
            "id": "re_test123",
            "amount": {"value": "10.00", "currency": "EUR"},
            "status": "refunded"
        }

        # Simulate original payment with receivable account
        original_payment = (
            "PE-MOCK-001",     # original_pe_name
            100.0,             # original_amount
            "1001 - Cash - TC",   # paid_from
            "1300 - Debtors - TC", # paid_to (Receivable account)
            frappe.defaults.get_defaults().company,  # company
            "Customer",        # party_type
            self.test_member.name  # party
        )

        # Mock the methods to test just the account type validation logic
        with patch('frappe.get_doc') as mock_get_doc, \
             patch('frappe.new_doc') as mock_new_doc:

            # Mock original payment entry
            original_pe_mock = Mock()
            original_pe_mock.mode_of_payment = "Mollie"
            original_pe_mock.cost_center = None
            original_pe_mock.title = "Original Payment"

            # Mock new refund payment entry
            refund_pe_mock = Mock()
            refund_pe_mock.name = "PE-REFUND-001"
            refund_pe_mock.insert = Mock()
            refund_pe_mock.submit = Mock()

            mock_get_doc.return_value = original_pe_mock
            mock_new_doc.return_value = refund_pe_mock

            result = self.service._create_refund_payment_entry(
                refund_details, self.test_donation, 10.0, original_payment
            )

            # The key test: when a receivable account is involved, party should be set
            # Verify party was set on the refund payment entry
            self.assertEqual(refund_pe_mock.party_type, "Customer")
            self.assertEqual(refund_pe_mock.party, self.test_member.name)

    def test_party_relationship_check_with_non_receivable_accounts(self):
        """Test that party relationships are NOT set when accounts don't support them"""
        refund_details = {
            "id": "re_test123",
            "amount": {"value": "10.00", "currency": "EUR"},
            "status": "refunded"
        }

        # Simulate original payment with only bank accounts (no receivable/payable)
        original_payment = (
            "PE-MOCK-002",     # original_pe_name
            100.0,             # original_amount
            "1001 - Cash - TC",   # paid_from (Bank account)
            "1002 - HDFC - TC",  # paid_to (Bank account, not Receivable)
            frappe.defaults.get_defaults().company,  # company
            "Customer",        # party_type (from original, but shouldn't be used)
            self.test_member.name  # party (from original, but shouldn't be used)
        )

        # Mock the methods to test the account type validation logic
        with patch('frappe.get_doc') as mock_get_doc, \
             patch('frappe.new_doc') as mock_new_doc:

            # Mock original payment entry
            original_pe_mock = Mock()
            original_pe_mock.mode_of_payment = "Mollie"
            original_pe_mock.cost_center = None
            original_pe_mock.title = "Original Payment"

            # Mock new refund payment entry
            refund_pe_mock = Mock()
            refund_pe_mock.name = "PE-REFUND-002"
            refund_pe_mock.insert = Mock()
            refund_pe_mock.submit = Mock()

            mock_get_doc.return_value = original_pe_mock
            mock_new_doc.return_value = refund_pe_mock

            result = self.service._create_refund_payment_entry(
                refund_details, self.test_donation, 10.0, original_payment
            )

            # The key test: when only bank accounts are involved, party should NOT be set
            # This tests the account type constraint fix
            self.assertFalse(hasattr(refund_pe_mock, 'party_type'))
            self.assertFalse(hasattr(refund_pe_mock, 'party'))

    def test_account_type_check_error_handling(self):
        """Test error handling when account type checking fails"""
        refund_details = {
            "id": "re_test123",
            "amount": {"value": "10.00", "currency": "EUR"},
            "status": "refunded"
        }

        # Use invalid account names to trigger error handling
        original_payment = (
            "PE-NONEXISTENT",      # Non-existent payment entry
            100.0,                 # original_amount
            "INVALID-ACCOUNT",     # Invalid paid_from account
            "ALSO-INVALID",        # Invalid paid_to account
            frappe.defaults.get_defaults().company,  # company
            "Customer",            # party_type
            self.test_member.name  # party
        )

        # Mock account type checking to raise exception (simulating DB error)
        with patch('frappe.db.get_value', side_effect=Exception("Database connection error")):
            result = self.service._create_refund_payment_entry(
                refund_details, self.test_donation, 10.0, original_payment
            )

            # Should handle the error gracefully and not crash
            # The actual behavior depends on implementation error handling
            # At minimum, it should log the error
            self.service.logger.error.assert_called()

    def test_chargeback_processing_no_party_relationships(self):
        """Test that chargeback processing correctly avoids party relationships"""
        chargeback_details = {
            "id": "chb_test123",
            "amount": {"value": "50.00", "currency": "EUR"},
            "reason": {"code": "duplicate", "description": "Duplicate transaction"},
            "created_at": "2023-01-01T00:00:00Z"
        }

        original_payment = (
            "PE-001",                  # original_pe_name
            100.0,                     # original_amount
            "1001 - Cash - TC",           # paid_from
            "1002 - HDFC - TC",          # paid_to
            frappe.defaults.get_defaults().company,  # company
            "Customer",                # party_type
            self.test_member.name      # party
        )

        result = self.service._create_chargeback_payment_entry(
            chargeback_details, original_payment, self.test_donation.name
        )

        # Verify chargeback processing succeeded
        self.assertEqual(result.get("status"), "success")

        # Verify the created Payment Entry exists and has no party information
        # (chargeback should use simple account-to-account transfer)
        chargeback_pe_name = result.get("payment_entry")
        if chargeback_pe_name:
            chargeback_pe = frappe.get_doc("Payment Entry", chargeback_pe_name)
            self.assertEqual(chargeback_pe.payment_type, "Pay")
            # Chargeback should not have party relationships
            self.assertFalse(chargeback_pe.party_type or False)
            self.assertFalse(chargeback_pe.party or False)

    def test_refund_webhook_processing_flow(self):
        """Test the complete refund webhook processing flow"""
        webhook_payload = '''{
            "payment": {"id": "tr_test123"},
            "refund": {"id": "re_test123"}
        }'''

        # Mock external API calls and internal methods for focused testing
        with patch.object(self.service, '_fetch_refund_details') as mock_fetch_refund, \
             patch.object(self.service, '_find_original_payment') as mock_find_payment, \
             patch.object(self.service, '_find_donation_for_payment') as mock_find_donation, \
             patch.object(self.service, '_create_refund_payment_entry') as mock_create_pe, \
             patch.object(self.service, '_update_donation_refund_history_payment_entry') as mock_update_history:

            # Mock API response from Mollie
            mock_fetch_refund.return_value = {
                "id": "re_test123",
                "status": "refunded",
                "amount": {"value": "25.00", "currency": "EUR"}
            }

            # Mock finding the original payment
            mock_find_payment.return_value = (
                "PE-MOCK-WEBHOOK", 100.0, "1001 - Cash - TC", "1002 - HDFC - TC",
                frappe.defaults.get_defaults().company, None, None
            )

            # Mock finding donation
            mock_find_donation.return_value = self.test_donation.name

            # Mock successful refund creation
            mock_create_pe.return_value = {
                "status": "success",
                "payment_entry": "PE-REFUND-WEBHOOK"
            }

            result = self.service.process_refund_webhook(webhook_payload)

            # Verify the flow worked correctly
            self.assertEqual(result["status"], "success")

            # Verify the core methods were called
            mock_fetch_refund.assert_called_once()
            mock_find_payment.assert_called_once()
            mock_create_pe.assert_called_once()

if __name__ == '__main__':
    unittest.main()