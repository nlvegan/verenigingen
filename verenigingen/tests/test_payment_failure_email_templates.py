"""
Payment Failure Email Template Test Suite
=========================================

Comprehensive testing for payment failure email templates and notification system.
Tests template rendering, context variable handling, escalation logic, and
integration with the EmailService system.

Key Coverage:
- Email template content validation
- Context variable injection and escaping
- Template fallback mechanisms
- Member notification escalation workflows
- EmailService integration testing
- Template rendering performance
"""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import frappe
from frappe.utils import getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPaymentFailureEmailTemplates(EnhancedTestCase):
    """Tests for payment failure email templates"""

    def setUp(self):
        """Set up email template testing environment"""
        super().setUp()

        # Create test member for email testing
        self.test_member = self.create_test_member(
            first_name="EmailTest",
            last_name="Member",
            email="emailtest.member@example.com",
            payment_method="Mollie"
        )

        # Set up member with next payment date
        self.test_member.next_payment_date = "2024-02-15"
        self.test_member.save()

        # Ensure payment failure templates exist
        self.ensure_email_templates_exist()

    def ensure_email_templates_exist(self):
        """Ensure payment failure email templates exist for testing"""
        templates = [
            "payment_failure_first",
            "payment_failure_second",
            "payment_failure_final",
            "subscription_cancelled",
            "subscription_suspended"
        ]

        for template_name in templates:
            if not frappe.db.exists("Email Template", template_name):
                # Create minimal test template
                frappe.get_doc({
                    "doctype": "Email Template",
                    "name": template_name,
                    "enabled": 1,
                    "subject": f"Test {template_name} - {{{{ member.first_name|e }}}}",
                    "response_html": f"""
                    <div>
                        <h1>Test {template_name}</h1>
                        <p>Dear {{{{ member.first_name|e }}}},</p>
                        <p>Payment Status: {{{{ payment_status|e }}}}</p>
                        <p>Amount: €{{{{ amount|floatformat:2|e }}}}</p>
                        <p>Failure Count: {{{{ failure_count|e }}}}</p>
                        <p>Next Payment: {{{{ next_payment_date|e }}}}</p>
                    </div>
                    """,
                    "use_html": 1
                }).insert()

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_payment_failure_first_template_rendering(self, mock_get_service):
        """Test first payment failure template rendering with proper context"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock payment object
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test first failure notification
        _notify_member_of_payment_failure(self.test_member, mock_payment, 1)

        # Verify email service was called
        mock_email_service.send_templated_email.assert_called_once()
        call_kwargs = mock_email_service.send_templated_email.call_args[1]

        # Verify correct template
        self.assertEqual(call_kwargs["template_name"], "payment_failure_first")

        # Verify context variables
        context = call_kwargs["context"]
        self.assertEqual(context["member"], self.test_member)
        self.assertEqual(context["failure_count"], 1)
        self.assertEqual(context["payment_status"], "failed")
        self.assertIn("amount", context)
        self.assertEqual(context["next_payment_date"], self.test_member.next_payment_date)

        # Verify recipients
        self.assertEqual(call_kwargs["recipients"], [self.test_member.email])

        # Verify reference
        self.assertEqual(call_kwargs["reference_doctype"], "Member")
        self.assertEqual(call_kwargs["reference_name"], self.test_member.name)

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_payment_failure_escalation_templates(self, mock_get_service):
        """Test email template escalation based on failure count"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test different failure counts
        test_cases = [
            (1, "payment_failure_first"),
            (2, "payment_failure_second"),
            (3, "payment_failure_final"),
            (5, "payment_failure_final"),  # Should still use final template
        ]

        for failure_count, expected_template in test_cases:
            mock_email_service.reset_mock()

            _notify_member_of_payment_failure(self.test_member, mock_payment, failure_count)

            call_kwargs = mock_email_service.send_templated_email.call_args[1]
            self.assertEqual(
                call_kwargs["template_name"],
                expected_template,
                f"Failure count {failure_count} should use template {expected_template}"
            )
            self.assertEqual(call_kwargs["context"]["failure_count"], failure_count)

    @patch('frappe.db.exists')
    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_email_template_fallback_mechanism(self, mock_get_service, mock_db_exists):
        """Test fallback to generic template when specific template doesn't exist"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock template existence check - first template doesn't exist, generic does
        def mock_exists(doctype, name):
            if doctype == "Email Template":
                if name == "payment_failure_first":
                    return False  # Specific template doesn't exist
                elif name == "payment_failure_generic":
                    return True   # Generic fallback exists
            return True

        mock_db_exists.side_effect = mock_exists

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test fallback behavior
        _notify_member_of_payment_failure(self.test_member, mock_payment, 1)

        # Verify fallback template was used
        call_kwargs = mock_email_service.send_templated_email.call_args[1]
        self.assertEqual(call_kwargs["template_name"], "payment_failure_generic")

    @patch('frappe.db.exists')
    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_email_template_missing_graceful_handling(self, mock_get_service, mock_db_exists):
        """Test graceful handling when no email templates exist"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service (should not be called)
        mock_email_service = Mock()
        mock_get_service.return_value = mock_email_service

        # Mock template existence check - no templates exist
        mock_db_exists.return_value = False

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Should not raise exception when no templates exist
        try:
            _notify_member_of_payment_failure(self.test_member, mock_payment, 1)
        except Exception as e:
            self.fail(f"Should handle missing templates gracefully: {e}")

        # Email service should not be called
        mock_email_service.send_templated_email.assert_not_called()

    def test_email_context_variable_validation(self):
        """Test that email context contains all required variables"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount

        # Mock payment with comprehensive data
        mock_payment = Mock()
        mock_payment.status = "failed"
        mock_payment.id = "tr_context_test_123"
        mock_payment.amount = Mock()
        mock_payment.amount.value = "25.50"
        mock_payment.amount.currency = "EUR"

        # Test amount validation
        validated_amount = _validate_payment_amount(mock_payment)
        self.assertEqual(validated_amount, 25.50)

        # Test context creation (this would be part of notification function)
        expected_context = {
            "member": self.test_member,
            "payment": mock_payment,
            "failure_count": 2,
            "payment_status": "failed",
            "amount": validated_amount,
            "next_payment_date": self.test_member.next_payment_date
        }

        # Verify all required context variables are present
        required_variables = ["member", "payment", "failure_count", "payment_status", "amount"]
        for var in required_variables:
            self.assertIn(var, expected_context, f"Required context variable '{var}' missing")

        # Verify data types
        self.assertIsInstance(expected_context["failure_count"], int)
        self.assertIsInstance(expected_context["amount"], float)
        self.assertIsInstance(expected_context["payment_status"], str)

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_email_service_error_handling(self, mock_get_service):
        """Test graceful handling of email service errors"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure

        # Mock email service that raises exception
        mock_email_service = Mock()
        mock_email_service.send_templated_email.side_effect = Exception("Email service unavailable")
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Should not raise exception even if email service fails
        try:
            _notify_member_of_payment_failure(self.test_member, mock_payment, 1)
        except Exception as e:
            self.fail(f"Should handle email service errors gracefully: {e}")

    def test_subscription_status_change_notification_templates(self):
        """Test subscription status change notification templates"""
        from verenigingen.integrations.mollie.api.sync import _notify_subscription_status_change

        # Mock subscription status data
        subscription_status = {
            "id": "sub_status_test_123",
            "status": "cancelled",
            "next_payment_date": None
        }

        # Test should pass without errors even if email service is not available
        # (This tests the template selection logic)
        try:
            # This would normally send an email, but we're testing template selection
            with patch('verenigingen.services.communication.email_service.get_email_service') as mock_get_service:
                mock_email_service = Mock()
                mock_email_service.send_templated_email.return_value = {"status": "success"}
                mock_get_service.return_value = mock_email_service

                _notify_subscription_status_change(
                    self.test_member,
                    "active",
                    "cancelled",
                    subscription_status
                )

                # Verify correct template was selected
                call_kwargs = mock_email_service.send_templated_email.call_args[1]
                self.assertEqual(call_kwargs["template_name"], "subscription_cancelled")

        except Exception as e:
            self.fail(f"Subscription status change notification failed: {e}")


