#!/usr/bin/env python3
"""
Email Bounce Handler
===================

Utilities for handling email bounces and delivery failures.
Integrates with external email service webhooks.
"""

from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime


def process_bounce_webhook(webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process email bounce webhook from external service

    Args:
        webhook_payload: Webhook data containing bounce information

    Returns:
        Dict with processing result
    """
    try:
        bounce_data = webhook_payload.get("data", {})
        email = bounce_data.get("email", "")
        bounce_type = bounce_data.get("bounce_type", "")
        reason = bounce_data.get("reason", "")

        if not email:
            return {"success": False, "error": "Missing email in bounce data"}

        # Find member by email
        members = frappe.get_all("Member", filters={"email": email}, fields=["name"])

        if not members:
            return {"success": False, "error": f"No member found for email: {email}"}

        member_name = members[0].name

        # Create bounce record
        bounce_record = frappe.new_doc("Email Bounce Record")
        bounce_record.update(
            {
                "member": member_name,
                "email_address": email,
                "bounce_type": bounce_type.title() if bounce_type else "Unknown",
                "reason": reason,
                "bounce_date": now_datetime(),
                "webhook_data": frappe.as_json(webhook_payload),
            }
        )
        bounce_record.insert()

        # Handle based on bounce type
        action_taken = "recorded"

        if bounce_type == "hard":
            # Disable email notifications for hard bounces
            member_doc = frappe.get_doc("Member", member_name)
            member_doc.email_notifications_disabled = 1
            member_doc.newsletter_status = "Bounced"
            member_doc.save()
            action_taken = "disabled_notifications"

        elif bounce_type == "soft":
            # Log soft bounce but don't disable immediately
            # Real implementation might count soft bounces
            action_taken = "logged_soft_bounce"

        return {
            "success": True,
            "action": action_taken,
            "member": member_name,
            "bounce_type": bounce_type,
            "bounce_record": bounce_record.name,
        }

    except Exception as e:
        frappe.log_error(f"Bounce webhook processing failed: {str(e)}")
        return {"success": False, "error": str(e)}


def get_bounce_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get email bounce statistics for specified period

    Args:
        days: Number of days to analyze

    Returns:
        Dict with bounce statistics
    """
    try:
        from frappe.utils import add_days

        start_date = add_days(None, -days)

        # Get bounce records for period
        bounce_records = frappe.get_all(
            "Email Bounce Record",
            filters={"bounce_date": [">=", start_date]},
            fields=["bounce_type", "reason"],
        )

        # Calculate statistics
        total_bounces = len(bounce_records)
        hard_bounces = len([r for r in bounce_records if r.bounce_type == "Hard Bounce"])
        soft_bounces = len([r for r in bounce_records if r.bounce_type == "Soft Bounce"])

        # Count reasons
        reasons = {}
        for record in bounce_records:
            reason = record.reason or "Unknown"
            reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "success": True,
            "period_days": days,
            "total_bounces": total_bounces,
            "hard_bounces": hard_bounces,
            "soft_bounces": soft_bounces,
            "bounce_reasons": reasons,
        }

    except Exception as e:
        frappe.log_error(f"Get bounce statistics failed: {str(e)}")
        return {"success": False, "error": str(e)}
