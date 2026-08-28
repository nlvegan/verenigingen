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


def _nested_id(webhook_data: dict, key: str) -> Optional[str]:
    """``webhook_data[key]["id"]``, but only when that path really is a dict."""
    nested = webhook_data.get(key)
    return nested.get("id") if isinstance(nested, dict) else None


def _top_level_id(webhook_data: dict) -> Optional[str]:
    """The top-level ``id``, but only when it is a string."""
    value = webhook_data.get("id")
    return value if isinstance(value, str) else None


def extract_webhook_ids(webhook_data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Extract common IDs from webhook payload in a consistent way.

    A webhook payload is untrusted input, so every lookup here is defensive.
    This used to assume `payment`/`refund`/`chargeback` are dicts and that `id`
    is a str, and raised AttributeError otherwise -- on `{"id": None}`,
    `{"id": 12345}`, `{"chargeback": ["a"]}` and `{"payment": "tr_x"}` among
    others. Every caller wraps this in a broad `except`, so a raise became an
    HTTP 500, and Mollie then redelivered ~10 times over 26h for a payload that
    fails identically every time. Returning None lets the caller refuse it once.

    Args:
        webhook_data: Parsed webhook JSON payload

    Returns:
        Dict with extracted IDs: payment_id, refund_id, chargeback_id
    """
    if not isinstance(webhook_data, dict):
        # json.loads can hand back a list, a string or a number, not only an object.
        return {"payment_id": None, "refund_id": None, "chargeback_id": None}

    resource = str(webhook_data.get("resource", "")).lower()
    top_id = _top_level_id(webhook_data)

    return {
        "payment_id": _nested_id(webhook_data, "payment") or webhook_data.get("payment_id"),
        "refund_id": (
            top_id
            if "refund" in resource
            else _nested_id(webhook_data, "refund")
            or (top_id if top_id and top_id.startswith("re_") else None)
        ),
        "chargeback_id": (top_id if "chargeback" in resource else _nested_id(webhook_data, "chargeback")),
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
