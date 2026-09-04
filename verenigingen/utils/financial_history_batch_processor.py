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

from verenigingen.utils.transaction_errors import release_savepoint_if_present, rollback_to_savepoint


class FinancialHistoryBatchProcessor:
    """
    Batches financial history updates with 10s processing windows.

    Operations are queued and processed in batches to reduce database
    contention while maintaining per-member atomicity.

    CAVEAT on "per-member atomicity": each member's work is wrapped in a savepoint,
    and since #411 the history manager no longer commits inside it. One inner
    commit remains on a path this one reaches: Member._get_invoice_with_retry
    (payment_mixin.py:546) commits between attempts when an invoice is not yet
    visible, deliberately, to get a fresh read view -- #421. When that retry fires the
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
        # (payment_mixin.py:546, #421) commits between attempts when an invoice is not
        # yet visible; on that path the savepoint is destroyed and the scoped rollback
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
        (payment_mixin.py:546, #421) commits between attempts to get a fresh read view --
        and MariaDB discards every savepoint when it does, so RELEASE then raises
        1305. The member's work is already durable at that point, so there is
        nothing to release.

        This used to fire on EVERY successful batch, because the history manager
        committed after `update_child_table`. That commit is gone (#411), so a 1305
        here now means some OTHER inner path committed -- which is worth the log
        line rather than being routine noise.
        """
        if not release_savepoint_if_present(save_point):
            # .error(), not .debug(): bare loggers default to ERROR under
            # `bench run-tests`, so a .debug() here would be invisible exactly where
            # it matters. The helper logs the generic fact; this adds the local why.
            frappe.logger("financial_batch").error(
                f"savepoint {save_point} already released by an inner commit "
                "(the invoice-retry path in payment_mixin still has one -- #421)"
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
        # 1213 (deadlock) and 2006 (server gone) reach the helper too, and they are a
        # different situation: the whole transaction is already gone, so continuing to feed
        # members into it would let each one "succeed" against a discarded transaction. The
        # helper re-raises those and swallows only the benign 1305.
        if not rollback_to_savepoint(save_point):
            frappe.logger("financial_batch").error(
                f"Could not roll back to {save_point} for {member_name}. "
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


def validate_donor_history_integrity(donor_names=None):
    """
    Scheduled integrity sweep for ``donor_history`` (#425).

    Before this, ``donor_history`` was one of two history tables (the other is
    ``fee_change_history``) with NO periodic safety net at all. Its writers
    (Donation's ``after_insert``/``on_update`` hooks) ride whatever transaction
    is open, same as ``payment_history`` and ``volunteer_expenses`` -- but
    unlike those two, nothing ever re-checked it, so a write lost to a rolled
    back transaction (an unhandled exception, or any GET request, per
    ``frappe/app.py``) stayed lost forever.

    Calls the existing, already-tested ``DonationHistoryManager.sync_donation_history()``
    (``donation_history_manager.py``) per donor, which rebuilds that donor's
    ENTIRE ``donor_history`` child table from ``Donation`` records -- the
    source of truth -- and commits per donor here, the same scope
    ``sync_all_donor_histories()`` already commits at and for the same reason
    (a lock per donor row, not a durability boundary of its own). This calls
    the manager directly rather than going through that whitelisted endpoint
    so an optional ``donor_names`` can scope the run -- used by tests to
    avoid rewriting every donor on a shared site, and available for chunking
    a production run later. The scheduled entry point always omits it and
    sweeps every donor.

    Because the rebuild is total (not a diff against a prior snapshot), one
    pass catches BOTH a missing entry (lost write) and a stale/orphaned entry
    (the donation was later deleted) -- unlike the payment/expense validators,
    which each detect only one direction of drift. Known tradeoff, not fixed
    here: because the rebuild is unconditional, it deletes and re-inserts
    every child row (and Donor has ``track_changes=1``) even when nothing was
    wrong, so a donor with real history accumulates a new Version every week.
    A follow-up to make the underlying sync a no-op when nothing changed is
    warranted but out of scope here.
    """
    from verenigingen.utils.donation_history_manager import DonationHistoryManager

    donors = donor_names if donor_names is not None else frappe.get_all("Donor", pluck="name")

    resynced = 0
    errors = 0

    for donor_name in donors:
        try:
            result = DonationHistoryManager.sync_donation_history(donor_name)
            if result.get("success"):
                frappe.db.commit()
                resynced += 1
            else:
                frappe.db.rollback()
                errors += 1
                frappe.logger("financial_batch").error(
                    f"Donor history sync reported failure for {donor_name}: {result.get('error')}"
                )
        except Exception as e:
            frappe.db.rollback()
            errors += 1
            frappe.log_error(
                title="Donor History Integrity Sweep Error",
                message=f"Failed to resync donor history for {donor_name}: {e}",
            )

    frappe.logger("financial_batch").info(
        f"Donor history integrity sweep: {resynced} resynced, {errors} errors, {len(donors)} total"
    )
    return {"total": len(donors), "resynced": resynced, "errors": errors}


def validate_fee_change_history_integrity(member_names=None):
    """
    Scheduled integrity sweep for ``fee_change_history`` (#425).

    Fee changes are recorded from several call sites (dues schedule creation,
    cancellation, resumption, and amendment approval), so unlike
    ``payment_history``/``volunteer_expenses``/``donor_history`` there is no
    single doctype whose rows map 1:1 to a fee change. This sweep finds two
    kinds of gap directly in SQL -- a ``Membership Dues Schedule`` with no
    matching ``Member Fee Change History`` row, and an ``Applied``
    ``Contribution Amendment Request`` with no matching row (the latter
    catches members whose ONLY fee-change record is an amendment, with no
    dues schedule of their own to key a sweep off) -- and repairs each by
    calling the "new entry" builders directly.

    Deliberately does NOT call ``MemberHistoryUpdateService.refresh_fee_change_history()``,
    which looked like the obvious reuse (it already reconstructs this same
    picture): its reconciliation path for an EXISTING entry
    (``_process_fee_schedule``'s ``needs_update`` check) compares
    ``existing_entry.reason`` against ``f"Dues schedule: {schedule_name}"`` --
    a string the live writer (``FeeChangeTrackingService``, which writes
    ``f"New schedule - {...}"`` or a custom reason) never actually produces.
    Every pre-existing row therefore looks "stale" and gets overwritten --
    change_date, change_type, reason and changed_by -- silently, on every run.
    Measured on veg11: 560 of 565 rows have ``change_type='New Schedule'``,
    and 476 carry ``reason='MijnRood CSV import'`` -- import provenance a
    single scheduled run of that path would erase. This sweep instead calls
    ``MemberHistoryUpdateService._process_fee_schedule``/``_process_fee_amendments``
    (the same two @staticmethod builders ``refresh_fee_change_history`` uses)
    but ONLY for rows already confirmed missing by the SQL above, passing an
    empty existing-entries map so the "already have one, check if it needs
    updating" branch is structurally unreachable from here. It never rewrites
    a row that already exists.
    """
    from verenigingen.services.member.history.member_history_update_service import (
        MemberHistoryUpdateService,
    )
    from verenigingen.utils.history_manager_utils import safe_child_table_update

    missing_schedules = frappe.db.sql(
        """
        SELECT mds.name AS name, mds.member AS member, mds.schedule_name AS schedule_name,
               mds.dues_rate AS dues_rate, mds.billing_frequency AS billing_frequency,
               mds.creation AS creation
        FROM `tabMembership Dues Schedule` mds
        LEFT JOIN `tabMember Fee Change History` mfch
            ON mfch.dues_schedule = mds.name
        WHERE mds.is_template = 0
          AND mds.member IS NOT NULL AND mds.member != ''
          AND mfch.name IS NULL
        """,
        as_dict=True,
    )

    missing_amendments = frappe.db.sql(
        """
        SELECT car.name AS name, car.member AS member, car.requested_amount AS requested_amount,
               car.current_amount AS current_amount, car.reason AS reason,
               car.applied_date AS applied_date, car.effective_date AS effective_date,
               car.applied_by AS applied_by
        FROM `tabContribution Amendment Request` car
        LEFT JOIN `tabMember Fee Change History` mfch
            ON mfch.amendment_request = car.name
        WHERE car.status = 'Applied'
          AND car.member IS NOT NULL AND car.member != ''
          AND mfch.name IS NULL
        """,
        as_dict=True,
    )

    by_member = defaultdict(lambda: {"schedules": [], "amendments": []})
    for row in missing_schedules:
        if member_names is None or row.member in member_names:
            by_member[row.member]["schedules"].append(row)
    for row in missing_amendments:
        if member_names is None or row.member in member_names:
            by_member[row.member]["amendments"].append(row)

    repaired = 0
    errors = 0
    skipped = 0

    for member_name, gaps in by_member.items():
        if not frappe.db.exists("Member", member_name):
            # The member was deleted after the schedule/amendment that named
            # it -- the same expected race _process_member_payment_batch
            # already tolerates for the batch queues. Not a failure.
            skipped += 1
            continue

        try:
            member_doc = frappe.get_doc("Member", member_name)
            for row in gaps["schedules"]:
                MemberHistoryUpdateService._process_fee_schedule(member_doc, row, None)
            if gaps["amendments"]:
                MemberHistoryUpdateService._process_fee_amendments(member_doc, gaps["amendments"], {})

            result = safe_child_table_update(
                member_doc,
                "fee_change_history",
                justification="Fee change history integrity sweep (#425): repair missing entries",
                doctype_permission="Member:write",
                auto_cleanup=True,
            )
            if result.success:
                frappe.db.commit()
                repaired += 1
            else:
                frappe.db.rollback()
                errors += 1
                frappe.logger("financial_batch").error(
                    f"Fee change history repair failed for {member_name}: {result.errors}"
                )
        except Exception as e:
            frappe.db.rollback()
            errors += 1
            frappe.log_error(
                title="Fee Change History Integrity Sweep Error",
                message=f"Failed to repair fee change history for {member_name}: {e}",
            )

    frappe.logger("financial_batch").info(
        f"Fee change history integrity sweep: {repaired} members repaired, {errors} errors, "
        f"{skipped} skipped (member deleted), {len(by_member)} members with gaps"
    )
    return {
        "members_with_gaps": len(by_member),
        "repaired": repaired,
        "errors": errors,
        "skipped": skipped,
    }


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
