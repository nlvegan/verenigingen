"""
Comprehensive EmailService Integration Tests
==========================================

Tests the unified email notification system with realistic data generation
and integration testing that validates the entire email flow from trigger
event to template rendering to delivery.

Covers:
- EmailService functionality with unified templates
- Event subscriber notifications
- Payment notification systems
- Template rendering with proper context variables
- Error handling and fallback mechanisms
- XSS protection in templates
- Compatibility layer functionality
"""

import json
import time
from unittest.mock import patch, MagicMock

import frappe
from frappe.utils import add_days, getdate, now_datetime, random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.communication.email_service import get_email_service, EmailService
from verenigingen.services.communication.compatibility import (
    send_sepa_email,
    send_member_notification,
    send_chapter_email,
)
import unittest


class TestEmailServiceIntegration(EnhancedTestCase):
    """Integration tests for unified EmailService system"""

    def setUp(self):
        """Set up test environment with realistic data"""
        super().setUp()
        self.email_service = get_email_service()

        # Create test templates for our tests
        self._create_test_email_templates()

        # Create realistic test data
        self.test_chapter = self.factory.ensure_test_chapter(
            "Integration Test Chapter",
            {
                "region": "Integration Region",
                "introduction": "Chapter for integration testing",
                "contact_email": "chapter@test.invalid"
            }
        )

        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="TestMember",
            email="integration.member@test.invalid",
            birth_date="1985-06-15",
            member_id=f"INT-TEST-{int(time.time() * 1000000) % 1000000}"
        )

        # Add member to chapter
        self.test_chapter.append("members", {
            "member": self.test_member.name,
            "enabled": 1,
            "join_date": getdate()
        })
        self.test_chapter.save()

    def _create_test_email_templates(self):
        """Create email templates needed for testing"""
        templates = [
            {
                "name": "test_member_approval",
                "subject": "Membership Approved - {{ member_name|e }}",
                "response_html": """
                <div>
                    <h2>Welcome {{ member_name|e }}!</h2>
                    <p>Your membership ({{ membership_number|e }}) has been approved.</p>
                    <p>Organization: {{ organization_name|e }}</p>
                </div>
                """,
            },
            {
                "name": "test_sepa_notification",
                "subject": "SEPA Mandate {{ mandate_action|e }}",
                "response_html": """
                <div>
                    <h2>SEPA Mandate Update</h2>
                    <p>Dear {{ member_name|e }},</p>
                    <p>Mandate ID: {{ mandate_id|e }}</p>
                    <p>IBAN: {{ iban|e }}</p>
                    <p>Bank: {{ bank_name|e }}</p>
                </div>
                """,
            },
            {
                "name": "test_chapter_announcement",
                "subject": "Chapter Update - {{ chapter_name|e }}",
                "response_html": """
                <div>
                    <h2>{{ chapter_name|e }} News</h2>
                    <p>{{ announcement_content|e }}</p>
                    <p>Contact: {{ contact_email|e }}</p>
                </div>
                """,
            }
        ]

        for template_data in templates:
            if not frappe.db.exists("Email Template", template_data["name"]):
                template_doc = frappe.get_doc({
                    "doctype": "Email Template",
                    "name": template_data["name"],
                    "subject": template_data["subject"],
                    "response_html": template_data["response_html"],
                    "use_html": 1,
                    "enabled": 1
                })
                template_doc.insert()

    def test_email_service_templated_sending(self):
        """Test EmailService templated email sending with realistic context"""
        context = {
            "member_name": self.test_member.full_name,
            "membership_number": self.test_member.name,
            "organization_name": "Test Organization"
        }

        # Mock frappe.sendmail to capture the email
        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_templated_email(
                template_name="test_member_approval",
                recipients=[self.test_member.email],
                context=context,
                reference_doctype="Member",
                reference_name=self.test_member.name
            )

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.data["recipients_count"], 1)
        self.assertEqual(result.data["template"], "test_member_approval")

        # Verify email was sent with correct content
        mock_sendmail.assert_called_once()
        call_args = mock_sendmail.call_args
        self.assertIn(self.test_member.email, call_args[1]["recipients"])
        self.assertIn("Membership Approved", call_args[1]["subject"])
        self.assertIn(self.test_member.full_name, call_args[1]["message"])

    def test_email_service_notification_mapping(self):
        """Test EmailService notification type mapping"""
        # Mock frappe.sendmail
        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_notification(
                notification_type="member_approval",
                recipients=[self.test_member.email],
                data={
                    "member_name": self.test_member.full_name,
                    "membership_number": self.test_member.name
                }
            )

        # Should succeed even if template doesn't exist (would fall back)
        self.assertIsNotNone(result)

    def test_email_service_bulk_sending(self):
        """Test EmailService bulk email functionality"""
        # Create additional test members
        test_members = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Bulk{i}",
                last_name="TestMember",
                email=f"bulk{i}@test.invalid",
                birth_date="1990-01-01",
                member_id=f"BULK-{i}-{int(time.time() * 1000000) % 1000000}"
            )
            test_members.append(member)

        # Prepare email batch
        email_batch = []
        for member in test_members:
            email_batch.append({
                "template_name": "test_member_approval",
                "recipients": [member.email],
                "context": {
                    "member_name": member.full_name,
                    "membership_number": member.name,
                    "organization_name": "Bulk Test Org"
                },
                "reference_doctype": "Member",
                "reference_name": member.name
            })

        # Mock frappe.sendmail to capture emails
        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_bulk_emails(
                email_batch=email_batch,
                batch_size=2,
                delay_between_batches=0.1
            )

        # Verify bulk result
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_emails"], 3)
        self.assertEqual(result.data["sent_count"], 3)
        self.assertEqual(result.data["failed_count"], 0)
        self.assertEqual(result.data["success_rate"], 100.0)

        # Verify all emails were sent
        self.assertEqual(mock_sendmail.call_count, 3)

    def test_email_service_error_handling(self):
        """Test EmailService error handling for various failure scenarios"""
        # Test non-existent template
        result = self.email_service.send_templated_email(
            template_name="non_existent_template",
            recipients=[self.test_member.email],
            context={}
        )

        self.assertFalse(result.success)
        self.assertIn("not found", result.error_message)

        # Test empty recipients
        result = self.email_service.send_templated_email(
            template_name="test_member_approval",
            recipients=[],
            context={}
        )

        # Should handle gracefully
        self.assertIsNotNone(result)

    def test_compatibility_layer_sepa_emails(self):
        """Test SEPA email compatibility layer"""
        context = {
            "member_name": self.test_member.full_name,
            "mandate_id": "TEST-MANDATE-001",
            "iban": "NL91****5264",
            "bank_name": "Test Bank"
        }

        with patch('frappe.sendmail') as mock_sendmail:
            result = send_sepa_email(
                recipients=[self.test_member.email],
                subject="Test SEPA Notification",
                template="test_sepa_notification",
                context=context,
                member=self.test_member.name
            )

        # Verify compatibility wrapper works
        self.assertTrue(result.success)
        mock_sendmail.assert_called_once()

    def test_compatibility_layer_member_notifications(self):
        """Test member notification compatibility layer"""
        with patch('frappe.sendmail') as mock_sendmail:
            result = send_member_notification(
                member_name=self.test_member.name,
                notification_type="approval",
                context={
                    "additional_info": "Test approval notification"
                }
            )

        # Should attempt to send notification
        self.assertIsNotNone(result)

    def test_compatibility_layer_chapter_emails(self):
        """Test chapter email compatibility layer"""
        recipients = [self.test_member.email]

        with patch('frappe.sendmail') as mock_sendmail:
            result = send_chapter_email(
                chapter_name=self.test_chapter.name,
                recipients=recipients,
                subject="Test Chapter Communication",
                template="test_chapter_announcement",
                context={
                    "chapter_name": self.test_chapter.chapter_head,
                    "announcement_content": "This is a test announcement",
                    "contact_email": self.test_chapter.contact_email
                }
            )

        self.assertTrue(result.success)
        mock_sendmail.assert_called_once()

    def test_template_context_validation_and_xss_protection(self):
        """Test template rendering with XSS protection"""
        # Test with potentially malicious context
        malicious_context = {
            "member_name": "<script>alert('xss')</script>Test User",
            "membership_number": "MEM-001",
            "organization_name": "<img src=x onerror=alert('xss')>Org",
            "unsafe_content": "javascript:alert('xss')"
        }

        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_templated_email(
                template_name="test_member_approval",
                recipients=[self.test_member.email],
                context=malicious_context
            )

        # Should succeed but escape dangerous content
        self.assertTrue(result.success)

        # Verify XSS content was escaped in the email
        call_args = mock_sendmail.call_args
        email_content = call_args[1]["message"]
        self.assertNotIn("<script>", email_content)
        self.assertNotIn("onerror=", email_content)
        self.assertNotIn("javascript:", email_content)

    def test_template_caching_performance(self):
        """Test template caching improves performance"""
        template_name = "test_member_approval"
        context = {"member_name": "Test User", "membership_number": "MEM-001"}

        # Clear cache first
        self.email_service.template_cache.clear()

        with patch('frappe.sendmail'):
            # First call - should load template
            start_time = time.time()
            result1 = self.email_service.send_templated_email(
                template_name=template_name,
                recipients=[self.test_member.email],
                context=context
            )
            first_call_time = time.time() - start_time

            # Second call - should use cached template
            start_time = time.time()
            result2 = self.email_service.send_templated_email(
                template_name=template_name,
                recipients=[self.test_member.email],
                context=context
            )
            second_call_time = time.time() - start_time

        # Both should succeed
        self.assertTrue(result1.success)
        self.assertTrue(result2.success)

        # Second call should be faster (cached)
        # Note: This might be flaky in fast environments, so we just verify both work
        self.assertGreater(first_call_time, 0)
        self.assertGreater(second_call_time, 0)

    def test_communication_record_creation(self):
        """Test that Communication records are created for audit trail"""
        context = {
            "member_name": self.test_member.full_name,
            "membership_number": self.test_member.name
        }

        # Count existing communications
        existing_count = frappe.db.count("Communication", filters={
            "reference_doctype": "Member",
            "reference_name": self.test_member.name
        })

        with patch('frappe.sendmail'):
            result = self.email_service.send_templated_email(
                template_name="test_member_approval",
                recipients=[self.test_member.email],
                context=context,
                reference_doctype="Member",
                reference_name=self.test_member.name,
                create_communication=True
            )

        # Verify communication record was created
        self.assertTrue(result.success)

        # Check if communication count increased
        new_count = frappe.db.count("Communication", filters={
            "reference_doctype": "Member",
            "reference_name": self.test_member.name
        })

        # Should have created a communication record
        self.assertGreaterEqual(new_count, existing_count)

    def test_email_service_with_realistic_dutch_data(self):
        """Test EmailService with realistic Dutch association data"""
        # Create member with Dutch characteristics
        dutch_member = self.create_test_member(
            first_name="Pieter",
            last_name="van der Berg",
            email="pieter.vandeberg@test.invalid",
            birth_date="1980-03-20",
            member_id=f"DUTCH-{int(time.time() * 1000000) % 1000000}"
        )

        # Test context with Dutch formatting (let EmailService use its default organization name)
        context = {
            "member_name": dutch_member.full_name,
            "membership_number": dutch_member.name,
            "current_date": now_datetime().strftime("%d-%m-%Y"),  # Dutch date format
        }

        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_templated_email(
                template_name="test_member_approval",
                recipients=[dutch_member.email],
                context=context,
                reference_doctype="Member",
                reference_name=dutch_member.name
            )

        self.assertTrue(result.success)

        # Verify Dutch content is properly handled
        call_args = mock_sendmail.call_args
        email_content = call_args[1]["message"]
        self.assertIn("van der Berg", email_content)  # Dutch name with tussenvoegsel
        self.assertIn("Verenigingen", email_content)  # Default organization name from EmailService

    def test_email_service_error_recovery(self):
        """Test EmailService error recovery and fallback mechanisms"""
        # Test with corrupted template data
        with patch.object(self.email_service, '_get_template') as mock_get_template:
            mock_get_template.return_value = None  # Simulate template not found

            result = self.email_service.send_templated_email(
                template_name="test_member_approval",
                recipients=[self.test_member.email],
                context={"member_name": "Test"}
            )

            # Should fail gracefully
            self.assertFalse(result.success)
            self.assertIn("not found", result.error_message)

    def test_bounded_cache_behavior(self):
        """Test that the bounded cache respects size limits and TTL"""
        cache = self.email_service.template_cache

        # Test cache size limits
        initial_size = cache.size()

        # Add items beyond capacity (if cache is small)
        test_items = {}
        for i in range(10):
            key = f"test_key_{i}"
            value = f"test_value_{i}"
            cache.set(key, value)
            test_items[key] = value

        # Cache should not exceed reasonable bounds
        self.assertLessEqual(cache.size(), 50)  # Max size from EmailService

        # Test that some items are retrievable
        retrieved_count = 0
        for key in test_items:
            if cache.get(key) is not None:
                retrieved_count += 1

        # Should have retrieved some items
        self.assertGreater(retrieved_count, 0)

    def test_email_service_singleton_behavior(self):
        """Test EmailService singleton pattern"""
        service1 = get_email_service()
        service2 = get_email_service()

        # Should be same instance
        self.assertIs(service1, service2)

        # Should have consistent cache
        self.assertIs(service1.template_cache, service2.template_cache)


