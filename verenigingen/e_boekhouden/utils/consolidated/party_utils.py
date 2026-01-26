"""
Consolidated party account utilities for E-Boekhouden integration.

This module provides canonical party account resolution with well-documented
fallback priorities. Used by migration, payment processing, and invoice handlers.
"""

from typing import Optional

import frappe


def get_party_account(
    party: str,
    party_type: str,
    company: str,
    debug_info: Optional[list] = None,
) -> Optional[str]:
    """
    Get the correct party account (Receivable/Payable) with well-documented fallbacks.

    IMPORTANT: This function explicitly avoids "Vraagposten" (question/suspense) accounts
    which are used in Dutch bookkeeping for unclassified items. These should never be
    used as default party accounts.

    Fallback Priority:
        1. Party-specific account from Party Account child table
        2. Company default receivable/payable account
        3. Account with "Default", "General", or "Algemeen" in name
        4. Any non-Vraagposten account of correct type
        5. Last resort: any account of correct type (with warning)

    Args:
        party: Party name (Customer or Supplier document name)
        party_type: Either "Customer" or "Supplier"
        company: Company name for account filtering
        debug_info: Optional list to append debug messages

    Returns:
        Account name if found, None if no suitable account exists

    Example:
        >>> account = get_party_account("CUST-001", "Customer", "NVV")
        >>> print(account)  # "1300 - Debiteuren - NVV"
    """
    if debug_info is None:
        debug_info = []

    # PRIORITY 1: Party-specific account from Party Account child table
    party_account = _get_party_specific_account(party, party_type, company)
    if party_account:
        debug_info.append(f"Found party-specific account for {party_type} {party}: {party_account}")
        return party_account

    # PRIORITY 2: Company default receivable/payable account
    account_type = "Receivable" if party_type == "Customer" else "Payable"
    company_default = _get_company_default_account(party_type, company)
    if company_default:
        debug_info.append(f"Using company default {account_type.lower()} account: {company_default}")
        return company_default

    # PRIORITY 3: Account with "Default", "General", or "Algemeen" in name
    generic_account = _get_generic_account(account_type, company)
    if generic_account:
        debug_info.append(f"Using generic {account_type.lower()} account: {generic_account}")
        return generic_account

    # PRIORITY 4: Any non-Vraagposten account of correct type
    safe_account = _get_safe_account(account_type, company)
    if safe_account:
        debug_info.append(f"Using safe {account_type.lower()} account (avoiding Vraagposten): {safe_account}")
        return safe_account

    # PRIORITY 5: Last resort - any account of correct type (with warning)
    fallback = frappe.db.get_value(
        "Account",
        {"account_type": account_type, "company": company, "is_group": 0},
        "name",
    )
    if fallback:
        frappe.logger().warning(
            f"Using fallback account {fallback} for {party_type} {party} - consider setting up proper defaults"
        )
        debug_info.append(f"WARNING: Using last-resort fallback account: {fallback}")

    return fallback


def _get_party_specific_account(party: str, party_type: str, company: str) -> Optional[str]:
    """Get account from Party Account child table."""
    result = frappe.db.sql(
        """
        SELECT pa.account
        FROM `tabParty Account` pa
        WHERE pa.parent = %s AND pa.parenttype = %s
        AND pa.company = %s
        LIMIT 1
        """,
        (party, party_type, company),
    )
    return result[0][0] if result else None


def _get_company_default_account(party_type: str, company: str) -> Optional[str]:
    """Get company default receivable/payable account."""
    if party_type == "Customer":
        return frappe.db.get_value("Company", company, "default_receivable_account")
    else:
        return frappe.db.get_value("Company", company, "default_payable_account")


def _get_generic_account(account_type: str, company: str) -> Optional[str]:
    """
    Get a generic account preferring ones with Default/General/Algemeen in name.

    Uses a CASE ordering to prefer:
    1. Accounts with "Default" or "General" in name
    2. Accounts with "Algemeen" (Dutch for general)
    3. Any account that is NOT Vraagposten or Specific
    4. Everything else (lowest priority)
    """
    result = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE account_type = %s
        AND company = %s
        AND is_group = 0
        ORDER BY
            CASE
                WHEN account_name LIKE '%%Default%%' OR account_name LIKE '%%General%%' THEN 1
                WHEN account_name LIKE '%%Algemeen%%' THEN 2
                WHEN account_name NOT LIKE '%%Vraagposten%%' AND account_name NOT LIKE '%%Specific%%' THEN 3
                ELSE 4
            END,
            account_name
        LIMIT 1
        """,
        (account_type, company),
        as_dict=True,
    )
    return result[0]["name"] if result else None


def _get_safe_account(account_type: str, company: str) -> Optional[str]:
    """
    Get any account of correct type while explicitly avoiding problematic accounts.

    Avoids:
    - Vraagposten (Dutch suspense/question accounts for unclassified items)
    - Specific (accounts meant for specific purposes, not general use)
    """
    result = frappe.db.sql(
        """
        SELECT name FROM `tabAccount`
        WHERE account_type = %s
        AND company = %s
        AND is_group = 0
        AND account_name NOT LIKE '%%Vraagposten%%'
        AND account_name NOT LIKE '%%Specific%%'
        ORDER BY account_name
        LIMIT 1
        """,
        (account_type, company),
        as_dict=True,
    )
    return result[0]["name"] if result else None
