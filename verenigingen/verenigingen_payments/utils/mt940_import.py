import base64
import hashlib
import os
import re
import tempfile
import traceback

import frappe
from frappe.utils import getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)
from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

# =============================================================================
# Constants
# =============================================================================

# Pattern for Dutch payment prefix in remittance info (Mollie/bank generated)
# Matches: "Betaling van [Name] [Dutch IBAN] [actual message]"
DUTCH_PAYMENT_PREFIX_PATTERN = r"^Betaling van\s+.+?\s+(NL\d{2}[A-Z]{4}\d{10})\s+"

# Default description for transactions without meaningful description
DEFAULT_TRANSACTION_DESCRIPTION = "MT940 Transaction"

# ING internal account reference pattern (e.g., 'L96981341' for linked savings accounts)
ING_INTERNAL_ACCOUNT_PATTERN = r"^L\d{6,10}$"

# Transaction ID hash length (128 bits for collision resistance)
TRANSACTION_HASH_LENGTH = 32

# Format-only "looks like an IBAN" shape check (2 letters + 2 digits + alnum).
# Used to decide whether a counterparty account string is stored as an IBAN or as
# a plain account reference (e.g. ING internal 'L96981341'). This is intentionally
# a SHAPE check, NOT a mod-97 validation: a typo'd-but-realistic IBAN must still be
# kept in the IBAN field so downstream party-matching can use it. See task R3 report
# for why this is not delegated to validate_iban() (mod-97 would flip such inputs).
IBAN_SHAPE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")

# =============================================================================
# Dutch Banking Transaction Type Mapping (ING, Triodos, ABN AMRO, Rabobank)
# TRCD codes from ING MT940 format
DUTCH_BOOKING_CODES = {
    "005": "Transfer/Wire",
    "020": "Check Payment",
    "051": "Periodic Transfer",
    "115": "POS Payment",
    "152": "ATM Withdrawal",
    "186": "Direct Debit",
    "199": "Cash Deposit",
    "202": "Bank Transfer",
    "544": "SEPA Credit Transfer",
    "694": "SEPA Direct Debit",
    "805": "Bank Costs",
    "806": "Bank Charges",
    "901": "Cash Withdrawal",
    "904": "Interest Credit",
    "905": "Interest Debit",
    # ING-specific TRCD codes
    "00100": "Inkomende overboeking",  # Incoming transfer
    "00112": "Uitgaande overboeking",  # Outgoing transfer
    "00370": "Interne overboeking",  # Internal transfer (e.g., savings)
    "09001": "Bankkosten",  # Bank charges
}

# SEPA Transaction Types for enhanced classification
SEPA_TRANSACTION_TYPES = {
    "SALA": "Salary Payment",
    "PENS": "Pension Payment",
    "DIVD": "Dividend Payment",
    "GOVT": "Government Payment",
    "TRAD": "Trade Payment",
    "LOAN": "Loan Payment",
    "RENT": "Rent Payment",
    "UTIL": "Utility Payment",
    "TELE": "Telephone Payment",
    "INSUR": "Insurance Payment",
    "TAXES": "Tax Payment",
    "CHAR": "Charity Payment",
    "SECU": "Securities Purchase/Sale",
}


def is_internal_account_reference(account_ref: str) -> bool:
    """
    Check if an account reference is an ING internal linked account reference.

    ING uses internal references like 'L96981341' for linked accounts (e.g., savings accounts
    connected to a business checking account). These are NOT IBANs and indicate internal transfers
    between the organization's own accounts.

    Pattern: L + 8 digits (ING internal account format)

    Args:
        account_ref: Account reference string (could be IBAN or internal ref)

    Returns:
        True if this looks like an internal ING account reference
    """
    if not account_ref:
        return False

    # ING internal account references: L followed by digits (typically 8)
    return bool(re.match(ING_INTERNAL_ACCOUNT_PATTERN, account_ref))


def find_own_bank_account_by_reference(account_ref: str, counterparty_name: str, company: str) -> dict:
    """
    Find own Bank Account by internal reference or name.

    For internal transfers (e.g., savings account), the counterparty is our own account.
    This function identifies these cases to avoid creating Customer/Supplier records
    for our own accounts.

    Args:
        account_ref: Internal account reference (e.g., 'L96981341')
        counterparty_name: Counterparty name from bank statement
        company: Company name to match against

    Returns:
        dict with:
        - is_own_account: True if matched to own Bank Account
        - bank_account: Bank Account name if found
        - bank_account_iban: IBAN of the matched account if available
    """
    result = {"is_own_account": False, "bank_account": None, "bank_account_iban": None}

    if not account_ref and not counterparty_name:
        return result

    # Priority 1: Match by internal account reference in bank_account_no field
    if account_ref:
        matched_account = frappe.db.sql(
            """
            SELECT name, iban, is_company_account, company
            FROM `tabBank Account`
            WHERE bank_account_no = %s
            AND (is_company_account = 1 OR company = %s)
            LIMIT 1
            """,
            (account_ref, company),
            as_dict=True,
        )

        if matched_account:
            result["is_own_account"] = True
            result["bank_account"] = matched_account[0]["name"]
            result["bank_account_iban"] = matched_account[0].get("iban", "")
            frappe.logger().info(
                f"MT940: Matched internal reference {account_ref} to own Bank Account "
                f"{result['bank_account']}"
            )
            return result

    # Priority 2: Match by counterparty name (for savings accounts with descriptive names)
    if counterparty_name:
        # Look for Bank Account with matching account_name (case-insensitive)
        matched_account = frappe.db.sql(
            """
            SELECT name, iban, is_company_account, company, account_name
            FROM `tabBank Account`
            WHERE LOWER(account_name) LIKE LOWER(%s)
            AND (is_company_account = 1 OR company = %s)
            LIMIT 1
            """,
            (f"%{counterparty_name}%", company),
            as_dict=True,
        )

        if matched_account:
            result["is_own_account"] = True
            result["bank_account"] = matched_account[0]["name"]
            result["bank_account_iban"] = matched_account[0].get("iban", "")
            frappe.logger().info(
                f"MT940: Matched counterparty name '{counterparty_name}' to own Bank Account "
                f"{result['bank_account']}"
            )
            return result

    return result