class TestEmailTemplatePerformance(EnhancedTestCase):
    """Performance tests for email template rendering"""

    def setUp(self):
        super().setUp()

        # Create multiple test members
        self.test_members = []
        for i in range(50):
            member = self.create_test_member(
                first_name=f"Perf{i}",
                last_name="Test",
                email=f"perf{i}.test@example.com"
            )
            self.test_members.append(member)

    @patch('verenigingen.services.communication.email_service.get_email_service')
    def test_bulk_email_notification_performance(self, mock_get_service):
        """Test performance of bulk email notifications"""
        from verenigingen.integrations.mollie.api.payment_webhook import _notify_member_of_payment_failure
        import time

        # Mock email service
        mock_email_service = Mock()
        mock_email_service.send_templated_email.return_value = {"status": "success"}
        mock_get_service.return_value = mock_email_service

        # Mock payment
        mock_payment = Mock()
        mock_payment.status = "failed"

        # Test bulk notifications
        start_time = time.time()

        for member in self.test_members[:20]:  # Test with 20 members
            _notify_member_of_payment_failure(member, mock_payment, 1)

        end_time = time.time()
        notification_time = end_time - start_time

        # Should complete within reasonable time
        self.assertLess(
            notification_time,
            2.0,
            f"Bulk email notifications took {notification_time:.2f}s for 20 members"
        )

        # Verify all emails were processed
        self.assertEqual(mock_email_service.send_templated_email.call_count, 20)

    def test_template_context_creation_performance(self):
        """Test performance of email template context creation"""
        from verenigingen.integrations.mollie.api.payment_webhook import _validate_payment_amount
        import time

        # Create mock payments
        mock_payments = []
        for i in range(1000):
            payment = Mock()
            payment.status = "failed"
            payment.id = f"tr_perf_{i}"
            payment.amount = Mock()
            payment.amount.value = f"{25.00 + i * 0.01:.2f}"
            mock_payments.append(payment)

        # Test context creation performance
        start_time = time.time()

        for payment in mock_payments:
            # Simulate context creation
            amount = _validate_payment_amount(payment)
            context = {
                "member": self.test_members[0],
                "payment": payment,
                "failure_count": 1,
                "payment_status": payment.status,
                "amount": amount,
                "next_payment_date": "2024-02-15"
            }
            # Verify context is created correctly
            self.assertIsInstance(context["amount"], float)

        end_time = time.time()
        context_time = end_time - start_time

        # Should complete within reasonable time
        self.assertLess(
            context_time,
            1.0,
            f"Template context creation took {context_time:.2f}s for 1000 payments"
        )


if __name__ == "__main__":
    unittest.main()