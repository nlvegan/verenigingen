"""
Overpayment detection and handling for E-Boekhouden imports

Detects patterns where overpayments are corrected with subsequent payments,
and handles them as unallocated payment entries to avoid double allocation.
"""

from datetime import timedelta
from typing import Dict, List, Optional

import frappe
from frappe.utils import flt, getdate


def is_potential_overpayment_correction(mutation: Dict, debug_log: List[str]) -> bool:
    """
    Check if this payment might be a correction for a previous overpayment.

    Patterns to detect:
    1. Same invoice reference as a recent larger payment
    2. Amount is close to (but less than) a previous payment
    3. Within a few days of the original payment
    """
    # Only check for customer payments (Type 3)
    if mutation.get("type") != 3:
        return False

    invoice_numbers = extract_invoice_numbers(mutation)
    if not invoice_numbers:
        return False

    amount = abs(flt(mutation.get("amount", 0)))
    posting_date = getdate(mutation.get("date"))

    # Look for recent payments to the same invoice(s)
    for invoice_num in invoice_numbers:
        recent_payments = find_recent_payments_to_invoice(
            invoice_num, posting_date, days_back=7  # Check payments within last week
        )

        for payment in recent_payments:
            # Check if this could be a correction
            # Correction amount is typically slightly less than the original overpayment
            if payment["amount"] > amount and payment["amount"] - amount < payment["amount"] * 0.1:
                debug_log.append(
                    f"Detected potential overpayment correction: "
                    f"Original payment {payment['mutation_nr']} of {payment['amount']} "
                    f"followed by {amount}"
                )

                # Check if the invoice is already overpaid
                invoice_status = check_invoice_payment_status(invoice_num)
                if invoice_status and invoice_status["outstanding_amount"] <= 0:
                    debug_log.append(
                        f"Invoice {invoice_num} already fully paid/overpaid "
                        f"(outstanding: {invoice_status['outstanding_amount']})"
                    )
                    return True

    return False


def extract_invoice_numbers(mutation: Dict) -> List[str]:
    """Extract invoice numbers from mutation data"""
    invoice_numbers = []

    # Check rows for invoice numbers
    for row in mutation.get("rows", []):
        if row.get("invoiceNumber"):
            invoice_numbers.append(row["invoiceNumber"])

    # Also check mutation-level invoice number
    if mutation.get("invoiceNumber"):
        invoice_numbers.append(mutation["invoiceNumber"])

    return list(set(invoice_numbers))  # Remove duplicates


def find_recent_payments_to_invoice(invoice_num: str, before_date, days_back: int = 7) -> List[Dict]:
    """Find recent payments linked to the same invoice"""
    start_date = before_date - timedelta(days=days_back)

    # First check by E-Boekhouden invoice number
    payments = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.paid_amount as amount,
            pe.posting_date,
            pe.eboekhouden_mutation_nr as mutation_nr
        FROM `tabPayment Entry` pe
        WHERE pe.eboekhouden_invoice_number = %s
        AND pe.posting_date BETWEEN %s AND %s
        AND pe.docstatus = 1
        ORDER BY pe.posting_date DESC
    """,
        (invoice_num, start_date, before_date),
        as_dict=True,
    )

    # Also check payment entry references
    if not payments:
        payments = frappe.db.sql(
            """
            SELECT DISTINCT
                pe.name,
                pe.paid_amount as amount,
                pe.posting_date,
                pe.eboekhouden_mutation_nr as mutation_nr
            FROM `tabPayment Entry` pe
            JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
            JOIN `tabSales Invoice` si ON si.name = per.reference_name
            WHERE si.eboekhouden_invoice_number = %s
            AND pe.posting_date BETWEEN %s AND %s
            AND pe.docstatus = 1
            ORDER BY pe.posting_date DESC
        """,
            (invoice_num, start_date, before_date),
            as_dict=True,
        )

    return payments


def check_invoice_payment_status(invoice_num: str) -> Optional[Dict]:
    """Check the payment status of an invoice"""
    invoice = frappe.db.get_value(
        "Sales Invoice",
        {"eboekhouden_invoice_number": invoice_num, "docstatus": 1},
        ["name", "grand_total", "outstanding_amount", "status"],
        as_dict=True,
    )

    return invoice


def create_unallocated_payment_entry(
    mutation: Dict, party: str, company: str, cost_center: str, debug_log: List[str]
) -> Optional[str]:
    """
    Create an unallocated payment entry for overpayment corrections.
    This avoids double allocation issues.
    """
    try:
        from frappe.utils import flt, getdate

        pe = frappe.new_doc("Payment Entry")
        pe.company = company
        pe.cost_center = cost_center
        pe.posting_date = getdate(mutation.get("date"))
        pe.payment_type = "Receive"
        pe.party_type = "Customer"
        pe.party = party

        # Calculate amount
        amount = abs(flt(mutation.get("amount", 0)))
        if mutation.get("rows"):
            row_amounts = [abs(flt(row.get("amount", 0))) for row in mutation["rows"]]
            if row_amounts:
                amount = sum(row_amounts)

        pe.paid_amount = amount
        pe.received_amount = amount

        # Set accounts
        pe.paid_from = "13900 - Te ontvangen bedragen - NVV"  # Debtors account
        pe.paid_to = "10440 - Triodos - 19.83.96.716 - Algemeen - NVV"  # Bank account

        # Add reference info but no invoice allocation
        pe.reference_no = f"EBH-{mutation.get('id', '')}"
        pe.reference_date = pe.posting_date

        # Store E-Boekhouden info
        pe.eboekhouden_mutation_nr = str(mutation.get("id", ""))

        invoice_nums = extract_invoice_numbers(mutation)
        if invoice_nums:
            pe.remarks = f"Overpayment correction for invoice(s): {', '.join(invoice_nums)}. Manual reconciliation required."
        else:
            pe.remarks = "Unallocated payment - possible overpayment correction"

        # Save without allocating to any invoices
        pe.save()
        pe.submit()

        debug_log.append(f"Created unallocated payment entry {pe.name} for mutation {mutation.get('id')}")
        return pe.name

    except Exception as e:
        debug_log.append(f"Error creating unallocated payment entry: {str(e)}")
        return None
