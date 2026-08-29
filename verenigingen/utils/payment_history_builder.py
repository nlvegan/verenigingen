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

    VALID_PAYMENT_STATUSES = {
        "Draft",
        "Unpaid",
        "Partially Paid",
        "Paid",
        "Credited",
        "Partially Credited",
        "Overdue",
        "Cancelled",
    }

    # transaction_type values that mark a row as a credit note. A set of exact values
    # rather than a substring test: `transaction_type` is one of four literals derived
    # from two booleans, so an exact match is simply the honest spelling of the check
    # and it stays correct if a fifth literal is ever added.
    CREDIT_NOTE_TRANSACTION_TYPES = {"Credit Note", "Membership Credit Note"}

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
        # Find linked payment entries
        payment_entries = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_doc.name},
            fields=["parent", "allocated_amount"],
        )

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

        row = {
            "invoice_name": invoice_doc.name,
            "is_return": getattr(invoice_doc, "is_return", 0),
            "is_membership_invoice": getattr(invoice_doc, "is_membership_invoice", 0),
            "membership": getattr(invoice_doc, "membership", None),  # ast-skip: custom field
            "posting_date": invoice_doc.posting_date,
            "due_date": invoice_doc.due_date,
            "grand_total": invoice_doc.grand_total,
            "outstanding_amount": invoice_doc.outstanding_amount,
            "invoice_status": invoice_doc.status,
            "docstatus": invoice_doc.docstatus,
            "coverage_start_date": coverage_start_date,
            "coverage_end_date": coverage_end_date,
            "paid_amount": paid_amount,
            "reconciled": reconciled,
            "payment_entry": payment_entry,
            "payment_date": payment_date,
            "payment_method": payment_method,
            "has_mandate": has_mandate,
            "sepa_mandate": sepa_mandate,
            "mandate_status": mandate_status,
            "mandate_reference": mandate_reference,
        }
        return PaymentHistoryEntryBuilder.build_from_query_row(row)

    @staticmethod
    def build_from_query_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a payment history entry from a canonical row dict.

        This is THE single invoice-row constructor. Callers (incremental builder
        via build_from_invoice_doc, and the batch rebuild) assemble the canonical
        row schema and pass it here so every writer emits identical rows.
        """
        from verenigingen.utils import determine_payment_status

        # Classifier: the unconditionally-set boolean (NOT the conditional link).
        is_membership = bool(row.get("is_membership_invoice"))
        membership = row.get("membership")
        # A credit note is labelled as one so a reader can tell which rows REDUCED what
        # the member owed. Present-but-indistinguishable is not trackable (#653).
        if row.get("is_return"):
            transaction_type = "Membership Credit Note" if is_membership else "Credit Note"
        else:
            transaction_type = "Membership Invoice" if is_membership else "Regular Invoice"
        if is_membership and membership:
            reference_doctype = "Membership"
            reference_name = membership
        else:
            reference_doctype = None
            reference_name = None

        # Shared payment-status derivation (same util the service uses).
        status_shim = frappe._dict(
            docstatus=row.get("docstatus"),
            status=row.get("invoice_status"),
            outstanding_amount=flt(row.get("outstanding_amount")),
            grand_total=flt(row.get("grand_total")),
        )
        payment_status = determine_payment_status(status_shim, flt(row.get("paid_amount", 0)))

        payment_entry = row.get("payment_entry")
        sepa_mandate = row.get("sepa_mandate")

        return {
            "invoice": row["invoice_name"],
            "invoice_doctype": "Sales Invoice",  # Required for Dynamic Link
            "posting_date": row.get("posting_date"),
            "due_date": row.get("due_date"),
            "coverage_start_date": row.get("coverage_start_date"),
            "coverage_end_date": row.get("coverage_end_date"),
            "transaction_type": transaction_type,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "amount": flt(row.get("grand_total")),
            "outstanding_amount": flt(row.get("outstanding_amount")),
            "status": row.get("invoice_status"),
            "payment_status": payment_status,
            "payment_date": row.get("payment_date"),
            "payment_entry": payment_entry,
            "payment_entry_doctype": "Payment Entry" if payment_entry else None,
            "payment_method": row.get("payment_method"),
            "paid_amount": flt(row.get("paid_amount", 0)),
            "reconciled": 1 if row.get("reconciled") else 0,
            "has_mandate": 1 if row.get("has_mandate") else 0,
            "sepa_mandate": sepa_mandate,
            "sepa_mandate_doctype": "SEPA Mandate" if sepa_mandate else None,
            "mandate_status": row.get("mandate_status"),
            "mandate_reference": row.get("mandate_reference"),
        }

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

        # Validate amounts. A credit note's `amount` is negative by construction -- a
        # return Sales Invoice has grand_total < 0 -- and its `outstanding_amount` is
        # negative too when `update_outstanding_for_self` is set. Refusing those made
        # `build_payment_history_entry` return None for EVERY credit note, and the
        # caller answered the rejection with a minimal entry stamped "Draft" (#653).
        #
        # For `amount` the relaxation is a sign RULE, not an exemption: an ordinary
        # invoice still may not be negative, and a credit note may not be positive.
        #
        # For `outstanding_amount` it IS an exemption, deliberately: a credit note
        # booked against the original carries 0, one booked against itself carries a
        # negative, and one partly consumed carries something in between -- there is no
        # single sign to enforce, so enforcing one would reject valid rows. Stated
        # rather than left to look symmetric.
        #
        # `paid_amount` stays unconditional -- money received is never negative on
        # either kind.
        is_credit_note = (
            entry.get("transaction_type") in PaymentHistoryEntryBuilder.CREDIT_NOTE_TRANSACTION_TYPES
        )

        if entry.get("amount") is not None:
            if is_credit_note and entry["amount"] > 0:
                errors.append("a credit note's amount must not be positive")
            elif not is_credit_note and entry["amount"] < 0:
                errors.append("amount cannot be negative")

        if (
            entry.get("outstanding_amount") is not None
            and not is_credit_note
            and entry["outstanding_amount"] < 0
        ):
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
