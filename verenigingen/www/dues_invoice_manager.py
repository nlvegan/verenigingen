"""
Dues Invoice Manager - Production Interface
Professional interface for managing membership dues invoicing and SEPA batch processing
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def get_context(context):
    """Set up context for production dues invoice manager page"""
    context.no_cache = 1  # Disable caching to always show current billing period

    # Start with absolute basics that shouldn't fail
    context.title = _("Dues Invoice Manager") if frappe.db else "Dues Invoice Manager"
    context.parents = [{"title": "Financial Management", "name": "financial-management"}]

    # Calculate billing period using CoverageCalculator service
    # This respects the billing_cutoff_frequency setting (Monthly/Quarterly/Yearly)
    from verenigingen.services.billing.coverage_calculator import CoverageCalculator

    today_date = getdate(today())
    settings = frappe.get_single("Verenigingen Settings")
    cutoff_freq = getattr(settings, "billing_cutoff_frequency", "Monthly")

    # Calculate period start based on billing frequency
    if cutoff_freq == "Monthly":
        period_start = today_date.replace(day=1)
    elif cutoff_freq == "Quarterly":
        # Calculate start of current quarter
        book_year_start_month = getattr(settings, "book_year_start_month", 1)
        months_since_book_start = (today_date.month - book_year_start_month) % 12
        current_quarter = (months_since_book_start // 3) + 1
        quarter_start_month = ((current_quarter - 1) * 3 + book_year_start_month - 1) % 12 + 1

        # Determine year for quarter start
        if quarter_start_month <= today_date.month:
            quarter_start_year = today_date.year
        else:
            # Quarter started in previous year
            quarter_start_year = today_date.year - 1

        period_start = today_date.replace(year=quarter_start_year, month=quarter_start_month, day=1)
    elif cutoff_freq == "Yearly":
        # Start of current book year
        book_year_start_month = getattr(settings, "book_year_start_month", 1)
        book_year_start_day = getattr(settings, "book_year_start_day", 1)

        if today_date.month >= book_year_start_month:
            # We're in the current book year
            book_year_start_year = today_date.year
        else:
            # Book year started last year
            book_year_start_year = today_date.year - 1

        period_start = today_date.replace(
            year=book_year_start_year, month=book_year_start_month, day=book_year_start_day
        )
    else:
        # Default to current month
        period_start = today_date.replace(day=1)

    period_end = CoverageCalculator().calculate_cutoff_date_for_period()

    context.current_period_start = period_start.strftime("%Y-%m-%d")
    context.current_period_end = period_end.strftime("%Y-%m-%d")

    # Check user permissions for financial operations
    current_user = frappe.session.user if frappe.session else "Guest"

    # Require authentication for this financial management page
    if current_user == "Guest":
        frappe.throw(_("Please login to access the Dues Invoice Manager"), frappe.PermissionError)

    user_roles = frappe.get_roles(current_user)

    # For financial operations (CRITICAL security level), check for specific roles
    # System Manager is included for admin access, plus specific verenigingen roles
    financial_roles = [
        "System Manager",
        "Administrator",  # Standard Frappe admin role
        "Verenigingen Administrator",
        "Verenigingen Treasurer",
        "Verenigingen System Administrator",
    ]
    can_generate_invoices = any(role in user_roles for role in financial_roles)
    can_approve = any(role in user_roles for role in financial_roles)

    # Debug: Log user roles for troubleshooting
    frappe.logger().info(
        f"Dues Invoice Manager - User: {current_user}, Roles: {user_roles}, Can Approve: {can_approve}"
    )

    # Don't load workflow status during page render - too expensive and causes permission issues
    # Cards will be populated when user clicks "Check Status" button
    context.workflow_status = {
        "recent_batches": [],
        "pending_invoices": 0,
        "members_analysis": {
            "total_active_members": 0,
            "members_missing_invoices": 0,
            "sepa_eligible": 0,
        },
        "coverage_mismatches": {
            "total_mismatches": 0,
            "extending_past": {"count": 0, "items": []},
            "ending_early": {"count": 0, "items": []},
        },
    }

    # Load SEPA settings
    try:
        context.sepa_settings = frappe.get_single("Verenigingen Settings").as_dict()
    except Exception:
        context.sepa_settings = {"billing_cutoff_frequency": "Monthly", "enable_sequential_coverage": True}
    # Get CSRF token for API calls
    csrf_token = ""
    try:
        csrf_token = frappe.sessions.get_csrf_token()
    except Exception:
        # Fallback to generate new token
        try:
            csrf_token = frappe.generate_hash()
        except Exception:
            pass

    context.user_roles = user_roles
    context.can_approve = can_approve
    context.can_generate_invoices = can_generate_invoices
    context.csrf_token = csrf_token

    # Create JavaScript config with actual values
    import json

    js_config = {
        "period_start": context.current_period_start,
        "period_end": context.current_period_end,
        "user_roles": user_roles,
        "can_approve": can_approve,
        "can_generate_invoices": can_generate_invoices,
        "csrf_token": csrf_token,
    }
    context.js_config = json.dumps(js_config)

    return context
