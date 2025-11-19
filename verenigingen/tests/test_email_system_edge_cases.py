"""
Email System Edge Case Tests
===========================

Tests edge cases, error conditions, and boundary scenarios for the email
notification system. Focuses on realistic failure scenarios and recovery.

Covers:
- Missing templates and invalid contexts
- Network failures and email delivery issues
- Malformed data and security edge cases
- Performance limits and resource constraints
- Database connectivity issues
- Template rendering failures
"""

import json
import time
from unittest.mock import patch, MagicMock, Mock

import frappe
from frappe.exceptions import ValidationError, DoesNotExistError

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.communication.email_service import get_email_service, BoundedLRUCache
from verenigingen.services.communication.compatibility import (
    send_sepa_email,
    send_member_notification,
    get_segment_recipients,
)


class TestEmailSystemEdgeCases(EnhancedTestCase):
    """Edge case tests for email system"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.email_service = get_email_service()

        self.test_member = self.create_test_member(
            first_name="EdgeCase",
            last_name="TestMember",
            email="edgecase@test.invalid",
            birth_date="1985-06-15"
        )

    def test_missing_template_handling(self):
        """Test handling of missing email templates"""
        result = self.email_service.send_templated_email(
            template_name="completely_non_existent_template",
            recipients=[self.test_member.email],
            context={"test": "data"}
        )

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"].lower())
        self.assertEqual(result["service_name"], "EmailService")
        self.assertEqual(result["operation"], "send_templated_email")

    def test_empty_and_invalid_recipients(self):
        """Test handling of empty and invalid recipient lists"""
        # Test empty recipients list
        result = self.email_service.send_templated_email(
            template_name="test_template",
            recipients=[],
            context={"test": "data"}
        )

        # Should handle gracefully
        self.assertIsInstance(result, dict)

        # Test None recipients
        result = self.email_service.send_templated_email(
            template_name="test_template",
            recipients=None,
            context={"test": "data"}
        )

        self.assertIsInstance(result, dict)

        # Test invalid email addresses
        result = self.email_service.send_templated_email(
            template_name="test_template",
            recipients=["invalid-email", "also@invalid@email.com"],
            context={"test": "data"}
        )

        # Should still process (validation happens at sendmail level)
        self.assertIsInstance(result, dict)

    def test_malformed_context_data(self):
        """Test handling of malformed context data"""
        # Create a simple test template
        if not frappe.db.exists("Email Template", "edge_case_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "edge_case_template",
                "subject": "Test {{ test_var|e }}",
                "response_html": "<p>Content: {{ content|e }}</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        malformed_contexts = [
            None,  # None context
            "not_a_dict",  # String instead of dict
            {"circular_ref": None},  # Will be made circular
            {"very_deep": {"nested": {"data": {"structure": {"deep": "value"}}}}},  # Very nested
            {"unicode_test": "Test avec des caractères spéciaux éàùî"},  # Unicode
            {"large_string": "x" * 10000},  # Very large string
        ]

        # Make one context circular
        malformed_contexts[2]["circular_ref"] = malformed_contexts[2]

        for i, context in enumerate(malformed_contexts):
            with self.subTest(context_type=f"context_{i}"):
                try:
                    result = self.email_service.send_templated_email(
                        template_name="edge_case_template",
                        recipients=[self.test_member.email],
                        context=context
                    )
                    # Should return a result dict even for malformed context
                    self.assertIsInstance(result, dict)
                    self.assertIn("success", result)
                except Exception as e:
                    # Should not raise unhandled exceptions
                    self.fail(f"Unhandled exception for context {i}: {e}")

    def test_template_rendering_failures(self):
        """Test handling of template rendering failures"""
        # Create template with invalid syntax
        if not frappe.db.exists("Email Template", "broken_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "broken_template",
                "subject": "Test {{ unclosed_tag",  # Invalid template syntax
                "response_html": "<p>{{ undefined_variable.missing_method() }}</p>",  # Will cause error
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        result = self.email_service.send_templated_email(
            template_name="broken_template",
            recipients=[self.test_member.email],
            context={"test": "data"}
        )

        # Should handle template rendering errors gracefully
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_frappe_sendmail_failures(self):
        """Test handling of frappe.sendmail failures"""
        # Create valid template
        if not frappe.db.exists("Email Template", "sendmail_test_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "sendmail_test_template",
                "subject": "Test Email",
                "response_html": "<p>Test content</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        # Mock frappe.sendmail to raise various exceptions
        exceptions_to_test = [
            Exception("Network error"),
            ConnectionError("SMTP connection failed"),
            TimeoutError("Email sending timeout"),
            frappe.ValidationError("Invalid recipient"),
        ]

        for exception in exceptions_to_test:
            with self.subTest(exception=type(exception).__name__):
                with patch('frappe.sendmail', side_effect=exception):
                    result = self.email_service.send_templated_email(
                        template_name="sendmail_test_template",
                        recipients=[self.test_member.email],
                        context={"test": "data"}
                    )

                    # Should handle sendmail failures gracefully
                    self.assertIsInstance(result, dict)
                    self.assertIn("success", result)

    def test_database_connectivity_issues(self):
        """Test handling of database connectivity issues"""
        # Mock database operations to fail
        with patch('frappe.db.exists', side_effect=Exception("Database connection lost")):
            result = self.email_service._get_template("any_template")
            self.assertIsNone(result)

        with patch('frappe.get_doc', side_effect=frappe.DoesNotExistError("Database error")):
            result = self.email_service._get_template("any_template")
            self.assertIsNone(result)

    def test_communication_record_creation_failures(self):
        """Test handling of Communication record creation failures"""
        # Create valid template
        if not frappe.db.exists("Email Template", "comm_test_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "comm_test_template",
                "subject": "Test Email",
                "response_html": "<p>Test content</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        # Mock Communication creation to fail
        with patch('verenigingen.utils.secure_operations.secure_document_operation') as mock_secure_op:
            mock_secure_op.return_value = type('Result', (), {
                'success': False,
                'errors': ['Permission denied'],
                'data': None
            })()

            with patch('frappe.sendmail'):
                result = self.email_service.send_templated_email(
                    template_name="comm_test_template",
                    recipients=[self.test_member.email],
                    context={"test": "data"},
                    create_communication=True
                )

            # Should still succeed even if Communication creation fails
            self.assertTrue(result["success"])

    def test_cache_memory_pressure(self):
        """Test cache behavior under memory pressure"""
        # Create cache with very small size for testing
        small_cache = BoundedLRUCache(max_size=3, ttl_seconds=300)

        # Fill cache beyond capacity
        for i in range(10):
            small_cache.set(f"key_{i}", f"value_{i}")

        # Should never exceed max size
        self.assertLessEqual(small_cache.size(), 3)

        # Most recent items should be preserved
        self.assertIsNotNone(small_cache.get("key_9"))
        self.assertIsNotNone(small_cache.get("key_8"))
        self.assertIsNotNone(small_cache.get("key_7"))

        # Oldest items should be evicted
        self.assertIsNone(small_cache.get("key_0"))
        self.assertIsNone(small_cache.get("key_1"))

    def test_cache_ttl_edge_cases(self):
        """Test cache TTL edge cases"""
        # Create cache with very short TTL
        short_ttl_cache = BoundedLRUCache(max_size=10, ttl_seconds=0.1)

        # Set item
        short_ttl_cache.set("test_key", "test_value")
        self.assertEqual(short_ttl_cache.get("test_key"), "test_value")

        # Wait for expiration
        time.sleep(0.2)

        # Should be expired
        self.assertIsNone(short_ttl_cache.get("test_key"))

        # Cache size should be reduced
        self.assertEqual(short_ttl_cache.size(), 0)

    def test_bulk_email_failure_scenarios(self):
        """Test bulk email sending with various failure scenarios"""
        # Create template
        if not frappe.db.exists("Email Template", "bulk_test_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "bulk_test_template",
                "subject": "Bulk Test {{ item_id|e }}",
                "response_html": "<p>Bulk item {{ item_id|e }}</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        # Create mixed batch with some invalid configurations
        email_batch = [
            {
                "template_name": "bulk_test_template",
                "recipients": [self.test_member.email],
                "context": {"item_id": "1"}
            },
            {
                "template_name": "non_existent_template",
                "recipients": [self.test_member.email],
                "context": {"item_id": "2"}
            },
            {
                "template_name": "bulk_test_template",
                "recipients": ["invalid@email"],
                "context": {"item_id": "3"}
            },
            {
                "template_name": "bulk_test_template",
                "recipients": [self.test_member.email],
                "context": None  # Invalid context
            }
        ]

        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_bulk_emails(
                email_batch=email_batch,
                batch_size=2,
                delay_between_batches=0.01
            )

        # Should complete and provide statistics
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_emails"], 4)
        self.assertGreaterEqual(result["data"]["failed_count"], 1)  # At least one should fail
        self.assertIn("results", result["data"])

    def test_compatibility_layer_error_handling(self):
        """Test compatibility layer error handling"""
        # Test SEPA email with member that doesn't exist
        result = send_sepa_email(
            recipients=["test@example.com"],
            subject="Test",
            template="non_existent_template",
            context={},
            member="NON_EXISTENT_MEMBER"
        )

        self.assertFalse(result["success"])
        self.assertIn("error", result)

        # Test member notification with invalid member
        result = send_member_notification(
            member_name="NON_EXISTENT_MEMBER",
            notification_type="approval",
            context={}
        )

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_segment_recipients_edge_cases(self):
        """Test get_segment_recipients with edge cases"""
        # Test with non-existent chapter
        recipients = get_segment_recipients("all", "NON_EXISTENT_CHAPTER")
        self.assertIsInstance(recipients, list)

        # Test with invalid segment
        recipients = get_segment_recipients("invalid_segment", None)
        self.assertIsInstance(recipients, list)

        # Test with board segment when no board members exist
        recipients = get_segment_recipients("board", None)
        self.assertIsInstance(recipients, list)

    def test_large_template_handling(self):
        """Test handling of very large templates"""
        # Create template with large content
        large_content = "<p>" + ("Large content line.<br>" * 1000) + "</p>"

        if not frappe.db.exists("Email Template", "large_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "large_template",
                "subject": "Large Template Test",
                "response_html": large_content,
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        with patch('frappe.sendmail') as mock_sendmail:
            result = self.email_service.send_templated_email(
                template_name="large_template",
                recipients=[self.test_member.email],
                context={}
            )

        # Should handle large templates
        self.assertTrue(result["success"])

    def test_concurrent_cache_access_simulation(self):
        """Simulate concurrent cache access patterns"""
        cache = BoundedLRUCache(max_size=10, ttl_seconds=60)

        # Simulate rapid concurrent-like access
        for iteration in range(100):
            # Simulate multiple "threads" accessing cache
            for thread_id in range(5):
                key = f"thread_{thread_id}_item_{iteration % 10}"
                value = f"value_{thread_id}_{iteration}"

                # Set and immediately get
                cache.set(key, value)
                retrieved = cache.get(key)

                # Should get back what we just set
                if retrieved is not None:  # Might be evicted immediately in small cache
                    self.assertEqual(retrieved, value)

        # Cache should remain consistent and bounded
        self.assertLessEqual(cache.size(), 10)

    def test_xss_protection_comprehensive(self):
        """Comprehensive XSS protection testing"""
        if not frappe.db.exists("Email Template", "xss_test_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "xss_test_template",
                "subject": "XSS Test {{ user_input|e }}",
                "response_html": "<p>User data: {{ user_input|e }}</p><p>Safe data: {{ safe_data|e }}</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        xss_payloads = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert('xss')",
            "<iframe src=javascript:alert('xss')></iframe>",
            "<svg onload=alert('xss')>",
            "';alert('xss');//",
            "<script>document.cookie='stolen'</script>",
            "<<SCRIPT>alert('xss')</SCRIPT>",
            "<script>/*malicious comment*/alert('xss')</script>",
        ]

        for payload in xss_payloads:
            with self.subTest(payload=payload[:20]):
                context = {
                    "user_input": payload,
                    "safe_data": "This is safe data"
                }

                with patch('frappe.sendmail') as mock_sendmail:
                    result = self.email_service.send_templated_email(
                        template_name="xss_test_template",
                        recipients=[self.test_member.email],
                        context=context
                    )

                if result["success"] and mock_sendmail.called:
                    email_content = mock_sendmail.call_args[1]["message"]

                    # Verify dangerous content is properly escaped (not executed)
                    # Check for unescaped dangerous tags - these should not exist
                    self.assertNotIn("<script", email_content.lower())
                    # Check that content is escaped (contains HTML entities instead of raw dangerous content)
                    if "javascript:" in payload.lower():
                        # Should be escaped as &#39; or similar
                        self.assertTrue("&#39;" in email_content or "&lt;" in email_content,
                                      "JavaScript should be HTML-escaped")
                    if "onerror=" in payload.lower():
                        # Should be escaped
                        self.assertTrue("&#39;" in email_content or "&lt;" in email_content,
                                      "Event handlers should be HTML-escaped")

    def test_resource_exhaustion_protection(self):
        """Test protection against resource exhaustion"""
        # Test with very large recipient list
        large_recipient_list = [f"test{i}@example.com" for i in range(1000)]

        result = self.email_service.send_templated_email(
            template_name="test_template",
            recipients=large_recipient_list,
            context={"test": "data"}
        )

        # Should handle large recipient lists gracefully
        self.assertIsInstance(result, dict)

        # Test with very large context
        large_context = {}
        for i in range(1000):
            large_context[f"key_{i}"] = f"value_{i}" * 100

        result = self.email_service.send_templated_email(
            template_name="test_template",
            recipients=[self.test_member.email],
            context=large_context
        )

        # Should handle large contexts gracefully
        self.assertIsInstance(result, dict)

    def test_unicode_and_encoding_edge_cases(self):
        """Test Unicode and encoding edge cases"""
        if not frappe.db.exists("Email Template", "unicode_test_template"):
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": "unicode_test_template",
                "subject": "Unicode Test: {{ unicode_text|e }}",
                "response_html": "<p>Content: {{ unicode_text|e }}</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()

        unicode_test_cases = [
            "Standard ASCII text",
            "Café with accents éàüöß",
            "Chinese characters: 你好世界",
            "Arabic text: مرحبا بالعالم",
            "Emoji: 🎉🚀💻🌟",
            "Mixed: Hello 世界 🌍 café",
            "Special chars: ñáéíóú",
            "Currency: €£$¥₹",
        ]

        for unicode_text in unicode_test_cases:
            with self.subTest(text=unicode_text[:20]):
                with patch('frappe.sendmail'):
                    result = self.email_service.send_templated_email(
                        template_name="unicode_test_template",
                        recipients=[self.test_member.email],
                        context={"unicode_text": unicode_text}
                    )

                # Should handle Unicode text properly
                self.assertIsInstance(result, dict)


if __name__ == '__main__':
    import unittest
    unittest.main()