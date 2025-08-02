"""
Admin Tools Page - System Health and Performance Monitoring
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

no_cache = 1


def json_encode_args(args_dict):
    """Safely encode arguments dict to JSON string"""
    if not args_dict:
        return ""
    return json.dumps(args_dict)


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

    # Invoice management tools
    context.invoice_tools = [
        {
            "title": "Invoice Generation Dashboard",
            "description": "View dues schedules summary and invoice generation status",
            "method": "verenigingen.utils.invoice_management.get_dues_schedules_summary",
            "icon": "fa fa-file-text-o",
            "color": "brand-primary",
        },
        {
            "title": "Validate Invoice System",
            "description": "Check system readiness for invoice generation and identify issues",
            "method": "verenigingen.utils.invoice_management.validate_invoice_generation_readiness",
            "icon": "fa fa-check-circle",
            "color": "brand-secondary",
        },
        {
            "title": "Bulk Generate Invoices (Dry Run)",
            "description": "Preview which invoices would be generated without creating them",
            "method": "verenigingen.utils.invoice_management.bulk_generate_dues_invoices",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_invoices": 20},
        },
        {
            "title": "Bulk Generate Invoices (Live)",
            "description": "Generate invoices for all eligible dues schedules",
            "method": "verenigingen.utils.invoice_management.bulk_generate_dues_invoices",
            "icon": "fa fa-bolt",
            "color": "brand-primary",
            "warning": "This will create actual invoices. Use after reviewing dry run results!",
            "args": {"dry_run": False, "max_invoices": 50},
        },
        {
            "title": "Cleanup Orphaned Schedules (Dry Run)",
            "description": "Preview orphaned dues schedules that would be cleaned up",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_schedules",
            "icon": "fa fa-search",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_cleanup": 10},
        },
        {
            "title": "Cleanup Orphaned Schedules (Live)",
            "description": "Remove orphaned dues schedules that reference deleted members",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_schedules",
            "icon": "fa fa-trash",
            "color": "brand-primary",
            "warning": "This will permanently delete orphaned dues schedules!",
            "args": {"dry_run": False, "max_cleanup": 20},
        },
    ]

    # System administration tools
    context.system_tools = [
        {
            "title": "System Health Check",
            "description": "Check database, cache, and API performance status",
            "method": "verenigingen.utils.performance_dashboard.get_system_health",
            "icon": "fa fa-heartbeat",
            "color": "brand-secondary",
        },
        {
            "title": "Performance Dashboard",
            "description": "24-hour performance metrics and analysis",
            "method": "verenigingen.utils.performance_dashboard.get_performance_dashboard",
            "icon": "fa fa-dashboard",
            "color": "brand-accent",
        },
        {
            "title": "Database Analysis",
            "description": "Analyze slow queries and get index recommendations",
            "method": "verenigingen.utils.database_query_analyzer.analyze_database_performance",
            "icon": "fa fa-database",
            "color": "brand-primary",
        },
        {
            "title": "Index Recommendations",
            "description": "Get and apply database index recommendations",
            "method": "verenigingen.utils.database_query_analyzer.get_index_recommendations",
            "icon": "fa fa-search",
            "color": "brand-accent",
        },
        {
            "title": "API Documentation",
            "description": "Generate API documentation in multiple formats",
            "method": "verenigingen.utils.api_doc_generator.generate_api_documentation",
            "icon": "fa fa-book",
            "color": "brand-secondary",
        },
        {
            "title": "Optimization Suggestions",
            "description": "Get specific optimization recommendations",
            "method": "verenigingen.utils.performance_dashboard.get_optimization_suggestions",
            "icon": "fa fa-lightbulb-o",
            "color": "brand-accent",
        },
        {
            "title": "API Endpoint Summary",
            "description": "View all available API endpoints",
            "method": "verenigingen.utils.api_doc_generator.get_api_endpoints_summary",
            "icon": "fa fa-plug",
            "color": "brand-primary",
        },
        {
            "title": "Fraud Detection Stats",
            "description": "View fraud detection statistics",
            "method": "verenigingen.utils.fraud_detection.get_fraud_statistics",
            "icon": "fa fa-shield",
            "color": "brand-secondary",
        },
        {
            "title": "Test Cleanup (Small Batch)",
            "description": "Test cleanup process on a small batch of documents to verify functionality",
            "method": "verenigingen.e_boekhouden.utils.cleanup_utils.test_cleanup_small_batch",
            "icon": "fa fa-flask",
            "color": "brand-accent",
        },
        {
            "title": "Cleanup Orphaned GL Entries",
            "description": "Clean up GL entries, Payment Entry References, and Payment Ledger Entries that reference deleted documents",
            "method": "verenigingen.e_boekhouden.utils.cleanup_utils.cleanup_orphaned_gl_entries",
            "icon": "fa fa-eraser",
            "color": "brand-secondary",
        },
        {
            "title": "Cleanup Imported Data",
            "description": "Clean up all e-Boekhouden imported data for fresh migration",
            "method": "verenigingen.e_boekhouden.utils.cleanup_utils.nuclear_cleanup_all_imported_data",
            "icon": "fa fa-trash-o",
            "color": "brand-primary",
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
            "command": "bench --site dev.veganisme.net execute verenigingen.e_boekhouden.utils.cleanup_utils.nuclear_cleanup_all_imported_data",
        },
        {
            "description": "View dues schedules summary",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.get_dues_schedules_summary",
        },
        {
            "description": "Validate invoice generation readiness",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.validate_invoice_generation_readiness",
        },
        {
            "description": "Bulk generate invoices (dry run)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.bulk_generate_dues_invoices --kwargs=\'{"dry_run": true, "max_invoices": 20}\'',
        },
        {
            "description": "Generate invoices for real (max 50)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.bulk_generate_dues_invoices --kwargs=\'{"dry_run": false, "max_invoices": 50}\'',
        },
        {
            "description": "Cleanup orphaned schedules (dry run)",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.cleanup_orphaned_schedules --kwargs='{\"dry_run\": true}'",
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
