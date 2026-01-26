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
                if bank_key in acc["name"].lower():
                    debug_info.append(f"Found bank account via pattern ({bank_key}): {acc['name']}")
                    return acc["name"]

    return None


def convert_gl_account_to_bank_account(
    gl_account: str,
    company: str,
    debug_info: Optional[list] = None,
) -> Optional[str]:
    """
    Convert a GL Account (Account DocType) to a Bank Account (Bank Account DocType) name.

    Bank Transaction DocType requires a Bank Account name, not a GL Account.
    E-Boekhouden ledger mappings return GL Accounts like "1120 - ASN - 97.88.80.455 - NVV",
    but for Bank Transactions we need the Bank Account DocType name like "ASN Main Account".

    Args:
        gl_account: Could be either a Bank Account name or GL Account name
        company: Company for filtering Bank Account lookup
        debug_info: Optional list to append debug messages

    Returns:
        Bank Account name if found, None if no Bank Account exists for the GL Account

    Note:
        Use convert_gl_account_to_bank_account_or_raise() when a Bank Account is required
        and the caller cannot proceed without one.
    """
    if debug_info is None:
        debug_info = []

    if not gl_account:
        debug_info.append("No GL Account provided for conversion")
        return None

    # Check if it's already a Bank Account (not a GL Account)
    if frappe.db.exists("Bank Account", gl_account):
        debug_info.append(f"Using Bank Account directly: {gl_account}")
        return gl_account

    # It's a GL Account, convert to Bank Account
    debug_info.append(f"Converting GL Account to Bank Account: {gl_account}")

    # Look up Bank Account that uses this GL Account
    bank_account_name = frappe.db.get_value(
        "Bank Account", {"account": gl_account, "company": company}, "name"
    )

    if bank_account_name:
        debug_info.append(f"Resolved Bank Account: {bank_account_name} (GL Account: {gl_account})")
        return bank_account_name

    debug_info.append(f"No Bank Account found for GL Account '{gl_account}'")
    return None


def convert_gl_account_to_bank_account_or_raise(
    gl_account: str,
    company: str,
    debug_info: Optional[list] = None,
) -> str:
    """
    Convert GL Account to Bank Account, raising if not found.

    Same as convert_gl_account_to_bank_account() but raises ValidationError
    when no Bank Account can be found for the GL Account.

    Use this when a Bank Account is required and the operation cannot proceed
    without one (e.g., creating Bank Transactions).

    Args:
        gl_account: GL Account name to convert
        company: Company for filtering
        debug_info: Optional list to append debug messages

    Returns:
        Bank Account name (guaranteed non-None)

    Raises:
        frappe.ValidationError if no Bank Account found for the GL Account
    """
    if debug_info is None:
        debug_info = []

    bank_account = convert_gl_account_to_bank_account(gl_account, company, debug_info)

    if bank_account:
        return bank_account

    # Bank Account not found - provide helpful error
    available_accounts = frappe.get_all(
        "Bank Account",
        filters={"company": company, "is_company_account": 1},
        fields=["name", "account", "bank"],
        limit=10,
    )

    error_msg = (
        f"No Bank Account found for GL Account '{gl_account}' in company {company}.\n\n"
        f"Available Bank Accounts:\n"
    )

    for ba in available_accounts:
        error_msg += f"  - {ba.name} (GL Account: {ba.account}, Bank: {ba.bank})\n"

    if not available_accounts:
        error_msg += "  (No Bank Accounts configured for this company)\n"

    error_msg += (
        f"\nPlease create a Bank Account that links to GL Account '{gl_account}', "
        f"or update your E-Boekhouden Ledger Mapping to use an existing Bank Account."
    )

    debug_info.append(f"ERROR: {error_msg}")
    frappe.throw(error_msg, title="Bank Account Configuration Error")
