"""
Financial Dashboard for Mollie Backend
Provides comprehensive financial insights and reporting
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api

from ..clients.balances_client import BalancesClient
from ..clients.chargebacks_client import ChargebacksClient
from ..clients.invoices_client import InvoicesClient
from ..clients.payments_client import PaymentsClient
from ..clients.settlements_client import SettlementsClient
from ..core.models.settlement import Settlement
from ..services.mollie_configuration_service import get_mollie_config
from ..utils.financial_calculation_utils import (
    convert_decimal_dict_to_float,
    find_gap_periods,
    prorate_amount_by_days,
    safe_decimal_from_dict,
)
from ..utils.payment_data_extractor import MollieObjectType, get_payment_data_extractor
from ..utils.timezone_utils import (
    filter_items_by_date_range,
    get_period_date_range,
    parse_mollie_datetime,
    parse_period_key_to_date_range,
    safe_datetime_to_isoformat,
)
from ..workflows.reconciliation_engine import ReconciliationEngine


class FinancialDashboard:
    """
    Financial dashboard for Mollie backend operations

    Provides:
    - Real-time balance monitoring
    - Settlement analytics
    - Revenue tracking
    - Cost analysis
    - Chargeback metrics
    - Reconciliation status
    """

    def __init__(self):
        """Initialize dashboard"""
        # Initialize API clients (no settings_name needed for singleton)
        self.balances_client = BalancesClient()
        try:
            self.payments_client = PaymentsClient()
        except Exception as e:
            frappe.logger().error(f"Failed to initialize PaymentsClient: {e}")
            self.payments_client = None
        self.settlements_client = SettlementsClient()
        self.invoices_client = InvoicesClient()
        self.chargebacks_client = ChargebacksClient()
        self.reconciliation_engine = ReconciliationEngine()

        # Cache for settlements data to prevent redundant API calls
        self._settlements_cache = None
        # Cache for payments data to prevent redundant API calls
        self._payments_cache = None

    def _get_settlements_data(self) -> List[Dict]:
        """Get settlements data with caching to prevent redundant API calls"""
        if self._settlements_cache is None:
            try:
                self._settlements_cache = self.settlements_client.get("settlements", paginated=True)
                frappe.logger().info(f"Cached settlements data: {len(self._settlements_cache)} items")

                # Debug: Log first few settlements to see what data structure we have
                for i, settlement in enumerate(self._settlements_cache[:2]):
                    frappe.logger().info(
                        f"Settlement {i}: ID={settlement.get('id')}, Status={settlement.get('status')}, Amount={settlement.get('amount')}, Created={settlement.get('createdAt')}, Settled={settlement.get('settledAt')}"
                    )

            except Exception as e:
                frappe.logger().error(f"Failed to fetch settlements data: {e}")
                self._settlements_cache = []

        return self._settlements_cache

    def _get_payments_data(self) -> List[Dict]:
        """Get payments data with caching to prevent redundant API calls"""
        if self._payments_cache is None and self.payments_client is not None:
            try:
                # Fetch all payments once, without date filtering
                self._payments_cache = self.payments_client.get(
                    "payments", params={"limit": 250}, paginated=True
                )
                frappe.logger().info(f"Cached payments data: {len(self._payments_cache)} items")
            except Exception as e:
                frappe.logger().error(f"Failed to fetch payments data: {e}")
                self._payments_cache = []

        return self._payments_cache or []

    def _calculate_revenue_from_payments(
        self, payments_data: List[Dict], start_date: datetime, end_date: datetime
    ) -> Decimal:
        """Calculate revenue from cached payments data for a specific period"""
        total_revenue = Decimal("0")

        # Filter payments by date range
        filtered_payments = filter_items_by_date_range(
            payments_data, start_date, end_date, date_field="createdAt"
        )

        for payment in filtered_payments:
            # Include paid payments and pending ones
            status = payment.get("status", "")
            if status in ["paid", "pending", "authorized"]:
                amount_data = payment.get("amount", {})
                # Only include EUR for now
                if amount_data and amount_data.get("currency") == "EUR":
                    payment_amount = safe_decimal_from_dict(payment, "amount", "value")
                    total_revenue += payment_amount

        return total_revenue

    def _calculate_revenue_by_settlement_periods(self, start_date: datetime, end_date: datetime) -> Decimal:
        """
        Calculate revenue using settlement-period-driven approach

        Strategy:
        1. Get all settlements in date range
        2. Use settled amounts for periods covered by settlements
        3. Fetch individual payments only for unsettled periods
        4. Handles monthly settlement cycles and December exceptions automatically
        """
        total_revenue = Decimal("0")

        try:
            # Step 1: Get all settlements that might cover our date range
            settlements_data = self._get_settlements_data()

            # Step 2: Analyze which periods are covered by settlements
            settled_periods = []
            settled_revenue = Decimal("0")

            for settlement in settlements_data:
                if hasattr(settlement, "settled_at_datetime") and settlement.settled_at_datetime:
                    # Use settlement periods to determine coverage
                    if hasattr(settlement, "periods") and settlement.periods:
                        for period_key, period_data in settlement.periods.items():
                            try:
                                # Use utility to parse period key
                                period_start, period_end = parse_period_key_to_date_range(period_key)

                                # Check if this period overlaps with our date range
                                if period_start <= end_date and period_end >= start_date:
                                    # Calculate overlap
                                    overlap_start = max(period_start, start_date)
                                    overlap_end = min(period_end, end_date)

                                    if overlap_start <= overlap_end:
                                        # Use settlement's revenue for this period
                                        if hasattr(period_data, "revenue") and period_data.revenue:
                                            for revenue_item in period_data.revenue:
                                                amount = safe_decimal_from_dict(
                                                    revenue_item, "amountNet", "value"
                                                )
                                                if amount > 0:
                                                    # If partial period overlap, prorate the amount
                                                    period_days = (period_end - period_start).days + 1
                                                    overlap_days = (overlap_end - overlap_start).days + 1

                                                    if overlap_days < period_days:
                                                        amount = prorate_amount_by_days(
                                                            amount, period_days, overlap_days
                                                        )

                                                    settled_revenue += amount
                                                    settled_periods.append(
                                                        {
                                                            "start": overlap_start,
                                                            "end": overlap_end,
                                                            "amount": amount,
                                                        }
                                                    )

                            except (ValueError, AttributeError):
                                continue

            # Step 3: Find unsettled periods (gaps in settlement coverage)
            unsettled_periods = find_gap_periods(settled_periods, start_date, end_date)

            # Step 4: Calculate revenue from unsettled periods using individual payments
            unsettled_revenue = Decimal("0")

            if unsettled_periods:
                frappe.logger().info(
                    f"Found {len(unsettled_periods)} unsettled periods, fetching individual payments"
                )

                # Get payments data once for all unsettled periods
                payments_data = self._get_payments_data()

                for period in unsettled_periods:
                    period_revenue = self._calculate_revenue_from_payments(
                        payments_data, period["start"], period["end"]
                    )
                    unsettled_revenue += period_revenue

            total_revenue = settled_revenue + unsettled_revenue

            frappe.logger().info(
                f"Revenue calculation: Settled €{settled_revenue} + Unsettled €{unsettled_revenue} = Total €{total_revenue}"
            )

        except Exception as e:
            frappe.logger().error(f"Settlement-period revenue calculation failed: {e}")
            # Fallback to individual payments calculation
            payments_data = self._get_payments_data()
            total_revenue = self._calculate_revenue_from_payments(payments_data, start_date, end_date)

        return total_revenue

    def get_dashboard_summary(self) -> Dict:
        """
        Get complete dashboard summary

        Returns:
            Dict with all dashboard metrics
        """
        summary = {
            "generated_at": now_datetime().isoformat(),
            "period": self._get_current_period(),
            "balance_overview": self._get_balance_overview(),
            "settlement_metrics": self._get_settlement_metrics(),
            "revenue_analysis": self._get_revenue_analysis(),
            "cost_breakdown": self._get_cost_breakdown(),
            "chargeback_metrics": self._get_chargeback_metrics(),
            "reconciliation_status": self._get_reconciliation_status(),
            "alerts": self._get_active_alerts(),
        }

        return summary

    def _get_current_period(self) -> Dict:
        """Get current reporting period"""
        now = datetime.now(timezone.utc)
        return {
            "current_month": now.strftime("%B %Y"),
            "current_quarter": f"Q{(now.month - 1) // 3 + 1} {now.year}",
            "current_year": now.year,
        }

    def _get_balance_overview(self) -> Dict:
        """Get balance overview across all currencies"""
        overview = {
            "balances": [],
            "total_available_eur": Decimal("0"),
            "total_pending_eur": Decimal("0"),
            "health_status": "healthy",
            "last_updated": now_datetime().isoformat(),
        }

        try:
            frappe.logger().info(f"_get_balance_overview: Getting balances for user {frappe.session.user}")
            balances = self.balances_client.list_balances()
            frappe.logger().info(f"_get_balance_overview: Got {len(balances)} balances")

            extractor = get_payment_data_extractor()
            for balance in balances:
                # Extract amounts using PaymentDataExtractor
                amounts = extractor.extract_balance_amounts(balance)

                balance_info = {
                    "currency": amounts["currency"],
                    "available": amounts["available"],
                    "pending": amounts["pending"],
                    "status": balance.status,
                }

                overview["balances"].append(balance_info)

                # Convert to EUR for totals (simplified - would use actual rates)
                if balance.currency == "EUR":
                    overview["total_available_eur"] += Decimal(str(balance_info["available"]))
                    overview["total_pending_eur"] += Decimal(str(balance_info["pending"]))

            # Check health
            try:
                health = self.balances_client.check_balance_health()
                overview["health_status"] = health["status"]
            except Exception as e:
                frappe.logger().warning(f"Balance health check failed: {e}")
                overview["health_status"] = "unknown"

            # Convert decimals to float for JSON
            overview["total_available_eur"] = float(overview["total_available_eur"])
            overview["total_pending_eur"] = float(overview["total_pending_eur"])

            frappe.logger().info(
                f"_get_balance_overview: Final totals - Available: {overview['total_available_eur']}, Pending: {overview['total_pending_eur']}"
            )

        except Exception as e:
            frappe.logger().error(f"FinancialDashboard._get_balance_overview failed: {e}")
            overview["error"] = str(e)
            overview["health_status"] = "error"

        return overview

    def _get_settlement_metrics(self) -> Dict:
        """Get settlement metrics for current month"""
        metrics = {
            "current_month": {
                "count": 0,
                "total_amount": Decimal("0"),
                "average_amount": Decimal("0"),
                "by_status": {},
            },
            "last_30_days": {"count": 0, "total_amount": Decimal("0"), "trend": "stable"},
            "recent_settlements": [],
        }

        try:
            # Get settlements for the last 30 days
            now = datetime.now(timezone.utc)
            thirty_days_ago = now - timedelta(days=30)

            # Get settlements data from cache
            response = self._get_settlements_data()

            frappe.logger().info(f"Settlement metrics: Got {len(response)} settlements from cache")

            # Parse settlement data
            for item in response:
                # Process all settlements, not just those with settledAt
                # Try to get settled date, fall back to created date
                settlement_date = parse_mollie_datetime(item.get("settledAt"))
                if settlement_date is None:
                    settlement_date = parse_mollie_datetime(item.get("createdAt"))

                if not settlement_date:
                    continue

                amount_value = float(item.get("amount", {}).get("value", 0))

                # Add to recent settlements for display (show all recent ones, not just settled)
                if len(metrics["recent_settlements"]) < 5:
                    metrics["recent_settlements"].append(
                        {
                            "date": settlement_date.strftime("%Y-%m-%d"),
                            "reference": item.get("reference", item.get("id", "")),
                            "amount": f"{amount_value:.2f}",
                            "status": item.get("status", "unknown"),
                        }
                    )

                # Count in last 30 days
                if settlement_date >= thirty_days_ago:
                    metrics["last_30_days"]["count"] += 1
                    metrics["last_30_days"]["total_amount"] += Decimal(str(amount_value))

                # Check if it's current month
                if settlement_date >= now.replace(day=1):
                    metrics["current_month"]["count"] += 1
                    metrics["current_month"]["total_amount"] += Decimal(str(amount_value))

                    status = item.get("status", "unknown")
                    if status not in metrics["current_month"]["by_status"]:
                        metrics["current_month"]["by_status"][status] = 0
                    metrics["current_month"]["by_status"][status] += 1

            # Calculate average
            if metrics["current_month"]["count"] > 0:
                metrics["current_month"]["average_amount"] = (
                    metrics["current_month"]["total_amount"] / metrics["current_month"]["count"]
                )

            # Last 30 days - use cached data instead of API call with dates
            # Note: Mollie settlements API doesn't support date filtering, so we filter in memory

            # The metrics above are already calculated from the cached data
            # metrics["last_30_days"] is already populated in the loop above

            # Get next and open settlements
            next_settlement = self.settlements_client.get_next_settlement()
            extractor = get_payment_data_extractor()
            if next_settlement:
                metrics["next_settlement"] = {
                    "id": next_settlement.id,
                    "expected_amount": extractor.extract_amount(
                        next_settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                    ),
                    "status": next_settlement.status,
                    "created_at": next_settlement.created_at,
                    "settled_at": next_settlement.settled_at,
                    # Add parsed datetime for easier frontend handling - safe timezone conversion
                    "created_at_datetime": safe_datetime_to_isoformat(
                        getattr(next_settlement, "created_at_datetime", None)
                    ),
                    "settled_at_datetime": safe_datetime_to_isoformat(
                        getattr(next_settlement, "settled_at_datetime", None)
                    ),
                }

            open_settlement = self.settlements_client.get_open_settlement()
            if open_settlement:
                metrics["open_settlement"] = {
                    "id": open_settlement.id,
                    "current_amount": extractor.extract_amount(
                        open_settlement, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                    ),
                }

            # Convert decimals for JSON serialization
            convert_decimal_dict_to_float(metrics["current_month"], keys=["total_amount", "average_amount"])
            convert_decimal_dict_to_float(metrics["last_30_days"], keys=["total_amount"])

        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _get_revenue_analysis(self) -> Dict:
        """Analyze revenue from all payments (including unsettled ones)"""
        analysis = {
            "current_month": {"total_revenue": Decimal("0")},
            "current_week": {"total_revenue": Decimal("0")},
            "current_quarter": {"total_revenue": Decimal("0")},
        }

        try:
            # Use timezone-aware datetime to match Mollie API responses
            now = datetime.now(timezone.utc)

            # Calculate date ranges using utility functions
            week_start, _ = get_period_date_range("week", now)
            month_start, _ = get_period_date_range("month", now)
            quarter_start, _ = get_period_date_range("quarter", now)

            frappe.logger().info(
                f"Revenue analysis date ranges - Week: {week_start}, Month: {month_start}, Quarter: {quarter_start}"
            )

            # Use settlement-period-driven approach for optimal performance
            analysis["current_quarter"]["total_revenue"] = float(
                self._calculate_revenue_by_settlement_periods(quarter_start, now)
            )
            analysis["current_month"]["total_revenue"] = float(
                self._calculate_revenue_by_settlement_periods(month_start, now)
            )
            analysis["current_week"]["total_revenue"] = float(
                self._calculate_revenue_by_settlement_periods(week_start, now)
            )

            frappe.logger().info(
                f"Settlement-period revenue analysis complete - Week: €{analysis['current_week']['total_revenue']}, "
                f"Month: €{analysis['current_month']['total_revenue']}, "
                f"Quarter: €{analysis['current_quarter']['total_revenue']}"
            )

        except Exception as e:
            analysis["error"] = str(e)
            frappe.logger().error(f"Revenue analysis failed: {e}")
            frappe.log_error(f"Revenue analysis error: {str(e)}", "Mollie Revenue Analysis")

        return analysis

    def _get_cost_breakdown(self) -> Dict:
        """Get breakdown of costs and fees"""
        breakdown = {
            "current_month": {
                "transaction_fees": Decimal("0"),
                "chargeback_fees": Decimal("0"),
                "refund_costs": Decimal("0"),
                "total_costs": Decimal("0"),
            },
            "cost_rate": 0,  # As percentage of revenue
            "by_category": {},
        }

        try:
            # Get costs from settlements
            # now = datetime.now(timezone.utc)  # unused for now

            # Use cached settlements data instead of API call with unsupported date filters
            settlements_data = self._get_settlements_data()
            # Filter in memory for current month
            settlements = []
            for settlement_data in settlements_data:
                settlement = Settlement(settlement_data)
                # Filter by month (simplified - just check if it exists)
                settlements.append(settlement)

            for settlement in settlements:
                costs = settlement.get_total_costs()
                breakdown["current_month"]["total_costs"] += costs

            # DEAD CODE (2025-10-21): Chargeback API disabled - lacks date filtering support
            # TODO: Remove this code block by 2026-04-21 (6 months) if not re-enabled
            # OR: Re-enable when Mollie adds date filtering to Chargebacks API
            # Reference: https://docs.mollie.com/reference/v2/chargebacks-api/list-chargebacks
            # chargebacks = self.chargebacks_client.list_all_chargebacks(from_date=month_start, until_date=now)
            chargebacks = []  # Skip chargeback processing to avoid API errors

            # Chargeback fee calculation ready for re-enablement
            extractor = get_payment_data_extractor()
            for chargeback in chargebacks:
                if chargeback.settlement_amount:
                    # Chargeback fees are typically the difference between settlement and original amount
                    settlement_amt = extractor.extract_amount(
                        chargeback, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                    )
                    original_amt = (
                        extractor.extract_amount(
                            chargeback, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                        )
                        if chargeback.amount
                        else Decimal("0")
                    )
                    fee = abs(Decimal(str(settlement_amt))) - Decimal(str(original_amt))
                    breakdown["current_month"]["chargeback_fees"] += fee

            # Calculate cost rate
            revenue = self._get_revenue_analysis()
            if revenue["current_month"]["total_revenue"] > 0:
                breakdown["cost_rate"] = float(
                    (
                        breakdown["current_month"]["total_costs"]
                        / Decimal(str(revenue["current_month"]["total_revenue"]))
                    )
                    * 100
                )

            # Convert decimals for JSON serialization
            convert_decimal_dict_to_float(
                breakdown["current_month"],
                keys=["transaction_fees", "chargeback_fees", "refund_costs", "total_costs"],
            )

        except Exception as e:
            breakdown["error"] = str(e)

        return breakdown

    def _get_chargeback_metrics(self) -> Dict:
        """Get chargeback metrics and trends"""
        metrics = {
            "current_month": {
                "count": 0,
                "total_amount": Decimal("0"),
                "reversed_count": 0,
                "net_loss": Decimal("0"),
            },
            "rate": 0,  # Chargeback rate as percentage
            "trend": "stable",
            "top_reasons": [],
            "risk_level": "low",
        }

        try:
            # Current month chargebacks
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1)

            # DEAD CODE (2025-10-21): Chargeback metrics disabled - API lacks date filtering
            # TODO: Remove this code block by 2026-04-21 (6 months) if not re-enabled
            # OR: Re-enable when Mollie adds date filtering to Chargebacks API
            # Reference: https://docs.mollie.com/reference/v2/chargebacks-api/list-chargebacks
            chargebacks = []  # Skip to avoid API errors

            metrics["current_month"]["count"] = len(chargebacks)

            # Chargeback metrics calculation ready for re-enablement
            extractor = get_payment_data_extractor()
            for chargeback in chargebacks:
                if chargeback.amount:
                    amount = extractor.extract_amount(
                        chargeback, source_type=MollieObjectType.SETTLEMENT, allow_zero=True
                    )
                    metrics["current_month"]["total_amount"] += Decimal(str(amount))

                if chargeback.is_reversed():
                    metrics["current_month"]["reversed_count"] += 1

            # Calculate net loss
            impact = self.chargebacks_client.calculate_financial_impact(month_start, now)
            metrics["current_month"]["net_loss"] = Decimal(str(impact["net_loss"]))

            # Get trend analysis
            trend_analysis = self.chargebacks_client.analyze_chargeback_trends(30)
            metrics["trend"] = "increasing" if trend_analysis["average_per_day"] > 0.2 else "stable"

            # Get top reasons
            if trend_analysis.get("by_reason"):
                sorted_reasons = sorted(
                    trend_analysis["by_reason"].items(), key=lambda x: x[1]["count"], reverse=True
                )
                metrics["top_reasons"] = [
                    {"reason": reason, "count": data["count"]} for reason, data in sorted_reasons[:3]
                ]

            # Get risk insights
            insights = self.chargebacks_client.get_chargeback_prevention_insights()
            metrics["risk_level"] = insights["risk_level"]

            # Convert decimals for JSON serialization
            convert_decimal_dict_to_float(metrics["current_month"], keys=["total_amount", "net_loss"])

        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _get_reconciliation_status(self) -> Dict:
        """Get payment reconciliation status based on payment success rates"""
        status = {
            "success_rate_30d": 0,
            "reconciled_payments": 0,
            "total_payments": 0,
        }

        try:
            # Get recent payments to calculate success rate
            now = datetime.now(timezone.utc)
            thirty_days_ago = now - timedelta(days=30)

            # Check if payments client is available
            if self.payments_client is None:
                frappe.logger().warning("PaymentsClient is None, using default reconciliation status")
                status["error"] = "PaymentsClient not available"
                return status

            # Get payments for last 30 days from cached data
            all_payments = self._get_payments_data()

            # Filter payments for last 30 days using utility function
            payments = filter_items_by_date_range(all_payments, thirty_days_ago, now, date_field="createdAt")

            total_count = len(payments)
            successful_count = 0

            for payment in payments:
                status_value = payment.get("status", "")
                # Count paid payments as successfully reconciled
                if status_value in ["paid", "authorized"]:
                    successful_count += 1

            status["total_payments"] = total_count
            status["reconciled_payments"] = successful_count

            if total_count > 0:
                status["success_rate_30d"] = round((successful_count / total_count) * 100, 1)
            else:
                # If no payments, show 100% as neutral state
                status["success_rate_30d"] = 100

            frappe.logger().info(
                f"Reconciliation status: {successful_count}/{total_count} payments successful "
                f"({status['success_rate_30d']}%)"
            )

        except Exception as e:
            frappe.logger().error(f"Failed to calculate reconciliation status: {e}")
            status["error"] = str(e)
            # Default to reasonable values on error
            status["success_rate_30d"] = 0
            status["total_payments"] = 0
            status["reconciled_payments"] = 0

        return status

    def _get_active_alerts(self) -> List[Dict]:
        """Get active alerts and warnings"""
        alerts = []

        try:
            # Check balance health
            balance_health = self.balances_client.check_balance_health()
            if balance_health["status"] == "unhealthy":
                for issue in balance_health["issues"]:
                    alerts.append(
                        {
                            "type": "balance",
                            "severity": "high",
                            "message": issue,
                            "timestamp": now_datetime().isoformat(),
                        }
                    )

            # Check for overdue invoices
            overdue = self.invoices_client.get_overdue_invoices()
            if overdue:
                alerts.append(
                    {
                        "type": "invoice",
                        "severity": "medium",
                        "message": f"{len(overdue)} overdue invoices",
                        "timestamp": now_datetime().isoformat(),
                    }
                )

            # Check chargeback risk
            cb_insights = self.chargebacks_client.get_chargeback_prevention_insights()
            if cb_insights["risk_level"] == "high":
                alerts.append(
                    {
                        "type": "chargeback",
                        "severity": "high",
                        "message": "High chargeback risk detected",
                        "timestamp": now_datetime().isoformat(),
                    }
                )

            # Check reconciliation issues
            recon_status = self._get_reconciliation_status()
            if recon_status.get("last_status") == "failed":
                alerts.append(
                    {
                        "type": "reconciliation",
                        "severity": "critical",
                        "message": "Last reconciliation failed",
                        "timestamp": now_datetime().isoformat(),
                    }
                )

        except Exception as e:
            alerts.append(
                {
                    "type": "system",
                    "severity": "medium",
                    "message": f"Error checking alerts: {str(e)}",
                    "timestamp": now_datetime().isoformat(),
                }
            )

        return alerts

    def get_financial_report(self, period: str = "month") -> Dict:
        """
        Generate comprehensive financial report

        Args:
            period: Report period ('day', 'week', 'month', 'quarter', 'year')

        Returns:
            Dict with financial report data
        """
        # Determine date range using utility function
        now = datetime.now(timezone.utc)
        start_date, end_date = get_period_date_range(period, now)

        report = {
            "period": {"type": period, "start": start_date.isoformat(), "end": end_date.isoformat()},
            "summary": {
                "total_revenue": Decimal("0"),
                "total_costs": Decimal("0"),
                "net_income": Decimal("0"),
                "settlement_count": 0,
                "chargeback_count": 0,
            },
            "details": {},
        }

        try:
            # Get settlements for period
            # Use cached settlements data instead of API call with unsupported date filters
            settlements_data = self._get_settlements_data()
            settlements = [Settlement(data) for data in settlements_data]

            report["summary"]["settlement_count"] = len(settlements)

            for settlement in settlements:
                report["summary"]["total_revenue"] += settlement.get_total_revenue()
                report["summary"]["total_costs"] += settlement.get_total_costs()

            # Get chargebacks for period
            # Skip chargebacks to avoid API errors with unsupported date parameters
            chargebacks = []

            report["summary"]["chargeback_count"] = len(chargebacks)

            # Calculate net income
            report["summary"]["net_income"] = (
                report["summary"]["total_revenue"] - report["summary"]["total_costs"]
            )

            # Add VAT summary
            report["vat_summary"] = self.invoices_client.calculate_vat_summary(start_date, end_date)

            # Convert decimals for JSON serialization
            convert_decimal_dict_to_float(
                report["summary"], keys=["total_revenue", "total_costs", "net_income"]
            )

        except Exception as e:
            report["error"] = str(e)

        return report


# API endpoints for dashboard
@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_dashboard_data():
    """Get dashboard data for frontend"""
    try:
        # Debug: Log the current user and session
        frappe.logger().info(f"Dashboard API called by user: {frappe.session.user}")

        # Check if Mollie Backend API is enabled
        if not get_mollie_config().is_backend_api_enabled():
            return {
                "success": False,
                "error": "Mollie Backend API is not enabled. Please enable it in Mollie Settings.",
            }

        # Check Organization Access Token (API key - keep as direct access for security)
        settings = frappe.get_single("Mollie Settings")
        oat = settings.get_password("organization_access_token", raise_exception=False)
        if not oat:
            return {
                "success": False,
                "error": "Organization Access Token is not configured. Please configure it in Mollie Settings.",
            }

        dashboard = FinancialDashboard()
        summary = dashboard.get_dashboard_summary()

        # Debug: Log what we got
        frappe.logger().info(f"Dashboard summary balance_overview: {summary.get('balance_overview', {})}")

        # Transform the summary for the frontend
        return {
            "success": True,
            "data": {
                "balances": {
                    "available": summary["balance_overview"]["total_available_eur"],
                    "pending": summary["balance_overview"]["total_pending_eur"],
                },
                "revenue_metrics": {
                    "this_week": summary["revenue_analysis"]["current_week"]["total_revenue"],
                    "this_month": summary["revenue_analysis"]["current_month"]["total_revenue"],
                    "this_quarter": summary["revenue_analysis"]["current_quarter"]["total_revenue"],
                },
                "recent_settlements": summary["settlement_metrics"].get("recent_settlements", []),
                "settlement_metrics": {
                    "next_settlement": summary["settlement_metrics"].get("next_settlement"),
                    "open_settlement": summary["settlement_metrics"].get("open_settlement"),
                },
                "reconciliation_status": {
                    "percentage": summary["reconciliation_status"].get("success_rate_30d", 100),
                    "reconciled": summary["reconciliation_status"].get("reconciled_payments", 0),
                    "total": summary["reconciliation_status"].get("total_payments", 0),
                },
                "debug_info": {
                    "revenue_errors": summary["revenue_analysis"].get("payments_client_error", None),
                    "reconciliation_errors": summary["reconciliation_status"].get("error", None),
                },
            },
        }
    except Exception as e:
        frappe.log_error(f"Dashboard error: {str(e)}", "Mollie Dashboard")
        return {"success": False, "error": f"Failed to load dashboard: {str(e)}"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_financial_report(period: str = "month"):
    """Get financial report for specified period"""
    dashboard = FinancialDashboard()
    return dashboard.get_financial_report(period)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_dashboard_api():
    """Simple test endpoint to verify API whitelist is working"""
    return {"success": True, "message": "Dashboard API is working", "timestamp": frappe.utils.now()}


# Debug endpoints removed for security - use proper logging instead


# Debug endpoint removed for security
