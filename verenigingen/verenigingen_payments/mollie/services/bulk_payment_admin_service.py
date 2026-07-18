"""
Shared Mollie admin bulk-processing service.

Holds the bulk-processing core (`bulk_process_member_payments` and its
background-job worker `process_payment_batch_job`), the bulk-retrieval core
(`bulk_retrieve_all_member_payments` and its `_retrieve_global_payments_with_orphans`
helper), extracted from the two duplicated page controllers
`mollie_payments_debug.py` and `mollie_payment_processing.py`. Both pages'
whitelisted endpoints now delegate here as thin wrappers.

The access check is injected by each page wrapper via the keyword-only
`access_check` parameter (`has_mollie_debug_access` for the debug page,
`has_payment_processing_access` for the processing page) so this module
does not need to know which page invoked it.
"""

import frappe
from frappe import _

from verenigingen.utils.settings_utils import get_mollie_days_back_limit
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import validate_mollie_payment_ids


def bulk_retrieve_all_member_payments(
    days_back: int = 30,
    max_payments: int = 5000,
    payment_status_filter: str = None,
    retrieval_mode: str = "customer",
    *,
    access_check,
):
    """
    Bulk retrieve payments for all members with Mollie customer IDs.

    Uses global payments endpoint for optimal performance - makes ~1 API call
    per 250 payments instead of 1 API call per member (N+1 problem).

    Args:
        days_back: Number of days back to check (default: 30)
        max_payments: Maximum total payments to retrieve (default: 5000)
        payment_status_filter: Optional filter ('paid', 'pending', 'all')
        retrieval_mode: 'customer' (iterate members) or 'balance_transactions' (finds orphans)
        access_check: Callable invoked to check caller access; injected by the calling page wrapper.

    Returns:
        Dict with retrieval results including api_calls_made count

    Security: POST-only to prevent accidental heavy API operations
    """
    try:
        if not access_check():
            frappe.throw(_("Access denied"))

        # Validate parameters - get max limit from Mollie Settings
        max_days_back = get_mollie_days_back_limit()

        try:
            days_back = int(days_back)
            if days_back < 1 or days_back > max_days_back:
                days_back = 30
        except (ValueError, TypeError):
            days_back = 30

        try:
            max_payments = int(max_payments)
            if max_payments < 250 or max_payments > 10000:
                max_payments = 5000
        except (ValueError, TypeError):
            max_payments = 5000

        # Validate retrieval_mode
        if retrieval_mode not in ["customer", "global_payments"]:
            retrieval_mode = "customer"

        # Use global_payments mode to find all payments including orphans
        if retrieval_mode == "global_payments":
            return _retrieve_global_payments_with_orphans(days_back, max_payments, payment_status_filter)

        # Default: use MollieDebugService for customer-based retrieval
        from verenigingen.services.mollie_debug_service import MollieDebugService

        service = MollieDebugService()
        return service.bulk_retrieve_all_member_payments(days_back, max_payments, payment_status_filter)

    except Exception as e:
        frappe.log_error(
            message=f"Bulk retrieve member payments error: {str(e)}",
            title="Bulk retrieve member payments error",
        )
        return {"error": str(e)}


