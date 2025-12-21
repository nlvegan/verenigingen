"""
Mollie Payment Processing Page
Streamlined interface for processing Mollie payments as membership dues and bank transactions.
"""

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    user_has_any_role,
    validate_mollie_payment_ids,
)
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


def get_context(context):
    """Get context for Mollie payment processing page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check permissions - only administrators and staff
    if not has_payment_processing_access():
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Mollie Payment Processing")

    # Ensure CSRF token is available
    from frappe.sessions import get_csrf_token

    context.csrf_token = get_csrf_token()

    # Get Mollie settings info
    try:
        # Use config service for test_mode
        context.test_mode = get_mollie_config().is_test_mode()
        context.api_key_type = "test" if context.test_mode else "live"

        # Check if API keys configured
        mollie_settings = frappe.get_single("Mollie Settings")
        context.mollie_configured = bool(mollie_settings.test_secret_key or mollie_settings.live_secret_key)
        context.mollie_settings = mollie_settings
    except Exception:
        context.mollie_configured = False
        context.test_mode = True
        context.api_key_type = "unknown"
        context.mollie_settings = frappe._dict({"payment_retrieval_days_back_limit": 1825})

    return context


def has_payment_processing_access():
    """Check if current user has access to payment processing page"""
    return user_has_any_role(
        [
            "System Manager",
            "Administrator",
            "Verenigingen Administrator",
            "Verenigingen Staff",
            "Treasurer",
        ]
    )


# =============================================================================
# MEMBERSHIP DUES PAYMENT PROCESSOR API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def retrieve_customer_payments_for_processing(customer_id, limit=250):
    """
    Retrieve all payment transactions for a customer ID with processing status.

    This is Phase 1 of the two-stage dues payment processing:
    - Retrieves all payments for the customer
    - Checks which payments are already processed (have Payment Entry)
    - Identifies payment type (dues vs donation)
    - Finds associated member for dues payments
    - Returns list with processable flag for UI selection

    Security: POST-only to prevent CSRF attacks on financial operations
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.retrieve_customer_payments_for_processing(customer_id, int(limit))

    except Exception as e:
        frappe.log_error(f"Mollie retrieve customer payments error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def batch_process_dues_payments(payment_ids, customer_id=None):
    """
    Process selected membership dues payments in batch.

    This is Phase 2 of the two-stage dues payment processing:
    - Takes list of payment IDs selected by user
    - Creates Payment Entry for each dues payment
    - Uses proper idempotency checks
    - Returns detailed results for each payment

    Args:
        payment_ids: JSON string or list of Mollie payment IDs
        customer_id: Optional customer ID for context

    Security: POST-only to prevent CSRF attacks on financial operations
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if it's a JSON string - use Frappe's secure parser
        if isinstance(payment_ids, str):
            import html

            try:
                payment_ids_decoded = html.unescape(payment_ids)
                payment_ids = frappe.parse_json(payment_ids_decoded)
            except (ValueError, TypeError) as e:
                frappe.throw(_("Invalid JSON format for payment_ids: {0}").format(str(e)))

        if not payment_ids or not isinstance(payment_ids, list):
            frappe.throw(_("Invalid payment_ids - must be a list"))

        # Validate each payment ID format using centralized helper
        try:
            validate_mollie_payment_ids(payment_ids)
        except ValueError as e:
            frappe.throw(str(e))

        # Enforce maximum batch size
        MAX_BATCH_SIZE = 50
        if len(payment_ids) > MAX_BATCH_SIZE:
            frappe.throw(
                _(
                    f"Cannot process more than {MAX_BATCH_SIZE} payments at once. Please process in smaller batches."
                )
            )

        # Rate limiting: 1 minute cooldown between batch operations (atomic operation)
        cache_key = f"dues_batch_limit:{frappe.session.user}"
        lock_acquired = frappe.cache().set(cache_key, "1", ex=60, nx=True)
        if not lock_acquired:
            remaining_ttl = frappe.cache().ttl(cache_key)
            frappe.throw(_("Please wait {0} seconds before next batch operation").format(remaining_ttl or 60))

        service = MollieDebugService()
        return service.batch_process_dues_payments(payment_ids, customer_id)

    except Exception as e:
        frappe.log_error(f"Mollie batch process dues payments error: {str(e)}")
        return {"error": str(e), "payment_ids": payment_ids}


# =============================================================================
# BULK MEMBER PAYMENT PROCESSOR API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_retrieve_all_member_payments(days_back=30, max_payments=5000, payment_status_filter=None):
    """
    Bulk retrieve payments for all members with Mollie customer IDs.

    Uses global payments endpoint for optimal performance - makes ~1 API call
    per 250 payments instead of 1 API call per member (N+1 problem).

    Args:
        days_back: Number of days back to check (default: 30)
        max_payments: Maximum total payments to retrieve (default: 5000)
        payment_status_filter: Optional filter ('paid', 'pending', 'all')

    Returns:
        Dict with retrieval results including api_calls_made count

    Security: POST-only to prevent accidental heavy API operations
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        # Validate parameters - get max limit from Mollie Settings
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            max_days_back = mollie_settings.payment_retrieval_days_back_limit or 1825
        except Exception:
            max_days_back = 1825

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

        service = MollieDebugService()
        return service.bulk_retrieve_all_member_payments(days_back, max_payments, payment_status_filter)

    except Exception as e:
        frappe.log_error(f"Bulk retrieve member payments error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_process_member_payments(payment_ids, docstatus=0, payment_modes=None, create_bank_transactions=None):
    """
    Bulk process selected payments with intelligent per-payment mode selection.

    Args:
        payment_ids: JSON string or list of Mollie payment IDs
        docstatus: 0 for Draft, 1 for Submitted (default: 0)
        payment_modes: JSON string or dict mapping payment_id to {mode, matching_invoice}
                      Modes: 'bt_pe_reconcile' (BT + PE + reconcile) or 'bt_only' (BT only)
        create_bank_transactions: DEPRECATED - kept for backward compatibility

    Returns:
        Dict with processing results

    Security: POST-only to prevent accidental data creation
    """
    try:
        if not has_payment_processing_access():
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
                frappe.log_error(f"Could not parse payment_modes: {e}")
                payment_modes = None

        # Log deprecation warning if old parameter is used
        if create_bank_transactions is not None:
            frappe.logger().warning(
                "DEPRECATION: create_bank_transactions parameter is deprecated. "
                "Use payment_modes parameter instead."
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

                job_name = frappe.enqueue(
                    "verenigingen.templates.pages.mollie_payment_processing.process_payment_batch_job",
                    queue="long",
                    timeout=3600,
                    batch_num=i + 1,
                    payment_ids=batch_payment_ids,
                    docstatus=docstatus,
                    payment_modes=batch_payment_modes,
                    tracking_id=job_id,
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
        service = MollieDebugService()
        return service.bulk_process_member_payments(payment_ids, docstatus, payment_modes)

    except Exception as e:
        frappe.log_error(f"Bulk process member payments error: {str(e)}")
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
        tracking_id: Unique job identifier

    Returns:
        Dict with batch processing results
    """
    service = MollieDebugService()
    return service.process_payment_batch_background(
        batch_num=batch_num,
        payment_ids=payment_ids,
        docstatus=docstatus,
        payment_modes=payment_modes,
        job_id=tracking_id,
    )
