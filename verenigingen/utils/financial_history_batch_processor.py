"""
Financial History Batch Processor

Implements 30-second batching for financial history updates to:
- Eliminate database lock contention
- Reduce I/O overhead
- Maintain atomic operations per member
- Provide better error recovery

This replaces immediate processing with intelligent batching.
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set

import frappe
from frappe.utils import get_datetime, now


class FinancialHistoryBatchProcessor:
    """
    Batches financial history updates with 10s processing windows.

    Operations are queued and processed in batches to reduce database
    contention while maintaining per-member atomicity.
    """

    # Class-level batch queues (shared across instances)
    _payment_queue = defaultdict(dict)  # member_name -> {invoice_name: operation_data}
    _expense_queue = defaultdict(dict)  # member_name -> {expense_name: operation_data}
    _last_processed = {}  # queue_type -> timestamp

    @classmethod
    def queue_payment_operation(cls, member_name: str, invoice_name: str, operation: str, data: dict = None):
        """
        Queue a payment history operation for batched processing.

        Args:
            member_name: Member to update
            invoice_name: Invoice identifier
            operation: 'add_update', 'remove'
            data: Additional operation data
        """
        operation_data = {"operation": operation, "timestamp": now(), "data": data or {}}

        cls._payment_queue[member_name][invoice_name] = operation_data

        frappe.logger("financial_batch").debug(
            f"Queued payment operation {operation} for {member_name}:{invoice_name}"
        )

        # Trigger processing if enough time has passed
        cls._maybe_process_batches()

    @classmethod
    def queue_expense_operation(cls, member_name: str, expense_name: str, operation: str, data: dict = None):
        """
        Queue an expense history operation for batched processing.

        Args:
            member_name: Member to update
            expense_name: Expense claim identifier
            operation: 'add_update', 'remove', 'update_payment'
            data: Additional operation data
        """
        operation_data = {"operation": operation, "timestamp": now(), "data": data or {}}

        cls._expense_queue[member_name][expense_name] = operation_data

        frappe.logger("financial_batch").debug(
            f"Queued expense operation {operation} for {member_name}:{expense_name}"
        )

        # Trigger processing if enough time has passed
        cls._maybe_process_batches()

    @classmethod
    def _maybe_process_batches(cls):
        """Check if it's time to process batches (every 30 seconds)."""
        current_time = get_datetime(now())

        # Process payment batches
        last_payment = cls._last_processed.get("payments")
        if not last_payment or (current_time - get_datetime(last_payment)).seconds >= 30:
            if cls._payment_queue:
                cls._process_payment_batches()
                cls._last_processed["payments"] = now()

        # Process expense batches
        last_expense = cls._last_processed.get("expenses")
        if not last_expense or (current_time - get_datetime(last_expense)).seconds >= 30:
            if cls._expense_queue:
                cls._process_expense_batches()
                cls._last_processed["expenses"] = now()

    @classmethod
    def _process_payment_batches(cls):
        """Process all queued payment operations in batches by member."""
        if not cls._payment_queue:
            return

        # Take snapshot and clear queue atomically
        payment_batches = dict(cls._payment_queue)
        cls._payment_queue.clear()

        processed_count = 0
        error_count = 0

        for member_name, operations in payment_batches.items():
            try:
                # Process all operations for this member atomically
                cls._process_member_payment_batch(member_name, operations)
                processed_count += len(operations)

            except Exception as e:
                error_count += len(operations)
                frappe.log_error(
                    f"Failed to process payment batch for {member_name}: {str(e)}",
                    "Financial History Batch Error",
                )

        frappe.logger("financial_batch").info(
            f"Processed payment batches: {processed_count} operations, {error_count} errors"
        )

    @classmethod
    def _process_expense_batches(cls):
        """Process all queued expense operations in batches by member."""
        if not cls._expense_queue:
            return

        # Take snapshot and clear queue atomically
        expense_batches = dict(cls._expense_queue)
        cls._expense_queue.clear()

        processed_count = 0
        error_count = 0

        for member_name, operations in expense_batches.items():
            try:
                # Process all operations for this member atomically
                cls._process_member_expense_batch(member_name, operations)
                processed_count += len(operations)

            except Exception as e:
                error_count += len(operations)
                frappe.log_error(
                    f"Failed to process expense batch for {member_name}: {str(e)}",
                    "Financial History Batch Error",
                )

        frappe.logger("financial_batch").info(
            f"Processed expense batches: {processed_count} operations, {error_count} errors"
        )

    @classmethod
    def _process_member_payment_batch(cls, member_name: str, operations: Dict[str, Dict]):
        """
        Process all payment operations for a single member atomically.

        This eliminates per-operation database locks by doing all operations
        for a member in one transaction.
        """
        try:
            # Load member fresh from database to avoid timestamp conflicts
            member = frappe.get_doc("Member", member_name)
            if not member.customer:
                return  # Skip members without customer records

            from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

            manager = get_payment_history_manager(member)

            # Process each operation in the batch
            for invoice_name, op_data in operations.items():
                operation = op_data["operation"]

                if operation == "add_update":
                    # Build invoice entry
                    def build_invoice_entry():
                        invoice = member._get_invoice_with_retry(invoice_name)
                        if invoice and invoice.customer == member.customer:
                            return member._build_payment_history_entry(invoice)
                        return None

                    manager.add_or_update_entry(invoice_name, build_invoice_entry, "invoice")

                elif operation == "remove":
                    manager.remove_entry(invoice_name, "invoice")

            frappe.db.commit()

        except Exception as e:
            frappe.db.rollback()
            raise e

    @classmethod
    def _process_member_expense_batch(cls, member_name: str, operations: Dict[str, Dict]):
        """
        Process all expense operations for a single member atomically.
        """
        try:
            # Load member fresh from database to avoid timestamp conflicts

            member = frappe.get_doc("Member", member_name)
            if not hasattr(member, "volunteer_expenses"):
                return  # Skip members without expense capability

            from verenigingen.utils.member_financial_history_manager import get_expense_history_manager

            manager = get_expense_history_manager(member)

            # Process each operation in the batch
            for expense_name, op_data in operations.items():
                operation = op_data["operation"]
                data = op_data.get("data", {})

                if operation == "add_update":
                    # Build expense entry using builder directly (avoids full Member doc dependency)
                    def build_expense_entry():
                        try:
                            from verenigingen.utils.expense_history_entry_builder import (
                                ExpenseHistoryEntryBuilder,
                            )

                            expense_doc = frappe.get_doc("Expense Claim", expense_name)
                            return ExpenseHistoryEntryBuilder.build_from_expense_doc(expense_doc, member_name)
                        except Exception:
                            return None

                    manager.add_or_update_entry(expense_name, build_expense_entry, "expense_claim")

                elif operation == "remove":
                    manager.remove_entry(expense_name, "expense_claim")

                elif operation == "update_payment":
                    # Update payment fields
                    payment_updates = data.get("payment_updates", {})
                    if payment_updates:
                        manager.update_entry_field(expense_name, payment_updates, "expense_claim")

            frappe.db.commit()

        except Exception as e:
            frappe.db.rollback()
            raise e

    @classmethod
    def force_process_all(cls):
        """Force immediate processing of all queued operations (for testing/shutdown)."""
        if cls._payment_queue:
            cls._process_payment_batches()
        if cls._expense_queue:
            cls._process_expense_batches()

    @classmethod
    def get_queue_status(cls):
        """Get current queue status for monitoring."""
        return {
            "payment_queue_size": sum(len(ops) for ops in cls._payment_queue.values()),
            "expense_queue_size": sum(len(ops) for ops in cls._expense_queue.values()),
            "payment_members": len(cls._payment_queue),
            "expense_members": len(cls._expense_queue),
            "last_processed": dict(cls._last_processed),
        }


