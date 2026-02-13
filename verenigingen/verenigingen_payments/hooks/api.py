# Copyright (c) 2025, Verenigingen
# License: MIT

"""
Payment API endpoints.

Provides whitelisted methods for frontend payment integration.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.verenigingen_payments.hooks.payment_hook import PaymentHook


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_methods(context: str | None = None) -> dict:
    """
    Get available payment methods for the given context.

    Args:
        context: JSON string with context options:
            - recurring: bool - Only return methods supporting recurring
            - form_type: str - Form type (donation, membership, event)

    Returns:
        {
            "success": True,
            "methods": [
                {
                    "id": "mollie",
                    "label": "Online Payment",
                    "description": "...",
                    "supports_recurring": True,
                    "type": "redirect"
                },
                ...
            ]
        }
    """
    ctx = frappe.parse_json(context) if context else {}
    methods = PaymentHook.get_available_methods(ctx)

    return {"success": True, "methods": methods}


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.FINANCIAL)
def initiate_payment(
    method: str,
    amount: float,
    reference_doctype: str,
    reference_name: str,
    payer_email: str,
    payer_name: str,
    payer_iban: str | None = None,
    account_holder: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
    recurring: bool = False,
    interval: str | None = None,
) -> dict:
    """
    Initiate a payment.

    Args:
        method: Payment method ID (mollie, sepa, bank_transfer, cash)
        amount: Payment amount
        reference_doctype: DocType being paid for
        reference_name: Document name
        payer_email: Payer's email address
        payer_name: Payer's name
        payer_iban: IBAN (required for SEPA)
        account_holder: Account holder name (for SEPA, defaults to payer_name)
        success_url: Redirect URL on success
        cancel_url: Redirect URL on cancel
        recurring: Whether to set up recurring payments
        interval: Recurring interval (e.g., "1 month")

    Returns:
        {
            "success": True/False,
            "action": "redirect" | "mandate_form" | "show_instructions",
            "data": {...},
            "payment_id": "...",
            "message": "..."
        }
    """
    payer_info = {
        "email": payer_email,
        "name": payer_name,
        "iban": payer_iban,
        "account_holder": account_holder or payer_name,
    }

    redirect_urls = None
    if success_url or cancel_url:
        redirect_urls = {"success": success_url, "cancel": cancel_url}

    return PaymentHook.initiate_payment(
        method=method,
        amount=float(amount),
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        payer_info=payer_info,
        redirect_urls=redirect_urls,
        recurring=bool(recurring),
        interval=interval,
    )


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_payment_status(method: str, payment_id: str) -> dict:
    """
    Check payment status.

    Args:
        method: Payment method ID
        payment_id: Payment identifier from gateway

    Returns:
        {
            "status": "pending" | "paid" | "failed" | "expired",
            "data": {...}
        }
    """
    return PaymentHook.get_payment_status(method, payment_id)
