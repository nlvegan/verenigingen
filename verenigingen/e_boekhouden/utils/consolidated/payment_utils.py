"""
Consolidated payment utilities for E-Boekhouden integration.

This module provides the canonical interface for payment entry creation,
decoupling processors from the monolith migration file.

Uses PaymentEntryHandler for:
- Proper bank account mapping from ledger IDs
- Multi-invoice payment support
- Automatic payment reconciliation
"""

from typing import Any, Dict, List, Optional

import frappe


def create_payment_entry(
    mutation: Dict[str, Any],
    company: str,
    cost_center: str,
    debug_info: Optional[List[str]] = None,
) -> Optional[frappe.model.document.Document]:
    """
    Create Payment Entry from E-Boekhouden mutation.

    This function wraps the PaymentEntryHandler to provide:
    - Proper bank account mapping from ledger IDs
    - Multi-invoice payment support with comma-separated invoice numbers
    - Automatic payment reconciliation
    - Comprehensive error handling and logging

    Args:
        mutation: E-Boekhouden mutation data dict containing:
            - id: Mutation ID
            - type: Mutation type (3=Customer Payment, 4=Supplier Payment)
            - amount: Payment amount
            - ledgerId: Bank account ledger ID
            - invoiceNumber: Invoice reference(s)
            - date: Posting date
            - description: Payment description
            - rows: Optional detail rows
        company: Company name for the Payment Entry
        cost_center: Default cost center
        debug_info: Optional list to append debug messages

    Returns:
        Payment Entry document if successful, None if creation fails

    Raises:
        frappe.ValidationError if critical errors occur (e.g., missing ledger mapping)
    """
    if debug_info is None:
        debug_info = []

    from verenigingen.e_boekhouden.utils.eboekhouden_payment_import import (
        create_payment_entry as _create_payment_entry_impl,
    )

    mutation_id = mutation.get("id")
    debug_info.append(f"Creating Payment Entry for mutation {mutation_id} via consolidated payment_utils")

    try:
        payment_name = _create_payment_entry_impl(mutation, company, cost_center, debug_info)

        if payment_name:
            return frappe.get_doc("Payment Entry", payment_name)
        else:
            error_msg = (
                f"Payment creation returned None for mutation {mutation_id}. "
                f"Check debug logs for details."
            )
            debug_info.append(f"ERROR: {error_msg}")
            raise frappe.ValidationError(error_msg)

    except frappe.ValidationError:
        # Re-raise validation errors (already logged)
        raise
    except Exception as e:
        error_msg = f"Payment creation failed for mutation {mutation_id}: {str(e)}"
        debug_info.append(f"ERROR: {error_msg}")
        frappe.log_error(error_msg, "Consolidated Payment Utils")
        raise frappe.ValidationError(error_msg)


def create_payment_entry_or_none(
    mutation: Dict[str, Any],
    company: str,
    cost_center: str,
    debug_info: Optional[List[str]] = None,
) -> Optional[frappe.model.document.Document]:
    """
    Create Payment Entry from mutation, returning None on failure.

    Same as create_payment_entry() but returns None instead of raising
    on non-critical failures. Use when payment creation failure should
    not halt processing.

    Args:
        mutation: E-Boekhouden mutation data
        company: Company name
        cost_center: Default cost center
        debug_info: Optional list to append debug messages

    Returns:
        Payment Entry document if successful, None on any failure
    """
    if debug_info is None:
        debug_info = []

    try:
        return create_payment_entry(mutation, company, cost_center, debug_info)
    except Exception as e:
        debug_info.append(f"Payment creation failed (non-fatal): {str(e)}")
        return None
