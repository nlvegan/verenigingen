"""
Mollie Subscription Audit Page

Provides UI for running subscription audit without report timeout constraints.
Also provides webhook URL management for active subscriptions.
"""

import json
import traceback
from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import critical_api


def has_webhook_admin_access() -> bool:
    """Check if current user has access to webhook management functions."""
    allowed_roles = [
        "System Manager",
        "Administrator",
        "Verenigingen Administrator",
        "Verenigingen Staff",
    ]
    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


def get_context(context):
    """Build page context with comprehensive permission validation."""
    context.no_cache = 1
    context.show_sidebar = False

    # Validate comprehensive permissions for financial audit
    required_permissions = [
        ("Member", "read"),
        ("Mollie Settings", "read"),
        ("Payment Entry", "read"),  # Financial audit context
    ]

    for doctype, ptype in required_permissions:
        if not frappe.has_permission(doctype, ptype):
            frappe.throw(
                f"Insufficient permissions: {doctype} {ptype} access required for subscription audit",
                frappe.PermissionError,
            )

    return context


@frappe.whitelist()
@critical_api()  # Handles financial data and Mollie API access
def run_audit() -> OperationResult[Dict[str, Any]]:
    """
    Run subscription audit and return results.
    This is called via AJAX so we can handle longer processing times.

    Security: Requires Member read, Mollie Settings read, and Payment Entry read permissions.

    Returns:
        OperationResult[Dict[str, Any]]: Audit results with summary and categorized issues
    """
    try:
        frappe.publish_realtime(
            "audit_progress", {"message": "Starting audit...", "progress": 0}, user=frappe.session.user
        )

        auditor = SubscriptionAudit()
        report = auditor.run_full_audit()

        frappe.publish_realtime(
            "audit_progress", {"message": "Audit complete!", "progress": 100}, user=frappe.session.user
        )

        # Format for display
        result = {
            "summary": report["summary"],
            "issues": {
                # Mollie-side issues
                "subscription_no_member_match": report["details"]["subscription_no_member_match"],
                "subscription_customer_no_member": report["details"]["subscription_customer_no_member"],
                "subscription_for_deleted_member": report["details"]["subscription_for_deleted_member"],
                "subscription_status_mismatch": report["details"]["subscription_status_mismatch"],
                # Database-side issues
                "member_subscription_not_in_mollie": report["details"]["member_subscription_not_in_mollie"],
                "member_incomplete_mollie_data": report["details"]["member_incomplete_mollie_data"],
            },
            "test_mode": report["test_mode"],
            "timestamp": report["audit_timestamp"],
        }

        return OperationResult.ok(result, message=_("Subscription audit completed successfully"))

    except Exception as e:
        frappe.log_error(
            f"Subscription audit failed: {str(e)}\n{traceback.format_exc()}", "Subscription Audit Error"
        )
        return OperationResult.fail(
            _("Unable to complete subscription audit. Please contact support."),
            errors=[str(e)],
            context={"operation": "run_audit"},
        )


@frappe.whitelist()
@critical_api()
def get_default_webhook_url() -> OperationResult[Dict[str, Any]]:
    """
    Get the default webhook URL from Mollie Settings based on current mode.

    Security: Requires Verenigingen Staff or Administrator role.

    Returns:
        OperationResult with webhook URL and mode information
    """
    if not has_webhook_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    try:
        mollie_settings = frappe.get_single("Mollie Settings")
        test_mode = mollie_settings.test_mode

        if test_mode:
            webhook_url = mollie_settings.testing_webhook_url
        else:
            webhook_url = mollie_settings.live_webhook_url

        return OperationResult.ok(
            {
                "webhook_url": webhook_url,
                "test_mode": test_mode,
                "mode_label": "Test" if test_mode else "Live",
            },
            message=_("Default webhook URL retrieved"),
        )

    except Exception as e:
        frappe.log_error(f"Failed to get default webhook URL: {str(e)}")
        return OperationResult.fail(
            _("Failed to retrieve webhook URL from Mollie Settings"),
            errors=[str(e)],
        )


