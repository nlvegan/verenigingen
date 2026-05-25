"""
Mollie Balances API Client
Client for managing and monitoring account balances
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
    MollieObjectType,
    get_payment_data_extractor,
)

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

    Note: Requires Organization Access Token (Backend API)
    """

    def __init__(self, settings_name: str = "Mollie Settings"):
        """
        Initialize Balances Client with Organization Access Token

        Args:
            settings_name: Name of Mollie Settings doctype
        """
        # Always use backend API for balances - they require Organization Access Token
        super().__init__(use_backend_api=True)
        self._validate_backend_api_access()

    def _validate_backend_api_access(self):
        """
        Validate that Backend API is properly configured

        Raises:
            frappe.ValidationError: If backend API is not configured properly
        """
        # Only short-circuit when MollieBaseClient.__init__ actually substituted
        # the in-test dummy api_key (no real key was provided). A test that
        # constructs the client with an explicit api_key still flows through the
        # full validation path, even under frappe.flags.in_test. This keeps the
        # bypass scoped to the exact failure mode the test runner produces on
        # unconfigured CI sites.
        if getattr(self, "_test_bypass_active", False):
            return
        try:
            # This will raise appropriate errors if backend API is not configured
            self._get_backend_api_key()
        except frappe.ValidationError as e:
            # Use centralized error handler for consistent messaging and logging
            self.error_handler.handle_error(
                error_type="configuration_missing",
                error=e,
                context={
                    "client": "BalancesClient",
                    "requirement": "Backend API (Organization Access Token)",
                    "configuration_location": "Mollie Settings",
                },
                audit_trail=self.audit_trail,
            )

    def get_balance(self, balance_id: str, use_cache: bool = True, cache_ttl: int = 60) -> Balance:
        """
        Get a specific balance

        Args:
            balance_id: Balance identifier
            use_cache: Whether to use cache (default: True, 60 second TTL)
            cache_ttl: Cache TTL in seconds (default: 60)

        Returns:
            Balance object
        """
        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.BALANCE_CHECKED, AuditSeverity.INFO, f"Retrieving balance: {balance_id}"
        # )

        if use_cache and self.enable_cache:
            response = self.get_cached(f"balances/{balance_id}", cache_ttl=cache_ttl)
        else:
            response = self.get(f"balances/{balance_id}")
        return self._parse_response(response, Balance)

    def list_balances(
        self, currency: Optional[str] = None, limit: int = 10, use_cache: bool = True, cache_ttl: int = 180
    ) -> List[Balance]:
        """
        List all balances

        Args:
            currency: Filter by currency code
            limit: Maximum number of balances to return (default: 10)
            use_cache: Whether to use cache (default: True, 180 second TTL)
            cache_ttl: Cache TTL in seconds (default: 180 = 3 minutes)

        Returns:
            List of Balance objects
        """
        params = {"limit": limit}
        if currency:
            params["currency"] = currency

        # Audit trail temporarily disabled
        # self.audit_trail.log_event(
        #     AuditEventType.BALANCE_CHECKED,
        #     AuditSeverity.INFO,
        #     "Listing all balances",
        #     details={"currency_filter": currency},
        # )

        if use_cache and self.enable_cache:
            response = self.get_cached("balances", params=params, paginated=True, cache_ttl=cache_ttl)
        else:
            response = self.get("balances", params=params, paginated=True)

        return self._parse_response(response, Balance)

    def get_primary_balance(self, use_cache: bool = True, cache_ttl: int = 30) -> Balance:
        """
        Get the primary balance

        Args:
            use_cache: Whether to use cache (default: True, 30 second TTL)
            cache_ttl: Cache TTL in seconds (default: 30 - frequently changing)

        Returns:
            Primary Balance object
        """
        self.audit_trail.log_event(
            AuditEventType.BALANCE_CHECKED, AuditSeverity.INFO, "Retrieving primary balance"
        )

        if use_cache and self.enable_cache:
            response = self.get_cached("balances/primary", cache_ttl=cache_ttl)
        else:
            response = self.get("balances/primary")
        return self._parse_response(response, Balance)

    def list_balance_transactions(
        self,
        balance_id: str,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
        use_cache: bool = True,
        cache_ttl: int = 120,
    ) -> List[BalanceTransaction]:
        """
        List transactions for a balance

        Args:
            balance_id: Balance identifier
            from_date: Start date filter (memory-based, Mollie API doesn't support date params)
            until_date: End date filter (memory-based, Mollie API doesn't support date params)
            limit: Maximum number of results to fetch before filtering (default: 250)
            use_cache: Whether to use cache (default: True, 120 second TTL)
            cache_ttl: Cache TTL in seconds (default: 120 = 2 minutes)

        Returns:
            List of BalanceTransaction objects

        Note:
            Mollie's balance transaction API doesn't support from/until date parameters.
            This method fetches transactions up to 'limit' and then filters them in memory.
            For large date ranges, you may need to increase the limit parameter.
        """
        params = {"limit": limit}

        # NOTE: Mollie API doesn't support date filtering for balance transactions
        # We always use memory-based filtering after fetching

        self.audit_trail.log_event(
            AuditEventType.BALANCE_CHECKED,
            AuditSeverity.INFO,
            f"Listing transactions for balance: {balance_id}",
            details={
                "from_date": from_date.strftime("%Y-%m-%d") if from_date else None,
                "until_date": until_date.strftime("%Y-%m-%d") if until_date else None,
                "limit": limit,
                "filtering_method": "memory",  # Always memory-based for balance transactions
            },
        )

        # Fetch transactions without date parameters (API doesn't support them)
        if use_cache and self.enable_cache:
            response = self.get_cached(
                f"balances/{balance_id}/transactions", params=params, paginated=True, cache_ttl=cache_ttl
            )
        else:
            response = self.get(f"balances/{balance_id}/transactions", params=params, paginated=True)
        transactions = self._parse_response(response, BalanceTransaction)

        # Apply memory-based date filtering using centralized method
        return self._filter_by_date(transactions, from_date=from_date, until_date=until_date)

    def get_balance_report(
        self,
        balance_id: str,
        from_date: datetime,
        until_date: datetime,
        grouping: str = "transaction-categories",
        use_cache: bool = True,
        cache_ttl: int = 600,
    ) -> BalanceReport:
        """
        Get balance report for a period

        Args:
            balance_id: Balance identifier
            from_date: Report start date
            until_date: Report end date
            grouping: Report grouping type
            use_cache: Whether to use cache (default: True, 600 second TTL)
            cache_ttl: Cache TTL in seconds (default: 600 = 10 minutes, semi-static data)

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

        if use_cache and self.enable_cache:
            response = self.get_cached(f"balances/{balance_id}/report", params=params, cache_ttl=cache_ttl)
        else:
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

                # Sum amounts by currency using PaymentDataExtractor
                extractor = get_payment_data_extractor()
                amounts = extractor.extract_balance_amounts(balance)

                if balance.currency not in summary["total_available"]:
                    summary["total_available"][balance.currency] = 0
                summary["total_available"][balance.currency] += amounts["available"]

                if balance.currency not in summary["total_pending"]:
                    summary["total_pending"][balance.currency] = 0
                summary["total_pending"][balance.currency] += amounts["pending"]

        return summary

    def monitor_balance_changes(
        self, balance_id: str, threshold_amount: float, currency: str = "EUR", real_time: bool = False
    ) -> Dict:
        """
        Monitor balance for significant changes

        Args:
            balance_id: Balance to monitor
            threshold_amount: Alert threshold
            currency: Currency code
            real_time: If True, bypass cache for critical monitoring (default: False)

        Returns:
            Dict with monitoring results
        """
        # Get current balance (bypass cache if real_time)
        balance = self.get_balance(balance_id, use_cache=not real_time)

        # Get recent transactions (bypass cache if real_time)
        recent_transactions = self.list_balance_transactions(
            balance_id, from_date=datetime.now() - timedelta(days=1), limit=50, use_cache=not real_time
        )

        # Check for threshold breach using PaymentDataExtractor
        extractor = get_payment_data_extractor()
        amounts = extractor.extract_balance_amounts(balance)
        current_amount = amounts["available"]

        alert_triggered = current_amount < threshold_amount

        # Calculate transaction velocity using PaymentDataExtractor
        transaction_count = len(recent_transactions)
        total_volume = sum(
            extractor.extract_amount(tx, source_type=MollieObjectType.BALANCE_TRANSACTION, allow_zero=True)
            for tx in recent_transactions
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

            # Invalidate all related caches to ensure consistency
            self.invalidate_cache(f"balances/{balance_id}")  # Specific balance
            self.invalidate_cache(f"balances/{balance_id}/transactions")  # Balance transactions
            self.invalidate_cache(f"balances/{balance_id}/report")  # Balance reports
            self.invalidate_cache("balances")  # Balance list (includes this balance)
            self.invalidate_cache("balances/primary")  # Primary balance (if this is it)
            # Note: get_all_balances_summary() calls list_balances() which is now invalidated

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
        self, balance_id: str, start_date: datetime, end_date: datetime, use_cache: bool = False
    ) -> Dict:
        """
        Reconcile balance transactions for a period

        Args:
            balance_id: Balance to reconcile
            start_date: Period start
            end_date: Period end
            use_cache: Whether to use cache (default: False - reconciliation needs accurate data)

        Returns:
            Dict with reconciliation results
        """
        # Get balance at start (bypass cache for accurate reconciliation)
        balance_start = self.get_balance(balance_id, use_cache=use_cache)

        # Get all transactions for period (bypass cache)
        transactions = self.list_balance_transactions(
            balance_id, from_date=start_date, until_date=end_date, use_cache=use_cache
        )

        # Get balance at end (bypass cache)
        balance_end = self.get_balance(balance_id, use_cache=use_cache)

        # Calculate expected vs actual using PaymentDataExtractor
        extractor = get_payment_data_extractor()
        start_amounts = extractor.extract_balance_amounts(balance_start)
        end_amounts = extractor.extract_balance_amounts(balance_end)

        starting_balance = start_amounts["available"]
        ending_balance = end_amounts["available"]

        transaction_total = sum(
            extractor.extract_amount(tx, source_type=MollieObjectType.BALANCE_TRANSACTION, allow_zero=True)
            for tx in transactions
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
