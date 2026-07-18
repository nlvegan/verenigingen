"""
Mollie Payment Processing Page
Streamlined interface for processing Mollie payments as membership dues and bank transactions.
"""

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import require_login
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.settings_utils import get_mollie_days_back_limit, populate_mollie_context
from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    user_has_any_role,
    validate_mollie_payment_ids,
)


def get_context(context):
    """Get context for Mollie payment processing page"""
    require_login()

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
    populate_mollie_context(context)

    return context


def has_payment_processing_access():
    """Check if current user has access to payment processing page"""
    return user_has_any_role(
        [
            Roles.SYSTEM_MANAGER,
            "Administrator",
            Roles.VERENIGINGEN_ADMIN,
            Roles.VERENIGINGEN_STAFF,
            "Treasurer",
        ]
    )


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


# =============================================================================
# MEMBERSHIP DUES PAYMENT PROCESSOR API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def retrieve_customer_payments_for_processing(customer_id: str, limit: int = 250):
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
        frappe.log_error(
            message=f"Mollie retrieve customer payments error: {str(e)}",
            title="Mollie retrieve customer payments error",
        )
        return {"error": str(e), "customer_id": customer_id}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def batch_process_dues_payments(payment_ids: str, customer_id: str = None):
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
        frappe.log_error(
            message=f"Mollie batch process dues payments error: {str(e)}",
            title="Mollie batch process dues payments error",
        )
        return {"error": str(e), "payment_ids": payment_ids}


