#!/usr/bin/env python3
"""
Newsletter Integration Utilities
================================

Webhook and integration utilities for external newsletter services.
These are lightweight wrappers for testing boundary integration points.
"""

from typing import Any, Dict

import frappe
from frappe import _


def process_newsletter_webhook(webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process webhook from external newsletter service

    Args:
        webhook_payload: Webhook data from newsletter service

    Returns:
        Dict with processing result
    """
    try:
        webhook_type = webhook_payload.get("type", "")
        data = webhook_payload.get("data", {})
        email = data.get("email", "")

        if not email:
            return {"success": False, "error": "Missing email in webhook data"}

        if webhook_type == "subscription_confirmed":
            # Update member newsletter status
            members = frappe.get_all("Member", filters={"email": email}, fields=["name"])

            if members:
                member_doc = frappe.get_doc("Member", members[0].name)
                member_doc.newsletter_status = "Subscribed"
                member_doc.newsletter_confirmed_date = frappe.utils.now_datetime()
                member_doc.save()

                return {"success": True, "action": "confirmed_subscription", "member": member_doc.name}

        elif webhook_type == "unsubscribed":
            # Update member newsletter status
            members = frappe.get_all("Member", filters={"email": email}, fields=["name"])

            if members:
                member_doc = frappe.get_doc("Member", members[0].name)
                member_doc.newsletter_status = "Unsubscribed"
                member_doc.newsletter_unsubscribed_date = frappe.utils.now_datetime()
                member_doc.save()

                return {"success": True, "action": "unsubscribed", "member": member_doc.name}

        return {"success": True, "action": "processed", "type": webhook_type}

    except Exception as e:
        frappe.log_error(f"Newsletter webhook processing failed: {str(e)}")
        return {"success": False, "error": str(e)}


def sync_newsletter_subscriptions() -> Dict[str, Any]:
    """
    Sync member newsletter subscriptions with external service

    Returns:
        Dict with sync results
    """
    try:
        # Get all members with newsletter subscription status
        members = frappe.get_all(
            "Member",
            filters={"newsletter_status": ["in", ["Subscribed", "Pending"]]},
            fields=["name", "email", "newsletter_status"],
        )

        synced_count = 0
        for member in members:
            # In a real implementation, this would sync with external service
            # For testing purposes, we just validate the data
            if member.email and "@" in member.email:
                synced_count += 1

        return {
            "success": True,
            "total_members": len(members),
            "synced_count": synced_count,
            "message": f"Synced {synced_count} member subscriptions",
        }

    except Exception as e:
        frappe.log_error(f"Newsletter sync failed: {str(e)}")
        return {"success": False, "error": str(e)}
