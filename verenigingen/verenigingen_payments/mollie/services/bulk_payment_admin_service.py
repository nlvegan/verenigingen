"""
Shared Mollie admin bulk-processing service.

Holds the bulk-processing core (`bulk_process_member_payments` and its
background-job worker `process_payment_batch_job`) extracted from the two
duplicated page controllers `mollie_payments_debug.py` and
`mollie_payment_processing.py`. Both pages' whitelisted endpoints now
delegate here as thin wrappers.

The access check is injected by each page wrapper via the keyword-only
`access_check` parameter (`has_mollie_debug_access` for the debug page,
`has_payment_processing_access` for the processing page) so this module
does not need to know which page invoked it.
"""

import frappe
from frappe import _

from verenigingen.verenigingen_payments.mollie.utils.common_helpers import validate_mollie_payment_ids


def bulk_process_member_payments(
    payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None, *, access_check
):
    """
    Bulk process selected payments with intelligent per-payment mode selection.

    Args:
        payment_ids: JSON string or list of Mollie payment IDs
        docstatus: 0 for Draft, 1 for Submitted (default: 0)
        payment_modes: JSON string or dict mapping payment_id to {mode, matching_invoice}
                      Modes: 'bt_pe_reconcile' (BT + PE + reconcile) or 'bt_only' (BT only)
        create_bank_transactions: DEPRECATED - kept for backward compatibility, ignored if payment_modes provided
        access_check: Callable invoked to check caller access; injected by the calling page wrapper.

    Returns:
        Dict with processing results

    Security: POST-only to prevent accidental data creation
    """
    try:
        if not access_check():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if it's a JSON string
        if isinstance(payment_ids, str):
            import html

            try:
                payment_ids_decoded = html.unescape(payment_ids)
                payment_ids = frappe.parse_json(payment_ids_decoded)
            except (ValueError, TypeError) as e:
                frappe.throw(_("Invalid JSON format for payment_ids: {0}").format(str(e)))

        if not payment_ids or not isinstance(payment_ids, list):
            frappe.throw(_("Invalid payment_ids - must be a list"))

        # Parse payment_modes if it's a JSON string
        if isinstance(payment_modes, str):
            import html

            try:
                payment_modes_decoded = html.unescape(payment_modes)
                payment_modes = frappe.parse_json(payment_modes_decoded)
            except (ValueError, TypeError) as e:
                frappe.log_error(
                    message=f"Could not parse payment_modes: {e}", title="Could not parse payment_modes"
                )
                payment_modes = None

        # Log deprecation warning if old parameter is used
        if create_bank_transactions is not None:
            frappe.logger().warning(
                "DEPRECATION: create_bank_transactions parameter is deprecated. "
                "Use payment_modes parameter instead. This parameter will be removed in a future version."
            )

        # Validate payment ID format using centralized helper
        try:
            validate_mollie_payment_ids(payment_ids)
        except ValueError as e:
            frappe.throw(str(e))

        # Validate docstatus
        try:
            docstatus = int(docstatus)
            if docstatus not in [0, 1]:
                docstatus = 0
        except (ValueError, TypeError):
            docstatus = 0

        # Automatic batching for large requests
        MAX_BATCH_SIZE = 100
        if len(payment_ids) > MAX_BATCH_SIZE:
            # Queue as background jobs in batches of 100
            import uuid
            from math import ceil

            job_id = str(uuid.uuid4())[:8]
            num_batches = ceil(len(payment_ids) / MAX_BATCH_SIZE)

            frappe.logger().info(
                f"Large batch detected ({len(payment_ids)} payments). "
                f"Queueing {num_batches} background jobs with ID: {job_id}"
            )

            # Split into batches and queue each
            batch_jobs = []
            for i in range(num_batches):
                start_idx = i * MAX_BATCH_SIZE
                end_idx = min((i + 1) * MAX_BATCH_SIZE, len(payment_ids))
                batch_payment_ids = payment_ids[start_idx:end_idx]

                # Extract payment_modes for this batch
                batch_payment_modes = None
                if payment_modes:
                    batch_payment_modes = {
                        pid: payment_modes.get(pid) for pid in batch_payment_ids if pid in payment_modes
                    }

                # Queue background job
                # Note: job_id is a reserved parameter in frappe.enqueue, so we use tracking_id instead
                job_name = frappe.enqueue(
                    "verenigingen.verenigingen_payments.mollie.services.bulk_payment_admin_service.process_payment_batch_job",
                    queue="long",
                    timeout=3600,  # 1 hour timeout per batch
                    batch_num=i + 1,
                    payment_ids=batch_payment_ids,
                    docstatus=docstatus,
                    payment_modes=batch_payment_modes,
                    tracking_id=job_id,  # Use tracking_id instead of job_id
                )

                batch_jobs.append(
                    {
                        "batch_num": i + 1,
                        "payment_count": len(batch_payment_ids),
                        "job_name": job_name,
                    }
                )

            return {
                "queued": True,
                "job_id": job_id,
                "total_payments": len(payment_ids),
                "num_batches": num_batches,
                "batch_size": MAX_BATCH_SIZE,
                "batches": batch_jobs,
                "message": _(
                    "Queued {0} batches for background processing. "
                    "Job ID: {1}. Check background jobs for progress."
                ).format(num_batches, job_id),
            }

        # Small batch - process synchronously
        from verenigingen.services.mollie_debug_service import MollieDebugService

        service = MollieDebugService()
        return service.bulk_process_member_payments(payment_ids, docstatus, payment_modes)

    except Exception as e:
        frappe.log_error(
            message=f"Bulk process member payments error: {str(e)}",
            title="Bulk process member payments error",
        )
        return {"error": str(e), "payment_ids": payment_ids if isinstance(payment_ids, list) else []}


def process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id):
    """
    Background job worker function for processing payment batches.

    This is a module-level function that can be called by frappe.enqueue().
    It instantiates the service and delegates to the instance method.

    Args:
        batch_num: Batch number for tracking
        payment_ids: List of payment IDs to process
        docstatus: 0 for Draft, 1 for Submitted
        payment_modes: Dict mapping payment_id to {mode, matching_invoice}
        tracking_id: Unique job identifier (using tracking_id because job_id is reserved by frappe.enqueue)

    Returns:
        Dict with batch processing results
    """
    from verenigingen.services.mollie_debug_service import MollieDebugService

    service = MollieDebugService()
    return service.process_payment_batch_background(
        batch_num=batch_num,
        payment_ids=payment_ids,
        docstatus=docstatus,
        payment_modes=payment_modes,
        job_id=tracking_id,  # Pass as job_id to the service method
    )
