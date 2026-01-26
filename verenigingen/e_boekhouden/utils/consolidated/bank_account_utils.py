"""
Consolidated bank account utilities for E-Boekhouden integration.

This module provides canonical bank account resolution from ledger IDs.
Used by PaymentEntryHandler and other payment processing components.
"""

from typing import Optional

import frappe

from .ledger_utils import get_ledger_mapping


def resolve_bank_account_for_ledger(
    ledger_id: str,
    company: str,
    payment_type: str = None,
    description: str = None,
    debug_info: Optional[list] = None,
    auto_create_mapping: bool = True,
) -> Optional[str]:
    """
    Resolve E-Boekhouden ledger_id to an ERPNext Bank/Cash GL account.

    Resolution strategy:
    1. Use ledger mapping with auto-create to get ERPNext account
    2. Verify it's a Bank or Cash account type
    3. Fall back to payment configuration if ledger code known
    4. Fall back to pattern matching on description

    Args:
        ledger_id: E-Boekhouden internal ledger ID
        company: Company name for account filtering
        payment_type: "Receive" or "Pay" for pattern matching hints
        description: Transaction description for pattern matching
        debug_info: Optional list to append debug messages
        auto_create_mapping: Whether to auto-create mapping from API

    Returns:
        ERPNext Account name (Bank/Cash type) or None

    Raises:
        frappe.ValidationError if ledger_id is None/empty
    """
    if debug_info is None:
        debug_info = []

    if not ledger_id:
        raise frappe.ValidationError(
            "No ledger ID provided. Cannot determine bank account without ledger mapping."
        )

    ledger_id_str = str(ledger_id)

    # Step 1: Use consolidated ledger mapping with optional auto-create
    ledger_code, erpnext_account = get_ledger_mapping(
        ledger_id_str,
        company=company,
        debug_info=debug_info,
        auto_create=auto_create_mapping,
    )

    # Step 2: If we have an ERPNext account, verify it's Bank/Cash type
    if erpnext_account:
        account_type = frappe.db.get_value("Account", erpnext_account, "account_type")
        if account_type in ["Bank", "Cash"]:
            debug_info.append(f"Ledger {ledger_id_str} -> Bank account: {erpnext_account}")
            return erpnext_account
        else:
            debug_info.append(f"Ledger {ledger_id_str} maps to {account_type} account, not Bank/Cash")

    # Step 3: Try payment configuration based on ledger code
    if ledger_code:
        account = _get_account_from_payment_config(ledger_code, company, debug_info)
        if account:
            return account

    # Step 4: Try pattern matching on description
    if description:
        account = _get_account_from_pattern(description, company, payment_type, debug_info)
        if account:
            return account

    debug_info.append(f"No Bank/Cash account found for ledger {ledger_id_str}")
    return None


def resolve_bank_account_or_raise(
    ledger_id: str,
    company: str,
    payment_type: str = None,
    description: str = None,
    debug_info: Optional[list] = None,
    auto_create_mapping: bool = True,
) -> str:
    """
    Same as resolve_bank_account_for_ledger but raises ValidationError if not found.

    Use this when a bank account is required and the import should fail
    if one cannot be determined.
    """
    if debug_info is None:
        debug_info = []

    account = resolve_bank_account_for_ledger(
        ledger_id=ledger_id,
        company=company,
        payment_type=payment_type,
        description=description,
        debug_info=debug_info,
        auto_create_mapping=auto_create_mapping,
    )

    if not account:
        ledger_code, _ = get_ledger_mapping(str(ledger_id), company, auto_create=False)
        raise frappe.ValidationError(
            f"No Bank/Cash account found for E-Boekhouden ledger {ledger_id} "
            f"(code: {ledger_code or 'unknown'}). "
            f"Please link the ledger mapping to a Bank or Cash account before importing."
        )

    return account


def _get_account_from_payment_config(
    ledger_code: str,
    company: str,
    debug_info: list,
) -> Optional[str]:
    """Look up bank account from payment configuration."""
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_migration_config import (
            get_payment_account_info,
        )

        account_info = get_payment_account_info(ledger_code, company)
        if account_info and account_info.get("erpnext_account"):
            account = account_info["erpnext_account"]
            debug_info.append(f"Found bank account via payment config: {account}")
            return account
    except ImportError:
        pass
    except Exception as e:
        debug_info.append(f"Payment config lookup failed: {str(e)}")

    return None


def _get_account_from_pattern(
    description: str,
    company: str,
    payment_type: str,
    debug_info: list,
) -> Optional[str]:
    """
    Extract bank account from description using pattern matching.

    Looks for known bank name patterns in the description.
    """
    if not description:
        return None

    description_lower = description.lower()

    # Common Dutch bank patterns
    bank_patterns = {
        "asn": ["asn", "a.s.n"],
        "ing": ["ing bank", "ingbank"],
        "rabo": ["rabobank", "rabo"],
        "abn": ["abn amro", "abnamro"],
        "triodos": ["triodos"],
    }

    for bank_key, patterns in bank_patterns.items():
        if any(pattern in description_lower for pattern in patterns):
            # Look for a bank account matching this pattern
            filters = {
                "account_type": "Bank",
                "company": company,
                "disabled": 0,
            }

            # Try to find account with bank name in it
            accounts = frappe.get_all(
                "Account",
                filters=filters,
                fields=["name"],
            )

            for acc in accounts:
                if bank_key in acc.name.lower():
                    debug_info.append(f"Found bank account via pattern ({bank_key}): {acc.name}")
                    return acc.name

    return None
