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


@frappe.whitelist()
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

    if not frappe.db.exists("ING Checkout Mandate", mandate_name):
        return {"success": False, "error": _("Mandate not found")}

    from verenigingen.verenigingen_payments.ing_checkout.services.mandate_service import get_mandate_service

    service = get_mandate_service()
    return service.sync_mandate_status(mandate_name)


@frappe.whitelist()
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
