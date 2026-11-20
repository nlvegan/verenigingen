"""
One creator for Bank and Bank Account records (#2126).

The Ponto integration and the e-Boekhouden CoA import used to carry their own copies,
with different contracts (raise vs return None / "Unknown Bank"). Both now delegate
here. Contract: every function RAISES ``BankAccountCreationError`` (a
``frappe.ValidationError``) and never returns a falsy stand-in. Callers that must keep
going translate or catch at their own boundary.

``Bank Account`` has no currency field. ERPNext enforces currency through the linked GL
Account's ``account_currency`` (``Bank Transaction.validate_currency``), so the explicit
``currency`` argument below is checked against that GL Account rather than stored.
"""

from typing import Optional

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


class BankAccountCreationError(frappe.ValidationError):
    """Bank or Bank Account could not be created. ``message`` is the reason."""

    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


def ensure_bank_record(
    bank_name: str,
    swift_number: Optional[str] = None,
    website: Optional[str] = None,
    source: str = "integration",
) -> str:
    """Return the Bank named ``bank_name``, creating it if absent. Raises on failure."""
    existing = frappe.db.exists("Bank", {"bank_name": bank_name})
    if existing:
        return existing

    bank = frappe.new_doc("Bank")
    bank.bank_name = bank_name
    if swift_number:
        bank.swift_number = swift_number
    if website:
        bank.website = website
    return _insert(
        bank,
        f"Bank {bank_name}",
        justification=f"Create Bank record {bank_name} for {source}",
        permission="Bank:create",
        title=f"{source} Bank creation failed",
        details={"bank_name": bank_name},
    )


def create_bank_account(
    gl_account: str,
    bank: str,
    account_name: str,
    company: str,
    currency: str,
    source: str = "integration",
    iban: Optional[str] = None,
    bank_account_no: Optional[str] = None,
    party_is_company: bool = False,
) -> str:
    """Create a Bank Account on ``gl_account``. Raises on failure.

    ``currency`` must equal the GL Account's ``account_currency`` (when it has one): a mismatch would make
    ERPNext refuse every Bank Transaction later, so it is refused here with both values.
    """
    gl_currency = frappe.db.get_value("Account", gl_account, "account_currency")
    if not frappe.db.exists("Account", gl_account):
        raise BankAccountCreationError(
            f"GL Account {gl_account} not found", {"gl_account": gl_account, "iban": iban}
        )
    if gl_currency and gl_currency != currency:  # a legacy GL row with no currency is not compared
        raise BankAccountCreationError(
            f"GL Account {gl_account} is in {gl_currency}, not {currency}; a Bank Account "
            f"takes the currency of its GL Account",
            {"gl_account": gl_account, "iban": iban},
        )

    bank_account = frappe.new_doc("Bank Account")
    bank_account.account_name = account_name
    bank_account.account = gl_account
    bank_account.bank = bank
    bank_account.company = company
    bank_account.is_company_account = 1
    bank_account.is_default = 0
    if iban:
        bank_account.iban = iban
    if bank_account_no:
        bank_account.bank_account_no = bank_account_no
    if party_is_company:
        # Non-IBAN accounts such as PayPal.
        bank_account.party_type = "Company"
        bank_account.party = company
    return _insert(
        bank_account,
        f"Bank Account {account_name}",
        justification=f"Create Bank Account {account_name} for {source}",
        permission="Bank Account:create",
        title=f"{source} Bank Account creation failed",
        details={"gl_account": gl_account, "iban": iban},
    )


def _insert(doc, label: str, justification: str, permission: str, title: str, details: dict) -> str:
    try:
        result = secure_document_operation(
            operation="insert",
            doc=doc,
            justification=justification,
            required_permissions=[permission],
        )
    except (*NON_RESUMABLE_DB_ERRORS, frappe.DuplicateEntryError):
        # Deadlock/timeout must reach whoever retries on the type (execute_with_deadlock_retry);
        # wrapping them in BankAccountCreationError hides them (#2976). A duplicate stays itself.
        raise
    except Exception as e:
        message = f"Error creating {label}: {e}"
        frappe.log_error(title=title, message=message)
        raise BankAccountCreationError(message, details) from e
    if not result.success:
        _fail(title, f"Failed to create {label}: {'; '.join(result.errors)}", details)
    return result.document.name


def _fail(title: str, message: str, details: dict):
    frappe.log_error(title=title, message=message)
    raise BankAccountCreationError(message, details)
