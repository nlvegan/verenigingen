"""
Payment Success Page

Handles users returning from external payment providers like Mollie.
Displays payment status and provides appropriate next steps.
"""

import frappe
from frappe import _
from frappe.utils import cstr

# Whitelist of doctypes allowed for public payment status queries
# This prevents IDOR attacks by limiting what documents can be accessed
ALLOWED_PAYMENT_DOCTYPES = {"Donation", "Member Application"}


def validate_payment_document_access(doctype, docname, payment_id):
    """
    Validate that a document can be accessed for payment status display.

    Security checks:
    1. Doctype must be in the allowed whitelist
    2. Document must exist
    3. payment_id must match the document's payment reference

    Returns:
        tuple: (is_valid, doc_or_error_message)
    """
    # Check doctype is allowed
    if doctype not in ALLOWED_PAYMENT_DOCTYPES:
        frappe.log_error(
            f"Attempted access to disallowed doctype for payment status: {doctype}", "Payment Status Security"
        )
        return False, _("Invalid document type for payment status")

    # Check document exists (without loading sensitive data)
    if not frappe.db.exists(doctype, docname):
        return False, _("Document not found")

    # Load document with minimal fields for validation
    try:
        doc = frappe.get_doc(doctype, docname)

        # Validate payment_id matches if provided
        if payment_id:
            doc_payment_id = getattr(doc, "payment_id", None) or getattr(doc, "mollie_payment_id", None)
            if not doc_payment_id or doc_payment_id != payment_id:
                frappe.log_error(
                    f"Payment ID mismatch: expected {doc_payment_id}, got {payment_id} for {doctype}/{docname}",
                    "Payment Status Security",
                )
                return False, _("Invalid payment reference")

        return True, doc

    except Exception as e:
        frappe.log_error(f"Error validating payment document: {str(e)}", "Payment Status Validation")
        return False, _("Unable to validate document")


def get_context(context):
    """Get context for payment success page"""

    # Set page properties
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Payment Status")

    # Ensure we have a valid session for guest users returning from payment providers
    if not frappe.session.user or frappe.session.user == "None":
        frappe.set_user("Guest")

    # Get parameters from URL
    doctype = frappe.form_dict.get("doctype")
    docname = frappe.form_dict.get("docname")
    payment_id = frappe.form_dict.get("payment_id")

    # Initialize context variables
    context.payment_status = "unknown"
    context.payment_message = _("Checking payment status...")
    context.document_info = {}
    context.next_steps = []

    if doctype and docname:
        # SECURITY: Validate document access before loading any data
        is_valid, result = validate_payment_document_access(doctype, docname, payment_id)

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
def refresh_payment_status(doctype, docname, payment_id):
    """
    API endpoint to refresh payment status.

    SECURITY: This endpoint is rate-limited and validates:
    1. doctype is in ALLOWED_PAYMENT_DOCTYPES whitelist
    2. document exists
    3. payment_id matches the document's payment reference
    """
    try:
        # SECURITY: Validate access before returning any data
        is_valid, result = validate_payment_document_access(doctype, docname, payment_id)

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
