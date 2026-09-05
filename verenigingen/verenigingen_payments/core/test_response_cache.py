"""
Comprehensive Tests for ResponseCache

Tests cache hit/miss, TTL expiration, LRU eviction, invalidation,
statistics tracking, and integration with MollieBaseClient.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from verenigingen.verenigingen_payments.core.mollie_base_client import MollieBaseClient
from verenigingen.verenigingen_payments.core.response_cache import ResponseCache


class TestResponseCacheBasics(unittest.TestCase):
    """Test basic cache operations"""

    def setUp(self):
        """Create fresh cache for each test"""
        self.cache = ResponseCache(max_size=5, default_ttl_seconds=2)

    def test_cache_initialization(self):
        """Test cache initializes with correct parameters"""
        self.assertEqual(self.cache.max_size, 5)
        self.assertEqual(self.cache.default_ttl_seconds, 2)
        self.assertEqual(len(self.cache._cache), 0)
        self.assertEqual(self.cache._hits, 0)
        self.assertEqual(self.cache._misses, 0)
        self.assertEqual(self.cache._evictions, 0)

    def test_cache_key_generation_basic(self):
        """Test basic cache key generation"""
        key = self.cache._generate_cache_key("settlements", None, "Settlement")
        self.assertEqual(key, "settlements:none:Settlement")

    def test_cache_key_generation_with_params(self):
        """Test cache key generation with query parameters"""
        params = {"limit": 10, "offset": 0}
        key1 = self.cache._generate_cache_key("settlements", params, "Settlement")

        # Same params in different order should produce same key (sorted)
        params_reversed = {"offset": 0, "limit": 10}
        key2 = self.cache._generate_cache_key("settlements", params_reversed, "Settlement")

        self.assertEqual(key1, key2)
        self.assertIn("settlements:", key1)
        self.assertIn(":Settlement", key1)

    def test_cache_key_generation_different_params(self):
        """Test different params produce different keys"""
        params1 = {"limit": 10}
        params2 = {"limit": 20}

        key1 = self.cache._generate_cache_key("settlements", params1, "Settlement")
        key2 = self.cache._generate_cache_key("settlements", params2, "Settlement")

        self.assertNotEqual(key1, key2)

    def test_cache_miss_on_empty_cache(self):
        """Test cache miss when cache is empty"""
        result = self.cache.get("settlements", None, "Settlement")
        self.assertIsNone(result)
        self.assertEqual(self.cache._misses, 1)
        self.assertEqual(self.cache._hits, 0)

    def test_cache_set_and_get(self):
        """Test setting and retrieving cache entry"""
        test_data = {"id": "stl_123", "amount": "100.00"}
        self.cache.set("settlements/stl_123", None, "Settlement", test_data)

        result = self.cache.get("settlements/stl_123", None, "Settlement")
        self.assertEqual(result, test_data)
        self.assertEqual(self.cache._hits, 1)
        self.assertEqual(self.cache._misses, 0)

    def test_cache_hit_updates_lru(self):
        """Test cache hit moves entry to end (most recently used)"""
        self.cache.set("endpoint1", None, "Model", {"data": 1})
        self.cache.set("endpoint2", None, "Model", {"data": 2})
        self.cache.set("endpoint3", None, "Model", {"data": 3})

        # Access endpoint1 to make it most recently used
        self.cache.get("endpoint1", None, "Model")

        # Cache order should now be: endpoint2, endpoint3, endpoint1 (most recent)
        keys = list(self.cache._cache.keys())
        self.assertEqual(keys[-1], "endpoint1:none:Model")


class TestResponseCacheTTL(unittest.TestCase):
    """Test TTL expiration behavior"""

    def setUp(self):
        """Create cache with short TTL for testing"""
        self.cache = ResponseCache(max_size=10, default_ttl_seconds=1)

    def test_cache_expires_after_ttl(self):
        """Test cache entry expires after TTL"""
        test_data = {"id": "test"}
        self.cache.set("endpoint", None, "Model", test_data, ttl_seconds=1)

        # Should hit immediately
        result = self.cache.get("endpoint", None, "Model")
        self.assertEqual(result, test_data)
        self.assertEqual(self.cache._hits, 1)

        # Wait for expiration
        time.sleep(1.1)

        # Should miss after expiration
        result = self.cache.get("endpoint", None, "Model")
        self.assertIsNone(result)
        self.assertEqual(self.cache._misses, 1)

    def test_custom_ttl_overrides_default(self):
        """Test custom TTL overrides default TTL"""
        test_data = {"id": "test"}
        # Set with 3 second TTL (longer than default 1 second)
        self.cache.set("endpoint", None, "Model", test_data, ttl_seconds=3)

        # Wait longer than default TTL but less than custom TTL
        time.sleep(1.5)

        # Should still hit (custom TTL not expired)
        result = self.cache.get("endpoint", None, "Model")
        self.assertEqual(result, test_data)
        self.assertEqual(self.cache._hits, 1)

    def test_cleanup_expired_removes_expired_entries(self):
        """Test cleanup_expired removes only expired entries"""
        self.cache.set("endpoint1", None, "Model", {"data": 1}, ttl_seconds=1)
        self.cache.set("endpoint2", None, "Model", {"data": 2}, ttl_seconds=10)
        self.cache.set("endpoint3", None, "Model", {"data": 3}, ttl_seconds=1)

        # Wait for short TTL entries to expire
        time.sleep(1.1)

        removed_count = self.cache.cleanup_expired()

        # Should remove 2 expired entries
        self.assertEqual(removed_count, 2)
        # endpoint2 should still be in cache
        self.assertEqual(len(self.cache._cache), 1)
        result = self.cache.get("endpoint2", None, "Model")
        self.assertEqual(result, {"data": 2})


class TestResponseCacheLRU(unittest.TestCase):
    """Test LRU eviction behavior"""

    def setUp(self):
        """Create small cache to test eviction"""
        self.cache = ResponseCache(max_size=3, default_ttl_seconds=60)

    def test_lru_eviction_when_full(self):
        """Test LRU eviction when cache reaches max size"""
        self.cache.set("endpoint1", None, "Model", {"data": 1})
        self.cache.set("endpoint2", None, "Model", {"data": 2})
        self.cache.set("endpoint3", None, "Model", {"data": 3})

        # Cache is now full (3/3)
        self.assertEqual(len(self.cache._cache), 3)

        # Adding 4th entry should evict endpoint1 (least recently used)
        self.cache.set("endpoint4", None, "Model", {"data": 4})

        self.assertEqual(len(self.cache._cache), 3)
        self.assertEqual(self.cache._evictions, 1)

        # endpoint1 should be evicted
        result = self.cache.get("endpoint1", None, "Model")
        self.assertIsNone(result)

        # Others should still be present
        self.assertIsNotNone(self.cache.get("endpoint2", None, "Model"))
        self.assertIsNotNone(self.cache.get("endpoint3", None, "Model"))
        self.assertIsNotNone(self.cache.get("endpoint4", None, "Model"))

    def test_lru_eviction_respects_recent_access(self):
        """Test LRU evicts oldest accessed entry, not oldest added"""
        self.cache.set("endpoint1", None, "Model", {"data": 1})
        self.cache.set("endpoint2", None, "Model", {"data": 2})
        self.cache.set("endpoint3", None, "Model", {"data": 3})

        # Access endpoint1 to make it recently used
        self.cache.get("endpoint1", None, "Model")

        # Now LRU order is: endpoint2 (oldest), endpoint3, endpoint1 (newest)
        # Adding 4th entry should evict endpoint2
        self.cache.set("endpoint4", None, "Model", {"data": 4})

        # endpoint2 should be evicted
        result = self.cache.get("endpoint2", None, "Model")
        self.assertIsNone(result)

        # endpoint1 (recently accessed) should still be present
        result = self.cache.get("endpoint1", None, "Model")
        self.assertEqual(result, {"data": 1})

    def test_updating_existing_entry_no_eviction(self):
        """Test updating existing cache entry doesn't trigger eviction"""
        self.cache.set("endpoint1", None, "Model", {"data": 1})
        self.cache.set("endpoint2", None, "Model", {"data": 2})
        self.cache.set("endpoint3", None, "Model", {"data": 3})

        # Update existing entry (cache still 3/3)
        self.cache.set("endpoint2", None, "Model", {"data": 2, "updated": True})

        # No eviction should occur
        self.assertEqual(self.cache._evictions, 0)
        self.assertEqual(len(self.cache._cache), 3)

        # Updated entry should be present
        result = self.cache.get("endpoint2", None, "Model")
        self.assertEqual(result, {"data": 2, "updated": True})


