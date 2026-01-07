"""
Ponto API Debug Page
Administrative interface for debugging Ponto API and creating payment links
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, standard_api
from verenigingen.utils.settings_utils import get_payments_settings


def get_context(context):
    """Get context for Ponto API debug page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check permissions - only administrators
    if not has_ponto_debug_access():
        frappe.throw(_("You don't have permission to access this debug page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Ponto API Debug")

    # Ensure CSRF token is available
    from frappe.sessions import get_csrf_token

    context.csrf_token = get_csrf_token()

    # Get Ponto settings info
    try:
        ponto_settings = frappe.get_single("Ponto Settings")
        context.ponto_configured = bool(
            ponto_settings.sandbox_client_id or ponto_settings.production_client_id
        )
        context.sandbox_mode = ponto_settings.sandbox_mode
        context.ponto_settings = ponto_settings

        # Activation status from userinfo
        context.organization_name = ponto_settings.organization_name or ""
        context.onboarding_complete = ponto_settings.onboarding_complete
        context.payments_activated = ponto_settings.payments_activated
        context.payment_requests_activated = ponto_settings.payment_requests_activated
        context.payments_activation_requested = ponto_settings.payments_activation_requested
        context.payment_requests_activation_requested = ponto_settings.payment_requests_activation_requested
        context.last_status_refresh = ponto_settings.last_status_refresh

        # Get default creditor info from Verenigingen Payments Settings
        payments_settings = get_payments_settings()
        context.default_creditor_name = payments_settings.company_account_holder or ""
        context.default_creditor_iban = payments_settings.company_iban or ""
        # ponto_payment_description_template remains in Verenigingen Settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        context.description_template = (
            verenigingen_settings.ponto_payment_description_template
            or "Membership dues MEMBER_NAME (MEMBER_ID) - COVERAGE_START to COVERAGE_END"
        )

    except Exception:
        context.ponto_configured = False
        context.sandbox_mode = True
        context.default_creditor_name = ""
        context.default_creditor_iban = ""
        context.description_template = ""
        context.ponto_settings = frappe._dict({})
        context.organization_name = ""
        context.onboarding_complete = False
        context.payments_activated = False
        context.payment_requests_activated = False
        context.payments_activation_requested = False
        context.payment_requests_activation_requested = False
        context.last_status_refresh = None

    # Get existing payment links for reference
    try:
        context.recent_payment_links = frappe.get_all(
            "Ponto Payment Link",
            filters={},
            fields=["name", "amount", "status", "payment_type", "description", "creation"],
            order_by="creation desc",
            limit=10,
        )
    except Exception:
        context.recent_payment_links = []

    return context


