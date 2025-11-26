"""
Dues Coverage Manager - Interactive Coverage Gap Analysis
Professional interface for analyzing coverage gaps and generating catch-up invoices
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


def get_context(context):
    """Set up context for coverage manager page"""
    context.no_cache = 1
    context.title = _("Dues Coverage Manager")
    context.parents = [{"title": "Financial Management", "name": "financial-management"}]

    # Require authentication
    current_user = frappe.session.user if frappe.session else "Guest"

    if current_user == "Guest":
        frappe.throw(_("Please login to access the Coverage Manager"), frappe.PermissionError)

    # Get CSRF token for API calls
    csrf_token = ""
    try:
        csrf_token = frappe.sessions.get_csrf_token()
    except Exception:
        try:
            csrf_token = frappe.generate_hash()
        except Exception:
            pass

    context.csrf_token = csrf_token

    return context


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)  # Financial data read access
def get_coverage_data(filters) -> OperationResult[Dict[str, Any]]:
    """Get coverage analysis data for members

    Args:
        filters: Filter criteria for coverage analysis (dict or JSON string)

    Returns:
        OperationResult[Dict[str, Any]]: Coverage data with summary statistics
    """
    import json

    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
        execute,
    )

    # Check permissions
    if not frappe.has_permission("Member", "read"):
        return OperationResult.fail(
            _("Insufficient permissions to view member data"),
            errors=["Permission denied: Member read access required"],
            context={"operation": "get_coverage_data"},
        )

    try:
        # Parse filters if string or None
        if not filters:
            filters = {}
        elif isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except (json.JSONDecodeError, ValueError):
                filters = {}

        # Execute the report
        columns, data = execute(filters)

        # Calculate summary statistics
        summary = {
            "total_members": len(data),
            "members_with_gaps": sum(1 for row in data if row.get("gap_days", 0) > 0),
            "catchup_required": sum(1 for row in data if row.get("catchup_required")),
            "total_catchup_amount": sum(row.get("catchup_amount", 0) for row in data),
        }

        result = {"data": data, "summary": summary}
        return OperationResult.ok(result, message=_("Coverage data retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error retrieving coverage data: {str(e)}\n{traceback.format_exc()}",
            "Dues Coverage Manager Error",
        )
        return OperationResult.fail(
            _("Unable to retrieve coverage data. Please contact support."),
            errors=[str(e)],
            context={"operation": "get_coverage_data", "filters": str(filters)},
        )