def batch_preload_party_lookups(ibans: list) -> dict:
    """
    Batch preload party lookup data for a list of IBANs.

    This eliminates N+1 query patterns when processing multiple MT940 transactions.
    Instead of 3-4 queries per transaction, we do 3 queries total for all transactions.

    Args:
        ibans: List of counterparty IBANs to look up

    Returns:
        dict with preloaded lookups:
        - member_by_iban: {iban: {member_name, customer}}
        - mandate_by_iban: {iban: {member, customer}}
        - bank_account_by_iban: {iban: {party_type, party}}
    """
    if not ibans:
        return {"member_by_iban": {}, "mandate_by_iban": {}, "bank_account_by_iban": {}}

    # Filter out empty IBANs
    valid_ibans = [i for i in ibans if i]
    if not valid_ibans:
        return {"member_by_iban": {}, "mandate_by_iban": {}, "bank_account_by_iban": {}}

    # Batch load Member -> Customer mappings by IBAN
    member_results = frappe.db.sql(
        """
        SELECT m.iban, m.name as member_name, m.customer
        FROM `tabMember` m
        WHERE m.iban IN %(ibans)s
        AND m.customer IS NOT NULL
        AND m.customer != ''
        """,
        {"ibans": valid_ibans},
        as_dict=True,
    )
    member_by_iban = {r["iban"]: r for r in member_results}

    # Batch load SEPA Mandate -> Member -> Customer mappings by IBAN
    try:
        mandate_results = frappe.db.sql(
            """
            SELECT sm.iban, sm.member, m.customer
            FROM `tabSEPA Mandate` sm
            JOIN `tabMember` m ON sm.member = m.name
            WHERE sm.iban IN %(ibans)s
            AND m.customer IS NOT NULL
            AND m.customer != ''
            """,
            {"ibans": valid_ibans},
            as_dict=True,
        )
        mandate_by_iban = {r["iban"]: r for r in mandate_results}
    except Exception:
        # SEPA Mandate table might not exist
        mandate_by_iban = {}

    # Batch load Bank Account -> Party mappings by IBAN
    bank_account_results = frappe.db.sql(
        """
        SELECT iban, bank_account_no, party, party_type
        FROM `tabBank Account`
        WHERE (bank_account_no IN %(ibans)s OR iban IN %(ibans)s)
        AND party IS NOT NULL
        AND party != ''
        """,
        {"ibans": valid_ibans},
        as_dict=True,
    )
    bank_account_by_iban = {r["iban"]: r for r in bank_account_results if r.get("iban")}
    # Also index by bank_account_no for those stored there
    for r in bank_account_results:
        if r.get("bank_account_no") and r["bank_account_no"] not in bank_account_by_iban:
            bank_account_by_iban[r["bank_account_no"]] = r

    return {
        "member_by_iban": member_by_iban,
        "mandate_by_iban": mandate_by_iban,
        "bank_account_by_iban": bank_account_by_iban,
    }


