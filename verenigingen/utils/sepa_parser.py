"""
SEPA Structured Data Parser for MT940 Bank Statements

This module parses SEPA/SWIFT structured data from MT940 :86: fields
(description/extra_details) which contain structured tags like /CNTP/, /REMI/, etc.

Dutch and European banks commonly embed SEPA data in these structured formats
rather than using separate fields in the MT940 library output.
"""

import re
from typing import Dict, Optional


def parse_sepa_structured_data(text: str) -> Dict[str, str]:
    """
    Parse SEPA structured data from MT940 :86: field (description/extra_details).

    SEPA/SWIFT structured data uses tags like:
    - /CNTP/account/bic/name/city/country/ - Counterparty
    - /REMI/type/text/ - Remittance information
    - /EREF/reference/ - End-to-end reference
    - /MREF/reference/ - Mandate reference
    - /CREF/reference/ - Creditor reference
    - /TRCD/code/ - Transaction code
    - /SVWZ/text/ - Payment purpose (Verwendungszweck)
    - /ABWA/name/ - Alternative payer/payee name
    - /NAME/name/ - Name (alternative format)
    - /IBAN/account/ - IBAN (alternative format)
    - /BIC/code/ - BIC (alternative format)

    Note: MT940 :86: fields wrap at ~65 chars, so tags can be split across lines.
    E.g., /REMI/ might appear as /REM\\nI/ - we normalize this before parsing.

    Args:
        text: Raw description/extra_details text from MT940

    Returns:
        dict: Parsed SEPA data with keys like counterparty_name, counterparty_account, etc.
    """
    # First, normalize the text by removing line breaks that split tag names
    # MT940 :86: fields wrap at ~65 characters, splitting tags like /REMI/ into /REM\nI/
    if text:
        # Remove newlines/carriage returns that occur within the text
        # but preserve the content by just removing the line break characters
        text = text.replace('\r\n', '').replace('\r', '').replace('\n', '')
    result = {
        "counterparty_name": "",
        "counterparty_account": "",
        "counterparty_bic": "",
        "remittance_info": "",
        "end_to_end_ref": "",
        "mandate_ref": "",
        "creditor_ref": "",
        "transaction_code": "",
        "payment_purpose": "",
    }

    if not text:
        return result

    # Parse CNTP (Counterparty) - format: /CNTP/account/bic/name/city/country/
    # Note: Account numbers may be split across lines in MT940, creating spaces/newlines
    cntp_match = re.search(r"/CNTP/([^/]*)/([^/]*)/([^/]*)/([^/]*)?/?([^/]*)?/?", text)
    if cntp_match:
        # Clean up account number - remove any whitespace/newlines from line breaks
        account = cntp_match.group(1)
        account = re.sub(r'\s+', '', account)  # Remove all whitespace
        result["counterparty_account"] = account
        result["counterparty_bic"] = cntp_match.group(2).strip()
        result["counterparty_name"] = cntp_match.group(3).strip()

    # Parse REMI (Remittance) - format: /REMI/type/text/ or /REMI/USTD//text/
    # After normalization, text has no newlines, but may have // (double slash)
    # IMPORTANT: Don't stop at "/" in text like "e/o" (Dutch "en/of" = and/or)
    # Only stop at "/" when followed by a SEPA tag name (uppercase letters)
    # Use negative lookahead to allow "/" not followed by SEPA tags
    remi_match = re.search(r"/REMI/([^/]*)/+(.+?)(?=/[A-Z]{4}/|//[A-Z]|\||\Z)", text)
    if remi_match:
        remi_type = remi_match.group(1).strip()
        remi_text = remi_match.group(2).strip()
        # Clean up: remove trailing slashes that aren't part of the text
        remi_text = remi_text.rstrip("/")
        result["remittance_info"] = remi_text if remi_text else remi_type

    # Parse EREF (End-to-end reference) - format: /EREF/reference/
    eref_match = re.search(r"/EREF/([^/|]+)", text)
    if eref_match:
        result["end_to_end_ref"] = eref_match.group(1).strip()

    # Parse MREF (Mandate reference) - format: /MREF/reference/
    mref_match = re.search(r"/MREF/([^/|]+)", text)
    if mref_match:
        result["mandate_ref"] = mref_match.group(1).strip()

    # Parse CREF/CRED (Creditor reference) - format: /CREF/reference/ or /CRED/reference/
    cref_match = re.search(r"/C(?:REF|RED)/([^/|]+)", text)
    if cref_match:
        result["creditor_ref"] = cref_match.group(1).strip()

    # Parse TRCD (Transaction code) - format: /TRCD/code/
    trcd_match = re.search(r"/TRCD/([^/|]+)", text)
    if trcd_match:
        result["transaction_code"] = trcd_match.group(1).strip()

    # Parse SVWZ (Payment purpose/Verwendungszweck) - format: /SVWZ/text/
    svwz_match = re.search(r"/SVWZ/([^/|]+)", text)
    if svwz_match:
        result["payment_purpose"] = svwz_match.group(1).strip()

    # Parse ABWA (Alternative payer/payee) - format: /ABWA/name/
    abwa_match = re.search(r"/ABWA/([^/|]+)", text)
    if abwa_match:
        # ABWA overrides counterparty name if present
        result["counterparty_name"] = abwa_match.group(1).strip()

    # Alternative formats - /NAME/, /IBAN/, /BIC/
    if not result["counterparty_name"]:
        name_match = re.search(r"/NAME/([^/|]+)", text)
        if name_match:
            result["counterparty_name"] = name_match.group(1).strip()

    if not result["counterparty_account"]:
        iban_match = re.search(r"/IBAN/([^/|]+)", text)
        if iban_match:
            # Clean up IBAN - remove any whitespace from line breaks
            iban = re.sub(r'\s+', '', iban_match.group(1))
            result["counterparty_account"] = iban

    if not result["counterparty_bic"]:
        bic_match = re.search(r"/BIC/([^/|]+)", text)
        if bic_match:
            result["counterparty_bic"] = bic_match.group(1).strip()

    return result


