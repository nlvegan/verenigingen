"""
Payment Success Page

Handles users returning from external payment providers like Mollie.
Displays payment status and provides appropriate next steps.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from verenigingen.utils.security.api_security_framework import public_api
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token

# Whitelist of doctypes allowed for public payment status queries
# This prevents IDOR attacks by limiting what documents can be accessed
ALLOWED_PAYMENT_DOCTYPES = {"Donation", "Member Application", "Sales Invoice", "Payment Plan Payment"}

# Namespaces the HMAC return token minted for this page's Ponto branch (see
# guest_return_tokens.py / #1055 finding 1) -- distinct from ponto_pay.py's
# own "ponto_pay" purpose, since these are two different disclosure surfaces
# for the same Ponto Payment Link.
PONTO_RETURN_TOKEN_PURPOSE = "ponto_payment_link_return"

# One generic refusal for every reason validate_payment_document_access can
# fail, so the doctype-allowlist / existence / payment-reference ladder does
# not double as an existence oracle for every listed doctype (#1055).
_GENERIC_PAYMENT_ACCESS_DENIED = _("Invalid payment reference or document not found")


def validate_payment_document_access(doctype, docname, payment_id, token=None):
    """
    Validate that a document can be accessed for payment status display.

    Security checks:
    1. Doctype must be in the allowed whitelist
    2. Document must exist
    3. Ownership must be proven, either by a payment_id matching the
       document's on-file payment reference, or by a return token minted at
       the one URL-construction point we control (MollieSettings.get_redirect_url) --
       payment_id alone cannot always serve this role, since it does not
       exist yet at the point some flows build their redirect URL.

    A missing/wrong payment_id AND a missing/wrong token both refuse with
    the exact same message as an unknown doctype or docname (#1055) --
    ownership here used to be skippable simply by omitting payment_id, which
    is exactly what MollieSettings.get_redirect_url() and
    mollie_checkout.js's own return-URL construction did by default.

    Returns:
        tuple: (is_valid, doc_or_error_message)
    """
    # Check doctype is allowed
    if doctype not in ALLOWED_PAYMENT_DOCTYPES:
        frappe.log_error(
            f"Attempted access to disallowed doctype for payment status: {doctype}", "Payment Status Security"
        )
        return False, _GENERIC_PAYMENT_ACCESS_DENIED

    # Check document exists (without loading sensitive data)
    if not frappe.db.exists(doctype, docname):
        return False, _GENERIC_PAYMENT_ACCESS_DENIED

    # Load document with minimal fields for validation
    try:
        doc = frappe.get_doc(doctype, docname)

        doc_payment_id = getattr(doc, "payment_id", None) or getattr(doc, "mollie_payment_id", None)
        payment_id_matches = bool(payment_id) and bool(doc_payment_id) and doc_payment_id == payment_id
        token_matches = verify_guest_return_token("payment_success", f"{doctype}:{docname}", token)

        if not payment_id_matches and not token_matches:
            frappe.log_error(
                f"Payment reference/token mismatch for {doctype}/{docname}",
                "Payment Status Security",
            )
            return False, _GENERIC_PAYMENT_ACCESS_DENIED

        return True, doc

    except Exception as e:
        frappe.log_error(f"Error validating payment document: {str(e)}", "Payment Status Validation")
        return False, _GENERIC_PAYMENT_ACCESS_DENIED


def handle_ing_checkout_return(context, order_id):
    """
    Handle return from ING Checkout/Pay.nl payment.

    Pay.nl redirects with ?orderId=EX-xxxx-xxxx-xxxx
    We look up the transaction and fetch current status from Pay.nl API.
    """
    # Initialize context
    context.payment_status = "unknown"
    context.payment_message = _("Checking payment status...")
    context.document_info = {}
    context.next_steps = []

    try:
        # Fetch status from Pay.nl API
        from verenigingen.verenigingen_payments.ing_checkout.api.payment import get_payment_status

        result = get_payment_status(order_id)

        if not result.get("success"):
            context.payment_status = "error"
            context.payment_message = result.get("message", _("Failed to fetch payment status"))
            return context

        # Map Pay.nl status codes to our status values
        status_code = result.get("status_code", 0)

        if status_code == 100:
            context.payment_status = "completed"
            context.payment_message = _("Payment completed successfully!")
        elif status_code in (20, 25):
            context.payment_status = "pending"
            context.payment_message = _("Payment is being processed. You will receive confirmation shortly.")
        elif status_code == -90:
            context.payment_status = "cancelled"
            context.payment_message = _("The payment was cancelled.")
        elif status_code == -63:
            context.payment_status = "failed"
            context.payment_message = _(
                "The payment was denied. Please try again or use a different payment method."
            )
        elif status_code == -64:
            context.payment_status = "expired"
            context.payment_message = _("The payment session has expired. Please try again.")
        elif status_code == -81:
            context.payment_status = "completed"  # Refunded is still "completed" from user perspective
            context.payment_message = _("This payment has been refunded.")
        else:
            context.payment_status = "pending"
            context.payment_message = _("Payment status is being updated. Please check back shortly.")

        # Try to get linked document info from our transaction record
        transaction = frappe.db.get_value(
            "ING Checkout Transaction",
            {"transaction_id": order_id},
            ["reference_doctype", "reference_name", "amount"],
            as_dict=True,
        )

        if transaction and transaction.reference_doctype and transaction.reference_name:
            context.document_info = {
                "doctype": transaction.reference_doctype,
                "docname": transaction.reference_name,
                "title": transaction.reference_name,
                "amount": transaction.amount or 0,
                "paid": status_code == 100,
            }

            # Get next steps based on status
            context.next_steps = get_next_steps(
                context.payment_status,
                transaction.reference_doctype,
                transaction.reference_name,
            )
        else:
            # No linked document, provide generic next steps
            context.document_info = {
                "doctype": "Payment",
                "docname": order_id,
                "title": _("ING Checkout Payment"),
                "amount": 0,
                "paid": status_code == 100,
            }
            context.next_steps = get_next_steps(context.payment_status, None, None)

    except Exception as e:
        frappe.log_error(
            title="ING Checkout Return Page Error",
            message=f"Error handling return for {order_id}: {str(e)}",
        )
        context.payment_status = "error"
        context.payment_message = _(
            "An error occurred while checking payment status. Please contact support."
        )

    return context


def handle_ponto_payment_link_return(context, payment_link_name, token=None):
    """
    Handle return from Ponto Payment Link authorization.

    Ponto callback redirects with ?payment_link=PONTO-LINK-0001&token=...
    We look up the payment link and display current status.

    Ponto Payment Link.autoname is a small sequential PONTO-LINK-{####}
    counter, so the id alone is directly enumerable, and this branch used to
    disclose amount/creditor_name/paid with no ownership check at all
    (#1055 finding 1). The token is minted at the one place we construct
    this return URL (betaalverzoek_callback.py); a missing/wrong token is
    refused exactly like an unknown payment link.
    """
    # Initialize context
    context.payment_status = "unknown"
    context.payment_message = _("Checking payment status...")
    context.document_info = {}
    context.next_steps = []

    try:
        # Check if payment link exists
        if not frappe.db.exists("Ponto Payment Link", payment_link_name):
            context.payment_status = "error"
            context.payment_message = _("Payment link not found")
            return context

        if not verify_guest_return_token(PONTO_RETURN_TOKEN_PURPOSE, payment_link_name, token):
            context.payment_status = "error"
            context.payment_message = _("Payment link not found")
            return context

        # Get payment link details
        payment_link = frappe.db.get_value(
            "Ponto Payment Link",
            payment_link_name,
            [
                "status",
                "amount",
                "currency",
                "description",
                "reference_doctype",
                "reference_name",
                "member",
                "sales_invoice",
                "creditor_name",
            ],
            as_dict=True,
        )

        # Map Ponto status to our status values
        status = payment_link.status

        if status == "Executed":
            context.payment_status = "completed"
            context.payment_message = _("Payment completed successfully! Thank you.")
        elif status in ("Draft", "Pending Authorization"):
            context.payment_status = "pending"
            context.payment_message = _("Payment is awaiting authorization.")
        elif status == "Authorized":
            context.payment_status = "pending"
            context.payment_message = _("Payment has been authorized and is being processed.")
        elif status == "Cancelled":
            context.payment_status = "cancelled"
            context.payment_message = _("The payment was cancelled.")
        elif status == "Rejected":
            context.payment_status = "failed"
            context.payment_message = _("The payment was rejected. Please try again or contact support.")
        elif status == "Expired":
            context.payment_status = "expired"
            context.payment_message = _("The payment request has expired. Please request a new payment link.")
        elif status == "Failed":
            context.payment_status = "failed"
            context.payment_message = _(
                "The payment failed. Please try again or use a different payment method."
            )
        else:
            context.payment_status = "pending"
            context.payment_message = _("Payment status is being updated.")

        # Build document info
        context.document_info = {
            "doctype": "Ponto Payment Link",
            "docname": payment_link_name,
            "title": payment_link.description or _("Ponto Payment"),
            "amount": payment_link.amount or 0,
            "paid": status == "Executed",
        }

        # If linked to a Sales Invoice, show that info
        if payment_link.sales_invoice:
            context.document_info["doctype"] = "Sales Invoice"
            context.document_info["docname"] = payment_link.sales_invoice
            context.document_info["title"] = payment_link.sales_invoice

        # Get next steps
        ref_doctype = payment_link.reference_doctype or payment_link.sales_invoice
        ref_name = payment_link.reference_name or payment_link.sales_invoice
        context.next_steps = get_next_steps(context.payment_status, ref_doctype, ref_name)

    except Exception as e:
        frappe.log_error(
            title="Ponto Payment Link Return Page Error",
            message=f"Error handling return for {payment_link_name}: {str(e)}",
        )
        context.payment_status = "error"
        context.payment_message = _(
            "An error occurred while checking payment status. Please contact support."
        )

    return context


def get_context(context):
    """Get context for payment success page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Payment Status")

    # Ensure we have a valid session for guest users returning from payment providers
    if not frappe.session.user or frappe.session.user == "None":
        frappe.set_user("Guest")

    # Check for ING Checkout/Pay.nl redirect (uses orderId param)
    order_id = frappe.form_dict.get("orderId")
    if order_id:
        return handle_ing_checkout_return(context, order_id)

    # Check for Ponto Payment Link redirect (uses payment_link param)
    ponto_link = frappe.form_dict.get("payment_link")
    if ponto_link:
        return handle_ponto_payment_link_return(context, ponto_link, frappe.form_dict.get("token"))

    # Get parameters from URL (Mollie style: doctype/docname/payment_id)
    doctype = frappe.form_dict.get("doctype")
    docname = frappe.form_dict.get("docname")
    payment_id = frappe.form_dict.get("payment_id")
    token = frappe.form_dict.get("token")

    # Initialize context variables
    context.payment_status = "unknown"
    context.payment_message = _("Checking payment status...")
    context.document_info = {}
    context.next_steps = []

    if doctype and docname:
        # SECURITY: Validate document access before loading any data
        is_valid, result = validate_payment_document_access(doctype, docname, payment_id, token)

        if not is_valid:
            # result contains error message
            context.payment_status = "error"
            context.payment_message = result
            return context

        try:
            # result contains the validated doc
            doc = result

            # Only expose minimal, non-sensitive document info
            context.document_info = {
                "doctype": doctype,
                "docname": docname,
                "title": getattr(doc, "title", docname),
                "amount": getattr(doc, "amount", 0),
                "paid": getattr(doc, "paid", 0),
            }

            # Check payment status - payment_id already validated above
            if payment_id:
                # Use the payment gateway to check status
                payment_status = check_payment_status(doc, payment_id)
                context.payment_status = payment_status["status"]
                context.payment_message = payment_status["message"]

                # Determine next steps based on status
                context.next_steps = get_next_steps(payment_status["status"], doctype, docname)

            elif getattr(doc, "paid", 0):
                # Document is already marked as paid
                context.payment_status = "completed"
                context.payment_message = _("Payment completed successfully!")
                context.next_steps = get_next_steps("completed", doctype, docname)

            else:
                # Payment not completed yet
                context.payment_status = "pending"
                context.payment_message = _(
                    "Payment is being processed. You will receive confirmation shortly."
                )
                context.next_steps = get_next_steps("pending", doctype, docname)

        except Exception as e:
            frappe.log_error(f"Error in payment success page: {str(e)}", "Payment Success Error")
            context.payment_status = "error"
            context.payment_message = _(
                "There was an issue checking your payment status. Please contact support."
            )

    else:
        context.payment_message = _(
            "Invalid payment reference. Please check your payment confirmation email."
        )

    return context


def check_payment_status(doc, payment_id):
    """Check payment status using the appropriate gateway"""
    try:
        if getattr(doc, "payment_method", "") == "Mollie":
            from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

            gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
            return gateway.get_payment_status(payment_id)
        else:
            return {
                "status": "unknown",
                "message": _("Payment status cannot be checked automatically for this payment method"),
            }

    except Exception as e:
        frappe.log_error(f"Error checking payment status for {payment_id}: {str(e)}", "Payment Status Check")
        return {"status": "error", "message": _("Unable to check payment status at this time")}


def get_next_steps(status, doctype, docname):
    """Get appropriate next steps based on payment status"""
    next_steps = []

    if status == "completed":
        next_steps.append(
            {
                "title": _("Thank you!"),
                "description": _("Your payment has been completed successfully."),
                "action": None,
            }
        )

        if doctype == "Donation":
            next_steps.append(
                {
                    "title": _("Receipt"),
                    "description": _("You will receive a donation receipt via email."),
                    "action": None,
                }
            )

        next_steps.append(
            {
                "title": _("Make Another Donation"),
                "description": _("Support our mission with another donation."),
                "action": "/donate",
            }
        )

    elif status == "pending":
        next_steps.append(
            {
                "title": _("Wait for Confirmation"),
                "description": _("Your payment is being processed. This usually takes a few minutes."),
                "action": None,
            }
        )

        next_steps.append(
            {
                "title": _("Check Your Email"),
                "description": _("You will receive a confirmation email once the payment is complete."),
                "action": None,
            }
        )

    elif status in ["cancelled", "expired", "failed"]:
        next_steps.append(
            {
                "title": _("Try Again"),
                "description": _(
                    "Your payment was not completed. You can try again with the same or different payment method."
                ),
                "action": "/donate",
            }
        )

        next_steps.append(
            {
                "title": _("Contact Support"),
                "description": _("If you continue to have issues, please contact our support team."),
                "action": "mailto:support@example.com",  # This should come from settings
            }
        )

    else:
        next_steps.append(
            {
                "title": _("Contact Support"),
                "description": _(
                    "If you have questions about your payment, please contact our support team."
                ),
                "action": "mailto:support@example.com",  # This should come from settings
            }
        )

    return next_steps


@frappe.whitelist(allow_guest=True)
@public_api
def refresh_payment_status(doctype: str, docname: str, payment_id: str = "", token: str = ""):
    """
    API endpoint to refresh payment status.

    SECURITY: This endpoint is rate-limited and validates:
    1. doctype is in ALLOWED_PAYMENT_DOCTYPES whitelist
    2. document exists
    3. payment_id matches the document's payment reference, OR token is a
       valid return token for this doctype/docname (#1055 -- payment_id
       alone was previously optional, so an empty string bypassed the
       ownership check entirely)
    """
    try:
        # SECURITY: Validate access before returning any data
        is_valid, result = validate_payment_document_access(doctype, docname, payment_id, token)

        if not is_valid:
            # result contains error message - don't leak document existence info
            return {
                "success": False,
                "message": _("Invalid payment reference or document not found"),
            }

        # result contains the validated doc
        doc = result
        payment_result = check_payment_status(doc, payment_id)

        return {
            "success": True,
            "status": payment_result["status"],
            "message": payment_result["message"],
            "is_paid": getattr(doc, "paid", 0),
        }

    except Exception as e:
        frappe.log_error(f"Error in refresh_payment_status: {str(e)}", "Payment Status API Error")
        return {"success": False, "message": _("Error checking payment status")}
