"""
Mollie Payments Debug Page
Administrative interface for debugging Mollie API issues
"""

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
)
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


def get_context(context):
    """Get context for Mollie payments debug page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check permissions - only administrators
    if not has_mollie_debug_access():
        frappe.throw(_("You don't have permission to access this debug page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Mollie Payments Debug")

    # Ensure CSRF token is available
    from frappe.sessions import get_csrf_token

    context.csrf_token = get_csrf_token()

    # Get Mollie settings info
    try:
        # Use config service for test_mode
        context.test_mode = get_mollie_config().is_test_mode()
        context.api_key_type = "test" if context.test_mode else "live"

        # Check if API keys configured (requires password field access)
        mollie_settings = frappe.get_single("Mollie Settings")
        context.mollie_configured = bool(mollie_settings.test_secret_key or mollie_settings.live_secret_key)
        context.mollie_settings = mollie_settings  # Make settings available to template
    except Exception:
        context.mollie_configured = False
        context.test_mode = True
        context.api_key_type = "unknown"
        # Provide fallback object for template
        context.mollie_settings = frappe._dict({"payment_retrieval_days_back_limit": 1825})

    return context


def has_mollie_debug_access():
    """Check if current user has access to Mollie debug page"""
    allowed_roles = [
        "System Manager",
        "Administrator",
        "Verenigingen Administrator",
        "Verenigingen Staff",
        "Treasurer",
    ]

    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_customer(customer_id):
    """Debug a Mollie customer with detailed information"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_customer(customer_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug customer error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_subscription(subscription_id, customer_id=None):
    """Debug a specific subscription"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_subscription(subscription_id, customer_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug subscription error: {str(e)}")
        return {"error": str(e), "subscription_id": subscription_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_mandate(mandate_id, customer_id=None):
    """Debug a specific mandate"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_mandate(mandate_id, customer_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug mandate error: {str(e)}")
        return {"error": str(e), "mandate_id": mandate_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def admin_cancel_subscription(customer_id, subscription_id, reason="Administrative cancellation"):
    """Admin function to cancel any subscription"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.admin_cancel_subscription(customer_id, subscription_id, reason)

    except Exception as e:
        frappe.log_error(f"Admin subscription cancellation error: {str(e)}")
        frappe.throw(_(f"Failed to cancel subscription: {str(e)}"))


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def admin_revoke_mandate(customer_id, mandate_id, reason="Administrative revocation"):
    """Admin function to revoke any mandate"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.admin_revoke_mandate(customer_id, mandate_id, reason)

    except Exception as e:
        frappe.log_error(f"Admin mandate revocation error: {str(e)}")
        frappe.throw(_(f"Failed to revoke mandate: {str(e)}"))


def has_customer_deletion_access():
    """Check if current user has access to customer deletion (most restrictive)"""
    allowed_roles = ["Verenigingen Administrator"]

    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def admin_delete_customer(customer_id, reason="Administrative deletion", confirmation_text=None):
    """Admin function to delete entire customer (DANGEROUS - cascades to all subscriptions/mandates)"""
    try:
        if not has_customer_deletion_access():
            frappe.throw(_("Access denied - Verenigingen Administrator role required"))

        service = MollieDebugService()
        return service.admin_delete_customer(customer_id, reason, confirmation_text)

    except Exception as e:
        frappe.log_error(f"Admin customer deletion error: {str(e)}")
        frappe.throw(_(f"Failed to delete customer: {str(e)}"))


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_customers(limit=20):
    """List Mollie customers for easy ID lookup"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.list_customers(limit)

    except Exception as e:
        frappe.log_error(f"Mollie list customers API error: {str(e)}")
        return {"error": str(e), "limit": limit}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def search_customers_by_name(search_term, limit=20):
    """Search Mollie customers by name/email"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.search_customers_by_name(search_term, limit)

    except Exception as e:
        frappe.log_error(f"Mollie search customers API error: {str(e)}")
        return {"error": str(e), "search_term": search_term}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_payment(payment_id):
    """Debug a specific payment with comprehensive details"""
    if not has_mollie_debug_access():
        frappe.throw(_("Access denied"))

    service = MollieDebugService()
    result = service.debug_payment(payment_id)

    # Always return the result directly - Frappe will wrap it in {"message": result}
    # The service already handles exceptions and returns error info in the result dict
    return result


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_payments(customer_id=None, limit=20, status_filter=None):
    """List payments with optional filtering"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.list_payments(customer_id, limit, status_filter)

    except Exception as e:
        frappe.log_error(f"Mollie list payments error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id, "limit": limit}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_refund(refund_id, payment_id=None):
    """Debug a specific refund"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_refund(refund_id, payment_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug refund error: {str(e)}")
        return {"error": str(e), "refund_id": refund_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_chargebacks(customer_id=None, limit=20):
    """List chargebacks for debugging disputed transactions"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.list_chargebacks(customer_id, limit)

    except Exception as e:
        frappe.log_error(f"Mollie list chargebacks error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def debug_webhook_delivery(payment_id):
    """Debug webhook delivery status for a payment"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_webhook_delivery(payment_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug webhook error: {str(e)}")
        return {"error": str(e), "payment_id": payment_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def test_webhook_processing(payment_id):
    """
    Test webhook processing for a specific payment ID.

    Simulates webhook delivery by calling the unified webhook handler directly.
    Useful for testing older failed webhooks or manually triggering webhook processing.
    """
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.test_webhook_processing(payment_id)

    except Exception as e:
        frappe.log_error(f"Webhook test error: {str(e)}")
        return {"error": str(e), "payment_id": payment_id, "status": "error", "timestamp": frappe.utils.now()}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def admin_cancel_payment(payment_id, reason="Administrative cancellation"):
    """Admin function to cancel any payment (if cancellable)"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.admin_cancel_payment(payment_id, reason)

    except Exception as e:
        frappe.log_error(f"Mollie admin payment cancellation error: {str(e)}")
        return {"error": str(e), "payment_id": payment_id}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_test_payment(amount, description, customer_id=None):
    """Create a test payment that can be completed via Mollie checkout URL"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.create_test_payment(amount, description, customer_id)

    except Exception as e:
        frappe.log_error(f"Mollie test payment creation error: {str(e)}")
        return {"error": str(e), "status": "error"}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_subscription(customer_id, amount, interval, description, mandate_id=None, start_date=None):
    """Create a new Mollie subscription for testing purposes (Verenigingen Administrator only)"""
    try:
        # Restrict to Verenigingen Administrator only
        user_roles = frappe.get_roles(frappe.session.user)
        if "Verenigingen Administrator" not in user_roles:
            frappe.throw(_("Access denied - Verenigingen Administrator role required"))

        service = MollieDebugService()
        return service.create_subscription(customer_id, amount, interval, description, mandate_id, start_date)

    except Exception as e:
        frappe.log_error(f"Mollie subscription creation error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id, "status": "error"}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def list_subscriptions(customer_id, limit=50, active_only=True):
    """List subscriptions for a specific customer with optional filtering"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        if not customer_id:
            frappe.throw(_("Customer ID is required"))

        # Validate and sanitize limit
        try:
            limit = int(limit)
            if not 1 <= limit <= 250:
                limit = 50
        except (ValueError, TypeError):
            limit = 50

        # Convert string boolean from form data
        if isinstance(active_only, str):
            active_only = active_only.lower() in ("true", "1", "yes")

        service = MollieDebugService()
        return service.list_subscriptions(customer_id, limit, active_only)

    except Exception as e:
        frappe.log_error(f"Mollie list subscriptions error: {str(e)}")
        return {"error": str(e), "customer_id": customer_id}


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
        if not has_mollie_debug_access():
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
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if it's a JSON string - use Frappe's secure parser
        if isinstance(payment_ids, str):
            import html
            import re

            try:
                # Decode HTML entities first (form data may be HTML-escaped)
                payment_ids_decoded = html.unescape(payment_ids)
                payment_ids = frappe.parse_json(payment_ids_decoded)
            except (ValueError, TypeError) as e:
                frappe.throw(_("Invalid JSON format for payment_ids: {0}").format(str(e)))

        if not payment_ids or not isinstance(payment_ids, list):
            frappe.throw(_("Invalid payment_ids - must be a list"))

        # Validate each payment ID format to prevent injection attacks
        # Mollie payment IDs follow pattern: tr_[alphanumeric 10+ chars]
        mollie_payment_pattern = re.compile(r"^tr_[a-zA-Z0-9]{10,}$")
        for pid in payment_ids:
            if not isinstance(pid, str):
                frappe.throw(_("Payment ID must be a string: {0}").format(pid))
            if not mollie_payment_pattern.match(pid):
                frappe.throw(_("Invalid Mollie payment ID format: {0}").format(pid))

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


# Balance Transaction Processing API Endpoints


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_balance_info():
    """Get primary balance information"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            get_primary_balance_info,
        )

        return get_primary_balance_info()

    except Exception as e:
        frappe.log_error(f"Get balance info error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def process_recent_balance_transactions(days, limit=250):
    """Process balance transactions from recent days"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from datetime import datetime, timedelta

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            process_balance_transactions,
        )

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(days))

        return process_balance_transactions(
            from_date=start_date.strftime("%Y-%m-%d"),
            until_date=end_date.strftime("%Y-%m-%d"),
            limit=int(limit),
        )

    except Exception as e:
        frappe.log_error(f"Process recent balance transactions error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def process_balance_date_range(from_date, until_date, limit=250):
    """Process balance transactions for a specific date range"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            process_balance_transactions,
        )

        return process_balance_transactions(from_date=from_date, until_date=until_date, limit=int(limit))

    except Exception as e:
        frappe.log_error(f"Process balance date range error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def process_balance_historical_data(months_back, batch_size=250):
    """Process historical balance transactions in batches"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            process_historical_data,
        )

        return process_historical_data(months_back=int(months_back), batch_size=int(batch_size))

    except Exception as e:
        frappe.log_error(f"Process historical balance data error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_balance_transaction_status(transaction_id, include_mollie_data=False):
    """Check if a balance transaction has been processed"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            check_transaction_status,
        )

        # Convert string boolean from form data
        if isinstance(include_mollie_data, str):
            include_mollie_data = include_mollie_data.lower() in ("true", "1", "yes")

        return check_transaction_status(
            transaction_id=transaction_id, include_mollie_data=include_mollie_data
        )

    except Exception as e:
        frappe.log_error(f"Check balance transaction status error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def search_balance_transactions(search_term, limit=50):
    """Search Bank Transactions by description"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            search_transactions_by_description,
        )

        return search_transactions_by_description(search_term=search_term, limit=int(limit))

    except Exception as e:
        frappe.log_error(f"Search balance transactions error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def fetch_recent_for_search(limit=100):
    """Fetch recent balance transactions from Mollie for search"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            fetch_recent_transactions_for_search,
        )

        return fetch_recent_transactions_for_search(limit=int(limit))

    except Exception as e:
        frappe.log_error(f"Fetch recent transactions error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_balance_processing_statistics(days=30):
    """Get statistics about balance transaction processing"""
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            get_processing_statistics,
        )

        return get_processing_statistics(days=int(days))

    except Exception as e:
        frappe.log_error(f"Get balance processing statistics error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def sync_membership_end_dates_from_mollie(dry_run=True):
    """
    Sync membership end dates from Mollie subscription cancellation dates.

    This function retrieves Mollie subscription cancellation dates for
    terminated/banned/suspended members and updates their Member.member_end_date
    field. If a Membership record exists, it also updates the
    Membership.cancellation_date field.

    This is particularly useful for imported terminated members who may lack
    Membership records but still need their end date populated from Mollie.

    Args:
        dry_run: If True (default), only report what would be updated

    Returns:
        Dict with sync results including members checked and updates applied

    Security: POST-only to prevent accidental data modifications
    """
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        # Convert string boolean from form data
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        service = MollieDebugService()
        return service.sync_membership_end_dates_from_mollie(dry_run=dry_run)

    except Exception as e:
        frappe.log_error(f"Sync membership end dates error: {str(e)}")
        return {"error": str(e)}


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
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        # Validate parameters - get max limit from Mollie Settings
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            max_days_back = mollie_settings.payment_retrieval_days_back_limit or 1825
        except Exception:
            max_days_back = 1825  # Default to 5 years if settings not available

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
def bulk_process_member_payments(payment_ids, docstatus=0, create_bank_transactions=True):
    """
    Bulk process selected payments to create Payment Entries and/or Bank Transactions.

    Args:
        payment_ids: JSON string or list of Mollie payment IDs
        docstatus: 0 for Draft, 1 for Submitted (default: 0)
        create_bank_transactions: Whether to create Bank Transactions (default: True)

    Returns:
        Dict with processing results

    Security: POST-only to prevent accidental data creation
    """
    try:
        if not has_mollie_debug_access():
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

        # Validate payment ID format
        import re

        mollie_payment_pattern = re.compile(r"^tr_[a-zA-Z0-9]{10,}$")
        for pid in payment_ids:
            if not isinstance(pid, str):
                frappe.throw(_("Payment ID must be a string: {0}").format(pid))
            if not mollie_payment_pattern.match(pid):
                frappe.throw(_("Invalid Mollie payment ID format: {0}").format(pid))

        # Convert string boolean from form data
        if isinstance(create_bank_transactions, str):
            create_bank_transactions = create_bank_transactions.lower() in ("true", "1", "yes")

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

                # Queue background job
                # Note: job_id is a reserved parameter in frappe.enqueue, so we use tracking_id instead
                job_name = frappe.enqueue(
                    "verenigingen.templates.pages.mollie_payments_debug.process_payment_batch_job",
                    queue="long",
                    timeout=3600,  # 1 hour timeout per batch
                    batch_num=i + 1,
                    payment_ids=batch_payment_ids,
                    docstatus=docstatus,
                    create_bank_transactions=create_bank_transactions,
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
        service = MollieDebugService()
        return service.bulk_process_member_payments(payment_ids, docstatus, create_bank_transactions)

    except Exception as e:
        frappe.log_error(f"Bulk process member payments error: {str(e)}")
        return {"error": str(e), "payment_ids": payment_ids if isinstance(payment_ids, list) else []}


def process_payment_batch_job(batch_num, payment_ids, docstatus, create_bank_transactions, tracking_id):
    """
    Background job worker function for processing payment batches.

    This is a module-level function that can be called by frappe.enqueue().
    It instantiates the service and delegates to the instance method.

    Args:
        batch_num: Batch number for tracking
        payment_ids: List of payment IDs to process
        docstatus: 0 for Draft, 1 for Submitted
        create_bank_transactions: Whether to create Bank Transactions
        tracking_id: Unique job identifier (using tracking_id because job_id is reserved by frappe.enqueue)

    Returns:
        Dict with batch processing results
    """
    service = MollieDebugService()
    return service.process_payment_batch_background(
        batch_num=batch_num,
        payment_ids=payment_ids,
        docstatus=docstatus,
        create_bank_transactions=create_bank_transactions,
        job_id=tracking_id,  # Pass as job_id to the service method
    )


# Bulk Payment Checker API Endpoints


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def check_all_customers_for_new_payments(days_back=7, all_history=False, limit_per_customer=250):
    """
    Stage 1: Discovery - Check all Member Mollie customers for new payments.

    This is the discovery phase that identifies which payments exist but haven't
    been processed yet. Results should be reviewed before processing.

    Args:
        days_back: Number of days back to check (default: 7 for this week)
        all_history: If True, retrieve all historical payments (ignores days_back)
        limit_per_customer: Maximum payments to retrieve per customer (default: 250)

    Returns:
        Dict containing:
            - total_members: Total members with Mollie customer IDs
            - members_checked: Number of members successfully checked
            - total_payments_found: Total payments discovered
            - total_new_payments: Total unprocessed payments
            - customers: List of customer results
            - errors: Number of errors encountered
            - summary: Human-readable summary

    Security: POST-only to prevent CSRF attacks on financial operations
    """
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        # Rate limiting: 1 minute cooldown for discovery operations
        # Prevents DoS via repeated API calls to Mollie
        cache_key = f"bulk_payment_discovery_limit:{frappe.session.user}"
        rate_limit_seconds = 60

        lock_acquired = frappe.cache().set(cache_key, "1", ex=rate_limit_seconds, nx=True)
        if not lock_acquired:
            remaining_ttl = frappe.cache().ttl(cache_key)
            frappe.throw(
                _("Please wait {0} seconds before next discovery operation").format(
                    remaining_ttl or rate_limit_seconds
                )
            )

        # Validate and convert parameters
        try:
            days_back = int(days_back)
            if days_back < 1 or days_back > 365:
                days_back = 7
        except (ValueError, TypeError):
            days_back = 7

        # Convert string boolean from form data
        if isinstance(all_history, str):
            all_history = all_history.lower() in ("true", "1", "yes")

        try:
            limit_per_customer = int(limit_per_customer)
            if limit_per_customer < 1 or limit_per_customer > 250:
                limit_per_customer = 250
        except (ValueError, TypeError):
            limit_per_customer = 250

        from verenigingen.integrations.mollie.services.bulk_payment_checker import BulkPaymentChecker

        checker = BulkPaymentChecker()
        return checker.check_all_customers_for_new_payments(
            days_back=days_back, all_history=all_history, limit_per_customer=limit_per_customer
        )

    except Exception as e:
        frappe.log_error(f"Bulk payment check error: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=False, methods=["POST"])
@high_security_api(operation_type=OperationType.FINANCIAL)
def process_discovered_payments(payment_ids, dry_run=False):
    """
    Stage 2: Processing - Process selected payments through dues payment processor.

    Takes the payment IDs discovered in Stage 1 and processes them through
    the dues payment processor to create Payment Entries or Bank Transactions.

    Args:
        payment_ids: JSON string or list of Mollie payment IDs to process
        dry_run: If True, don't actually create Payment Entries (for testing)

    Returns:
        Dict with processing results:
            - total_requested: Number of payments requested to process
            - processed: Successfully processed payments
            - skipped: Payments skipped (already processed, wrong status, etc.)
            - errors: Number of errors
            - results: Detailed results for each payment

    Security: POST-only to prevent CSRF attacks on financial operations
    """
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        # Parse payment_ids if it's a JSON string - use Frappe's secure parser
        if isinstance(payment_ids, str):
            import html

            try:
                # Decode HTML entities first (form data may be HTML-escaped)
                payment_ids_decoded = html.unescape(payment_ids)
                payment_ids = frappe.parse_json(payment_ids_decoded)
            except (ValueError, TypeError) as e:
                frappe.throw(_("Invalid JSON format for payment_ids: {0}").format(str(e)))

        if not payment_ids or not isinstance(payment_ids, list):
            frappe.throw(_("Invalid payment_ids - must be a list"))

        # Validate each payment ID format to prevent injection attacks
        # Mollie payment IDs follow pattern: tr_[alphanumeric 10+ chars]
        import re

        mollie_payment_pattern = re.compile(r"^tr_[a-zA-Z0-9]{10,}$")
        for pid in payment_ids:
            if not isinstance(pid, str):
                frappe.throw(_("Payment ID must be a string: {0}").format(pid))
            if not mollie_payment_pattern.match(pid):
                frappe.throw(_("Invalid Mollie payment ID format: {0}").format(pid))

        # Enforce maximum batch size
        MAX_BATCH_SIZE = 100
        if len(payment_ids) > MAX_BATCH_SIZE:
            frappe.throw(
                _("Cannot process more than {0} payments at once. Please process in smaller batches.").format(
                    MAX_BATCH_SIZE
                )
            )

        # Convert string boolean from form data
        if isinstance(dry_run, str):
            dry_run = dry_run.lower() in ("true", "1", "yes")

        # Rate limiting: ALWAYS enforce, even for dry runs (prevents API abuse)
        # Different rate limits for dry run vs actual processing
        cache_key = f"bulk_payment_process_limit:{frappe.session.user}"
        rate_limit_seconds = 30 if dry_run else 120  # 30s for dry run, 2min for processing

        lock_acquired = frappe.cache().set(cache_key, "1", ex=rate_limit_seconds, nx=True)
        if not lock_acquired:
            remaining_ttl = frappe.cache().ttl(cache_key)
            operation_type = "dry run" if dry_run else "batch processing"
            frappe.throw(
                _("Please wait {0} seconds before next {1} operation").format(
                    remaining_ttl or rate_limit_seconds, operation_type
                )
            )

        from verenigingen.integrations.mollie.services.bulk_payment_checker import BulkPaymentChecker

        checker = BulkPaymentChecker()
        return checker.process_discovered_payments(payment_ids=payment_ids, dry_run=dry_run)

    except Exception as e:
        frappe.log_error(f"Bulk payment processing error: {str(e)}")
        return {"error": str(e), "payment_ids": payment_ids if isinstance(payment_ids, list) else []}
