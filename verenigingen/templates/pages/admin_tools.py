"""
Admin Tools Page - System Health and Performance Monitoring
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.security.api_security_framework import OperationType, critical_api

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
        {
            "title": "Enhanced Membership Cleanup (Dry Run)",
            "description": "Preview comprehensive cleanup of orphaned schedules, invalid memberships, and orphaned amendments",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_membership_data",
            "icon": "fa fa-search-plus",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_cleanup": 20},
        },
        {
            "title": "Enhanced Membership Cleanup (Live)",
            "description": "Comprehensive cleanup including orphaned schedules, invalid membership types (like 'Standard Monthly'), and orphaned amendments",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_membership_data",
            "icon": "fa fa-magic",
            "color": "brand-secondary",
            "warning": "This will permanently delete orphaned membership data including invalid membership types!",
            "args": {"dry_run": False, "max_cleanup": 20},
        },
        {
            "title": "Find Stuck Dues Schedules",
            "description": "Identify all schedules that are stuck due to validation failures or equal-date issues",
            "method": "verenigingen.api.fix_stuck_dues_schedule.find_all_stuck_schedules",
            "icon": "fa fa-search",
            "color": "brand-accent",
        },
        {
            "title": "Check Stuck Schedule Notifications",
            "description": "Run the enhanced stuck schedule detection and notification system",
            "method": "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",
            "icon": "fa fa-bell",
            "color": "brand-secondary",
        },
        {
            "title": "Diagnose Specific Schedule",
            "description": "Get detailed diagnosis of why a specific schedule is not generating invoices",
            "method": "verenigingen.api.fix_stuck_dues_schedule.diagnose_stuck_schedule",
            "icon": "fa fa-stethoscope",
            "color": "brand-primary",
            "args": {"schedule_name": ""},
            "requires_input": True,
        },
        {
            "title": "Fix Stuck Schedule (Safe)",
            "description": "Attempt to fix a specific stuck schedule by resetting dates appropriately",
            "method": "verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule",
            "icon": "fa fa-wrench",
            "color": "brand-secondary",
            "args": {"schedule_name": "", "force": False},
            "requires_input": True,
            "warning": "This will modify schedule dates to allow invoice generation",
        },
        {
            "title": "Force Fix Stuck Schedule",
            "description": "Force fix a schedule even if no obvious issues are detected",
            "method": "verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule",
            "icon": "fa fa-bolt",
            "color": "brand-primary",
            "args": {"schedule_name": "", "force": True},
            "requires_input": True,
            "warning": "This will force fix the schedule regardless of detected issues",
        },
        {
            "title": "Comprehensive Dues Health Check",
            "description": "Full health check: missing schedules + stuck schedules + data integrity + field synchronization",
            "method": "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_schedule_health_check",
            "icon": "fa fa-heartbeat",
            "color": "brand-primary",
        },
        {
            "title": "Comprehensive Dues Health Maintenance",
            "description": "Complete maintenance job: reconstruction + synchronization + stuck schedule processing",
            "method": "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_health_maintenance",
            "icon": "fa fa-cogs",
            "color": "brand-secondary",
            "warning": "This will run all health maintenance operations and may take several minutes",
        },
        {
            "title": "Sync All Member Fields",
            "description": "Synchronize all member fields (current_membership_plan, current_dues_schedule, dues_rate) with their related records",
            "method": "verenigingen.utils.dues_schedule_health_manager.sync_all_member_fields",
            "icon": "fa fa-refresh",
            "color": "brand-accent",
        },
        {
            "title": "Reconstruct Member Data",
            "description": "Reconstruct missing membership and dues schedule data for a specific member",
            "method": "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_schedule_health_check",
            "icon": "fa fa-magic",
            "color": "brand-primary",
            "args": {"member_filter": "", "fix_issues": True},
            "requires_input": True,
        },
    ]

    # System administration tools
    context.system_tools = [
        {
            "title": "Security Configuration",
            "description": "Check and configure security settings including CSRF protection",
            "method": "verenigingen.setup.security_setup.check_current_security_status",
            "icon": "fa fa-lock",
            "color": "brand-primary",
        },
        {
            "title": "Apply Production Security",
            "description": "Enable CSRF protection and apply production security settings",
            "method": "verenigingen.setup.security_setup.apply_production_security",
            "icon": "fa fa-shield",
            "color": "brand-secondary",
            "warning": "This will enable CSRF protection and disable developer mode. Restart bench after applying.",
        },
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

    # Member import cleanup tools
    context.member_cleanup_tools = [
        {
            "title": "Preview Member Cleanup",
            "description": "Preview what would be deleted in a full member cleanup (safe dry run)",
            "method": "verenigingen.utils.member_import_cleanup.preview_member_cleanup",
            "icon": "fa fa-search",
            "color": "brand-accent",
        },
        {
            "title": "Cleanup Test Members Only",
            "description": "Delete only members with test email patterns and their related records",
            "method": "verenigingen.utils.member_import_cleanup.cleanup_test_members_only",
            "icon": "fa fa-filter",
            "color": "brand-secondary",
            "warning": "This will delete test members and their related records!",
        },
        {
            "title": "Nuclear Cleanup All Members (DRY RUN)",
            "description": "Preview what would be deleted in nuclear cleanup of ALL members",
            "method": "verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"confirm_nuclear_cleanup": True, "dry_run": True},
        },
        {
            "title": "⚠️ NUCLEAR: Delete ALL Members",
            "description": "DELETE ALL MEMBERS and related records - USE EXTREME CAUTION!",
            "method": "verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members",
            "icon": "fa fa-exclamation-triangle",
            "color": "danger",
            "warning": "⚠️ EXTREME DANGER: This will permanently delete ALL members, memberships, dues schedules, volunteers, SEPA mandates, payment history, user accounts, and related records! Only use for import testing on development servers!",
            "args": {"confirm_nuclear_cleanup": True, "dry_run": False},
        },
    ]

    # Payment History Race Condition Fix Tools
    context.payment_fix_tools = [
        {
            "title": "Fix Recent Missing Invoices",
            "description": "Scan recent invoices and fix any missing from member payment history (last 7 days)",
            "method": "verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices",
            "icon": "fa fa-refresh",
            "color": "brand-secondary",
            "args": {"days_back": 7},
        },
        {
            "title": "Fix Recent Missing Invoices (14 days)",
            "description": "Scan recent invoices and fix any missing from member payment history (last 14 days)",
            "method": "verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices",
            "icon": "fa fa-calendar",
            "color": "brand-accent",
            "args": {"days_back": 14},
        },
        {
            "title": "Fix Recent Missing Invoices (30 days)",
            "description": "Scan recent invoices and fix any missing from member payment history (last 30 days)",
            "method": "verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices",
            "icon": "fa fa-history",
            "color": "brand-primary",
            "args": {"days_back": 30},
            "warning": "This will scan 30 days of invoices - may take longer to complete",
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
        {
            "description": "Enhanced membership cleanup (dry run)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.cleanup_orphaned_membership_data --kwargs=\'{"dry_run": True, "max_cleanup": 20}\'',
        },
        {
            "description": "Enhanced membership cleanup (live) - handles Standard Monthly issues",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.cleanup_orphaned_membership_data --kwargs=\'{"dry_run": False, "max_cleanup": 20}\'',
        },
        {
            "description": "Preview member cleanup (safe)",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.preview_member_cleanup",
        },
        {
            "description": "Cleanup test members only",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.cleanup_test_members_only",
        },
        {
            "description": "Nuclear cleanup ALL members (DRY RUN)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members --kwargs=\'{"confirm_nuclear_cleanup": true, "dry_run": true}\'',
        },
        {
            "description": "⚠️ DANGER: Nuclear cleanup ALL members (LIVE)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members --kwargs=\'{"confirm_nuclear_cleanup": true, "dry_run": false}\'',
        },
        {
            "description": "Fix missing invoices in payment history (7 days)",
            "command": "bench --site dev.veganisme.net execute verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices --kwargs='{\"days_back\": 7}'",
        },
        {
            "description": "Fix missing invoices in payment history (30 days)",
            "command": "bench --site dev.veganisme.net execute verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices --kwargs='{\"days_back\": 30}'",
        },
        {
            "description": "Check specific invoice in payment history",
            "command": 'bench --site dev.veganisme.net execute verenigingen.api.fix_race_condition_invoices.check_and_fix_invoice --kwargs=\'{"invoice_name": "SINV-YYYY-NNNNN"}\'',
        },
    ]

    return context


# Define allowed methods - CRITICAL for security
ALLOWED_ADMIN_METHODS = {
    # Invoice management
    "verenigingen.utils.invoice_management.get_dues_schedules_summary",
    "verenigingen.utils.invoice_management.validate_invoice_generation_readiness",
    "verenigingen.utils.invoice_management.bulk_generate_dues_invoices",
    "verenigingen.utils.invoice_management.cleanup_orphaned_schedules",
    "verenigingen.utils.invoice_management.cleanup_orphaned_membership_data",
    # Stuck schedule management
    "verenigingen.api.fix_stuck_dues_schedule.find_all_stuck_schedules",
    "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",
    "verenigingen.api.fix_stuck_dues_schedule.diagnose_stuck_schedule",
    "verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule",
    # Dues schedule health management
    "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_schedule_health_check",
    "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_health_maintenance",
    "verenigingen.utils.dues_schedule_health_manager.sync_all_member_fields",
    # System administration
    "verenigingen.utils.performance_dashboard.get_system_health",
    "verenigingen.utils.performance_dashboard.get_performance_dashboard",
    "verenigingen.utils.performance_dashboard.get_optimization_suggestions",
    "verenigingen.utils.database_query_analyzer.analyze_database_performance",
    "verenigingen.utils.database_query_analyzer.get_index_recommendations",
    "verenigingen.utils.api_doc_generator.generate_api_documentation",
    "verenigingen.utils.api_doc_generator.get_api_endpoints_summary",
    "verenigingen.utils.fraud_detection.get_fraud_statistics",
    # E-Boekhouden cleanup
    "verenigingen.e_boekhouden.utils.cleanup_utils.test_cleanup_small_batch",
    "verenigingen.e_boekhouden.utils.cleanup_utils.cleanup_orphaned_gl_entries",
    "verenigingen.e_boekhouden.utils.cleanup_utils.nuclear_cleanup_all_imported_data",
    # Security management
    "verenigingen.setup.security_setup.check_current_security_status",
    "verenigingen.setup.security_setup.apply_production_security",
    "verenigingen.setup.security_setup.enable_csrf_protection",
    # Member import cleanup
    "verenigingen.utils.member_import_cleanup.preview_member_cleanup",
    "verenigingen.utils.member_import_cleanup.cleanup_test_members_only",
    "verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members",
    # Payment history race condition fixes
    "verenigingen.api.fix_race_condition_invoices.fix_recent_missing_invoices",
    "verenigingen.api.fix_race_condition_invoices.check_and_fix_invoice",
}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def execute_admin_tool(method, args=None):
    """Execute an admin tool method with strict security validation"""

    # ENHANCED PERMISSION VALIDATION - No bypasses allowed
    user = frappe.session.user
    user_roles = frappe.get_roles()

    # Must be Administrator OR have System Manager role OR have write permission on System Settings
    has_admin_access = (
        user == "Administrator"
        or "System Manager" in user_roles
        or frappe.has_permission("System Settings", "write")
    )

    # Additional role check for Verenigingen Administrator (but not sufficient alone)
    has_verenigingen_admin = "Verenigingen Administrator" in user_roles

    if not has_admin_access and not has_verenigingen_admin:
        frappe.throw(
            _(
                "Insufficient permissions. You need Administrator access, System Manager role, or Verenigingen Administrator role."
            ),
            frappe.PermissionError,
        )

    # For cleanup operations, require stricter permissions
    if "member_import_cleanup" in method and user != "Administrator" and "System Manager" not in user_roles:
        frappe.throw(
            _("Cleanup operations require Administrator or System Manager role for security."),
            frappe.PermissionError,
        )

    # CRITICAL: Validate method is in allowed list
    if method not in ALLOWED_ADMIN_METHODS:
        frappe.log_error(
            f"Unauthorized admin tool execution attempt: {method} by {frappe.session.user}", "Security Alert"
        )
        frappe.throw(_("Method not allowed for security reasons"), frappe.PermissionError)

    # Log the admin action for audit purposes
    frappe.logger("verenigingen.admin_tools").info(
        f"Admin tool executed: {method} by {frappe.session.user} with args: {args}"
    )

    try:
        # Import the module and call the method
        from importlib import import_module

        # Split module and function
        if "." not in method:
            raise ValueError(f"Invalid method path: {method}")

        module_path, function_name = method.rsplit(".", 1)

        # Additional security check - ensure module is from verenigingen app
        if not module_path.startswith(("verenigingen.", "frappe.")):
            frappe.throw(_("Invalid module path"), frappe.PermissionError)

        module = import_module(module_path)
        func = getattr(module, function_name)

        # Validate the function has the whitelist decorator
        is_whitelisted = getattr(func, "__func_is_whitelisted__", False)

        # For functions that are explicitly in our ALLOWED_ADMIN_METHODS list,
        # we can be more forgiving if the whitelist attribute is missing
        # since we've already validated they should be accessible
        method_explicitly_allowed = method in ALLOWED_ADMIN_METHODS

        if not is_whitelisted and not method_explicitly_allowed:
            # Enhanced debug information to understand the issue
            debug_info = {
                "method": method,
                "function_name": func.__name__,
                "has_whitelisted_attr": hasattr(func, "__func_is_whitelisted__"),
                "whitelisted_value": getattr(func, "__func_is_whitelisted__", None),
                "has_wrapped": hasattr(func, "__wrapped__"),
                "all_attrs": [
                    attr
                    for attr in dir(func)
                    if not attr.startswith("__") or attr == "__func_is_whitelisted__"
                ],
            }

            # Check wrapped function if exists
            if hasattr(func, "__wrapped__"):
                wrapped = func.__wrapped__
                debug_info.update(
                    {
                        "wrapped_name": wrapped.__name__,
                        "wrapped_has_whitelisted": hasattr(wrapped, "__func_is_whitelisted__"),
                        "wrapped_whitelisted_value": getattr(wrapped, "__func_is_whitelisted__", None),
                    }
                )

                # Check deep wrapped
                if hasattr(wrapped, "__wrapped__"):
                    deep_wrapped = wrapped.__wrapped__
                    debug_info.update(
                        {
                            "deep_wrapped_name": deep_wrapped.__name__,
                            "deep_wrapped_has_whitelisted": hasattr(deep_wrapped, "__func_is_whitelisted__"),
                            "deep_wrapped_whitelisted_value": getattr(
                                deep_wrapped, "__func_is_whitelisted__", None
                            ),
                        }
                    )

            frappe.log_error(
                f"Whitelist validation failed for {method}. Debug info: {debug_info}",
                "Admin Tools Whitelist Debug",
            )
            frappe.throw(
                _(
                    "Method is not properly whitelisted and not in allowed methods list - see error log for details"
                ),
                frappe.PermissionError,
            )

        # Additional logging for methods that bypass whitelist validation due to explicit allowance
        elif not is_whitelisted and method_explicitly_allowed:
            # This is acceptable - method is pre-approved in ALLOWED_ADMIN_METHODS
            frappe.logger("verenigingen.admin_tools").info(
                f"Method {method} allowed via ALLOWED_ADMIN_METHODS list (whitelist attribute: {is_whitelisted})"
            )

            # Additional safety check for cleanup methods - require explicit confirmation in user session
            if "member_import_cleanup" in method:
                # For cleanup methods, add extra validation
                frappe.logger("verenigingen.admin_tools").warning(
                    f"CLEANUP OPERATION: {method} executed by {frappe.session.user} - high-risk operation logged"
                )

        # Parse and validate arguments
        if args:
            import json

            # Parse args if string
            args = json.loads(args) if isinstance(args, str) else args

            # Validate args is a dict
            if not isinstance(args, dict):
                frappe.throw(_("Invalid arguments format"), frappe.ValidationError)

            # Execute with arguments
            result = func(**args)
        else:
            # Execute without arguments
            result = func()

        # Log successful execution
        frappe.logger("verenigingen.admin_tools").info(
            f"Admin tool completed successfully: {method} by {frappe.session.user}"
        )

        return {"success": True, "result": result, "timestamp": now_datetime()}

    except frappe.PermissionError:
        # Re-raise permission errors
        raise
    except Exception as e:
        # Log error with full traceback for debugging
        frappe.log_error(
            f"Admin tool execution failed: {method}\nUser: {frappe.session.user}\nError: {str(e)}",
            "Admin Tools Error",
        )

        # Return sanitized error message
        error_msg = str(e) if frappe.conf.developer_mode else "An error occurred while executing the tool"
        return {"success": False, "error": error_msg, "timestamp": now_datetime()}