def has_ponto_debug_access():
    """Check if current user has access to Ponto debug page"""
    user_roles = frappe.get_roles(frappe.session.user)
    allowed_roles = [
        "System Manager",
        "Administrator",
        "Verenigingen Administrator",
        "Verenigingen Staff",
        "Treasurer",
    ]
    return any(role in user_roles for role in allowed_roles)


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def create_payment_link(
    amount,
    description,
    payment_type="One-Time",
    frequency=None,
    creditor_name=None,
    creditor_iban=None,
    member=None,
    sales_invoice=None,
):
    """
    Create a new Ponto Payment Link for testing/debugging.

    Args:
        amount: Payment amount in EUR
        description: Payment description
        payment_type: "One-Time" or "Periodic"
        frequency: For periodic payments: "Monthly", "Quarterly", "Annually"
        creditor_name: Organization name (uses default if not provided)
        creditor_iban: Organization IBAN (uses default if not provided)
        member: Optional linked member
        sales_invoice: Optional linked sales invoice

    Returns:
        Dict with created payment link details
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        # Validate amount
        try:
            amount = float(amount)
            if amount <= 0:
                frappe.throw(_("Amount must be greater than zero"))
        except (ValueError, TypeError):
            frappe.throw(_("Invalid amount format"))

        # Get defaults if not provided
        if not creditor_name or not creditor_iban:
            payments_settings = get_payments_settings()
            if not creditor_name:
                creditor_name = payments_settings.company_account_holder
            if not creditor_iban:
                creditor_iban = payments_settings.company_iban

        if not creditor_name or not creditor_iban:
            frappe.throw(
                _("Creditor name and IBAN are required. Configure them in Verenigingen Payments Settings.")
            )

        # Create the payment link document
        doc = frappe.new_doc("Ponto Payment Link")
        doc.amount = amount
        doc.currency = "EUR"
        doc.description = description
        doc.payment_type = payment_type
        doc.creditor_name = creditor_name
        doc.creditor_iban = creditor_iban

        if payment_type == "Periodic" and frequency:
            doc.frequency = frequency

        if member:
            doc.member = member

        if sales_invoice:
            doc.sales_invoice = sales_invoice

        doc.insert()

        frappe.msgprint(
            _("Payment Link created: {0}").format(doc.name),
            indicator="green",
            alert=True,
        )

        return {
            "success": True,
            "name": doc.name,
            "status": doc.status,
            "amount": doc.amount,
            "description": doc.description,
            "payment_type": doc.payment_type,
            "creditor_name": doc.creditor_name,
            "creditor_iban": doc.creditor_iban,
        }

    except Exception as e:
        frappe.log_error(title="Ponto Payment Link Error", message=f"Create failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def submit_payment_link(payment_link_name):
    """
    Submit a payment link to create it in Ponto API.

    Args:
        payment_link_name: Name of the Ponto Payment Link document

    Returns:
        Dict with submission result including redirect_link
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        doc = frappe.get_doc("Ponto Payment Link", payment_link_name)

        if doc.docstatus != 0:
            frappe.throw(_("Payment link is already submitted"))

        doc.submit()

        return {
            "success": True,
            "name": doc.name,
            "status": doc.status,
            "redirect_link": doc.redirect_link,
            "ponto_request_id": doc.ponto_request_id,
        }

    except Exception as e:
        frappe.log_error(title="Ponto Payment Link Error", message=f"Submit failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def refresh_payment_link_status(payment_link_name):
    """
    Refresh the status of a payment link from Ponto API.

    Args:
        payment_link_name: Name of the Ponto Payment Link document

    Returns:
        Dict with refreshed status
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        doc = frappe.get_doc("Ponto Payment Link", payment_link_name)
        result = doc.refresh_status()

        return {
            "success": True,
            "name": doc.name,
            "status": doc.status,
            "debtor_name": doc.debtor_name,
            "debtor_iban": doc.debtor_iban,
            "debtor_bank": doc.debtor_bank,
        }

    except Exception as e:
        frappe.log_error(title="Ponto Payment Link Error", message=f"Refresh failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def list_payment_links(limit=20, status_filter=None):
    """
    List Ponto Payment Links.

    Args:
        limit: Maximum number of results
        status_filter: Optional status filter

    Returns:
        Dict with list of payment links
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        filters = {}
        if status_filter:
            filters["status"] = status_filter

        links = frappe.get_all(
            "Ponto Payment Link",
            filters=filters,
            fields=[
                "name",
                "amount",
                "currency",
                "description",
                "payment_type",
                "frequency",
                "status",
                "creditor_name",
                "redirect_link",
                "ponto_request_id",
                "member",
                "sales_invoice",
                "creation",
                "modified",
            ],
            order_by="creation desc",
            limit=int(limit),
        )

        return {
            "success": True,
            "count": len(links),
            "links": links,
        }

    except Exception as e:
        frappe.log_error(title="Ponto Payment Link Error", message=f"List failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def get_payment_link_details(payment_link_name):
    """
    Get full details of a payment link.

    Args:
        payment_link_name: Name of the Ponto Payment Link document

    Returns:
        Dict with payment link details
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        doc = frappe.get_doc("Ponto Payment Link", payment_link_name)

        return {
            "success": True,
            "name": doc.name,
            "amount": doc.amount,
            "currency": doc.currency,
            "description": doc.description,
            "payment_type": doc.payment_type,
            "frequency": doc.frequency,
            "status": doc.status,
            "creditor_name": doc.creditor_name,
            "creditor_iban": doc.creditor_iban,
            "redirect_link": doc.redirect_link,
            "ponto_request_id": doc.ponto_request_id,
            "debtor_name": doc.debtor_name,
            "debtor_iban": doc.debtor_iban,
            "debtor_bank": doc.debtor_bank,
            "member": doc.member,
            "sales_invoice": doc.sales_invoice,
            "payment_entry": doc.payment_entry,
            "total_payments_collected": doc.total_payments_collected,
            "docstatus": doc.docstatus,
            "creation": str(doc.creation),
            "modified": str(doc.modified),
        }

    except Exception as e:
        frappe.log_error(title="Ponto Payment Link Error", message=f"Get details failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def test_ponto_connection():
    """
    Test connection to Ponto API.

    Returns:
        Dict with connection test result
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        ponto_settings = frappe.get_single("Ponto Settings")
        result = ponto_settings.test_connection()

        return result

    except Exception as e:
        frappe.log_error(title="Ponto Connection Error", message=f"Test failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@standard_api(operation_type=OperationType.FINANCIAL)
def test_mtls_connection():
    """
    Test mTLS connection to Ibanity API.

    Tests:
    1. Certificate configuration
    2. mTLS handshake
    3. Userinfo endpoint (if accessible)

    Returns:
        Dict with detailed mTLS test results
    """
    try:
        if not has_ponto_debug_access():
            frappe.throw(_("Access denied"))

        from verenigingen.verenigingen_payments.ponto.core.ponto_client import PontoClient

        ponto_settings = frappe.get_single("Ponto Settings")

        results = {
            "mtls_enabled": ponto_settings.use_ibanity_mtls,
            "certificate_configured": bool(ponto_settings.ibanity_certificate),
            "private_key_configured": bool(ponto_settings.ibanity_private_key),
            "passphrase_configured": bool(ponto_settings.get_password("ibanity_key_passphrase")),
            "signature_cert_configured": bool(ponto_settings.signature_certificate),
            "signature_key_configured": bool(ponto_settings.signature_private_key),
            "api_url": ponto_settings.ibanity_api_url or "https://api.ibanity.com",
        }

        if not ponto_settings.use_ibanity_mtls:
            results[
                "message"
            ] = "mTLS is not enabled. Enable 'Use Ibanity mTLS Authentication' in Ponto Settings."
            return {"success": False, **results}

        if not ponto_settings.ibanity_certificate or not ponto_settings.ibanity_private_key:
            results["message"] = "Certificate and/or private key not configured."
            return {"success": False, **results}

        # Try to create a client (this tests certificate loading)
        try:
            client = PontoClient()
            results["client_created"] = True
            results["client_mtls_active"] = client._use_mtls
            results["client_base_url"] = client.BASE_URL
        except Exception as e:
            results["client_created"] = False
            results["client_error"] = str(e)
            results["message"] = f"Failed to create client with mTLS: {e}"
            return {"success": False, **results}

        # Try a simple API call to test mTLS handshake
        try:
            # Try to get userinfo endpoint
            response = client.get("/ponto-connect/userinfo")
            results["api_call_success"] = True
            results["api_response"] = response
            results["message"] = "mTLS connection successful"
            return {"success": True, **results}
        except Exception as e:
            error_str = str(e)
            results["api_call_success"] = False
            results["api_error"] = error_str

            # Interpret the error
            if "SSL" in error_str or "certificate" in error_str.lower():
                results["message"] = f"SSL/Certificate error - check certificate format: {error_str}"
            elif "401" in error_str or "authentication" in error_str.lower():
                results[
                    "message"
                ] = "Authentication failed - mTLS handshake succeeded but API rejected request"
            elif "404" in error_str:
                results["message"] = "Endpoint not found - mTLS may be working but endpoint path incorrect"
            else:
                results["message"] = f"API call failed: {error_str}"

            return {"success": False, **results}

    except Exception as e:
        frappe.log_error(title="Ponto mTLS Error", message=f"Test failed: {str(e)}")
        return {"success": False, "error": str(e)}