class TestResponseCacheInvalidation(unittest.TestCase):
    """Test cache invalidation strategies"""

    def setUp(self):
        """Create cache with test data"""
        self.cache = ResponseCache(max_size=10, default_ttl_seconds=60)
        self.cache.set("settlements", None, "Settlement", {"data": "all"})
        self.cache.set("settlements", {"limit": 10}, "Settlement", {"data": "limited"})
        self.cache.set("settlements/stl_123", None, "Settlement", {"id": "stl_123"})
        self.cache.set("balances", None, "Balance", {"data": "balances"})

    def test_invalidate_all_entries_for_endpoint(self):
        """Test invalidating all entries for an endpoint"""
        # Should have 4 entries total
        self.assertEqual(len(self.cache._cache), 4)

        # Invalidate "settlements" entries (should remove 2: base and with params)
        # Note: "settlements/stl_123" is a different endpoint and won't be matched
        count = self.cache.invalidate("settlements")
        self.assertEqual(count, 2)

        # Should have 2 entries left (settlements/stl_123 and balances)
        self.assertEqual(len(self.cache._cache), 2)

        # Balances should still be cached
        result = self.cache.get("balances", None, "Balance")
        self.assertEqual(result, {"data": "balances"})

        # settlements/stl_123 should still be cached
        result = self.cache.get("settlements/stl_123", None, "Settlement")
        self.assertEqual(result, {"id": "stl_123"})

    def test_invalidate_specific_entry_with_params(self):
        """Test invalidating specific entry by endpoint and params"""
        # Invalidate only settlements with specific params
        count = self.cache.invalidate("settlements", params={"limit": 10})
        self.assertEqual(count, 1)

        # Should have 3 entries left
        self.assertEqual(len(self.cache._cache), 3)

        # Settlements without params should still be cached
        result = self.cache.get("settlements", None, "Settlement")
        self.assertEqual(result, {"data": "all"})

    def test_clear_removes_all_entries(self):
        """Test clear removes all cache entries"""
        self.assertEqual(len(self.cache._cache), 4)

        self.cache.clear()

        self.assertEqual(len(self.cache._cache), 0)
        # Stats should be reset
        stats = self.cache.get_stats()
        self.assertEqual(stats["size"], 0)


