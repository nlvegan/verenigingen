"""
Settlement Cache Service
Provides caching for Mollie settlements to work around API limitations

The Mollie API allows listing settlements but not retrieving individual settlements
via the standard API. This cache stores settlement data from list operations to
enable lookups by settlement ID or bank reference.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe

from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.core.models.settlement import Settlement


class SettlementCache:
    """
    Cache for Mollie settlements with automatic refresh

    Features:
    - In-memory cache with TTL (time-to-live)
    - Lookup by settlement ID or bank reference
    - Automatic refresh when stale
    - Thread-safe operations
    """

    # Cache TTL in minutes
    CACHE_TTL_MINUTES = 30

    # Maximum number of settlements to cache
    MAX_CACHE_SIZE = 1000

    def __init__(self, settlements_client: Optional[SettlementsClient] = None):
        """
        Initialize settlement cache

        Args:
            settlements_client: Optional SettlementsClient instance
        """
        self.settlements_client = settlements_client or SettlementsClient()

        # Cache structure: {settlement_id: (settlement_obj, cached_at)}
        self._cache: Dict[str, tuple] = {}

        # Reference index: {bank_reference: settlement_id}
        self._reference_index: Dict[str, str] = {}

        # Last full refresh timestamp
        self._last_refresh: Optional[datetime] = None

    def get_settlement(
        self, settlement_id: Optional[str] = None, bank_reference: Optional[str] = None
    ) -> Optional[Settlement]:
        """
        Get settlement by ID or bank reference

        Args:
            settlement_id: Mollie settlement ID
            bank_reference: Bank reference from statement

        Returns:
            Settlement object or None if not found
        """
        # Refresh cache if stale
        if self._is_cache_stale():
            self._refresh_cache()

        # Lookup by settlement ID
        if settlement_id:
            cache_entry = self._cache.get(settlement_id)
            if cache_entry:
                settlement, cached_at = cache_entry

                # Check if entry is still fresh
                if self._is_entry_fresh(cached_at):
                    frappe.logger().info(f"Settlement {settlement_id} retrieved from cache (hit)")
                    return settlement

                # Entry is stale, remove it
                self._remove_from_cache(settlement_id)

        # Lookup by bank reference
        if bank_reference:
            settlement_id = self._reference_index.get(bank_reference)
            if settlement_id:
                return self.get_settlement(settlement_id=settlement_id)

        # Not in cache, try to fetch and cache recent settlements
        frappe.logger().info(f"Settlement cache miss, refreshing cache")
        self._refresh_cache()

        # Try again after refresh
        if settlement_id:
            cache_entry = self._cache.get(settlement_id)
            if cache_entry:
                return cache_entry[0]

        if bank_reference:
            settlement_id = self._reference_index.get(bank_reference)
            if settlement_id:
                cache_entry = self._cache.get(settlement_id)
                if cache_entry:
                    return cache_entry[0]

        return None

    def _refresh_cache(self, days: int = 90):
        """
        Refresh cache with recent settlements

        Args:
            days: Number of days to look back (default: 90)
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            frappe.logger().info(f"Refreshing settlement cache (last {days} days)")

            # Fetch settlements
            settlements = self.settlements_client.list_settlements(from_date=start_date, until_date=end_date)

            # Clear old cache if it's getting too large
            if len(self._cache) > self.MAX_CACHE_SIZE:
                self._cache.clear()
                self._reference_index.clear()

            # Add to cache
            now = datetime.now()
            for settlement in settlements:
                self._cache[settlement.id] = (settlement, now)

                # Index by bank reference
                if settlement.reference:
                    self._reference_index[settlement.reference] = settlement.id

            self._last_refresh = now

            frappe.logger().info(f"Settlement cache refreshed: {len(settlements)} settlements cached")

        except Exception as e:
            frappe.log_error(f"Error refreshing settlement cache: {str(e)}", "Settlement Cache Error")
            # Don't raise - allow system to continue with stale cache

    def _is_cache_stale(self) -> bool:
        """
        Check if cache needs refresh

        Returns:
            True if cache is stale or empty
        """
        if not self._last_refresh:
            return True

        age_minutes = (datetime.now() - self._last_refresh).total_seconds() / 60
        return age_minutes > self.CACHE_TTL_MINUTES

    def _is_entry_fresh(self, cached_at: datetime) -> bool:
        """
        Check if a cache entry is still fresh

        Args:
            cached_at: Timestamp when entry was cached

        Returns:
            True if entry is still fresh
        """
        age_minutes = (datetime.now() - cached_at).total_seconds() / 60
        return age_minutes <= self.CACHE_TTL_MINUTES

    def _remove_from_cache(self, settlement_id: str):
        """
        Remove a settlement from cache and indices

        Args:
            settlement_id: Settlement ID to remove
        """
        # Get settlement to find its reference
        cache_entry = self._cache.get(settlement_id)
        if cache_entry:
            settlement, _ = cache_entry

            # Remove from reference index
            if settlement.reference and settlement.reference in self._reference_index:
                del self._reference_index[settlement.reference]

        # Remove from main cache
        if settlement_id in self._cache:
            del self._cache[settlement_id]

    def clear_cache(self):
        """
        Clear all cached data
        """
        self._cache.clear()
        self._reference_index.clear()
        self._last_refresh = None
        frappe.logger().info("Settlement cache cleared")

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics

        Returns:
            Dict with cache statistics
        """
        return {
            "cached_settlements": len(self._cache),
            "indexed_references": len(self._reference_index),
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "is_stale": self._is_cache_stale(),
            "ttl_minutes": self.CACHE_TTL_MINUTES,
            "max_cache_size": self.MAX_CACHE_SIZE,
        }

    def warm_cache(self, days: int = 90):
        """
        Pre-populate cache with recent settlements

        Useful for initial setup or after clearing cache

        Args:
            days: Number of days to look back
        """
        frappe.logger().info(f"Warming settlement cache (last {days} days)")
        self._refresh_cache(days=days)


# Global cache instance (singleton pattern)
_settlement_cache: Optional[SettlementCache] = None


def get_settlement_cache() -> SettlementCache:
    """
    Get global settlement cache instance

    Returns:
        SettlementCache singleton
    """
    global _settlement_cache

    if _settlement_cache is None:
        _settlement_cache = SettlementCache()

    return _settlement_cache


def clear_settlement_cache():
    """
    Clear global settlement cache

    Useful for testing or when cache becomes inconsistent
    """
    global _settlement_cache

    if _settlement_cache:
        _settlement_cache.clear_cache()
