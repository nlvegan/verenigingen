# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Sync Client

Client for triggering bank account synchronizations in Ponto.

Ponto synchronizations refresh account data from the bank. After triggering
a sync, new transactions become available via the transactions API.

Usage:
    from verenigingen.verenigingen_payments.ponto.clients.sync_client import (
        PontoSyncClient,
    )

    client = PontoSyncClient()
    result = client.trigger_sync(account_id)
"""

from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient, get_ponto_client
from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError


class PontoSyncClient:
    """
    Client for Ponto synchronization operations.

    Provides methods for:
    - Triggering account synchronization
    - Checking synchronization status
    - Getting latest synchronization info
    """

    def __init__(self, client: Optional[PontoClient] = None):
        """
        Initialize sync client.

        Args:
            client: Optional PontoClient instance (creates new if not provided)
        """
        self._client = client or get_ponto_client()

    def trigger_sync(self, account_id: str) -> Dict:
        """
        Trigger a synchronization for a Ponto account.

        This requests Ponto to refresh account data from the bank.
        The sync happens asynchronously - new transactions will be
        available after completion (typically a few seconds to minutes).

        Note: Ponto has rate limits on sync requests. If called too
        frequently, the API may return an error or ignore the request.

        Args:
            account_id: Ponto account UUID

        Returns:
            Dict with sync status:
            {
                "status": "success" | "error" | "pending",
                "synchronization_id": str (if available),
                "message": str,
            }
        """
        if not account_id:
            return {
                "status": "error",
                "message": "Account ID is required",
            }

        frappe.logger().info(f"Triggering Ponto sync for account {account_id}")

        try:
            # POST to synchronizations endpoint
            # Ponto API: POST /accounts/{accountId}/synchronizations
            response = self._client.post(
                f"/accounts/{account_id}/synchronizations",
                data={"data": {"type": "synchronization"}},
            )

            # Extract synchronization ID from response
            sync_id = None
            if response and "data" in response:
                sync_id = response["data"].get("id")

            frappe.logger().info(f"Ponto sync triggered for {account_id}, sync_id={sync_id}")

            return {
                "status": "success",
                "synchronization_id": sync_id,
                "message": "Synchronization triggered successfully",
            }

        except PontoAPIError as e:
            # Handle specific error cases
            error_code = getattr(e, "error_code", None)
            status_code = getattr(e, "status_code", None)

            # Rate limit or sync already in progress
            if error_code in ("synchronizationInProgress", "rateLimitExceeded"):
                frappe.logger().info(f"Ponto sync already in progress or rate limited for {account_id}")
                return {
                    "status": "pending",
                    "message": str(e),
                }

            # 404 means endpoint not available (might require user OAuth flow)
            # This is OK - Ponto auto-syncs periodically, we can still import
            if status_code == 404 or error_code == "resourceNotFound":
                frappe.logger().info(
                    f"Ponto sync endpoint not available for {account_id} "
                    "(may require user OAuth). Continuing with existing transactions."
                )
                return {
                    "status": "skipped",
                    "message": "Sync endpoint not available. Using existing transactions.",
                }

            frappe.logger().warning(f"Ponto sync trigger failed for {account_id}: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

        except Exception as e:
            frappe.logger().error(f"Ponto sync trigger error for {account_id}: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    def get_synchronization(self, account_id: str, sync_id: str) -> Dict:
        """
        Get status of a specific synchronization.

        Args:
            account_id: Ponto account UUID
            sync_id: Synchronization UUID

        Returns:
            Dict with synchronization details
        """
        try:
            response = self._client.get(f"/accounts/{account_id}/synchronizations/{sync_id}")

            if response and "data" in response:
                data = response["data"]
                attrs = data.get("attributes", {})
                return {
                    "id": data.get("id"),
                    "status": attrs.get("status"),
                    "subtype": attrs.get("subtype"),
                    "created_at": attrs.get("createdAt"),
                    "updated_at": attrs.get("updatedAt"),
                }

            return {"status": "unknown"}

        except Exception as e:
            frappe.logger().error(f"Failed to get sync status: {e}")
            return {"status": "error", "message": str(e)}

    def get_latest_synchronization(self, account_id: str) -> Optional[Dict]:
        """
        Get the latest synchronization for an account.

        Args:
            account_id: Ponto account UUID

        Returns:
            Dict with latest synchronization info or None
        """
        try:
            response = self._client.get(
                f"/accounts/{account_id}/synchronizations",
                params={"limit": 1},
            )

            if response and "data" in response:
                data = response["data"]
                if isinstance(data, list) and len(data) > 0:
                    sync = data[0]
                    attrs = sync.get("attributes", {})
                    return {
                        "id": sync.get("id"),
                        "status": attrs.get("status"),
                        "subtype": attrs.get("subtype"),
                        "created_at": attrs.get("createdAt"),
                        "updated_at": attrs.get("updatedAt"),
                    }

            return None

        except Exception as e:
            frappe.logger().error(f"Failed to get latest sync: {e}")
            return None


def get_sync_client() -> PontoSyncClient:
    """
    Factory function to get PontoSyncClient instance.

    Returns:
        PontoSyncClient: Client instance
    """
    return PontoSyncClient()
