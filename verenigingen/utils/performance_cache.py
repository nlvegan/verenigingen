#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Caching Utilities for Verenigingen
==============================================

Intelligent caching layer to complement the N+1 query optimizations.
Provides Redis-based caching with automatic invalidation for frequently
accessed data that changes infrequently.

Key Features:
- Smart cache invalidation based on document events
- TTL-based expiration with business logic considerations
- Batch cache operations for efficiency
- Cache warming for critical data
- Performance monitoring and metrics

Architecture:
- Layer 1: Redis cache for hot data (chapters, permissions, settings)
- Layer 2: Application-level caching for computed values
- Layer 3: Database query result caching with invalidation hooks

Usage:
    from verenigingen.utils.performance_cache import PerformanceCache

    cache = PerformanceCache()

    # Cache chapter access data
    chapters = cache.get_or_set(
        key=f"user_chapters:{user_email}",
        getter=lambda: get_user_accessible_chapters(user_email),
        ttl=900  # 15 minutes
    )
"""

import json
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe.utils import cstr


class PerformanceCache:
    """High-performance caching layer with intelligent invalidation"""

    # Cache prefixes for organization
    PREFIXES = {
        "chapter_access": "ch_access",
        "member_info": "mem_info",
        "report_data": "rpt_data",
        "permissions": "perms",
        "settings": "settings",
        "lookup": "lookup",
    }

    # Default TTL values (seconds)
    DEFAULT_TTLS = {
        "chapter_access": 900,  # 15 minutes - user chapters change rarely
        "member_info": 600,  # 10 minutes - member data changes occasionally
        "report_data": 300,  # 5 minutes - reports need fresher data
        "permissions": 1800,  # 30 minutes - permissions change rarely
        "settings": 3600,  # 1 hour - settings change very rarely
        "lookup": 1800,  # 30 minutes - lookup data is relatively stable
    }

    def __init__(self, enabled: bool = None):
        """Initialize cache with Redis connection"""
        self.enabled = enabled if enabled is not None else self._is_caching_enabled()
        self.cache = frappe.cache() if self.enabled else None

    def _is_caching_enabled(self) -> bool:
        """Check if caching is enabled for the site"""
        try:
            # Check if Redis is available and caching is enabled
            cache_test = frappe.cache()
            cache_test.set_value("cache_test", "working", 1)
            result = cache_test.get_value("cache_test")
            cache_test.delete_value("cache_test")
            return result == "working"
        except Exception:
            return False

    def _make_key(self, category: str, identifier: str) -> str:
        """Generate consistent cache key with prefix"""
        prefix = self.PREFIXES.get(category, category)
        return f"perf_{prefix}:{identifier}"

    def _track_category_key(self, category: str, key: str) -> None:
        """Track key in category for efficient statistics and invalidation"""
        try:
            category_keys_key = f"perf_category_keys:{category}"
            stored_keys = self.cache.get_value(category_keys_key)

            if stored_keys:
                keys_list = json.loads(stored_keys) if isinstance(stored_keys, str) else stored_keys
            else:
                keys_list = []

            # Add key if not already present
            if key not in keys_list:
                keys_list.append(key)
                # Store with longer TTL than individual cache entries
                self.cache.set_value(category_keys_key, json.dumps(keys_list), 7200)  # 2 hours

        except Exception:
            # Non-critical operation, just log warning
            frappe.logger().warning(f"Failed to track category key {category}:{key}")

    def get(self, category: str, identifier: str) -> Any:
        """Get cached value"""
        if not self.enabled:
            return None

        try:
            key = self._make_key(category, identifier)
            cached_data = self.cache.get_value(key)

            if cached_data is not None:
                # Try to deserialize JSON data
                try:
                    return json.loads(cached_data)
                except (json.JSONDecodeError, TypeError):
                    # Return raw data if not JSON
                    return cached_data

            return None

        except Exception as e:
            frappe.logger().warning(f"Cache get failed for {category}:{identifier}: {str(e)}")
            return None

    def set(self, category: str, identifier: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set cached value with TTL"""
        if not self.enabled:
            return False

        try:
            key = self._make_key(category, identifier)
            cache_ttl = ttl or self.DEFAULT_TTLS.get(category, 600)

            # Serialize complex data structures
            if isinstance(value, (dict, list)):
                cache_value = json.dumps(value, default=str)
            else:
                cache_value = value

            self.cache.set_value(key, cache_value, cache_ttl)

            # Track key in category for efficient statistics and invalidation
            self._track_category_key(category, key)

            return True

        except Exception as e:
            frappe.logger().warning(f"Cache set failed for {category}:{identifier}: {str(e)}")
            return False

    def get_or_set(self, category: str, identifier: str, getter: Callable, ttl: Optional[int] = None) -> Any:
        """Get cached value or compute and cache it"""

        # Try to get from cache first
        cached_value = self.get(category, identifier)
        if cached_value is not None:
            return cached_value

        # Compute value using getter function
        try:
            computed_value = getter()

            # Cache the computed value
            if computed_value is not None:
                self.set(category, identifier, computed_value, ttl)

            return computed_value

        except Exception as e:
            frappe.logger().error(f"Cache getter failed for {category}:{identifier}: {str(e)}")
            return None

    def invalidate(self, category: str, identifier: str = None) -> bool:
        """Invalidate cached value(s) - FIXED to avoid expensive pattern matching"""
        if not self.enabled:
            return False

        try:
            if identifier:
                # Invalidate specific key
                key = self._make_key(category, identifier)
                self.cache.delete_value(key)
                return True
            else:
                # FIXED: Instead of pattern matching, maintain category key lists
                # This is more efficient and reliable than get_keys with patterns
                category_keys_key = f"perf_category_keys:{category}"
                try:
                    stored_keys = self.cache.get_value(category_keys_key)
                    if stored_keys:
                        keys_list = json.loads(stored_keys) if isinstance(stored_keys, str) else stored_keys
                        for key in keys_list:
                            self.cache.delete_value(key)
                        # Clear the category keys list
                        self.cache.delete_value(category_keys_key)
                except Exception:
                    # Fallback: just log that category-wide invalidation failed
                    frappe.logger().warning(f"Category-wide cache invalidation failed for {category}")

            return True

        except Exception as e:
            frappe.logger().warning(f"Cache invalidation failed for {category}:{identifier}: {str(e)}")
            return False

    def warm_cache(self, warm_functions: Dict[str, Callable]) -> Dict[str, bool]:
        """Pre-warm cache with critical data"""
        if not self.enabled:
            return {}

        results = {}

        for cache_key, warm_function in warm_functions.items():
            try:
                category, identifier = cache_key.split(":", 1)
                value = warm_function()
                results[cache_key] = self.set(category, identifier, value)

            except Exception as e:
                frappe.logger().error(f"Cache warming failed for {cache_key}: {str(e)}")
                results[cache_key] = False

        return results

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        if not self.enabled:
            return {"enabled": False}

        try:
            stats = {"enabled": True, "backend": type(self.cache).__name__, "categories": {}}

            # Get key counts by category using tracked keys (avoids expensive pattern matching)
            for category in self.PREFIXES.keys():
                category_keys_key = f"perf_category_keys:{category}"
                try:
                    stored_keys = self.cache.get_value(category_keys_key)
                    if stored_keys:
                        keys_list = json.loads(stored_keys) if isinstance(stored_keys, str) else stored_keys
                        # Filter out expired keys by checking if they still exist
                        active_keys = [key for key in keys_list if self.cache.get_value(key) is not None]
                        stats["categories"][category] = len(active_keys)

                        # Update the tracked keys to remove expired ones
                        if len(active_keys) != len(keys_list):
                            self.cache.set_value(category_keys_key, json.dumps(active_keys), 7200)
                    else:
                        stats["categories"][category] = 0
                except Exception:
                    stats["categories"][category] = 0

            return stats

        except Exception as e:
            return {"enabled": True, "error": str(e)}


