# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Utilities

Extraction and parsing utilities for Ponto webhook payloads.
These functions handle the JSON:API format used by Ponto/Ibanity.

Split from webhook.py as part of HIGH-4 (PSP Integration Consolidation Plan).
"""

from typing import Any, Dict, Optional


def extract_event_type(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the event type from webhook payload.

    Ponto uses JSON:API format, so the event type could be:
    - In `data.type` field
    - In `data.attributes.eventType` field
    - In a top-level `type` field

    Args:
        event_data: Parsed webhook payload

    Returns:
        Event type string or None if not found
    """
    # Try JSON:API data.type format
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # Check data.type
            if "type" in data:
                return data["type"]
            # Check data.attributes.eventType
            if "attributes" in data and "eventType" in data["attributes"]:
                return data["attributes"]["eventType"]

    # Try top-level type
    if "type" in event_data:
        return event_data["type"]

    # Try eventType directly
    if "eventType" in event_data:
        return event_data["eventType"]

    return None


def extract_account_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the account ID from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Account ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # Check relationships.account.data.id (JSON:API format)
            if "relationships" in data:
                account_rel = data["relationships"].get("account", {})
                if "data" in account_rel:
                    return account_rel["data"].get("id")

            # Check attributes.accountId
            if "attributes" in data:
                attrs = data["attributes"]
                if "accountId" in attrs:
                    return attrs["accountId"]

    return None


def extract_payment_request_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment request ID from webhook payload.

    For outgoing payment requests.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment request ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # The ID might be directly in the data
            if "id" in data:
                return data["id"]
            # Or in relationships
            if "relationships" in data:
                pr_rel = data["relationships"].get("paymentRequest", {})
                if "data" in pr_rel:
                    return pr_rel["data"].get("id")

    return None


def extract_payment_status(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment status from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment status string or None if not found
    """
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        return attrs.get("status")

    return None


def extract_payment_link_id(event_data: Dict[str, Any]) -> Optional[str]:
    """
    Extract the payment initiation request ID from webhook payload.

    For betaalverzoek (incoming payment requests).

    Args:
        event_data: Parsed webhook payload

    Returns:
        Payment initiation request ID string or None if not found
    """
    if "data" in event_data:
        data = event_data["data"]
        if isinstance(data, dict):
            # The ID might be directly in the data
            if "id" in data:
                return data["id"]
            # Or in relationships
            if "relationships" in data:
                pir_rel = data["relationships"].get("paymentInitiationRequest", {})
                if "data" in pir_rel:
                    return pir_rel["data"].get("id")

    return None


def extract_debtor_info(event_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract debtor information from webhook payload.

    Args:
        event_data: Parsed webhook payload

    Returns:
        Dict with debtor details (name, iban, bank)
    """
    debtor_info = {}
    if "data" in event_data and "attributes" in event_data["data"]:
        attrs = event_data["data"]["attributes"]
        if attrs.get("debtorName"):
            debtor_info["name"] = attrs["debtorName"]
        if attrs.get("debtorAccountReference"):
            debtor_info["iban"] = attrs["debtorAccountReference"]
        if attrs.get("debtorAgent"):
            debtor_info["bank"] = attrs["debtorAgent"]
    return debtor_info


__all__ = [
    "extract_event_type",
    "extract_account_id",
    "extract_payment_request_id",
    "extract_payment_status",
    "extract_payment_link_id",
    "extract_debtor_info",
]
