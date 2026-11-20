# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Bank Account Creator

Creates GL Accounts, Bank records, and Bank Accounts for Ponto bank accounts.
Follows the pattern from eBoekhouden CoA import.

Usage:
    from verenigingen.verenigingen_payments.ponto.utils.bank_account_creator import (
        create_ponto_bank_account,
    )

    result = create_ponto_bank_account(ponto_account, company)
    if result["success"]:
        bank_account_name = result["bank_account"]
"""

from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.verenigingen.doctype.member.mixins.payment_mixin import (  # one IBAN normaliser
    _normalise_iban,
)
from verenigingen.verenigingen_payments.ponto.exceptions import PontoIntegrationError

# Bank code mappings for Dutch banks
DUTCH_BANK_CODES = {
    "triodos": ("Triodos Bank", "TRIO", "TRIONL2U"),
    "ing": ("ING Bank", "INGB", "INGBNL2A"),
    "rabo": ("Rabobank", "RABO", "RABONL2U"),
    "abn": ("ABN AMRO", "ABNA", "ABNANL2A"),
    "bunq": ("bunq", "BUNQ", "BUNQNL2A"),
    "sns": ("SNS Bank", "SNSB", "SNSBNL2A"),
    "asn": ("ASN Bank", "ASNB", "ASNBNL21"),
    "knab": ("Knab", "KNAB", "KNABNL2H"),
    "regiobank": ("RegioBank", "RBRB", "RBRBNL21"),
}


def identify_bank_from_iban(iban: str) -> Dict[str, str]:
    """
    Identify bank name, code, and SWIFT from IBAN.

    Args:
        iban: IBAN string (e.g., NL91TRIO0123456789)

    Returns:
        Dict with bank_name, bank_code, swift_code
    """
    if not iban or len(iban) < 8:
        return {"bank_name": "Unknown Bank", "bank_code": None, "swift_code": None}

    # Dutch IBANs have bank code at positions 4-7 (e.g., NL91TRIO...)
    iban_bank_code = iban[4:8].upper()

    for key, (bank_name, code, swift) in DUTCH_BANK_CODES.items():
        if code == iban_bank_code:
            return {"bank_name": bank_name, "bank_code": code, "swift_code": swift}

    # Fallback - try to identify from code
    return {
        "bank_name": f"Bank ({iban_bank_code})",
        "bank_code": iban_bank_code,
        "swift_code": None,
    }


def get_or_create_bank(bank_info: Dict[str, str]) -> str:
    """
    Get existing Bank record or create new one.

    Args:
        bank_info: Dict with bank_name, swift_code

    Returns:
        Bank record name

    Raises:
        PontoIntegrationError: If bank creation fails
    """
    bank_name = bank_info.get("bank_name", "Unknown Bank")

    # Check if Bank already exists
    existing_bank = frappe.db.exists("Bank", {"bank_name": bank_name})

    if existing_bank:
        return existing_bank

    # Create new Bank record
    try:
        bank = frappe.new_doc("Bank")
        bank.bank_name = bank_name

        if bank_info.get("swift_code"):
            bank.swift_number = bank_info["swift_code"]

        result = secure_document_operation(
            operation="insert",
            doc=bank,
            justification=f"Create Bank record {bank_name} for Ponto integration",
            required_permissions=["Bank:create"],
        )

        if not result.success:
            error_msg = f"Failed to create Bank {bank_name}: {'; '.join(result.errors)}"
            frappe.log_error(title="Ponto Bank creation failed", message=error_msg)
            raise PontoIntegrationError(message=error_msg, details={"bank_name": bank_name})

        frappe.logger().info(f"Created Bank: {result.document.name}")
        return result.document.name

    except PontoIntegrationError:
        raise
    except Exception as e:
        frappe.logger().error(f"Error creating Bank {bank_name}: {e}")
        raise PontoIntegrationError(
            message=f"Error creating Bank {bank_name}",
            details={"bank_name": bank_name, "error": str(e)},
        )


def create_gl_account(
    account_name: str,
    parent_account: str,
    company: str,
    currency: str = "EUR",
) -> str:
    """
    Create a GL Account (Chart of Accounts entry) for a bank account.

    Args:
        account_name: Name for the GL account
        parent_account: Parent group account (e.g., "Bankrekeningen - VNN")
        company: Company name
        currency: Account currency

    Returns:
        Account name

    Raises:
        PontoIntegrationError: If GL account creation fails
    """
    # Reuse by name only when nothing else owns it: a GL account that already has a Bank
    # Account, or a different currency, belongs to another Ponto account (#2125).
    existing = frappe.db.get_value("Account", {"account_name": account_name, "company": company}, "name")
    if existing:
        existing_currency = frappe.db.get_value("Account", existing, "account_currency")
        if existing_currency != currency or frappe.db.exists("Bank Account", {"account": existing}):
            raise PontoIntegrationError(
                message=(
                    f"GL Account {existing} ({existing_currency}) already exists and cannot be reused "
                    f"for a {currency} Ponto account"
                ),
                details={"account_name": account_name},
            )
        return existing

    try:
        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.parent_account = parent_account
        account.company = company
        account.account_type = "Bank"
        account.account_currency = currency
        account.is_group = 0

        result = secure_document_operation(
            operation="insert",
            doc=account,
            justification=f"Create GL Account {account_name} for Ponto bank integration",
            required_permissions=["Account:create"],
        )

        if not result.success:
            error_msg = f"Failed to create GL Account {account_name}: {'; '.join(result.errors)}"
            frappe.log_error(title="Ponto GL Account creation failed", message=error_msg)
            raise PontoIntegrationError(message=error_msg, details={"account_name": account_name})

        frappe.logger().info(f"Created GL Account: {result.document.name}")
        return result.document.name

    except PontoIntegrationError:
        raise
    except Exception as e:
        frappe.logger().error(f"Error creating GL Account {account_name}: {e}")
        raise PontoIntegrationError(
            message=f"Error creating GL Account {account_name}",
            details={"account_name": account_name, "error": str(e)},
        )


def create_bank_account_record(
    gl_account: str,
    bank_name: str,
    iban: str,
    account_name: str,
    company: str,
    currency: str = "EUR",
) -> str:
    """
    Create a Bank Account record linked to GL Account.

    Args:
        gl_account: GL Account name (Chart of Accounts)
        bank_name: Bank record name
        iban: IBAN number
        account_name: Display name for the Bank Account
        company: Company name
        currency: Account currency

    Returns:
        Bank Account name

    Raises:
        PontoIntegrationError: If bank account creation fails
    """
    try:
        bank_account = frappe.new_doc("Bank Account")
        bank_account.account_name = account_name
        bank_account.account = gl_account
        bank_account.bank = bank_name
        bank_account.company = company
        bank_account.is_company_account = 1
        bank_account.is_default = 0
        if iban:
            bank_account.iban = iban
        bank_account.currency = currency

        result = secure_document_operation(
            operation="insert",
            doc=bank_account,
            justification=f"Create Bank Account {account_name} for Ponto integration",
            required_permissions=["Bank Account:create"],
        )

        if not result.success:
            error_msg = f"Failed to create Bank Account {account_name}: {'; '.join(result.errors)}"
            frappe.log_error(title="Ponto Bank Account creation failed", message=error_msg)
            raise PontoIntegrationError(message=error_msg, details={"iban": iban})

        frappe.logger().info(f"Created Bank Account: {result.document.name}")
        return result.document.name

    except PontoIntegrationError:
        raise
    except Exception as e:
        frappe.logger().error(f"Error creating Bank Account {account_name}: {e}")
        raise PontoIntegrationError(
            message=f"Error creating Bank Account {account_name}",
            details={"iban": iban, "error": str(e)},
        )


def create_ponto_bank_account(
    ponto_account,
    company: str,
    parent_account: str = None,
    record_iban: bool = True,
) -> Dict:
    """
    Create GL Account, Bank, and Bank Account for a Ponto account.

    Always creates: matching an existing Bank Account is the caller's job
    (``resolve_bank_account_for_ponto_account``). ``record_iban=False`` leaves the
    Bank Account's IBAN blank, for a Ponto IBAN that several accounts share.

    Args:
        ponto_account: PontoAccount dataclass with id, iban, holder_name, description, currency
        company: Company name
        parent_account: Parent GL Account group (optional, uses Verenigingen Settings if not provided)

    Returns:
        Dict with success, gl_account, bank, bank_account, or error
    """
    try:
        # Get parent account from settings if not provided
        if not parent_account:
            parent_account = get_parent_bank_account_group(company)

        if not parent_account:
            raise PontoIntegrationError(
                message="No parent bank account group configured in Verenigingen Settings",
                details={"company": company},
            )

        # Extract bank info from IBAN
        iban = ponto_account.iban or ""
        bank_info = identify_bank_from_iban(iban)

        # Generate account name from Ponto account info
        account_display_name = (
            ponto_account.description or ponto_account.holder_name or f"Ponto Account {iban[-4:]}"
        )
        # Currency from Ponto or default to EUR
        currency = getattr(ponto_account, "currency", "EUR") or "EUR"
        # Name unique per Ponto account: description and IBAN can both repeat (#2125).
        gl_account_name = (
            f"{bank_info['bank_name']} - {account_display_name} ({currency} {str(ponto_account.id)[:8]})"
        )

        # Step 1: Create Bank record (raises PontoIntegrationError on failure)
        bank_name = get_or_create_bank(bank_info)

        # Step 2: Create GL Account under parent group (raises PontoIntegrationError on failure)
        gl_account = create_gl_account(
            account_name=gl_account_name,
            parent_account=parent_account,
            company=company,
            currency=currency,
        )

        # Step 3: Create Bank Account linked to GL Account (raises PontoIntegrationError on failure)
        bank_account = create_bank_account_record(
            gl_account=gl_account,
            bank_name=bank_name,
            iban=iban if record_iban else "",
            account_name=gl_account_name,
            company=company,
            currency=currency,
        )

        return {
            "success": True,
            "gl_account": gl_account,
            "bank": bank_name,
            "bank_account": bank_account,
            "iban": iban,
        }

    except PontoIntegrationError as e:
        frappe.log_error(
            title="Ponto bank account creation failed",
            message=f"Error creating bank account for Ponto account: {e.message}",
        )
        return {"success": False, "error": e.message}
    except Exception as e:
        frappe.log_error(
            title="Ponto bank account creation failed",
            message=f"Unexpected error creating bank account for Ponto account: {e}",
        )
        return {"success": False, "error": str(e)}


def _gl_currency(bank_account: str) -> Optional[str]:
    gl = frappe.db.get_value("Bank Account", bank_account, "account")
    return frappe.db.get_value("Account", gl, "account_currency") if gl else None


def resolve_bank_account_for_ponto_account(
    ponto_account, company: str, shared_iban: bool, claimed: set
) -> Dict:
    """
    Find or create the ERPNext Bank Account for ONE Ponto account (#2125).

    No fallback matching. An existing Bank Account is adopted only when the Ponto
    account has a non-empty IBAN that no other Ponto account carries, exactly one Bank
    Account has that IBAN, it is unclaimed, in this company, and its GL currency equals
    the Ponto currency. Any other IBAN hit is a ``pause_reason``; no hit creates a new
    Bank Account + GL Account in the Ponto currency.

    Returns ``{"bank_account", "created"}`` or ``{"pause_reason"}``.
    """
    iban = _normalise_iban(ponto_account.iban)
    currency = ponto_account.currency or "EUR"
    if iban and not shared_iban:
        candidates = frappe.get_all("Bank Account", filters={"iban": iban}, pluck="name")
        if candidates:
            return _adopt_or_pause(candidates, iban, currency, company, claimed)
    result = create_ponto_bank_account(ponto_account, company, record_iban=bool(iban) and not shared_iban)
    if result.get("success"):
        return {"bank_account": result["bank_account"], "created": True}
    return {"pause_reason": f"Could not create a {currency} Bank Account: {result.get('error')}"}


def _adopt_or_pause(candidates, iban, currency, company, claimed) -> Dict:
    if len(candidates) > 1:
        return {
            "pause_reason": f"{len(candidates)} Bank Accounts carry IBAN {iban}; link the right one by hand"
        }
    name = candidates[0]
    if name in claimed:
        return {
            "pause_reason": f"Bank Account {name} (IBAN {iban}) is already linked to another Ponto account"
        }
    if frappe.db.get_value("Bank Account", name, "company") != company:
        return {"pause_reason": f"Bank Account {name} (IBAN {iban}) belongs to another company"}
    gl_currency = _gl_currency(name)
    if gl_currency != currency:
        return {
            "pause_reason": (
                f"Bank Account {name} (IBAN {iban}) has GL currency {gl_currency}, "
                f"but the Ponto account is {currency}"
            )
        }
    return {"bank_account": name, "created": False}


def mapping_pause_reason(bank_account: str, ponto_currency: str, links_to_it: int) -> Optional[str]:
    """Why a mapping's linked Bank Account cannot receive imports, or None if it can."""
    if links_to_it > 1:
        return (
            f"Bank Account {bank_account} is shared by {links_to_it} Ponto accounts. Clear the Bank "
            "Account field of the ones that do not belong to it and retrieve accounts again"
        )
    gl_currency = _gl_currency(bank_account)
    if gl_currency != ponto_currency:
        return (
            f"Bank Account {bank_account} has GL currency {gl_currency}, but the Ponto account is "
            f"{ponto_currency}. Clear the Bank Account field and retrieve accounts again"
        )
    return None


def get_parent_bank_account_group(company: str) -> Optional[str]:
    """
    Get the parent bank account group from Verenigingen Settings.

    Args:
        company: Company name

    Returns:
        Parent account name or None
    """
    try:
        # ponto_bank_account_parent lives on Verenigingen Payments Settings.
        from verenigingen.utils.settings_utils import get_payments_settings

        settings = get_payments_settings()
        parent_account = getattr(settings, "ponto_bank_account_parent", None)

        if parent_account:
            # Verify the account exists and belongs to the company
            if frappe.db.exists("Account", {"name": parent_account, "company": company}):
                return parent_account
            else:
                frappe.logger().warning(
                    f"Configured parent account {parent_account} not found for company {company}"
                )

        # Fallback: Try to find "Bankrekeningen" or similar
        fallback_names = [
            f"Bankrekeningen - {company}",
            "Bankrekeningen",
            f"Bank Accounts - {company}",
            "Bank Accounts",
        ]

        for name in fallback_names:
            if frappe.db.exists(
                "Account",
                {"account_name": name.split(" - ")[0], "company": company, "is_group": 1},
            ):
                account = frappe.db.get_value(
                    "Account",
                    {"account_name": name.split(" - ")[0], "company": company, "is_group": 1},
                    "name",
                )
                return account

        return None

    except Exception as e:
        frappe.logger().error(f"Error getting parent bank account group: {e}")
        return None
