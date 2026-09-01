"""
eBoekhouden REST API Client for Financial Data Integration

This module provides a comprehensive REST API client for integrating with eBoekhouden
(e-boekhouden.nl), a Dutch cloud-based accounting platform. It specifically addresses
the limitations of SOAP API endpoints by implementing efficient REST-based data retrieval
with pagination and caching capabilities.

Key Features:
    * Session-based authentication with automatic token management
    * Paginated mutation retrieval overcoming SOAP's 500-record limitation
    * Cached ledger and relation data for performance optimization
    * Real-time progress updates during large data imports
    * Comprehensive error handling and logging
    * Automatic retry with exponential backoff for transient errors

Integration Context:
    This client is used as part of the comprehensive eBoekhouden migration system
    for importing historical accounting data into ERPNext. It handles the complex
    mapping between eBoekhouden's transaction structure and ERPNext's accounting
    framework while maintaining data integrity and audit trails.

Usage:
    client = EBoekhoudenRESTClient()
    mutations = client.get_all_mutations(date_from="2023-01-01")

Configuration:
    Requires "E-Boekhouden Settings" DocType with:
    - api_url: REST API endpoint (default: https://api.e-boekhouden.nl)
    - api_token: Authentication token (stored encrypted)
    - source_application: Application identifier for API requests

Note:
    This client inherits token management and retry logic from EBoekhoudenHTTPClientMixin.
"""

import threading
from typing import Any, Dict, Optional

import frappe
import requests

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

from .http_client_mixin import EBoekhoudenHTTPClientMixin


