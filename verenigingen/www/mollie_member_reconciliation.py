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


def _permission_denied_result() -> OperationResult[Dict[str, Any]]:
    """Identical refusal for update_member_mollie_fields, regardless of existence (#1334).

    Both the "member_id doesn't exist" and the "member_id exists but the caller
    can't write it" branches below return this SAME message/shape -- deliberately
    WITHOUT the caller-supplied member_id in the context/metadata, so an
    unauthorized caller cannot use any difference between the two responses to
    probe which member ids are real. Kept as one helper (not two call sites) so
    they can't drift apart.
    """
    return OperationResult.fail(
        _("Insufficient permissions to update this member"),
        errors=["Permission denied"],
        context={"operation": "update_member_mollie_fields"},
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

    Existence is resolved via a silent frappe.db.exists() BEFORE any
    permission-revealing branch runs (#1334): frappe.has_permission("Member",
    "write", doc=<name>) itself eagerly loads the target document and raises
    frappe.DoesNotExistError for a missing one -- true for any caller other
    than the literal "Administrator" user (measured on test_site_6) -- so
    calling it (or frappe.get_doc) on an unconfirmed id let the bare `except
    Exception` below catch that DoesNotExistError and return a DIFFERENT
    message than the explicit permission-denied branch: an existence oracle
    for an unauthorized caller. Both branches now return the identical
    _permission_denied_result().

    Trade-off: a genuinely AUTHORIZED caller (including an admin) who simply
    mistypes member_id now also sees "Insufficient permissions to update this
    member" instead of a distinct "not found" -- deliberate, since telling
    "authorized but missing" apart from "authorized and forbidden" would need
    this function to re-derive the same doc-level scoping decision
    frappe.has_permission() makes, without loading the document first (#1328
    is the open issue about that scoping decision being its own oracle).

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
        if not frappe.db.exists("Member", member_id):
            return _permission_denied_result()

        member = frappe.get_doc("Member", member_id)

        # Check write permission
        if not frappe.has_permission("Member", "write", member):
            return _permission_denied_result()

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