def find_party_by_iban_or_name(
    iban: str,
    counterparty_name: str,
    is_incoming: bool,
    internal_account_ref: str = None,
    company: str = None,
    preloaded_lookups: dict = None,
) -> dict:
    """
    Find party (Customer/Supplier) by IBAN or name for MT940 bank transactions.

    Priority order:
    0. Internal transfer detection (own savings accounts, etc.)
    1. Member by IBAN -> get linked Customer (+ create Bank Account link)
    2. SEPA Mandate by IBAN -> get linked Member -> Customer
    3. Customer/Supplier by Bank Account IBAN
    4. Customer/Supplier by name (using BankTransactionParser)
       - If matched by name and IBAN provided, creates Bank Account link for future matching

    Args:
        iban: Counterparty IBAN from bank statement
        counterparty_name: Counterparty name from bank statement
        is_incoming: True for deposits (Customer), False for withdrawals (Supplier)
        internal_account_ref: Non-IBAN account reference (e.g., ING internal ref 'L96981341')
        company: Company name for internal account matching
        preloaded_lookups: Optional dict from batch_preload_party_lookups() to avoid N+1 queries

    Returns:
        dict with:
        - party_type and party (both may be None if no match or internal transfer)
        - is_internal_transfer: True if this is a transfer to/from own account
        - internal_bank_account: Bank Account name if internal transfer
    """
    result = {"party_type": None, "party": None, "is_internal_transfer": False, "internal_bank_account": None}

    # Determine expected party type based on transaction direction
    # Incoming payments (deposits) are typically from Customers
    # Outgoing payments (withdrawals) are typically to Suppliers
    party_type = "Customer" if is_incoming else "Supplier"

    # Priority 0: Check for internal transfers (own accounts like savings)
    # ING uses internal references like 'L96981341' for linked accounts
    if internal_account_ref and company:
        if is_internal_account_reference(internal_account_ref):
            own_account = find_own_bank_account_by_reference(internal_account_ref, counterparty_name, company)
            if own_account["is_own_account"]:
                result["is_internal_transfer"] = True
                result["internal_bank_account"] = own_account["bank_account"]
                frappe.logger().info(
                    f"MT940: Detected internal transfer to/from {own_account['bank_account']} "
                    f"(internal ref: {internal_account_ref})"
                )
                return result

    # Also check by counterparty name alone if it matches a company Bank Account
    # (Some internal transfers may not have a special reference pattern)
    if counterparty_name and company and not iban:
        own_account = find_own_bank_account_by_reference(None, counterparty_name, company)
        if own_account["is_own_account"]:
            result["is_internal_transfer"] = True
            result["internal_bank_account"] = own_account["bank_account"]
            frappe.logger().info(
                f"MT940: Detected internal transfer to/from {own_account['bank_account']} "
                f"(matched by name: '{counterparty_name}')"
            )
            return result

    # Priority 1: Look up Member by IBAN (for association payments)
    if iban:
        # Use preloaded data if available (batch mode), otherwise query
        member_data = None
        if preloaded_lookups and "member_by_iban" in preloaded_lookups:
            member_data = preloaded_lookups["member_by_iban"].get(iban)
        else:
            member_customer = frappe.db.sql(
                """
                SELECT m.name as member_name, m.customer
                FROM `tabMember` m
                WHERE m.iban = %s
                AND m.customer IS NOT NULL
                AND m.customer != ''
                LIMIT 1
                """,
                (iban,),
                as_dict=True,
            )
            if member_customer:
                member_data = member_customer[0]

        if member_data and member_data.get("customer"):
            customer_name = member_data["customer"]
            if frappe.db.exists("Customer", customer_name):
                result["party_type"] = "Customer"
                result["party"] = customer_name
                # Create Bank Account link for future matching
                _ensure_bank_account_link(iban, customer_name, "Customer")
                frappe.logger().debug(
                    f"[MT940] Matched IBAN {iban} to Member {member_data.get('member_name')} -> Customer {customer_name}"
                )
                return result

    # Priority 2: Look up SEPA Mandate by IBAN -> Member -> Customer
    if iban:
        # Use preloaded data if available (batch mode), otherwise query
        mandate_data = None
        if preloaded_lookups and "mandate_by_iban" in preloaded_lookups:
            mandate_data = preloaded_lookups["mandate_by_iban"].get(iban)
        else:
            try:
                mandate_member = frappe.db.sql(
                    """
                    SELECT sm.member, m.customer
                    FROM `tabSEPA Mandate` sm
                    JOIN `tabMember` m ON sm.member = m.name
                    WHERE sm.iban = %s
                    AND m.customer IS NOT NULL
                    AND m.customer != ''
                    LIMIT 1
                    """,
                    (iban,),
                    as_dict=True,
                )
                if mandate_member:
                    mandate_data = mandate_member[0]
            except Exception:
                pass  # SEPA Mandate table might not exist

        if mandate_data and mandate_data.get("customer"):
            customer_name = mandate_data["customer"]
            if frappe.db.exists("Customer", customer_name):
                result["party_type"] = "Customer"
                result["party"] = customer_name
                _ensure_bank_account_link(iban, customer_name, "Customer")
                frappe.logger().debug(
                    f"[MT940] Matched IBAN {iban} via SEPA Mandate -> Customer {customer_name}"
                )
                return result

    # Priority 3: Look up party by Bank Account IBAN (any party type)
    if iban:
        # Use preloaded data if available (batch mode), otherwise query
        bank_account_data = None
        if preloaded_lookups and "bank_account_by_iban" in preloaded_lookups:
            bank_account_data = preloaded_lookups["bank_account_by_iban"].get(iban)
        else:
            bank_account_party = frappe.db.sql(
                """
                SELECT party, party_type
                FROM `tabBank Account`
                WHERE (bank_account_no = %s OR iban = %s)
                AND party IS NOT NULL
                AND party != ''
                LIMIT 1
                """,
                (iban, iban),
                as_dict=True,
            )
            if bank_account_party:
                bank_account_data = bank_account_party[0]

        if bank_account_data:
            result["party_type"] = bank_account_data["party_type"]
            result["party"] = bank_account_data["party"]
            frappe.logger().debug(
                f"[MT940] Matched IBAN {iban} to {result['party_type']} {result['party']} via Bank Account"
            )
            return result

    # Priority 4: Use BankTransactionParser for name matching
    # This handles exact, case-insensitive, and fuzzy matching
    # AND creates Bank Account links when parties are found/created
    if counterparty_name:
        try:
            from verenigingen.e_boekhouden.utils.bank_transaction_parser import BankTransactionParser

            parser = BankTransactionParser()

            # Use find_or_create_party which:
            # 1. Matches by IBAN (already checked above, but double-checks)
            # 2. Matches by name (exact, case-insensitive, fuzzy)
            # 3. Creates new party if no match (with Bank Account link)
            party_name, created = parser.find_or_create_party(
                party_name=counterparty_name,
                party_type=party_type,
                iban=iban,
            )

            if party_name:
                result["party_type"] = party_type
                result["party"] = party_name
                if created:
                    frappe.logger().info(
                        f"MT940: Created new {party_type} '{party_name}' from bank statement"
                    )
                else:
                    frappe.logger().debug(
                        f"MT940: Matched name '{counterparty_name}' to {party_type} {party_name}"
                    )
                return result

        except ImportError:
            frappe.logger().debug("BankTransactionParser not available for party matching")
        except Exception as e:
            # Fail loudly - party matching is critical for financial reconciliation
            frappe.log_error(
                title="MT940 Party Matching Failed",
                message=f"IBAN: {iban}, Name: {counterparty_name}, Error: {str(e)}",
            )
            raise

    return result


def _ensure_bank_account_link(iban: str, party: str, party_type: str) -> None:
    """
    Ensure a Bank Account record exists linking this IBAN to the party.
    Creates one if it doesn't exist.
    """
    if not iban or not party:
        return

    try:
        # Check if Bank Account already exists for this IBAN
        existing = frappe.db.exists("Bank Account", {"iban": iban})
        if existing:
            return

        # Also check by bank_account_no field
        existing = frappe.db.exists("Bank Account", {"bank_account_no": iban})
        if existing:
            return

        # Ensure the Unknown bank exists (Bank Account requires a Bank link)
        bank_name = get_or_create_unknown_bank()

        # Create Bank Account linking IBAN to party
        # Use migration context for proper permission handling
        from verenigingen.e_boekhouden.utils.security_helper import migration_context

        with migration_context("party_creation"):
            bank_account = frappe.new_doc("Bank Account")
            bank_account.account_name = f"{party} - {iban[-4:]}"
            bank_account.bank = bank_name
            bank_account.iban = iban
            bank_account.party_type = party_type
            bank_account.party = party
            bank_account.is_default = 0  # Don't override existing defaults
            bank_account.insert()

        frappe.logger().info(f"[MT940] Created Bank Account link: IBAN {iban} -> {party_type} {party}")

    except Exception as e:
        # Fail loudly - bank account linking is important for payment matching
        frappe.log_error(
            title="MT940 Bank Account Creation Failed",
            message=f"IBAN: {iban}, Party: {party_type} {party}, Error: {str(e)}",
        )
        raise


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def import_mt940_file(bank_account, file_content, company=None):
    """
    Import MT940 bank statement file without expensive fintech license.

    Args:
        bank_account: ERPNext Bank Account name
        file_content: Base64 encoded MT940 file content
        company: Company name (optional, will be fetched from bank account)

    Returns:
        dict: Import results with success/error information
    """
    try:
        # Validate inputs
        if not bank_account:
            return {"success": False, "message": "Bank Account is required"}

        if not file_content:
            return {"success": False, "message": "File content is required"}

        # Decode file content
        try:
            mt940_content = base64.b64decode(file_content).decode("utf-8")
        except Exception as e:
            return {"success": False, "message": f"Failed to decode file content: {str(e)}"}

        # Get company from bank account if not provided
        if not company:
            company = frappe.db.get_value("Bank Account", bank_account, "company")
            if not company:
                return {
                    "success": False,
                    "message": f"Could not determine company for bank account {bank_account}",
                }

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            return {"success": False, "message": f"Bank Account {bank_account} does not exist"}

        # Process the MT940 file
        result = process_mt940_document(mt940_content, bank_account, company)

        return result

    except Exception as e:
        frappe.logger().error(f"Error in MT940 import: {str(e)}")
        frappe.logger().error(traceback.format_exc())
        return {"success": False, "message": f"Import failed with error: {str(e)}"}