@frappe.whitelist()
@critical_api()
def get_active_subscriptions_with_webhooks() -> OperationResult[Dict[str, Any]]:
    """
    Fetch all active Mollie subscriptions with their current webhook URLs.

    Security: Requires Verenigingen Staff or Administrator role.

    Returns:
        OperationResult with list of active subscriptions and their webhook URLs
    """
    if not has_webhook_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    try:
        frappe.publish_realtime(
            "webhook_fetch_progress",
            {"message": "Fetching active subscriptions...", "progress": 10},
            user=frappe.session.user,
        )

        # Get all members with active Mollie subscriptions
        members_with_subscriptions = frappe.get_all(
            "Member",
            filters={
                "mollie_customer_id": ["is", "set"],
                "mollie_subscription_id": ["is", "set"],
                "subscription_status": "Active",
            },
            fields=[
                "name",
                "full_name",
                "mollie_customer_id",
                "mollie_subscription_id",
            ],
        )

        service = MollieDebugService()
        subscriptions = []
        errors = []

        total = len(members_with_subscriptions)
        for idx, member in enumerate(members_with_subscriptions):
            try:
                # Get subscription details from Mollie
                result = service.debug_subscription(
                    member.mollie_subscription_id,
                    member.mollie_customer_id,
                )

                if result.get("subscription_found"):
                    sub_data = result.get("subscription_data", {})
                    subscriptions.append(
                        {
                            "member_id": member.name,
                            "member_name": member.full_name or member.name,
                            "customer_id": member.mollie_customer_id,
                            "subscription_id": member.mollie_subscription_id,
                            "status": sub_data.get("status"),
                            "current_webhook_url": sub_data.get("webhook_url"),
                            "amount": sub_data.get("amount"),
                            "interval": sub_data.get("interval"),
                        }
                    )
                elif result.get("error"):
                    errors.append(
                        {
                            "member_id": member.name,
                            "subscription_id": member.mollie_subscription_id,
                            "error": result.get("error"),
                        }
                    )

            except Exception as e:
                errors.append(
                    {
                        "member_id": member.name,
                        "subscription_id": member.mollie_subscription_id,
                        "error": str(e),
                    }
                )

            # Update progress
            if (idx + 1) % 10 == 0 or idx == total - 1:
                progress = int(10 + (idx + 1) / total * 80)
                frappe.publish_realtime(
                    "webhook_fetch_progress",
                    {"message": f"Processed {idx + 1}/{total} members...", "progress": progress},
                    user=frappe.session.user,
                )

        # Get default webhook URL for comparison
        mollie_settings = frappe.get_single("Mollie Settings")
        test_mode = mollie_settings.test_mode
        default_webhook = (
            mollie_settings.testing_webhook_url if test_mode else mollie_settings.live_webhook_url
        )

        frappe.publish_realtime(
            "webhook_fetch_progress",
            {"message": "Complete!", "progress": 100},
            user=frappe.session.user,
        )

        return OperationResult.ok(
            {
                "subscriptions": subscriptions,
                "errors": errors,
                "total_found": len(subscriptions),
                "total_errors": len(errors),
                "default_webhook_url": default_webhook,
                "test_mode": test_mode,
            },
            message=_("Found {0} active subscriptions").format(len(subscriptions)),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to fetch subscriptions: {str(e)}\n{traceback.format_exc()}",
            "Webhook Fetch Error",
        )
        return OperationResult.fail(
            _("Failed to fetch active subscriptions"),
            errors=[str(e)],
        )


@frappe.whitelist()
@critical_api()
def bulk_update_subscription_webhooks(
    subscriptions_json: str,
    new_webhook_url: str,
) -> OperationResult[Dict[str, Any]]:
    """
    Update webhook URLs for multiple subscriptions.

    Security: Requires Verenigingen Staff or Administrator role.

    Args:
        subscriptions_json: JSON array of objects with customer_id and subscription_id
        new_webhook_url: The new webhook URL to set

    Returns:
        OperationResult with update results for each subscription
    """
    if not has_webhook_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    if not new_webhook_url:
        return OperationResult.fail(
            _("Webhook URL is required"),
            errors=["missing_webhook_url"],
        )

    if not new_webhook_url.startswith("https://"):
        return OperationResult.fail(
            _("Webhook URL must use HTTPS"),
            errors=["invalid_webhook_url"],
        )

    try:
        subscriptions = json.loads(subscriptions_json)
    except json.JSONDecodeError as e:
        return OperationResult.fail(
            _("Invalid JSON format"),
            errors=[str(e)],
        )

    if not subscriptions:
        return OperationResult.fail(
            _("No subscriptions provided"),
            errors=["empty_list"],
        )

    service = MollieDebugService()
    results = []
    success_count = 0
    error_count = 0

    total = len(subscriptions)
    for idx, sub in enumerate(subscriptions):
        customer_id = sub.get("customer_id")
        subscription_id = sub.get("subscription_id")

        result = {
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "status": "pending",
            "error": None,
        }

        try:
            update_result = service.update_subscription_webhook(
                customer_id=customer_id,
                subscription_id=subscription_id,
                webhook_url=new_webhook_url,
                reason="Bulk webhook URL update via audit page",
            )

            if update_result.get("status") == "success":
                result["status"] = "success"
                result["old_webhook_url"] = update_result.get("old_webhook_url")
                success_count += 1
            else:
                result["status"] = "error"
                result["error"] = update_result.get("message", "Unknown error")
                error_count += 1

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            error_count += 1

        results.append(result)

        # Update progress
        if (idx + 1) % 5 == 0 or idx == total - 1:
            progress = int((idx + 1) / total * 100)
            frappe.publish_realtime(
                "webhook_update_progress",
                {"message": f"Updated {idx + 1}/{total}...", "progress": progress},
                user=frappe.session.user,
            )

    return OperationResult.ok(
        {
            "results": results,
            "summary": {
                "total": total,
                "success": success_count,
                "errors": error_count,
            },
            "new_webhook_url": new_webhook_url,
        },
        message=_("Updated {0} of {1} subscriptions").format(success_count, total),
    )
