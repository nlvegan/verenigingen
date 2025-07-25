"""
Admin Tools Page - System Health and Performance Monitoring
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

no_cache = 1


def get_context(context):
    """Build context for admin tools page"""

    # Check permissions
    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    context.title = "System Admin Tools"
    context.no_cache = 1

    # Get quick system health
    try:
        from verenigingen.utils.performance_dashboard import get_system_health

        context.system_health = get_system_health()
    except Exception as e:
        context.system_health = {"status": "error", "error": str(e)}

    # Get database statistics summary
    try:
        from verenigingen.utils.database_query_analyzer import get_table_statistics

        stats = get_table_statistics()
        if stats.get("success"):
            context.db_stats = stats.get("summary", {})
        else:
            context.db_stats = {"error": "Failed to load database statistics"}
    except Exception as e:
        context.db_stats = {"error": str(e)}

    # Available tools
    context.available_tools = [
        {
            "title": "System Health Check",
            "description": "Check database, cache, and API performance status",
            "method": "verenigingen.utils.performance_dashboard.get_system_health",
            "icon": "fa fa-heartbeat",
            "color": "green",
        },
        {
            "title": "Performance Dashboard",
            "description": "24-hour performance metrics and analysis",
            "method": "verenigingen.utils.performance_dashboard.get_performance_dashboard",
            "icon": "fa fa-dashboard",
            "color": "blue",
        },
        {
            "title": "Database Analysis",
            "description": "Analyze slow queries and get index recommendations",
            "method": "verenigingen.utils.database_query_analyzer.analyze_database_performance",
            "icon": "fa fa-database",
            "color": "purple",
        },
        {
            "title": "Index Recommendations",
            "description": "Get and apply database index recommendations",
            "method": "verenigingen.utils.database_query_analyzer.get_index_recommendations",
            "icon": "fa fa-search",
            "color": "orange",
        },
        {
            "title": "API Documentation",
            "description": "Generate API documentation in multiple formats",
            "method": "verenigingen.utils.api_doc_generator.generate_api_documentation",
            "icon": "fa fa-book",
            "color": "teal",
        },
        {
            "title": "Optimization Suggestions",
            "description": "Get specific optimization recommendations",
            "method": "verenigingen.utils.performance_dashboard.get_optimization_suggestions",
            "icon": "fa fa-lightbulb-o",
            "color": "yellow",
        },
        {
            "title": "API Endpoint Summary",
            "description": "View all available API endpoints",
            "method": "verenigingen.utils.api_doc_generator.get_api_endpoints_summary",
            "icon": "fa fa-plug",
            "color": "indigo",
        },
        {
            "title": "Fraud Detection Stats",
            "description": "View fraud detection statistics",
            "method": "verenigingen.utils.fraud_detection.get_fraud_statistics",
            "icon": "fa fa-shield",
            "color": "red",
        },
        {
            "title": "Cleanup Imported Data",
            "description": "Clean up all e-Boekhouden imported data for fresh migration",
            "method": "verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.debug_cleanup_all_imported_data",
            "icon": "fa fa-trash-o",
            "color": "danger",
            "warning": "This will permanently delete all imported e-Boekhouden data. Use with caution!",
        },
    ]

    # Add command examples
    context.command_examples = [
        {
            "description": "Check system health",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_system_health",
        },
        {
            "description": "Get 48-hour performance report",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.performance_dashboard.get_api_performance_summary --hours=48",
        },
        {
            "description": "Apply database optimizations",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.api_endpoint_optimizer.run_api_optimization --dry_run=False",
        },
        {
            "description": "Clean up all e-Boekhouden imported data",
            "command": "bench --site dev.veganisme.net execute verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.debug_cleanup_all_imported_data",
        },
    ]

    return context


@frappe.whitelist()
def execute_admin_tool(method, args=None):
    """Execute an admin tool method"""

    # Check permissions
    if not (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles()
        or "Verenigingen Administrator" in frappe.get_roles()
    ):
        frappe.throw(_("Insufficient permissions"))

    try:
        # Import the module and call the method directly
        from importlib import import_module

        # Split module and function
        if "." not in method:
            raise ValueError(f"Invalid method path: {method}")
        module_path, function_name = method.rsplit(".", 1)
        module = import_module(module_path)
        func = getattr(module, function_name)

        if args:
            import json

            args = json.loads(args) if isinstance(args, str) else args
            result = func(**args)
        else:
            result = func()

        return {"success": True, "result": result, "timestamp": now_datetime()}
    except Exception as e:
        frappe.log_error(f"Admin tool execution failed: {str(e)}", "Admin Tools")
        return {"success": False, "error": str(e), "timestamp": now_datetime()}