def schedule_financial_history_processing():
    """
    Scheduled function to ensure batches are processed regularly.

    Add to hooks.py:
    "cron": {
        "*/30 * * * * *": [  # Every 30 seconds
            "verenigingen.utils.financial_history_batch_processor.schedule_financial_history_processing"
        ]
    }
    """
    try:
        FinancialHistoryBatchProcessor.force_process_all()
    except Exception as e:
        frappe.log_error(f"Scheduled financial history processing failed: {e}")


# Convenience functions for immediate use
def queue_payment_update(member_name: str, invoice_name: str):
    """Queue a payment history add/update operation."""
    FinancialHistoryBatchProcessor.queue_payment_operation(member_name, invoice_name, "add_update")


def queue_payment_removal(member_name: str, invoice_name: str):
    """Queue a payment history removal operation."""
    FinancialHistoryBatchProcessor.queue_payment_operation(member_name, invoice_name, "remove")


def queue_expense_update(member_name: str, expense_name: str):
    """Queue an expense history add/update operation."""
    FinancialHistoryBatchProcessor.queue_expense_operation(member_name, expense_name, "add_update")


def queue_expense_removal(member_name: str, expense_name: str):
    """Queue an expense history removal operation."""
    FinancialHistoryBatchProcessor.queue_expense_operation(member_name, expense_name, "remove")


def queue_expense_payment_update(member_name: str, expense_name: str, payment_updates: dict):
    """Queue an expense payment status update operation."""
    FinancialHistoryBatchProcessor.queue_expense_operation(
        member_name, expense_name, "update_payment", {"payment_updates": payment_updates}
    )
