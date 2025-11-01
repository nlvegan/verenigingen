"""
Dues Coverage Manager - Interactive Coverage Gap Analysis
Professional interface for analyzing coverage gaps and generating catch-up invoices
"""

import frappe
from frappe import _
from frappe.utils import getdate, today


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
def get_coverage_data(filters):
    """Get coverage analysis data for members"""
    import json

    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
        execute,
    )

    # Check permissions
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions to view member data"))

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

    return {"success": True, "data": data, "summary": summary}
