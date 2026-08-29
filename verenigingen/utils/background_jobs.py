#!/usr/bin/env python3
"""
Background Jobs Manager - Enhanced for Phase 2.2
Phase 2.2 Implementation - Targeted Event Handler Optimization

ENHANCED VERSION: This module provides smart background job implementation with
comprehensive error handling, job status tracking, user notifications, and
intelligent retry mechanisms for Phase 2.2 performance optimization.

Performance Improvements Based on Phase 2.1 Baseline Analysis:
- Payment entry submission: 0.156s (blocks UI - 3 heavy operations identified)
- Target: 60-70% faster UI response times through background processing
- Expected outcome: Payment operations 3x faster (67% improvement)
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import add_days, get_datetime, now


class BackgroundJobManager:
    """Manager for background job operations with status tracking and notifications"""

    @staticmethod
    def _enqueue_tracked_job(
        *,
        method: str,
        job_type: str,
        job_prefix: str,
        queue: str = "default",
        timeout: int = 300,
        enqueue_kwargs: Optional[Dict] = None,
        status_kwargs: Optional[Dict] = None,
    ) -> str:
        """Enqueue a background job with status tracking. Returns job_name."""
        job_name = f"{job_prefix}_{int(time.time())}"

        frappe.enqueue(
            method,
            **(enqueue_kwargs or {}),
            queue=queue,
            timeout=timeout,
            # `tracking_job_name`, NOT `job_name`: job_name is one of frappe.enqueue's
            # own parameters, so enqueue consumed it and the executors received
            # job_name=None -- every `if job_name:` guard fell through and the status
            # record stayed "Queued" for the life of the job.
            # `retry=` used to be passed here too. It is not an enqueue parameter, so it
            # was forwarded to the executors and absorbed by their **kwargs; it has
            # never retried anything. Removed rather than reimplemented.
            tracking_job_name=job_name,
        )

        BackgroundJobManager.create_job_status_record(
            job_name=job_name,
            job_type=job_type,
            status="Queued",
            **(status_kwargs or {}),
        )

        return job_name

    @staticmethod
    def queue_member_payment_history_update(
        member_name: str, payment_entry: str = None, priority: str = "default"
    ) -> str:
        """Queue member payment history update as background job"""
        try:
            return BackgroundJobManager._enqueue_tracked_job(
                method="verenigingen.utils.background_jobs.execute_member_payment_history_update",
                job_type="member_payment_history_update",
                job_prefix=f"payment_history_update_{member_name}",
                queue=priority,
                timeout=300,
                enqueue_kwargs={"member_name": member_name, "payment_entry": payment_entry},
                status_kwargs={"member_name": member_name, "payment_entry": payment_entry},
            )
        except Exception as e:
            frappe.log_error(f"Failed to queue payment history update for {member_name}: {e}")
            return BackgroundJobManager.execute_member_payment_history_update_sync(member_name, payment_entry)

    @staticmethod
    def queue_expense_event_processing(expense_doc_name: str, event_type: str) -> str:
        """Queue expense event processing as background job"""
        try:
            return BackgroundJobManager._enqueue_tracked_job(
                method="verenigingen.utils.background_jobs.execute_expense_event_processing",
                job_type="expense_event_processing",
                job_prefix=f"expense_event_{event_type}_{expense_doc_name}",
                queue="short",
                timeout=180,
                enqueue_kwargs={"expense_doc_name": expense_doc_name, "event_type": event_type},
                status_kwargs={"reference_doctype": "Expense Claim", "reference_name": expense_doc_name},
            )
        except Exception as e:
            frappe.log_error(f"Failed to queue expense event processing for {expense_doc_name}: {e}")
            return None

    @staticmethod
    def queue_donor_auto_creation(payment_doc_name: str) -> str:
        """Queue donor auto creation as background job"""
        try:
            return BackgroundJobManager._enqueue_tracked_job(
                method="verenigingen.utils.background_jobs.execute_donor_auto_creation",
                job_type="donor_auto_creation",
                job_prefix=f"donor_auto_creation_{payment_doc_name}",
                queue="default",
                timeout=240,
                enqueue_kwargs={"payment_doc_name": payment_doc_name},
                status_kwargs={"reference_doctype": "Payment Entry", "reference_name": payment_doc_name},
            )
        except Exception as e:
            frappe.log_error(f"Failed to queue donor auto creation for {payment_doc_name}: {e}")
            return None

    @staticmethod
    def create_job_status_record(job_name: str, job_type: str, status: str, **kwargs) -> None:
        """Create job status tracking record"""
        try:
            # Create a simple job status record in database
            job_status = {
                "job_name": job_name,
                "job_type": job_type,
                "status": status,
                "created_at": now(),
                "user": frappe.session.user,
                **kwargs,
            }

            # Store in cache for quick access
            cache_key = f"job_status_{job_name}"
            frappe.cache().set_value(cache_key, job_status, expires_in_sec=3600)

        except Exception as e:
            frappe.log_error(f"Failed to create job status record for {job_name}: {e}")

    @staticmethod
    def update_job_status(job_name: str, status: str, result: Dict = None, error: str = None) -> None:
        """Update job status"""
        try:
            cache_key = f"job_status_{job_name}"
            # NOTE: use get_value (not the raw redis .get) -- set_value/get_value
            # are the matched cache API; .get() bypasses make_key + unpickling and
            # always returns None, silently losing every tracked job's status.
            job_status = frappe.cache().get_value(cache_key) or {}

            job_status.update({"status": status, "updated_at": now(), "result": result, "error": error})

            frappe.cache().set_value(cache_key, job_status, expires_in_sec=3600)

            # Notify user if job completed or failed
            if status in ["Completed", "Failed"] and job_status.get("user"):
                BackgroundJobManager.notify_job_completion(job_status)

        except Exception as e:
            frappe.log_error(f"Failed to update job status for {job_name}: {e}")

    @staticmethod
    def notify_job_completion(job_status: Dict) -> None:
        """Notify user about job completion"""
        try:
            if job_status["status"] == "Completed":
                message = f"Background job '{job_status['job_type']}' completed successfully"
                indicator = "green"
            else:
                message = f"Background job '{job_status['job_type']}' failed: {job_status.get('error', 'Unknown error')}"
                indicator = "red"

            # Real-time notification
            frappe.publish_realtime(
                "background_job_update",
                {
                    "job_name": job_status["job_name"],
                    "job_type": job_status["job_type"],
                    "status": job_status["status"],
                    "message": message,
                    "indicator": indicator,
                },
                user=job_status["user"],
            )

        except Exception as e:
            frappe.log_error(f"Failed to notify job completion: {e}")

    @staticmethod
    def get_job_status(job_name: str) -> Dict:
        """Get job status"""
        try:
            cache_key = f"job_status_{job_name}"
            # get_value matches set_value (see create_job_status_record). The raw
            # redis .get() bypasses make_key/unpickling and always misses.
            return frappe.cache().get_value(cache_key) or {"status": "Unknown", "job_name": job_name}
        except Exception as e:
            frappe.log_error(f"Failed to get job status for {job_name}: {e}")
            return {"status": "Error", "job_name": job_name, "error": str(e)}

    @staticmethod
    def enqueue_with_tracking(
        method: str, job_name: str, user: str, queue: str = "default", timeout: int = 300, **kwargs
    ) -> str:
        """
        Enhanced job enqueuing with comprehensive tracking and user notifications

        Args:
            method: Function path to execute
            job_name: Unique job identifier
            user: User who initiated the job
            queue: Queue name (default, short, long)
            timeout: Job timeout in seconds
            **kwargs: Arguments to pass to the job function

        Returns:
            Job ID for tracking
        """
        try:
            # Generate unique job ID
            job_id = f"{job_name}_{int(time.time())}"

            # Queue the background job
            # No `retry=`: it is not a frappe.enqueue parameter, so it was forwarded to
            # the target and would raise TypeError for any target without **kwargs.
            # It never retried anything. `job_name` IS an enqueue parameter (deprecated
            # in v16) and is used here only to label the job, not passed to the target.
            frappe.enqueue(method, job_name=job_id, queue=queue, timeout=timeout, **kwargs)

            # Create comprehensive job status record
            BackgroundJobManager.create_job_status_record(
                job_name=job_id,
                job_type=method.split(".")[-1],  # Extract function name
                status="Queued",
                user=user,
                method=method,
                queue=queue,
                timeout=timeout,
                **kwargs,
            )

            # Send immediate user notification
            frappe.publish_realtime(
                "show_alert",
                {
                    "message": f"Background job '{job_name}' has been queued. You'll be notified when complete.",
                    "indicator": "blue",
                },
                user=user,
            )

            return job_id

        except Exception as e:
            frappe.log_error(f"Failed to enqueue job {job_name}: {e}")
            # Send error notification to user
            frappe.publish_realtime(
                "show_alert",
                {"message": f"Failed to queue background job '{job_name}': {str(e)}", "indicator": "red"},
                user=user,
            )
            raise

    @staticmethod
    def retry_failed_job(job_name: str, max_retries: int = 3) -> bool:
        """Retry failed job with exponential backoff"""
        try:
            job_status = BackgroundJobManager.get_job_status(job_name)

            if job_status.get("status") != "Failed":
                return False

            retry_count = job_status.get("retry_count", 0)
            if retry_count >= max_retries:
                frappe.log_error(f"Job {job_name} exceeded max retries ({max_retries})")
                return False

            # Calculate backoff delay (exponential: 1s, 2s, 4s, 8s...)
            delay = min(2**retry_count, 60)  # Cap at 60 seconds

            # Schedule retry.
            # NOTE: do NOT name this kwarg `job_name`. That is one of
            # frappe.enqueue's own parameters, so enqueue consumes it and the job
            # is invoked without it -> TypeError: missing a required argument.
            frappe.enqueue(
                "verenigingen.utils.background_jobs.retry_job_execution",
                target_job_name=job_name,
                # `delay` IS a real parameter of retry_job_execution, unlike the
                # enqueue-level `delay=` that was the bug at the other call sites.
                delay=delay,
                queue="default",
                timeout=300,
            )

            # Update job status
            job_status.update(
                {"status": "Retrying", "retry_count": retry_count + 1, "retry_scheduled_at": now()}
            )

            cache_key = f"job_status_{job_name}"
            frappe.cache().set_value(cache_key, job_status, expires_in_sec=3600)

            return True

        except Exception as e:
            frappe.log_error(f"Failed to retry job {job_name}: {e}")
            return False


# Background Job Execution Functions
# These functions are called by the queued jobs


def execute_member_payment_history_update(
    member_name: str, payment_entry: str = None, tracking_job_name: str = None, **kwargs
):
    """Execute member payment history update in background.

    `tracking_job_name`, not `job_name`: frappe.enqueue owns that parameter name
    and would consume it instead of forwarding it, leaving status tracking inert.
    """
    job_name = tracking_job_name
    try:
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Running")

        # Get member document
        member = frappe.get_doc("Member", member_name)

        # FIXED: Use atomic/incremental update when we have a specific payment entry
        # This prevents clearing the entire payment history
        if payment_entry and hasattr(member, "refresh_payment_entry"):
            # Use atomic update for specific payment entry
            result = member.refresh_payment_entry(payment_entry)
            frappe.logger("payment_history").info(
                f"Used atomic payment history update for member {member_name}, payment {payment_entry}"
            )
        else:
            # Only use full rebuild when no specific payment entry is provided
            # This should be rare - typically only for manual refresh operations
            result = refresh_member_financial_history_optimized(member, payment_entry)
            frappe.logger("payment_history").info(
                f"Used full payment history rebuild for member {member_name} (no specific payment entry)"
            )

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Completed", result)

        return result

    except frappe.DoesNotExistError:
        # A member that no longer exists when this async job runs is a benign race,
        # not a failure: in the async-only payment-history flow the enqueuing request
        # may have rolled back (or the member was deleted) between enqueue and
        # execution. Skip quietly -- do NOT frappe.log_error() and do NOT re-raise.
        # Re-raising would both be re-logged by the worker's execute_job wrapper and,
        # for jobs that leak out of a rolled-back test onto a real worker, drop an
        # Error Log into whatever unrelated test's assertNoErrorLog() window it lands
        # in. (This path is only reached via the test-only queue helper /
        # retry_job_execution; production populates payment history via
        # drain_member_payment_history.)
        skip_msg = f"Skipped payment history update for missing member {member_name}"
        frappe.logger("payment_history").info(skip_msg)
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Skipped", {"reason": skip_msg})
        return {"status": "skipped", "reason": "member_not_found"}

    except Exception as e:
        error_msg = f"Failed to update payment history for {member_name}: {e}"
        frappe.log_error(error_msg)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Failed", error=error_msg)

        raise


def execute_expense_event_processing(
    expense_doc_name: str, event_type: str, tracking_job_name: str = None, **kwargs
):
    """Execute expense event processing in background.

    See execute_member_payment_history_update for why the parameter is not `job_name`.
    """
    job_name = tracking_job_name
    try:
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Running")

        # Import the expense events module
        from verenigingen.events import expense_events

        if event_type == "payment_made":
            result = expense_events.emit_expense_payment_made_background(expense_doc_name)
        elif event_type == "claim_approved":
            result = expense_events.emit_expense_claim_approved_background(expense_doc_name)
        elif event_type == "claim_cancelled":
            result = expense_events.emit_expense_claim_cancelled_background(expense_doc_name)
        else:
            raise ValueError(f"Unknown event type: {event_type}")

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Completed", result)

        return result

    except Exception as e:
        error_msg = f"Failed to process expense event {event_type} for {expense_doc_name}: {e}"
        frappe.log_error(error_msg)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Failed", error=error_msg)

        raise


def execute_donor_auto_creation(payment_doc_name: str, tracking_job_name: str = None, **kwargs):
    """Execute donor auto creation in background.

    See execute_member_payment_history_update for why the parameter is not `job_name`.
    """
    job_name = tracking_job_name
    try:
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Running")

        # Check if payment entry still exists before processing
        if not frappe.db.exists("Payment Entry", payment_doc_name):
            result = {"status": "skipped", "reason": f"Payment Entry {payment_doc_name} no longer exists"}
            if job_name:
                BackgroundJobManager.update_job_status(job_name, "Completed", result)
            return result

        # Import the donor auto creation module
        from verenigingen.utils import donor_auto_creation

        payment_doc = frappe.get_doc("Payment Entry", payment_doc_name)
        result = donor_auto_creation.process_payment_for_donor_creation(payment_doc, method=None)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Completed", result)

        return result

    except Exception as e:
        error_msg = f"Failed to process donor auto creation for {payment_doc_name}: {e}"
        frappe.log_error(error_msg)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Failed", error=error_msg)

        raise


def retry_job_execution(target_job_name: str, delay: int):
    """Retry job execution after delay.

    Args:
        target_job_name: The job being retried. Deliberately NOT called
            `job_name`: frappe.enqueue owns that parameter name and would
            swallow it instead of forwarding it to this function.
        delay: Seconds to wait before retrying.
    """
    import time

    job_name = target_job_name  # the body below keeps the original name
    time.sleep(delay)

    try:
        job_status = BackgroundJobManager.get_job_status(job_name)
        job_type = job_status.get("job_type")

        if job_type == "member_payment_history_update":
            execute_member_payment_history_update(
                member_name=job_status.get("member_name"),
                payment_entry=job_status.get("payment_entry"),
                tracking_job_name=job_name,
            )
        elif job_type == "expense_event_processing":
            execute_expense_event_processing(
                expense_doc_name=job_status.get("reference_name"),
                event_type="payment_made",  # Default
                tracking_job_name=job_name,
            )
        elif job_type == "donor_auto_creation":
            execute_donor_auto_creation(
                payment_doc_name=job_status.get("reference_name"), tracking_job_name=job_name
            )
        else:
            raise ValueError(f"Unknown job type for retry: {job_type}")

    except Exception as e:
        error_msg = f"Job retry failed for {job_name}: {e}"
        frappe.log_error(error_msg)
        BackgroundJobManager.update_job_status(job_name, "Failed", error=error_msg)


# Optimized Payment History Functions


def refresh_member_financial_history_optimized(member_doc, payment_entry: str = None) -> Dict[str, Any]:
    """
    Optimized payment history refresh using batch queries and intelligent caching

    This replaces the N+1 query pattern in payment_mixin.py with batch operations
    """
    if not member_doc.customer:
        return {"status": "skipped", "reason": "No customer record"}

    start_time = time.time()

    try:
        # Use intelligent caching
        cache_key = f"payment_history_optimized_{member_doc.name}_{member_doc.modified}"
        # get_value matches the set_value below; raw .get() never hit this cache.
        cached_result = frappe.cache().get_value(cache_key)

        if cached_result and not payment_entry:  # Skip cache if specific payment triggered update
            return {"status": "cached", "cache_hit": True, "execution_time": 0.001}

        # Clear existing payment history
        member_doc.payment_history = []

        # Batch query approach - eliminate N+1 queries
        result = load_payment_history_batch_optimized(member_doc)

        # Save with optimized flags
        # Security: Background job for payment history sync - system operation
        member_doc.flags.ignore_version = True
        member_doc.flags.ignore_links = True
        member_doc.flags.ignore_validate_update_after_submit = True
        member_doc.save(ignore_permissions=True)

        execution_time = time.time() - start_time

        # Cache result for 30 minutes
        cache_result = {
            "status": "completed",
            "entries_processed": result["entries_processed"],
            "execution_time": execution_time,
            "timestamp": now(),
        }
        frappe.cache().set_value(cache_key, cache_result, expires_in_sec=1800)

        return cache_result

    except Exception as e:
        execution_time = time.time() - start_time
        frappe.log_error(f"Optimized payment history refresh failed for {member_doc.name}: {e}")
        return {"status": "failed", "error": str(e), "execution_time": execution_time}


def load_payment_history_batch_optimized(member_doc) -> Dict[str, Any]:
    """Populate member_doc.payment_history via the canonical service rebuild.

    Row construction now lives in PaymentHistoryService (single source of truth).
    This function is retained only as the in-memory populate step for
    refresh_member_financial_history_optimized (which owns cache + save).
    """
    from verenigingen.services.member.payment import get_payment_history_service

    result = get_payment_history_service().load_payment_history_batched(member_doc)
    count = result.data.get("entries_loaded", 0) if result.success else 0
    return {"entries_processed": count}


# Synchronous fallback functions


def execute_member_payment_history_update_sync(member_name: str, payment_entry: str = None) -> str:
    """Synchronous fallback for payment history update"""
    try:
        member = frappe.get_doc("Member", member_name)
        refresh_member_financial_history_optimized(member, payment_entry)
        return f"sync_fallback_{member_name}_{int(time.time())}"
    except Exception as e:
        frappe.log_error(f"Synchronous payment history update failed for {member_name}: {e}")
        return None


# Event Handler Functions (called from hooks.py)


def enqueue_payment_history_drain_for_customers(customers):
    """Enqueue one drain job per Member linked to any of `customers`.

    Deferred via enqueue_after_commit so the batch processor's commit/rollback
    never runs inside the submitting document's transaction. Deduplicated per
    member, so several rows naming the same member cost one job.
    """
    for customer in customers:
        for member_doc in frappe.get_all("Member", filters={"customer": customer}, fields=["name"]):
            frappe.enqueue(
                "verenigingen.utils.background_jobs.drain_member_payment_history",
                queue="short",
                job_id=f"fin_history_payment_{member_doc.name}",
                deduplicate=True,
                enqueue_after_commit=True,
                timeout=300,
                member=member_doc.name,
                customer=customer,
            )


def queue_member_payment_history_update_handler(doc, method=None):
    """Payment Entry hook: enqueue a per-member payment-history drain job."""
    try:
        if doc.party_type != "Customer":
            return
        enqueue_payment_history_drain_for_customers([doc.party])
    except Exception as e:
        frappe.log_error(f"Failed to enqueue payment history update for payment {doc.name}: {e}")
        # Don't raise - we don't want to block the payment entry submission


def customers_named_on_rows(rows):
    """The distinct Customer parties on a child table that carries party per ROW.

    Journal Entry (`accounts`) and Unreconcile Payment (`allocations`) both do that,
    unlike Payment Entry, which carries one party on the document.
    """
    return {row.party for row in (rows or []) if row.get("party_type") == "Customer" and row.get("party")}


def queue_journal_entry_payment_history_update_handler(doc, method=None):
    """Journal Entry hook: refresh payment history for every member it touches.

    A Journal Entry carries its party per ACCOUNT ROW, not on the document as a
    Payment Entry does, and one entry can name several members' receivables -- so
    every distinct Customer row is refreshed, not just the first (#645).

    Why this hook has to exist at all: a Journal Entry referencing a Sales Invoice
    restores that invoice's `outstanding_amount`, but ERPNext writes that figure
    without dispatching `on_update_after_submit` on the invoice -- so the Sales
    Invoice route that covers every other post-submit change to an invoice never
    fires here, and the member's payment history keeps saying Paid.

    (#645 cited `gl_entry.py` for that write. In v16.30 the writer is
    `update_voucher_outstanding` (`erpnext/accounts/utils.py:2141`), reached from
    `PaymentLedgerEntry.on_update`; `gl_entry.update_outstanding_amt` cannot run for a
    Sales Invoice at all, because `GLEntry.on_update` gates it on the account NOT being
    Receivable and the against_voucher row always sits on `debit_to`. The conclusion is
    unchanged -- neither writer dispatches a document event -- but the old citation sent
    a later sweep looking for GL rows, which is how a producer that posts none was
    missed. See `queue_unreconcile_payment_history_update_handler`.)
    """
    try:
        enqueue_payment_history_drain_for_customers(customers_named_on_rows(doc.get("accounts")))
    except Exception as e:
        frappe.log_error(f"Failed to enqueue payment history update for journal entry {doc.name}: {e}")
        # Don't raise - we don't want to block the journal entry submission


def queue_unreconcile_payment_history_update_handler(doc, method=None):
    """Unreconcile Payment hook: undoing an allocation puts the outstanding back.

    The producer a GL-shaped grep can never find. `UnreconcilePayment.on_submit`
    (`erpnext/accounts/doctype/unreconcile_payment/unreconcile_payment.py:67`) calls
    `update_voucher_outstanding` DIRECTLY, once per allocation row, and unlinks the
    reference with raw query-builder updates -- so it posts no GL row, saves no Payment
    Entry and saves no Journal Entry. None of the other registrations here can see it,
    and the member's history keeps saying Paid on an invoice that is owed again.

    Desk-reachable from the Sales Invoice, Payment Entry, Journal Entry and Purchase
    Invoice forms (`erpnext/public/js/utils/unreconcile.js`).

    `on_cancel` is not registered: the doctype defines no `on_cancel`, so cancelling one
    reverts nothing to react to.
    """
    try:
        enqueue_payment_history_drain_for_customers(customers_named_on_rows(doc.get("allocations")))
    except Exception as e:
        frappe.log_error(f"Failed to enqueue payment history update for unreconcile {doc.name}: {e}")
        # Don't raise - we don't want to block the unreconciliation


def queue_credit_note_payment_history_update_handler(doc, method=None):
    """Sales Invoice hook: a credit note moves the ORIGINAL invoice's outstanding.

    When a return invoice names `return_against` and `update_outstanding_for_self` is
    off, ERPNext posts the customer GL row with `against_voucher = return_against`
    (`sales_invoice.py:1675-1676`) -- so the figure that moves belongs to the invoice being
    credited, not to this document. The app's Sales Invoice route queues a refresh for
    the submitted document itself, which is the credit note, and the original's history
    row keeps the pre-credit figure (#649).

    The customer-wide drain is used rather than a refresh of `return_against` alone
    because it is the same job the Payment Entry and Journal Entry hooks already queue,
    deduplicated per member, and it re-reads every submitted invoice for the customer.
    The credit note's OWN row lands wrong, and that is a separate defect filed on its
    own rather than widened into this fix. Measured: `validate_entry` rejects the
    negative `amount` (`payment_history_builder.py:253`), and the caller answers a
    rejection with a hard-coded minimal entry stamped `payment_status = "Draft"`
    (`payment_history_service.py:620`) -- so a SUBMITTED credit note sits in the
    member's history labelled Draft. What this handler fixes is the ORIGINAL invoice's
    row.

    Guarded on the return fields rather than registered unconditionally: every ordinary
    membership invoice submit would otherwise pay for a customer-wide drain on top of
    the per-invoice refresh the event route already queues.
    """
    try:
        if not (doc.get("is_return") and doc.get("return_against")):
            return
        if doc.get("update_outstanding_for_self"):
            # ERPNext books this one against itself, so no other invoice moved. Note the
            # DocType default for this field is 1 -- the desk has to uncheck it.
            return
        enqueue_payment_history_drain_for_customers([doc.customer])
    except Exception as e:
        frappe.log_error(f"Failed to enqueue payment history update for credit note {doc.name}: {e}")
        # Don't raise - we don't want to block the credit note submission


def drain_member_payment_history(member, customer):
    """Worker job: queue the customer's submitted invoices for `member` and drain."""
    from verenigingen.utils.financial_history_batch_processor import (
        FinancialHistoryBatchProcessor,
        queue_payment_update,
    )

    invoices = frappe.get_all(
        "Sales Invoice", filters={"customer": customer, "docstatus": 1}, fields=["name"]
    )
    for invoice in invoices:
        queue_payment_update(member, invoice.name)
    FinancialHistoryBatchProcessor.force_process_all()


def queue_expense_event_processing_handler(doc, method=None):
    """
    Event handler for expense events - queues background job

    This replaces the synchronous expense event emission in hooks.py
    """
    try:
        # Determine event type based on method
        if method == "on_cancel":
            event_type = "claim_cancelled"
        else:
            event_type = "payment_made"

        # Queue background job
        job_id = BackgroundJobManager.queue_expense_event_processing(
            expense_doc_name=doc.name, event_type=event_type
        )

        frappe.logger().info(
            f"Queued expense event processing for {doc.name}, type: {event_type}, job: {job_id}"
        )

    except Exception as e:
        frappe.log_error(f"Failed to queue expense event processing for {doc.name}: {e}")
        # Don't raise - we don't want to block the document submission


def queue_donor_auto_creation_handler(doc, method=None):
    """
    Event handler for donor auto creation - queues background job

    This replaces the synchronous donor creation in hooks.py
    """
    try:
        # Queue background job
        job_id = BackgroundJobManager.queue_donor_auto_creation(payment_doc_name=doc.name)

        frappe.logger().info(f"Queued donor auto creation for payment {doc.name}, job: {job_id}")

    except Exception as e:
        frappe.log_error(f"Failed to queue donor auto creation for payment {doc.name}: {e}")
        # Don't raise - we don't want to block the payment entry submission
