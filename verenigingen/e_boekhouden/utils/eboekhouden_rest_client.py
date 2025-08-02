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
"""

from typing import Any, Dict, Optional

import frappe
import requests


class EBoekhoudenRESTClient:
    """
    REST API client for eBoekhouden integration with advanced session management.

    This client provides a robust interface for accessing eBoekhouden's REST API
    endpoints, specifically designed to handle large-scale data migrations and
    real-time integrations. It implements session-based authentication, intelligent
    caching, and pagination to efficiently process thousands of financial records.

    Attributes:
        settings: eBoekhouden configuration settings
        base_url: API endpoint URL
        api_token: Encrypted authentication token
        _session_token: Cached session token for API requests
        _ledger_cache: Cached chart of accounts data
        _relation_cache: Cached customer/supplier data
    """

    def __init__(self, settings=None):
        if not settings:
            settings = frappe.get_single("E-Boekhouden Settings")

        self.settings = settings
        self.base_url = settings.api_url if hasattr(settings, "api_url") else "https://api.e-boekhouden.nl"
        self.api_token = settings.get_password("api_token") if hasattr(settings, "api_token") else None

        if not self.api_token:
            raise ValueError("API token is required for REST API access")

        # Session token will be obtained on first use
        self._session_token = None

        # Cache for lookup data to improve performance during bulk operations
        self._ledger_cache = None
        self._relation_cache = None

    def _get_session_token(self):
        """
        Obtain and cache session token for API authentication.

        Session tokens are required for all REST API calls and have a limited
        lifetime. This method handles token acquisition and caching to minimize
        authentication overhead during bulk operations.

        Returns:
            str: Valid session token for API requests
            None: If authentication fails

        Raises:
            ValueError: If API token is not configured
        """
        if self._session_token:
            return self._session_token

        try:
            session_url = f"{self.base_url}/v1/session"
            session_data = {
                "accessToken": self.api_token,
                "source": self.settings.source_application or "Verenigingen ERPNext",
            }

            response = requests.post(session_url, json=session_data, timeout=30)

            if response.status_code == 200:
                session_response = response.json()
                self._session_token = session_response.get("token")
                return self._session_token
            else:
                frappe.log_error(
                    f"Session token request failed: {response.status_code} - {response.text}",
                    "E-Boekhouden REST",
                )
                return None

        except Exception as e:
            frappe.log_error(f"Error getting session token: {str(e)}", "E-Boekhouden REST")
            return None

    def _get_headers(self):
        """
        Build HTTP headers for authenticated API requests.

        Returns:
            dict: Headers including authorization token and content type

        Raises:
            ValueError: If session token cannot be obtained
        """
        token = self._get_session_token()
        if not token:
            raise ValueError("Failed to obtain session token")

        return {"Authorization": token, "Content-Type": "application/json", "Accept": "application/json"}

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

            response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)

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
            frappe.log_error(f"REST API error: {str(e)}", "E-Boekhouden REST")
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
            response = requests.get(url, headers=self._get_headers(), timeout=30)

            if response.status_code == 200:
                return response.json()
            else:
                frappe.log_error(
                    f"Failed to get mutation detail for ID {mutation_id}: {response.status_code}",
                    "E-Boekhouden REST",
                )
                return None

        except Exception as e:
            frappe.log_error(f"Error fetching mutation {mutation_id}: {str(e)}", "E-Boekhouden REST")
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
        if self._ledger_cache is not None:
            return {"success": True, "ledgers": self._ledger_cache}

        try:
            url = f"{self.base_url}/v1/ledger"
            all_ledgers = []
            offset = 0
            limit = 2000

            while True:
                params = {"limit": limit, "offset": offset}
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)

                if response.status_code != 200:
                    return {"success": False, "error": f"Failed to get ledgers: {response.status_code}"}

                data = response.json()
                if not data:
                    break

                all_ledgers.extend(data)

                if len(data) < limit:
                    break

                offset += limit

            # Cache the results
            self._ledger_cache = all_ledgers

            return {"success": True, "ledgers": all_ledgers, "count": len(all_ledgers)}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_relations(self) -> Dict[str, Any]:
        """
        Retrieve complete customer/supplier database with caching.

        Fetches all relation records (customers, suppliers, employees) from
        eBoekhouden for entity mapping during transaction import. Results
        are cached to improve performance during bulk operations.

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
        if self._relation_cache is not None:
            return {"success": True, "relations": self._relation_cache}

        try:
            url = f"{self.base_url}/v1/relation"
            all_relations = []
            offset = 0
            limit = 2000

            while True:
                params = {"limit": limit, "offset": offset}
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)

                if response.status_code != 200:
                    return {"success": False, "error": f"Failed to get relations: {response.status_code}"}

                data = response.json()
                if not data:
                    break

                all_relations.extend(data)

                if len(data) < limit:
                    break

                offset += limit

            # Cache the results
            self._relation_cache = all_relations

            return {"success": True, "relations": all_relations, "count": len(all_relations)}

        except Exception as e:
            return {"success": False, "error": str(e)}


@frappe.whitelist()
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
