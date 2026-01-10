"""
Mollie Member Reconciliation Page

Member-centric view for reconciling Mollie subscription data with Member records.
Shows all subscriptions per member and allows updating Member fields.
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import critical_api
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient


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
        # Get membership dues keywords from settings
        settings = get_payments_settings()
        dues_keywords = [k.strip().lower() for k in (settings.dues_keywords or "contributie").split(",")]

        frappe.publish_realtime(
            "reconciliation_progress",
            {
                "message": f"Fetching Mollie subscriptions (filtering for: {', '.join(dues_keywords)})...",
                "progress": 10,
            },
            user=frappe.session.user,
        )

        # Fetch all subscriptions from Mollie
        client = MollieClient()
        all_subscriptions = _fetch_all_mollie_subscriptions(client)

        frappe.publish_realtime(
            "reconciliation_progress",
            {
                "message": f"Filtering {len(all_subscriptions)} subscriptions for membership dues...",
                "progress": 30,
            },
            user=frappe.session.user,
        )

        # Filter for membership dues subscriptions only
        dues_subscriptions = []
        for sub in all_subscriptions:
            description = (sub.get("description") or "").lower()
            if any(keyword in description for keyword in dues_keywords):
                dues_subscriptions.append(sub)

        frappe.publish_realtime(
            "reconciliation_progress",
            {
                "message": f"Found {len(dues_subscriptions)} membership dues subscriptions. Loading members...",
                "progress": 50,
            },
            user=frappe.session.user,
        )

        # Fetch all members with Mollie data
        members = frappe.get_all(
            "Member",
            filters={"mollie_customer_id": ["is", "set"]},
            fields=[
                "name",
                "full_name",
                "status",
                "subscription_status",
                "mollie_customer_id",
                "mollie_subscription_id",
                "next_payment_date",
                "mollie_subscription_next_invoice_date",
            ],
        )

        frappe.publish_realtime(
            "reconciliation_progress",
            {"message": f"Processing {len(members)} members with Mollie data...", "progress": 70},
            user=frappe.session.user,
        )

        # Build member reconciliation data
        member_data = _build_member_reconciliation(members, dues_subscriptions)

        frappe.publish_realtime(
            "reconciliation_progress",
            {"message": "Reconciliation complete!", "progress": 100},
            user=frappe.session.user,
        )

        result = {
            "members": member_data,
            "total_members": len(member_data),
            "dues_keywords": dues_keywords,
            "test_mode": client.test_mode,
        }

        return OperationResult.ok(result, message=_("Member reconciliation completed successfully"))

    except Exception as e:
        frappe.log_error(
            f"Member reconciliation failed: {str(e)}\n{traceback.format_exc()}", "Member Reconciliation Error"
        )
        return OperationResult.fail(
            _("Unable to complete member reconciliation. Please contact support."),
            errors=[str(e)],
            context={"operation": "get_member_reconciliation_data"},
        )


def _fetch_all_mollie_subscriptions(client):
    """Fetch all subscriptions from Mollie API with pagination."""
    all_subscriptions = []
    next_url = None
    page_count = 0

    endpoint = "subscriptions?limit=250"

    while True:
        page_count += 1

        frappe.publish_realtime(
            "reconciliation_progress",
            {"message": f"Fetching page {page_count} from Mollie API...", "progress": 10 + (page_count * 2)},
            user=frappe.session.user,
        )

        if next_url:
            response = client._make_request("GET", next_url.replace(client.BASE_URL, ""))
        else:
            response = client._make_request("GET", endpoint)

        subscriptions = response.get("_embedded", {}).get("subscriptions", [])
        all_subscriptions.extend(subscriptions)

        # Check for pagination
        next_link = response.get("_links", {}).get("next", {})
        if next_link and next_link.get("href"):
            next_url = next_link["href"]
        else:
            break

    return all_subscriptions


def _build_member_reconciliation(members, mollie_subscriptions):
    """
    Build member-centric reconciliation data.

    Args:
        members: List of Member records with Mollie data
        mollie_subscriptions: List of Mollie subscriptions (membership dues only)

    Returns:
        list: Member reconciliation data with subscriptions grouped by member
    """
    # Group subscriptions by customer ID
    subs_by_customer = {}
    for sub in mollie_subscriptions:
        customer_id = sub.get("customerId")
        if customer_id:
            if customer_id not in subs_by_customer:
                subs_by_customer[customer_id] = []
            subs_by_customer[customer_id].append(
                {
                    "subscription_id": sub.get("id"),
                    "status": sub.get("status"),
                    "description": sub.get("description"),
                    "amount": sub.get("amount", {}).get("value"),
                    "interval": sub.get("interval"),
                    "next_payment_date": sub.get("nextPaymentDate"),
                    "created_at": sub.get("createdAt"),
                    "cancelled_at": sub.get("canceledAt"),
                }
            )

    # Build member reconciliation data
    member_data = []
    for member in members:
        customer_id = member.mollie_customer_id
        mollie_subs = subs_by_customer.get(customer_id, [])

        # Sort subscriptions: active first, then by creation date (newest first)
        mollie_subs.sort(key=lambda s: (s["status"] != "active", s.get("created_at", "")), reverse=True)

        # Categorize subscriptions
        active_subs = [s for s in mollie_subs if s["status"] == "active"]
        inactive_subs = [s for s in mollie_subs if s["status"] != "active"]

        # Determine discrepancies
        discrepancies = []
        suggested_subscription_id = None
        suggested_status = None

        if not active_subs and member.subscription_status in ["active", "pending"]:
            discrepancies.append("Member claims active subscription but no active subscription in Mollie")
            suggested_status = "canceled"
        elif len(active_subs) == 1:
            active_sub = active_subs[0]
            suggested_subscription_id = active_sub["subscription_id"]
            if member.mollie_subscription_id != active_sub["subscription_id"]:
                discrepancies.append(
                    f"Member subscription ID doesn't match Mollie ({member.mollie_subscription_id} vs {active_sub['subscription_id']})"
                )
            if member.subscription_status != active_sub["status"]:
                discrepancies.append(
                    f"Status mismatch ({member.subscription_status} vs {active_sub['status']})"
                )
                suggested_status = active_sub["status"]
        elif len(active_subs) > 1:
            discrepancies.append(
                f"Multiple active subscriptions found ({len(active_subs)}) - manual review needed"
            )
            # Suggest the newest one by default
            suggested_subscription_id = active_subs[0]["subscription_id"]

        # Get next invoice date from active subscription if available
        suggested_next_invoice_date = None
        if len(active_subs) > 0:
            suggested_next_invoice_date = active_subs[0].get("next_payment_date")

        member_data.append(
            {
                "member_id": member.name,
                "member_name": member.full_name,
                "member_status": member.status,
                "current_subscription_status": member.subscription_status,
                "current_subscription_id": member.mollie_subscription_id,
                "current_next_payment_date": member.next_payment_date,
                "current_mollie_next_invoice_date": member.mollie_subscription_next_invoice_date,
                "customer_id": customer_id,
                "active_subscriptions": active_subs,
                "inactive_subscriptions": inactive_subs,
                "discrepancies": discrepancies,
                "has_issues": len(discrepancies) > 0,
                "suggested_subscription_id": suggested_subscription_id,
                "suggested_status": suggested_status,
                "suggested_next_invoice_date": suggested_next_invoice_date,
            }
        )

    # Sort: issues first, then by member name
    member_data.sort(key=lambda m: (not m["has_issues"], m["member_name"]))

    return member_data


@frappe.whitelist()
@critical_api()  # Financial data updates
def update_member_mollie_fields(
    member_id,
    mollie_subscription_id=None,
    subscription_status=None,
    next_payment_date=None,
    mollie_subscription_next_invoice_date=None,
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
        OperationResult[Dict[str, Any]]: Success status, updated values, and refreshed member data for UI update
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

            # Return updated member data for frontend to use (no new API call needed)
            result = {
                "member_id": member_id,
                "updated_fields": updated_fields,
                "message": f"Updated {', '.join(updated_fields)} for {member.full_name}",
                # Return refreshed values so frontend can update display without reloading
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
