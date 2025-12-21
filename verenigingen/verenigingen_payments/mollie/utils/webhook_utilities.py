"""
Webhook Processing Utilities

Common utilities for Mollie webhook processing to eliminate code duplication
and ensure consistent behavior across all webhook endpoints.
"""

from typing import Any, Dict, Optional

import frappe


def get_donation_by_payment_id(payment_id: str):
    """
    Find donation document by Mollie payment ID.

    Args:
        payment_id: Mollie payment ID (tr_xxxxx)

    Returns:
        Donation document or None if not found

    Raises:
        frappe.DoesNotExistError: If donation found but cannot be loaded
    """
    if not payment_id:
        frappe.logger().warning("❌ Empty payment_id provided to get_donation_by_payment_id")
        return None

    donations = frappe.get_all("Donation", filters={"payment_id": payment_id}, fields=["name"])

    if not donations:
        frappe.logger().warning(f"❌ Original donation not found for payment {payment_id}")
        return None

    return frappe.get_doc("Donation", donations[0]["name"])


def standardized_webhook_response(status: str, message: str, **additional_data) -> Dict[str, Any]:
    """
    Create standardized webhook response format.

    Args:
        status: "success", "error", or "ignored"
        message: Human-readable message
        **additional_data: Additional fields to include

    Returns:
        Standardized response dictionary
    """
    response = {"status": status, "message": message, "timestamp": frappe.utils.now()}

    # Add any additional fields
    response.update(additional_data)

    return response


def extract_webhook_ids(webhook_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Extract common IDs from webhook payload in a consistent way.

    Args:
        webhook_data: Parsed webhook JSON payload

    Returns:
        Dict with extracted IDs: payment_id, refund_id, chargeback_id
    """
    return {
        "payment_id": (webhook_data.get("payment", {}).get("id") or webhook_data.get("payment_id")),
        "refund_id": (
            webhook_data.get("id")
            if "refund" in str(webhook_data.get("resource", "")).lower()
            else webhook_data.get("refund", {}).get("id")
            or (webhook_data.get("id") if webhook_data.get("id", "").startswith("re_") else None)
        ),
        "chargeback_id": (
            webhook_data.get("id")
            if "chargeback" in str(webhook_data.get("resource", "")).lower()
            else webhook_data.get("chargeback", {}).get("id")
        ),
    }


def safe_extract_amount(webhook_data: Dict[str, Any], default: float = 0.0) -> float:
    """
    Safely extract amount from webhook data.

    Args:
        webhook_data: Parsed webhook JSON payload
        default: Default value if extraction fails

    Returns:
        Float amount or default
    """
    try:
        amount_data = webhook_data.get("amount", {})
        if isinstance(amount_data, dict):
            return float(amount_data.get("value", default))
        else:
            return float(amount_data or default)
    except (ValueError, TypeError):
        frappe.logger().warning(
            f"⚠️ Could not extract amount from webhook data: {webhook_data.get('amount')}"
        )
        return default


def safe_extract_date(webhook_data: Dict[str, Any], date_field: str = "created_at") -> Optional[str]:
    """
    Safely extract date from webhook data.

    Args:
        webhook_data: Parsed webhook JSON payload
        date_field: Field name to extract date from

    Returns:
        Date string in YYYY-MM-DD format or None
    """
    try:
        date_value = webhook_data.get(date_field)
        if date_value:
            # Extract date part (first 10 characters for YYYY-MM-DD)
            return date_value[:10] if len(date_value) >= 10 else None
    except (TypeError, AttributeError):
        frappe.logger().warning(f"⚠️ Could not extract {date_field} from webhook data")

    return None
