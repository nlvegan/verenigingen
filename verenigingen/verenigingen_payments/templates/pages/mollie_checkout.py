"""
Mollie Checkout Page Handler

Manages the Mollie payment checkout process including payment initialization,
status checking, and user interface coordination. This page serves as the
intermediary between the user's payment initiation and the Mollie payment
gateway, providing real-time status updates and proper redirect handling.

Key Features:
- Payment data validation and initialization
- Real-time payment status checking via API
- Automatic payment retry for cancelled/expired payments
- User-friendly status display and error handling
- Integration with Mollie Settings for branding and configuration

Business Context:
This checkout page is the crucial link in the payment flow where users
are presented with payment information before being redirected to Mollie's
secure payment interface. It handles the technical coordination while
providing a seamless user experience.

Architecture:
- Server-side: Payment initialization and status management
- Client-side: Real-time status polling and user interface updates
- Mollie API: Payment creation and status verification
- Frappe framework: Authentication, permissions, and data handling

Author: Development Team
Date: 2025-01-13
Version: 1.0
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, fmt_money

no_cache = 1

# Required parameters for checkout processing
expected_keys = (
    "amount",
    "title",
    "description",
    "reference_doctype",
    "reference_docname",
    "payer_name",
    "payer_email",
    "order_id",
    "currency",
)


def get_context(context):
    """
    Prepare checkout page context and validate parameters

    Args:
        context: Frappe page context object

    Returns:
        None (modifies context in place)

    Raises:
        frappe.Redirect: If required parameters are missing
    """
    context.no_cache = 1

    # Validate all required parameters are present
    if not (set(expected_keys) - set(list(frappe.form_dict))):
        # All required keys present, populate context
        for key in expected_keys:
            context[key] = frappe.form_dict[key]

        # Get gateway configuration
        gateway_name = frappe.form_dict.get("gateway_name", "Default")
        mollie_settings = get_mollie_settings(context.reference_docname, gateway_name)

        # Add Mollie-specific context
        context.profile_id = mollie_settings.profile_id
        context.gateway_name = gateway_name
        context.header_image = mollie_settings.header_img
        context.test_mode = mollie_settings.test_mode

        # Format amount for display
        context["amount_formatted"] = fmt_money(amount=context["amount"], currency=context["currency"])

        # Add page metadata
        context.page_title = _("Payment - {0}").format(context["title"])
        context.show_sidebar = False

    else:
        # Missing required parameters
        missing_keys = set(expected_keys) - set(list(frappe.form_dict))
        frappe.log_error(
            f"Mollie checkout missing parameters: {missing_keys}. Form data: {frappe.form_dict}",
            "Mollie Checkout Error",
        )

        frappe.redirect_to_message(
            _("Incomplete Payment Information"),
            _("Some required payment information is missing. Please try again or contact support."),
        )
        frappe.local.flags.redirect_location = frappe.local.response.location
        raise frappe.Redirect


def get_mollie_settings(reference_docname, gateway_name):
    """
    Get Mollie settings for the payment gateway

    Args:
        reference_docname (str): Name of the document being paid for
        gateway_name (str): Mollie gateway configuration name

    Returns:
        MollieSettings: Mollie settings document
    """
    try:
        from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import (
            get_mollie_settings,
        )

        return get_mollie_settings(gateway_name)
    except Exception as e:
        frappe.log_error(f"Error loading Mollie settings '{gateway_name}': {str(e)}", "Mollie Settings Error")
        frappe.throw(_("Payment gateway configuration error. Please contact support."))


@frappe.whitelist(allow_guest=True)
def make_payment(data, reference_doctype, reference_docname, gateway_name="Default"):
    """
    Create or check Mollie payment status

    This method handles the core payment logic including:
    - Creating new payments if none exist
    - Checking status of existing payments
    - Recreating cancelled/expired payments
    - Updating payment status in the database

    Args:
        data (str): JSON string containing payment data
        reference_doctype (str): DocType of document being paid for
        reference_docname (str): Name of document being paid for
        gateway_name (str): Mollie gateway configuration to use

    Returns:
        dict: Payment status and URL information
    """
    try:
        # Parse payment data
        data = json.loads(data)

        # Get the document being paid for
        doc = frappe.get_doc(reference_doctype, reference_docname)

        # Check if payment already exists
        existing_payment_id = getattr(doc, "payment_id", None)

        if not existing_payment_id:
            # No existing payment, create new one
            result = create_new_payment(doc, data, gateway_name)
        else:
            # Check existing payment status
            result = check_existing_payment(doc, data, existing_payment_id, gateway_name)

        # Update payment status in database if status field exists
        if hasattr(doc, "payment_status") and result.get("status"):
            try:
                # Map statuses to database values
                status_mapping = {
                    "Open": "Open",
                    "Pending": "Pending",
                    "Completed": "Completed",
                    "Cancelled": "Cancelled",
                    "Error": "Error",
                }

                db_status = status_mapping.get(result["status"], result["status"])
                frappe.db.set_value(reference_doctype, reference_docname, "payment_status", db_status)
                frappe.db.commit()

            except Exception as e:
                frappe.log_error(f"Error updating payment status: {str(e)}", "Payment Status Update")

        return result

    except Exception as e:
        frappe.log_error(f"Mollie payment processing error: {str(e)}", "Mollie Payment Error")
        return {
            "status": "Error",
            "message": _("Payment processing failed. Please try again."),
            "paymentUrl": None,
        }


def create_new_payment(doc, data, gateway_name):
    """
    Create a new Mollie payment

    Args:
        doc: Document being paid for
        data (dict): Payment data
        gateway_name (str): Mollie gateway configuration

    Returns:
        dict: Payment creation result
    """
    try:
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        # Get Mollie gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", gateway_name)

        # Create payment
        result = gateway.process_payment(doc, data)

        if result.get("status") == "redirect_required":
            return {
                "status": "Open",
                "paymentUrl": result["payment_url"],
                "paymentID": result["payment_id"],
                "message": _("Payment created successfully"),
            }
        else:
            return {
                "status": "Error",
                "message": result.get("message", _("Payment creation failed")),
                "paymentUrl": None,
            }

    except Exception as e:
        frappe.log_error(f"Error creating new Mollie payment: {str(e)}", "Mollie Payment Creation")
        return {
            "status": "Error",
            "message": _("Could not create payment. Please try again."),
            "paymentUrl": None,
        }


def check_existing_payment(doc, data, payment_id, gateway_name):
    """
    Check status of existing Mollie payment

    Args:
        doc: Document being paid for
        data (dict): Payment data
        payment_id (str): Existing Mollie payment ID
        gateway_name (str): Mollie gateway configuration

    Returns:
        dict: Payment status result
    """
    try:
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        # Get Mollie gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", gateway_name)

        # Check payment status
        status_result = gateway.get_payment_status(payment_id)

        # Handle different status responses
        if status_result["status"] == "Completed":
            return {"status": "Completed", "paymentUrl": None, "message": _("Payment completed successfully")}

        elif status_result["status"] in ["Open", "Pending"]:
            return {
                "status": status_result["status"],
                "paymentUrl": status_result.get("payment_url"),
                "message": status_result.get("message", _("Payment is being processed")),
            }

        elif status_result["status"] == "Cancelled":
            # Payment was cancelled/expired, create new one
            frappe.logger().info(f"Payment {payment_id} was cancelled, creating new payment")
            return create_new_payment(doc, data, gateway_name)

        else:
            # Error or unknown status
            return {
                "status": "Error",
                "message": status_result.get("message", _("Could not check payment status")),
                "paymentUrl": None,
            }

    except Exception as e:
        frappe.log_error(f"Error checking Mollie payment {payment_id}: {str(e)}", "Mollie Payment Status")

        # If we can't check status, try to create new payment
        frappe.logger().info(f"Could not check payment status, creating new payment for {doc.name}")
        return create_new_payment(doc, data, gateway_name)


@frappe.whitelist()
def get_payment_status_only(reference_doctype, reference_docname):
    """
    Get only the payment status without processing

    Args:
        reference_doctype (str): DocType of document
        reference_docname (str): Name of document

    Returns:
        dict: Payment status information
    """
    try:
        doc = frappe.get_doc(reference_doctype, reference_docname)

        # Check if already paid
        if getattr(doc, "paid", 0):
            return {"status": "Completed", "message": _("Payment completed")}

        # Check payment status field if exists
        if hasattr(doc, "payment_status"):
            status = getattr(doc, "payment_status")
            if status:
                return {"status": status, "message": f"Payment status: {status}"}

        return {"status": "Pending", "message": _("Payment not yet completed")}

    except Exception as e:
        frappe.log_error(f"Error getting payment status: {str(e)}", "Payment Status Check")
        return {"status": "Error", "message": _("Could not check payment status")}
