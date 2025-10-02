"""
Payment History Entry Builder

Provides a single source of truth for building Member Payment History entries.
Used by both individual updates and bulk optimized updates to ensure consistency.
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, getdate


class PaymentHistoryEntryBuilder:
    """
    Builds Member Payment History entries with consistent structure and validation.

    This ensures that individual updates (_build_payment_history_entry) and
    bulk updates (optimized_queries) produce identical data structures.
    """

    # Define the expected schema based on Member Payment History DocType
    REQUIRED_FIELDS = {"invoice", "posting_date", "amount", "outstanding_amount", "payment_status"}

    OPTIONAL_FIELDS = {
        "due_date",
        "coverage_start_date",
        "coverage_end_date",
        "transaction_type",
        "reference_doctype",
        "reference_name",
        "status",
        "payment_date",
        "payment_entry",
        "payment_method",
        "paid_amount",
        "reconciled",
        "has_mandate",
        "sepa_mandate",
        "mandate_status",
        "mandate_reference",
        "notes",
    }

    VALID_PAYMENT_STATUSES = {"Draft", "Unpaid", "Partially Paid", "Paid", "Overdue", "Cancelled"}

    @staticmethod
    def build_from_invoice_doc(invoice_doc, member_doc=None, mandate_cache=None) -> Dict[str, Any]:
        """
        Build a payment history entry from a Sales Invoice document.

        Args:
            invoice_doc: Sales Invoice document
            member_doc: Optional Member document (for efficiency)
            mandate_cache: Optional dict to cache SEPA mandate lookups (prevents N+1 queries)

        Returns:
            Dictionary with payment history entry data
        """
        # Determine transaction type and reference
        transaction_type = "Regular Invoice"
        reference_doctype = None
        reference_name = None

        if hasattr(invoice_doc, "membership") and invoice_doc.membership:
            transaction_type = "Membership Invoice"
            reference_doctype = "Membership"
            reference_name = invoice_doc.membership

        # Find linked payment entries
        payment_entries = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_doc.name},
            fields=["parent", "allocated_amount"],
        )

        payment_status = "Unpaid"
        payment_date = None
        payment_entry = None
        payment_method = None
        paid_amount = 0
        reconciled = 0

        if payment_entries:
            for pe in payment_entries:
                paid_amount += float(pe.allocated_amount or 0)

            most_recent_payment = frappe.get_all(
                "Payment Entry",
                filters={
                    "name": ["in", [pe.parent for pe in payment_entries]],
                    "docstatus": ["!=", 2],
                },
                fields=["name", "posting_date", "mode_of_payment"],
                order_by="posting_date desc",
                limit=1,
            )

            if most_recent_payment:
                payment_entry = most_recent_payment[0].name
                payment_date = most_recent_payment[0].posting_date
                payment_method = most_recent_payment[0].mode_of_payment
                reconciled = 1

        # Determine payment status
        # ✅ FIX: Handle draft invoices explicitly
        if invoice_doc.docstatus == 0:
            payment_status = "Draft"
        elif invoice_doc.status == "Paid" or invoice_doc.outstanding_amount <= 0:
            payment_status = "Paid"
        elif invoice_doc.status == "Overdue":
            payment_status = "Overdue"
        elif invoice_doc.status == "Cancelled":
            payment_status = "Cancelled"
        elif paid_amount > 0 and paid_amount < invoice_doc.grand_total:
            payment_status = "Partially Paid"

        # Get coverage dates if available
        # ✅ FIX: Validate fields exist in DocType per CLAUDE.md guidelines
        coverage_start_date = None
        coverage_end_date = None

        try:
            sales_invoice_meta = frappe.get_meta("Sales Invoice")
            if sales_invoice_meta.has_field("custom_coverage_start_date"):
                coverage_start_date = invoice_doc.custom_coverage_start_date
            if sales_invoice_meta.has_field("custom_coverage_end_date"):
                coverage_end_date = invoice_doc.custom_coverage_end_date
        except Exception as e:
            frappe.log_error(
                f"Error accessing coverage date fields: {str(e)}", "Payment History Field Access"
            )

        # SEPA mandate information
        # ✅ FIX: Use cache to prevent N+1 queries
        has_mandate = 0
        sepa_mandate = None
        mandate_status = None
        mandate_reference = None

        if member_doc:
            # Initialize cache if not provided
            if mandate_cache is None:
                mandate_cache = {}

            # Check cache first
            if member_doc.name not in mandate_cache:
                mandate_cache[member_doc.name] = frappe.db.get_value(
                    "SEPA Mandate",
                    {
                        "member": member_doc.name,
                        "status": "Active",
                        "is_active": 1,
                        "used_for_memberships": 1,
                    },
                    ["name", "status", "mandate_id"],
                    as_dict=True,
                )

            default_mandate = mandate_cache[member_doc.name]

            if default_mandate:
                has_mandate = 1
                sepa_mandate = default_mandate.name
                mandate_status = default_mandate.status
                mandate_reference = default_mandate.mandate_id

        # Build the entry dictionary
        entry = {
            "invoice": invoice_doc.name,
            "posting_date": invoice_doc.posting_date,
            "due_date": invoice_doc.due_date,
            "coverage_start_date": coverage_start_date,
            "coverage_end_date": coverage_end_date,
            "transaction_type": transaction_type,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "amount": invoice_doc.grand_total,
            "outstanding_amount": invoice_doc.outstanding_amount,
            "status": invoice_doc.status,
            "payment_status": payment_status,
            "payment_date": payment_date,
            "payment_entry": payment_entry,
            "payment_method": payment_method,
            "paid_amount": paid_amount,
            "reconciled": reconciled,
            "has_mandate": has_mandate,
            "sepa_mandate": sepa_mandate,
            "mandate_status": mandate_status,
            "mandate_reference": mandate_reference,
        }

        return entry

    @staticmethod
    def build_from_query_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a payment history entry from a database query row.

        Used by optimized bulk queries where we already have the data
        and don't need to fetch the full document.

        Args:
            row: Dictionary with invoice data from query

        Returns:
            Dictionary with payment history entry data
        """
        # Determine transaction type and reference
        if row.get("membership_id"):
            transaction_type = "Membership Invoice"
            reference_doctype = "Membership"
            reference_name = row["membership_id"]
        else:
            transaction_type = "Regular Invoice"
            reference_doctype = "Sales Invoice"
            reference_name = row["invoice_name"]

        entry = {
            "invoice": row["invoice_name"],
            "posting_date": row["posting_date"],
            "due_date": row.get("due_date"),
            "transaction_type": transaction_type,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "amount": flt(row["grand_total"]),
            "outstanding_amount": flt(row["outstanding_amount"]),
            "status": row.get("invoice_status"),
            "payment_status": row.get("payment_status", "Unpaid"),
            "payment_date": row.get("payment_date"),
            "paid_amount": flt(row.get("allocated_amount", 0)),
        }

        return entry

    @staticmethod
    def validate_entry(entry: Dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate a payment history entry against schema and business rules.

        Args:
            entry: Payment history entry dictionary

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        for field in PaymentHistoryEntryBuilder.REQUIRED_FIELDS:
            if field not in entry or entry[field] is None:
                errors.append(f"Missing required field: {field}")

        # Validate payment status
        if entry.get("payment_status") not in PaymentHistoryEntryBuilder.VALID_PAYMENT_STATUSES:
            errors.append(f"Invalid payment_status: {entry.get('payment_status')}")

        # Validate amounts
        if entry.get("amount") is not None and entry["amount"] < 0:
            errors.append("amount cannot be negative")

        if entry.get("outstanding_amount") is not None and entry["outstanding_amount"] < 0:
            errors.append("outstanding_amount cannot be negative")

        if entry.get("paid_amount") is not None and entry["paid_amount"] < 0:
            errors.append("paid_amount cannot be negative")

        # Validate dates
        if entry.get("posting_date"):
            try:
                getdate(entry["posting_date"])
            except Exception:
                errors.append(f"Invalid posting_date: {entry.get('posting_date')}")

        # Validate reference consistency
        if entry.get("reference_doctype") and not entry.get("reference_name"):
            errors.append("reference_name required when reference_doctype is set")

        if entry.get("reference_name") and not entry.get("reference_doctype"):
            errors.append("reference_doctype required when reference_name is set")

        return (len(errors) == 0, errors)


def build_payment_history_entry(
    invoice_doc, member_doc=None, validate=True, mandate_cache=None
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to build and optionally validate a payment history entry.

    Args:
        invoice_doc: Sales Invoice document
        member_doc: Optional Member document
        validate: Whether to validate the entry (default True)
        mandate_cache: Optional dict to cache SEPA mandate lookups

    Returns:
        Payment history entry dict, or None if validation fails
    """
    entry = PaymentHistoryEntryBuilder.build_from_invoice_doc(invoice_doc, member_doc, mandate_cache)

    if validate:
        is_valid, errors = PaymentHistoryEntryBuilder.validate_entry(entry)
        if not is_valid:
            frappe.log_error(
                f"Payment history entry validation failed for {invoice_doc.name}: {', '.join(errors)}",
                "Payment History Validation Error",
            )
            return None

    return entry


def build_payment_history_entry_from_query(row: Dict[str, Any], validate=True) -> Optional[Dict[str, Any]]:
    """
    Convenience function to build and optionally validate from query row.

    Args:
        row: Query result row
        validate: Whether to validate the entry (default True)

    Returns:
        Payment history entry dict, or None if validation fails
    """
    entry = PaymentHistoryEntryBuilder.build_from_query_row(row)

    if validate:
        is_valid, errors = PaymentHistoryEntryBuilder.validate_entry(entry)
        if not is_valid:
            frappe.log_error(
                f"Payment history entry validation failed for {row.get('invoice_name')}: {', '.join(errors)}",
                "Payment History Validation Error",
            )
            return None

    return entry
