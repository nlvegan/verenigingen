"""
Bank Reconciliation Utilities

Provides functionality for bank reconciliation, transaction matching,
and unreconciled transaction management.
"""

from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def get_unreconciled_transactions(company: str, from_date: str = None, to_date: str = None) -> List[Dict]:
    """
    Get all unreconciled bank transactions for a company

    Args:
        company: Company name
        from_date: Optional start date filter
        to_date: Optional end date filter

    Returns:
        List of unreconciled transactions
    """
    filters = {"company": company, "status": "Unreconciled", "docstatus": 1}

    if from_date:
        filters["date"] = [">=", from_date]
    if to_date:
        if from_date:
            filters["date"] = ["between", [from_date, to_date]]
        else:
            filters["date"] = ["<=", to_date]

    unreconciled = frappe.get_all(
        "Bank Transaction",
        filters=filters,
        fields=[
            "name",
            "date",
            "description",
            "deposit",
            "withdrawal",
            "currency",
            "bank_account",
            "reference_number",
            "status",
        ],
        order_by="date desc",
    )

    # Add calculated amount field
    for transaction in unreconciled:
        transaction["amount"] = transaction.get("deposit", 0) or -transaction.get("withdrawal", 0)

    return unreconciled


def find_matching_payment_entries(bank_transaction: Dict) -> List[Dict]:
    """
    Find potentially matching payment entries for a bank transaction

    Args:
        bank_transaction: Bank transaction data

    Returns:
        List of potentially matching payment entries
    """
    amount = bank_transaction.get("amount", 0)
    date = bank_transaction.get("date")

    # Search for payment entries within date range and amount
    date_from = add_days(date, -7)  # 7 days before
    date_to = add_days(date, 7)  # 7 days after

    filters = {"docstatus": 1, "posting_date": ["between", [date_from, date_to]]}

    if amount > 0:
        # Credit transaction - look for receive payments
        filters.update(
            {
                "payment_type": "Receive",
                "paid_amount": ["between", [amount * 0.95, amount * 1.05]],  # 5% tolerance
            }
        )
    else:
        # Debit transaction - look for pay payments
        filters.update(
            {"payment_type": "Pay", "paid_amount": ["between", [abs(amount) * 0.95, abs(amount) * 1.05]]}
        )

    payment_entries = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=[
            "name",
            "posting_date",
            "payment_type",
            "party_type",
            "party",
            "paid_amount",
            "reference_no",
            "remarks",
        ],
        order_by="posting_date desc",
        limit=10,
    )

    # Calculate match scores
    for entry in payment_entries:
        entry["match_score"] = calculate_match_score(bank_transaction, entry)

    # Sort by match score (highest first)
    payment_entries.sort(key=lambda x: x["match_score"], reverse=True)

    return payment_entries


def calculate_match_score(bank_transaction: Dict, payment_entry: Dict) -> float:
    """
    Calculate match score between bank transaction and payment entry

    Args:
        bank_transaction: Bank transaction data
        payment_entry: Payment entry data

    Returns:
        Match score (0-100, higher is better match)
    """
    score = 0.0

    # Amount match (40 points max)
    bank_amount = abs(bank_transaction.get("amount", 0))
    payment_amount = payment_entry.get("paid_amount", 0)

    if bank_amount and payment_amount:
        amount_diff = abs(bank_amount - payment_amount) / max(bank_amount, payment_amount)
        if amount_diff <= 0.01:  # Exact match
            score += 40
        elif amount_diff <= 0.05:  # Within 5%
            score += 30
        elif amount_diff <= 0.10:  # Within 10%
            score += 20
        elif amount_diff <= 0.20:  # Within 20%
            score += 10

    # Date match (30 points max)
    bank_date = getdate(bank_transaction.get("date"))
    payment_date = getdate(payment_entry.get("posting_date"))

    if bank_date and payment_date:
        date_diff = abs((bank_date - payment_date).days)
        if date_diff == 0:  # Same date
            score += 30
        elif date_diff <= 1:  # Within 1 day
            score += 25
        elif date_diff <= 3:  # Within 3 days
            score += 20
        elif date_diff <= 7:  # Within 1 week
            score += 15
        elif date_diff <= 14:  # Within 2 weeks
            score += 10

    # Reference match (20 points max)
    bank_ref = bank_transaction.get("reference_number", "").lower()
    payment_ref = payment_entry.get("reference_no", "").lower()
    bank_desc = bank_transaction.get("description", "").lower()
    payment_remarks = payment_entry.get("remarks", "").lower()

    if bank_ref and payment_ref and bank_ref in payment_ref:
        score += 20
    elif bank_ref and payment_remarks and bank_ref in payment_remarks:
        score += 15
    elif bank_desc and payment_remarks:
        # Check for common words
        bank_words = set(bank_desc.split())
        payment_words = set(payment_remarks.split())
        common_words = bank_words.intersection(payment_words)
        if len(common_words) >= 2:
            score += 10
        elif len(common_words) >= 1:
            score += 5

    # Party name match (10 points max)
    bank_desc = bank_transaction.get("description", "").lower()
    party_name = payment_entry.get("party", "").lower()

    if party_name and party_name in bank_desc:
        score += 10
    elif party_name:
        # Partial name match
        party_words = set(party_name.split())
        desc_words = set(bank_desc.split())
        if party_words.intersection(desc_words):
            score += 5

    return min(score, 100)  # Cap at 100


