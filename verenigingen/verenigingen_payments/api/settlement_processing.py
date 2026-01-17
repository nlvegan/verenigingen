"""
Settlement Processing API
Provides endpoints for processing Mollie settlements into ERPNext Bank Transactions

Security: Uses @frappe.whitelist() for API access control
Authorization: Requires appropriate ERPNext permissions for Bank Transaction creation
"""

from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.verenigingen_payments.services.settlement_bank_transaction_processor import (
    SettlementBankTransactionProcessor,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_settlement_deposit(
    settlement_id: Optional[str] = None, bank_reference: Optional[str] = None
) -> Dict:
    """
    Process a Mollie settlement into an ERPNext Bank Transaction.

    This endpoint creates a Bank Transaction from a Mollie settlement (payout to your bank),
    enabling reconciliation via ERPNext Bank Reconciliation Tool.

    Args:
        settlement_id: Mollie settlement ID (e.g., "stl_jDk30akdN")
        bank_reference: Bank reference from statement (e.g., "1234.5678.90")
                       One of settlement_id or bank_reference must be provided.

    Returns:
        dict: {
            "status": "success" | "error" | "already_processed",
            "bank_transaction": str (BT name if created),
            "settlement_id": str,
            "settlement_reference": str (bank reference),
            "amount": float,
            "linked_payment_entries": int (count of linked PEs),
            "reconciliation_details": dict with counts,
            "message": str (if already processed or error),
            "error": str (if error occurred)
        }

    Examples:
        # Via settlement ID
        frappe.call({
            method: 'verenigingen.verenigingen_payments.api.settlement_processing.process_settlement_deposit',
            args: {settlement_id: 'stl_jDk30akdN'}
        })

        # Via bank reference from statement
        frappe.call({
            method: 'verenigingen.verenigingen_payments.api.settlement_processing.process_settlement_deposit',
            args: {bank_reference: '1234.5678.90'}
        })

    Permissions:
        Requires permission to create Bank Transaction documents
    """
    try:
        processor = SettlementBankTransactionProcessor()
        result = processor.process_settlement_deposit(
            settlement_id=settlement_id, bank_reference=bank_reference
        )

        # Log success for audit trail
        if result.get("status") == "success":
            frappe.logger().info(
                f"API: Successfully processed settlement {result.get('settlement_id')} "
                f"→ Bank Transaction {result.get('bank_transaction')}"
            )

        return result

    except Exception as e:
        frappe.log_error(f"API Error processing settlement: {str(e)}", "Settlement Processing API Error")
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def batch_process_recent_settlements(days: int = 7) -> Dict:
    """
    Batch process all recent Mollie settlements into Bank Transactions.

    Useful for catching up on settlements that weren't processed automatically,
    or for initial migration of historical settlement data.

    Args:
        days: Number of days to look back (default: 7)

    Returns:
        dict: {
            "total_settlements": int,
            "processed": int,
            "already_processed": int,
            "errors": int,
            "results": List[Dict] with individual settlement results
        }

    Example:
        # Process settlements from last 7 days
        frappe.call({
            method: 'verenigingen.verenigingen_payments.api.settlement_processing.batch_process_recent_settlements',
            args: {days: 7}
        })

        # Process settlements from last 30 days (e.g., for migration)
        frappe.call({
            method: 'verenigingen.verenigingen_payments.api.settlement_processing.batch_process_recent_settlements',
            args: {days: 30}
        })

    Permissions:
        Requires permission to create Bank Transaction documents
        Recommended to run in background for large date ranges
    """
    try:
        days = int(days) if days else 7

        if days > 90:
            return {
                "status": "error",
                "error": "Cannot process more than 90 days at once. Please use smaller batches.",
            }

        processor = SettlementBankTransactionProcessor()
        result = processor.batch_process_recent_settlements(days=days)

        # Log batch completion
        frappe.logger().info(
            f"API: Batch settlement processing complete: "
            f"{result['processed']} processed, "
            f"{result['already_processed']} already processed, "
            f"{result['errors']} errors"
        )

        return result

    except Exception as e:
        frappe.log_error(
            f"API Error in batch settlement processing: {str(e)}",
            "Settlement Batch Processing API Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_settlement_status(settlement_id: str) -> Dict:
    """
    Check if a settlement has already been processed into a Bank Transaction.

    Args:
        settlement_id: Mollie settlement ID

    Returns:
        dict: {
            "settlement_id": str,
            "processed": bool,
            "bank_transaction": str (BT name if exists),
            "settlement_info": dict (from Mollie API if available)
        }

    Example:
        frappe.call({
            method: 'verenigingen.verenigingen_payments.api.settlement_processing.get_settlement_status',
            args: {settlement_id: 'stl_jDk30akdN'}
        })

    Permissions:
        Requires read permission on Bank Transaction
    """
    try:
        # Check if Bank Transaction exists
        existing_bt = frappe.db.get_value(
            "Bank Transaction", {"reference_number": settlement_id}, ["name", "date", "deposit"]
        )

        result = {"settlement_id": settlement_id, "processed": bool(existing_bt)}

        if existing_bt:
            result["bank_transaction"] = existing_bt[0]
            result["date"] = existing_bt[1]
            result["amount"] = existing_bt[2]

        # Try to get settlement info from Mollie
        try:
            processor = SettlementBankTransactionProcessor()
            settlement = processor.settlements_client.get_settlement(settlement_id)

            result["settlement_info"] = {
                "reference": settlement.reference,
                "status": settlement.status,
                "amount": float(settlement.amount.decimal_value) if settlement.amount else 0.0,
                "settled_at": str(settlement.settled_at) if settlement.settled_at else None,
            }
        except Exception as api_error:
            result["settlement_info_error"] = str(api_error)

        return result

    except Exception as e:
        frappe.log_error(
            f"API Error checking settlement status: {str(e)}",
            "Settlement Status Check API Error",
        )
        return {"status": "error", "error": str(e)}
