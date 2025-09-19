"""
Bank Reconciliation Report

Provides detailed bank reconciliation report with transaction matching
and unreconciled item identification.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
    """
    Execute bank reconciliation report

    Args:
        filters: Report filters (company, from_date, to_date)

    Returns:
        Tuple of (columns, data)
    """
    if not filters:
        filters = {}

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Get report columns"""
    return [
        {"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
        {"fieldname": "transaction_type", "label": _("Type"), "fieldtype": "Data", "width": 120},
        {"fieldname": "reference", "label": _("Reference"), "fieldtype": "Data", "width": 150},
        {"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 200},
        {"fieldname": "debit", "label": _("Debit"), "fieldtype": "Currency", "width": 100},
        {"fieldname": "credit", "label": _("Credit"), "fieldtype": "Currency", "width": 100},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {
            "fieldname": "payment_entry",
            "label": _("Payment Entry"),
            "fieldtype": "Link",
            "options": "Payment Entry",
            "width": 150,
        },
    ]


def get_data(filters):
    """Get report data"""
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    if not company:
        return []

    data = []

    # Get bank transactions
    bank_filters = {"company": company, "docstatus": 1}

    if from_date:
        bank_filters["date"] = [">=", from_date]
    if to_date:
        if from_date:
            bank_filters["date"] = ["between", [from_date, to_date]]
        else:
            bank_filters["date"] = ["<=", to_date]

    bank_transactions = frappe.get_all(
        "Bank Transaction",
        filters=bank_filters,
        fields=[
            "name",
            "date",
            "description",
            "deposit",
            "withdrawal",
            "reference_number",
            "status",
            "payment_entry",
        ],
        order_by="date",
    )

    # Add bank transactions to data
    for bt in bank_transactions:
        data.append(
            {
                "date": bt.date,
                "transaction_type": "Bank Transaction",
                "reference": bt.reference_number or bt.name,
                "description": bt.description or "",
                "debit": bt.withdrawal or 0,
                "credit": bt.deposit or 0,
                "status": bt.status,
                "payment_entry": bt.payment_entry or "",
            }
        )

    # Get payment entries in date range
    payment_filters = {"company": company, "docstatus": 1}

    if from_date:
        payment_filters["posting_date"] = [">=", from_date]
    if to_date:
        if from_date:
            payment_filters["posting_date"] = ["between", [from_date, to_date]]
        else:
            payment_filters["posting_date"] = ["<=", to_date]

    payment_entries = frappe.get_all(
        "Payment Entry",
        filters=payment_filters,
        fields=["name", "posting_date", "payment_type", "party", "paid_amount", "reference_no", "remarks"],
        order_by="posting_date",
    )

    # Add payment entries to data
    for pe in payment_entries:
        # Check if this payment is already linked to a bank transaction
        linked_bank_trans = any(bt.get("payment_entry") == pe.name for bt in bank_transactions)

        status = "Reconciled" if linked_bank_trans else "Unmatched"

        data.append(
            {
                "date": pe.posting_date,
                "transaction_type": f"Payment Entry ({pe.payment_type})",
                "reference": pe.reference_no or pe.name,
                "description": f"{pe.party}: {pe.remarks or ''}",
                "debit": pe.paid_amount if pe.payment_type == "Pay" else 0,
                "credit": pe.paid_amount if pe.payment_type == "Receive" else 0,
                "status": status,
                "payment_entry": pe.name,
            }
        )

    # Sort by date
    data.sort(key=lambda x: x["date"])

    return data
