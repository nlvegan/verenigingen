"""
Financial Dashboard for Mollie Backend
Provides comprehensive financial insights and reporting
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime, now_datetime

from ..clients.balances_client import BalancesClient
from ..clients.chargebacks_client import ChargebacksClient
from ..clients.invoices_client import InvoicesClient
from ..clients.settlements_client import SettlementsClient
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

    def __init__(self, settings_name: str):
        """Initialize dashboard"""
        self.settings_name = settings_name

        # Initialize API clients
        self.balances_client = BalancesClient(settings_name)
        self.settlements_client = SettlementsClient(settings_name)
        self.invoices_client = InvoicesClient(settings_name)
        self.chargebacks_client = ChargebacksClient(settings_name)
        self.reconciliation_engine = ReconciliationEngine(settings_name)

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
        now = datetime.now()
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
            balances = self.balances_client.list_balances()

            for balance in balances:
                balance_info = {
                    "currency": balance.currency,
                    "available": float(balance.available_amount.decimal_value)
                    if balance.available_amount
                    else 0,
                    "pending": float(balance.pending_amount.decimal_value) if balance.pending_amount else 0,
                    "status": balance.status,
                }

                overview["balances"].append(balance_info)

                # Convert to EUR for totals (simplified - would use actual rates)
                if balance.currency == "EUR":
                    overview["total_available_eur"] += Decimal(str(balance_info["available"]))
                    overview["total_pending_eur"] += Decimal(str(balance_info["pending"]))

            # Check health
            health = self.balances_client.check_balance_health()
            overview["health_status"] = health["status"]

            # Convert decimals to float for JSON
            overview["total_available_eur"] = float(overview["total_available_eur"])
            overview["total_pending_eur"] = float(overview["total_pending_eur"])

        except Exception as e:
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
            "next_settlement": None,
            "open_settlement": None,
        }

        try:
            # Current month settlements
            now = datetime.now()
            month_start = now.replace(day=1)

            settlements = self.settlements_client.list_settlements(from_date=month_start, until_date=now)

            for settlement in settlements:
                metrics["current_month"]["count"] += 1

                if settlement.amount:
                    metrics["current_month"]["total_amount"] += settlement.amount.decimal_value

                # Count by status
                status = settlement.status or "unknown"
                if status not in metrics["current_month"]["by_status"]:
                    metrics["current_month"]["by_status"][status] = 0
                metrics["current_month"]["by_status"][status] += 1

            # Calculate average
            if metrics["current_month"]["count"] > 0:
                metrics["current_month"]["average_amount"] = (
                    metrics["current_month"]["total_amount"] / metrics["current_month"]["count"]
                )

            # Last 30 days
            thirty_days_ago = now - timedelta(days=30)
            recent_settlements = self.settlements_client.list_settlements(
                from_date=thirty_days_ago, until_date=now
            )

            metrics["last_30_days"]["count"] = len(recent_settlements)
            metrics["last_30_days"]["total_amount"] = sum(
                s.amount.decimal_value for s in recent_settlements if s.amount
            )

            # Get next and open settlements
            next_settlement = self.settlements_client.get_next_settlement()
            if next_settlement:
                metrics["next_settlement"] = {
                    "id": next_settlement.id,
                    "expected_amount": float(next_settlement.amount.decimal_value)
                    if next_settlement.amount
                    else 0,
                }

            open_settlement = self.settlements_client.get_open_settlement()
            if open_settlement:
                metrics["open_settlement"] = {
                    "id": open_settlement.id,
                    "current_amount": float(open_settlement.amount.decimal_value)
                    if open_settlement.amount
                    else 0,
                }

            # Convert decimals
            metrics["current_month"]["total_amount"] = float(metrics["current_month"]["total_amount"])
            metrics["current_month"]["average_amount"] = float(metrics["current_month"]["average_amount"])
            metrics["last_30_days"]["total_amount"] = float(metrics["last_30_days"]["total_amount"])

        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _get_revenue_analysis(self) -> Dict:
        """Analyze revenue streams"""
        analysis = {
            "current_month": {
                "payment_revenue": Decimal("0"),
                "subscription_revenue": Decimal("0"),
                "total_revenue": Decimal("0"),
            },
            "ytd": {"total_revenue": Decimal("0"), "monthly_average": Decimal("0")},  # Year to date
            "growth_rate": 0,
            "top_revenue_days": [],
        }

        try:
            # Get current month data from settlements
            now = datetime.now()
            month_start = now.replace(day=1)
            year_start = now.replace(month=1, day=1)

            # Current month settlements
            settlements = self.settlements_client.list_settlements(from_date=month_start, until_date=now)

            for settlement in settlements:
                revenue = settlement.get_total_revenue()
                analysis["current_month"]["total_revenue"] += revenue

            # YTD settlements
            ytd_settlements = self.settlements_client.list_settlements(from_date=year_start, until_date=now)

            for settlement in ytd_settlements:
                analysis["ytd"]["total_revenue"] += settlement.get_total_revenue()

            # Calculate monthly average
            months_elapsed = now.month
            if months_elapsed > 0:
                analysis["ytd"]["monthly_average"] = analysis["ytd"]["total_revenue"] / months_elapsed

            # Calculate growth rate (compare to previous month)
            prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
            prev_month_end = month_start - timedelta(days=1)

            prev_settlements = self.settlements_client.list_settlements(
                from_date=prev_month_start, until_date=prev_month_end
            )

            prev_revenue = sum(s.get_total_revenue() for s in prev_settlements)

            if prev_revenue > 0:
                growth = ((analysis["current_month"]["total_revenue"] - prev_revenue) / prev_revenue) * 100
                analysis["growth_rate"] = float(growth)

            # Convert decimals
            analysis["current_month"]["total_revenue"] = float(analysis["current_month"]["total_revenue"])
            analysis["ytd"]["total_revenue"] = float(analysis["ytd"]["total_revenue"])
            analysis["ytd"]["monthly_average"] = float(analysis["ytd"]["monthly_average"])

        except Exception as e:
            analysis["error"] = str(e)

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
            now = datetime.now()
            month_start = now.replace(day=1)

            settlements = self.settlements_client.list_settlements(from_date=month_start, until_date=now)

            for settlement in settlements:
                costs = settlement.get_total_costs()
                breakdown["current_month"]["total_costs"] += costs

            # Get chargeback costs
            chargebacks = self.chargebacks_client.list_all_chargebacks(from_date=month_start, until_date=now)

            for chargeback in chargebacks:
                if chargeback.settlement_amount:
                    # Chargeback fees are typically the difference
                    fee = abs(chargeback.settlement_amount.decimal_value) - (
                        chargeback.amount.decimal_value if chargeback.amount else Decimal("0")
                    )
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

            # Convert decimals
            breakdown["current_month"]["transaction_fees"] = float(
                breakdown["current_month"]["transaction_fees"]
            )
            breakdown["current_month"]["chargeback_fees"] = float(
                breakdown["current_month"]["chargeback_fees"]
            )
            breakdown["current_month"]["refund_costs"] = float(breakdown["current_month"]["refund_costs"])
            breakdown["current_month"]["total_costs"] = float(breakdown["current_month"]["total_costs"])

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
            now = datetime.now()
            month_start = now.replace(day=1)

            chargebacks = self.chargebacks_client.list_all_chargebacks(from_date=month_start, until_date=now)

            metrics["current_month"]["count"] = len(chargebacks)

            for chargeback in chargebacks:
                if chargeback.amount:
                    metrics["current_month"]["total_amount"] += chargeback.amount.decimal_value

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

            # Convert decimals
            metrics["current_month"]["total_amount"] = float(metrics["current_month"]["total_amount"])
            metrics["current_month"]["net_loss"] = float(metrics["current_month"]["net_loss"])

        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _get_reconciliation_status(self) -> Dict:
        """Get reconciliation status and history"""
        status = {
            "last_run": None,
            "last_status": None,
            "success_rate_30d": 0,
            "recent_issues": [],
            "trend_analysis": {},
        }

        try:
            # Get reconciliation history
            history = self.reconciliation_engine.get_reconciliation_history(30)

            if history:
                # Last run info
                last_run = history[0]
                status["last_run"] = last_run["date"]
                status["last_status"] = last_run["status"]

                # Calculate success rate
                successful = sum(1 for r in history if r["status"] == "completed")
                status["success_rate_30d"] = (successful / len(history)) * 100

                # Get recent issues
                for record in history[:5]:
                    if record["error_count"] > 0 or record["warning_count"] > 0:
                        status["recent_issues"].append(
                            {
                                "date": record["date"],
                                "errors": record["error_count"],
                                "warnings": record["warning_count"],
                            }
                        )

            # Get trend analysis
            status["trend_analysis"] = self.reconciliation_engine.analyze_reconciliation_trends()

        except Exception as e:
            status["error"] = str(e)

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
        # Determine date range
        now = datetime.now()
        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now.replace(day=1)
        elif period == "quarter":
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            start_date = now.replace(month=quarter_start_month, day=1)
        else:  # year
            start_date = now.replace(month=1, day=1)

        report = {
            "period": {"type": period, "start": start_date.isoformat(), "end": now.isoformat()},
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
            settlements = self.settlements_client.list_settlements(from_date=start_date, until_date=now)

            report["summary"]["settlement_count"] = len(settlements)

            for settlement in settlements:
                report["summary"]["total_revenue"] += settlement.get_total_revenue()
                report["summary"]["total_costs"] += settlement.get_total_costs()

            # Get chargebacks for period
            chargebacks = self.chargebacks_client.list_all_chargebacks(from_date=start_date, until_date=now)

            report["summary"]["chargeback_count"] = len(chargebacks)

            # Calculate net income
            report["summary"]["net_income"] = (
                report["summary"]["total_revenue"] - report["summary"]["total_costs"]
            )

            # Add VAT summary
            report["vat_summary"] = self.invoices_client.calculate_vat_summary(start_date, now)

            # Convert decimals
            report["summary"]["total_revenue"] = float(report["summary"]["total_revenue"])
            report["summary"]["total_costs"] = float(report["summary"]["total_costs"])
            report["summary"]["net_income"] = float(report["summary"]["net_income"])

        except Exception as e:
            report["error"] = str(e)

        return report


# API endpoints for dashboard
@frappe.whitelist()
def get_dashboard_data(settings_name: Optional[str] = None):
    """Get dashboard data for frontend"""
    if not settings_name:
        settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)
        if not settings:
            return {"error": "No active Mollie backend API settings"}
        settings_name = settings[0]["name"]

    dashboard = FinancialDashboard(settings_name)
    return dashboard.get_dashboard_summary()


@frappe.whitelist()
def get_financial_report(period: str = "month", settings_name: Optional[str] = None):
    """Get financial report for specified period"""
    if not settings_name:
        settings = frappe.get_all("Mollie Settings", filters={"enable_backend_api": True}, limit=1)
        if not settings:
            return {"error": "No active Mollie backend API settings"}
        settings_name = settings[0]["name"]

    dashboard = FinancialDashboard(settings_name)
    return dashboard.get_financial_report(period)