class TestResponseCacheStatistics(unittest.TestCase):
    """Test cache statistics tracking"""

    def setUp(self):
        """Create cache for statistics testing"""
        self.cache = ResponseCache(max_size=5, default_ttl_seconds=60)

    def test_statistics_initial_state(self):
        """Test statistics in initial state"""
        stats = self.cache.get_stats()

        self.assertEqual(stats["size"], 0)
        self.assertEqual(stats["max_size"], 5)
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)
        self.assertEqual(stats["evictions"], 0)
        self.assertEqual(stats["hit_rate_percent"], 0)
        self.assertEqual(stats["total_requests"], 0)

    def test_statistics_track_hits_and_misses(self):
        """Test statistics track hits and misses correctly"""
        self.cache.set("endpoint", None, "Model", {"data": "test"})

        # Miss
        self.cache.get("nonexistent", None, "Model")
        # Hit
        self.cache.get("endpoint", None, "Model")
        # Hit
        self.cache.get("endpoint", None, "Model")
        # Miss
        self.cache.get("another", None, "Model")

        stats = self.cache.get_stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 2)
        self.assertEqual(stats["total_requests"], 4)
        self.assertEqual(stats["hit_rate_percent"], 50.0)

    def test_statistics_track_evictions(self):
        """Test statistics track evictions correctly"""
        # Fill cache
        for i in range(5):
            self.cache.set(f"endpoint{i}", None, "Model", {"data": i})

        # Trigger evictions
        self.cache.set("endpoint5", None, "Model", {"data": 5})
        self.cache.set("endpoint6", None, "Model", {"data": 6})

        stats = self.cache.get_stats()
        self.assertEqual(stats["evictions"], 2)
        self.assertEqual(stats["size"], 5)  # Still at max

    def test_hit_rate_calculation(self):
        """Test hit rate percentage calculation"""
        self.cache.set("endpoint", None, "Model", {"data": "test"})

        # 7 hits, 3 misses = 70% hit rate
        for _ in range(7):
            self.cache.get("endpoint", None, "Model")
        for _ in range(3):
            self.cache.get("nonexistent", None, "Model")

        stats = self.cache.get_stats()
        self.assertEqual(stats["hit_rate_percent"], 70.0)


