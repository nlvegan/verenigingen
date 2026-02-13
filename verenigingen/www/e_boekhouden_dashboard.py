import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.e_boekhouden.services.dashboard_service import get_eboekhouden_dashboard_service
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, public_api


def get_context(context):
    """Get context for dashboard page"""
    context.no_cache = 1  # Disable caching for this page
    context.title = _("E-Boekhouden Migration Dashboard")

    # Initialize with fallback data FIRST to ensure all variables exist
    context.migration_stats = {"total": 0, "completed": 0, "in_progress": 0, "failed": 0, "draft": 0}
    context.connection_status = "Unknown"
    context.available_data = {"accounts": 0, "cost_centers": 0, "customers": 0, "suppliers": 0}
    context.recent_migrations = []
    context.system_health = {"status": "unknown", "issues": []}

    # Check permissions - use a more permissive check
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to view dashboard"))

    try:
        # Get dashboard data and override fallback values
        dashboard_data = get_eboekhouden_dashboard_service().get_dashboard_data()
        context.update(dashboard_data)

    except Exception as e:
        frappe.log_error(f"Dashboard error: {str(e)}")
        context.error = str(e)
        context.system_health = {"status": "error", "issues": [str(e)]}

    return context


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def get_live_dashboard_data() -> OperationResult[Dict[str, Any]]:
    """API endpoint for live dashboard updates

    Returns:
        OperationResult[Dict[str, Any]]: Dashboard data with migration stats and connection status
    """
    try:
        data = get_eboekhouden_dashboard_service().get_dashboard_data()
        return OperationResult.ok(data, message=_("Dashboard data retrieved successfully"))
    except Exception as e:
        frappe.log_error(
            f"Error retrieving dashboard data: {str(e)}\n{traceback.format_exc()}",
            "E-Boekhouden Dashboard Error",
        )
        return OperationResult.fail(
            _("Unable to retrieve dashboard data. Please contact support."),
            errors=[str(e)],
            context={"operation": "get_live_dashboard_data"},
        )
