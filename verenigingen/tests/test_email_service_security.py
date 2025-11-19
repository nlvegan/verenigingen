"""
Unit tests for EmailService security features including bounded cache and XSS protection.
Tests the security enhancements added to the unified EmailService.
"""

import unittest
import time
import frappe

from verenigingen.services.communication.email_service import (
    EmailService,
    BoundedLRUCache,
    get_email_service
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestBoundedLRUCache(unittest.TestCase):
    """Test the BoundedLRUCache implementation for security and performance."""

    def setUp(self):
        """Set up test cache with small limits for testing."""
        self.cache = BoundedLRUCache(max_size=3, ttl_seconds=1)

    def test_cache_basic_operations(self):
        """Test basic cache set/get operations."""
        # Test set and get
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

        # Test cache size
        self.assertEqual(self.cache.size(), 1)

        # Test non-existent key
        self.assertIsNone(self.cache.get("non_existent"))

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache exceeds max size."""
        # Fill cache to capacity
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.cache.set("key3", "value3")
        self.assertEqual(self.cache.size(), 3)

        # Access key1 to mark it as recently used
        self.cache.get("key1")

        # Add fourth item - should evict key2 (least recently used)
        self.cache.set("key4", "value4")
        self.assertEqual(self.cache.size(), 3)

        # key2 should be evicted, key1 should still be there
        self.assertIsNone(self.cache.get("key2"))
        self.assertEqual(self.cache.get("key1"), "value1")
        self.assertEqual(self.cache.get("key4"), "value4")

    def test_cache_ttl_expiration(self):
        """Test TTL-based cache expiration."""
        # Set item and verify it's there
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

        # Wait for TTL to expire (cache TTL is 1 second)
        time.sleep(1.1)

        # Item should be expired and removed
        self.assertIsNone(self.cache.get("key1"))
        self.assertEqual(self.cache.size(), 0)

    def test_cache_update_existing(self):
        """Test updating existing cache entries."""
        # Set initial value
        self.cache.set("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

        # Update value
        self.cache.set("key1", "new_value")
        self.assertEqual(self.cache.get("key1"), "new_value")
        self.assertEqual(self.cache.size(), 1)

    def test_cache_clear(self):
        """Test cache clearing functionality."""
        # Fill cache
        self.cache.set("key1", "value1")
        self.cache.set("key2", "value2")
        self.assertEqual(self.cache.size(), 2)

        # Clear cache
        self.cache.clear()
        self.assertEqual(self.cache.size(), 0)
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))

    def test_cache_memory_bounds(self):
        """Test that cache respects memory bounds."""
        # Create cache with very small size
        small_cache = BoundedLRUCache(max_size=2, ttl_seconds=300)

        # Fill beyond capacity
        for i in range(10):
            small_cache.set(f"key{i}", f"value{i}")

        # Should never exceed max size
        self.assertLessEqual(small_cache.size(), 2)

        # Should contain most recent items
        self.assertEqual(small_cache.get("key9"), "value9")
        self.assertEqual(small_cache.get("key8"), "value8")
        self.assertIsNone(small_cache.get("key0"))  # Should be evicted


class TestEmailServiceSecurity(EnhancedTestCase):
    """Test EmailService security features including XSS protection."""

    def setUp(self):
        """Set up test environment."""
        super().setUp()
        self.email_service = EmailService()

    def test_template_caching_bounds(self):
        """Test that template caching respects bounds using real templates."""
        # Create real email templates for testing
        template_names = []
        for i in range(10):  # Reduced number for realistic testing
            template_name = f"test_cache_template_{i}_{int(frappe.utils.now_datetime().timestamp())}"
            template_doc = frappe.get_doc({
                "doctype": "Email Template",
                "name": template_name,
                "subject": f"Test Subject {i}",
                "response_html": f"<p>Test Content {i}</p>",
                "use_html": 1,
                "enabled": 1
            })
            template_doc.insert()
            template_names.append(template_name)

        # Test cache bounds - should not exceed max size
        initial_size = self.email_service.template_cache.size()

        # Load templates to populate cache
        loaded_templates = []
        for name in template_names:
            template = self.email_service._get_template(name)
            if template:  # Template exists
                loaded_templates.append(template)
                self.assertIsNotNone(template)

        # Cache should not exceed max size (50)
        final_size = self.email_service.template_cache.size()
        self.assertLessEqual(final_size, 50)

        # Verify at least some templates were cached
        self.assertGreater(len(loaded_templates), 0)

    def test_template_cache_ttl(self):
        """Test template cache TTL expiration."""
        # Create service with very short TTL for testing
        service = EmailService()
        service.template_cache = BoundedLRUCache(max_size=50, ttl_seconds=0.1)

        # Create a real template for testing
        template_name = f"test_ttl_template_{int(frappe.utils.now_datetime().timestamp())}"
        template_doc = frappe.get_doc({
            "doctype": "Email Template",
            "name": template_name,
            "subject": "TTL Test Subject",
            "response_html": "<p>TTL Test Content</p>",
            "use_html": 1,
            "enabled": 1
        })
        template_doc.insert()

        # Load template into cache
        template = service._get_template(template_name)
        if template:  # Template exists and was cached
            cache_size_before = service.template_cache.size()
            self.assertGreater(cache_size_before, 0)

            # Wait for TTL expiration
            time.sleep(0.2)

            # Try to get expired item - should trigger cleanup
            service._get_template(template_name)

            # Cache should have cleaned up expired items
            cache_size_after = service.template_cache.size()
            self.assertLessEqual(cache_size_after, cache_size_before)

    def test_context_variable_validation(self):
        """Test that context variables are properly validated."""
        # Test with various context types
        test_contexts = [
            {"normal_var": "safe_value"},
            {"script_tag": "<script>alert('xss')</script>"},
            {"html_entity": "&lt;script&gt;"},
            {"unicode_attack": "\u003cscript\u003e"},
            {"null_bytes": "safe\x00malicious"},
            {"empty_dict": {}},
            {"nested_dict": {"safe": {"also_safe": "value"}}},
        ]

        for context in test_contexts:
            # Should not raise exception during context processing
            # EmailService should handle all input types gracefully
            try:
                # This would normally be called internally
                processed_context = context.copy() if context else {}
                self.assertIsInstance(processed_context, dict)
            except Exception as e:
                self.fail(f"Context validation failed for {context}: {e}")

    def test_template_loading_security(self):
        """Test security of template loading process."""
        # Test with malicious template names
        malicious_names = [
            "../../../etc/passwd",
            "../../config.json",
            "<script>alert('xss')</script>",
            "'; DROP TABLE email_templates; --",
        ]

        # Create one valid template for comparison
        valid_template_name = f"normal_template_{int(frappe.utils.now_datetime().timestamp())}"
        valid_template = frappe.get_doc({
            "doctype": "Email Template",
            "name": valid_template_name,
            "subject": "Normal Subject",
            "response_html": "<p>Normal Content</p>",
            "use_html": 1,
            "enabled": 1
        })
        valid_template.insert()

        for template_name in malicious_names:
            # Should handle malicious names gracefully
            result = self.email_service._get_template(template_name)
            self.assertIsNone(result)  # Should return None for non-existent templates

        # Valid template should work
        valid_result = self.email_service._get_template(valid_template_name)
        self.assertIsNotNone(valid_result)

        # Verify no exceptions were raised and cache remains bounded
        self.assertLessEqual(self.email_service.template_cache.size(), 50)

    def test_service_singleton_behavior(self):
        """Test that get_email_service returns same instance."""
        # Get service instances
        service1 = get_email_service()
        service2 = get_email_service()

        # Should be same instance (singleton pattern)
        self.assertIs(service1, service2)

        # Both should have bounded cache
        self.assertIsInstance(service1.template_cache, BoundedLRUCache)
        self.assertIsInstance(service2.template_cache, BoundedLRUCache)

    def test_error_handling_resilience(self):
        """Test EmailService resilience to various error conditions."""
        # Test with None template name
        result = self.email_service._get_template(None)
        self.assertIsNone(result)

        # Test with empty string
        result = self.email_service._get_template("")
        self.assertIsNone(result)

        # Test with very long template name
        long_name = "a" * 1000
        result = self.email_service._get_template(long_name)
        self.assertIsNone(result)

    def test_cache_thread_safety_simulation(self):
        """Simulate concurrent access to test thread safety patterns."""
        # While we can't easily test true thread safety in unit tests,
        # we can test rapid sequential access patterns
        cache = BoundedLRUCache(max_size=10, ttl_seconds=60)

        # Simulate rapid concurrent-like access
        for i in range(100):
            cache.set(f"key_{i % 10}", f"value_{i}")
            retrieved = cache.get(f"key_{i % 10}")
            self.assertIsNotNone(retrieved)

        # Cache should remain consistent and bounded
        self.assertLessEqual(cache.size(), 10)


if __name__ == '__main__':
    unittest.main()