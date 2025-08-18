"""
Mollie Balances API Client
Client for managing and monitoring account balances
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _

from ..core.compliance.audit_trail import AuditEventType, AuditSeverity
from ..core.models.balance import Balance, BalanceReport, BalanceTransaction
from ..core.mollie_base_client import MollieBaseClient


class BalancesClient(MollieBaseClient):
    """
    Client for Mollie Balances API

    Provides:
    - Balance retrieval and monitoring
    - Transaction history
    - Balance reports
    - Primary balance management
    """

    def get_balance(self, balance_id: str) -> Balance:
        """
        Get a specific balance

        Args:
            balance_id: Balance identifier

        Returns:
            Balance object
        """
        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.BALANCE_CHECKED, AuditSeverity.INFO, f"Retrieving balance: {balance_id}"
        # )

        response = self.get(f"balances/{balance_id}")
        return Balance(response)

    def list_balances(self, currency: Optional[str] = None) -> List[Balance]:
        """
        List all balances

        Args:
            currency: Filter by currency code

        Returns:
            List of Balance objects
        """
        params = {}
        if currency:
            params["currency"] = currency

        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.BALANCE_CHECKED,
        #     AuditSeverity.INFO,
        #     "Listing all balances",
        #     details={"currency_filter": currency},
        # )

        response = self.get("balances", params=params, paginated=True)

        balances = []
        for item in response:
            balance = Balance(item)
            balances.append(balance)

        return balances

    def get_primary_balance(self) -> Balance:
        """
        Get the primary balance

        Returns:
            Primary Balance object
        """
        self.audit_trail.log_event(
            AuditEventType.BALANCE_CHECKED, AuditSeverity.INFO, "Retrieving primary balance"
        )

        response = self.get("balances/primary")
        return Balance(response)

    def list_balance_transactions(
        self,
        balance_id: str,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
    ) -> List[BalanceTransaction]:
        """
        List transactions for a balance

        Args:
            balance_id: Balance identifier
            from_date: Start date filter (applied via API if supported, fallback to memory filtering)
            until_date: End date filter (applied via API if supported, fallback to memory filtering)
            limit: Maximum number of results

        Returns:
            List of BalanceTransaction objects
        """
        params = {"limit": limit}

        # Try to use API date filtering first, with fallback to memory filtering
        api_date_filtering = True
        if from_date and api_date_filtering:
            params["from"] = from_date.strftime("%Y-%m-%d")
        if until_date and api_date_filtering:
            params["until"] = until_date.strftime("%Y-%m-%d")

        self.audit_trail.log_event(
            AuditEventType.BALANCE_CHECKED,
            AuditSeverity.INFO,
            f"Listing transactions for balance: {balance_id}",
            details={"from_date": params.get("from"), "until_date": params.get("until"), "limit": limit},
        )

        try:
            response = self.get(f"balances/{balance_id}/transactions", params=params, paginated=True)
            transactions = [BalanceTransaction(item) for item in response]

            # If API date filtering was used successfully, return directly
            if api_date_filtering and (from_date or until_date):
                return transactions

        except Exception as e:
            # If API date filtering failed (400 error), fall back to memory filtering
            if "400" in str(e) and ("from" in str(e) or "until" in str(e)):
                frappe.logger().warning(
                    "API date filtering not supported for balance transactions, using memory filtering"
                )
                api_date_filtering = False
                # Retry without date parameters
                params = {"limit": limit}
                response = self.get(f"balances/{balance_id}/transactions", params=params, paginated=True)
                transactions = [BalanceTransaction(item) for item in response]
            else:
                raise

        # Apply memory-based date filtering if needed
        if (from_date or until_date) and not api_date_filtering:
            filtered_transactions = []
            for transaction in transactions:
                # Try to get transaction date from created_at
                transaction_date = None

                if hasattr(transaction, "created_at") and transaction.created_at:
                    if isinstance(transaction.created_at, str):
                        try:
                            transaction_date = datetime.fromisoformat(
                                transaction.created_at.replace("Z", "+00:00")
                            )
                            transaction_date = transaction_date.replace(
                                tzinfo=None
                            )  # Convert to naive for comparison
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(transaction.created_at, datetime):
                        transaction_date = transaction.created_at
                        if transaction_date.tzinfo:
                            transaction_date = transaction_date.replace(tzinfo=None)

                # Apply date filter
                if transaction_date:
                    if from_date and transaction_date.date() < from_date.date():
                        continue
                    if until_date and transaction_date.date() > until_date.date():
                        continue

                filtered_transactions.append(transaction)

            return filtered_transactions

        return transactions

    def get_balance_report(
        self,
        balance_id: str,
        from_date: datetime,
        until_date: datetime,
        grouping: str = "transaction-categories",
    ) -> BalanceReport:
        """
        Get balance report for a period

        Args:
            balance_id: Balance identifier
            from_date: Report start date
            until_date: Report end date
            grouping: Report grouping type

        Returns:
            BalanceReport object
        """
        params = {
            "from": from_date.strftime("%Y-%m-%d"),
            "until": until_date.strftime("%Y-%m-%d"),
            "grouping": grouping,
        }

        self.audit_trail.log_event(
            AuditEventType.REPORT_GENERATED,
            AuditSeverity.INFO,
            f"Generating balance report for: {balance_id}",
            details=params,
        )

        response = self.get(f"balances/{balance_id}/report", params=params)
        return BalanceReport(response)

    def get_all_balances_summary(self) -> Dict:
        """
        Get summary of all balances

        Returns:
            Dict with balance summary information
        """
        balances = self.list_balances()

        summary = {
            "total_balances": len(balances),
            "by_currency": {},
            "total_available": {},
            "total_pending": {},
            "active_balances": 0,
            "inactive_balances": 0,
        }

        for balance in balances:
            # Count active/inactive
            if balance.is_active():
                summary["active_balances"] += 1
            else:
                summary["inactive_balances"] += 1

            # Group by currency
            if balance.currency:
                if balance.currency not in summary["by_currency"]:
                    summary["by_currency"][balance.currency] = []
                summary["by_currency"][balance.currency].append(balance.id)

                # Sum amounts by currency
                if balance.available_amount and hasattr(balance.available_amount, "decimal_value"):
                    if balance.currency not in summary["total_available"]:
                        summary["total_available"][balance.currency] = 0
                    summary["total_available"][balance.currency] += float(
                        balance.available_amount.decimal_value
                    )

                if balance.pending_amount and hasattr(balance.pending_amount, "decimal_value"):
                    if balance.currency not in summary["total_pending"]:
                        summary["total_pending"][balance.currency] = 0
                    summary["total_pending"][balance.currency] += float(balance.pending_amount.decimal_value)

        return summary

    def monitor_balance_changes(
        self, balance_id: str, threshold_amount: float, currency: str = "EUR"
    ) -> Dict:
        """
        Monitor balance for significant changes

        Args:
            balance_id: Balance to monitor
            threshold_amount: Alert threshold
            currency: Currency code

        Returns:
            Dict with monitoring results
        """
        # Get current balance
        balance = self.get_balance(balance_id)

        # Get recent transactions
        recent_transactions = self.list_balance_transactions(
            balance_id, from_date=datetime.now() - timedelta(days=1), limit=50
        )

        # Check for threshold breach
        current_amount = 0
        if balance.available_amount and hasattr(balance.available_amount, "decimal_value"):
            current_amount = float(balance.available_amount.decimal_value)

        alert_triggered = current_amount < threshold_amount

        # Calculate transaction velocity
        transaction_count = len(recent_transactions)
        total_volume = sum(
            float(tx.result_amount.decimal_value)
            for tx in recent_transactions
            if tx.result_amount and hasattr(tx.result_amount, "decimal_value")
        )

        monitoring_result = {
            "balance_id": balance_id,
            "current_amount": current_amount,
            "currency": currency,
            "threshold_amount": threshold_amount,
            "alert_triggered": alert_triggered,
            "recent_transaction_count": transaction_count,
            "recent_transaction_volume": total_volume,
            "monitored_at": datetime.now().isoformat(),
        }

        # Log alert if triggered
        if alert_triggered:
            self.audit_trail.log_event(
                AuditEventType.BALANCE_CHECKED,
                AuditSeverity.WARNING,
                f"Balance below threshold: {balance_id}",
                details=monitoring_result,
            )

            # Send notification
            frappe.publish_realtime(
                "balance_alert",
                {
                    "message": _(f"Balance {balance_id} is below threshold: {currency} {current_amount:.2f}"),
                    "balance_id": balance_id,
                    "current_amount": current_amount,
                    "threshold": threshold_amount,
                },
                user=frappe.session.user,
            )

        return monitoring_result

    def reconcile_balance_transactions(
        self, balance_id: str, start_date: datetime, end_date: datetime
    ) -> Dict:
        """
        Reconcile balance transactions for a period

        Args:
            balance_id: Balance to reconcile
            start_date: Period start
            end_date: Period end

        Returns:
            Dict with reconciliation results
        """
        # Get balance at start
        balance_start = self.get_balance(balance_id)

        # Get all transactions for period
        transactions = self.list_balance_transactions(balance_id, from_date=start_date, until_date=end_date)

        # Get balance at end
        balance_end = self.get_balance(balance_id)

        # Calculate expected vs actual
        starting_balance = (
            float(balance_start.available_amount.decimal_value) if balance_start.available_amount else 0
        )
        ending_balance = (
            float(balance_end.available_amount.decimal_value) if balance_end.available_amount else 0
        )

        transaction_total = sum(
            float(tx.result_amount.decimal_value)
            for tx in transactions
            if tx.result_amount and hasattr(tx.result_amount, "decimal_value")
        )

        expected_balance = starting_balance + transaction_total
        discrepancy = ending_balance - expected_balance

        reconciliation = {
            "balance_id": balance_id,
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "starting_balance": starting_balance,
            "ending_balance": ending_balance,
            "transaction_count": len(transactions),
            "transaction_total": transaction_total,
            "expected_balance": expected_balance,
            "discrepancy": discrepancy,
            "reconciled": abs(discrepancy) < 0.01,  # Allow 1 cent tolerance
            "reconciled_at": datetime.now().isoformat(),
        }

        # Log reconciliation
        self.audit_trail.log_event(
            AuditEventType.BALANCE_CHECKED,
            AuditSeverity.INFO,
            f"Balance reconciliation completed: {balance_id}",
            details=reconciliation,
        )

        return reconciliation
