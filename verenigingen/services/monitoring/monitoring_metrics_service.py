"""
Monitoring Metrics Service

Provides system metrics collection, error tracking, audit summaries,
and performance monitoring for the monitoring dashboard.

This service consolidates metrics gathering logic that was previously
scattered across portal controllers.
"""

from typing import Any, Dict, List

import frappe
from frappe.utils import add_to_date, now, today

from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class MonitoringMetricsService:
    """
    Service for collecting and aggregating system monitoring metrics.

    This service provides:
    - Real-time system metrics (members, volunteers, SEPA, errors, invoices)
    - Error log analysis and summaries
    - SEPA audit trail summaries
    - Active system alerts
    - Performance metrics (database, system, business)
    """

    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get real-time system metrics.

        Returns:
            Dict containing counts for members, volunteers, SEPA, errors, and invoices.
        """
        try:
            return {
                "members": {
                    "active": frappe.db.count("Member", {"status": "Active"}),
                    "pending": frappe.db.count("Member", {"status": "Pending"}),
                    "terminated": frappe.db.count("Member", {"status": "Quit"}),
                    "total": frappe.db.count("Member"),
                },
                "volunteers": {
                    "active": frappe.db.count("Volunteer", {"status": "Active"}),
                    "total": frappe.db.count("Volunteer"),
                },
                "sepa": {
                    "active_mandates": frappe.db.count("SEPA Mandate", {"status": "Active"}),
                    "recent_batches": frappe.db.count(
                        "Direct Debit Batch",
                        {"creation": (">=", add_to_date(now(), days=-7))},
                    ),
                    "pending_payments": frappe.db.count(
                        "Payment Entry",
                        {"docstatus": 0, "payment_type": "Receive"},
                    ),
                },
                "errors": {
                    "last_hour": frappe.db.count(
                        "Error Log",
                        {"creation": (">=", add_to_date(now(), hours=-1))},
                    ),
                    "last_24h": frappe.db.count(
                        "Error Log",
                        {"creation": (">=", add_to_date(now(), days=-1))},
                    ),
                    "last_week": frappe.db.count(
                        "Error Log",
                        {"creation": (">=", add_to_date(now(), days=-7))},
                    ),
                },
                "invoices": {
                    "draft": frappe.db.count("Sales Invoice", {"docstatus": 0}),
                    "submitted": frappe.db.count("Sales Invoice", {"docstatus": 1}),
                    "paid": frappe.db.count("Sales Invoice", {"docstatus": 1, "status": "Paid"}),
                },
            }
        except Exception as e:
            frappe.log_error(f"Error getting system metrics: {str(e)}")
            return {"error": str(e)}

    def get_recent_errors(self) -> List[Dict[str, Any]]:
        """
        Get recent error summary grouped by error type.

        Returns:
            List of error summaries with counts and timestamps.
        """
        try:
            return frappe.db.sql(
                """
                SELECT
                    SUBSTRING(error, 1, 100) as error_summary,
                    COUNT(*) as count,
                    MAX(creation) as latest,
                    MIN(creation) as first_occurrence
                FROM `tabError Log`
                WHERE creation >= %s
                GROUP BY SUBSTRING(error, 1, 100)
                ORDER BY count DESC, latest DESC
                LIMIT 10
            """,
                [add_to_date(now(), days=-1)],
                as_dict=True,
            )
        except Exception as e:
            frappe.log_error(f"Error getting recent errors: {str(e)}")
            return []

    def get_audit_summary(self) -> List[Dict[str, Any]]:
        """
        Get SEPA audit trail summary.

        Returns:
            List of audit entries grouped by process type and action.
        """
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                return []

            return frappe.db.sql(
                """
                SELECT
                    process_type,
                    action,
                    compliance_status,
                    COUNT(*) as count,
                    MAX(timestamp) as latest
                FROM `tabSEPA Audit Log`
                WHERE timestamp >= %s
                GROUP BY process_type, action, compliance_status
                ORDER BY count DESC
                LIMIT 15
            """,
                [add_to_date(now(), days=-7)],
                as_dict=True,
            )
        except Exception as e:
            frappe.log_error(f"Error getting audit summary: {str(e)}")
            return []

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """
        Get active system alerts.

        Returns:
            List of active or acknowledged system alerts.
        """
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "System Alert"):
                return []

            return frappe.get_all(
                "System Alert",
                filters={"status": ["in", ["Active", "Acknowledged"]]},
                fields=["name", "alert_type", "severity", "message", "status", "timestamp"],
                order_by="timestamp DESC",
                limit=20,
            )
        except Exception as e:
            frappe.log_error(f"Error getting active alerts: {str(e)}")
            return []

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for database, system, and business operations.

        Returns:
            Dict containing database, system, and business performance indicators.
        """
        try:
            return {
                "database": {
                    "total_tables": self._get_table_count(),
                    "error_logs_size": frappe.db.count("Error Log"),
                    "recent_queries": self._get_slow_query_count(),
                },
                "system": {
                    "active_users": frappe.db.count("User", {"enabled": 1}),
                    "background_jobs": self._get_background_job_count(),
                    "cache_status": "OK",
                },
                "business": {
                    "daily_transactions": self._get_daily_transaction_count(),
                    "payment_success_rate": self._get_payment_success_rate(),
                    "member_growth": self._get_member_growth_rate(),
                },
            }
        except Exception as e:
            frappe.log_error(f"Error getting performance metrics: {str(e)}")
            return {"error": str(e)}

    def get_all_dashboard_data(self) -> Dict[str, Any]:
        """
        Get all dashboard data in a single call.

        Returns:
            Dict containing all metrics for the monitoring dashboard.
        """
        return {
            "system_metrics": self.get_system_metrics(),
            "recent_errors": self.get_recent_errors(),
            "audit_summary": self.get_audit_summary(),
            "alerts": self.get_active_alerts(),
            "performance_metrics": self.get_performance_metrics(),
            "timestamp": now(),
        }

    # Private helper methods

    def _get_table_count(self) -> int:
        """Get count of tables in the database."""
        try:
            result = frappe.db.sql(
                "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = %s",
                [frappe.conf.db_name],
                as_dict=True,
            )
            return result[0]["count"] if result else 0
        except Exception:
            return 0

    def _get_slow_query_count(self) -> int:
        """Get count of potential slow queries (timeout-related errors)."""
        try:
            return frappe.db.count(
                "Error Log",
                {
                    "error": ("like", "%timeout%"),
                    "creation": (">=", add_to_date(now(), hours=-1)),
                },
            )
        except Exception as e:
            frappe.log_error(
                message=f"Error counting slow queries: {str(e)}",
                title="Monitoring - Slow Query Count Error",
            )
            return 0

    def _get_background_job_count(self) -> int:
        """Get background job queue length.

        RQ Job is a virtual DocType backed by Redis (no `tabRQ Job` table), so a raw
        `frappe.db.count` issues SQL against a missing table and errors. Query through the
        ORM instead, which dispatches to the virtual DocType controller.
        """
        try:
            return len(frappe.get_all("RQ Job", filters={"status": "queued"}, fields=["name"]))
        except Exception as e:
            frappe.log_error(
                message=f"Error counting background jobs: {str(e)}",
                title="Monitoring - Background Job Count Error",
            )
            return 0

    def _get_daily_transaction_count(self) -> int:
        """Get daily transaction count."""
        try:
            return frappe.db.count(
                "Payment Entry",
                {"creation": (">=", today()), "docstatus": 1},
            )
        except Exception as e:
            frappe.log_error(
                message=f"Error counting daily transactions: {str(e)}",
                title="Monitoring - Daily Transaction Count Error",
            )
            return 0

    def _get_payment_success_rate(self) -> float:
        """Get payment success rate for today."""
        try:
            total_today = frappe.db.count(
                "Payment Entry",
                {"creation": (">=", today())},
            )
            if total_today == 0:
                return 100.0

            failed_today = frappe.db.count(
                "Payment Entry",
                {"creation": (">=", today()), "docstatus": 2},  # Cancelled
            )

            return round(((total_today - failed_today) / total_today) * 100, 2)
        except Exception as e:
            frappe.log_error(
                message=f"Error calculating payment success rate: {str(e)}",
                title="Monitoring - Payment Success Rate Error",
            )
            return 100.0

    def _get_member_growth_rate(self) -> Dict[str, Any]:
        """Get member growth rate."""
        try:
            today_count = frappe.db.count(
                "Member",
                {"creation": (">=", today())},
            )
            week_count = frappe.db.count(
                "Member",
                {"creation": (">=", add_to_date(today(), days=-7))},
            )

            return {
                "today": today_count,
                "week": week_count,
                "daily_average": round(week_count / 7, 1),
            }
        except Exception as e:
            frappe.log_error(
                message=f"Error calculating member growth rate: {str(e)}",
                title="Monitoring - Member Growth Rate Error",
            )
            # The cause, not zeros: this dict is one entry of the metrics payload
            # get_performance_metrics() builds, and three zeros there read as "no
            # members joined" (#593). No in-repo consumer indexes these keys, so
            # dropping them is safe; raising instead would blank every sibling
            # metric on the dashboard.
            return {"error": str(e)}
