"""
Consolidated invoice line utilities for E-Boekhouden integration.

This module provides invoice line creation from tegenrekening (contra-account) codes.
Used by PaymentProcessor for fallback account resolution when ledger mapping is incomplete.

Uses eboekhouden_improved_item_naming.get_or_create_item_improved() for item resolution,
which provides comprehensive business logic for bank costs, events, COGS detection, etc.
"""

from typing import Optional

import frappe


def get_account_for_tegenrekening(
    tegenrekening_code: str,
    transaction_type: str,
    amount: float = 0,
    description: str = "",
    debug_info: Optional[list] = None,
) -> Optional[str]:
    """
    Get the appropriate ERPNext account for an E-Boekhouden tegenrekening code.

    This is a simplified interface that returns just the account, which is what
    payment processing typically needs (not the full invoice line dict).

    Args:
        tegenrekening_code: E-Boekhouden account code (e.g., "80001", "42200")
        transaction_type: "sales" for income accounts, "purchase" for expense accounts
        amount: Transaction amount (for item creation context)
        description: Transaction description (for fallback mapping)
        debug_info: Optional list to append debug messages

    Returns:
        ERPNext account name if found, None if:
        - tegenrekening_code is empty/None
        - No account mapping exists for this code
        - Item creation fails and no account can be determined

    Note:
        This function returns None for missing mappings rather than raising.
        Use get_account_for_tegenrekening_or_raise() if you need strict behavior.
        Exceptions from underlying infrastructure (database errors, etc.) are re-raised.
    """
    if debug_info is None:
        debug_info = []

    if not tegenrekening_code:
        debug_info.append("No tegenrekening code provided")
        return None

    try:
        line_dict = _create_invoice_line_impl(
            tegenrekening_code=tegenrekening_code,
            amount=amount,
            description=description,
            transaction_type=transaction_type,
            debug_info=debug_info,
        )

        if not line_dict:
            debug_info.append(f"No mapping found for tegenrekening {tegenrekening_code}")
            return None

        # Extract the relevant account based on transaction type
        if transaction_type == "sales":
            account = line_dict.get("income_account")
            debug_info.append(f"Tegenrekening {tegenrekening_code} -> income account: {account}")
        else:
            account = line_dict.get("expense_account")
            debug_info.append(f"Tegenrekening {tegenrekening_code} -> expense account: {account}")

        return account

    except Exception as e:
        debug_info.append(f"Failed to get account for tegenrekening {tegenrekening_code}: {str(e)}")
        raise


def get_account_for_tegenrekening_or_raise(
    tegenrekening_code: str,
    transaction_type: str,
    amount: float = 0,
    description: str = "",
    debug_info: Optional[list] = None,
) -> str:
    """
    Get ERPNext account for tegenrekening code, raising if not found.

    Same as get_account_for_tegenrekening() but raises ValidationError
    when no account can be determined.

    Args:
        tegenrekening_code: E-Boekhouden account code
        transaction_type: "sales" or "purchase"
        amount: Transaction amount
        description: Transaction description
        debug_info: Optional list to append debug messages

    Returns:
        ERPNext account name (guaranteed non-None)

    Raises:
        frappe.ValidationError if no account can be determined
    """
    if debug_info is None:
        debug_info = []

    account = get_account_for_tegenrekening(
        tegenrekening_code=tegenrekening_code,
        transaction_type=transaction_type,
        amount=amount,
        description=description,
        debug_info=debug_info,
    )

    if not account:
        account_type = "income" if transaction_type == "sales" else "expense"
        raise frappe.ValidationError(
            f"No {account_type} account found for E-Boekhouden tegenrekening '{tegenrekening_code}'. "
            f"Please configure the account mapping before importing transactions."
        )

    return account


def create_invoice_line_for_tegenrekening(
    tegenrekening_code: str,
    amount: float,
    description: str = "",
    transaction_type: str = "purchase",
    debug_info: Optional[list] = None,
) -> dict:
    """
    Create a complete invoice line dict for a tegenrekening code.

    Uses eboekhouden_improved_item_naming for intelligent item resolution including:
    - Bank cost detection and special handling
    - Event ticket items for WooCommerce
    - COGS vs Expense classification
    - Intelligent item naming from account names

    Args:
        tegenrekening_code: E-Boekhouden account code
        amount: Transaction amount
        description: Line item description
        transaction_type: "sales" or "purchase"
        debug_info: Optional list to append debug messages

    Returns:
        dict with keys: item_code, item_name, description, qty, rate, amount,
        cost_center, and either income_account or expense_account

    Raises:
        frappe.ValidationError if mapping fails
    """
    if debug_info is None:
        debug_info = []

    debug_info.append(f"Creating invoice line for tegenrekening {tegenrekening_code} ({transaction_type})")

    line_dict = _create_invoice_line_impl(
        tegenrekening_code=tegenrekening_code,
        amount=amount,
        description=description,
        transaction_type=transaction_type,
        debug_info=debug_info,
    )

    if not line_dict:
        raise frappe.ValidationError(
            f"Failed to create invoice line for tegenrekening '{tegenrekening_code}'. "
            f"Please configure the account and item mapping before importing transactions."
        )

    return line_dict