class EBoekhoudenRESTClient(EBoekhoudenHTTPClientMixin):
    """
    REST API client for eBoekhouden integration with advanced session management.

    This client provides a robust interface for accessing eBoekhouden's REST API
    endpoints, specifically designed to handle large-scale data migrations and
    real-time integrations. It inherits session-based authentication and retry
    logic from EBoekhoudenHTTPClientMixin and adds intelligent caching and
    pagination to efficiently process thousands of financial records.

    Attributes:
        settings: eBoekhouden configuration settings
        base_url: API endpoint URL
        api_token: Encrypted authentication token
        _session_token: Cached session token for API requests (inherited)
        _token_obtained_at: Timestamp when token was acquired (inherited)
        _ledger_cache: Cached chart of accounts data
        _relation_cache: Cached customer/supplier data
    """

    def __init__(self, settings=None):
        """
        Initialize the REST client with optional settings.

        Args:
            settings: E-Boekhouden Settings document, or None to load automatically

        Raises:
            ValueError: If API token is not configured
        """
        # Initialize token management and HTTP client from mixin
        self._init_http_client(settings)

        # Cache for lookup data to improve performance during bulk operations
        # Thread-safe: use lock to prevent race conditions during cache updates
        self._cache_lock = threading.Lock()
        self._ledger_cache = None
        self._relation_cache = None

    def invalidate_ledger_cache(self) -> None:
        """
        Invalidate the cached ledger data, forcing refresh on next request.

        Thread-safe: Uses lock to prevent race conditions during invalidation.
        """
        with self._cache_lock:
            self._ledger_cache = None

    def invalidate_relation_cache(self) -> None:
        """
        Invalidate the cached relation data, forcing refresh on next request.

        Thread-safe: Uses lock to prevent race conditions during invalidation.
        """
        with self._cache_lock:
            self._relation_cache = None

    def invalidate_all_caches(self) -> None:
        """
        Invalidate all cached data (ledgers and relations).

        Thread-safe: Uses lock to prevent race conditions during invalidation.
        """
        with self._cache_lock:
            self._ledger_cache = None
            self._relation_cache = None

    def _fetch_and_cache_paginated(
        self, endpoint: str, cache_attr: str, result_key: str, entity_name: str
    ) -> Dict[str, Any]:
        """
        Fetch paginated data from API with double-checked locking cache pattern.

        This helper method implements the thread-safe caching pattern used for
        ledgers and relations. It handles:
        - Fast path cache check without lock
        - Double-checked locking for thread safety
        - Paginated API fetching
        - Result caching

        Args:
            endpoint: API endpoint path (e.g., "/v1/ledger")
            cache_attr: Name of the cache attribute (e.g., "_ledger_cache")
            result_key: Key name for results in response dict (e.g., "ledgers")
            entity_name: Human-readable name for error messages (e.g., "ledgers")

        Returns:
            Dict with success status and data or error message
        """
        # Fast path: check cache without lock
        cache_value = getattr(self, cache_attr)
        if cache_value is not None:
            return {"success": True, result_key: cache_value}

        with self._cache_lock:
            # Double-check after acquiring lock (another thread may have populated)
            cache_value = getattr(self, cache_attr)
            if cache_value is not None:
                return {"success": True, result_key: cache_value}

            try:
                url = f"{self.base_url}{endpoint}"
                all_items = []
                offset = 0
                limit = 2000

                while True:
                    params = {"limit": limit, "offset": offset}
                    response = self._request_with_retry("GET", url, params=params)

                    if response.status_code != 200:
                        return {
                            "success": False,
                            "error": f"Failed to get {entity_name}: {response.status_code}",
                        }

                    data = response.json()
                    if not data:
                        break

                    all_items.extend(data)

                    if len(data) < limit:
                        break

                    offset += limit

                # Cache the results
                setattr(self, cache_attr, all_items)

                return {"success": True, result_key: all_items, "count": len(all_items)}

            except Exception as e:
                return {"success": False, "error": str(e)}

    def get_mutations(self, limit=2000, offset=0, date_from=None, date_to=None) -> Dict[str, Any]:
        """
        Retrieve financial mutations with intelligent pagination.

        This method fetches accounting transactions (mutations) from eBoekhouden
        using the REST API's pagination capabilities. It automatically handles
        the API's 2000-record limit and provides detailed metadata for
        pagination management.

        Args:
            limit (int): Records per page, max 2000 (API limitation)
            offset (int): Starting position for pagination (0-based)
            date_from (str, optional): Start date filter (YYYY-MM-DD format)
            date_to (str, optional): End date filter (YYYY-MM-DD format)

        Returns:
            Dict[str, Any]: Response containing:
                - success (bool): Operation success status
                - mutations (list): List of financial transaction records
                - count (int): Number of records in current page
                - has_more (bool): Whether additional pages exist
                - offset (int): Current pagination offset
                - limit (int): Current page size
                - error (str, optional): Error message if failed

        Note:
            The eBoekhouden API may return mutations with id=0 for certain
            record types. These are handled as-is since detailed fetch
            operations may not be available for all mutation types.
        """
        try:
            url = f"{self.base_url}/v1/mutation"
            params = {"limit": min(limit, 2000), "offset": offset}  # API max is 2000

            # Add date filters if provided
            if date_from:
                params["from"] = date_from
            if date_to:
                params["to"] = date_to

            response = self._request_with_retry("GET", url, params=params)

            if response.status_code == 200:
                response_data = response.json()

                # Handle wrapped response format
                if isinstance(response_data, dict) and "items" in response_data:
                    data = response_data["items"]
                    response_data.get("count", len(data))
                else:
                    data = response_data if isinstance(response_data, list) else []
                    len(data)

                # Note: The mutations endpoint returns items with id=0
                # We'll use them as-is since detailed fetch might not work
                mutations = data

                return {
                    "success": True,
                    "mutations": mutations,
                    "count": len(mutations),
                    "has_more": len(data) == limit,  # If we got full page, there might be more
                    "offset": offset,
                    "limit": limit,
                }
            else:
                return {
                    "success": False,
                    "error": f"API request failed: {response.status_code} - {response.text}",
                }

        except Exception as e:
            frappe.log_error(title="E-Boekhouden REST", message=f"REST API error: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_mutation_detail(self, mutation_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch comprehensive details for a specific financial mutation.

        Retrieves the complete record for a single mutation, including all
        line items, account mappings, and metadata. Used for detailed
        processing and validation during migration operations.

        Args:
            mutation_id (int): Unique identifier of the mutation to fetch

        Returns:
            Optional[Dict[str, Any]]: Complete mutation record with all
                associated data, or None if the mutation cannot be retrieved

        Note:
            Some mutations may not support detailed retrieval due to
            eBoekhouden API limitations. Always check for None return.
        """
        try:
            url = f"{self.base_url}/v1/mutation/{mutation_id}"
            response = self._request_with_retry("GET", url)

            if response.status_code == 200:
                return response.json()
            else:
                frappe.log_error(
                    title="E-Boekhouden REST",
                    message=f"Failed to get mutation detail for ID {mutation_id}: {response.status_code}",
                )
                return None

        except Exception as e:
            frappe.log_error(
                title="E-Boekhouden REST", message=f"Error fetching mutation {mutation_id}: {str(e)}"
            )
            return None

    def get_all_mutations(self, date_from=None, date_to=None) -> Dict[str, Any]:
        """
        Retrieve complete mutation dataset using automatic pagination.

        This method orchestrates the retrieval of all available mutations
        by automatically handling pagination across multiple API calls.
        It provides real-time progress updates for long-running operations
        and combines all pages into a single comprehensive dataset.

        Args:
            date_from (str, optional): Start date filter (YYYY-MM-DD)
            date_to (str, optional): End date filter (YYYY-MM-DD)

        Returns:
            Dict[str, Any]: Complete result set containing:
                - success (bool): Overall operation success
                - mutations (list): All mutations from all pages
                - count (int): Total number of mutations retrieved
                - error (str, optional): Error message if failed

        Note:
            Large datasets may take significant time to retrieve. Progress
            updates are published via Frappe's realtime system for UI feedback.
        """
        all_mutations = []
        offset = 0
        limit = 2000  # Maximum allowed by API

        while True:
            result = self.get_mutations(limit=limit, offset=offset, date_from=date_from, date_to=date_to)

            if not result["success"]:
                return result

            all_mutations.extend(result["mutations"])

            # Check if there are more pages
            if not result.get("has_more", False):
                break

            offset += limit

            # Progress update
            frappe.publish_realtime(
                "eboekhouden_migration_progress",
                {"message": f"Fetched {len(all_mutations)} mutations...", "progress": len(all_mutations)},
            )

        return {"success": True, "mutations": all_mutations, "count": len(all_mutations)}

    def get_ledgers(self) -> Dict[str, Any]:
        """
        Retrieve complete chart of accounts with intelligent caching.

        Fetches all ledger accounts from eBoekhouden for account mapping
        operations. Results are cached to improve performance during
        bulk processing operations that require frequent account lookups.

        Thread-safe: Uses lock to prevent concurrent cache population.

        Returns:
            Dict[str, Any]: Ledger data containing:
                - success (bool): Operation success status
                - ledgers (list): Complete chart of accounts
                - count (int): Total number of ledger accounts
                - error (str, optional): Error message if failed

        Note:
            Ledger data is cached after first retrieval to optimize
            performance during migration operations.
        """
        return self._fetch_and_cache_paginated(
            endpoint="/v1/ledger",
            cache_attr="_ledger_cache",
            result_key="ledgers",
            entity_name="ledgers",
        )

    def get_relations(self) -> Dict[str, Any]:
        """
        Retrieve complete customer/supplier database with caching.

        Fetches all relation records (customers, suppliers, employees) from
        eBoekhouden for entity mapping during transaction import. Results
        are cached to improve performance during bulk operations.

        Thread-safe: Uses lock to prevent concurrent cache population.

        Returns:
            Dict[str, Any]: Relations data containing:
                - success (bool): Operation success status
                - relations (list): Complete customer/supplier records
                - count (int): Total number of relations
                - error (str, optional): Error message if failed

        Note:
            Relation data is cached after first retrieval. This is essential
            for efficient customer/supplier matching during large migrations.
        """
        return self._fetch_and_cache_paginated(
            endpoint="/v1/relation",
            cache_attr="_relation_cache",
            result_key="relations",
            entity_name="relations",
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def count_all_mutations():
    """
    Generate comprehensive mutation statistics for migration planning.

    This function provides detailed analytics about the mutation dataset
    available through the eBoekhouden REST API. It categorizes mutations
    by type and provides counts essential for migration planning and
    progress estimation.

    Returns:
        Dict[str, Any]: Statistics containing:
            - success (bool): Operation success status
            - total_count (int): Total mutations available
            - by_type (dict): Breakdown of mutations by transaction type
            - message (str): Human-readable summary
            - error (str, optional): Error message if failed

    Note:
        This function is exposed via Frappe's whitelist for use in
        administrative interfaces and migration planning tools.
    """
    try:
        client = EBoekhoudenRESTClient()

        # Get all mutations
        result = client.get_all_mutations()

        if result["success"]:
            # Group by type
            by_type = {}
            for mut in result["mutations"]:
                mut_type = mut.get("type", "Unknown")
                by_type[mut_type] = by_type.get(mut_type, 0) + 1

            return {
                "success": True,
                "total_count": result["count"],
                "by_type": by_type,
                "message": f"Found {result['count']} total mutations via REST API",
            }
        else:
            return result

    except Exception as e:
        return {"success": False, "error": str(e)}