# Global cache instance
_cache = PerformanceCache()


def cached(category: str, key_template: str = None, ttl: int = None):
    """
    Decorator for caching function results

    Args:
        category: Cache category for organization
        key_template: Template for cache key (uses function args)
        ttl: Time to live in seconds
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not _cache.enabled:
                return func(*args, **kwargs)

            # Generate cache key from function name and args
            if key_template:
                try:
                    cache_key = key_template.format(*args, **kwargs)
                except (KeyError, IndexError):
                    cache_key = f"{func.__name__}:{':'.join(map(str, args))}"
            else:
                cache_key = f"{func.__name__}:{':'.join(map(str, args))}"

            # Use get_or_set for atomic cache operation
            return _cache.get_or_set(
                category=category, identifier=cache_key, getter=lambda: func(*args, **kwargs), ttl=ttl
            )

        return wrapper

    return decorator


# Convenience functions for common caching patterns


def cache_chapter_access(user_email: str, chapters: List[str], ttl: int = 900):
    """Cache user chapter access data"""
    return _cache.set("chapter_access", user_email, chapters, ttl)


def get_cached_chapter_access(user_email: str) -> Optional[List[str]]:
    """Get cached user chapter access data"""
    return _cache.get("chapter_access", user_email)


def cache_member_info(member_name: str, member_data: Dict, ttl: int = 600):
    """Cache member information"""
    return _cache.set("member_info", member_name, member_data, ttl)


def get_cached_member_info(member_name: str) -> Optional[Dict]:
    """Get cached member information"""
    return _cache.get("member_info", member_name)


def invalidate_user_cache(user_email: str):
    """Invalidate all cache data for a specific user"""
    _cache.invalidate("chapter_access", user_email)
    _cache.invalidate("permissions", user_email)


def invalidate_member_cache(member_name: str):
    """Invalidate all cache data for a specific member"""
    _cache.invalidate("member_info", member_name)

    # Also invalidate related user cache if member has user
    try:
        user_email = frappe.db.get_value("Member", member_name, "user")
        if user_email:
            invalidate_user_cache(user_email)
    except Exception:
        pass


def warm_critical_caches():
    """Pre-warm caches with critical data during startup"""
    if not _cache.enabled:
        return {}

    warm_functions = {
        "settings:verenigingen_settings": lambda: frappe.get_cached_doc("Verenigingen Settings"),
        "lookup:membership_types": lambda: frappe.get_all(
            "Membership Type", fields=["name", "minimum_amount"]
        ),
        "lookup:chapter_roles": lambda: frappe.get_all("Chapter Role", fields=["name", "permissions_level"]),
    }

    return _cache.warm_cache(warm_functions)


# Cache invalidation hooks (to be used in document events)


def on_member_update(doc, method):
    """Invalidate member-related caches when member is updated"""
    invalidate_member_cache(doc.name)


def on_chapter_member_update(doc, method):
    """Invalidate chapter access caches when chapter memberships change"""
    if hasattr(doc, "member") and doc.member:
        try:
            member_doc = frappe.get_doc("Member", doc.member)
            if member_doc.user:
                invalidate_user_cache(member_doc.user)
        except Exception:
            pass


def on_membership_update(doc, method):
    """Invalidate member info caches when memberships change"""
    if hasattr(doc, "member") and doc.member:
        invalidate_member_cache(doc.member)