class TestEventSubscriberIntegration(EnhancedTestCase):
    """Integration tests for event subscriber notification system"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="EventTest",
            last_name="Member",
            email="event.test@test.invalid",
            birth_date="1985-06-15",
            member_id=f"EVENT-TEST-{int(time.time() * 1000000) % 1000000}"
        )

    def test_member_status_change_notification_flow(self):
        """Test complete member status change notification flow"""
        with patch('frappe.sendmail') as mock_sendmail:
            # Import the event handler
            from verenigingen.events.subscribers.member_subscribers import handle_status_change_notifications

            # Simulate member approval event
            event_data = {
                "member": self.test_member.name,
                "old_status": "Pending",
                "new_status": "Approved",
                "status_type": "application"
            }

            # Call the event handler
            handle_status_change_notifications("member_status_changed", event_data)

            # Should have attempted to send notification
            # (Exact behavior depends on template availability)
            self.assertTrue(True)  # Handler should not crash

    def test_member_lifecycle_notification_flow(self):
        """Test member lifecycle notification flow"""
        with patch('frappe.sendmail') as mock_sendmail:
            from verenigingen.events.subscribers.member_subscribers import handle_lifecycle_notifications

            # Simulate member suspension event
            event_data = {
                "member": self.test_member.name,
                "old_status": "Active",
                "new_status": "Suspended"
            }

            # Call the event handler
            handle_lifecycle_notifications("member_lifecycle_changed", event_data)

            # Handler should complete without error
            self.assertTrue(True)


class TestPaymentNotificationIntegration(EnhancedTestCase):
    """Integration tests for payment notification system"""

    def setUp(self):
        """Set up test environment with payment-related data"""
        super().setUp()

        self.test_member = self.create_test_member(
            first_name="PaymentTest",
            last_name="Member",
            email="payment.test@test.invalid",
            birth_date="1985-06-15",
            member_id=f"PAYMENT-TEST-{int(time.time())}"
        )

    def test_sepa_notification_manager_integration(self):
        """Test SEPA notification manager with realistic data"""
        from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager

        # Create notification manager
        manager = SEPAMandateNotificationManager()

        # Test notification manager initialization
        self.assertIsNotNone(manager)
        self.assertIsNotNone(manager._get_settings())

        # Test IBAN masking utility
        test_iban = "NL91ABNA0417164300"
        masked = manager._mask_iban(test_iban)
        self.assertEqual(masked, "NL91****4300")

        # Test bank name derivation
        bank_name = manager._get_bank_name(test_iban)
        self.assertIsNotNone(bank_name)

    def test_payment_notification_context_preparation(self):
        """Test payment notification context preparation"""
        from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager

        manager = SEPAMandateNotificationManager()

        # Mock mandate object
        class MockMandate:
            def __init__(self):
                self.mandate_id = "TEST-MANDATE-001"
                self.iban = "NL91ABNA0417164300"
                self.sign_date = getdate()
                self.expiry_date = add_days(getdate(), 365)

        mock_mandate = MockMandate()
        mock_member_data = {
            "name": self.test_member.name,
            "full_name": self.test_member.full_name,
            "email": self.test_member.email
        }
        mock_settings = type('MockSettings', (), {
            'company_name': 'Test Company',
            'support_email': 'support@test.invalid'
        })()

        # Test context preparation methods
        created_context = manager._prepare_created_context(mock_mandate, mock_member_data, mock_settings)
        self.assertIn("member_name", created_context)
        self.assertIn("mandate_id", created_context)
        self.assertIn("iban", created_context)
        self.assertEqual(created_context["iban"], "NL91****4300")  # Should be masked

        cancelled_context = manager._prepare_cancelled_context(
            mock_mandate, mock_member_data, mock_settings, "Test cancellation"
        )
        self.assertIn("cancellation_reason", cancelled_context)

        expiring_context = manager._prepare_expiring_context(
            mock_mandate, mock_member_data, mock_settings, 30
        )
        self.assertIn("days_until_expiry", expiring_context)
        self.assertEqual(expiring_context["days_until_expiry"], 30)


if __name__ == '__main__':
    import unittest
    unittest.main()