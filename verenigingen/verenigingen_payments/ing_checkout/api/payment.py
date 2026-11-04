# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout Payment API Endpoints

Whitelisted methods for initiating payments and checking status.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import get_url

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token
from verenigingen.verenigingen_payments.ing_checkout.client import PayNLError, get_client

# Namespace of the return token minted into the ING return URL and checked by
# templates/pages/payment_success.py (#2038); distinct from "payment_success" (Mollie).
ING_RETURN_TOKEN_PURPOSE = "ing_checkout_return"

# Payment Method IDs
PAYMENT_METHOD_IDEAL = 10
PAYMENT_METHOD_BANCONTACT = 436
PAYMENT_METHOD_CREDITCARD = 706


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
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
@high_security_api(operation_type=OperationType.FINANCIAL)
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

    Note:
        This is a thin whitelisted wrapper around `create_ideal_order`, which
        holds the actual order-creation logic and is also called directly by
        trusted internal callers (e.g. other payment gateways) that don't go
        through the whitelist/request layer.
    """
    try:
        # Validate inputs
        if not reference_doctype or not reference_name:
            frappe.throw(_("Reference document is required"))
        if not amount or amount <= 0:
            frappe.throw(_("Amount must be greater than 0"))
    except Exception as e:
        frappe.log_error(
            title="ING Checkout Payment Error",
            message=f"Unexpected error creating iDEAL payment: {str(e)}",
        )
        return {
            "success": False,
            "message": _("An unexpected error occurred"),
        }

    return create_ideal_order(reference_doctype, reference_name, amount, description, return_url)


def create_ideal_order(
    reference_doctype: str,
    reference_name: str,
    amount: float,
    description: str = None,
    return_url: str = None,
) -> dict:
    """
    Core iDEAL order creation, without the whitelist/security decorators.

    Builds the Pay.nl order, creates the `ING Checkout Transaction` tracking
    record, and returns the same shape as `create_ideal_payment`. Callers are
    trusted to have already authorized the request (e.g. a payment gateway
    acting on behalf of an authenticated flow) - the reference-document
    existence check and read-permission check below still run regardless,
    since they are cheap and reference-document specific.

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
            - reference: Structured reference (DOCTYPE_CODE:DOCUMENT_NAME)
            - message: Status message
    """
    try:
        # Check document exists
        if not frappe.db.exists(reference_doctype, reference_name):
            frappe.throw(_("Reference document not found: {0} {1}").format(reference_doctype, reference_name))

        # SECURITY: Verify user has permission to access reference document
        # This prevents users from creating payments for documents they cannot access
        ref_doc = frappe.get_doc(reference_doctype, reference_name)
        ref_doc.check_permission("read")

        # Get settings
        from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
            get_ing_checkout_settings,
        )

        settings = get_ing_checkout_settings()
        client = get_client(settings)

        # Build return URL
        # Pay.nl automatically appends ?orderId=... to the return URL
        # Only OUR default page gets a return token (#2038). A caller-supplied return_url or a
        # stored default_return_url override points at a page we do not render, so handing it
        # a proof would only leak it to that page; the override wins unchanged (as Mollie's does).
        if not return_url:
            return_url = settings.default_return_url or build_default_return_url(
                reference_doctype, reference_name
            )

        # Build webhook URL
        webhook_url = (
            f"{get_url()}/api/method/"
            "verenigingen.verenigingen_payments.ing_checkout.api.webhook.handle_payment"
        )

        # Create structured reference for reliable parsing
        # Format: DOCTYPE_CODE:DOCUMENT_NAME
        DOCTYPE_CODES = {
            "Sales Invoice": "SINV",
            "Member": "MEM",
            "Purchase Invoice": "PINV",
            "Payment Plan Payment": "PPP",
        }
        doctype_code = DOCTYPE_CODES.get(reference_doctype, reference_doctype[:4].upper())
        reference = f"{doctype_code}:{reference_name}"

        # Convert amount to cents using Decimal to avoid float precision issues
        # e.g., 19.99 * 100 = 1998.9999... with floats, but 1999 with Decimal
        amount_cents = int(Decimal(str(amount)) * 100)

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

        # Create ING Checkout Transaction record for tracking
        from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
            get_or_create_transaction,
        )

        transaction = get_or_create_transaction(
            transaction_id=order_id,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            amount=amount,
            payment_method="iDEAL",
        )
        transaction.redirect_url = redirect_url
        transaction.return_url = return_url
        transaction.raw_request = frappe.as_json(order_data)
        transaction.raw_response = frappe.as_json(response)
        # SECURITY JUSTIFICATION: ignore_permissions=True is acceptable here because:
        # 1. User is authenticated (whitelisted method without allow_guest)
        # 2. Permission validated on reference document (ref_doc.check_permission above)
        # 3. Transaction is a tracking record for user's own payment request
        # 4. @standard_api decorator provides audit logging
        transaction.save(ignore_permissions=True)

        frappe.logger().info(
            f"Created iDEAL payment: order_id={order_id}, transaction={transaction.name}, "
            f"reference={reference}, amount={amount}"
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


def build_default_return_url(reference_doctype: str, reference_name: str) -> str:
    """Our /payment_success URL carrying the signed return token (#2038).

    The token binds to the reference document, not the Pay.nl orderId: the orderId does not
    exist until Pay.nl answers create_order, which is after this URL has been sent. Pay.nl then
    appends `orderId` (with `&`, since the URL already has a query string - derived from Pay.nl's
    documented behaviour, not measured against a live order).
    """
    token = generate_guest_return_token(ING_RETURN_TOKEN_PURPOSE, f"{reference_doctype}:{reference_name}")
    return f"{get_url('/payment_success')}?token={token}"


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
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
    return fetch_payment_status(transaction_id)


def fetch_payment_status(transaction_id: str) -> dict:
    """Pay.nl order status, WITHOUT the whitelist/auth decorators.

    For trusted internal callers that authorised the request themselves (the guest return
    page, after verifying its signed token). `get_payment_status` is the authenticated wrapper.
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
