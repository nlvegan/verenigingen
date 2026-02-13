"""
E-Boekhouden Dashboard Service

Handles all data fetching and aggregation for the E-Boekhouden migration dashboard.
Extracted from the e_boekhouden_dashboard.py template controller to follow
service-oriented architecture.

All methods are read-only queries -- no transaction management needed.
"""

import json
from typing import Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService


class EBoekhoudenDashboardService(StatelessService):
    """Service for fetching and assembling E-Boekhouden dashboard data.

    Inherits from StatelessService -- read-only queries, no state management.
    """

    def __init__(self):
        super().__init__(service_name="EBoekhoudenDashboardService")

    def get_dashboard_data(self) -> dict:
        """Get comprehensive dashboard data.

        Returns:
            dict: Dashboard data including connection status, migration stats,
                  available data counts, recent migrations, migration summary,
                  and system health indicators.
        """
        from verenigingen.e_boekhouden.utils.eboekhouden_api import EBoekhoudenAPI

        data = {}

        try:
            # Connection status
            settings = frappe.get_single("E-Boekhouden Settings")
            api = EBoekhoudenAPI(settings)

            connection_test = api.get_chart_of_accounts()
            data["connection_status"] = "Connected" if connection_test["success"] else "Disconnected"
            data["connection_error"] = (
                connection_test.get("error", "") if not connection_test["success"] else ""
            )

            # Migration statistics
            data["migration_stats"] = {
                "total": frappe.db.count("E-Boekhouden Migration"),
                "completed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Completed"}),
                "in_progress": frappe.db.count("E-Boekhouden Migration", {"migration_status": "In Progress"}),
                "failed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Failed"}),
                "draft": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Draft"}),
            }

            # Available data counts
            data["available_data"] = self._get_available_data_counts(api)

            # Recent migrations
            data["recent_migrations"] = frappe.get_all(
                "E-Boekhouden Migration",
                fields=[
                    "name",
                    "migration_name",
                    "migration_status",
                    "progress_percentage",
                    "start_time",
                    "end_time",
                ],
                order_by="start_time desc",
                limit=10,
            )

            # Migration summary by type
            data["migration_summary"] = self._get_migration_summary()

            # System health
            data["system_health"] = self._get_system_health()

        except Exception as e:
            frappe.log_error(f"Error getting dashboard data: {str(e)}")
            data["error"] = str(e)
            # Provide fallback data to prevent template errors
            data.setdefault(
                "migration_stats",
                {"total": 0, "completed": 0, "in_progress": 0, "failed": 0, "draft": 0},
            )
            data.setdefault("connection_status", "Unknown")
            data.setdefault(
                "available_data", {"accounts": 0, "cost_centers": 0, "customers": 0, "suppliers": 0}
            )
            data.setdefault("recent_migrations", [])
            data.setdefault("system_health", {"status": "unknown", "issues": [str(e)]})

        return data

    def _get_available_data_counts(self, api) -> dict:
        """Get counts of available data from e-Boekhouden.

        Args:
            api: An initialized EBoekhoudenAPI instance.

        Returns:
            dict: Counts for accounts, cost_centers, customers, and suppliers.
        """
        counts = {"accounts": 0, "cost_centers": 0, "customers": 0, "suppliers": 0}

        try:
            # Chart of Accounts
            result = api.get_chart_of_accounts()
            if result["success"]:
                data = json.loads(result["data"])
                counts["accounts"] = len(data.get("items", []))

            # Cost Centers
            result = api.get_cost_centers()
            if result["success"]:
                data = json.loads(result["data"])
                counts["cost_centers"] = len(data.get("items", []))

            # Customers
            result = api.get_customers()
            if result["success"]:
                data = json.loads(result["data"])
                counts["customers"] = len(data.get("items", []))

            # Suppliers
            result = api.get_suppliers()
            if result["success"]:
                data = json.loads(result["data"])
                counts["suppliers"] = len(data.get("items", []))

        except Exception as e:
            frappe.log_error(f"Error getting data counts: {str(e)}")

        return counts

    def _get_migration_summary(self) -> dict:
        """Get migration summary statistics.

        Returns:
            dict: Aggregated migration statistics for completed migrations.
        """
        try:
            summary = frappe.db.sql(
                """
                SELECT
                    SUM(CASE WHEN migrate_accounts = 1 THEN 1 ELSE 0 END) as accounts_migrations,
                    SUM(CASE WHEN migrate_cost_centers = 1 THEN 1 ELSE 0 END) as cost_center_migrations,
                    SUM(CASE WHEN migrate_customers = 1 THEN 1 ELSE 0 END) as customer_migrations,
                    SUM(CASE WHEN migrate_suppliers = 1 THEN 1 ELSE 0 END) as supplier_migrations,
                    SUM(CASE WHEN migrate_transactions = 1 THEN 1 ELSE 0 END) as transaction_migrations,
                    SUM(total_records) as total_records_processed,
                    SUM(imported_records) as successful_imports,
                    SUM(failed_records) as failed_imports
                FROM `tabE-Boekhouden Migration`
                WHERE migration_status = 'Completed'
            """,
                as_dict=True,
            )

            return summary[0] if summary else {}

        except Exception as e:
            frappe.log_error(f"Error getting migration summary: {str(e)}")
            return {}

    def _get_system_health(self) -> dict:
        """Get system health indicators.

        Returns:
            dict: Health status with a list of issues, if any.
        """
        health = {"status": "good", "issues": []}

        try:
            # Check if settings are configured
            settings = frappe.get_single("E-Boekhouden Settings")
            if not settings.api_token:
                health["issues"].append("API token not configured")
                health["status"] = "warning"

            if not settings.default_company:
                health["issues"].append("Default company not set")
                health["status"] = "warning"

            # Check for stuck migrations
            from frappe.utils import add_to_date, now

            two_hours_ago = add_to_date(now(), hours=-2)
            stuck_migrations = frappe.db.count(
                "E-Boekhouden Migration",
                {
                    "migration_status": "In Progress",
                    "start_time": ["<", two_hours_ago],
                },
            )

            if stuck_migrations > 0:
                health["issues"].append(f"{stuck_migrations} migrations may be stuck")
                health["status"] = "warning"

            # Check recent failures
            one_day_ago = add_to_date(now(), days=-1)
            recent_failures = frappe.db.count(
                "E-Boekhouden Migration",
                {
                    "migration_status": "Failed",
                    "start_time": [">=", one_day_ago],
                },
            )

            if recent_failures > 3:
                health["issues"].append(f"{recent_failures} recent failures")
                health["status"] = "error" if recent_failures > 10 else "warning"

            if not health["issues"]:
                health["status"] = "good"

        except Exception as e:
            health["status"] = "error"
            health["issues"].append(f"Health check failed: {str(e)}")

        return health


# Module-level singleton accessor
_service_instance: Optional[EBoekhoudenDashboardService] = None


def get_eboekhouden_dashboard_service() -> EBoekhoudenDashboardService:
    """Get or create the EBoekhoudenDashboardService singleton.

    Returns:
        EBoekhoudenDashboardService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = EBoekhoudenDashboardService()
    return _service_instance
