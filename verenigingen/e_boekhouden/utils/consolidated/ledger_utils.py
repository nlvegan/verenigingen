"""
Consolidated ledger utilities for E-Boekhouden integration.

This module provides canonical ledger resolution with optional auto-creation
of mappings. All ledger ID to code/account resolution should go through here.
"""

from typing import Optional, Tuple

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_ledger_mapping import (
    _find_erpnext_account_by_code,
    get_account_code_from_ledger_id,
)


def get_ledger_mapping(
    ledger_id: str,
    company: Optional[str] = None,
    debug_info: Optional[list] = None,
    auto_create: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve E-Boekhouden ledger_id to ledger_code and ERPNext account.

    This is the canonical function for ledger resolution. It:
    1. Looks up the ledger mapping table for ledger_code
    2. Tries to find/link an ERPNext account by matching account_number
    3. Optionally fetches from API and creates mapping if missing

    Args:
        ledger_id: E-Boekhouden internal ledger ID (e.g., "13201916")
        company: Optional company filter for account matching
        debug_info: Optional list to append debug messages
        auto_create: If True, fetch from API and create mapping when missing

    Returns:
        Tuple of (ledger_code, erpnext_account_name) - either can be None

    Example:
        >>> code, account = get_ledger_mapping("13201916", "NVV", debug_info=[])
        >>> print(code)  # "42902"
        >>> print(account)  # "42902 - Inkomstenrekening - NVV"
    """
    if debug_info is None:
        debug_info = []

    if not ledger_id:
        return (None, None)

    ledger_id_str = str(ledger_id)

    # Step 1: Check mapping table for ledger_code
    mapping = frappe.db.get_value(
        "E-Boekhouden Ledger Mapping",
        {"ledger_id": ledger_id_str},
        ["ledger_code", "erpnext_account"],
        as_dict=True,
    )

    if mapping:
        ledger_code = mapping.get("ledger_code")
        erpnext_account = mapping.get("erpnext_account")

        if ledger_code:
            debug_info.append(f"Ledger mapping found: {ledger_id_str} -> code={ledger_code}")

            # If erpnext_account already set, we're done
            if erpnext_account:
                debug_info.append(f"ERPNext account linked: {erpnext_account}")
                return (ledger_code, erpnext_account)

            # Try to auto-link by matching account_number
            erpnext_account = _find_erpnext_account_by_code(ledger_code, company)
            if erpnext_account:
                # Update mapping record to persist the auto-link
                _update_mapping_erpnext_account(ledger_id_str, erpnext_account, debug_info)
                return (ledger_code, erpnext_account)

            return (ledger_code, None)

    # Step 2: No mapping found - optionally create one via API
    if auto_create:
        ledger_code, erpnext_account = _fetch_and_create_single_mapping(ledger_id_str, company, debug_info)
        if ledger_code:
            return (ledger_code, erpnext_account)

    debug_info.append(f"No mapping found for ledger_id {ledger_id_str}")
    return (None, None)


def resolve_ledger_code(
    ledger_id: str,
    company: Optional[str] = None,
    debug_info: Optional[list] = None,
    auto_create: bool = False,
) -> Optional[str]:
    """
    Resolve E-Boekhouden ledger_id to ledger_code only.

    Convenience wrapper around get_ledger_mapping() that returns just the code.

    Args:
        ledger_id: E-Boekhouden internal ledger ID
        company: Optional company filter
        debug_info: Optional list to append debug messages
        auto_create: If True, fetch from API and create mapping when missing

    Returns:
        ledger_code if found, otherwise the original ledger_id as fallback
    """
    if not ledger_id:
        return None

    ledger_code, _ = get_ledger_mapping(ledger_id, company, debug_info, auto_create)
    return ledger_code or str(ledger_id)


def _update_mapping_erpnext_account(ledger_id: str, erpnext_account: str, debug_info: list) -> None:
    """Update the mapping record with the auto-linked ERPNext account."""
    try:
        docname = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id})
        if docname:
            frappe.db.set_value(
                "E-Boekhouden Ledger Mapping",
                docname,
                "erpnext_account",
                erpnext_account,
                update_modified=False,
            )
            debug_info.append(f"Auto-linked ledger {ledger_id} to account {erpnext_account}")
    except Exception as e:
        # Non-critical - mapping can be reconciled by admin
        debug_info.append(f"Failed to persist auto-link for {ledger_id}: {str(e)}")


def _fetch_and_create_single_mapping(
    ledger_id: str,
    company: Optional[str],
    debug_info: list,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch a single ledger from E-Boekhouden API and create mapping.

    This is idempotent - concurrent calls will handle duplicate creation gracefully.
    """
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator import EBoekhoudenRESTIterator

        iterator = EBoekhoudenRESTIterator()
        token = iterator._get_session_token()
        if not token:
            debug_info.append("Could not obtain session token for ledger fetch")
            return (None, None)

        import requests

        base_url = iterator.base_url
        url = f"{base_url}/v1/ledger/{ledger_id}"
        resp = requests.get(
            url,
            headers={"Authorization": token, "Accept": "application/json"},
            timeout=15,
        )

        if resp.status_code != 200:
            debug_info.append(f"API returned {resp.status_code} for ledger {ledger_id}")
            return (None, None)

        ledger_data = resp.json()
        ledger_code = ledger_data.get("code")
        ledger_name = ledger_data.get("description", "")

        if not ledger_code:
            debug_info.append(f"API returned no code for ledger {ledger_id}")
            return (None, None)

        # Check if mapping already exists (race condition protection)
        existing = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id})
        if existing:
            debug_info.append(f"Mapping for {ledger_id} already exists (concurrent creation)")
            return get_ledger_mapping(ledger_id, company, debug_info, auto_create=False)

        # Create mapping record
        erpnext_account = _find_erpnext_account_by_code(ledger_code, company)

        try:
            doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
            doc.ledger_id = ledger_id
            doc.ledger_code = ledger_code
            doc.ledger_name = ledger_name
            if erpnext_account:
                doc.erpnext_account = erpnext_account
            doc.insert(ignore_permissions=True)
            debug_info.append(f"Created ledger mapping: {ledger_id} -> {ledger_code}")
        except frappe.DuplicateEntryError:
            # Concurrent creation - fetch the existing mapping
            debug_info.append(f"Concurrent ledger mapping creation for {ledger_id}")
            return get_ledger_mapping(ledger_id, company, debug_info, auto_create=False)

        return (ledger_code, erpnext_account)

    except Exception as e:
        debug_info.append(f"Failed to fetch/create mapping for ledger {ledger_id}: {str(e)}")
        return (None, None)
