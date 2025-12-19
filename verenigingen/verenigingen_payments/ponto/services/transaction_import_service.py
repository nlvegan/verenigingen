# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Transaction Import Service

Handles importing transactions from Ponto into Bank Transaction records.
Called by webhook handlers when new transactions are available.

Usage:
    from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
        import_new_transactions,
    )

    # Called by webhook handler
    import_new_transactions(account_id="ponto-account-uuid")
"""

from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.ponto.exceptions import PontoTransactionImportError


def import_new_transactions(
    account_id: str,
    since_date: str = None,
    limit: int = 100,
) -> Dict:
    """
    Import new transactions from Ponto for a given account.

    This is typically called by the webhook handler when a
    synchronization.succeeded event is received.

    Args:
        account_id: Ponto account UUID
        since_date: Only import transactions after this date (ISO format)
        limit: Maximum number of transactions to import

    Returns:
        Dict with import results:
        {
            "success": bool,
            "imported": int,
            "skipped": int,
            "errors": List[str],
        }
    """
    try:
        frappe.logger().info(f"Starting transaction import for Ponto account {account_id}")

        # Get configuration
        from verenigingen.verenigingen_payments.ponto.services.configuration_service import get_ponto_config

        config = get_ponto_config()

        # Check if account is mapped
        mapping = config.get_mapping_for_ponto_account(account_id)
        if not mapping:
            frappe.logger().warning(f"Ponto account {account_id} not found in mappings")
            return {
                "success": False,
                "imported": 0,
                "skipped": 0,
                "errors": [f"Account {account_id} not found in Ponto Settings mappings"],
            }

        if not mapping.get("enabled"):
            frappe.logger().info(f"Ponto account {account_id} is disabled, skipping import")
            return {
                "success": True,
                "imported": 0,
                "skipped": 0,
                "errors": [],
                "reason": "account_disabled",
            }

        bank_account = mapping.get("bank_account")
        if not bank_account:
            frappe.logger().warning(f"Ponto account {account_id} has no linked Bank Account")
            return {
                "success": False,
                "imported": 0,
                "skipped": 0,
                "errors": ["No Bank Account linked in Ponto Settings"],
            }

        # Import transactions using the importer (which fetches them internally)
        from verenigingen.verenigingen_payments.ponto.clients.transaction_importer import (
            PontoTransactionImporter,
        )

        importer = PontoTransactionImporter()
        result = importer.import_transactions(
            account_id=account_id,
            bank_account=bank_account,
            limit=limit,
        )

        # Update last sync time in settings
        config.update_last_sync_time(ponto_account_id=account_id)

        # Increment transaction counter
        if result.imported > 0:
            config.increment_transactions_imported(
                ponto_account_id=account_id,
                count=result.imported,
            )

        frappe.logger().info(
            f"Transaction import complete for {account_id}: "
            f"imported={result.imported}, "
            f"skipped={result.skipped}"
        )

        return {
            "success": result.success,
            "imported": result.imported,
            "skipped": result.skipped,
            "errors": [e.error_message for e in result.errors],
        }

    except Exception as e:
        frappe.logger().error(f"Transaction import failed for {account_id}: {e}")
        frappe.log_error(
            title=f"Ponto transaction import failed: {account_id}",
            message=str(e),
        )
        return {
            "success": False,
            "imported": 0,
            "skipped": 0,
            "errors": [str(e)],
        }


def import_all_accounts() -> Dict:
    """
    Import transactions for all enabled Ponto accounts.

    This is typically called by the scheduled sync service.

    Returns:
        Dict with results per account
    """
    from verenigingen.verenigingen_payments.ponto.services.configuration_service import get_ponto_config

    config = get_ponto_config()
    enabled_mappings = config.get_enabled_account_mappings()

    results = {}
    for mapping in enabled_mappings:
        account_id = mapping.get("ponto_account_id")
        if account_id:
            results[account_id] = import_new_transactions(account_id)

    return results
