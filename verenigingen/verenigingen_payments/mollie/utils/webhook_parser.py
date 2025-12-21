"""
Unified Mollie webhook parsing utility for consistent JSON event format handling.

This module provides a centralized, robust implementation for parsing Mollie webhooks
that supports both the modern JSON event format and legacy form data format.
All webhook handlers should use this utility to ensure consistency.
"""

from typing import Any, Dict, Optional, Tuple

import frappe


class MollieWebhookParser:
    """
    Centralized parser for Mollie webhook payloads.

    Handles both modern JSON event format and legacy form data format
    with robust error handling and validation.
    """

    @staticmethod
    def parse_webhook_data(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse webhook data and extract relevant IDs and event information.

        Args:
            webhook_data: Raw webhook payload data

        Returns:
            Dict containing:
            - event_type: Type of event (payment, subscription, ping)
            - payment_id: Payment ID if applicable
            - subscription_id: Subscription ID if applicable
            - is_ping: True if this is a ping event
            - raw_format: 'json_event' or 'form_data'
            - status: 'success' or 'error'
            - message: Status message
        """

        result = {
            "event_type": None,
            "payment_id": None,
            "subscription_id": None,
            "is_ping": False,
            "raw_format": "unknown",
            "status": "success",
            "message": "Webhook parsed successfully",
        }

        try:
            # Check for Mollie JSON event format
            if webhook_data.get("resource") == "event":
                return MollieWebhookParser._parse_json_event(webhook_data, result)
            else:
                return MollieWebhookParser._parse_legacy_format(webhook_data, result)

        except Exception as e:
            frappe.logger().error(f"Webhook parsing error: {str(e)}")
            result.update({"status": "error", "message": f"Webhook parsing failed: {str(e)}"})
            return result

    @staticmethod
    def _parse_json_event(webhook_data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse modern Mollie JSON event format."""

        result["raw_format"] = "json_event"
        event_type = webhook_data.get("type", "")
        result["event_type"] = event_type

        # Handle ping events
        if event_type == "hook.ping":
            result["is_ping"] = True
            result["message"] = "Webhook ping event received"
            return result

        # Extract entity ID based on event type
        entity_id = webhook_data.get("entityId")
        if not entity_id:
            result.update({"status": "error", "message": "Missing entityId in JSON event"})
            return result

        # Route based on event type
        if event_type.startswith("payment."):
            result["payment_id"] = entity_id
            result["event_type"] = "payment"

            # Check for subscription information in embedded data
            embedded_entity = webhook_data.get("_embedded", {}).get("entity", {})
            if embedded_entity.get("subscriptionId"):
                result["subscription_id"] = embedded_entity.get("subscriptionId")

        elif event_type.startswith("subscription."):
            result["subscription_id"] = entity_id
            result["event_type"] = "subscription"

        else:
            result.update({"status": "error", "message": f"Unsupported event type: {event_type}"})

        return result

    @staticmethod
    def _parse_legacy_format(webhook_data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse legacy form data format."""

        result["raw_format"] = "form_data"

        # Extract ID from webhook data
        webhook_id = webhook_data.get("id")
        if not webhook_id:
            result.update({"status": "error", "message": "Missing ID in legacy webhook format"})
            return result

        # Determine type based on ID prefix
        if webhook_id.startswith("tr_"):
            result["payment_id"] = webhook_id
            result["event_type"] = "payment"
        elif webhook_id.startswith("sub_"):
            result["subscription_id"] = webhook_id
            result["event_type"] = "subscription"
        else:
            result.update({"status": "error", "message": f"Unsupported webhook ID format: {webhook_id}"})

        return result

    @staticmethod
    def get_payment_id_from_webhook(webhook_data: Dict[str, Any]) -> Optional[str]:
        """
        Convenience method to extract just the payment ID.

        Returns None if no payment ID found or if this is a ping event.
        """
        parsed = MollieWebhookParser.parse_webhook_data(webhook_data)

        if parsed["status"] == "error" or parsed["is_ping"]:
            return None

        return parsed["payment_id"]

    @staticmethod
    def get_subscription_id_from_webhook(webhook_data: Dict[str, Any]) -> Optional[str]:
        """
        Convenience method to extract just the subscription ID.

        Returns None if no subscription ID found or if this is a ping event.
        """
        parsed = MollieWebhookParser.parse_webhook_data(webhook_data)

        if parsed["status"] == "error" or parsed["is_ping"]:
            return None

        return parsed["subscription_id"]

    @staticmethod
    def is_ping_event(webhook_data: Dict[str, Any]) -> bool:
        """
        Check if this is a ping event that should return success without processing.
        """
        return webhook_data.get("resource") == "event" and webhook_data.get("type") == "hook.ping"

    @staticmethod
    def create_ping_response() -> Dict[str, Any]:
        """Create appropriate response for ping events."""
        return {"status": "success", "message": "Webhook ping received", "event_type": "ping"}


def get_webhook_parser() -> MollieWebhookParser:
    """Factory function to get webhook parser instance."""
    return MollieWebhookParser()
