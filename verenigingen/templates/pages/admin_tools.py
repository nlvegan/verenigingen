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
            "formatter": "invoice",
        },
        {
            "title": "Validate Invoice System",
            "description": "Check system readiness for invoice generation and identify issues",
            "method": "verenigingen.utils.invoice_management.validate_invoice_generation_readiness",
            "icon": "fa fa-check-circle",
            "color": "brand-secondary",
            "formatter": "invoice",
        },
        {
            "title": "Bulk Generate Invoices (Dry Run)",
            "description": "Preview which invoices would be generated without creating them",
            "method": "verenigingen.utils.invoice_management.bulk_generate_dues_invoices",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_invoices": 20},
            "formatter": "invoice",
        },
        {
            "title": "Bulk Generate Invoices (Live)",
            "description": "Generate invoices for all eligible dues schedules",
            "method": "verenigingen.utils.invoice_management.bulk_generate_dues_invoices",
            "icon": "fa fa-bolt",
            "color": "brand-primary",
            "warning": "This will create actual invoices. Use after reviewing dry run results!",
            "args": {"dry_run": False, "max_invoices": 50},
            "formatter": "invoice",
        },
        {
            "title": "Cleanup Orphaned Schedules (Dry Run)",
            "description": "Preview orphaned dues schedules that would be cleaned up",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_schedules",
            "icon": "fa fa-search",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_cleanup": 10},
            "formatter": "cleanup",
        },
        {
            "title": "Cleanup Orphaned Schedules (Live)",
            "description": "Remove orphaned dues schedules that reference deleted members",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_schedules",
            "icon": "fa fa-trash",
            "color": "brand-primary",
            "warning": "This will permanently delete orphaned dues schedules!",
            "args": {"dry_run": False, "max_cleanup": 20},
            "formatter": "cleanup",
        },
        {
            "title": "Enhanced Membership Cleanup (Dry Run)",
            "description": "Preview comprehensive cleanup of orphaned schedules, invalid memberships, and orphaned amendments",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_membership_data",
            "icon": "fa fa-search-plus",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_cleanup": 20},
            "formatter": "cleanup",
        },
        {
            "title": "Enhanced Membership Cleanup (Live)",
            "description": "Comprehensive cleanup including orphaned schedules, invalid membership types (like 'Standard Monthly'), and orphaned amendments",
            "method": "verenigingen.utils.invoice_management.cleanup_orphaned_membership_data",
            "icon": "fa fa-magic",
            "color": "brand-secondary",
            "warning": "This will permanently delete orphaned membership data including invalid membership types!",
            "args": {"dry_run": False, "max_cleanup": 20},
            "formatter": "cleanup",
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
            "title": "Find All Stuck Schedules",
            "description": "Find and analyze all stuck schedules that need attention",
            "method": "verenigingen.api.fix_stuck_dues_schedule.find_all_stuck_schedules",
            "icon": "fa fa-search",
            "color": "brand-accent",
        },
        {
            "title": "Check and Notify Stuck Schedules",
            "description": "Check for stuck schedules and send notifications about critical ones",
            "method": "verenigingen.api.fix_stuck_dues_schedule.check_and_notify_stuck_schedules",
            "icon": "fa fa-bell",
            "color": "brand-secondary",
        },
        {
            "title": "Schedule Health Check - Sample Run",
            "description": "Health check sample: missing schedules + stuck schedules + data integrity (uses default limits)",
            "method": "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_schedule_health_check",
            "icon": "fa fa-heartbeat",
            "color": "brand-primary",
            "formatter": "health",
        },
        {
            "title": "Comprehensive Dues Health Maintenance",
            "description": "Complete maintenance job: reconstruction + synchronization + stuck schedule processing",
            "method": "verenigingen.utils.dues_schedule_health_manager.comprehensive_dues_health_maintenance",
            "icon": "fa fa-cogs",
            "color": "brand-secondary",
            "warning": "This will run all health maintenance operations and may take several minutes",
            "formatter": "health",
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

    # Data integrity tools
    context.data_integrity_tools = [
        {
            "title": "Verify Child Table Indexes",
            "description": "Check if required database indexes exist for optimal performance",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.verify_child_table_indexes",
            "icon": "fa fa-tachometer",
            "color": "brand-primary",
            "formatter": "generic",
        },
        {
            "title": "Detect Orphaned Child Tables",
            "description": "Scan all child tables for orphaned records (where parent has been deleted)",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.detect_orphaned_child_tables",
            "icon": "fa fa-search",
            "color": "brand-accent",
            "formatter": "orphan",
        },
        {
            "title": "Cleanup All Orphaned Child Tables (DRY RUN)",
            "description": "Preview cleanup of all orphaned child table records across entire system",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_orphaned_child_tables",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"dry_run": True},
            "formatter": "orphan",
        },
        {
            "title": "Cleanup All Orphaned Child Tables (LIVE)",
            "description": "Delete all orphaned child table records system-wide",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_orphaned_child_tables",
            "icon": "fa fa-eraser",
            "color": "brand-secondary",
            "warning": "This will permanently delete orphaned child table records across all DocTypes!",
            "args": {"dry_run": False},
            "formatter": "orphan",
        },
        {
            "title": "Cleanup Member Child Tables Only (DRY RUN)",
            "description": "Preview cleanup of orphaned Member child table records only",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_member_child_tables_only",
            "icon": "fa fa-user",
            "color": "brand-accent",
            "args": {"dry_run": True},
            "formatter": "orphan",
        },
        {
            "title": "Cleanup Member Child Tables Only (LIVE)",
            "description": "Delete orphaned Member child table records (Payment History, Volunteer Expenses, etc.)",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_member_child_tables_only",
            "icon": "fa fa-user-times",
            "color": "brand-secondary",
            "warning": "This will permanently delete orphaned Member child table records!",
            "args": {"dry_run": False},
            "formatter": "orphan",
        },
        {
            "title": "Cleanup Volunteer Child Tables Only (DRY RUN)",
            "description": "Preview cleanup of orphaned Volunteer child table records only",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_volunteer_child_tables_only",
            "icon": "fa fa-heart",
            "color": "brand-accent",
            "args": {"dry_run": True},
            "formatter": "orphan",
        },
        {
            "title": "Cleanup Volunteer Child Tables Only (LIVE)",
            "description": "Delete orphaned Volunteer child table records (Assignments, Skills, etc.)",
            "method": "verenigingen.utils.orphaned_child_table_cleanup.cleanup_volunteer_child_tables_only",
            "icon": "fa fa-heart-broken",
            "color": "brand-secondary",
            "warning": "This will permanently delete orphaned Volunteer child table records!",
            "args": {"dry_run": False},
            "formatter": "orphan",
        },
        {
            "title": "Preview Payment Entry Cleanup",
            "description": "Preview which Payment Entries would be deleted and which members would be affected (safe preview)",
            "method": "verenigingen.utils.payment_entry_cleanup.get_payment_entry_cleanup_preview",
            "icon": "fa fa-search",
            "color": "brand-accent",
            "args": {"filters": {"docstatus": ["in", [0, 2]]}},
            "formatter": "generic",
        },
        {
            "title": "Delete Draft & Cancelled Payment Entries",
            "description": "Delete all draft and cancelled Payment Entries and clean up Member Payment History references",
            "method": "verenigingen.utils.payment_entry_cleanup.bulk_delete_payment_entries",
            "icon": "fa fa-trash-o",
            "color": "warning",
            "warning": "This will permanently delete all draft and cancelled Payment Entries and remove them from Member Payment History!",
            "args": {"filters": {"docstatus": ["in", [0, 2]]}},
            "formatter": "cleanup",
        },
        {
            "title": "Analyze Payment Processing Gaps",
            "description": "Identify payments missing Bank Transactions, Payment Entries, or Sales Invoices",
            "method": "verenigingen.utils.payment_processing_recovery.analyze_payment_gaps",
            "icon": "fa fa-search-plus",
            "color": "brand-accent",
            "formatter": "generic",
        },
        {
            "title": "Find Incomplete Payments (All)",
            "description": "Check ALL recent Bank Transactions for missing documents (may take a minute)",
            "method": "verenigingen.utils.payment_processing_recovery.get_incomplete_payments",
            "icon": "fa fa-exclamation-triangle",
            "color": "warning",
            "formatter": "generic",
        },
        {
            "title": "Complete Partial Payments (DRY RUN) - 300 limit",
            "description": "Preview which documents would be created to complete partially processed payments (max 300)",
            "method": "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"dry_run": True, "max_payments": 300},
            "formatter": "generic",
        },
        {
            "title": "Complete Partial Payments (LIVE) - 300 limit",
            "description": "Create missing Bank Transactions, Payment Entries, and Sales Invoices for incomplete payments (max 300)",
            "method": "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
            "icon": "fa fa-magic",
            "color": "success",
            "warning": "This will create missing financial documents for partially processed payments!",
            "args": {"dry_run": False, "max_payments": 300},
            "formatter": "generic",
        },
    ]

    # System administration tools
    context.system_tools = [
        {
            "title": "Delete All Payment Entries",
            "description": "Delete all payment entries from the system (development only)",
            "method": "verenigingen.e_boekhouden.utils.cleanup_utils.delete_all_payment_entries",
            "icon": "fa fa-trash-o",
            "color": "danger",
            "warning": "⚠️ This will permanently delete ALL payment entries in the system! Only use on development servers!",
        },
        {
            "title": "Security Configuration",
            "description": "Check and configure security settings including CSRF protection",
            "method": "verenigingen.setup.security_setup.check_current_security_status",
            "icon": "fa fa-lock",
            "color": "brand-primary",
            "formatter": "security",
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
            "title": "Force Cleanup Orphaned Schedules/Invoices (DRY RUN)",
            "description": "Preview cleanup of orphaned dues schedules and invoices after members deleted",
            "method": "verenigingen.utils.member_import_cleanup.force_cleanup_orphaned_schedules_and_invoices",
            "icon": "fa fa-eye",
            "color": "brand-accent",
            "args": {"dry_run": True},
        },
        {
            "title": "Force Cleanup Orphaned Schedules/Invoices (LIVE)",
            "description": "Delete orphaned dues schedules and membership invoices that reference deleted members",
            "method": "verenigingen.utils.member_import_cleanup.force_cleanup_orphaned_schedules_and_invoices",
            "icon": "fa fa-trash",
            "color": "brand-secondary",
            "warning": "This will force-delete orphaned schedules and invoices!",
            "args": {"dry_run": False},
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
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.bulk_generate_dues_invoices --kwargs=\'{"dry_run": True, "max_invoices": 20}\'',
        },
        {
            "description": "Generate invoices for real (max 50)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.bulk_generate_dues_invoices --kwargs=\'{"dry_run": False, "max_invoices": 50}\'',
        },
        {
            "description": "Cleanup orphaned schedules (dry run)",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.invoice_management.cleanup_orphaned_schedules --kwargs='{\"dry_run\": True}'",
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
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members --kwargs=\'{"confirm_nuclear_cleanup": True, "dry_run": True}\'',
        },
        {
            "description": "⚠️ DANGER: Nuclear cleanup ALL members (LIVE)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members --kwargs=\'{"confirm_nuclear_cleanup": True, "dry_run": False}\'',
        },
        {
            "description": "Complete partial payments (dry run, max 300)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.payment_processing_recovery.complete_partial_payments --kwargs=\'{"dry_run": True, "max_payments": 300}\'',
        },
        {
            "description": "Complete partial payments (LIVE, max 300)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.payment_processing_recovery.complete_partial_payments --kwargs=\'{"dry_run": False, "max_payments": 300}\'',
        },
        {
            "description": "Complete partial payments (LIVE, unlimited - up to 2500)",
            "command": "bench --site dev.veganisme.net execute verenigingen.utils.payment_processing_recovery.complete_partial_payments --kwargs='{\"dry_run\": False}'",
        },
        {
            "description": "Complete partial payments (LIVE, custom limit)",
            "command": 'bench --site dev.veganisme.net execute verenigingen.utils.payment_processing_recovery.complete_partial_payments --kwargs=\'{"dry_run": False, "max_payments": 500}\'',
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
    # Data integrity management
    "verenigingen.utils.orphaned_child_table_cleanup.verify_child_table_indexes",
    "verenigingen.utils.orphaned_child_table_cleanup.detect_orphaned_child_tables",
    "verenigingen.utils.orphaned_child_table_cleanup.cleanup_orphaned_child_tables",
    "verenigingen.utils.orphaned_child_table_cleanup.cleanup_member_child_tables_only",
    "verenigingen.utils.orphaned_child_table_cleanup.cleanup_volunteer_child_tables_only",
    # Payment Entry cleanup
    "verenigingen.utils.payment_entry_cleanup.bulk_delete_payment_entries",
    "verenigingen.utils.payment_entry_cleanup.delete_payment_entries_by_date_range",
    "verenigingen.utils.payment_entry_cleanup.get_payment_entry_cleanup_preview",
    # Payment processing recovery
    "verenigingen.utils.payment_processing_recovery.analyze_payment_gaps",
    "verenigingen.utils.payment_processing_recovery.get_incomplete_payments",
    "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
    "verenigingen.utils.payment_processing_recovery.get_payment_processing_status",
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
    "verenigingen.e_boekhouden.utils.cleanup_utils.delete_all_payment_entries",
    # Security management
    "verenigingen.setup.security_setup.check_current_security_status",
    "verenigingen.setup.security_setup.apply_production_security",
    "verenigingen.setup.security_setup.enable_csrf_protection",
    # Member import cleanup
    "verenigingen.utils.member_import_cleanup.preview_member_cleanup",
    "verenigingen.utils.member_import_cleanup.cleanup_test_members_only",
    "verenigingen.utils.member_import_cleanup.nuclear_cleanup_all_members",
    "verenigingen.utils.member_import_cleanup.force_cleanup_orphaned_schedules_and_invoices",
    # API Audit Log management
    "verenigingen.verenigingen.doctype.api_audit_log.api_audit_log.clear_all_audit_logs",
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

            try:
                # Parse args if string
                if isinstance(args, str):
                    # Handle common malformed JSON cases
                    args = args.strip()
                    if not args:
                        args = {}
                    elif args.startswith("{") and args.endswith("}"):
                        # Decode HTML entities that may be present from template rendering
                        import html

                        decoded_args = html.unescape(args)
                        args = json.loads(decoded_args)
                    else:
                        # Log the problematic input for debugging
                        frappe.log_error(
                            f"Invalid JSON args received for method {method}: {args[:100]}",
                            "Admin Tool Args Error",
                        )
                        frappe.throw(
                            _('Invalid JSON format in arguments. Expected format: {{"key": "value"}}'),
                            frappe.ValidationError,
                        )

                # Validate args is a dict
                if not isinstance(args, dict):
                    frappe.throw(_("Invalid arguments format - must be a dictionary"), frappe.ValidationError)

                # Execute with arguments
                result = func(**args)
            except json.JSONDecodeError as e:
                frappe.log_error(
                    f"JSON parsing error in admin tool {method}: {str(e)} | Raw args: {args[:200] if isinstance(args, str) else str(args)[:200]}",
                    "Admin Tool JSON Error",
                )
                frappe.throw(
                    _("Invalid JSON format in arguments: {0}").format(str(e)), frappe.ValidationError
                )
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
