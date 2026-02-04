"""
Mollie Subscription Audit Page

Provides UI for running subscription audit without report timeout constraints.
Also provides webhook URL management for active subscriptions.
"""

import json
import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.services.payment.mollie_webhook_service import MollieWebhookService
from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import critical_api


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


def _publish_progress(event_name: str, message: str, progress: int) -> None:
    """Publish progress update via realtime."""
    frappe.publish_realtime(
        event_name,
        {"message": message, "progress": progress},
        user=frappe.session.user,
    )


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
        _publish_progress("audit_progress", "Starting audit...", 0)

        auditor = SubscriptionAudit()
        report = auditor.run_full_audit()

        _publish_progress("audit_progress", "Audit complete!", 100)

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
            f"Subscription audit failed: {str(e)}\n{traceback.format_exc()}",
            "Subscription Audit Error",
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
    service = MollieWebhookService()

    if not service.has_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    try:
        result = service.get_default_webhook_url()
        return OperationResult.ok(result, message=_("Default webhook URL retrieved"))

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
    service = MollieWebhookService()

    if not service.has_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    try:

        def progress_callback(message: str, progress: int) -> None:
            _publish_progress("webhook_fetch_progress", message, progress)

        result = service.get_active_subscriptions_with_webhooks(
            progress_callback=progress_callback,
        )

        return OperationResult.ok(
            result,
            message=_("Found {0} active subscriptions").format(result["total_found"]),
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
    service = MollieWebhookService()

    if not service.has_admin_access():
        return OperationResult.fail(
            _("Access denied - Verenigingen Staff or Administrator role required"),
            errors=["permission_denied"],
        )

    try:
        subscriptions = json.loads(subscriptions_json)
    except json.JSONDecodeError as e:
        return OperationResult.fail(
            _("Invalid JSON format"),
            errors=[str(e)],
        )

    try:

        def progress_callback(message: str, progress: int) -> None:
            _publish_progress("webhook_update_progress", message, progress)

        result = service.bulk_update_webhooks(
            subscriptions=subscriptions,
            new_webhook_url=new_webhook_url,
            progress_callback=progress_callback,
        )

        return OperationResult.ok(
            result,
            message=_("Updated {0} of {1} subscriptions").format(
                result["summary"]["success"],
                result["summary"]["total"],
            ),
        )

    except ValueError as e:
        return OperationResult.fail(str(e), errors=["validation_error"])

    except Exception as e:
        frappe.log_error(
            f"Failed to update webhooks: {str(e)}\n{traceback.format_exc()}",
            "Webhook Update Error",
        )
        return OperationResult.fail(
            _("Failed to update subscription webhooks"),
            errors=[str(e)],
        )
