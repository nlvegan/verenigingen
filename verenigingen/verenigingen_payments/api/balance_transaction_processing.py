"""
Balance Transaction Processing API
Provides API endpoints for processing Mollie Balance Transactions

These endpoints enable unlimited historical access to transaction data,
complementing the settlement processor which is limited to 90 days.

Usage:
    bench --site [site] execute verenigingen.verenigingen_payments.api.balance_transaction_processing.process_balance_transactions --kwargs "{'balance_id': 'bal_abc123', 'from_date': '2024-01-01', 'until_date': '2024-12-31'}"
    bench --site [site] execute verenigingen.verenigingen_payments.api.balance_transaction_processing.process_historical_data --kwargs "{'months_back': 12}"
    bench --site [site] execute verenigingen.verenigingen_payments.api.balance_transaction_processing.get_primary_balance_info
"""

from datetime import datetime
from typing import Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import critical_api
from verenigingen.utils.security.types import OperationType
from verenigingen.verenigingen_payments.services.balance_transaction_processor import (
    BalanceTransactionProcessor,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_balance_transactions(
    balance_id: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
    limit: int = 250,
) -> Dict:
    """
    Process balance transactions into Bank Transactions.

    Args:
        balance_id: Mollie balance ID (defaults to primary balance)
        from_date: Start date (ISO format: YYYY-MM-DD)
        until_date: End date (ISO format: YYYY-MM-DD)
        limit: Maximum transactions to process (default: 250)

    Returns:
        dict: Processing results

    Example:
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.process_balance_transactions \\
            --kwargs "{'from_date': '2024-01-01', 'until_date': '2024-12-31', 'limit': 250}"
    """
    try:
        processor = BalanceTransactionProcessor()

        # Get balance ID if not provided
        if not balance_id:
            balance_id = processor.get_primary_balance_id()

        # Parse dates if provided
        from_date_obj = None
        until_date_obj = None

        if from_date:
            try:
                from_date_obj = datetime.fromisoformat(from_date)
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid from_date format: {from_date}. Use YYYY-MM-DD.",
                }

        if until_date:
            try:
                until_date_obj = datetime.fromisoformat(until_date)
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid until_date format: {until_date}. Use YYYY-MM-DD.",
                }

        # Validate limit
        try:
            limit = int(limit)
            if limit < 1 or limit > 1000:
                return {
                    "status": "error",
                    "error": "Limit must be between 1 and 1000",
                }
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid limit value: {limit}"}

        # Process transactions
        result = processor.process_balance_transactions(
            balance_id=balance_id,
            from_date=from_date_obj,
            until_date=until_date_obj,
            limit=limit,
        )

        return result

    except frappe.ValidationError as e:
        frappe.log_error(
            f"Validation error in balance transaction processing: {str(e)}",
            "Balance Transaction Processing Error",
        )
        return {"status": "error", "error": str(e)}

    except Exception as e:
        frappe.log_error(
            f"Error in balance transaction processing: {str(e)}",
            "Balance Transaction Processing Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def process_historical_data(months_back: int = 12, batch_size: int = 250) -> Dict:
    """
    Process historical balance transactions in batches.

    Useful for initial data migration or catching up on old transactions.

    Args:
        months_back: Number of months to look back (default: 12)
        batch_size: Transactions per batch (default: 250)

    Returns:
        dict: Overall processing results

    Example:
        # Process last 12 months
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.process_historical_data \\
            --kwargs "{'months_back': 12}"

        # Process last 24 months with larger batches
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.process_historical_data \\
            --kwargs "{'months_back': 24, 'batch_size': 500}"
    """
    try:
        # Validate months_back
        try:
            months_back = int(months_back)
            if months_back < 1 or months_back > 120:
                return {
                    "status": "error",
                    "error": "months_back must be between 1 and 120 (10 years)",
                }
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid months_back value: {months_back}"}

        # Validate batch_size
        try:
            batch_size = int(batch_size)
            if batch_size < 1 or batch_size > 1000:
                return {
                    "status": "error",
                    "error": "batch_size must be between 1 and 1000",
                }
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid batch_size value: {batch_size}"}

        processor = BalanceTransactionProcessor()
        result = processor.process_historical_data(months_back=months_back, batch_size=batch_size)

        return result

    except Exception as e:
        frappe.log_error(
            f"Error in historical balance transaction processing: {str(e)}",
            "Balance Historical Processing Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_primary_balance_info() -> Dict:
    """
    Get information about the primary balance.

    Returns:
        dict: Primary balance details

    Example:
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.get_primary_balance_info
    """
    try:
        processor = BalanceTransactionProcessor()
        primary_balance = processor.balances_client.get_primary_balance()

        return {
            "status": "success",
            "balance_id": primary_balance.id,
            "currency": primary_balance.currency,
            "available_amount": (
                float(primary_balance.available_amount.decimal_value)
                if primary_balance.available_amount
                else 0.0
            ),
            "pending_amount": (
                float(primary_balance.pending_amount.decimal_value) if primary_balance.pending_amount else 0.0
            ),
            "created_at": primary_balance.created_at,
            "status_value": primary_balance.status,
        }

    except Exception as e:
        frappe.log_error(
            f"Error retrieving primary balance info: {str(e)}",
            "Balance Info Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def check_transaction_status(transaction_id: str, include_mollie_data: bool = False) -> Dict:
    """
    Check if a balance transaction has already been processed and optionally fetch raw Mollie API data.

    Args:
        transaction_id: Mollie balance transaction ID
        include_mollie_data: Whether to fetch raw Mollie API data (slow, defaults to False)

    Returns:
        dict: Transaction processing status with optional raw API data dump

    Example:
        # Fast check (ERPNext only)
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.check_transaction_status \\
            --kwargs "{'transaction_id': 'baltr_QM24bwP3Ur'}"

        # Full check including Mollie API data (slow)
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.check_transaction_status \\
            --kwargs "{'transaction_id': 'baltr_QM24bwP3Ur', 'include_mollie_data': true}"
    """
    try:
        if not transaction_id:
            return {"status": "error", "error": "transaction_id is required"}

        # Initialize result
        result = {
            "status": "success",
            "transaction_id": transaction_id,
            "processed": False,
            "bank_transaction": None,
            "mollie_api_data": None,
        }

        # Check if Bank Transaction exists
        existing_bt = frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": transaction_id},
            ["name", "date", "deposit", "withdrawal", "status", "currency", "description"],
            as_dict=True,
        )

        if existing_bt:
            result["processed"] = True
            result["bank_transaction"] = {
                "name": existing_bt.name,
                "date": str(existing_bt.date),
                "deposit": float(existing_bt.deposit or 0),
                "withdrawal": float(existing_bt.withdrawal or 0),
                "amount": float(existing_bt.deposit or existing_bt.withdrawal or 0),
                "currency": existing_bt.currency,
                "status": existing_bt.status,
                "description": existing_bt.description,
            }

        # Fetch raw Mollie API data (only if explicitly requested)
        # This is SLOW (~30 seconds) because Mollie API doesn't support direct ID lookup
        if include_mollie_data:
            try:
                processor = BalanceTransactionProcessor()
                balance_id = processor.get_primary_balance_id()

                # Fetch recent balance transactions and search for the specific one
                # Note: Mollie doesn't provide a direct get-by-ID endpoint, so we list and filter
                # Use smaller limit since unprocessed transactions are likely very recent
                transactions = processor.balances_client.list_balance_transactions(
                    balance_id=balance_id, limit=100  # Reduced from 500 for better performance
                )

                # Find the specific transaction by ID
                transaction = None
                for tx in transactions:
                    if tx.id == transaction_id:
                        transaction = tx
                        break

                if not transaction:
                    result[
                        "mollie_api_error"
                    ] = f"Transaction {transaction_id} not found in recent transactions (checked last 100). Try processing it first."
                else:
                    # Convert Mollie object to dict for JSON serialization
                    result["mollie_api_data"] = {
                        "id": transaction.id,
                        "type": transaction.type,
                        "result_amount": {
                            "value": transaction.result_amount.value if transaction.result_amount else None,
                            "currency": transaction.result_amount.currency
                            if transaction.result_amount
                            else None,
                        }
                        if transaction.result_amount
                        else None,
                        "initial_amount": {
                            "value": transaction.initial_amount.value if transaction.initial_amount else None,
                            "currency": transaction.initial_amount.currency
                            if transaction.initial_amount
                            else None,
                        }
                        if transaction.initial_amount
                        else None,
                        "deductions": {
                            "amount": {
                                "value": transaction.deductions.amount.value
                                if transaction.deductions and transaction.deductions.amount
                                else None,
                                "currency": transaction.deductions.amount.currency
                                if transaction.deductions and transaction.deductions.amount
                                else None,
                            }
                            if transaction.deductions and hasattr(transaction.deductions, "amount")
                            else None,
                            "count": transaction.deductions.count
                            if transaction.deductions and hasattr(transaction.deductions, "count")
                            else 0,
                            "period_id": transaction.deductions.period_id
                            if transaction.deductions and hasattr(transaction.deductions, "period_id")
                            else None,
                        }
                        if transaction.deductions
                        else None,
                        "created_at": str(transaction.created_at) if transaction.created_at else None,
                        "context": transaction.context if hasattr(transaction, "context") else None,
                        "resource": transaction.resource if hasattr(transaction, "resource") else None,
                        "_links": {
                            "self": transaction._links.get("self", {}).get("href")
                            if hasattr(transaction, "_links") and transaction._links
                            else None,
                            "balance": transaction._links.get("balance", {}).get("href")
                            if hasattr(transaction, "_links") and transaction._links
                            else None,
                        }
                        if hasattr(transaction, "_links") and transaction._links
                        else None,
                    }

            except Exception as api_error:
                result["mollie_api_error"] = str(api_error)
                frappe.logger().warning(
                    f"Could not fetch Mollie API data for {transaction_id}: {str(api_error)}"
                )
        else:
            # Mollie API data not requested (improves performance)
            result["mollie_api_note"] = "Mollie API data not fetched (set include_mollie_data=true to fetch)"

        return result

    except Exception as e:
        frappe.log_error(f"Error checking transaction status: {str(e)}", "Transaction Status Check Error")
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def search_transactions_by_description(search_term: str, limit: int = 50) -> Dict:
    """
    Search Bank Transactions by description text.

    Args:
        search_term: Text to search for in description field
        limit: Maximum results to return (default: 50)

    Returns:
        dict: Search results with matching Bank Transactions

    Example:
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.search_transactions_by_description \\
            --kwargs "{'search_term': 'Bestelling', 'limit': 20}"
    """
    try:
        if not search_term:
            return {"status": "error", "error": "search_term is required"}

        # Validate limit
        try:
            limit = int(limit)
            if limit < 1 or limit > 500:
                return {"status": "error", "error": "limit must be between 1 and 500"}
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid limit value: {limit}"}

        # Search Bank Transactions with balance transaction IDs
        results = frappe.db.sql(
            """
            SELECT
                name,
                date,
                description,
                deposit,
                withdrawal,
                currency,
                status,
                reference_number,
                transaction_id,
                bank_account
            FROM `tabBank Transaction`
            WHERE (reference_number LIKE 'baltr_%' OR transaction_id LIKE 'tr_%')
                AND description LIKE %s
            ORDER BY date DESC, creation DESC
            LIMIT %s
        """,
            (f"%{search_term}%", limit),
            as_dict=True,
        )

        # Format results
        formatted_results = []
        for row in results:
            formatted_results.append(
                {
                    "name": row.name,
                    "date": str(row.date),
                    "description": row.description,
                    "amount": float(row.deposit or row.withdrawal or 0),
                    "type": "deposit" if row.deposit else "withdrawal",
                    "currency": row.currency,
                    "status": row.status,
                    "reference_number": row.reference_number,
                    "transaction_id": row.transaction_id,
                    "bank_account": row.bank_account,
                }
            )

        return {
            "status": "success",
            "search_term": search_term,
            "total_found": len(formatted_results),
            "limit": limit,
            "results": formatted_results,
        }

    except Exception as e:
        frappe.log_error(
            f"Error searching transactions by description: {str(e)}",
            "Transaction Description Search Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def fetch_recent_transactions_for_search(limit: int = 100) -> Dict:
    """
    Fetch recent balance transactions from Mollie API for search purposes.

    This retrieves transactions from Mollie and processes them into ERPNext,
    making them searchable via the description search function.

    Args:
        limit: Number of recent transactions to fetch (default: 100, max: 250)

    Returns:
        dict: Processing results with count of fetched transactions

    Example:
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.fetch_recent_transactions_for_search \\
            --kwargs "{'limit': 100}"
    """
    try:
        # Validate limit
        try:
            limit = int(limit)
            if limit < 1 or limit > 250:
                return {"status": "error", "error": "limit must be between 1 and 250"}
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid limit value: {limit}"}

        processor = BalanceTransactionProcessor()
        balance_id = processor.get_primary_balance_id()

        # Fetch recent transactions from Mollie
        transactions = processor.balances_client.list_balance_transactions(balance_id=balance_id, limit=limit)

        # Process each transaction into ERPNext
        processed = 0
        already_exists = 0
        errors = []

        for transaction in transactions:
            try:
                # Check if already processed
                existing = frappe.db.exists("Bank Transaction", {"reference_number": transaction.id})
                if existing:
                    already_exists += 1
                    continue

                # Process the transaction
                result = processor._process_single_transaction(transaction, balance_id)
                if result.get("status") == "success":
                    processed += 1
                elif result.get("status") == "already_processed":
                    already_exists += 1
                else:
                    errors.append(f"{transaction.id}: {result.get('error', 'Unknown error')}")

            except Exception as e:
                errors.append(f"{transaction.id}: {str(e)}")

        return {
            "status": "success",
            "total_fetched": len(transactions),
            "processed": processed,
            "already_exists": already_exists,
            "errors": len(errors),
            "error_details": errors[:10] if errors else [],  # First 10 errors
        }

    except Exception as e:
        frappe.log_error(
            f"Error fetching recent transactions for search: {str(e)}",
            "Fetch Recent Transactions Error",
        )
        return {"status": "error", "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_processing_statistics(days: int = 30) -> Dict:
    """
    Get statistics about balance transaction processing.

    Args:
        days: Number of days to look back (default: 30)

    Returns:
        dict: Processing statistics

    Example:
        bench --site dev.veganisme.net execute \\
            verenigingen.verenigingen_payments.api.balance_transaction_processing.get_processing_statistics \\
            --kwargs "{'days': 30}"
    """
    try:
        from datetime import timedelta

        from frappe.utils import getdate, now_datetime

        # Validate days
        try:
            days = int(days)
            if days < 1 or days > 365:
                return {"status": "error", "error": "days must be between 1 and 365"}
        except (ValueError, TypeError):
            return {"status": "error", "error": f"Invalid days value: {days}"}

        # Calculate date range
        end_date = now_datetime()
        start_date = end_date - timedelta(days=days)

        # Count Bank Transactions from balance transactions
        # Balance transaction IDs start with 'baltr_'
        total_processed = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
            },
        )

        # Get reconciliation status breakdown
        reconciled = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
                "status": "Reconciled",
            },
        )

        unreconciled = frappe.db.count(
            "Bank Transaction",
            filters={
                "reference_number": ["like", "baltr_%"],
                "date": ["between", [getdate(start_date), getdate(end_date)]],
                "status": "Unreconciled",
            },
        )

        # Get total amounts
        amounts = frappe.db.sql(
            """
            SELECT
                SUM(deposit) as total_deposits,
                SUM(withdrawal) as total_withdrawals,
                COUNT(*) as count
            FROM `tabBank Transaction`
            WHERE reference_number LIKE 'baltr_%'
                AND date BETWEEN %s AND %s
        """,
            (getdate(start_date), getdate(end_date)),
            as_dict=True,
        )

        amount_data = amounts[0] if amounts else {}

        return {
            "status": "success",
            "period": {
                "from_date": start_date.date().isoformat(),
                "to_date": end_date.date().isoformat(),
                "days": days,
            },
            "totals": {
                "total_processed": total_processed,
                "reconciled": reconciled,
                "unreconciled": unreconciled,
                "total_deposits": float(amount_data.get("total_deposits") or 0),
                "total_withdrawals": float(amount_data.get("total_withdrawals") or 0),
            },
            "percentages": {
                "reconciled_pct": (
                    round(reconciled / total_processed * 100, 2) if total_processed > 0 else 0
                ),
                "unreconciled_pct": (
                    round(unreconciled / total_processed * 100, 2) if total_processed > 0 else 0
                ),
            },
        }

    except Exception as e:
        frappe.log_error(
            f"Error getting processing statistics: {str(e)}",
            "Processing Statistics Error",
        )
        return {"status": "error", "error": str(e)}
