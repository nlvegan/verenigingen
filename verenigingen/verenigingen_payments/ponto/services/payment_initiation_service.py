# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Initiation Service

High-level service for creating and managing SEPA payments via Ponto.

This service coordinates between:
- Ponto Payment Request DocType (tracking)
- Ponto Payment Client (API calls)
- ERPNext Payment Entry (accounting)

Usage:
    from verenigingen.verenigingen_payments.ponto.services.payment_initiation_service import (
        create_sepa_payment,
        get_payment_authorization_url,
    )

    # Create a payment request
    payment_doc = create_sepa_payment(
        ponto_account_id="uuid-from-ponto",
        amount=150.00,
        creditor_name="Supplier BV",
        creditor_iban="NL91ABNA0417164300",
        remittance_info="Invoice INV-2025-001",
    )

    # Get the authorization URL for signing
    auth_url = get_payment_authorization_url(payment_doc.name)
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import frappe
from frappe import _

from verenigingen.utils.validation.iban_validator import validate_iban
from verenigingen.verenigingen_payments.ponto.clients.payment_client import PaymentRequest, get_payment_client
from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError


def create_sepa_payment(
    ponto_account_id: str,
    amount: float,
    creditor_name: str,
    creditor_iban: str,
    remittance_info: str,
    creditor_bic: str = None,
    requested_execution_date: date = None,
    reference_doctype: str = None,
    reference_name: str = None,
    redirect_uri: str = None,
    auto_submit: bool = True,
) -> "frappe.Document":
    """
    Create a SEPA payment request through Ponto.

    Creates a Ponto Payment Request document and optionally submits it
    to initiate the payment in Ponto.

    Args:
        ponto_account_id: Ponto account UUID to pay from
        amount: Payment amount in EUR (must be positive)
        creditor_name: Beneficiary name
        creditor_iban: Beneficiary IBAN
        remittance_info: Payment reference/description
        creditor_bic: Beneficiary BIC/SWIFT (optional)
        requested_execution_date: Future execution date (optional)
        reference_doctype: DocType this payment relates to (optional)
        reference_name: Document name this payment relates to (optional)
        redirect_uri: Custom redirect URI after signing (optional)
        auto_submit: Whether to submit immediately (default: True)

    Returns:
        Ponto Payment Request document

    Raises:
        PontoIntegrationError: If validation fails
        frappe.ValidationError: If document creation fails
    """
    # Validate inputs
    if amount <= 0:
        raise PontoIntegrationError(
            message="Payment amount must be positive",
            details={"amount": amount},
        )

    # SEPA amount limits and precision
    # Max €999,999,999.99 for SEPA Credit Transfer (SCT)
    SEPA_MAX_AMOUNT = 999999999.99
    if amount > SEPA_MAX_AMOUNT:
        raise PontoIntegrationError(
            message=f"Payment amount exceeds SEPA maximum of {SEPA_MAX_AMOUNT:,.2f} EUR",
            details={"amount": amount, "max_allowed": SEPA_MAX_AMOUNT},
        )

    # Validate decimal precision (max 2 decimal places for EUR)
    # Check by multiplying by 100 and verifying it's a whole number
    amount_cents = round(amount * 100, 6)  # round to avoid floating point issues
    if abs(amount_cents - round(amount_cents)) > 0.0001:
        raise PontoIntegrationError(
            message="Payment amount must have at most 2 decimal places",
            details={"amount": amount},
        )

    if not creditor_name or not creditor_iban:
        raise PontoIntegrationError(
            message="Creditor name and IBAN are required",
            details={"creditor_name": creditor_name, "creditor_iban": creditor_iban},
        )

    # Validate IBAN format and checksum
    iban_validation = validate_iban(creditor_iban)
    if not iban_validation.get("valid"):
        raise PontoIntegrationError(
            message=f"Invalid creditor IBAN: {iban_validation.get('message', 'Validation failed')}",
            details={"creditor_iban": creditor_iban},
        )

    if not remittance_info:
        raise PontoIntegrationError(
            message="Remittance information is required",
        )

    # Verify ponto_account_id exists in settings
    settings = frappe.get_single("Ponto Settings")
    account_valid = any(
        mapping.ponto_account_id == ponto_account_id for mapping in settings.bank_account_mappings
    )
    if not account_valid:
        raise PontoIntegrationError(
            message=f"Ponto account {ponto_account_id} not found in settings",
            details={"ponto_account_id": ponto_account_id},
        )

    # Create Ponto Payment Request document
    doc = frappe.new_doc("Ponto Payment Request")
    doc.ponto_account = ponto_account_id
    doc.amount = amount
    doc.currency = "EUR"  # SEPA only supports EUR
    doc.creditor_name = creditor_name
    doc.creditor_iban = creditor_iban
    doc.remittance_info = remittance_info

    if creditor_bic:
        doc.creditor_bic = creditor_bic

    if requested_execution_date:
        doc.requested_execution_date = requested_execution_date

    if reference_doctype and reference_name:
        doc.reference_doctype = reference_doctype
        doc.reference_name = reference_name

    if redirect_uri:
        doc.redirect_uri = redirect_uri

    # Save draft
    doc.insert()

    frappe.logger().info(f"Created Ponto Payment Request {doc.name} for {amount} EUR to {creditor_name}")

    # Optionally submit to initiate payment in Ponto
    if auto_submit:
        doc.submit()
        frappe.logger().info(f"Submitted Ponto Payment Request {doc.name}")

    return doc


