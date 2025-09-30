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
        mollie_settings = frappe.get_single("Mollie Settings")
        context.mollie_configured = bool(mollie_settings.test_secret_key or mollie_settings.live_secret_key)
        context.test_mode = mollie_settings.test_mode
        context.api_key_type = "test" if mollie_settings.test_mode else "live"
    except Exception:
        context.mollie_configured = False
        context.test_mode = True
        context.api_key_type = "unknown"

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
    try:
        if not has_mollie_debug_access():
            frappe.throw(_("Access denied"))

        service = MollieDebugService()
        return service.debug_payment(payment_id)

    except Exception as e:
        frappe.log_error(f"Mollie debug payment error: {str(e)}")
        return {"error": str(e), "payment_id": payment_id}


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
