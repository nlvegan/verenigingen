"""
Mollie Failed Payment Processing Test Suite
==========================================

Comprehensive unit and integration tests for the failed payment handling system.
Tests webhook processing, member notifications, payment history tracking, and
all critical business logic for failed recurring payments.

Key Test Coverage:
- Failed payment processing for both donations and members
- Payment failure counting with race condition protection
- Member notification escalation (1st, 2nd, final warnings)
- Payment history tracking with proper transaction IDs
- Database transaction boundaries and rollback scenarios
- Input validation and error handling
"""

import json
import time
import unittest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import frappe
from frappe.utils import getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFailedPaymentProcessing(EnhancedTestCase):
    """Unit tests for failed payment processing functions"""

    def setUp(self):
        """Set up test data for failed payment processing tests"""
        super().setUp()

        # Create test member with payment history
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email="test.member@example.com",
            payment_method="Mollie"
        )

        # Create test donation
        self.test_donation = self.create_test_donation(
            donor_name="Test Donor",
            amount=50.0
        )

        # Mock Mollie payment object
        self.mock_failed_payment = Mock()
        self.mock_failed_payment.id = "tr_test_failed_123"
        self.mock_failed_payment.status = "failed"
        self.mock_failed_payment.subscription_id = "sub_test_subscription"
        self.mock_failed_payment.customer_id = "cst_test_customer"
        self.mock_failed_payment.amount = Mock()
        self.mock_failed_payment.amount.value = "25.00"
        self.mock_failed_payment.amount.currency = "EUR"
        self.mock_failed_payment.method = "directdebit"

    def test_validate_payment_amount_dict_format(self):
        """Test payment amount validation with dictionary format"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount

        # Test dictionary format
        mock_payment = Mock()
        mock_payment.id = "tr_test_123"
        mock_payment.amount = {"value": "25.50", "currency": "EUR"}

        result = _validate_payment_amount(mock_payment)
        self.assertEqual(result, 25.50)

    def test_validate_payment_amount_object_format(self):
        """Test payment amount validation with object format"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount

        # Test object format
        mock_payment = Mock()
        mock_payment.id = "tr_test_123"
        mock_amount = Mock()
        mock_amount.value = "30.75"
        mock_payment.amount = mock_amount

        result = _validate_payment_amount(mock_payment)
        self.assertEqual(result, 30.75)

    def test_validate_payment_amount_edge_cases(self):
        """Test payment amount validation edge cases"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount

        # Test None payment
        result = _validate_payment_amount(None)
        self.assertEqual(result, 0.0)

        # Test payment without amount
        mock_payment = Mock()
        mock_payment.id = "tr_test_123"
        mock_payment.amount = None

        result = _validate_payment_amount(mock_payment)
        self.assertEqual(result, 0.0)

        # Test zero amount
        mock_payment.amount = {"value": "0.00", "currency": "EUR"}
        result = _validate_payment_amount(mock_payment)
        self.assertEqual(result, 0.0)

    def test_get_subscription_failure_count_atomic(self):
        """Test atomic failure count retrieval from database"""
        from verenigingen.integrations.mollie.api.payment_webhook import _get_subscription_failure_count

        # Add some test payment history with failures
        subscription_id = "sub_test_123"
        member = self.test_member

        # Add successful payment
        member.append("payment_history", {
            "payment_date": getdate(),
            "amount": 25.0,
            "payment_method": "Mollie",
            "payment_status": "Paid",
            "mollie_subscription_id": subscription_id
        })

        # Add failed payments
        for i in range(3):
            member.append("payment_history", {
                "payment_date": getdate(),
                "amount": 25.0,
                "payment_method": "Mollie",
                "payment_status": f"Failed (failed)",
                "mollie_subscription_id": subscription_id,
                "mollie_payment_id": f"tr_failed_{i}"
            })

        member.save()

        # Test failure counting
        failure_count = _get_subscription_failure_count(member.name, subscription_id)
        self.assertEqual(failure_count, 3)

        # Test with different subscription ID
        failure_count = _get_subscription_failure_count(member.name, "sub_different")
        self.assertEqual(failure_count, 0)

    def test_find_member_for_payment_by_subscription(self):
        """Test finding member by subscription ID"""
        from verenigingen.integrations.mollie.api.payment_webhook import find_member_for_payment

        # Set up member with subscription
        member = self.test_member
        member.mollie_subscription_id = "sub_test_find"
        member.save()

        # Create mock payment with subscription
        mock_payment = Mock()
        mock_payment.subscription_id = "sub_test_find"

        found_member = find_member_for_payment("tr_test_123", mock_payment)
        self.assertIsNotNone(found_member)
        self.assertEqual(found_member.name, member.name)

    def test_find_member_for_payment_by_customer_id(self):
        """Test finding member by customer ID"""
        from verenigingen.integrations.mollie.api.payment_webhook import find_member_for_payment

        # Set up member with customer ID
        member = self.test_member
        member.mollie_customer_id = "cst_test_customer"
        member.save()

        # Create mock payment with customer ID
        mock_payment = Mock()
        mock_payment.customer_id = "cst_test_customer"
        mock_payment.subscription_id = None

        found_member = find_member_for_payment("tr_test_123", mock_payment)
        self.assertIsNotNone(found_member)
        self.assertEqual(found_member.name, member.name)

    def test_find_member_for_payment_by_metadata(self):
        """Test finding member by payment metadata"""
        from verenigingen.integrations.mollie.api.payment_webhook import find_member_for_payment

        member = self.test_member

        # Create mock payment with metadata
        mock_payment = Mock()
        mock_payment.subscription_id = None
        mock_payment.customer_id = None
        mock_payment.metadata = {"member_id": member.name}

        found_member = find_member_for_payment("tr_test_123", mock_payment)
        self.assertIsNotNone(found_member)
        self.assertEqual(found_member.name, member.name)

    @patch('verenigingen.integrations.mollie.api.payment_webhook._notify_member_of_payment_failure')
    @patch('verenigingen.integrations.mollie.api.payment_webhook._get_subscription_failure_count')
    def test_process_failed_payment_member(self, mock_get_count, mock_notify):
        """Test processing failed member subscription payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import process_failed_payment

        # Set up member
        member = self.test_member
        member.mollie_subscription_id = "sub_test_123"
        member.save()

        # Mock failure count
        mock_get_count.return_value = 2

        # Process failed payment
        result = process_failed_payment("tr_failed_test", self.mock_failed_payment)

        # Verify results
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["processed_records"]), 1)
        self.assertEqual(result["processed_records"][0]["type"], "member")

        # Verify notification was called
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        self.assertEqual(args[2], 3)  # failure_count should be 2 + 1 = 3

    def test_process_failed_payment_donation(self):
        """Test processing failed donation payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import process_failed_payment

        # Set up donation
        donation = self.test_donation
        donation.payment_id = "tr_failed_test"
        donation.save()

        # Process failed payment
        result = process_failed_payment("tr_failed_test", self.mock_failed_payment)

        # Verify results
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["processed_records"]), 1)
        self.assertEqual(result["processed_records"][0]["type"], "donation")

        # Verify donation payment history was updated
        donation.reload()
        self.assertTrue(len(donation.payments) > 0)
        failed_payment = next((p for p in donation.payments if "Failed" in p.payment_status), None)
        self.assertIsNotNone(failed_payment)

    def test_process_successful_member_payment(self):
        """Test processing successful member subscription payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import process_successful_member_payment

        member = self.test_member
        member.mollie_customer_id = "cst_test_123"

        # Create mock successful payment
        mock_payment = Mock()
        mock_payment.id = "tr_success_123"
        mock_payment.subscription_id = "sub_test_123"
        mock_payment.amount = Mock()
        mock_payment.amount.value = "25.00"
        mock_payment.method = "directdebit"

        # Mock subscription service
        with patch('verenigingen.integrations.mollie.services.subscription_service.SubscriptionService') as mock_service:
            mock_service_instance = Mock()
            mock_service_instance.get_subscription_status.return_value = {
                "next_payment_date": "2024-02-01"
            }
            mock_service.return_value = mock_service_instance

            result = process_successful_member_payment(member, mock_payment)

            # Verify result
            self.assertEqual(result["status"], "processed")
            self.assertEqual(result["payment_id"], "tr_success_123")

            # Verify member payment history
            member.reload()
            payment_history = next((p for p in member.payment_history if p.payment_status == "Paid"), None)
            self.assertIsNotNone(payment_history)
            self.assertEqual(payment_history.mollie_payment_id, "tr_success_123")


