"""
Debug and diagnostic endpoints for membership application troubleshooting.

These endpoints are development-only and blocked in production environments.
Extracted from membership_application_review.py for separation of concerns.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
)


def _safe_log_error(message, title=None):
    """Helper to log errors with length protection"""
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_and_fix_member_approval(member_name: str):
    """Debug and fix member approval issues"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Check field access
        result = {
            "member": member.name,
            "full_name": member.full_name,
            "application_status": member.application_status,
            "has_selected_type": hasattr(member, "selected_membership_type"),
            "selected_membership_type": getattr(member, "selected_membership_type", None),
            "has_current_type": hasattr(member, "current_membership_type"),
            "current_membership_type": getattr(member, "current_membership_type", None),
        }

        # Get available membership types
        membership_types = frappe.get_all(
            "Membership Type", fields=["name", "membership_type_name", "minimum_amount"]
        )
        result["available_membership_types"] = len(membership_types)
        result["membership_types"] = membership_types[:3]  # Show first 3

        # Try to fix if no membership type is set
        if (
            not result["selected_membership_type"]
            and not result["current_membership_type"]
            and membership_types
        ):
            default_type = membership_types[0].name
            try:
                member.selected_membership_type = default_type
                member.save()
                result["fix_applied"] = True
                result["default_type_set"] = default_type
                result["selected_membership_type"] = default_type
            except AttributeError:
                # Field doesn't exist yet, but we can still use it for approval
                result["fix_applied"] = "field_missing_but_will_work"
                result["default_type_set"] = default_type
                result["note"] = "Field not in database yet, but approval logic will handle this"
        else:
            result["fix_applied"] = False

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_member_approval(member_name: str):
    """Test member approval without actually approving"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Test the same logic as in approve_membership_application
        membership_type = None

        # Use the same fallback logic
        if not membership_type:
            membership_type = getattr(member, "selected_membership_type", None)

        if not membership_type:
            membership_type = getattr(member, "current_membership_type", None)

        if not membership_type:
            membership_types = frappe.get_all("Membership Type", fields=["name"], limit=1)
            if membership_types:
                membership_type = membership_types[0].name

        result = {
            "member": member.name,
            "application_status": member.application_status,
            "resolved_membership_type": membership_type,
            "can_approve": bool(membership_type and member.application_status == "Pending"),
            "status": "Ready for approval" if membership_type else "No membership type available",
        }

        return result

    except Exception as e:
        return {"error": str(e), "member": member_name}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_member_iban_data(member_name: str):
    """Check the current IBAN data for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member.name,
            "full_name": member.full_name,
            "payment_method": getattr(member, "payment_method", "Not set"),
            "iban": getattr(member, "iban", "Not set"),
            "bic": getattr(member, "bic", "Not set"),
            "bank_account_name": getattr(member, "bank_account_name", "Not set"),
            "application_id": getattr(member, "application_id", "Not set"),
            "application_status": getattr(member, "application_status", "Not set"),
        }

        return result

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_custom_amount_flow(member_name: str):
    """Debug the custom amount flow for a specific member"""
    try:
        member = frappe.get_doc("Member", member_name)

        result = {
            "member_name": member_name,
            "full_name": member.full_name,
            "has_notes": bool(getattr(member, "notes", None)),
            "notes": getattr(member, "notes", ""),
            "custom_amount_data": None,
            "error": None,
        }

        # Legacy JSON parsing removed - check direct fee override field
        result["dues_rate"] = getattr(member, "dues_rate", None)
        result["uses_custom_amount"] = bool(getattr(member, "dues_rate", None))
        result["membership_amount"] = getattr(member, "dues_rate", None)

        # Check existing memberships
        memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name},
            fields=["name", "membership_type", "status"],
        )

        result["memberships"] = memberships

        # Check dues schedules if any
        for membership in memberships:
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "payment_terms_template", "dues_rate", "billing_frequency", "status"],
            )
            membership["dues_schedules"] = dues_schedules

        return result

    except Exception as e:
        return {"error": str(e), "member_name": member_name}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_membership_dues_schedule(membership_name: str):
    """Debug a specific membership and its dues schedule"""
    try:
        membership = frappe.get_doc("Membership", membership_name)

        result = {
            "membership_name": membership_name,
            "billing_amount": membership.get_billing_amount(),
            "dues_schedules": [],
        }

        # Get all dues schedules for this member
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": membership.member},
            fields=[
                "name",
                "contribution_mode",
                "dues_rate",
                "billing_frequency",
                "status",
                "next_invoice_date",
                "last_invoice_date",
            ],
        )

        for schedule in dues_schedules:
            schedule_data = {
                "name": schedule.name,
                "contribution_mode": schedule.contribution_mode,
                "dues_rate": schedule.dues_rate,
                "billing_frequency": schedule.billing_frequency,
                "status": schedule.status,
                "next_invoice_date": schedule.next_invoice_date,
                "last_invoice_date": schedule.last_invoice_date,
            }
            result["dues_schedules"].append(schedule_data)

        return result

    except Exception as e:
        return {"error": str(e), "membership_name": membership_name}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_membership_type_settings(membership_type_name: str):
    """Debug a membership type and its settings"""
    try:
        membership_type = frappe.get_doc("Membership Type", membership_type_name)

        # Get amount from template
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)

        result = {
            "membership_type_name": membership_type_name,
            "membership_type_details": {
                "membership_type_name": membership_type.membership_type_name,
                "amount": template.suggested_amount or 0,
                "description": membership_type.description,
            },
        }

        return result

    except Exception as e:
        return {"error": str(e), "membership_type_name": membership_type_name}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def check_dues_schedule_invoice_relationship(invoice_name: str):
    """Check dues schedule invoice relationships"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        result = {
            "invoice_name": invoice_name,
            "customer": invoice.customer,
            "grand_total": invoice.grand_total,
            "docstatus": invoice.docstatus,
            "status": invoice.status,
            "dues_schedule": None,
        }

        # Find related dues schedule
        if invoice.customer:
            member = frappe.db.get_value("Member", {"customer": invoice.customer}, "name")
            if member:
                dues_schedule = frappe.get_all(
                    "Membership Dues Schedule",
                    filters={"member": member, "status": "Active"},
                    fields=["name", "contribution_mode", "dues_rate"],
                    limit=1,
                )
                if dues_schedule:
                    result["dues_schedule"] = dues_schedule[0]

        return result

    except Exception as e:
        return {"error": str(e), "invoice_name": invoice_name}