def _retrieve_global_payments_with_orphans(days_back: int, max_payments: int, payment_status_filter: str):
    """
    Retrieve ALL payments from Mollie globally and identify orphaned ones.

    Uses the global payments.list() endpoint (regular API key) to find all payments,
    then checks which ones can be matched to members.

    Uses centralized MemberPaymentMatcher for consistent matching with customer mode.
    Counting and filtering logic is aligned with bulk_retrieve_all_member_payments.

    Args:
        days_back: Number of days back to check
        max_payments: Maximum payments to retrieve
        payment_status_filter: Filter by payment status

    Returns:
        Dict with payments grouped by member match status
    """
    from datetime import datetime, timedelta

    from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
    from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
    from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
        get_member_payment_matcher,
    )
    from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
        get_bank_transaction_creator,
    )

    result = {
        "retrieval_mode": "global_payments",
        "total_payments_found": 0,  # Raw count from Mollie API before filtering
        "total_payments_after_filtering": 0,  # After all filters applied
        "total_filtered_by_duplicate": 0,
        "total_filtered_by_date": 0,
        "total_filtered_by_status": 0,
        "total_new_payments": 0,
        "orphaned_transactions": [],
        "customers": [],  # Payments that matched to members
        "errors": 0,
        "error_details": [],
        "processable_orphaned_count": 0,
        "started_at": frappe.utils.now(),
        "completed_at": None,
        "summary": "",
        "early_termination": False,
    }

    try:
        mollie_client = MollieClient()
        dues_processor = DuesPaymentProcessor()
        bt_creator = get_bank_transaction_creator()
        matcher = get_member_payment_matcher()

        # Calculate date cutoff (use created_at for consistency with customer mode)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        start_date_str = start_date.strftime("%Y-%m-%d")

        # Get global payments list
        client = mollie_client.sdk_client
        params = {"limit": min(250, max_payments)}

        all_payments = []
        total_fetched = 0
        seen_payment_ids = set()  # Track duplicates
        consecutive_old_payments = 0  # For early termination

        # Paginate through payments
        while total_fetched < max_payments:
            payment_list = client.payments.list(**params)
            batch = list(payment_list)

            if not batch:
                break

            for payment in batch:
                total_fetched += 1
                result["total_payments_found"] += 1  # Count raw API results

                # Deduplicate
                if payment.id in seen_payment_ids:
                    result["total_filtered_by_duplicate"] += 1
                    continue
                seen_payment_ids.add(payment.id)

                # Check date filter using created_at (consistent with customer mode)
                if hasattr(payment, "created_at") and payment.created_at:
                    payment_date_str = payment.created_at[:10]  # YYYY-MM-DD

                    if payment_date_str < start_date_str:
                        result["total_filtered_by_date"] += 1
                        consecutive_old_payments += 1
                        # Early termination after 50 consecutive old payments
                        if consecutive_old_payments >= 50:
                            result["early_termination"] = True
                            break
                        continue
                    else:
                        consecutive_old_payments = 0

                # Apply status filter
                if payment_status_filter and payment_status_filter != "all":
                    if payment.status != payment_status_filter:
                        result["total_filtered_by_status"] += 1
                        continue

                all_payments.append(payment)
                result["total_payments_after_filtering"] += 1

            # Check for early termination
            if result["early_termination"]:
                break

            # Check if there are more pages
            if payment_list.has_next():
                params["from"] = batch[-1].id
            else:
                break

        # Check which payments are already processed (batch query for efficiency)
        payment_ids = [p.id for p in all_payments]
        existing_bts = {}
        existing_pes = {}

        if payment_ids:
            # Batch check Bank Transactions
            placeholders = ", ".join(["%s"] * len(payment_ids))
            bt_results = frappe.db.sql(
                f"""
                SELECT reference_number, name FROM `tabBank Transaction`
                WHERE reference_number IN ({placeholders}) AND docstatus != 2
                """,
                tuple(payment_ids),
                as_dict=True,
            )
            existing_bts = {bt["reference_number"]: bt["name"] for bt in bt_results}

            # Batch check Payment Entries
            pe_results = frappe.db.sql(
                f"""
                SELECT reference_no, name FROM `tabPayment Entry`
                WHERE reference_no IN ({placeholders}) AND docstatus != 2
                """,
                tuple(payment_ids),
                as_dict=True,
            )
            existing_pes = {pe["reference_no"]: pe["name"] for pe in pe_results}

        # Process each payment
        member_payments = {}  # Group by member

        for payment in all_payments:
            payment_id = payment.id
            already_processed = payment_id in existing_bts or payment_id in existing_pes

            # Use centralized matcher for consistent member matching
            member_info = matcher.find_member_for_payment(payment)

            # Extract payment details
            currency = payment.amount["currency"] if payment.amount else "Unknown"
            amount = payment.amount["value"] if payment.amount else "Unknown"
            mollie_customer_id = getattr(payment, "customer_id", None)

            payment_info = {
                "payment_id": payment_id,
                "id": payment_id,  # Alias for compatibility
                "status": payment.status,
                "amount": f"{currency} {amount}",
                "amount_value": amount,
                "currency": currency,
                "description": getattr(payment, "description", "No description"),
                "customer_id": mollie_customer_id or "No customer",
                "subscription_id": getattr(payment, "subscription_id", None),
                "payment_type": dues_processor.identify_payment_type(payment),
                "paid_at": str(getattr(payment, "paid_at", None)),
                "created_at": str(getattr(payment, "created_at", None)),
                "already_processed": already_processed,
                "bank_transaction": existing_bts.get(payment_id),
                "payment_entry": existing_pes.get(payment_id),
            }

            if member_info:
                # Payment matches a member
                member_name = member_info["name"]
                if member_name not in member_payments:
                    member_payments[member_name] = {
                        "member": member_name,
                        "member_name": member_name,
                        "full_name": member_info.get("full_name", member_name),
                        "member_status": member_info.get("status"),
                        "customer_id": member_info.get("mollie_customer_id"),
                        "payments": [],
                    }

                # Determine processing mode
                is_processable = payment.status == "paid" and not already_processed and currency == "EUR"
                payment_info["processable"] = is_processable
                payment_info["processing_mode"] = "bt_pe_reconcile" if is_processable else None

                member_payments[member_name]["payments"].append(payment_info)

                if is_processable:
                    result["total_new_payments"] += 1
            else:
                # Orphaned payment - no member match
                # Allow processing even without customer_id (anonymous payments)
                is_orphan_processable = (
                    payment.status == "paid" and not already_processed and currency == "EUR"
                )

                # Determine processing mode based on available data
                if is_orphan_processable:
                    if mollie_customer_id:
                        processing_mode = "bt_only_orphaned"
                        reason = "Cannot match to any member (has Mollie customer)"
                    else:
                        processing_mode = "bt_only_anonymous"
                        reason = "Anonymous payment (no member, no Mollie customer)"
                else:
                    processing_mode = None
                    reason = "Cannot match to any member"

                payment_info["processable"] = is_orphan_processable
                payment_info["processing_mode"] = processing_mode
                payment_info["reason"] = reason

                result["orphaned_transactions"].append(payment_info)

                if is_orphan_processable:
                    result["total_new_payments"] += 1
                    result["processable_orphaned_count"] += 1

        # Convert member_payments dict to list
        result["customers"] = list(member_payments.values())

        # Calculate total matched to members (for parity with customer mode)
        total_member_payments = sum(len(c.get("payments", [])) for c in result["customers"])
        result["total_matched_to_members"] = total_member_payments
        result["total_orphaned"] = len(result["orphaned_transactions"])

        result["completed_at"] = frappe.utils.now()
        result["summary"] = (
            f"Retrieved {result['total_payments_found']} payments (raw), "
            f"{result['total_payments_after_filtering']} after filtering "
            f"(date: {result['total_filtered_by_date']}, status: {result['total_filtered_by_status']}, "
            f"dups: {result['total_filtered_by_duplicate']}). "
            f"{len(result['customers'])} members with {total_member_payments} payments, "
            f"{len(result['orphaned_transactions'])} orphaned ({result['processable_orphaned_count']} processable). "
            f"Total unprocessed: {result['total_new_payments']}"
        )

    except Exception as e:
        result["error"] = str(e)
        frappe.log_error(message=f"Global payments retrieval error: {e}", title="Mollie Payment Processing")

    return result


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
