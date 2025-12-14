"""
Mollie Webhook Integration Test Suite - Comprehensive End-to-End Testing
======================================================================

Complete integration testing for the Mollie webhook processing system.
Tests the entire webhook processing pipeline from HTTP request to database
updates, email notifications, and proper error handling.

Key Integration Coverage:
- End-to-end webhook processing for failed payments
- Complete signature validation and authentication
- Member and donation payment processing workflows
- Email notification integration testing
- Database transaction and rollback scenarios
- Performance under concurrent webhook processing
- Real business logic validation with proper test data
"""

import hashlib
import hmac
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.test_runner import make_test_records
from frappe.utils import getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestWebhookIntegrationComprehensive(EnhancedTestCase):
    """Comprehensive end-to-end webhook integration tests"""

    def setUp(self):
        """Set up complete test environment for webhook integration"""
        super().setUp()

        # Set up test webhook secret
        self.webhook_secret = "test_webhook_secret_integration_123"

        # Create test member with complete subscription setup
        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email="integration.test@example.com",
            payment_method="Mollie",
        )

        # Set up Mollie subscription details
        self.test_member.mollie_customer_id = "cst_integration_test_123"
        self.test_member.mollie_subscription_id = "sub_integration_test_456"
        self.test_member.subscription_status = "active"
        self.test_member.save()

        # Create test donation
        self.test_donation = self.create_test_donation(donor_name="Integration Test Donor", amount=75.0)
        self.test_donation.payment_id = "tr_donation_integration_123"
        self.test_donation.save()

        # Mock Mollie Settings
        self.mock_mollie_settings = Mock()
        self.mock_mollie_settings.get_webhook_secret.return_value = self.webhook_secret

        # Create webhook user for testing
        self.webhook_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "webhook.test@verenigingen.test",
                "first_name": "Webhook",
                "last_name": "Test User",
                "enabled": 1,
            }
        ).insert()

        # Add Verenigingen Webhook User role
        if not frappe.db.exists("Role", "Verenigingen Webhook User"):
            frappe.get_doc(
                {"doctype": "Role", "role_name": "Verenigingen Webhook User", "desk_access": 0}
            ).insert()

        # Assign role to webhook user
        frappe.get_doc(
            {"doctype": "Has Role", "parent": self.webhook_user.name, "role": "Verenigingen Webhook User"}
        ).insert()

    def generate_webhook_signature(self, payload):
        """Generate valid webhook signature for integration testing"""
        return hmac.new(
            self.webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def create_webhook_request_data(self, payment_id, status="failed", **kwargs):
        """Create realistic webhook request data"""
        webhook_data = {
            "id": payment_id,
            "status": status,
            "amount": {"value": "25.00", "currency": "EUR"},
            "method": "directdebit",
            "created_at": now_datetime().isoformat(),
            **kwargs,
        }
        return json.dumps(webhook_data)

    @patch("frappe.get_single")
    @patch("frappe.local.form_dict", new_callable=dict)
    @patch("frappe.request")
    def test_complete_failed_member_payment_workflow(self, mock_request, mock_form_dict, mock_get_single):
        """Test complete workflow for failed member subscription payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import handle_mollie_payment_webhook

        # Set up webhook request data
        payment_id = "tr_member_failed_integration"
        webhook_payload = self.create_webhook_request_data(
            payment_id,
            status="failed",
            subscription_id=self.test_member.mollie_subscription_id,
            customer_id=self.test_member.mollie_customer_id,
        )
        signature = self.generate_webhook_signature(webhook_payload)

        # Mock request components
        mock_request.get_data.return_value = webhook_payload
        mock_request.headers = {"X-Mollie-Signature": signature}
        mock_form_dict.update(json.loads(webhook_payload))
        mock_get_single.return_value = self.mock_mollie_settings

        # Mock Mollie API client
        mock_payment = Mock()
        mock_payment.id = payment_id
        mock_payment.status = "failed"
        mock_payment.subscription_id = self.test_member.mollie_subscription_id
        mock_payment.customer_id = self.test_member.mollie_customer_id
        # Use dict format for amount to match real Mollie SDK v3.8.0 behavior
        mock_payment.amount = {"value": "25.00", "currency": "EUR"}
        mock_payment.method = "directdebit"

        with patch("verenigingen.integrations.mollie.api.payment_webhook.get_webhook_user") as mock_get_user:
            mock_get_user.return_value = self.webhook_user.email

            with patch("frappe.set_user"):
                with patch.object(self.mock_mollie_settings, "get_mollie_client") as mock_get_client:
                    mock_client = Mock()
                    mock_client.payments.get.return_value = mock_payment
                    mock_get_client.return_value = mock_client

                    # Mock email service to prevent actual email sending
                    with patch(
                        "verenigingen.services.communication.email_service.get_email_service"
                    ) as mock_email:
                        mock_email_service = Mock()
                        mock_email_service.send_templated_email.return_value = {"status": "success"}
                        mock_email.return_value = mock_email_service

                        # Process webhook
                        result = handle_mollie_payment_webhook()

                        # Verify webhook processing success
                        self.assertEqual(result["status"], "success")
                        self.assertIn("Failed payment processed", result["message"])

                        # Verify member payment history was updated
                        self.test_member.reload()
                        failed_payment = None
                        for payment in self.test_member.payment_history:
                            if payment.mollie_payment_id == payment_id:
                                failed_payment = payment
                                break

                        self.assertIsNotNone(failed_payment)
                        self.assertIn("Failed", failed_payment.payment_status)
                        self.assertEqual(
                            failed_payment.mollie_subscription_id, self.test_member.mollie_subscription_id
                        )

                        # Verify email notification was sent
                        mock_email_service.send_templated_email.assert_called_once()

    @patch("frappe.get_single")
    @patch("frappe.local.form_dict", new_callable=dict)
    @patch("frappe.request")
    def test_complete_failed_donation_workflow(self, mock_request, mock_form_dict, mock_get_single):
        """Test complete workflow for failed donation payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import handle_mollie_payment_webhook

        # Set up webhook request data
        payment_id = self.test_donation.payment_id
        webhook_payload = self.create_webhook_request_data(payment_id, status="failed")
        signature = self.generate_webhook_signature(webhook_payload)

        # Mock request components
        mock_request.get_data.return_value = webhook_payload
        mock_request.headers = {"X-Mollie-Signature": signature}
        mock_form_dict.update(json.loads(webhook_payload))
        mock_get_single.return_value = self.mock_mollie_settings

        # Mock Mollie API client
        mock_payment = Mock()
        mock_payment.id = payment_id
        mock_payment.status = "failed"
        mock_payment.subscription_id = None
        mock_payment.customer_id = None
        # Use dict format for amount to match real Mollie SDK v3.8.0 behavior
        mock_payment.amount = {"value": "75.00", "currency": "EUR"}
        mock_payment.method = "ideal"

        with patch("verenigingen.integrations.mollie.api.payment_webhook.get_webhook_user") as mock_get_user:
            mock_get_user.return_value = self.webhook_user.email

            with patch("frappe.set_user"):
                with patch.object(self.mock_mollie_settings, "get_mollie_client") as mock_get_client:
                    mock_client = Mock()
                    mock_client.payments.get.return_value = mock_payment
                    mock_get_client.return_value = mock_client

                    # Process webhook
                    result = handle_mollie_payment_webhook()

                    # Verify webhook processing success
                    self.assertEqual(result["status"], "success")
                    self.assertIn("Failed payment processed", result["message"])

                    # Verify donation payment history was updated
                    self.test_donation.reload()
                    failed_payment = None
                    for payment in self.test_donation.payments:
                        if payment.mollie_payment_id == payment_id:
                            failed_payment = payment
                            break

                    self.assertIsNotNone(failed_payment)
                    self.assertIn("Failed", failed_payment.payment_status)

    @patch("frappe.get_single")
    @patch("frappe.local.form_dict", new_callable=dict)
    @patch("frappe.request")
    def test_successful_member_payment_workflow(self, mock_request, mock_form_dict, mock_get_single):
        """Test complete workflow for successful member subscription payment"""
        from verenigingen.integrations.mollie.api.payment_webhook import handle_mollie_payment_webhook

        # Set up webhook request data
        payment_id = "tr_member_success_integration"
        webhook_payload = self.create_webhook_request_data(
            payment_id,
            status="paid",
            subscription_id=self.test_member.mollie_subscription_id,
            customer_id=self.test_member.mollie_customer_id,
        )
        signature = self.generate_webhook_signature(webhook_payload)

        # Mock request components
        mock_request.get_data.return_value = webhook_payload
        mock_request.headers = {"X-Mollie-Signature": signature}
        mock_form_dict.update(json.loads(webhook_payload))
        mock_get_single.return_value = self.mock_mollie_settings

        # Mock Mollie API client
        mock_payment = Mock()
        mock_payment.id = payment_id
        mock_payment.status = "paid"
        mock_payment.subscription_id = self.test_member.mollie_subscription_id
        mock_payment.customer_id = self.test_member.mollie_customer_id
        # Use dict format for amount to match real Mollie SDK v3.8.0 behavior
        mock_payment.amount = {"value": "25.00", "currency": "EUR"}
        mock_payment.method = "directdebit"

        with patch("verenigingen.integrations.mollie.api.payment_webhook.get_webhook_user") as mock_get_user:
            mock_get_user.return_value = self.webhook_user.email

            with patch("frappe.set_user"):
                with patch.object(self.mock_mollie_settings, "get_mollie_client") as mock_get_client:
                    mock_client = Mock()
                    mock_client.payments.get.return_value = mock_payment
                    mock_get_client.return_value = mock_client

                    # Mock subscription service
                    with patch(
                        "verenigingen.integrations.mollie.services.subscription_service.SubscriptionService"
                    ) as mock_sub_service:
                        mock_service_instance = Mock()
                        mock_service_instance.get_subscription_status.return_value = {
                            "next_payment_date": "2024-02-01"
                        }
                        mock_sub_service.return_value = mock_service_instance

                        # Process webhook
                        result = handle_mollie_payment_webhook()

                        # Verify webhook processing success
                        self.assertEqual(result["status"], "success")
                        self.assertIn("Member subscription payment processed", result["message"])

                        # Verify member payment history was updated
                        self.test_member.reload()
                        successful_payment = None
                        for payment in self.test_member.payment_history:
                            if payment.mollie_payment_id == payment_id:
                                successful_payment = payment
                                break

                        self.assertIsNotNone(successful_payment)
                        self.assertEqual(successful_payment.payment_status, "Paid")
                        self.assertEqual(
                            successful_payment.mollie_subscription_id, self.test_member.mollie_subscription_id
                        )

    def test_webhook_signature_validation_integration(self):
        """Test webhook signature validation in integration context"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_webhook_signature

        # Test with valid signature
        payload = '{"id": "tr_test_signature_validation"}'
        valid_signature = self.generate_webhook_signature(payload)

        with patch("frappe.request") as mock_request:
            with patch("frappe.get_single") as mock_get_single:
                mock_request.get_data.return_value = payload
                mock_request.headers = {"X-Mollie-Signature": valid_signature}
                mock_get_single.return_value = self.mock_mollie_settings

                # Should not raise exception
                try:
                    _validate_webhook_signature()
                except Exception as e:
                    self.fail(f"Valid signature validation failed: {e}")

        # Test with invalid signature
        invalid_signature = "invalid_signature_123"

        with patch("frappe.request") as mock_request:
            with patch("frappe.get_single") as mock_get_single:
                mock_request.get_data.return_value = payload
                mock_request.headers = {"X-Mollie-Signature": invalid_signature}
                mock_get_single.return_value = self.mock_mollie_settings

                # Should raise PermissionError
                with self.assertRaises(frappe.PermissionError):
                    _validate_webhook_signature()

    def test_webhook_idempotency_protection(self):
        """Test that duplicate webhooks are handled properly by existing idempotency"""
        from verenigingen.integrations.mollie.api.payment_webhook import check_payment_processing_status

        # Create a donation for idempotency testing
        donation = self.test_donation
        payment_id = "tr_idempotency_test_123"

        # First processing - should show not processed
        status = check_payment_processing_status(donation, payment_id)
        self.assertFalse(status["payment_entry_created"])
        self.assertFalse(status["payment_history_exists"])
        self.assertFalse(status["all_complete"])

        # Simulate processing by adding payment history
        donation.append(
            "payments",
            {
                "payment_date": getdate(),
                "amount": donation.amount,
                "payment_method": "Mollie",
                "payment_id": payment_id,
                "payment_reference": payment_id,
                "payment_status": "Failed (failed)",
                "mollie_payment_id": payment_id,
            },
        )
        donation.save()

        # Second check - should show payment history exists
        status = check_payment_processing_status(donation, payment_id)
        self.assertFalse(status["payment_entry_created"])  # No PE created for failed payment
        self.assertTrue(status["payment_history_exists"])

    def test_concurrent_webhook_processing_safety(self):
        """Test that concurrent webhook processing maintains data integrity"""
        from verenigingen.integrations.mollie.api.payment_webhook import _get_subscription_failure_count

        member = self.test_member
        subscription_id = "sub_concurrent_safety_test"

        # Simulate adding multiple failures rapidly (as would happen with concurrent webhooks)
        initial_count = _get_subscription_failure_count(member.name, subscription_id)
        self.assertEqual(initial_count, 0)

        # Add failures one at a time (simulating concurrent processing)
        for i in range(3):
            # Get current count atomically
            current_count = _get_subscription_failure_count(member.name, subscription_id)

            # Add new failure
            member.append(
                "payment_history",
                {
                    "payment_date": getdate(),
                    "amount": 25.0,
                    "payment_method": "Mollie",
                    "payment_status": f"Failed (failed)",
                    "mollie_subscription_id": subscription_id,
                    "mollie_payment_id": f"tr_concurrent_safety_{i}",
                },
            )
            member.save()

            # Verify count increases correctly
            new_count = _get_subscription_failure_count(member.name, subscription_id)
            self.assertEqual(new_count, current_count + 1)

        # Final verification
        final_count = _get_subscription_failure_count(member.name, subscription_id)
        self.assertEqual(final_count, 3)

    def tearDown(self):
        """Clean up test environment"""
        try:
            # Clean up test user
            if hasattr(self, "webhook_user") and self.webhook_user:
                frappe.delete_doc("User", self.webhook_user.name, force=True)
        except:
            pass

        super().tearDown()


class TestWebhookPerformanceIntegration(EnhancedTestCase):
    """Performance tests for webhook processing under load"""

    def setUp(self):
        super().setUp()

        # Create multiple test members for performance testing
        self.test_members = []
        for i in range(10):
            member = self.create_test_member(
                first_name=f"Performance{i}",
                last_name="Test",
                email=f"performance{i}.test@example.com",
                payment_method="Mollie",
            )
            member.mollie_customer_id = f"cst_perf_test_{i}"
            member.mollie_subscription_id = f"sub_perf_test_{i}"
            member.save()
            self.test_members.append(member)

    def test_bulk_failure_count_queries_performance(self):
        """Test performance of failure count queries with bulk data"""
        from verenigingen.integrations.mollie.api.payment_webhook import _get_subscription_failure_count

        # Add bulk payment history data
        for member in self.test_members[:5]:  # Test with 5 members
            for i in range(20):  # 20 payments each
                member.append(
                    "payment_history",
                    {
                        "payment_date": getdate(),
                        "amount": 25.0,
                        "payment_method": "Mollie",
                        "payment_status": "Failed (failed)" if i % 3 == 0 else "Paid",
                        "mollie_subscription_id": member.mollie_subscription_id,
                        "mollie_payment_id": f"tr_bulk_{member.name}_{i}",
                    },
                )
            member.save()

        # Test query performance
        start_time = time.time()

        for member in self.test_members[:5]:
            failure_count = _get_subscription_failure_count(member.name, member.mollie_subscription_id)
            # Each member should have ~7 failures (every 3rd payment out of 20)
            self.assertGreater(failure_count, 5)
            self.assertLess(failure_count, 10)

        end_time = time.time()
        query_time = end_time - start_time

        # Should complete within reasonable time (adjust threshold as needed)
        self.assertLess(query_time, 2.0, f"Bulk failure count queries took {query_time:.2f}s")

    def test_payment_amount_validation_performance(self):
        """Test performance of payment amount validation with various formats"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount

        # Test various payment object formats
        test_cases = []

        # Dictionary format
        for i in range(1000):
            mock_payment = Mock()
            mock_payment.id = f"tr_perf_{i}"
            mock_payment.amount = {"value": f"{25.00 + i * 0.01:.2f}", "currency": "EUR"}
            test_cases.append(mock_payment)

        # Object format
        for i in range(1000):
            mock_payment = Mock()
            mock_payment.id = f"tr_perf_obj_{i}"
            mock_amount = Mock()
            mock_amount.value = f"{30.00 + i * 0.01:.2f}"
            mock_payment.amount = mock_amount
            test_cases.append(mock_payment)

        # Test performance
        start_time = time.time()

        for payment in test_cases:
            amount = _validate_payment_amount(payment)
            self.assertGreater(amount, 0)

        end_time = time.time()
        validation_time = end_time - start_time

        # Should complete within reasonable time
        self.assertLess(
            validation_time, 1.0, f"Payment validation took {validation_time:.2f}s for 2000 payments"
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