def extract_sepa_data_enhanced(mt940_transaction):
    """
    Extract SEPA data from MT940 transaction using Banking app approach.

    Attempts to access SEPA fields (EREF, MREF, CRED, SVWZ, ABWA) if available
    in the mt940 library, with fallbacks to parsing structured data from
    description fields.
    """
    from verenigingen.verenigingen_payments.utils.sepa_parser import parse_sepa_structured_data

    transaction_data = mt940_transaction.data

    # Try to access SEPA fields if available in mt940 library
    sepa_data = getattr(mt940_transaction, "sepa", {}) or {}

    # Parse structured SEPA data from description/extra_details fields
    # This handles the /CNTP/, /REMI/, /EREF/ etc. tags that Dutch banks embed
    raw_text = " ".join(
        filter(
            None,
            [
                str(transaction_data.get("extra_details", "") or ""),
                str(transaction_data.get("transaction_details", "") or ""),
                str(transaction_data.get("purpose", "") or ""),
            ],
        )
    )
    parsed_sepa = parse_sepa_structured_data(raw_text)

    # Extract enhanced SEPA information with fallbacks
    # Priority: parsed structured data > mt940 library sepa
    # NOTE: Do NOT use transaction_data.get("transaction_reference") here!
    # That field contains the MT940 :20: statement reference (e.g., "P251214000000001")
    # which is the same for all transactions in a statement, not the individual EREF.
    eref = parsed_sepa.get("end_to_end_ref") or sepa_data.get("EREF") or ""

    # Mandate Reference - crucial for direct debit processing
    mref = (
        parsed_sepa.get("mandate_ref")
        or sepa_data.get("MREF")
        or transaction_data.get("mandate_reference")
        or ""
    )

    # Payment purpose (Verwendungszweck) - enhanced description
    svwz = (
        parsed_sepa.get("remittance_info")
        or parsed_sepa.get("payment_purpose")
        or sepa_data.get("SVWZ")
        or transaction_data.get("purpose")
        or transaction_data.get("description")
        or ""
    )
    # Normalize svwz - remove line breaks and collapse whitespace
    if svwz:
        svwz = re.sub(r"[\r\n]+", "", svwz)  # Remove line breaks
        svwz = re.sub(r"\s+", " ", svwz).strip()  # Collapse multiple spaces

    # Creditor Reference
    creditor_ref = (
        parsed_sepa.get("creditor_ref")
        or sepa_data.get("CRED")
        or transaction_data.get("creditor_reference")
        or ""
    )

    # Counterparty name (ABWA = Abweichender Auftraggeber/Begünstigter)
    counterparty = (
        parsed_sepa.get("counterparty_name")
        or sepa_data.get("ABWA")
        or transaction_data.get("counterparty_name")
        or transaction_data.get("name")
        or ""
    )

    # Normalize counterparty - remove line breaks and collapse whitespace
    if counterparty:
        counterparty = re.sub(r"[\r\n]+", "", counterparty)
        counterparty = re.sub(r"\s+", " ", counterparty).strip()

    # Filter out placeholder values
    from verenigingen.verenigingen_payments.utils.sepa_parser import is_placeholder_value

    if is_placeholder_value(counterparty):
        counterparty = ""

    # Counterparty IBAN - get from various sources
    counterparty_iban = (
        parsed_sepa.get("counterparty_account")
        or transaction_data.get("counterparty_account")
        or transaction_data.get("iban")
        or transaction_data.get("account")
        or ""
    )

    # Clean up IBAN - remove whitespace from line breaks in MT940
    if counterparty_iban:
        counterparty_iban = re.sub(r"\s+", "", counterparty_iban)

    # Validate IBAN format - must start with 2 letters (country code) + 2 digits
    # Non-IBANs like 'L96981341' (internal account refs) should be stored separately
    counterparty_account_ref = ""
    if counterparty_iban:
        # Check if it looks like an IBAN (2 letters + 2 digits + rest). Shape-only
        # by design (see IBAN_SHAPE_RE): non-IBANs like 'L96981341' are moved to the
        # account-reference field; anything IBAN-shaped is kept for party matching.
        if not IBAN_SHAPE_RE.match(counterparty_iban.upper()):
            # Not an IBAN, treat as account reference
            counterparty_account_ref = counterparty_iban
            counterparty_iban = ""

    return {
        "eref": eref,
        "mref": mref,
        "svwz": svwz,
        "creditor_ref": creditor_ref,
        "counterparty": counterparty,
        "counterparty_iban": counterparty_iban,
        "counterparty_account_ref": counterparty_account_ref,  # For non-IBAN account numbers
        "raw_sepa": sepa_data,  # Keep raw SEPA data for debugging
        "parsed_sepa": parsed_sepa,  # Include parsed structured data
    }


