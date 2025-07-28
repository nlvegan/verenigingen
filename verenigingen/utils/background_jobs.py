#!/usr/bin/env python3
"""
Background Jobs Manager
Phase 2.2 Implementation - Comprehensive Architectural Refactoring Plan v2.0

This module provides smart background job implementation with error handling,
job status tracking, and user notifications for performance optimization.
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import add_days, get_datetime, now


class BackgroundJobManager:
    """Manager for background job operations with status tracking and notifications"""

    @staticmethod
    def queue_member_payment_history_update(
        member_name: str, payment_entry: str = None, priority: str = "default"
    ) -> str:
        """
        Queue member payment history update as background job

        Args:
            member_name: Name of the member to update
            payment_entry: Optional payment entry that triggered the update
            priority: Job priority (default, short, long)

        Returns:
            Job ID for tracking
        """
        job_name = f"payment_history_update_{member_name}_{int(time.time())}"

        try:
            # Queue the background job
            frappe.enqueue(
                "verenigingen.utils.background_jobs.execute_member_payment_history_update",
                member_name=member_name,
                payment_entry=payment_entry,
                queue=priority,
                timeout=300,
                retry=3,
                job_name=job_name,
            )

            # Track job status
            BackgroundJobManager.create_job_status_record(
                job_name=job_name,
                job_type="member_payment_history_update",
                status="Queued",
                member_name=member_name,
                payment_entry=payment_entry,
            )

            return job_name

        except Exception as e:
            frappe.log_error(f"Failed to queue payment history update for {member_name}: {e}")
            # Fallback to synchronous execution if queueing fails
            return BackgroundJobManager.execute_member_payment_history_update_sync(member_name, payment_entry)

    @staticmethod
    def queue_expense_event_processing(expense_doc_name: str, event_type: str) -> str:
        """Queue expense event processing as background job"""
        job_name = f"expense_event_{event_type}_{expense_doc_name}_{int(time.time())}"

        try:
            frappe.enqueue(
                "verenigingen.utils.background_jobs.execute_expense_event_processing",
                expense_doc_name=expense_doc_name,
                event_type=event_type,
                queue="short",
                timeout=180,
                retry=2,
                job_name=job_name,
            )

            BackgroundJobManager.create_job_status_record(
                job_name=job_name,
                job_type="expense_event_processing",
                status="Queued",
                reference_doctype="Expense Claim",
                reference_name=expense_doc_name,
            )

            return job_name

        except Exception as e:
            frappe.log_error(f"Failed to queue expense event processing for {expense_doc_name}: {e}")
            return None

    @staticmethod
    def queue_donor_auto_creation(payment_doc_name: str) -> str:
        """Queue donor auto creation as background job"""
        job_name = f"donor_auto_creation_{payment_doc_name}_{int(time.time())}"

        try:
            frappe.enqueue(
                "verenigingen.utils.background_jobs.execute_donor_auto_creation",
                payment_doc_name=payment_doc_name,
                queue="default",
                timeout=240,
                retry=2,
                job_name=job_name,
            )

            BackgroundJobManager.create_job_status_record(
                job_name=job_name,
                job_type="donor_auto_creation",
                status="Queued",
                reference_doctype="Payment Entry",
                reference_name=payment_doc_name,
            )

            return job_name

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
            frappe.cache().set(cache_key, job_status, expires_in_sec=3600)

        except Exception as e:
            frappe.log_error(f"Failed to create job status record for {job_name}: {e}")

    @staticmethod
    def update_job_status(job_name: str, status: str, result: Dict = None, error: str = None) -> None:
        """Update job status"""
        try:
            cache_key = f"job_status_{job_name}"
            job_status = frappe.cache().get(cache_key) or {}

            job_status.update({"status": status, "updated_at": now(), "result": result, "error": error})

            frappe.cache().set(cache_key, job_status, expires_in_sec=3600)

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
            return frappe.cache().get(cache_key) or {"status": "Unknown", "job_name": job_name}
        except Exception as e:
            frappe.log_error(f"Failed to get job status for {job_name}: {e}")
            return {"status": "Error", "job_name": job_name, "error": str(e)}

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

            # Schedule retry
            frappe.enqueue(
                "verenigingen.utils.background_jobs.retry_job_execution",
                job_name=job_name,
                delay=delay,
                queue="default",
                timeout=300,
            )

            # Update job status
            job_status.update(
                {"status": "Retrying", "retry_count": retry_count + 1, "retry_scheduled_at": now()}
            )

            cache_key = f"job_status_{job_name}"
            frappe.cache().set(cache_key, job_status, expires_in_sec=3600)

            return True

        except Exception as e:
            frappe.log_error(f"Failed to retry job {job_name}: {e}")
            return False


# Background Job Execution Functions
# These functions are called by the queued jobs


def execute_member_payment_history_update(member_name: str, payment_entry: str = None, job_name: str = None):
    """Execute member payment history update in background"""
    try:
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Running")

        # Get member document
        member = frappe.get_doc("Member", member_name)

        # Use optimized payment history update method
        result = refresh_member_financial_history_optimized(member, payment_entry)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Completed", result)

        return result

    except Exception as e:
        error_msg = f"Failed to update payment history for {member_name}: {e}"
        frappe.log_error(error_msg)

        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Failed", error=error_msg)

        raise


def execute_expense_event_processing(expense_doc_name: str, event_type: str, job_name: str = None):
    """Execute expense event processing in background"""
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


def execute_donor_auto_creation(payment_doc_name: str, job_name: str = None):
    """Execute donor auto creation in background"""
    try:
        if job_name:
            BackgroundJobManager.update_job_status(job_name, "Running")

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


def retry_job_execution(job_name: str, delay: int):
    """Retry job execution after delay"""
    import time

    time.sleep(delay)

    try:
        job_status = BackgroundJobManager.get_job_status(job_name)
        job_type = job_status.get("job_type")

        if job_type == "member_payment_history_update":
            execute_member_payment_history_update(
                member_name=job_status.get("member_name"),
                payment_entry=job_status.get("payment_entry"),
                job_name=job_name,
            )
        elif job_type == "expense_event_processing":
            execute_expense_event_processing(
                expense_doc_name=job_status.get("reference_name"),
                event_type="payment_made",  # Default
                job_name=job_name,
            )
        elif job_type == "donor_auto_creation":
            execute_donor_auto_creation(payment_doc_name=job_status.get("reference_name"), job_name=job_name)
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
        cached_result = frappe.cache().get(cache_key)

        if cached_result and not payment_entry:  # Skip cache if specific payment triggered update
            return {"status": "cached", "cache_hit": True, "execution_time": 0.001}

        # Clear existing payment history
        member_doc.payment_history = []

        # Batch query approach - eliminate N+1 queries
        result = load_payment_history_batch_optimized(member_doc)

        # Save with optimized flags
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
        frappe.cache().set(cache_key, cache_result, expires_in_sec=1800)

        return cache_result

    except Exception as e:
        execution_time = time.time() - start_time
        frappe.log_error(f"Optimized payment history refresh failed for {member_doc.name}: {e}")
        return {"status": "failed", "error": str(e), "execution_time": execution_time}


def load_payment_history_batch_optimized(member_doc) -> Dict[str, Any]:
    """
    Optimized batch loading of payment history to eliminate N+1 queries

    Instead of querying each invoice individually, this batches all queries
    """
    MAX_PAYMENT_HISTORY_ENTRIES = 20
    customer = member_doc.customer

    # 1. BATCH QUERY: Get all invoices with fields in single query
    base_fields = [
        "name",
        "posting_date",
        "due_date",
        "grand_total",
        "outstanding_amount",
        "status",
        "docstatus",
        "membership",
    ]

    # Check for coverage fields existence once
    coverage_fields = []
    if frappe.db.has_column("Sales Invoice", "custom_coverage_start_date"):
        coverage_fields.append("custom_coverage_start_date")
    if frappe.db.has_column("Sales Invoice", "custom_coverage_end_date"):
        coverage_fields.append("custom_coverage_end_date")

    query_fields = base_fields + coverage_fields

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "docstatus": ["in", [0, 1]],
        },
        fields=query_fields,
        order_by="posting_date desc",
        limit=MAX_PAYMENT_HISTORY_ENTRIES,
    )

    invoice_names = [inv.name for inv in invoices]

    if not invoice_names:
        return {"entries_processed": 0}

    # 2. BATCH QUERY: Get all payment entry references for these invoices
    payment_references = frappe.get_all(
        "Payment Entry Reference",
        filters={"reference_doctype": "Sales Invoice", "reference_name": ["in", invoice_names]},
        fields=["parent", "reference_name", "allocated_amount"],
    )

    # Group payment references by invoice
    payment_refs_by_invoice = {}
    payment_entry_names = set()

    for ref in payment_references:
        if ref.reference_name not in payment_refs_by_invoice:
            payment_refs_by_invoice[ref.reference_name] = []
        payment_refs_by_invoice[ref.reference_name].append(ref)
        payment_entry_names.add(ref.parent)

    # 3. BATCH QUERY: Get all payment entries in one query
    payment_entries = {}
    if payment_entry_names:
        payment_entry_list = frappe.get_all(
            "Payment Entry",
            filters={"name": ["in", list(payment_entry_names)]},
            fields=["name", "posting_date", "mode_of_payment", "paid_amount"],
        )
        payment_entries = {pe.name: pe for pe in payment_entry_list}

    # 4. BATCH QUERY: Get memberships for invoices that have them
    membership_names = [inv.membership for inv in invoices if inv.get("membership")]
    memberships = {}
    if membership_names:
        membership_list = frappe.get_all(
            "Membership", filters={"name": ["in", membership_names]}, fields=["name", "member", "status"]
        )
        memberships = {m.name: m for m in membership_list}

    # 5. BATCH QUERY: Get SEPA mandates for members
    member_names = [m.member for m in memberships.values() if m.get("member")]
    mandates = {}
    if member_names:
        mandate_list = frappe.get_all(
            "SEPA Mandate",
            filters={"member": ["in", member_names], "status": "Active"},
            fields=["name", "member", "status", "mandate_id", "iban"],
        )
        mandates = {m.member: m for m in mandate_list}

    # 6. BATCH QUERY: Get unreconciled payments
    reconciled_payment_names = list(payment_entry_names)
    unreconciled_payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": customer,
            "docstatus": 1,
            "name": ["not in", reconciled_payment_names or [""]],
        },
        fields=[
            "name",
            "posting_date",
            "paid_amount",
            "mode_of_payment",
            "status",
            "reference_no",
            "reference_date",
        ],
        order_by="posting_date desc",
        limit=MAX_PAYMENT_HISTORY_ENTRIES,
    )

    # 7. Process invoices using batch-loaded data
    entries_processed = 0

    for invoice in invoices:
        try:
            # Determine transaction type and reference
            transaction_type = "Regular Invoice"
            reference_doctype = None
            reference_name = None

            if invoice.get("membership"):
                transaction_type = "Membership Invoice"
                reference_doctype = "Membership"
                reference_name = invoice.membership

            # Process payments using pre-loaded data
            payment_refs = payment_refs_by_invoice.get(invoice.name, [])
            payment_status = "Unpaid"
            payment_date = None
            payment_entry = None
            payment_method = None
            paid_amount = 0
            reconciled = 0

            if payment_refs:
                for ref in payment_refs:
                    allocated_amount = ref.allocated_amount or 0
                    if allocated_amount < 0:
                        frappe.log_error(
                            f"Negative allocated amount in payment entry {ref.parent}: {allocated_amount}",
                            "PaymentValidation",
                        )
                    paid_amount += float(allocated_amount)

                # Get most recent payment using pre-loaded data
                payment_names = [ref.parent for ref in payment_refs]
                recent_payments = [payment_entries[name] for name in payment_names if name in payment_entries]

                if recent_payments:
                    recent_payment = max(recent_payments, key=lambda x: x.posting_date)
                    payment_entry = recent_payment.name
                    payment_date = recent_payment.posting_date
                    payment_method = recent_payment.mode_of_payment
                    reconciled = 1

            # Set payment status
            if invoice.docstatus == 0:
                payment_status = "Draft"
            elif invoice.status == "Paid":
                payment_status = "Paid"
            elif invoice.status == "Overdue":
                payment_status = "Overdue"
            elif invoice.status == "Cancelled":
                payment_status = "Cancelled"
            elif paid_amount > 0 and paid_amount < invoice.grand_total:
                payment_status = "Partially Paid"

            # Process SEPA mandate using pre-loaded data
            has_mandate = 0
            sepa_mandate = None
            mandate_status = None
            mandate_reference = None

            if reference_name and reference_name in memberships:
                membership = memberships[reference_name]
                if membership.get("sepa_mandate") and membership.sepa_mandate in mandates:
                    mandate = mandates[membership.sepa_mandate]
                    has_mandate = 1
                    sepa_mandate = mandate.name
                    mandate_status = mandate.status
                    mandate_reference = mandate.mandate_id

            if not has_mandate and default_mandate and default_mandate.name in mandates:
                mandate = mandates[default_mandate.name]
                has_mandate = 1
                sepa_mandate = mandate.name
                mandate_status = mandate.status
                mandate_reference = mandate.mandate_id

            # Get coverage dates from invoice data (already loaded)
            coverage_start_date = invoice.get("custom_coverage_start_date")
            coverage_end_date = invoice.get("custom_coverage_end_date")

            # Validate coverage dates
            if coverage_start_date and coverage_end_date and coverage_start_date > coverage_end_date:
                frappe.log_error(
                    f"Invalid coverage period for invoice {invoice.name}: "
                    f"start_date ({coverage_start_date}) > end_date ({coverage_end_date})",
                    "Coverage Date Validation Error",
                )
                coverage_start_date = None
                coverage_end_date = None

            # Add to payment history
            member_doc.append(
                "payment_history",
                {
                    "invoice": invoice.name,
                    "posting_date": invoice.posting_date,
                    "due_date": invoice.due_date,
                    "coverage_start_date": coverage_start_date,
                    "coverage_end_date": coverage_end_date,
                    "transaction_type": transaction_type,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "amount": invoice.grand_total,
                    "outstanding_amount": invoice.outstanding_amount,
                    "status": invoice.status,
                    "payment_status": payment_status,
                    "payment_date": payment_date,
                    "payment_entry": payment_entry,
                    "payment_method": payment_method,
                    "paid_amount": paid_amount,
                    "reconciled": reconciled,
                    "has_mandate": has_mandate,
                    "sepa_mandate": sepa_mandate,
                    "mandate_status": mandate_status,
                    "mandate_reference": mandate_reference,
                },
            )

            entries_processed += 1

        except Exception as e:
            frappe.log_error(
                f"Error processing invoice {invoice.name} in batch mode: {e}", "Invoice Processing Error"
            )
            continue

    # 8. Process unreconciled payments
    for payment in unreconciled_payments:
        try:
            # Check for donations
            donation = None
            if payment.reference_no:
                donations = frappe.get_all(
                    "Donation", filters={"payment_id": payment.reference_no}, fields=["name"], limit=1
                )
                if donations:
                    donation = donations[0].name

            member_doc.append(
                "payment_history",
                {
                    "invoice": None,
                    "posting_date": payment.posting_date,
                    "due_date": None,
                    "coverage_start_date": None,
                    "coverage_end_date": None,
                    "transaction_type": "Unreconciled Payment",
                    "reference_doctype": "Donation" if donation else None,
                    "reference_name": donation,
                    "amount": payment.paid_amount,
                    "outstanding_amount": 0,
                    "status": payment.status,
                    "payment_status": "Paid",
                    "payment_date": payment.posting_date,
                    "payment_entry": payment.name,
                    "payment_method": payment.mode_of_payment,
                    "paid_amount": payment.paid_amount,
                    "reconciled": 0,
                    "has_mandate": 0,
                    "sepa_mandate": None,
                    "mandate_status": None,
                    "mandate_reference": None,
                },
            )

            entries_processed += 1

        except Exception as e:
            frappe.log_error(f"Error processing unreconciled payment {payment.name}: {e}")
            continue

    return {"entries_processed": entries_processed}


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


def queue_member_payment_history_update_handler(doc, method=None):
    """
    Event handler for payment entry changes - queues background job

    This replaces the synchronous update_member_payment_history in hooks.py
    """
    try:
        if doc.party_type != "Customer":
            return

        # Get all members for this customer
        members = frappe.get_all("Member", filters={"customer": doc.party}, fields=["name"])

        for member_doc in members:
            # Queue background job for each member
            job_id = BackgroundJobManager.queue_member_payment_history_update(
                member_name=member_doc.name, payment_entry=doc.name, priority="default"
            )

            # Log for monitoring
            frappe.logger().info(f"Queued payment history update for member {member_doc.name}, job: {job_id}")

    except Exception as e:
        frappe.log_error(f"Failed to queue payment history updates for payment {doc.name}: {e}")
        # Don't raise - we don't want to block the payment entry submission


def queue_expense_event_processing_handler(doc, method=None):
    """
    Event handler for expense events - queues background job

    This replaces the synchronous expense event emission in hooks.py
    """
    try:
        # Determine event type based on method
        if method == "on_submit":
            event_type = "payment_made"
        elif method == "on_update_after_submit":
            event_type = "claim_approved"
        elif method == "on_cancel":
            event_type = "claim_cancelled"
        else:
            event_type = "payment_made"  # Default

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
