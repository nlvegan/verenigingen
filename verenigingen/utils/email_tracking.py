#!/usr/bin/env python3
"""
Email Tracking Utilities
========================

Utilities for tracking email opens, clicks, and engagement.
Integrates with external email service tracking webhooks.
"""

from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime


def process_tracking_webhook(webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process email tracking webhook from external service

    Args:
        webhook_payload: Webhook data containing tracking information

    Returns:
        Dict with processing result
    """
    try:
        event_type = webhook_payload.get("type", "")
        event_data = webhook_payload.get("data", {})
        email = event_data.get("email", "")
        tracking_id = event_data.get("tracking_id", "")

        if not email:
            return {"success": False, "error": "Missing email in tracking data"}

        # Find member by email
        members = frappe.get_all("Member", filters={"email": email}, fields=["name"])

        if not members:
            return {"success": False, "error": f"No member found for email: {email}"}

        member_name = members[0].name

        # Process different tracking events
        if event_type == "open":
            return _process_email_open(tracking_id, member_name, email, event_data)
        elif event_type == "click":
            return _process_email_click(tracking_id, member_name, email, event_data)
        elif event_type == "delivered":
            return _process_email_delivery(tracking_id, member_name, email, event_data)
        else:
            return {"success": True, "action": "unknown_event", "type": event_type}

    except Exception as e:
        frappe.log_error(f"Tracking webhook processing failed: {str(e)}")
        return {"success": False, "error": str(e)}


def _process_email_open(tracking_id: str, member_name: str, email: str, event_data: Dict) -> Dict[str, Any]:
    """Process email open event"""
    try:
        # Use the actual analytics tracker
        from verenigingen.email.analytics_tracker import track_open

        track_open(tracking_id, email)

        return {"success": True, "action": "tracked_open", "member": member_name, "tracking_id": tracking_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _process_email_click(tracking_id: str, member_name: str, email: str, event_data: Dict) -> Dict[str, Any]:
    """Process email click event"""
    try:
        url = event_data.get("url", "")

        # Use the actual analytics tracker
        from verenigingen.email.analytics_tracker import track_click

        track_click(tracking_id, url, email)

        return {
            "success": True,
            "action": "tracked_click",
            "member": member_name,
            "tracking_id": tracking_id,
            "url": url,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _process_email_delivery(
    tracking_id: str, member_name: str, email: str, event_data: Dict
) -> Dict[str, Any]:
    """Process email delivery event"""
    try:
        # Create delivery record if needed
        return {
            "success": True,
            "action": "tracked_delivery",
            "member": member_name,
            "tracking_id": tracking_id,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_member_engagement_stats(email: str, days: int = 30) -> Dict[str, Any]:
    """
    Get engagement statistics for a specific member

    Args:
        email: Member email address
        days: Number of days to analyze

    Returns:
        Dict with engagement statistics
    """
    try:
        # Use the actual analytics tracker
        from verenigingen.email.analytics_tracker import get_member_engagement

        engagement_data = get_member_engagement(email)

        return {"success": True, "email": email, "engagement_data": engagement_data}

    except Exception as e:
        frappe.log_error(f"Get member engagement failed: {str(e)}")
        return {"success": False, "error": str(e)}
