"""
Data Integrity Utilities for eBoekhouden Integration

This module provides utilities for ensuring data integrity during imports:
- Duplicate handling with race condition protection
- PII masking for safe error logging
- Date format normalization
"""

import copy
import re
from typing import Any, Dict, Optional, Tuple

import frappe
from frappe.exceptions import DuplicateEntryError, UniqueValidationError


def insert_with_duplicate_handling(
    doc: frappe.model.document.Document,
    mutation_id_field: str = "eboekhouden_mutation_nr",
) -> Tuple[frappe.model.document.Document, bool]:
    """
    Insert document with graceful duplicate handling for race conditions.

    When two concurrent processes check for duplicates simultaneously, both may
    see "not exists" and attempt to insert. The DB unique constraint will cause
    one insert to fail. `mutation_id_field` is a unique FIELD (not the
    doctype's autoname/primary key) on every doctype this is called with
    (Journal Entry, Payment Entry, Purchase/Sales Invoice, Stock
    Reconciliation), so frappe raises `UniqueValidationError` for the
    collision, not `DuplicateEntryError` -- the two share no MRO relationship
    apart from Exception. This function handles that gracefully by fetching
    and returning the existing document (#699).

    Args:
        doc: The document to insert
        mutation_id_field: The field name containing the mutation ID (must be unique)

    Returns:
        Tuple of (document, was_duplicate):
        - document: The inserted or existing document
        - was_duplicate: True if an existing document was found, False if newly inserted

    Raises:
        UniqueValidationError: Re-raised if the duplicate can't be found (shouldn't happen)
        Other exceptions: Propagated from doc.insert()

    Example:
        doc = frappe.new_doc("Payment Entry")
        doc.eboekhouden_mutation_nr = "12345"
        # ... set other fields ...
        result_doc, was_duplicate = insert_with_duplicate_handling(doc)
        if was_duplicate:
            frappe.logger().info(f"Using existing document: {result_doc.name}")
    """
    try:
        doc.insert()
        return doc, False
    except (DuplicateEntryError, UniqueValidationError):
        # Race condition: another process inserted first
        mutation_id = getattr(doc, mutation_id_field, None)

        if not mutation_id:
            frappe.log_error(
                title="Duplicate Handling Failed",
                message=f"Duplicate/unique collision caught but {mutation_id_field} is empty on {doc.doctype}",
            )
            raise

        # Try to find the existing document
        existing_name = frappe.db.get_value(
            doc.doctype,
            {mutation_id_field: mutation_id},
            "name",
        )

        if existing_name:
            frappe.logger().info(
                f"Duplicate handled gracefully: {doc.doctype} with "
                f"{mutation_id_field}={mutation_id} already exists as {existing_name}"
            )
            existing_doc = frappe.get_doc(doc.doctype, existing_name)
            return existing_doc, True

        # Couldn't find the duplicate - this is unexpected
        frappe.log_error(
            title="Duplicate Handling Failed",
            message=f"Duplicate/unique collision caught but couldn't find existing "
            f"{doc.doctype} with {mutation_id_field}={mutation_id}",
        )
        raise


def submit_with_duplicate_handling(
    doc: frappe.model.document.Document,
    mutation_id_field: str = "eboekhouden_mutation_nr",
) -> Tuple[frappe.model.document.Document, bool]:
    """
    Insert and submit document with graceful duplicate handling.

    Similar to insert_with_duplicate_handling but also submits the document
    after successful insertion.

    Args:
        doc: The document to insert and submit
        mutation_id_field: The field name containing the mutation ID (must be unique)

    Returns:
        Tuple of (document, was_duplicate):
        - document: The inserted/submitted or existing document
        - was_duplicate: True if an existing document was found

    Example:
        doc = frappe.new_doc("Journal Entry")
        doc.eboekhouden_mutation_nr = "12345"
        # ... set other fields ...
        result_doc, was_duplicate = submit_with_duplicate_handling(doc)
    """
    result_doc, was_duplicate = insert_with_duplicate_handling(doc, mutation_id_field)

    if not was_duplicate:
        # Newly inserted, need to submit
        result_doc.submit()

    return result_doc, was_duplicate


# PII fields that should be masked in logs
PII_FIELDS = frozenset(
    [
        # Contact information
        "email",
        "e-mail",
        "emailaddress",
        "emailadres",
        "phone",
        "telefoon",
        "telefoonnummer",
        "mobile",
        "mobiel",
        "fax",
        "faxnummer",
        # Address information
        "address",
        "adres",
        "street",
        "straat",
        "straatadres",
        "postcode",
        "zipcode",
        "postalcode",
        "city",
        "stad",
        "plaats",
        "woonplaats",
        "country",
        "land",
        # Personal information
        "name",
        "naam",
        "fullname",
        "volledigenaam",
        "firstname",
        "voornaam",
        "lastname",
        "achternaam",
        "contactname",
        "contactpersoon",
        "contactemail",
        "contactmail",
        # Financial information
        "bankaccount",
        "bankrekeningnummer",
        "rekeningnummer",
        "iban",
        "bic",
        "swift",
        "bsn",
        "burgerservicenummer",  # Dutch SSN equivalent
        "kvknummer",
        "kvk",  # Chamber of Commerce number
        "btwnummer",
        "btw",
        "vatnumber",  # VAT number
    ]
)


