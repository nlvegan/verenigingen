"""
Mollie Subscription Audit Page

Provides UI for running subscription audit without report timeout constraints.
"""

import json

import frappe

from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit
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


@frappe.whitelist()
@critical_api()  # Handles financial data and Mollie API access
def run_audit():
    """
    Run subscription audit and return results.
    This is called via AJAX so we can handle longer processing times.

    Security: Requires Member read, Mollie Settings read, and Payment Entry read permissions.
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
        return {
            "success": True,
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

    except Exception as e:
        frappe.log_error(f"Subscription audit failed: {str(e)}", "Subscription Audit")
        return {"success": False, "error": str(e)}
