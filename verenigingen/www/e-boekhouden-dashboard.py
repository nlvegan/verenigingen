import json

import frappe
from frappe import _


def get_context(context):
    """Get context for dashboard page"""
    context.title = _("E-Boekhouden Migration Dashboard")

    # Check permissions - use a more permissive check
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to view dashboard"))

    try:
        # Get dashboard data
        dashboard_data = get_dashboard_data()
        context.update(dashboard_data)

    except Exception as e:
        frappe.log_error(f"Dashboard error: {str(e)}")
        context.error = str(e)
        # Provide fallback data
        context.migration_stats = {"total": 0, "completed": 0, "in_progress": 0, "failed": 0, "draft": 0}
        context.connection_status = "Unknown"
        context.available_data = {"accounts": 0, "cost_centers": 0, "customers": 0, "suppliers": 0}
        context.recent_migrations = []
        context.system_health = {"status": "unknown", "issues": [str(e)]}


def get_dashboard_data():
    """Get comprehensive dashboard data"""
    from verenigingen.utils.eboekhouden_api import EBoekhoudenAPI

    data = {}

    try:
        # Connection status
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenAPI(settings)

        connection_test = api.get_chart_of_accounts()
        data["connection_status"] = "Connected" if connection_test["success"] else "Disconnected"
        data["connection_error"] = connection_test.get("error", "") if not connection_test["success"] else ""

        # Migration statistics
        data["migration_stats"] = {
            "total": frappe.db.count("E-Boekhouden Migration"),
            "completed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Completed"}),
            "in_progress": frappe.db.count("E-Boekhouden Migration", {"migration_status": "In Progress"}),
            "failed": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Failed"}),
            "draft": frappe.db.count("E-Boekhouden Migration", {"migration_status": "Draft"}),
        }

        # Available data counts
        data["available_data"] = get_available_data_counts(api)

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
        data["migration_summary"] = get_migration_summary()

        # System health
        data["system_health"] = get_system_health()

    except Exception as e:
        frappe.log_error(f"Error getting dashboard data: {str(e)}")
        data["error"] = str(e)

    return data


def get_available_data_counts(api):
    """Get counts of available data from e-Boekhouden"""
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


def get_migration_summary():
    """Get migration summary statistics"""
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


def get_system_health():
    """Get system health indicators"""
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
        stuck_migrations = frappe.db.count(
            "E-Boekhouden Migration",
            {
                "migration_status": "In Progress",
                "start_time": ["<", frappe.utils.add_hours(frappe.utils.now(), -2)],
            },
        )

        if stuck_migrations > 0:
            health["issues"].append(f"{stuck_migrations} migrations may be stuck")
            health["status"] = "warning"

        # Check recent failures
        recent_failures = frappe.db.count(
            "E-Boekhouden Migration",
            {
                "migration_status": "Failed",
                "start_time": [">=", frappe.utils.add_days(frappe.utils.now(), -1)],
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


@frappe.whitelist(allow_guest=True)
def get_live_dashboard_data():
    """API endpoint for live dashboard updates"""
    try:
        return {"success": True, "data": get_dashboard_data()}
    except Exception as e:
        return {"success": False, "error": str(e)}