def get_payment_authorization_url(payment_request_name: str) -> Optional[str]:
    """
    Get the authorization URL for signing a payment.

    The user must visit this URL in their browser to sign the payment
    in the Ponto authorization portal.

    Args:
        payment_request_name: Name of the Ponto Payment Request document

    Returns:
        Authorization URL string or None if not available

    Raises:
        frappe.DoesNotExistError: If payment request not found
    """
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)
    return doc.redirect_link


def refresh_payment_status(payment_request_name: str) -> dict:
    """
    Refresh the status of a payment request from Ponto API.

    Args:
        payment_request_name: Name of the Ponto Payment Request document

    Returns:
        Dict with updated status information
    """
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)
    return doc.refresh_status()


def list_pending_payments(ponto_account_id: str = None) -> list:
    """
    List all pending (unsigned) payment requests.

    Args:
        ponto_account_id: Filter by Ponto account (optional)

    Returns:
        List of Ponto Payment Request documents
    """
    filters = {"status": ["in", ["Draft", "Pending"]]}
    if ponto_account_id:
        filters["ponto_account"] = ponto_account_id

    return frappe.get_all(
        "Ponto Payment Request",
        filters=filters,
        fields=["name", "ponto_account", "amount", "creditor_name", "status", "creation"],
        order_by="creation desc",
    )


def cancel_payment(payment_request_name: str) -> bool:
    """
    Cancel a payment request.

    Only works for payments that haven't been signed yet.

    Args:
        payment_request_name: Name of the Ponto Payment Request document

    Returns:
        True if cancelled successfully

    Raises:
        frappe.ValidationError: If payment cannot be cancelled
    """
    doc = frappe.get_doc("Ponto Payment Request", payment_request_name)

    if doc.status not in ["Draft", "Pending"]:
        frappe.throw(
            _("Cannot cancel payment with status {0}").format(doc.status),
            title=_("Cannot Cancel"),
        )

    if doc.docstatus == 1:
        doc.cancel()
    else:
        doc.delete()

    frappe.logger().info(f"Cancelled Ponto Payment Request {payment_request_name}")
    return True


def create_payment_for_supplier(
    supplier: str,
    amount: float,
    remittance_info: str,
    ponto_account_id: str = None,
    auto_submit: bool = True,
) -> "frappe.Document":
    """
    Create a SEPA payment to a supplier.

    Retrieves the supplier's bank details automatically.

    Args:
        supplier: Supplier name
        amount: Payment amount in EUR
        remittance_info: Payment reference
        ponto_account_id: Ponto account to pay from (uses default if not specified)
        auto_submit: Whether to submit immediately

    Returns:
        Ponto Payment Request document

    Raises:
        PontoIntegrationError: If supplier has no bank account
    """
    # Get supplier bank details
    supplier_doc = frappe.get_doc("Supplier", supplier)

    # Find supplier's bank account
    bank_accounts = frappe.get_all(
        "Bank Account",
        filters={"party_type": "Supplier", "party": supplier},
        fields=["iban", "branch_code"],  # branch_code often used for BIC
    )

    if not bank_accounts:
        raise PontoIntegrationError(
            message=f"Supplier {supplier} has no linked bank account",
            details={"supplier": supplier},
        )

    bank_account = bank_accounts[0]

    if not bank_account.iban:
        raise PontoIntegrationError(
            message=f"Supplier {supplier}'s bank account has no IBAN",
            details={"supplier": supplier},
        )

    # Get default Ponto account if not specified
    if not ponto_account_id:
        settings = frappe.get_single("Ponto Settings")
        enabled_accounts = [m for m in settings.bank_account_mappings if m.enabled]
        if not enabled_accounts:
            raise PontoIntegrationError(
                message="No enabled Ponto accounts configured",
            )
        ponto_account_id = enabled_accounts[0].ponto_account_id

    return create_sepa_payment(
        ponto_account_id=ponto_account_id,
        amount=amount,
        creditor_name=supplier_doc.supplier_name,
        creditor_iban=bank_account.iban,
        creditor_bic=bank_account.branch_code,  # BIC stored in branch_code
        remittance_info=remittance_info,
        reference_doctype="Supplier",
        reference_name=supplier,
        auto_submit=auto_submit,
    )