def get_enhanced_transaction_type(mt940_transaction):
    """
    Enhanced transaction type classification using Banking app approach.

    Priority order:
    1. booking_text (human-readable bank description)
    2. Dutch booking code mapping
    3. SEPA transaction type classification
    4. Amount-based fallback
    """
    transaction_data = mt940_transaction.data

    # Priority 1: Use booking_text if available (Banking app approach)
    booking_text = transaction_data.get("booking_text")
    if booking_text and booking_text.strip():
        return booking_text.strip()[:50]  # ERPNext field limit

    # Priority 2: Map Dutch banking codes
    booking_key = transaction_data.get("booking_key") or transaction_data.get("gv_code")
    if booking_key and str(booking_key) in DUTCH_BOOKING_CODES:
        return DUTCH_BOOKING_CODES[str(booking_key)]

    # Priority 3: SEPA transaction type classification
    sepa_data = extract_sepa_data_enhanced(mt940_transaction)
    purpose = sepa_data["svwz"].upper()

    for sepa_code, sepa_type in SEPA_TRANSACTION_TYPES.items():
        if sepa_code in purpose:
            return sepa_type

    # Priority 4: Amount-based fallback with transaction direction
    amount_obj = transaction_data.get("amount")
    if amount_obj:
        amount = float(amount_obj.amount) if hasattr(amount_obj, "amount") else float(amount_obj)
    else:
        amount = 0

    if amount > 0:
        return "Incoming Transfer"
    else:
        return "Outgoing Transfer"


def get_enhanced_duplicate_hash(mt940_transaction, sepa_data):
    """
    Enhanced duplicate detection using Banking app strategy.

    Includes transaction type and SEPA data for more robust duplicate detection.
    """
    transaction_data = mt940_transaction.data

    # Enhanced hash components following Banking app approach
    # Extract date and amount from transaction data
    trans_date = transaction_data.get("date", "")
    amount_obj = transaction_data.get("amount")
    if amount_obj:
        amount_val = amount_obj.amount if hasattr(amount_obj, "amount") else amount_obj
        currency_val = getattr(amount_obj, "currency", "EUR") if hasattr(amount_obj, "currency") else "EUR"
    else:
        amount_val = 0
        currency_val = "EUR"

    values_to_hash = [
        str(trans_date),  # Transaction date
        str(amount_val),  # Amount
        str(currency_val),  # Currency
        sepa_data["eref"],  # SEPA End-to-end reference
        sepa_data["counterparty"],  # Counterparty name
        sepa_data["counterparty_iban"],  # Counterparty IBAN
        get_enhanced_transaction_type(mt940_transaction),  # Transaction type
        sepa_data["svwz"],  # SEPA payment purpose
        transaction_data.get("booking_key", ""),  # Bank booking code
        transaction_data.get("bank_reference", ""),  # Bank reference
    ]

    # Create SHA256 hash
    sha = hashlib.sha256()
    for value in values_to_hash:
        if value:
            sha.update(str(value).encode("utf-8"))

    return sha.hexdigest()


def extract_sepa_purpose_code(purpose_text):
    """
    Extract SEPA purpose code from payment purpose text.

    Args:
        purpose_text: Payment purpose text from SVWZ field

    Returns:
        str: SEPA purpose code (e.g., SALA, PENS, GOVT) or empty string
    """
    if not purpose_text:
        return ""

    purpose_upper = purpose_text.upper()

    # Check for SEPA purpose codes in the text
    for code in SEPA_TRANSACTION_TYPES.keys():
        if code in purpose_upper:
            return code

    return ""


def clean_description_redundancy(description: str, counterparty_name: str, counterparty_iban: str) -> str:
    """
    Remove redundant "Betaling van [Name] [IBAN]" prefix from payment descriptions.

    Dutch banks/Mollie often include the payer's name and IBAN in the remittance info
    even though this is already in the CNTP (counterparty) field. This creates verbose
    descriptions like "Betaling van Hr M E J Eggermont NL96INGB0005119504 Contributie..."
    when the meaningful part is just "Contributie...".

    Args:
        description: The raw description/remittance info
        counterparty_name: The counterparty name from CNTP field
        counterparty_iban: The counterparty IBAN from CNTP field

    Returns:
        str: Cleaned description with redundant prefix removed
    """
    if not description:
        return description

    # Pattern: "Betaling van [Name] [IBAN] [actual message]"
    # The name/IBAN in the prefix may have slight variations from CNTP
    # so we use a flexible regex approach

    # First try exact match with counterparty info
    if counterparty_name and counterparty_iban:
        # Escape special regex chars in name
        escaped_name = re.escape(counterparty_name)
        escaped_iban = re.escape(counterparty_iban)

        # Try pattern: "Betaling van [Name] [IBAN] "
        pattern = rf"^Betaling van\s+{escaped_name}\s+{escaped_iban}\s+"
        cleaned = re.sub(pattern, "", description, flags=re.IGNORECASE)
        if cleaned != description:
            return cleaned.strip()

    # Generic pattern: "Betaling van [any name] [any IBAN] "
    # IBAN pattern: 2 letters + 2 digits + up to 30 alphanumeric
    match = re.match(DUTCH_PAYMENT_PREFIX_PATTERN, description, re.IGNORECASE)
    if match:
        # Remove the matched prefix
        cleaned = description[match.end() :].strip()
        if cleaned:
            return cleaned

    return description