def _should_mask_field(field_name: str) -> bool:
    """Check if a field name indicates PII content."""
    field_lower = field_name.lower().replace("_", "").replace("-", "")
    return field_lower in PII_FIELDS or any(pii in field_lower for pii in PII_FIELDS)


def _mask_value(value: Any) -> Any:
    """
    Mask a PII value while preserving some structure for debugging.

    Examples:
        "john@example.com" -> "jo***om"
        "0612345678" -> "06***78"
        "Short" -> "***"
    """
    if value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    if len(value) <= 4:
        return "***"

    # Preserve first 2 and last 2 characters
    return f"{value[:2]}***{value[-2:]}"


def _mask_dict_recursive(data: Dict[str, Any], depth: int = 0, max_depth: int = 10) -> Dict[str, Any]:
    """Recursively mask PII fields in a dictionary."""
    if depth > max_depth:
        return data

    for key in list(data.keys()):
        value = data[key]

        if isinstance(value, dict):
            data[key] = _mask_dict_recursive(value, depth + 1, max_depth)
        elif isinstance(value, list):
            data[key] = [
                _mask_dict_recursive(item, depth + 1, max_depth) if isinstance(item, dict) else item
                for item in value
            ]
        elif _should_mask_field(key):
            data[key] = _mask_value(value)

    return data


def mask_pii_in_mutation(mutation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a copy of mutation with PII fields masked for safe logging.

    This function masks personally identifiable information (PII) such as:
    - Email addresses
    - Phone numbers
    - Physical addresses
    - Bank account numbers
    - Names

    The masked version preserves the structure and partial content for debugging
    while preventing exposure of sensitive data in logs.

    Args:
        mutation: The mutation data dictionary

    Returns:
        A deep copy of the mutation with PII fields masked

    Example:
        mutation = {"email": "john@example.com", "amount": 100.0}
        masked = mask_pii_in_mutation(mutation)
        # masked = {"email": "jo***om", "amount": 100.0}
    """
    if not mutation:
        return mutation

    # Create deep copy to avoid modifying original
    masked = copy.deepcopy(mutation)
    return _mask_dict_recursive(masked)


def normalize_date(date_value: Any) -> Optional[str]:
    """
    Normalize various date formats to YYYY-MM-DD.

    Handles:
    - YYYYMMDD (eBoekhouden format): "20250110" -> "2025-01-10"
    - ISO datetime: "2025-01-10T00:00:00" -> "2025-01-10"
    - ISO datetime with timezone: "2025-01-10T00:00:00+01:00" -> "2025-01-10"
    - Already correct: "2025-01-10" -> "2025-01-10"
    - European format: "10-01-2025" -> "2025-01-10"
    - European format with slashes: "10/01/2025" -> "2025-01-10"

    Args:
        date_value: The date value in various formats

    Returns:
        The date in YYYY-MM-DD format, or None if parsing fails

    Example:
        normalize_date("20250110") -> "2025-01-10"
        normalize_date("2025-01-10T12:30:00") -> "2025-01-10"
    """
    if not date_value:
        return None

    date_str = str(date_value).strip()

    if not date_str:
        return None

    # Handle eBoekhouden YYYYMMDD format
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Handle ISO datetime format (2025-01-10T00:00:00 or with timezone)
    if "T" in date_str:
        return date_str.split("T")[0]

    # Handle already-correct YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    # Handle European format DD-MM-YYYY or DD/MM/YYYY
    european_match = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", date_str)
    if european_match:
        day, month, year = european_match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Try dateutil as fallback for other formats
    try:
        from dateutil import parser

        parsed = parser.parse(date_str)
        return parsed.date().isoformat()
    except Exception:
        pass

    # Return as-is if we can't parse it
    frappe.logger().warning(f"Could not normalize date format: {date_str}")
    return date_str


def safe_log_mutation_error(
    title: str,
    mutation: Dict[str, Any],
    error: Optional[Exception] = None,
    additional_context: Optional[str] = None,
) -> None:
    """
    Log a mutation error with PII masked for privacy compliance.

    This is the recommended way to log mutation-related errors as it ensures
    sensitive data is not exposed in error logs.

    Args:
        title: Short title for the error log
        mutation: The mutation data (will be masked)
        error: Optional exception that occurred
        additional_context: Optional additional context string

    Example:
        try:
            process_mutation(mutation)
        except Exception as e:
            safe_log_mutation_error(
                "Payment Processing Failed",
                mutation,
                e,
                "Failed during bank reconciliation step"
            )
    """
    masked_mutation = mask_pii_in_mutation(mutation)

    message_parts = []

    if additional_context:
        message_parts.append(additional_context)

    if error:
        message_parts.append(f"Error: {type(error).__name__}: {str(error)}")

    message_parts.append(f"Mutation (PII masked):\n{frappe.as_json(masked_mutation, indent=2)}")

    frappe.log_error(
        title=title,
        message="\n\n".join(message_parts),
    )