def extract_sepa_from_mt940_transaction(transaction_data: dict) -> Dict[str, str]:
    """
    Extract SEPA data from MT940 transaction data dictionary.

    Combines data from multiple potential source fields and parses
    any SEPA structured data found.

    Args:
        transaction_data: The .data dictionary from an MT940 transaction object

    Returns:
        dict: Parsed SEPA data
    """
    # Combine text fields that might contain SEPA structured data
    raw_text = " ".join(
        filter(
            None,
            [
                str(transaction_data.get("extra_details", "") or ""),
                str(transaction_data.get("transaction_details", "") or ""),
                str(transaction_data.get("purpose", "") or ""),
                str(transaction_data.get("description", "") or ""),
            ],
        )
    )

    return parse_sepa_structured_data(raw_text)


def get_counterparty_from_sepa(
    sepa_data: Dict[str, str],
    fallback_name: Optional[str] = None,
    fallback_account: Optional[str] = None,
) -> tuple:
    """
    Get counterparty name and account from SEPA data with fallbacks.

    Filters out placeholder values like "NONREF".

    Args:
        sepa_data: Parsed SEPA data dictionary
        fallback_name: Fallback counterparty name if not in SEPA data
        fallback_account: Fallback counterparty account if not in SEPA data

    Returns:
        tuple: (counterparty_name, counterparty_account)
    """
    name = sepa_data.get("counterparty_name") or fallback_name or ""
    account = sepa_data.get("counterparty_account") or fallback_account or ""

    # Filter out placeholder values
    if name and name.upper() in ("NONREF", "NOTPROVIDED", "N/A"):
        name = ""

    return name, account


def get_description_from_sepa(
    sepa_data: Dict[str, str],
    fallback_description: Optional[str] = None,
) -> str:
    """
    Get a clean description from SEPA data.

    Prefers remittance_info or payment_purpose over raw description.

    Args:
        sepa_data: Parsed SEPA data dictionary
        fallback_description: Fallback if no SEPA description available

    Returns:
        str: Clean description text
    """
    if sepa_data.get("remittance_info"):
        return sepa_data["remittance_info"]
    if sepa_data.get("payment_purpose"):
        return sepa_data["payment_purpose"]
    return fallback_description or ""
