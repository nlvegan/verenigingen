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

SAVEPOINT_DOES_NOT_EXIST = 1305  # MariaDB: SAVEPOINT ... does not exist


def _mysql_error_code(exc):
    """First positional arg of a MySQLdb-style error, or None."""
    args = getattr(exc, "args", None)
    return args[0] if args else None


class FinancialHistoryBatchProcessor:
    """
    Batches financial history updates with 10s processing windows.

    Operations are queued and processed in batches to reduce database
    contention while maintaining per-member atomicity.

    CAVEAT on "per-member atomicity": each member's work is wrapped in a savepoint,
    and since #411 the history manager no longer commits inside it. One inner
    commit remains on a path this one reaches: Member._get_invoice_with_retry
    (payment_mixin.py:546) commits between attempts when an invoice is not yet
    visible, deliberately, to get a fresh read view. When that retry fires the
    savepoint is gone and the scoped rollback below is a no-op for anything
    already applied.

    So the guarantee to rely on is still the narrower one, which holds
    unconditionally: a failure never escalates into a transaction-wide rollback of
    other members or of the caller.
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
        if not frappe.db.exists("Member", member_name):
            # The member was deleted between queueing and this flush -- an expected
            # race, since entries accumulate across jobs within the batching window
            # before one drain processes them all. Not a failure, and it must not
            # reach the except-clause below.
            frappe.logger("financial_batch").info(f"Skipping payment batch for missing member {member_name}")
            return

        # Roll back to a SAVEPOINT, never the whole transaction. A bare
        # frappe.db.rollback() discards every OTHER member already processed in this
        # run plus whatever the caller had in flight -- and the dispatch loop swallows
        # the exception, so the run still reports success.
        #
        # Still not FULL per-member atomicity, despite the docstring above. The
        # history manager's own commit is gone (#411), but Member._get_invoice_with_retry
        # (payment_mixin.py:546) commits between attempts when an invoice is not yet
        # visible; on that path the savepoint is destroyed and the scoped rollback
        # below cannot undo what was already applied. The guarantee is the narrower
        # one: a failure here NEVER escalates beyond the member that caused it.
        #
        # Explicit savepoint rather than the savepoint() context manager, which catches
        # Exception and would swallow the re-raise the caller's error accounting needs.
        sp = "fin_hist_pay_" + frappe.generate_hash(length=10)
        frappe.db.savepoint(sp)
        try:
            # Load member fresh from database to avoid timestamp conflicts
            member = frappe.get_doc("Member", member_name)
            if not member.customer:
                cls._release_savepoint(sp)
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

            # No commit: this queue is drained INLINE from
            # add_invoice_to_payment_history(), i.e. hook context, where durability
            # belongs to the request or job that owns the transaction. The history
            # manager one frame down no longer commits either (#411) -- but releasing
            # the savepoint still tolerates it being gone, because the invoice-retry
            # path can commit before we get here.
            cls._release_savepoint(sp)

        except Exception as e:
            # Undo only THIS member's operations; leave siblings and the caller's
            # transaction intact.
            cls._rollback_to_savepoint(sp, member_name)
            raise

    @classmethod
    def _process_member_expense_batch(cls, member_name: str, operations: Dict[str, Dict]):
        """
        Process all expense operations for a single member atomically.
        """
        if not frappe.db.exists("Member", member_name):
            # Same expected race as the payment path, and not a reason to unwind
            # anyone else's work.
            frappe.logger("financial_batch").info(f"Skipping expense batch for missing member {member_name}")
            return

        # Savepoint, never a transaction-wide rollback, and NOT full per-member
        # atomicity -- see _process_member_payment_batch for what that buys.
        sp = "fin_hist_exp_" + frappe.generate_hash(length=10)
        frappe.db.savepoint(sp)
        try:
            # Load member fresh from database to avoid timestamp conflicts

            member = frappe.get_doc("Member", member_name)
            if not hasattr(member, "volunteer_expenses"):
                cls._release_savepoint(sp)
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
                            from verenigingen.services.volunteer.expense_history_entry_builder import (
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

            cls._release_savepoint(sp)

        except Exception:
            cls._rollback_to_savepoint(sp, member_name)
            raise

    @classmethod
    def force_process_all(cls):
        """Force immediate processing of all queued operations (for testing/shutdown)."""
        if cls._payment_queue:
            cls._process_payment_batches()
        if cls._expense_queue:
            cls._process_expense_batches()

    @staticmethod
    def _release_savepoint(save_point):
        """Release a savepoint, tolerating one that no longer exists.

        Inner code can still end the transaction -- Member._get_invoice_with_retry
        (payment_mixin.py:546) commits between attempts to get a fresh read view --
        and MariaDB discards every savepoint when it does, so RELEASE then raises
        1305. The member's work is already durable at that point, so there is
        nothing to release.

        This used to fire on EVERY successful batch, because the history manager
        committed after `update_child_table`. That commit is gone (#411), so a 1305
        here now means some OTHER inner path committed -- which is worth the log
        line rather than being routine noise.
        """
        try:
            frappe.db.release_savepoint(save_point)
        except Exception as release_error:
            if _mysql_error_code(release_error) != SAVEPOINT_DOES_NOT_EXIST:
                raise
            # .error(), not .debug(): bare loggers default to ERROR under
            # `bench run-tests`, so a .debug() here would be invisible exactly where
            # it matters.
            frappe.logger("financial_batch").error(
                f"savepoint {save_point} already released by an inner commit "
                "(the invoice-retry path in payment_mixin still has one)"
            )

    @staticmethod
    def _rollback_to_savepoint(save_point, member_name):
        """Undo only this member's work, and never escalate if that is impossible.

        If inner code committed (see _release_savepoint), the savepoint is gone and
        this raises 1305. Escalating to a bare frappe.db.rollback() is exactly the
        behaviour these handlers exist to avoid -- it would discard every other
        member and the caller's in-flight work -- and it would be useless anyway,
        since the committed rows cannot be rolled back. Report it and let the
        ORIGINAL exception propagate rather than masking it with the 1305.
        """
        try:
            frappe.db.rollback(save_point=save_point)
        except Exception as rollback_error:
            if _mysql_error_code(rollback_error) != SAVEPOINT_DOES_NOT_EXIST:
                # 1213 (deadlock) and 2006 (server gone) reach here too, and they are
                # a different situation: the whole transaction is already gone, so
                # continuing to feed members into it would let each one "succeed"
                # against a discarded transaction. Only the benign case is swallowed.
                raise
            frappe.logger("financial_batch").error(
                f"Could not roll back to {save_point} for {member_name}: {rollback_error}. "
                "An inner commit had already made this member's work durable, so there "
                "was nothing scoped left to undo; NOT escalated to a full rollback."
            )

    @classmethod
    def reset_queues(cls):
        """Drop every queued operation without processing it (testing/shutdown).

        The queues are class-level and therefore PROCESS-global: entries outlive the
        transaction that created them. A test whose transaction is rolled back leaves
        entries naming Members that no longer exist, and the next caller to drain the
        queue processes them. Test base classes call this per method so one test's
        residue cannot reach another's flush.
        """
        cls._payment_queue.clear()
        cls._expense_queue.clear()

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