# =============================================================================
# BULK MEMBER PAYMENT PROCESSOR API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_retrieve_all_member_payments(
    days_back: int = 30,
    max_payments: int = 5000,
    payment_status_filter: str = None,
    retrieval_mode: str = "customer",
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

    Returns:
        Dict with retrieval results including api_calls_made count

    Security: POST-only to prevent accidental heavy API operations
    """
    try:
        if not has_payment_processing_access():
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
        service = MollieDebugService()
        return service.bulk_retrieve_all_member_payments(days_back, max_payments, payment_status_filter)

    except Exception as e:
        frappe.log_error(
            message=f"Bulk retrieve member payments error: {str(e)}",
            title="Bulk retrieve member payments error",
        )
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def bulk_process_member_payments(
    payment_ids: str, docstatus: int = 0, payment_modes: str = None, create_bank_transactions: str = None
):
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
    return bulk_payment_admin_service.bulk_process_member_payments(
        payment_ids,
        docstatus,
        payment_modes,
        create_bank_transactions,
        access_check=has_payment_processing_access,
    )


def process_payment_batch_job(batch_num, payment_ids, docstatus, payment_modes, tracking_id):
    """
    Background job worker function for processing payment batches.

    Back-compat shim: in-flight jobs queued under this page's old dotted path
    still resolve here and delegate to the consolidated service.

    Args:
        batch_num: Batch number for tracking
        payment_ids: List of payment IDs to process
        docstatus: 0 for Draft, 1 for Submitted
        payment_modes: Dict mapping payment_id to {mode, matching_invoice}
        tracking_id: Unique job identifier

    Returns:
        Dict with batch processing results
    """
    return bulk_payment_admin_service.process_payment_batch_job(
        batch_num, payment_ids, docstatus, payment_modes, tracking_id
    )


# =============================================================================
# HISTORICAL PAYMENT RECOVERY API ENDPOINTS
# =============================================================================


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def scan_incomplete_payments() -> dict:
    """
    Scan for payments that are partially processed (missing documents).

    Analyzes all Bank Transactions to find gaps where:
    - Bank Transaction exists but Payment Entry is missing
    - Bank Transaction exists but Sales Invoice is missing
    - Bank Transaction and Payment Entry exist but are not linked

    Returns:
        Dict with gap analysis including statistics and detailed list
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        from verenigingen.utils.payment_processing_recovery import analyze_payment_gaps

        result = analyze_payment_gaps()

        # Enhance the result with additional UI-friendly data
        result["has_gaps"] = result["total_bank_transactions"] > result["complete"]
        result["completion_rate"] = (
            round(result["complete"] / result["total_bank_transactions"] * 100, 1)
            if result["total_bank_transactions"] > 0
            else 100
        )

        # Group gaps by missing document type for easier filtering
        gaps_by_type = {
            "missing_invoice": [],
            "missing_payment_entry": [],
            "missing_both": [],
            "missing_link": [],
        }

        for gap in result.get("gap_details", []):
            missing = gap.get("missing", [])
            if "Sales Invoice" in missing and "Payment Entry" in missing:
                gaps_by_type["missing_both"].append(gap)
            elif "Sales Invoice" in missing:
                gaps_by_type["missing_invoice"].append(gap)
            elif "Payment Entry" in missing:
                gaps_by_type["missing_payment_entry"].append(gap)
            elif "Bank Transaction → Payment Entry Link" in missing or "Sales Invoice Link" in missing:
                gaps_by_type["missing_link"].append(gap)

        result["gaps_by_type"] = gaps_by_type

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Scan incomplete payments error: {str(e)}", title="Scan incomplete payments error"
        )
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def preview_payment_recovery(payment_ids: str = None, max_payments: int = 100):
    """
    Preview what documents would be created to complete partial payments.

    Args:
        payment_ids: Optional JSON list of specific payment IDs to preview.
                    If None, previews all incomplete payments.
        max_payments: Maximum number of payments to preview (default: 100)

    Returns:
        Dict with preview of what would be created for each payment
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if provided
        if payment_ids and isinstance(payment_ids, str):
            import html

            try:
                payment_ids = frappe.parse_json(html.unescape(payment_ids))
            except (ValueError, TypeError):
                payment_ids = None

        from verenigingen.utils.payment_processing_recovery import complete_partial_payments

        result = complete_partial_payments(
            payment_ids=payment_ids,
            dry_run=True,
            max_payments=int(max_payments),
        )

        # Add summary statistics for UI
        if result.get("results"):
            would_create = {
                "bank_transactions": 0,
                "payment_entries": 0,
                "sales_invoices": 0,
                "links": 0,
            }
            for item in result["results"]:
                for doc_type in item.get("would_create", []):
                    if "Bank Transaction" in doc_type:
                        would_create["bank_transactions"] += 1
                    elif "Payment Entry" in doc_type:
                        would_create["payment_entries"] += 1
                    elif "Sales Invoice" in doc_type:
                        would_create["sales_invoices"] += 1
                    elif "Link" in doc_type:
                        would_create["links"] += 1

            result["would_create_summary"] = would_create

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Preview payment recovery error: {str(e)}", title="Preview payment recovery error"
        )
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def execute_payment_recovery(payment_ids: str = None, max_payments: int = 50):
    """
    Execute payment recovery to create missing documents.

    Creates missing Bank Transactions, Payment Entries, and Sales Invoices
    for partially processed payments.

    Args:
        payment_ids: Optional JSON list of specific payment IDs to process.
                    If None, processes all incomplete payments.
        max_payments: Maximum number of payments to process (default: 50)

    Returns:
        Dict with processing results including created documents

    Security: Enforces smaller batch size than preview for safety
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if provided
        if payment_ids and isinstance(payment_ids, str):
            import html

            try:
                payment_ids = frappe.parse_json(html.unescape(payment_ids))
            except (ValueError, TypeError):
                payment_ids = None

        # Validate payment IDs if provided
        if payment_ids:
            try:
                validate_mollie_payment_ids(payment_ids)
            except ValueError as e:
                frappe.throw(str(e))

        # Enforce reasonable batch size for live execution
        max_payments = min(int(max_payments), 100)

        from verenigingen.utils.payment_processing_recovery import complete_partial_payments

        result = complete_partial_payments(
            payment_ids=payment_ids,
            dry_run=False,
            max_payments=max_payments,
        )

        # Add execution summary
        result["execution_summary"] = {
            "documents_created": {
                "bank_transactions": sum(1 for r in result.get("results", []) if r.get("bank_transaction")),
                "payment_entries": sum(1 for r in result.get("results", []) if r.get("payment_entry")),
                "sales_invoices": sum(1 for r in result.get("results", []) if r.get("sales_invoice")),
            }
        }

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Execute payment recovery error: {str(e)}", title="Execute payment recovery error"
        )
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_payment_status(payment_id: str):
    """
    Get detailed processing status for a single payment.

    Args:
        payment_id: Mollie payment ID (tr_xxx format)

    Returns:
        Dict with complete status information for the payment
    """
    try:
        if not has_payment_processing_access():
            frappe.throw(_("Access denied"))

        if not payment_id or not isinstance(payment_id, str):
            frappe.throw(_("Invalid payment_id"))

        # Validate format
        try:
            validate_mollie_payment_ids([payment_id])
        except ValueError as e:
            frappe.throw(str(e))

        from verenigingen.utils.payment_processing_recovery import get_payment_processing_status

        return get_payment_processing_status(payment_id)

    except Exception as e:
        frappe.log_error(message=f"Get payment status error: {str(e)}", title="Get payment status error")
        return {"error": str(e)}