def process_mt940_document(mt940_content, bank_account, company):
    """
    Process MT940 document content using the WoLpH/mt940 library.

    Uses the free mt940 library instead of expensive fintech license.
    """
    try:
        # Try to import the mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Write content to temporary file (mt940 library expects file path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            # Parse the MT940 file
            transactions = mt940.parse(temp_file_path)

            # Convert to list to check if any transactions found
            transaction_list = list(transactions)

            if not transaction_list:
                return {"success": False, "message": "No transactions found in MT940 file"}

            # Get bank account IBAN for validation
            bank_account_iban = frappe.db.get_value("Bank Account", bank_account, "bank_account_no")

            # The statement-level account identification (MT940 :25:) lives on the
            # parsed *container*, not on the individual Transaction objects. Read it
            # from `transactions` before iterating. (The previous per-transaction
            # `statement.data["account_identification"]` check never matched real
            # mt940 output, so the bank-account guard below was dead code.)
            statement_iban = (getattr(transactions, "data", None) or {}).get("account_identification")

            # Reject up front if the statement belongs to a different account than the
            # selected Bank Account — before creating any records. Compare with
            # whitespace/case normalisation so trivial formatting differences (e.g.
            # spaced IBAN groups) don't false-reject a matching account.
            if bank_account_iban and statement_iban:
                _norm_bank = "".join(str(bank_account_iban).split()).upper()
                _norm_stmt = "".join(str(statement_iban).split()).upper()
                if _norm_bank != _norm_stmt:
                    return {
                        "success": False,
                        "message": (
                            f"IBAN mismatch: Bank Account IBAN {bank_account_iban} does not "
                            f"match MT940 statement IBAN {statement_iban}"
                        ),
                    }

            # Process transactions
            transactions_created = 0
            transactions_skipped = 0
            errors = []

            # Process transactions - avoid double counting by processing all transactions directly
            processed_transaction_ids = set()  # Track processed transactions to avoid duplicates

            # Batch preload party lookups to eliminate N+1 query pattern
            # Extract all counterparty IBANs first
            all_ibans = []
            for stmt in transaction_list:
                sepa_data = extract_sepa_data_enhanced(stmt)
                if sepa_data.get("counterparty_iban"):
                    all_ibans.append(sepa_data["counterparty_iban"])
            preloaded_lookups = batch_preload_party_lookups(all_ibans)

            # Use savepoint for transaction isolation - allows atomic rollback on failure
            # This prevents orphaned Customer/Bank Account records if import fails partway
            savepoint_name = f"mt940_import_{frappe.generate_hash()[:8]}"

            try:
                frappe.db.savepoint(savepoint_name)

                for statement in transaction_list:
                    # (Statement/bank-account IBAN validation happens once before this
                    # loop — see above. The per-transaction objects carry no
                    # account_identification.)
                    # In MT940 library, each statement object IS a transaction, not a container
                    # The library structure treats each parsed item as a single transaction
                    try:
                        # Generate transaction ID to check for duplicates within this import.
                        # NOTE: extract_sepa_data_enhanced and get_enhanced_duplicate_hash are
                        # already module-level functions. A previous self-import here
                        # (`from ...mt940_import import extract_sepa_data_enhanced`) made those
                        # names function-local, which raised UnboundLocalError at the earlier
                        # preload call (all_ibans loop) and broke every import that contained a
                        # counterparty IBAN. Use the module-level names directly.
                        sepa_data = extract_sepa_data_enhanced(statement)
                        transaction_id = get_enhanced_duplicate_hash(statement, sepa_data)[:32]

                        # Skip if we've already processed this exact transaction in this import
                        if transaction_id in processed_transaction_ids:
                            continue

                        processed_transaction_ids.add(transaction_id)

                        # Create bank transaction using enhanced method
                        if create_enhanced_bank_transaction_from_mt940(
                            statement, bank_account, company, preloaded_lookups=preloaded_lookups
                        ):
                            transactions_created += 1
                        else:
                            transactions_skipped += 1

                    except Exception as e:
                        errors.append(f"Transaction error: {str(e)}")
                        frappe.logger().error(f"[MT940] Error processing transaction: {str(e)}")

                # Release savepoint on success (implicit commit of savepoint).
                # A nested commit can occur mid-import - e.g. the API security audit
                # logger commits unconditionally when it stores an audit event
                # (utils/security/audit_logging.py). A COMMIT clears all savepoints,
                # so the named savepoint may no longer exist here even though the
                # import succeeded and its rows are already persisted. Treat a
                # missing savepoint on release as a no-op rather than failing an
                # otherwise-successful import.
                release_savepoint_if_present(savepoint_name)

            except NON_RESUMABLE_DB_ERRORS:
                # The return below reports "import failed and rolled back". On a 1205/1213
                # neither half of that sentence is knowable here: the server has discarded
                # or half-applied the transaction, and the rows this batch created may or
                # may not survive. Let the caller see the real error and retry the import.
                raise
            except Exception as batch_error:
                # Rollback entire batch on critical failure. The savepoint may have been
                # cleared by a nested commit (see release note above); if so the partial
                # rows are already committed and cannot be rolled back here, so don't let a
                # missing-savepoint error mask the real batch error. That is what
                # rollback_to_savepoint() does -- this file hand-wrote both halves of it
                # before they were helpers (#561).
                rollback_to_savepoint(savepoint_name)
                frappe.log_error(
                    title="MT940 Import Batch Failed",
                    message=f"Bank Account: {bank_account}, Error: {str(batch_error)}",
                )
                return {
                    "success": False,
                    "message": f"Import failed and rolled back: {str(batch_error)}",
                    "transactions_created": 0,
                    "transactions_skipped": 0,
                    "errors": [str(batch_error)],
                }

            # Calculate date range from processed transactions - each statement IS a transaction
            transaction_dates = []
            processed_dates = set()  # Track unique dates to avoid duplicates

            for statement in transaction_list:
                # Extract date from statement data
                transaction_data = getattr(statement, "data", {})
                if transaction_data and "date" in transaction_data:
                    date_obj = transaction_data["date"]
                    date_str = str(date_obj)

                    # Only add unique dates to avoid counting the same date multiple times
                    if date_str not in processed_dates:
                        transaction_dates.append(date_obj)
                        processed_dates.add(date_str)

            # Determine date range
            from_date = min(transaction_dates) if transaction_dates else getdate(today())
            to_date = max(transaction_dates) if transaction_dates else getdate(today())

            return {
                "success": True,
                "message": f"Import completed: {transactions_created} transactions created, {transactions_skipped} skipped",
                "transactions_created": transactions_created,
                "transactions_skipped": transactions_skipped,
                "errors": errors[:10],  # Limit errors shown
                "iban": statement_iban,
                "statement_date": str(getdate(today())),
                "statement_from_date": str(from_date),
                "statement_to_date": str(to_date),
                "transaction_count": len(transaction_dates),
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Failed to process MT940 document: {str(e)}"}


def create_enhanced_bank_transaction_from_mt940(
    mt940_transaction, bank_account, company, preloaded_lookups=None
):
    """
    Enhanced Bank Transaction creation inspired by Banking app approach.

    Features:
    - Advanced SEPA data extraction (EREF, MREF, SVWZ, ABWA)
    - Sophisticated transaction type classification
    - Enhanced duplicate detection using multiple fields
    - Better handling of Dutch banking codes
    - Batch preloaded party lookups to eliminate N+1 queries

    Args:
        mt940_transaction: Parsed MT940 transaction object
        bank_account: ERPNext Bank Account name
        company: Company name
        preloaded_lookups: Optional dict from batch_preload_party_lookups() for N+1 optimization
    """
    try:
        import contextlib

        # Extract enhanced SEPA data
        sepa_data = extract_sepa_data_enhanced(mt940_transaction)

        # Generate enhanced transaction ID using Banking app strategy
        # Use 32 chars (128 bits) for collision-resistant duplicate detection
        transaction_id = get_enhanced_duplicate_hash(mt940_transaction, sepa_data)[:32]

        # Check if transaction already exists
        if transaction_id and frappe.db.exists(
            "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
        ):
            return False  # Already exists

        # Create new Bank Transaction with enhanced data
        bt = frappe.new_doc("Bank Transaction")

        # Extract date from transaction data
        transaction_data = mt940_transaction.data
        bt.date = transaction_data.get("date") or getdate(today())
        bt.bank_account = bank_account
        bt.company = company

        # Handle amount and direction - amount is in the data structure
        amount_obj = transaction_data.get("amount")
        if amount_obj:
            amount = float(amount_obj.amount) if hasattr(amount_obj, "amount") else float(amount_obj)
            bt.currency = getattr(amount_obj, "currency", "EUR") if hasattr(amount_obj, "currency") else "EUR"
        else:
            amount = 0.0
            bt.currency = "EUR"

        bt.deposit = max(amount, 0)
        bt.withdrawal = abs(min(amount, 0))

        # Enhanced description using SEPA SVWZ field (Banking app approach)
        description = sepa_data["svwz"]
        if not description:
            # Fallback to other description sources
            transaction_data = mt940_transaction.data
            description_parts = []
            if transaction_data.get("purpose"):
                description_parts.append(str(transaction_data["purpose"]))

            # Translate a TRCD booking code into a human-readable description.
            # The /TRCD/<code>/ blob canonically lives in the :86: structured
            # field, which the mt940 library parses into `transaction_details`;
            # `extra_details` is only the short :61: supplementary field. Inspect
            # both so genuine library output is translated, not just hand-built
            # transactions whose code happens to sit in extra_details.
            extra_details = transaction_data.get("extra_details", "") or ""
            detail_text = str(transaction_data.get("transaction_details", "") or "")
            trcd_match = re.search(r"/TRCD/(\d+)/?", detail_text) or re.search(
                r"/TRCD/(\d+)/?", str(extra_details)
            )
            if trcd_match:
                trcd_code = trcd_match.group(1)
                # Use human-readable description from DUTCH_BOOKING_CODES
                trcd_description = DUTCH_BOOKING_CODES.get(trcd_code)
                if trcd_description:
                    # Use counterparty name to make description more useful
                    counterparty = sepa_data.get("counterparty", "")
                    if counterparty:
                        description_parts.append(f"{trcd_description} - {counterparty}")
                    else:
                        description_parts.append(trcd_description)
                elif extra_details:
                    # Unknown code, just use the raw extra_details
                    description_parts.append(str(extra_details))
            elif extra_details:
                description_parts.append(str(extra_details))

            description = " | ".join(filter(None, description_parts))

        # Normalize description - remove line breaks and collapse whitespace
        if description:
            description = re.sub(r"[\r\n]+", "", description)
            description = re.sub(r"\s+", " ", description).strip()

        # Clean up redundant "Betaling van [Name] [IBAN]" prefix
        if description:
            description = clean_description_redundancy(
                description,
                sepa_data.get("counterparty", ""),
                sepa_data.get("counterparty_iban", ""),
            )

        bt.description = description or DEFAULT_TRANSACTION_DESCRIPTION

        # Enhanced transaction type using Banking app approach
        bt.transaction_type = get_enhanced_transaction_type(mt940_transaction)

        # Enhanced reference using SEPA EREF, then bank_reference as fallback
        # Avoid using transaction_reference as it may be the statement reference
        reference = sepa_data["eref"]
        if not reference or reference == "NONREF":
            # Use bank_reference from :61: field as fallback
            reference = transaction_data.get("bank_reference", "")
        bt.reference_number = reference if reference and reference != "NONREF" else ""
        bt.transaction_id = transaction_id

        # Enhanced party information using SEPA ABWA field
        bt.bank_party_name = sepa_data["counterparty"]
        bt.bank_party_iban = sepa_data["counterparty_iban"]

        # Store non-IBAN account reference (e.g., ING internal account ref like 'L96981341')
        if sepa_data.get("counterparty_account_ref"):
            bt.bank_party_account_number = sepa_data["counterparty_account_ref"]

        # Party matching - try to link to existing Customer/Supplier
        # Incoming transactions (deposits) -> look for Customer
        # Outgoing transactions (withdrawals) -> look for Supplier
        is_incoming = amount > 0
        party_match = find_party_by_iban_or_name(
            iban=sepa_data["counterparty_iban"],
            counterparty_name=sepa_data["counterparty"],
            is_incoming=is_incoming,
            internal_account_ref=sepa_data.get("counterparty_account_ref"),
            company=company,
            preloaded_lookups=preloaded_lookups,
        )

        # Handle internal transfers (own accounts like savings)
        if party_match.get("is_internal_transfer"):
            # Don't set party for internal transfers - it's our own account
            frappe.logger().info(
                f"MT940: Internal transfer detected to/from {party_match.get('internal_bank_account')} "
                f"(counterparty: {sepa_data['counterparty']}, ref: {sepa_data.get('counterparty_account_ref')})"
            )
            # Update description to indicate internal transfer if not already clear
            if bt.description and "intern" not in bt.description.lower():
                internal_account = party_match.get("internal_bank_account", "")
                if internal_account:
                    # Get the account name for a clearer description
                    account_name = (
                        frappe.db.get_value("Bank Account", internal_account, "account_name")
                        or internal_account
                    )
                    bt.description = f"Internal transfer: {account_name} - {bt.description}"
        elif party_match.get("party"):
            bt.party_type = party_match["party_type"]
            bt.party = party_match["party"]
            frappe.logger().debug(
                f"MT940: Linked transaction to {bt.party_type} {bt.party} "
                f"(IBAN: {sepa_data['counterparty_iban']}, Name: {sepa_data['counterparty']})"
            )
            # Link to Member if this Customer is linked to a Member
            if bt.party_type == "Customer":
                from verenigingen.utils.financial_utils import get_member_for_customer

                member_name = get_member_for_customer(bt.party)
                if member_name:
                    bt.custom_member = member_name
                    frappe.logger().debug(f"MT940: Linked transaction to Member {member_name}")

        # Store additional SEPA data in custom fields (if available)
        try:
            from verenigingen.verenigingen_payments.utils.mt940_enhanced_fields import (
                populate_enhanced_mt940_fields,
                validate_enhanced_fields_exist,
            )

            if validate_enhanced_fields_exist():
                enhanced_data = {
                    "mandate_reference": sepa_data["mref"],
                    "creditor_reference": sepa_data["creditor_ref"],
                    "booking_key": mt940_transaction.data.get("booking_key", ""),
                    "bank_reference": mt940_transaction.data.get("bank_reference", ""),
                    "enhanced_transaction_type": bt.transaction_type,
                    "sepa_purpose_code": extract_sepa_purpose_code(sepa_data["svwz"]),
                }

                populate_enhanced_mt940_fields(bt, enhanced_data)
            else:
                # Store in temporary attribute for debugging if fields don't exist
                bt._enhanced_data = {
                    "mandate_reference": sepa_data["mref"],
                    "creditor_reference": sepa_data["creditor_ref"],
                    "booking_key": mt940_transaction.data.get("booking_key", ""),
                    "bank_reference": mt940_transaction.data.get("bank_reference", ""),
                    "raw_sepa": sepa_data["raw_sepa"],
                }
        except ImportError:
            # Enhanced fields module not available
            pass

        # Insert and submit with enhanced error handling
        with contextlib.suppress(frappe.exceptions.UniqueValidationError):
            bt.insert()
            bt.submit()

            # Log enhanced transaction creation for debugging
            frappe.logger().info(
                f"Enhanced MT940 transaction created: {transaction_id} - "
                f"{bt.transaction_type} - {amount} {bt.currency} - {sepa_data['counterparty']}"
            )
            return True

    except Exception as e:
        frappe.logger().error(f"Error creating enhanced bank transaction from MT940: {str(e)}")
        # Log additional debug information
        frappe.logger().error(f"Transaction data: {getattr(mt940_transaction, 'data', {})}")
        raise

    return False


def create_bank_transaction_from_mt940(mt940_transaction, bank_account, company):
    """
    Legacy function - redirects to enhanced version for backwards compatibility.
    """
    return create_enhanced_bank_transaction_from_mt940(mt940_transaction, bank_account, company)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_mt940_import_status():
    """Get status of recent MT940 imports"""
    try:
        # Get recent bank transactions that might have been imported
        recent_transactions = frappe.get_all(
            "Bank Transaction",
            filters={"modified": [">=", frappe.utils.add_days(today(), -7)]},
            fields=["name", "date", "bank_account", "deposit", "withdrawal", "description"],
            order_by="modified desc",
            limit=20,
        )

        return {
            "success": True,
            "recent_transactions": recent_transactions,
            "total_recent": len(recent_transactions),
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_mt940_file(file_content):
    """Validate an MT940 file without importing it"""
    try:
        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Try to import mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Write to temporary file and parse
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            # Parse document
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            # Count total transactions
            total_transactions = 0
            statement_iban = None

            for statement in transaction_list:
                if hasattr(statement, "data") and "account_identification" in statement.data:
                    statement_iban = statement.data["account_identification"]

                # Count transactions in statement
                if hasattr(statement, "transactions"):
                    total_transactions += len(statement.transactions)
                elif hasattr(statement, "__iter__"):
                    try:
                        total_transactions += len(list(statement))
                    except Exception:
                        total_transactions += 1
                else:
                    total_transactions += 1

            return {
                "success": True,
                "message": f"Valid MT940 file with {total_transactions} transactions",
                "transaction_count": total_transactions,
                "iban": statement_iban or "Unknown",
                "file_size": len(mt940_content),
                "statements_count": len(transaction_list),
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Invalid MT940 file: {str(e)}"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def convert_mt940_to_csv(file_content, bank_account):
    """
    Convert MT940 file to CSV format that ERPNext can import.

    This provides an alternative approach using ERPNext's existing
    Bank Statement Import functionality.
    """
    try:
        # Decode and validate MT940 content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Import mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Parse MT940 file
        import csv
        import io

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transactions = mt940.parse(temp_file_path)

            # Create CSV output
            output = io.StringIO()
            csv_writer = csv.writer(output)

            # Write header row matching ERPNext Bank Transaction fields
            csv_writer.writerow(
                [
                    "Date",
                    "Description",
                    "Reference Number",
                    "Deposit",
                    "Withdrawal",
                    "Bank Account",
                    "Bank Party Name",
                    "Bank Party IBAN",
                ]
            )

            # Write transaction rows
            for statement in transactions:
                statement_transactions = []
                if hasattr(statement, "transactions"):
                    statement_transactions = statement.transactions
                elif hasattr(statement, "__iter__"):
                    try:
                        statement_transactions = list(statement)
                    except Exception:
                        statement_transactions = [statement]
                else:
                    statement_transactions = [statement]

                for transaction in statement_transactions:
                    transaction_data = transaction.data
                    # mt940 exposes parsed fields via .data, not as attributes
                    # (transaction.amount / transaction.date raise AttributeError
                    # on a real Transaction object).
                    amount_obj = transaction_data.get("amount")
                    amount = float(getattr(amount_obj, "amount", 0) or 0)
                    trans_date = transaction_data.get("date")
                    date_str = (
                        trans_date.strftime("%Y-%m-%d")
                        if hasattr(trans_date, "strftime")
                        else str(trans_date or "")
                    )

                    csv_writer.writerow(
                        [
                            date_str,
                            transaction_data.get("purpose", "MT940 Transaction"),
                            transaction_data.get("transaction_reference", ""),
                            max(amount, 0),  # Deposit (positive amounts)
                            abs(min(amount, 0)),  # Withdrawal (negative amounts as positive)
                            bank_account,
                            transaction_data.get("counterparty_name", ""),
                            transaction_data.get("counterparty_account", ""),
                        ]
                    )

            csv_content = output.getvalue()
            output.close()

            # Encode as base64 for download
            csv_base64 = base64.b64encode(csv_content.encode()).decode()

            return {
                "success": True,
                "message": "MT940 file converted to CSV successfully",
                "csv_content": csv_base64,
                "filename": f"mt940_import_{today()}.csv",
            }

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Failed to convert MT940 to CSV: {str(e)}"}
