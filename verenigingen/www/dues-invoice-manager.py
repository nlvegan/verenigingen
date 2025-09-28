"""
Dues Invoice Manager - Production Interface
Professional interface for managing membership dues invoicing and SEPA batch processing
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def get_context(context):
    """Set up context for production dues invoice manager page"""

    # Start with absolute basics that shouldn't fail
    context.title = _("Dues Invoice Manager") if frappe.db else "Dues Invoice Manager"
    context.parents = [{"title": "Financial Management", "name": "financial-management"}]

    # Calculate actual current dates - ensure proper month coverage
    try:
        today_date = getdate(today())
        # Start of current month
        period_start = today_date.replace(day=1)
        # End of current month - go to next month, then back one day
        next_month = add_days(period_start, 32)  # This gets us into next month
        next_month_start = next_month.replace(day=1)  # First day of next month
        period_end = add_days(next_month_start, -1)  # Last day of current month

        context.current_period_start = period_start.strftime("%Y-%m-%d")
        context.current_period_end = period_end.strftime("%Y-%m-%d")
    except Exception:
        # Fallback to proper monthly range
        context.current_period_start = "2025-09-01"
        context.current_period_end = "2025-09-30"

    # Check user permissions for financial operations
    current_user = frappe.session.user if frappe.session else "Guest"
    user_roles = frappe.get_roles(current_user) if current_user != "Guest" else ["Guest"]

    # For financial operations (CRITICAL security level), check for specific roles
    # System Manager is included for admin access, plus specific verenigingen roles
    financial_roles = [
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen Treasurer",
        "Verenigingen System Administrator",
    ]
    can_generate_invoices = any(role in user_roles for role in financial_roles)
    can_approve = any(role in user_roles for role in financial_roles)

    # Set defaults for workflow components
    context.sepa_settings = {"billing_cutoff_frequency": "Monthly", "enable_sequential_coverage": True}
    context.workflow_status = {
        "recent_batches": [],
        "pending_invoices": 0,
        "members_analysis": {"total_active_members": 0, "members_missing_invoices": 0, "sepa_eligible": 0},
    }
    context.user_roles = user_roles
    context.can_approve = can_approve
    context.can_generate_invoices = can_generate_invoices

    # Create JavaScript config with actual values
    import json

    js_config = {
        "period_start": context.current_period_start,
        "period_end": context.current_period_end,
        "user_roles": user_roles,
        "can_approve": can_approve,
        "can_generate_invoices": can_generate_invoices,
    }
    context.js_config = json.dumps(js_config)

    return context
