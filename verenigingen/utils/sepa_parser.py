"""
SEPA Structured Data Parser for MT940 Bank Statements

This module parses SEPA/SWIFT structured data from MT940 :86: fields
(description/extra_details) which contain structured tags like /CNTP/, /REMI/, etc.

Dutch and European banks commonly embed SEPA data in these structured formats
rather than using separate fields in the MT940 library output.
"""

import re
from typing import Dict, Optional, Tuple

# Maximum length for party names (ERPNext customer_name field limit)
MAX_PARTY_NAME_LENGTH = 140

# Maximum input length for SEPA parsing (DoS prevention)
# MT940 :86: fields are typically <1000 chars; 10000 is generous upper bound
MAX_SEPA_INPUT_LENGTH = 10000

# Placeholder values that should be treated as empty
SEPA_PLACEHOLDER_VALUES = frozenset({"NONREF", "NOTPROVIDED", "N/A", "NICHT ANGEGEBEN", "NOT PROVIDED"})


def sanitize_party_name(name: str) -> str:
    """
    Sanitize party name from bank statement for safe storage.

    Bank statements can contain:
    - Control characters
    - Emojis and special Unicode
    - Excessively long strings
    - Leading/trailing whitespace

    Args:
        name: Raw party name from bank statement

    Returns:
        Sanitized name safe for database storage
    """
    if not name:
        return name

    # Remove control characters (ASCII 0-31 and 127-159)
    name = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", name)

    # Remove emojis and other non-BMP Unicode (keeps accented chars for Dutch/European names)
    # This pattern removes characters outside Basic Multilingual Plane
    name = re.sub(r"[\U00010000-\U0010FFFF]", "", name)

    # Collapse multiple whitespace to single space
    name = re.sub(r"\s+", " ", name)

    # Strip leading/trailing whitespace
    name = name.strip()

    # Truncate to maximum length
    if len(name) > MAX_PARTY_NAME_LENGTH:
        name = name[:MAX_PARTY_NAME_LENGTH].strip()

    return name


def is_placeholder_value(value: str) -> bool:
    """Check if a value is a SEPA placeholder that should be treated as empty."""
    if not value:
        return True
    return value.strip().upper() in SEPA_PLACEHOLDER_VALUES


# Dutch salutations mapped to ERPNext Salutation DocType names
# Bank statements often include salutations like "Hr", "Mw", "Dhr" before names
# Key: Dutch abbreviation (case-insensitive match)
# Value: ERPNext Salutation name (must exist in Salutation DocType)
DUTCH_SALUTATIONS = {
    # Male salutations -> Mr
    "hr": "Mr",  # Heer (formal) - most common in bank statements
    "dhr": "Mr",  # De Heer (formal)
    "dhr.": "Mr",  # De Heer with period
    "hr.": "Mr",  # Heer with period
    "de heer": "Mr",  # Full form
    "heer": "Mr",  # Without "de"
    "meneer": "Mr",  # Informal
    "mijnheer": "Mr",  # Formal spoken
    "mnhr": "Mr",  # Abbreviation
    # Female salutations -> Mrs/Ms
    "mw": "Mrs",  # Mevrouw (formal) - most common in bank statements
    "mw.": "Mrs",  # Mevrouw with period
    "mevr": "Mrs",  # Mevrouw abbreviated
    "mevr.": "Mrs",  # Mevrouw abbreviated with period
    "mevrouw": "Mrs",  # Full form
    "mvr": "Mrs",  # Abbreviation
    "mvr.": "Mrs",  # Abbreviation with period
    "mejuffrouw": "Miss",  # Unmarried woman (traditional)
    "mej": "Miss",  # Mejuffrouw abbreviated
    "mej.": "Miss",  # Mejuffrouw abbreviated with period
    "juffrouw": "Miss",  # Informal unmarried
    # Professional/Academic titles
    "dr": "Dr",  # Doctor
    "dr.": "Dr",  # Doctor with period
    "drs": "Dr",  # Doctorandus (Dutch academic title)
    "drs.": "Dr",  # Doctorandus with period
    "ir.": "Mr",  # Ingenieur (require period - avoid matching random text)
    "ing.": "Mr",  # Ingenieur HBO (require period - "ING" is a bank)
    "mr.": "Mr",  # Meester in de rechten (law degree)
    "prof": "Prof",  # Professor
    "prof.": "Prof",  # Professor with period
    "professor": "Prof",  # Full form
    # Religious titles
    "ds": "Mr",  # Dominee (minister)
    "ds.": "Mr",  # Dominee with period
    "pastoor": "Mr",  # Pastor
    "pater": "Mr",  # Father (religious)
    "zr": "Ms",  # Zuster (sister/nurse)
    "zr.": "Ms",  # Zuster with period
    "br": "Mr",  # Broeder (brother, religious)
    "br.": "Mr",  # Broeder with period
    # Family/Other
    "fam": None,  # Familie - not personal, skip
    "fam.": None,  # Familie with period
    "familie": None,  # Full form
    "wed": "Mrs",  # Weduwe (widow)
    "wed.": "Mrs",  # Weduwe with period
    "weduwe": "Mrs",  # Full form
}


