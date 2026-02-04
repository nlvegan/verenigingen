"""
Mollie Member Reconciliation Page

Member-centric view for reconciling Mollie subscription data with Member records.
Shows all subscriptions per member and allows updating Member fields.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.services.payment.mollie_reconciliation_service import (
    MollieReconciliationService,
)
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import critical_api


def get_context(context):
    """Build page context with comprehensive permission validation."""
    context.no_cache = 1
    context.show_sidebar = False

    # Validate comprehensive permissions for financial reconciliation
    required_permissions = [
        ("Member", "read"),
        ("Member", "write"),  # Need write to update fields
        ("Mollie Settings", "read"),
        ("Verenigingen Payments Settings", "read"),
    ]

    for doctype, ptype in required_permissions:
        if not frappe.has_permission(doctype, ptype):
            frappe.throw(
                f"Insufficient permissions: {doctype} {ptype} access required for member reconciliation",
                frappe.PermissionError,
            )

    return context


def _publish_progress(message: str, progress: int) -> None:
    """Publish progress update via realtime."""
    frappe.publish_realtime(
        "reconciliation_progress",
        {"message": message, "progress": progress},
        user=frappe.session.user,
    )


@frappe.whitelist()
@critical_api()  # Financial data and member updates
def get_member_reconciliation_data() -> OperationResult[Dict[str, Any]]:
    """
    Get member-centric reconciliation data showing all Mollie subscriptions per member.

    Security: Requires Member read/write, Mollie Settings read permissions.

    Returns:
        OperationResult[Dict[str, Any]]: Member reconciliation data with subscriptions grouped by member
    """
    try:
        service = MollieReconciliationService()
        result = service.get_reconciliation_data(progress_callback=_publish_progress)

        return OperationResult.ok(result, message=_("Member reconciliation completed successfully"))

    except Exception as e:
        frappe.log_error(
            f"Member reconciliation failed: {str(e)}\n{traceback.format_exc()}",
            "Member Reconciliation Error",
        )
        return OperationResult.fail(
            _("Unable to complete member reconciliation. Please contact support."),
            errors=[str(e)],
            context={"operation": "get_member_reconciliation_data"},
        )


@frappe.whitelist()
@critical_api()  # Financial data updates
def update_member_mollie_fields(
    member_id: str,
    mollie_subscription_id: str | None = None,
    subscription_status: str | None = None,
    next_payment_date: str | None = None,
    mollie_subscription_next_invoice_date: str | None = None,
) -> OperationResult[Dict[str, Any]]:
    """
    Update Member's Mollie-related fields and return updated member data.

    Security: Requires Member write permission.

    Args:
        member_id: Member ID to update
        mollie_subscription_id: New subscription ID (optional, can be None to clear)
        subscription_status: New subscription status (optional)
        next_payment_date: New next payment date (optional)
        mollie_subscription_next_invoice_date: Next invoice date from Mollie (optional)

    Returns:
        OperationResult[Dict[str, Any]]: Success status, updated values, and refreshed member data
    """
    try:
        member = frappe.get_doc("Member", member_id)

        # Check write permission
        if not frappe.has_permission("Member", "write", member):
            return OperationResult.fail(
                _("Insufficient permissions to update Member {0}").format(member_id),
                errors=["Permission denied"],
                context={"operation": "update_member_mollie_fields", "member_id": member_id},
            )

        # Update fields if provided
        updated_fields = []

        if mollie_subscription_id is not None:  # Allow clearing by passing empty string
            member.mollie_subscription_id = mollie_subscription_id or None
            updated_fields.append("mollie_subscription_id")

        if subscription_status:
            member.subscription_status = subscription_status
            updated_fields.append("subscription_status")

        if next_payment_date:
            member.next_payment_date = next_payment_date
            updated_fields.append("next_payment_date")

        if mollie_subscription_next_invoice_date:
            member.mollie_subscription_next_invoice_date = mollie_subscription_next_invoice_date
            updated_fields.append("mollie_subscription_next_invoice_date")

        if updated_fields:
            member.save()
            frappe.db.commit()

            result = {
                "member_id": member_id,
                "updated_fields": updated_fields,
                "message": f"Updated {', '.join(updated_fields)} for {member.full_name}",
                "updated_member": {
                    "member_id": member.name,
                    "current_subscription_status": member.subscription_status,
                    "current_subscription_id": member.mollie_subscription_id,
                    "current_next_payment_date": member.next_payment_date,
                    "current_mollie_next_invoice_date": member.mollie_subscription_next_invoice_date,
                },
            }
            return OperationResult.ok(result, message=_("Member updated successfully"))
        else:
            return OperationResult.fail(
                _("No fields to update"),
                errors=["No fields provided"],
                context={"operation": "update_member_mollie_fields", "member_id": member_id},
            )

    except Exception as e:
        frappe.log_error(
            f"Failed to update member {member_id}: {str(e)}\n{traceback.format_exc()}",
            "Member Reconciliation Update Error",
        )
        return OperationResult.fail(
            _("Unable to update member. Please contact support."),
            errors=[str(e)],
            context={"operation": "update_member_mollie_fields", "member_id": member_id},
        )
