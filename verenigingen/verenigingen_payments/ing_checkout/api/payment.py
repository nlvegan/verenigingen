# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout Payment API Endpoints

Whitelisted methods for initiating payments and checking status.
"""

import frappe
from frappe import _
from frappe.utils import get_url

from verenigingen.verenigingen_payments.ing_checkout.client import PayNLError, get_client

# Payment Method IDs
PAYMENT_METHOD_IDEAL = 10
PAYMENT_METHOD_BANCONTACT = 436
PAYMENT_METHOD_CREDITCARD = 706


@frappe.whitelist()
def test_connection() -> dict:
    """
    Test the Pay.nl API connection.

    Returns:
        dict with success status and message
    """
    try:
        client = get_client()
        result = client.test_connection()
        return result
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
        }


@frappe.whitelist()
def create_ideal_payment(
    reference_doctype: str,
    reference_name: str,
    amount: float,
    description: str,
    return_url: str = None,
) -> dict:
    """
    Create an iDEAL payment for a document.

    Args:
        reference_doctype: DocType to link payment to (e.g., "Sales Invoice")
        reference_name: Document name
        amount: Amount in EUR (e.g., 25.00)
        description: Payment description (shown on bank statement, max 30 chars)
        return_url: Optional URL to redirect after payment

    Returns:
        dict with:
            - success: bool
            - transaction_id: Pay.nl order ID
            - redirect_url: URL to redirect user for payment
            - message: Status message

    Example:
        result = create_ideal_payment(
            reference_doctype="Sales Invoice",
            reference_name="INV-2025-001",
            amount=25.00,
            description="Membership fee 2025"
        )
        # Redirect user to result["redirect_url"]
    """
    try:
        # Validate inputs
        if not reference_doctype or not reference_name:
            frappe.throw(_("Reference document is required"))
        if not amount or amount <= 0:
            frappe.throw(_("Amount must be greater than 0"))

        # Check document exists
        if not frappe.db.exists(reference_doctype, reference_name):
            frappe.throw(_("Reference document not found: {0} {1}").format(reference_doctype, reference_name))

        # Get settings
        from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
            get_ing_checkout_settings,
        )

        settings = get_ing_checkout_settings()
        client = get_client(settings)

        # Build return URL
        if not return_url:
            return_url = settings.default_return_url or get_url("/payment-complete")

        # Build webhook URL
        webhook_url = (
            f"{get_url()}/api/method/"
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment"
        )

        # Create unique reference
        reference = f"{reference_doctype[:3].upper()}-{reference_name}"

        # Convert amount to cents
        amount_cents = int(amount * 100)

        # Truncate description to 30 chars (bank statement limit)
        description = description[:30] if description else "Payment"

        # Create order
        order_data = {
            "serviceId": settings.service_id,
            "amount": {
                "value": amount_cents,
                "currency": "EUR",
            },
            "description": description,
            "reference": reference,
            "returnUrl": return_url,
            "exchangeUrl": webhook_url,
            "paymentMethod": {
                "id": PAYMENT_METHOD_IDEAL,
            },
        }

        response = client.create_order(order_data)

        # Extract redirect URL
        redirect_url = None
        if "links" in response:
            redirect_url = response["links"].get("redirect")
        elif "order_url" in response:
            redirect_url = response["order_url"]

        order_id = response.get("id")

        # TODO: Create ING Checkout Transaction record

        frappe.logger().info(
            f"Created iDEAL payment: order_id={order_id}, " f"reference={reference}, amount={amount}"
        )

        return {
            "success": True,
            "transaction_id": order_id,
            "redirect_url": redirect_url,
            "reference": reference,
            "message": _("Payment created successfully"),
        }

    except PayNLError as e:
        frappe.log_error(
            title="ING Checkout Payment Error",
            message=f"Failed to create iDEAL payment: {str(e)}",
        )
        return {
            "success": False,
            "message": str(e),
        }
    except Exception as e:
        frappe.log_error(
            title="ING Checkout Payment Error",
            message=f"Unexpected error creating iDEAL payment: {str(e)}",
        )
        return {
            "success": False,
            "message": _("An unexpected error occurred"),
        }


@frappe.whitelist()
def get_payment_status(transaction_id: str) -> dict:
    """
    Get the status of a payment.

    Args:
        transaction_id: Pay.nl order ID (EX-xxxx-xxxx-xxxx)

    Returns:
        dict with:
            - success: bool
            - status_code: Pay.nl status code
            - status_action: Status action (PAID, PENDING, etc.)
            - paid: bool indicating if payment is complete
            - customer_iban: IBAN of payer (if available)
            - customer_name: Name of payer (if available)
    """
    try:
        if not transaction_id:
            frappe.throw(_("Transaction ID is required"))

        client = get_client()
        order = client.get_order(transaction_id)

        status = order.get("status", {})
        status_code = status.get("code", 0)
        status_action = status.get("action", "UNKNOWN")

        # Extract customer info from payments
        customer_iban = None
        customer_name = None
        payments = order.get("payments", [])
        if payments:
            customer_method = payments[0].get("customerMethod", {})
            customer_iban = customer_method.get("iban")
            customer_name = customer_method.get("name")

        return {
            "success": True,
            "transaction_id": transaction_id,
            "status_code": status_code,
            "status_action": status_action,
            "paid": status_code == 100,  # 100 = PAID
            "customer_iban": customer_iban,
            "customer_name": customer_name,
            "raw_status": status,
        }

    except PayNLError as e:
        return {
            "success": False,
            "message": str(e),
        }
    except Exception as e:
        frappe.log_error(
            title="ING Checkout Status Error",
            message=f"Error getting payment status: {str(e)}",
        )
        return {
            "success": False,
            "message": _("Failed to get payment status"),
        }
