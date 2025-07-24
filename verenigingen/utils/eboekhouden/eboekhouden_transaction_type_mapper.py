"""
E-Boekhouden Transaction Type Mapper
Maps native E-boekhouden transaction types directly to ERPNext document types
Replaces complex pattern matching with simple direct mapping
"""

from typing import Any, Dict, Optional, Union

import frappe
from frappe import _

# Direct mapping of E-boekhouden transaction types to ERPNext document types
TRANSACTION_TYPE_MAPPING = {
    # Dutch transaction types from E-boekhouden SOAP API
    "Factuur ontvangen": "Purchase Invoice",
    "Factuur verstuurd": "Sales Invoice",
    "Factuurbetaling ontvangen": "Payment Entry",
    "Factuurbetaling verstuurd": "Payment Entry",
    "Geld ontvangen": "Journal Entry",
    "Geld verstuurd": "Journal Entry",
    "Memoriaal": "Journal Entry",
    # English variants (if E-boekhouden provides them)
    "Invoice received": "Purchase Invoice",
    "Invoice sent": "Sales Invoice",
    "Invoice payment received": "Payment Entry",
    "Invoice payment sent": "Payment Entry",
    "Money received": "Journal Entry",
    "Money sent": "Journal Entry",
    "Memorial": "Journal Entry",
    # Normalized SOAP types (from normalize_mutation_types.py)
    "FactuurOntvangen": "Purchase Invoice",
    "FactuurVerstuurd": "Sales Invoice",
    "FactuurbetalingOntvangen": "Payment Entry",
    "FactuurbetalingVerstuurd": "Payment Entry",
    "GeldOntvangen": "Journal Entry",
    "GeldUitgegeven": "Journal Entry",
    "Memoriaal": "Journal Entry",
    "BeginBalans": "Journal Entry",
    # Numeric types from REST API
    0: "Journal Entry",  # Opening Balance
    1: "Purchase Invoice",  # Invoice received
    2: "Sales Invoice",  # Invoice sent
    3: "Payment Entry",  # Invoice payment received (for Sales Invoice)
    4: "Payment Entry",  # Invoice payment sent (for Purchase Invoice)
    5: "Journal Entry",  # Money received
    6: "Journal Entry",  # Money sent
    7: "Journal Entry",  # General journal entry
}


def get_erpnext_document_type(eboekhouden_transaction_type: Union[str, int, None]) -> str:
    """
    Get ERPNext document type based on E-boekhouden transaction type

    Args:
        eboekhouden_transaction_type: The Soort/MutatieType from E-boekhouden

    Returns:
        ERPNext document type (Sales Invoice, Purchase Invoice, Journal Entry, Payment Entry)
    """
    if not eboekhouden_transaction_type:
        return "Journal Entry"  # Default fallback

    # Direct lookup
    doc_type = TRANSACTION_TYPE_MAPPING.get(eboekhouden_transaction_type)

    if doc_type:
        return doc_type

    # Check if it contains key patterns (fallback for variations)
    transaction_lower = eboekhouden_transaction_type.lower()

    if "factuur ontvangen" in transaction_lower or "invoice received" in transaction_lower:
        return "Purchase Invoice"
    elif "factuur verstuurd" in transaction_lower or "invoice sent" in transaction_lower:
        return "Sales Invoice"
    elif "factuurbetaling" in transaction_lower or "invoice payment" in transaction_lower:
        return "Payment Entry"
    elif "memoriaal" in transaction_lower or "memorial" in transaction_lower:
        return "Journal Entry"
    else:
        # Default to Journal Entry for unknown types
        return "Journal Entry"


def get_payment_entry_reference_type(eboekhouden_transaction_type: Union[str, int, None]) -> Optional[str]:
    """
    For Payment Entries, determine what type of invoice it's paying

    Args:
        eboekhouden_transaction_type: The Soort/MutatieType from E-boekhouden (text or numeric)

    Returns:
        "Sales Invoice" or "Purchase Invoice" or None
    """
    if not eboekhouden_transaction_type and eboekhouden_transaction_type != 0:
        return None

    # Handle numeric types from REST API
    if isinstance(eboekhouden_transaction_type, (int, float)):
        if eboekhouden_transaction_type == 3:  # Invoice payment received
            return "Sales Invoice"
        elif eboekhouden_transaction_type == 4:  # Invoice payment sent
            return "Purchase Invoice"
        return None

    # Handle text types from SOAP API
    transaction_lower = str(eboekhouden_transaction_type).lower()

    if "ontvangen" in transaction_lower or "received" in transaction_lower:
        # Payment received = payment for Sales Invoice
        return "Sales Invoice"
    elif "verstuurd" in transaction_lower or "sent" in transaction_lower:
        # Payment sent = payment for Purchase Invoice
        return "Purchase Invoice"

    return None


@frappe.whitelist()
def get_transaction_type_mapping() -> Dict[str, Any]:
    """
    Get all available transaction type mappings
    For display in UI or debugging
    """
    return {
        "mappings": TRANSACTION_TYPE_MAPPING,
        "description": _("Direct mapping from E-boekhouden transaction types to ERPNext document types"),
    }


def simplify_migration_process(mutation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simplified migration process using native transaction types

    Args:
        mutation_data: Mutation data from E-boekhouden with 'Soort' (SOAP) or 'type' (REST) field

    Returns:
        Dict with document_type and additional mapping info
    """
    # Try multiple field names - SOAP uses 'Soort', REST uses 'type' - modernized lookup
    TRANSACTION_TYPE_FIELDS = ["Soort", "MutatieType", "type"]
    transaction_type = None

    for field in TRANSACTION_TYPE_FIELDS:
        value = mutation_data.get(field)
        if value is not None:  # Explicit None check to allow 0 values
            transaction_type = value
            break

    if not transaction_type and transaction_type != 0:  # 0 is valid for opening balance
        frappe.log_error(
            "No transaction type found in mutation {mutation_data.get('MutatieNr') or mutation_data.get('id', 'Unknown')}",
            "E-Boekhouden Migration",
        )
        return {
            "document_type": "Journal Entry",
            "confidence": "low",
            "reason": "No transaction type provided",
        }

    doc_type = get_erpnext_document_type(transaction_type)

    result = {
        "document_type": doc_type,
        "transaction_type": transaction_type,
        "confidence": "high",
        "reason": "Direct mapping from E-boekhouden type: {transaction_type}",
    }

    # Add payment reference info if it's a payment entry
    if doc_type == "Payment Entry":
        result["reference_type"] = get_payment_entry_reference_type(transaction_type)
        result["needs_invoice_link"] = True

    return result
