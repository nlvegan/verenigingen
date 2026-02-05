# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Sync Log DocType Controller

Tracks synchronization operations between Ponto and ERPNext.
Provides audit trail and debugging information for transaction imports.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class PontoSyncLog(Document):
    """Controller for Ponto Sync Log DocType."""

    def before_save(self):
        """Calculate duration before saving."""
        self.calculate_duration()

    def calculate_duration(self):
        """Calculate sync duration if both start and end times exist."""
        if self.start_time and self.end_time:
            start = self.start_time
            end = self.end_time

            # Handle string datetimes
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            duration = (end - start).total_seconds()
            self.duration_seconds = round(duration, 2)

    def start_sync(self):
        """Mark sync as started."""
        self.status = "In Progress"
        self.start_time = now_datetime()
        # Security: Sync log updating its own status - system audit record
        self.save(ignore_permissions=True)

    def complete_sync(
        self,
        imported: int = 0,
        skipped: int = 0,
        failed: int = 0,
        errors: Optional[List[Dict]] = None,
        bank_transactions: Optional[List[str]] = None,
    ):
        """
        Mark sync as completed with results.

        Args:
            imported: Number of transactions imported
            skipped: Number of duplicates skipped
            failed: Number of failed imports
            errors: List of error dicts (optional)
            bank_transactions: List of created Bank Transaction names (optional)
        """
        self.status = "Completed" if failed == 0 else "Failed"
        self.end_time = now_datetime()
        self.transactions_imported = imported
        self.transactions_skipped = skipped
        self.transactions_failed = failed

        if errors:
            self.error_summary = self._build_error_summary(errors)
            self.error_details = json.dumps(errors, indent=2)

        if bank_transactions:
            self.bank_transactions = json.dumps(bank_transactions)

        # Security: Sync log updating its own completion status - system audit record
        self.save(ignore_permissions=True)

    def fail_sync(self, error_message: str, error_details: Optional[Dict] = None):
        """
        Mark sync as failed with error.

        Args:
            error_message: Error summary message
            error_details: Optional detailed error info
        """
        self.status = "Failed"
        self.end_time = now_datetime()
        self.error_summary = error_message

        if error_details:
            self.error_details = json.dumps(error_details, indent=2)

        # Security: Sync log updating its own failure status - system audit record
        self.save(ignore_permissions=True)

    def _build_error_summary(self, errors: List[Dict]) -> str:
        """Build a brief summary of errors."""
        if not errors:
            return ""

        if len(errors) == 1:
            return f"1 error: {errors[0].get('error_message', 'Unknown error')[:100]}"

        # Group by error type
        by_type = {}
        for error in errors:
            error_type = error.get("error_type", "unknown")
            by_type[error_type] = by_type.get(error_type, 0) + 1

        parts = [f"{count} {error_type}" for error_type, count in by_type.items()]
        return f"{len(errors)} errors: " + ", ".join(parts)

    def get_bank_transaction_list(self) -> List[str]:
        """Get list of created Bank Transaction names."""
        if not self.bank_transactions:
            return []
        try:
            return json.loads(self.bank_transactions)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_error_list(self) -> List[Dict]:
        """Get list of error dicts."""
        if not self.error_details:
            return []
        try:
            return json.loads(self.error_details)
        except (json.JSONDecodeError, TypeError):
            return []


def create_sync_log(
    sync_type: str = "Manual",
    account_id: Optional[str] = None,
    ponto_sync_id: Optional[str] = None,
) -> PontoSyncLog:
    """
    Create a new Ponto Sync Log entry.

    Args:
        sync_type: Type of sync (Manual, Automatic, Webhook)
        account_id: Ponto account UUID
        ponto_sync_id: Ponto synchronization ID (for manual syncs)

    Returns:
        PontoSyncLog document
    """
    log = frappe.new_doc("Ponto Sync Log")
    log.sync_type = sync_type
    log.account_id = account_id
    log.ponto_sync_id = ponto_sync_id
    log.status = "Pending"
    # Security: System audit log creation - must record sync operations regardless of user permissions
    log.insert(ignore_permissions=True)
    return log


def get_latest_sync_log(account_id: Optional[str] = None) -> Optional[PontoSyncLog]:
    """
    Get the most recent sync log.

    Args:
        account_id: Optional account ID to filter by

    Returns:
        Most recent PontoSyncLog or None
    """
    filters = {}
    if account_id:
        filters["account_id"] = account_id

    log_name = frappe.db.get_value(
        "Ponto Sync Log",
        filters=filters,
        fieldname="name",
        order_by="creation desc",
    )

    if log_name:
        return frappe.get_doc("Ponto Sync Log", log_name)

    return None
