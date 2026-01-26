"""
Consolidated invoice line utilities for E-Boekhouden integration.

This module provides invoice line creation from tegenrekening (contra-account) codes.
Used by PaymentProcessor for fallback account resolution when ledger mapping is incomplete.

NOTE: The underlying SmartTegenrekeningMapper is deprecated. Future refactoring should
consider using eboekhouden_improved_item_naming.get_or_create_item_improved() directly.
However, the current function signature is retained for backward compatibility.
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
        ERPNext account name if found, None otherwise

    Raises:
        frappe.ValidationError if mapping fails and no account can be determined
    """
    if debug_info is None:
        debug_info = []

    if not tegenrekening_code:
        debug_info.append("No tegenrekening code provided")
        return None

    try:
        # Import from the existing (deprecated but functional) mapper
        from verenigingen.utils.smart_tegenrekening_mapper import (
            create_invoice_line_for_tegenrekening as _create_line,
        )

        line_dict = _create_line(
            tegenrekening_code=tegenrekening_code,
            amount=amount,
            description=description,
            transaction_type=transaction_type,
        )

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


def create_invoice_line_for_tegenrekening(
    tegenrekening_code: str,
    amount: float,
    description: str = "",
    transaction_type: str = "purchase",
    debug_info: Optional[list] = None,
) -> dict:
    """
    Create a complete invoice line dict for a tegenrekening code.

    This is a direct wrapper around the smart_tegenrekening_mapper function,
    provided for backward compatibility and consolidated imports.

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

    # Import from the existing mapper
    from verenigingen.utils.smart_tegenrekening_mapper import (
        create_invoice_line_for_tegenrekening as _create_line,
    )

    debug_info.append(f"Creating invoice line for tegenrekening {tegenrekening_code} ({transaction_type})")

    return _create_line(
        tegenrekening_code=tegenrekening_code,
        amount=amount,
        description=description,
        transaction_type=transaction_type,
    )