class TestMollieBaseClientCacheIntegration(unittest.TestCase):
    """Test cache integration with MollieBaseClient"""

    def setUp(self):
        """Create client with caching enabled"""
        import frappe
        from frappe.test_runner import make_test_records

        frappe.set_user("Administrator")

        # Create test Mollie Settings if needed. frappe.db.exists(dt, dt) is
        # unconditionally truthy for a Single (#889); check whether it has
        # actually been saved instead.
        if not frappe.db.get_singles_dict("Mollie Settings"):
            make_test_records("Mollie Settings")

        self.client = MollieBaseClient(
            use_backend_api=False, enable_cache=True, cache_max_size=10, cache_default_ttl=60
        )

    def test_client_initializes_with_cache_enabled(self):
        """Test client properly initializes cache"""
        self.assertTrue(self.client.enable_cache)
        self.assertIsNotNone(self.client.cache)
        self.assertEqual(self.client.cache.max_size, 10)
        self.assertEqual(self.client.cache.default_ttl_seconds, 60)

    def test_client_initializes_without_cache_when_disabled(self):
        """Test client without cache when disabled"""
        client = MollieBaseClient(use_backend_api=False, enable_cache=False)
        self.assertFalse(client.enable_cache)
        self.assertIsNone(client.cache)

    @patch.object(MollieBaseClient, "get")
    def test_get_cached_uses_cache_on_hit(self, mock_get):
        """Test get_cached uses cache on hit (no API call)"""
        # Prime cache
        mock_get.return_value = {"id": "test_123"}
        result1 = self.client.get_cached("endpoint", params=None)

        # Second call should hit cache (no additional API call)
        result2 = self.client.get_cached("endpoint", params=None)

        # get() should only be called once
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(result1, result2)

    @patch.object(MollieBaseClient, "get")
    def test_get_cached_makes_api_call_on_miss(self, mock_get):
        """Test get_cached makes API call on cache miss"""
        mock_get.return_value = {"id": "test_123"}

        result = self.client.get_cached("endpoint", params=None)

        mock_get.assert_called_once_with("endpoint", params=None, paginated=False)
        self.assertEqual(result, {"id": "test_123"})

    @patch.object(MollieBaseClient, "get")
    def test_get_cached_force_refresh_bypasses_cache(self, mock_get):
        """Test force_refresh bypasses cache and makes fresh API call"""
        # Prime cache
        mock_get.return_value = {"id": "cached"}
        self.client.get_cached("endpoint", params=None)

        # Force refresh should make new API call
        mock_get.return_value = {"id": "fresh"}
        result = self.client.get_cached("endpoint", params=None, force_refresh=True)

        # get() should be called twice (initial + force refresh)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(result, {"id": "fresh"})

    @patch.object(MollieBaseClient, "get")
    def test_get_cached_custom_ttl(self, mock_get):
        """Test get_cached respects custom TTL"""
        mock_get.return_value = {"id": "test"}

        # Set with 1 second TTL
        self.client.get_cached("endpoint", params=None, cache_ttl=1)

        # Wait for expiration
        time.sleep(1.1)

        # Should make fresh API call after TTL expiration
        self.client.get_cached("endpoint", params=None)

        # get() should be called twice (initial + after expiration)
        self.assertEqual(mock_get.call_count, 2)

    def test_invalidate_cache_removes_entries(self):
        """Test invalidate_cache removes specified entries"""
        with patch.object(self.client, "get") as mock_get:
            mock_get.return_value = {"id": "test"}

            # Prime cache with multiple entries
            self.client.get_cached("settlements", params=None)
            self.client.get_cached("settlements", params={"limit": 10})
            self.client.get_cached("balances", params=None)

            # Invalidate settlements
            count = self.client.invalidate_cache("settlements")

            # Should invalidate 2 entries
            self.assertEqual(count, 2)

    def test_clear_cache_removes_all_entries(self):
        """Test clear_cache removes all cached entries"""
        with patch.object(self.client, "get") as mock_get:
            mock_get.return_value = {"id": "test"}

            # Prime cache
            self.client.get_cached("endpoint1", params=None)
            self.client.get_cached("endpoint2", params=None)

            self.client.clear_cache()

            # Cache should be empty
            stats = self.client.cache.get_stats()
            self.assertEqual(stats["size"], 0)

    def test_get_metrics_includes_cache_stats(self):
        """Test get_metrics includes cache statistics"""
        with patch.object(self.client, "get") as mock_get:
            mock_get.return_value = {"id": "test"}

            # Generate some cache activity
            self.client.get_cached("endpoint", params=None)  # Miss, then set
            self.client.get_cached("endpoint", params=None)  # Hit

            # Get cache stats directly (not through full get_metrics which depends on http_client)
            cache_stats = self.client.cache.get_stats()

            # Should have correct stats
            self.assertIn("hits", cache_stats)
            self.assertIn("misses", cache_stats)
            self.assertIn("hit_rate_percent", cache_stats)
            self.assertEqual(cache_stats["hits"], 1)
            self.assertEqual(cache_stats["misses"], 1)

    def test_cleanup_expired_cache_removes_expired_entries(self):
        """Test cleanup_expired_cache removes expired entries"""
        with patch.object(self.client, "get") as mock_get:
            mock_get.return_value = {"id": "test"}

            # Set entries with different TTLs
            self.client.get_cached("endpoint1", cache_ttl=1)
            self.client.get_cached("endpoint2", cache_ttl=10)

            # Wait for short TTL to expire
            time.sleep(1.1)

            removed = self.client.cleanup_expired_cache()

            # Should remove 1 expired entry
            self.assertEqual(removed, 1)


class TestResponseCacheEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        """Create cache for edge case testing"""
        self.cache = ResponseCache(max_size=5, default_ttl_seconds=60)

    def test_cache_none_value(self):
        """Test caching None value (should be allowed)"""
        self.cache.set("endpoint", None, "Model", None)
        result = self.cache.get("endpoint", None, "Model")
        self.assertIsNone(result)
        self.assertEqual(self.cache._hits, 1)  # Should count as hit, not miss

    def test_cache_empty_dict(self):
        """Test caching empty dict"""
        self.cache.set("endpoint", None, "Model", {})
        result = self.cache.get("endpoint", None, "Model")
        self.assertEqual(result, {})
        self.assertEqual(self.cache._hits, 1)

    def test_cache_empty_list(self):
        """Test caching empty list"""
        self.cache.set("endpoint", None, "Model", [])
        result = self.cache.get("endpoint", None, "Model")
        self.assertEqual(result, [])
        self.assertEqual(self.cache._hits, 1)

    def test_cache_large_params_dict(self):
        """Test cache handles large params dict"""
        large_params = {f"param{i}": i for i in range(100)}
        key = self.cache._generate_cache_key("endpoint", large_params, "Model")

        # Key should be generated successfully
        self.assertIsInstance(key, str)
        self.assertIn("endpoint:", key)

    def test_cache_special_characters_in_endpoint(self):
        """Test cache handles special characters in endpoint"""
        endpoint = "settlements/stl_123/refunds?status=pending"
        self.cache.set(endpoint, None, "Model", {"data": "test"})
        result = self.cache.get(endpoint, None, "Model")
        self.assertEqual(result, {"data": "test"})

    def test_invalidate_nonexistent_endpoint(self):
        """Test invalidating nonexistent endpoint returns 0"""
        count = self.cache.invalidate("nonexistent_endpoint")
        self.assertEqual(count, 0)

    def test_get_stats_empty_cache_no_division_error(self):
        """Test get_stats handles empty cache (no division by zero)"""
        stats = self.cache.get_stats()
        self.assertEqual(stats["hit_rate_percent"], 0)
        self.assertEqual(stats["total_requests"], 0)


if __name__ == "__main__":
    unittest.main()
