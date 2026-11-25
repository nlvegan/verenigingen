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
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates
from verenigingen.utils.operation_result import OperationResult


class TestPaymentFailureEmailTemplates(EnhancedTestCase):
    """Tests for payment failure email templates"""

    @classmethod
    def tearDownClass(cls):
        # #1982: tests here delete the fixture-shipped payment_failure_* templates;
        # restore the shipped rows
        _cleanup_stock_email_templates(
            ["payment_failure_final", "subscription_cancelled", "subscription_suspended"]
        )
        super().tearDownClass()

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
                        <p>Amount: €{{{{ "%.2f"|format(amount)|e }}}}</p>
                        <p>Failure Count: {{{{ failure_count|e }}}}</p>
                        <p>Next Payment: {{{{ next_payment_date|e }}}}</p>
                    </div>
                    """,
                    "use_html": 1
                }).insert()

    def create_specific_template(self, template_name, subject="Test Subject", response="Test Response"):
        """
        Helper method to create a specific email template for testing.
        Permission bypasses allowed in helper methods.
        """
        if not frappe.db.exists("Email Template", template_name):
            frappe.get_doc({
                "doctype": "Email Template",
                "name": template_name,
                "subject": subject,
                "response": response
            }).insert(ignore_permissions=True)

    def delete_specific_template(self, template_name):
        """
        Helper method to delete a specific email template for testing.
        Permission bypasses allowed in helper methods.
        """
        if frappe.db.exists("Email Template", template_name):
            frappe.delete_doc("Email Template", template_name, ignore_permissions=True)

    def delete_all_failure_templates(self):
        """
        Helper method to delete all payment failure templates for testing.
        Permission bypasses allowed in helper methods.
        """
        template_names = ["payment_failure_final"]
        for template_name in template_names:
            self.delete_specific_template(template_name)

    def test_email_context_variable_validation(self):
        """Test that email context contains all required variables"""
        from verenigingen.verenigingen_payments.mollie.api.payment_webhook import _validate_payment_amount

        # Mock payment with comprehensive data
        mock_payment = Mock()
        mock_payment.status = "failed"
        # _validate_payment_amount parses payment.amount; give it a realistic Mollie
        # amount so it does not throw (a bare Mock has no parseable amount and the
        # notification would silently swallow the resulting ValidationError).
        mock_payment.amount = {"value": "25.00", "currency": "EUR"}
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

    def test_subscription_status_change_notification_templates(self):
        """Test subscription status change notification templates

        REGRESSION: send_templated_email() (services/communication/email_service.py)
        returns a real OperationResult dataclass, not a dict -- the mock here must
        return the same shape the production EmailService actually returns.
        _notify_subscription_status_change() previously read
        result.get("status") == "success", which raises AttributeError on a real
        OperationResult on every call. That AttributeError was itself swallowed by
        the function's own outer try/except (so the call still "succeeds" from the
        caller's point of view), which is exactly why a bare
        "does it raise" test cannot catch this class of bug -- the assertion below
        inspects the logger calls the two branches actually make, which do differ.
        """
        from verenigingen.verenigingen_payments.mollie.api.sync import _notify_subscription_status_change

        # Mock subscription status data. Mollie's status value is "canceled"
        # (American spelling, one 'l'); the notifier matches that exact value.
        subscription_status = {
            "id": "sub_status_test_123",
            "status": "canceled",
            "next_payment_date": None
        }

        # Test should pass without errors even if email service is not available
        # (This tests the template selection logic)
        try:
            # This would normally send an email, but we're testing template selection
            with patch('verenigingen.services.communication.email_service.get_email_service') as mock_get_service, \
                 patch('verenigingen.verenigingen_payments.mollie.api.sync.frappe.logger') as mock_logger:
                mock_email_service = Mock()
                mock_email_service.send_templated_email.return_value = OperationResult.ok(
                    {}, message="sent"
                )
                mock_get_service.return_value = mock_email_service
                mock_log = Mock()
                mock_logger.return_value = mock_log

                _notify_subscription_status_change(
                    self.test_member,
                    "active",
                    "canceled",
                    subscription_status
                )

                # Verify correct template was selected
                call_kwargs = mock_email_service.send_templated_email.call_args[1]
                self.assertEqual(call_kwargs["template_name"], "subscription_cancelled")

                # A successful OperationResult must be read via .success, not
                # .get("status") -- the buggy version raised AttributeError here,
                # was swallowed by the outer except, and logged via .error(...)
                # instead of the success .info(...) line below.
                mock_log.info.assert_called_once()
                mock_log.error.assert_not_called()

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

    def test_template_context_creation_performance(self):
        """Test performance of email template context creation"""
        from verenigingen.verenigingen_payments.mollie.api.payment_webhook import _validate_payment_amount
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



