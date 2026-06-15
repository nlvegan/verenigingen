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
    # Check if account already exists
    existing = frappe.db.exists(
        "Account",
        {"account_name": account_name, "company": company},
    )
    if existing:
        frappe.logger().info(f"GL Account already exists: {existing}")
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
    # Check if Bank Account already exists by IBAN
    existing = frappe.db.exists("Bank Account", {"iban": iban})
    if existing:
        frappe.logger().info(f"Bank Account already exists for IBAN {iban}: {existing}")
        return existing

    try:
        bank_account = frappe.new_doc("Bank Account")
        bank_account.account_name = account_name
        bank_account.account = gl_account
        bank_account.bank = bank_name
        bank_account.company = company
        bank_account.is_company_account = 1
        bank_account.is_default = 0
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
) -> Dict:
    """
    Create GL Account, Bank, and Bank Account for a Ponto account.

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
        iban = ponto_account.iban
        bank_info = identify_bank_from_iban(iban)

        # Generate account name from Ponto account info
        account_display_name = (
            ponto_account.description or ponto_account.holder_name or f"Ponto Account {iban[-4:]}"
        )
        gl_account_name = f"{bank_info['bank_name']} - {account_display_name}"

        # Currency from Ponto or default to EUR
        currency = getattr(ponto_account, "currency", "EUR") or "EUR"

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
            iban=iban,
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
