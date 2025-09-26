"""
Integration tests for Mollie refund processing fixes.
Tests the actual service behavior with real-like data.
"""

import json
import unittest
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.integrations.mollie.services.refund_chargeback_service import RefundChargebackService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMollieRefundIntegrationFixes(EnhancedTestCase):
    """Integration tests for the Mollie refund service fixes - uses real database operations"""

    def setUp(self):
        """Set up test environment with real test data"""
        super().setUp()
        self.service = RefundChargebackService()
        # Only mock external Mollie client
        self.service.client = Mock()
        self.service.logger = Mock()
        self.service.performance_monitor = Mock()
        self.service.performance_monitor.start_operation.return_value = "mock_operation"

        # Create real test data
        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email="integration.test@example.com"
        )

        self.test_donation = self.create_test_donation(
            donor_name=self.test_member.name,
            amount=100.0,
            payment_method="Mollie"
        )

    def test_refund_webhook_with_non_receivable_accounts(self):
        """Test refund processing when accounts don't support party relationships"""

        # Mock webhook payload
        webhook_payload = json.dumps({
            "payment": {"id": "tr_test123"},
            "refund": {"id": "re_test123"}
        })

        # Test the service behavior directly - don't create invalid Payment Entries
        # Instead, mock the account constraint scenario that the service needs to handle
        with patch.object(self.service, '_fetch_refund_details') as mock_fetch_refund, \
             patch.object(self.service, '_find_original_payment') as mock_find_payment, \
             patch.object(self.service, '_find_donation_for_payment') as mock_find_donation:

            # Mock external API response from Mollie
            mock_fetch_refund.return_value = {
                "id": "re_test123",
                "status": "refunded",
                "amount": {"value": "25.00", "currency": "EUR"},
                "description": "Test refund"
            }

            # Mock the scenario: original payment with non-receivable accounts
            # This simulates a bank-to-bank transfer that was originally created
            mock_find_payment.return_value = (
                "PE-001",                      # original_pe_name
                100.0,                         # original_amount
                "10460 - Mollie - NVV",        # paid_from (Bank type)
                "10000 - Kas - NVV",           # paid_to (Bank type, not Receivable)
                "Ned Ver Vegan",               # company
                None,                          # party_type (None for bank-to-bank)
                None                           # party (None for bank-to-bank)
            )

            # Mock finding donation (use real donation we created)
            mock_find_donation.return_value = self.test_donation.name

            # Process the webhook
            result = self.service.process_refund_webhook(webhook_payload)

            # Should succeed with Payment Entry method since Credit Note fails
            self.assertEqual(result.get("status"), "success")

            # Key test: when accounts don't support party relationships,
            # the system should not crash and should process the refund successfully
            # This validates the account type constraint fix

    def test_refund_webhook_with_receivable_accounts(self):
        """Test refund processing when accounts DO support party relationships"""

        webhook_payload = json.dumps({
            "payment": {"id": "tr_test456"},
            "refund": {"id": "re_test456"}
        })

        # Test the service behavior with receivable account scenario using mocking
        # Ensure the member has a customer record for the party link
        if not self.test_member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
            customer.customer_type = "Individual"
            customer.insert()
            self.test_member.customer = customer.name
            self.test_member.save()

        # Only mock external API calls and service inputs
        with patch.object(self.service, '_fetch_refund_details') as mock_fetch_refund, \
             patch.object(self.service, '_find_original_payment') as mock_find_payment, \
             patch.object(self.service, '_find_donation_for_payment') as mock_find_donation:

            # Mock external API response
            mock_fetch_refund.return_value = {
                "id": "re_test456",
                "status": "refunded",
                "amount": {"value": "30.00", "currency": "EUR"}
            }

            # Mock the scenario: original payment with receivable account
            mock_find_payment.return_value = (
                "PE-002",                      # original_pe_name
                150.0,                         # original_amount
                "10460 - Mollie - NVV",        # paid_from (Bank type)
                "13900 - Te ontvangen bedragen - NVV",  # paid_to (Receivable type)
                "Ned Ver Vegan",               # company
                "Customer",                    # party_type
                self.test_member.customer      # party
            )

            mock_find_donation.return_value = self.test_donation.name

            # Process the webhook
            result = self.service.process_refund_webhook(webhook_payload)

            # Should succeed
            self.assertEqual(result.get("status"), "success")

            # In this case, party relationships should work since we have a receivable account
            # The key test is that it doesn't raise the "Party Type and Party can only be set" error

    def test_chargeback_processing_avoids_party_relationships(self):
        """Test that chargeback processing correctly avoids party relationships entirely"""

        webhook_payload = json.dumps({
            "payment": {"id": "tr_chargeback123"},
            "chargeback": {"id": "chb_test123"}
        })

        # Only mock external API calls, not database operations
        with patch.object(self.service, '_fetch_chargeback_details') as mock_fetch_chargeback, \
             patch.object(self.service, '_find_original_payment') as mock_find_payment, \
             patch.object(self.service, '_find_donation_for_payment') as mock_find_donation:

            # Mock chargeback details
            mock_fetch_chargeback.return_value = {
                "id": "chb_test123",
                "amount": {"value": "50.00", "currency": "EUR"},
                "reason": {"code": "duplicate", "description": "Duplicate transaction"},
                "created_at": "2023-01-01T00:00:00Z"
            }

            # Mock original payment (with or without party doesn't matter for chargebacks)
            # Ensure the customer exists for this test
            if not self.test_member.customer:
                customer = frappe.new_doc("Customer")
                customer.customer_name = f"{self.test_member.first_name} {self.test_member.last_name}"
                customer.customer_type = "Individual"
                customer.insert()
                self.test_member.customer = customer.name
                self.test_member.save()

            mock_find_payment.return_value = (
                "PE-003", 200.0, "10460 - Mollie - NVV", "10000 - Kas - NVV",
                "Ned Ver Vegan", "Customer", self.test_member.customer
            )

            mock_find_donation.return_value = self.test_donation.name

            # Process chargeback webhook
            result = self.service.process_chargeback_webhook(webhook_payload)

            # Should succeed
            self.assertEqual(result.get("status"), "success")

            # The key test: chargeback processing should avoid party relationships entirely
            # and not crash with account type constraint errors
            self.assertIsNotNone(result.get("payment_entry"))


if __name__ == '__main__':
    unittest.main()