class SalutationTrie:
    """
    Trie-based matcher for Dutch salutations.

    More efficient than a 60+ alternation regex pattern.
    Provides O(k) lookup where k is the maximum salutation length.
    """

    def __init__(self, salutations: Dict[str, Optional[str]]):
        self.root: Dict = {}
        self.salutations = salutations
        # Sort by length descending to prefer longer matches
        for key in sorted(salutations.keys(), key=len, reverse=True):
            self._insert(key.lower(), salutations[key])

    def _insert(self, key: str, value: Optional[str]) -> None:
        """Insert a salutation into the trie."""
        node = self.root
        for char in key:
            if char not in node:
                node[char] = {}
            node = node[char]
        node["_value"] = value
        node["_key"] = key

    def match_prefix(self, text: str) -> Tuple[Optional[str], Optional[str], int]:
        """
        Match the longest salutation at the start of text.

        Args:
            text: Input text to match against

        Returns:
            Tuple of (matched_key, erpnext_salutation, match_length)
            Returns (None, None, 0) if no match found
        """
        if not text:
            return None, None, 0

        text_lower = text.lower()
        node = self.root
        last_match = (None, None, 0)

        for i, char in enumerate(text_lower):
            if char not in node:
                break
            node = node[char]
            # Check if this is a complete salutation
            if "_value" in node:
                # Only accept if followed by whitespace (word boundary)
                next_pos = i + 1
                if next_pos < len(text) and text[next_pos].isspace():
                    last_match = (node["_key"], node["_value"], next_pos)

        return last_match


# Build trie for efficient salutation matching
_SALUTATION_TRIE = SalutationTrie(DUTCH_SALUTATIONS)


def extract_salutation(name: str) -> Tuple[Optional[str], str]:
    """
    Extract Dutch salutation from the beginning of a name.

    Bank statements often include salutations like "Hr M E J Eggermont"
    or "Mw S Bostelaar". This extracts the salutation and returns
    the clean name.

    Uses trie-based matching for O(k) performance instead of 60+ regex alternations.

    Args:
        name: Full name potentially starting with salutation

    Returns:
        Tuple of (erpnext_salutation, clean_name)
        - erpnext_salutation: ERPNext Salutation name (Mr, Mrs, etc.) or None
        - clean_name: Name with salutation prefix removed
    """
    if not name:
        return None, name

    matched_key, erpnext_salutation, match_end = _SALUTATION_TRIE.match_prefix(name)

    if matched_key is not None:
        # Skip the salutation and any following whitespace
        clean_name = name[match_end:].lstrip()
        return erpnext_salutation, clean_name

    return None, name


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
        text = text.replace("\r\n", "").replace("\r", "").replace("\n", "")
    result = {
        "counterparty_name": "",
        "counterparty_salutation": "",
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

    # DoS prevention: reject excessively long input that could cause regex backtracking
    if len(text) > MAX_SEPA_INPUT_LENGTH:
        import frappe

        frappe.logger().warning(f"[SEPA] Input text too long ({len(text)} chars), truncating to prevent DoS")
        text = text[:MAX_SEPA_INPUT_LENGTH]

    # Parse CNTP (Counterparty) - format: /CNTP/account/bic/name/city/country/
    # Note: Account numbers may be split across lines in MT940, creating spaces/newlines
    cntp_match = re.search(r"/CNTP/([^/]*)/([^/]*)/([^/]*)/([^/]*)?/?([^/]*)?/?", text)
    if cntp_match:
        # Clean up account number - remove any whitespace/newlines from line breaks
        account = cntp_match.group(1)
        account = re.sub(r"\s+", "", account)  # Remove all whitespace
        result["counterparty_account"] = account
        result["counterparty_bic"] = cntp_match.group(2).strip()

        # Extract salutation from counterparty name (e.g., "Hr M E J Eggermont" -> "Mr", "M E J Eggermont")
        raw_name = cntp_match.group(3).strip()
        salutation, clean_name = extract_salutation(raw_name)
        result["counterparty_name"] = sanitize_party_name(clean_name)
        result["counterparty_salutation"] = salutation or ""

    # Parse REMI (Remittance) - format: /REMI/type/text/ or /REMI/USTD//text/
    # After normalization, text has no newlines, but may have // (double slash)
    # IMPORTANT: Don't stop at "/" in text like "e/o" (Dutch "en/of" = and/or)
    # Only stop at "/" when followed by a SEPA tag name (uppercase letters)
    # Using bounded repetition {1,2000} to prevent catastrophic backtracking
    remi_match = re.search(r"/REMI/([^/]*)/+(.{1,2000}?)(?=/[A-Z]{4}/|//[A-Z]|\||\Z)", text)
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
        # ABWA overrides counterparty name if present - also extract salutation
        raw_name = abwa_match.group(1).strip()
        salutation, clean_name = extract_salutation(raw_name)
        result["counterparty_name"] = sanitize_party_name(clean_name)
        result["counterparty_salutation"] = salutation or ""

    # Alternative formats - /NAME/, /IBAN/, /BIC/
    if not result["counterparty_name"]:
        name_match = re.search(r"/NAME/([^/|]+)", text)
        if name_match:
            raw_name = name_match.group(1).strip()
            salutation, clean_name = extract_salutation(raw_name)
            result["counterparty_name"] = sanitize_party_name(clean_name)
            if not result["counterparty_salutation"]:
                result["counterparty_salutation"] = salutation or ""

    if not result["counterparty_account"]:
        iban_match = re.search(r"/IBAN/([^/|]+)", text)
        if iban_match:
            # Clean up IBAN - remove any whitespace from line breaks
            iban = re.sub(r"\s+", "", iban_match.group(1))
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
    if is_placeholder_value(name):
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