def auto_reconcile_transactions(company: str, min_score: float = 80.0) -> Dict:
    """
    Automatically reconcile bank transactions with high match scores

    Args:
        company: Company name
        min_score: Minimum match score for auto-reconciliation

    Returns:
        Reconciliation results
    """
    unreconciled = get_unreconciled_transactions(company)
    reconciled_count = 0
    errors = []

    for transaction in unreconciled:
        try:
            # Find matching payment entries
            matches = find_matching_payment_entries(transaction)

            if matches and matches[0]["match_score"] >= min_score:
                # Auto-reconcile with best match
                best_match = matches[0]

                if reconcile_transaction_with_payment(transaction, best_match):
                    reconciled_count += 1
                else:
                    errors.append(f"Failed to reconcile transaction {transaction['name']}")

        except Exception as e:
            errors.append(f"Error processing transaction {transaction['name']}: {str(e)}")
            frappe.log_error(f"Auto-reconciliation error: {str(e)}", "Bank Reconciliation Error")

    return {
        "success": True,
        "reconciled_count": reconciled_count,
        "total_processed": len(unreconciled),
        "errors": errors,
    }


def reconcile_transaction_with_payment(bank_transaction: Dict, payment_entry: Dict) -> bool:
    """
    Reconcile a bank transaction with a payment entry

    Args:
        bank_transaction: Bank transaction data
        payment_entry: Payment entry data

    Returns:
        True if reconciliation successful
    """
    try:
        # Get the actual bank transaction document
        bank_trans_doc = frappe.get_doc("Bank Transaction", bank_transaction["name"])

        # Update bank transaction status and link payment entry
        bank_trans_doc.status = "Reconciled"
        bank_trans_doc.append(
            "payment_entries",
            {
                "payment_document": "Payment Entry",
                "payment_entry": payment_entry["name"],
                "allocated_amount": abs(
                    bank_trans_doc.unallocated_amount
                    or bank_trans_doc.deposit
                    or bank_trans_doc.withdrawal
                    or 0
                ),
            },
        )
        bank_trans_doc.save()

        # Log reconciliation
        frappe.logger().info(
            f"Auto-reconciled bank transaction {bank_transaction['name']} with payment {payment_entry['name']}"
        )

        return True

    except Exception as e:
        frappe.log_error(f"Reconciliation error: {str(e)}", "Bank Reconciliation Error")
        return False


def create_reconciliation_report(company: str, from_date: str, to_date: str) -> Dict:
    """
    Create bank reconciliation report

    Args:
        company: Company name
        from_date: Report start date
        to_date: Report end date

    Returns:
        Reconciliation report data
    """
    # Get reconciled transactions
    reconciled = frappe.get_all(
        "Bank Transaction",
        filters={
            "company": company,
            "date": ["between", [from_date, to_date]],
            "status": "Reconciled",
            "docstatus": 1,
        },
        fields=["name", "date", "deposit", "withdrawal", "payment_entry"],
        order_by="date",
    )

    # Get unreconciled transactions
    unreconciled = get_unreconciled_transactions(company, from_date, to_date)

    # Calculate totals
    reconciled_deposits = sum(t.get("deposit", 0) for t in reconciled)
    reconciled_withdrawals = sum(t.get("withdrawal", 0) for t in reconciled)
    unreconciled_deposits = sum(t.get("deposit", 0) for t in unreconciled)
    unreconciled_withdrawals = sum(t.get("withdrawal", 0) for t in unreconciled)

    return {
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
        "reconciled_transactions": len(reconciled),
        "unreconciled_transactions": len(unreconciled),
        "reconciled_deposits": reconciled_deposits,
        "reconciled_withdrawals": reconciled_withdrawals,
        "unreconciled_deposits": unreconciled_deposits,
        "unreconciled_withdrawals": unreconciled_withdrawals,
        "total_reconciled": reconciled_deposits - reconciled_withdrawals,
        "total_unreconciled": unreconciled_deposits - unreconciled_withdrawals,
        "reconciliation_rate": (
            (len(reconciled) / (len(reconciled) + len(unreconciled)) * 100)
            if (reconciled or unreconciled)
            else 0
        ),
    }


def suggest_payment_matches(bank_transaction_name: str) -> List[Dict]:
    """
    Suggest payment entry matches for a specific bank transaction

    Args:
        bank_transaction_name: Name of bank transaction

    Returns:
        List of suggested matches with scores
    """
    bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)

    bank_data = {
        "amount": bank_transaction.deposit or -bank_transaction.withdrawal,
        "date": bank_transaction.date,
        "description": bank_transaction.description or "",
        "reference_number": bank_transaction.reference_number or "",
    }

    return find_matching_payment_entries(bank_data)
