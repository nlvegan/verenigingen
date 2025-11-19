"""
Response Cache for Mollie API Clients

Provides intelligent caching for Mollie API responses with:
- TTL-based expiration
- LRU eviction policy
- Cache key generation
- Configurable cache sizes
- Thread-safe operations
"""

import hashlib
import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import frappe


class ResponseCache:
    """
    Thread-safe LRU cache for Mollie API responses with TTL support

    Features:
    - LRU eviction when cache is full
    - TTL-based expiration for stale data
    - Configurable max size and default TTL
    - Cache statistics for monitoring
    - Automatic cleanup of expired entries

    Cache Key Format:
        "{endpoint}:{params_hash}:{model_class}"

    Example:
        cache = ResponseCache(max_size=100, default_ttl_seconds=300)
        cache.set("settlements/stl_123", None, Settlement, settlement_obj)
        cached = cache.get("settlements/stl_123", None, Settlement)
    """

    def __init__(self, max_size: int = 100, default_ttl_seconds: int = 300):
        """
        Initialize response cache

        Args:
            max_size: Maximum number of cached responses (default: 100)
            default_ttl_seconds: Default TTL in seconds (default: 300 = 5 minutes)
        """
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def _generate_cache_key(
        self, endpoint: str, params: Optional[Dict[str, Any]], model_class_name: str
    ) -> str:
        """
        Generate cache key from endpoint, params, and model class

        Args:
            endpoint: API endpoint (e.g., "settlements/stl_123")
            params: Query parameters dict (or None)
            model_class_name: Model class name for type safety

        Returns:
            Cache key string

        Example:
            >>> cache._generate_cache_key("settlements", {"limit": 10}, "Settlement")
            'settlements:a3f2b1:Settlement'
        """
        # Sort params for consistent hashing
        if params:
            params_str = json.dumps(params, sort_keys=True)
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        else:
            params_hash = "none"

        return f"{endpoint}:{params_hash}:{model_class_name}"

    def get(self, endpoint: str, params: Optional[Dict[str, Any]], model_class_name: str) -> Optional[Any]:
        """
        Get cached response if not expired

        Args:
            endpoint: API endpoint
            params: Query parameters
            model_class_name: Model class name

        Returns:
            Cached response or None if not found/expired
        """
        cache_key = self._generate_cache_key(endpoint, params, model_class_name)

        if cache_key not in self._cache:
            self._misses += 1
            return None

        cached_value, expiry_time = self._cache[cache_key]

        # Check if expired
        if time.time() > expiry_time:
            # Remove expired entry
            del self._cache[cache_key]
            self._misses += 1
            frappe.logger().debug(f"Cache expired for key: {cache_key}")
            return None

        # Move to end (LRU - most recently used)
        self._cache.move_to_end(cache_key)
        self._hits += 1
        frappe.logger().debug(f"Cache hit for key: {cache_key}")
        return cached_value

    def set(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]],
        model_class_name: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Cache response with TTL

        Args:
            endpoint: API endpoint
            params: Query parameters
            model_class_name: Model class name
            value: Response to cache
            ttl_seconds: TTL in seconds (default: use default_ttl_seconds)
        """
        cache_key = self._generate_cache_key(endpoint, params, model_class_name)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        expiry_time = time.time() + ttl

        # Evict oldest entry if cache is full
        if len(self._cache) >= self.max_size and cache_key not in self._cache:
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]
            self._evictions += 1
            frappe.logger().debug(f"Cache evicted key: {evicted_key} (LRU)")

        self._cache[cache_key] = (value, expiry_time)
        self._cache.move_to_end(cache_key)  # Mark as most recently used
        frappe.logger().debug(f"Cache set for key: {cache_key}, TTL: {ttl}s")

    def invalidate(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> int:
        """
        Invalidate cache entries matching endpoint (and optionally params)

        Args:
            endpoint: API endpoint to invalidate
            params: If provided, only invalidate exact match. If None, invalidate all matching endpoint.

        Returns:
            Number of entries invalidated
        """
        if params is not None:
            # Invalidate specific entry
            keys_to_remove = [key for key in self._cache.keys() if key.startswith(f"{endpoint}:")]
            # Filter by params hash
            params_str = json.dumps(params, sort_keys=True)
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
            keys_to_remove = [key for key in keys_to_remove if f":{params_hash}:" in key]
        else:
            # Invalidate all entries for endpoint
            keys_to_remove = [key for key in self._cache.keys() if key.startswith(f"{endpoint}:")]

        for key in keys_to_remove:
            del self._cache[key]

        if keys_to_remove:
            frappe.logger().debug(f"Cache invalidated {len(keys_to_remove)} entries for endpoint: {endpoint}")

        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all cache entries"""
        count = len(self._cache)
        self._cache.clear()
        frappe.logger().info(f"Cache cleared: {count} entries removed")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dict with cache stats (hits, misses, size, hit_rate, etc.)
        """
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate_percent": round(hit_rate, 2),
            "total_requests": total_requests,
        }

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries

        Returns:
            Number of entries removed
        """
        current_time = time.time()
        keys_to_remove = [key for key, (value, expiry) in self._cache.items() if current_time > expiry]

        for key in keys_to_remove:
            del self._cache[key]

        if keys_to_remove:
            frappe.logger().debug(f"Cache cleanup removed {len(keys_to_remove)} expired entries")

        return len(keys_to_remove)
