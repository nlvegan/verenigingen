# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout Mandate API Endpoints

Provides whitelisted methods for mandate operations:
- Creating mandates for members
- Executing direct debits
- Checking mandate status
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    member_solely_holds_customer,
    validate_member_ownership,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


def _is_staff() -> bool:
    return bool(set(frappe.get_roles()) & Roles.ADMIN_ROLES)


def _refuse_mandate_access():
    frappe.throw(_("You can only access your own member information"), frappe.PermissionError)


def _require_mandate_access(mandate_name: str, sales_invoice: str = None) -> None:
    """Refuse unless the caller is staff or owns the mandate (#1089, ruling #1101).

    A non-staff caller gets the identical PermissionError for an unknown mandate
    and for someone else's mandate (#1328): one get_value decides both, so there
    is no existence oracle. With ``sales_invoice``, the invoice's customer must
    also be the mandate owner's customer, or the pair is refused the same way.
    """
    if _is_staff():
        return
    owner = frappe.db.get_value("ING Checkout Mandate", mandate_name, "member")
    current_member = get_current_user_member_name()
    if not owner or not current_member or owner != current_member:
        _refuse_mandate_access()
    if sales_invoice is not None:
        member_customer = frappe.db.get_value("Member", owner, "customer")
        invoice = frappe.db.get_value("Sales Invoice", sales_invoice, ["customer", "member"], as_dict=True)
        invoice_customer = invoice.customer if invoice else None
        sole_holder = member_solely_holds_customer(owner, member_customer)
        if not member_customer or member_customer != invoice_customer:
            _refuse_mandate_access()
        # A blank-member invoice is claimed through its Customer alone: refused when shared (#2493).
        if invoice and not invoice.member and not sole_holder:
            _refuse_mandate_access()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_mandate_for_member(
    member_name: str,
    mandate_type: str = "flexible",
    amount: float = None,
    description: str = None,
) -> dict:
    """
    Create a SEPA Direct Debit mandate for a member.

    Args:
        member_name: Member document name
        mandate_type: Type of mandate (single, recurring, flexible)
        amount: Optional amount for single/recurring mandates
        description: Optional description

    Returns:
        dict with success status and mandate info
    """
    if not member_name:
        return {"success": False, "error": _("Member name is required")}

    if mandate_type not in ["single", "recurring", "flexible"]:
        return {"success": False, "error": _("Invalid mandate type")}

    validate_member_ownership(member_name, allow_admin=True)

    if not frappe.db.exists("Member", member_name):
        return {"success": False, "error": _("Member not found")}

    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import get_mandate_service

    service = get_mandate_service()
    return service.create_mandate_for_member(
        member_name=member_name,
        mandate_type=mandate_type,
        amount=float(amount) if amount else None,
        description=description,
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def execute_debit_for_invoice(
    mandate_name: str,
    sales_invoice: str,
    process_date: str = None,
) -> dict:
    """
    Execute a direct debit for a Sales Invoice.

    Args:
        mandate_name: ING Checkout Mandate document name
        sales_invoice: Sales Invoice document name
        process_date: Optional date to process (YYYY-MM-DD)

    Returns:
        dict with success status and debit reference
    """
    if not mandate_name:
        return {"success": False, "error": _("Mandate name is required")}

    if not sales_invoice:
        return {"success": False, "error": _("Sales Invoice is required")}

    _require_mandate_access(mandate_name, sales_invoice)

    if not frappe.db.exists("ING Checkout Mandate", mandate_name):
        return {"success": False, "error": _("Mandate not found")}

    if not frappe.db.exists("Sales Invoice", sales_invoice):
        return {"success": False, "error": _("Sales Invoice not found")}

    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import get_mandate_service

    service = get_mandate_service()
    return service.execute_debit_for_invoice(
        mandate_name=mandate_name,
        sales_invoice=sales_invoice,
        process_date=process_date,
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_mandate_status(mandate_name: str) -> dict:
    """
    Get the current status of a mandate.

    Args:
        mandate_name: ING Checkout Mandate document name

    Returns:
        dict with mandate status
    """
    if not mandate_name:
        return {"success": False, "error": _("Mandate name is required")}

    _require_mandate_access(mandate_name)

    if not frappe.db.exists("ING Checkout Mandate", mandate_name):
        return {"success": False, "error": _("Mandate not found")}

    mandate = frappe.get_doc("ING Checkout Mandate", mandate_name)
    return {
        "success": True,
        "name": mandate.name,
        "mandate_id": mandate.mandate_id,
        "status": mandate.status,
        "mandate_type": mandate.mandate_type,
        "debtor_name": mandate.debtor_name,
        "debtor_iban": mandate.debtor_iban,
        "member": mandate.member,
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def sync_mandate_status(mandate_name: str) -> dict:
    """
    Synchronize mandate status with Pay.nl.

    Args:
        mandate_name: ING Checkout Mandate document name

    Returns:
        dict with updated status
    """
    if not mandate_name:
        return {"success": False, "error": _("Mandate name is required")}

    _require_mandate_access(mandate_name)

    if not frappe.db.exists("ING Checkout Mandate", mandate_name):
        return {"success": False, "error": _("Mandate not found")}

    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import get_mandate_service

    service = get_mandate_service()
    return service.sync_mandate_status(mandate_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_mandate(mandate_name: str) -> dict:
    """
    Cancel a mandate.

    Args:
        mandate_name: ING Checkout Mandate document name

    Returns:
        dict with success status
    """
    if not mandate_name:
        return {"success": False, "error": _("Mandate name is required")}

    _require_mandate_access(mandate_name)

    if not frappe.db.exists("ING Checkout Mandate", mandate_name):
        return {"success": False, "error": _("Mandate not found")}

    try:
        mandate = frappe.get_doc("ING Checkout Mandate", mandate_name)
        mandate.cancel()
        return {
            "success": True,
            "status": mandate.status,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_member_mandates(member_name: str) -> dict:
    """
    Get all mandates for a member.

    Args:
        member_name: Member document name

    Returns:
        dict with list of mandates
    """
    if not member_name:
        return {"success": False, "error": _("Member name is required")}

    validate_member_ownership(member_name, allow_admin=True)

    if not frappe.db.exists("Member", member_name):
        return {"success": False, "error": _("Member not found")}

    mandates = frappe.get_all(
        "ING Checkout Mandate",
        filters={"member": member_name},
        fields=[
            "name",
            "mandate_id",
            "mandate_type",
            "status",
            "debtor_iban",
            "created_date",
            "expiry_date",
        ],
        order_by="creation desc",
    )

    return {
        "success": True,
        "mandates": mandates,
    }