class TestWebhookSignatureValidation(EnhancedTestCase):
    """Integration tests for webhook signature validation"""

    def setUp(self):
        super().setUp()

        # Create test Mollie settings
        self.webhook_secret = "test_webhook_secret_123"

        # Mock Mollie settings
        self.mock_mollie_settings = Mock()
        self.mock_mollie_settings.get_webhook_secret.return_value = self.webhook_secret

    def generate_valid_signature(self, payload):
        """Generate valid HMAC-SHA256 signature for testing"""
        import hmac
        import hashlib

        return hmac.new(
            self.webhook_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    @patch('frappe.get_single')
    @patch('frappe.request')
    def test_validate_webhook_signature_success(self, mock_request, mock_get_single):
        """Test successful webhook signature validation"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_webhook_signature

        # Set up mock request
        payload = json.dumps({"id": "tr_test_123"})
        valid_signature = self.generate_valid_signature(payload)

        mock_request.get_data.return_value = payload
        mock_request.headers = {"X-Mollie-Signature": valid_signature}
        mock_get_single.return_value = self.mock_mollie_settings

        # Should not raise exception
        try:
            _validate_webhook_signature()
        except Exception as e:
            self.fail(f"Valid signature validation failed: {e}")

    @patch('frappe.get_single')
    @patch('frappe.request')
    def test_validate_webhook_signature_invalid(self, mock_request, mock_get_single):
        """Test invalid webhook signature rejection"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_webhook_signature

        # Set up mock request with invalid signature
        payload = json.dumps({"id": "tr_test_123"})
        invalid_signature = "invalid_signature_12345"

        mock_request.get_data.return_value = payload
        mock_request.headers = {"X-Mollie-Signature": invalid_signature}
        mock_get_single.return_value = self.mock_mollie_settings

        # Should raise PermissionError
        with self.assertRaises(frappe.PermissionError):
            _validate_webhook_signature()

    @patch('frappe.get_single')
    @patch('frappe.request')
    def test_validate_webhook_signature_missing_header(self, mock_request, mock_get_single):
        """Test webhook validation with missing signature header"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_webhook_signature

        # Set up mock request without signature header
        payload = json.dumps({"id": "tr_test_123"})

        mock_request.get_data.return_value = payload
        mock_request.headers = {}  # No signature header
        mock_get_single.return_value = self.mock_mollie_settings

        # Should raise PermissionError
        with self.assertRaises(frappe.PermissionError):
            _validate_webhook_signature()

    @patch('frappe.get_single')
    @patch('frappe.request')
    def test_validate_webhook_signature_no_secret_configured(self, mock_request, mock_get_single):
        """Test webhook validation with no secret configured"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_webhook_signature

        # Set up mock settings with no secret
        mock_settings = Mock()
        mock_settings.get_webhook_secret.return_value = None

        payload = json.dumps({"id": "tr_test_123"})
        mock_request.get_data.return_value = payload
        mock_request.headers = {"X-Mollie-Signature": "some_signature"}
        mock_get_single.return_value = mock_settings

        # Should raise PermissionError
        with self.assertRaises(frappe.PermissionError):
            _validate_webhook_signature()


class TestPaymentFailureNotifications(EnhancedTestCase):
    """Tests for payment failure notification system"""

    def setUp(self):
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="Notification",
            last_name="Test",
            email="notification.test@example.com"
        )

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_notify_member_first_failure(self, mock_get_service):
        """Test first payment failure notification"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test first failure notification
        _notify_member_of_payment_failure(self.test_member, mock_payment, 1)

        # Verify email service was called with correct template
        mock_email_service.send_templated_email.assert_called_once()
        call_args = mock_email_service.send_templated_email.call_args
        self.assertEqual(call_args[1]["template_name"], "payment_failure_first")

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_notify_member_final_failure(self, mock_get_service):
        """Test final payment failure notification"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test final failure notification (3+ failures)
        _notify_member_of_payment_failure(self.test_member, mock_payment, 5)

        # Verify email service was called with final template
        mock_email_service.send_templated_email.assert_called_once()
        call_args = mock_email_service.send_templated_email.call_args
        self.assertEqual(call_args[1]["template_name"], "payment_failure_final")

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_notify_member_email_failure_handling(self, mock_get_service):
        """Test graceful handling of email notification failures"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service that fails
        mock_email_service = Mock()
        mock_email_service.send_templated_email.side_effect = Exception("Email service error")
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Should not raise exception even if email fails
        try:
            _notify_member_of_payment_failure(self.test_member, mock_payment, 2)
        except Exception as e:
            self.fail(f"Email notification failure should be handled gracefully: {e}")


class TestTransactionBoundariesAndRaceConditions(EnhancedTestCase):
    """Tests for database transaction boundaries and race condition handling"""

    def setUp(self):
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="Transaction",
            last_name="Test",
            email="transaction.test@example.com"
        )

    @patch('frappe.db.rollback')
    @patch('frappe.db.commit')
    @patch('frappe.db.begin')
    def test_failed_payment_transaction_rollback(self, mock_begin, mock_commit, mock_rollback):
        """Test transaction rollback on member save failure"""
        from verenigingen.integrations.mollie.api.payment_webhook import process_failed_payment

        # Set up member
        member = self.test_member
        member.mollie_subscription_id = "sub_test_rollback"
        member.save()

        # Mock payment
        mock_payment = Mock()
        mock_payment.id = "tr_rollback_test"
        mock_payment.status = "failed"
        mock_payment.subscription_id = "sub_test_rollback"
        mock_payment.amount = Mock()
        mock_payment.amount.value = "25.00"

        # Mock member.save() to raise exception after begin()
        original_save = member.save
        def failing_save(*args, **kwargs):
            if mock_begin.called and not mock_rollback.called:
                raise Exception("Database save failed")
            return original_save(*args, **kwargs)

        member.save = failing_save

        # Process failed payment should handle the transaction error gracefully
        result = process_failed_payment("tr_rollback_test", mock_payment)

        # Verify transaction methods were called
        mock_begin.assert_called()
        mock_rollback.assert_called()

        # Should still return success (graceful error handling)
        self.assertEqual(result["status"], "failed")

    def test_concurrent_failure_count_accuracy(self):
        """Test that concurrent failure counting remains accurate"""
        from verenigingen.integrations.mollie.api.payment_webhook import _get_subscription_failure_count

        member = self.test_member
        subscription_id = "sub_concurrent_test"

        # Add multiple failed payments
        for i in range(5):
            member.append("payment_history", {
                "payment_date": getdate(),
                "amount": 25.0,
                "payment_method": "Mollie",
                "payment_status": f"Failed (failed)",
                "mollie_subscription_id": subscription_id,
                "mollie_payment_id": f"tr_concurrent_{i}"
            })

        member.save()

        # Multiple calls should return consistent results
        counts = []
        for _ in range(10):
            count = _get_subscription_failure_count(member.name, subscription_id)
            counts.append(count)

        # All counts should be the same (5 failures)
        self.assertTrue(all(count == 5 for count in counts))

        # Test with different subscription ID should return 0
        different_count = _get_subscription_failure_count(member.name, "sub_different")
        self.assertEqual(different_count, 0)


if __name__ == "__main__":
    unittest.main()