def _create_invoice_line_impl(
    tegenrekening_code: str,
    amount: float,
    description: str,
    transaction_type: str,
    debug_info: list,
) -> Optional[dict]:
    """
    Internal implementation for creating invoice line dict.

    Uses eboekhouden_improved_item_naming.get_or_create_item_improved() for item
    resolution, then builds the complete invoice line dict with account mapping.

    Returns:
        Invoice line dict or None if mapping fails
    """
    from verenigingen.e_boekhouden.utils.eboekhouden_improved_item_naming import (
        get_or_create_item_improved,
    )

    # Get company from settings - required configuration, no fallback
    company = frappe.db.get_single_value("E-Boekhouden Settings", "company")
    if not company:
        raise frappe.ValidationError(
            "E-Boekhouden Settings.company is not configured. "
            "Please set the company in E-Boekhouden Settings before importing transactions."
        )

    # Map transaction_type to the format expected by get_or_create_item_improved
    item_transaction_type = "Sales" if transaction_type == "sales" else "Purchase"

    try:
        # Get or create item using improved naming logic
        item_code = get_or_create_item_improved(
            account_code=tegenrekening_code,
            company=company,
            transaction_type=item_transaction_type,
            description=description,
            price=abs(amount) if amount else None,
        )

        if not item_code:
            debug_info.append(f"get_or_create_item_improved returned None for {tegenrekening_code}")
            return None

        # Get item details
        item_doc = frappe.get_cached_doc("Item", item_code)
        item_name = item_doc.item_name or item_code

        # Get cost center
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        # Get account from Item Defaults or ledger mapping
        account = _resolve_account_for_item(
            item_code, company, tegenrekening_code, transaction_type, debug_info
        )

        # Build the invoice line dict
        line_dict = {
            "item_code": item_code,
            "item_name": item_name,
            "description": description or item_name,
            "qty": 1,
            "rate": abs(float(amount)) if amount else 0,
            "amount": abs(float(amount)) if amount else 0,
            "cost_center": cost_center,
        }

        # Add appropriate account field
        if account:
            if transaction_type == "sales":
                line_dict["income_account"] = account
            else:
                line_dict["expense_account"] = account

        debug_info.append(f"Created invoice line: item={item_code}, account={account}")
        return line_dict

    except Exception as e:
        debug_info.append(f"Error in _create_invoice_line_impl: {str(e)}")
        raise


def _resolve_account_for_item(
    item_code: str,
    company: str,
    tegenrekening_code: str,
    transaction_type: str,
    debug_info: list,
) -> Optional[str]:
    """
    Resolve the ERPNext account for an item.

    Resolution order:
    1. Item Defaults for the company
    2. E-Boekhouden Ledger Mapping by account code
    3. Account by account_number field
    """
    account = None

    # Try Item Defaults first
    if transaction_type == "sales":
        account = frappe.db.get_value(
            "Item Default", {"parent": item_code, "company": company}, "income_account"
        )
    else:
        account = frappe.db.get_value(
            "Item Default", {"parent": item_code, "company": company}, "expense_account"
        )

    if account:
        debug_info.append(f"Account from Item Default: {account}")
        return account

    # Try E-Boekhouden Ledger Mapping
    # First check if tegenrekening_code is a ledger_id (long numeric)
    if str(tegenrekening_code).isdigit() and len(str(tegenrekening_code)) > 5:
        # It's a ledger ID
        account = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": str(tegenrekening_code)}, "erpnext_account"
        )
        if account:
            debug_info.append(f"Account from Ledger Mapping (ledger_id): {account}")
            return account
    else:
        # It's an account code - try by ledger_code
        account = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_code": str(tegenrekening_code)}, "erpnext_account"
        )
        if account:
            debug_info.append(f"Account from Ledger Mapping (ledger_code): {account}")
            return account

    # Try by account_number
    account = frappe.db.get_value(
        "Account", {"account_number": str(tegenrekening_code), "company": company}, "name"
    )
    if account:
        debug_info.append(f"Account from account_number: {account}")
        return account

    # Try by eboekhouden_grootboek_nummer
    account = frappe.db.get_value(
        "Account", {"eboekhouden_grootboek_nummer": str(tegenrekening_code), "company": company}, "name"
    )
    if account:
        debug_info.append(f"Account from eboekhouden_grootboek_nummer: {account}")
        return account

    debug_info.append(f"No account found for tegenrekening {tegenrekening_code}")
    return None
