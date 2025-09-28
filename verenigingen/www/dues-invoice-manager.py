"""
Dues Invoice Manager - Production Interface
Professional interface for managing membership dues invoicing and SEPA batch processing
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def get_context(context):
    """Set up context for production dues invoice manager page"""

    context.title = _("Dues Invoice Manager")
    context.parents = [{"title": _("Financial Management"), "name": "financial-management"}]

    # Check permissions with defensive error handling
    is_system_manager = "System Manager" in frappe.get_roles()

    try:
        has_dd_permission = frappe.has_permission("Direct Debit Batch", "create")
    except Exception:
        has_dd_permission = False

    try:
        has_invoice_permission = frappe.has_permission("Sales Invoice", "create")
    except Exception:
        has_invoice_permission = False

    # Allow System Manager to bypass permission checks for setup/demo
    if not (has_dd_permission or is_system_manager):
        if not is_system_manager:
            frappe.throw(_("You don't have permission to manage SEPA Direct Debit operations"))

    if not (has_invoice_permission or is_system_manager):
        if not is_system_manager:
            frappe.throw(_("You don't have permission to create invoices"))

    # Get user roles for permission-based features
    context.user_roles = frappe.get_roles()
    context.can_approve = any(role in ["Finance Manager", "System Manager"] for role in context.user_roles)
    context.can_generate_invoices = any(
        role in ["Verenigingen Staff", "Finance Manager", "System Manager"] for role in context.user_roles
    )

    # Get current billing period (current month by default)
    today_date = getdate(today())
    context.current_period_start = today_date.replace(day=1)
    context.current_period_end = add_days(add_days(context.current_period_start, 32).replace(day=1), -1)

    # Get SEPA and billing settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        context.sepa_settings = {
            "creditor_id": getattr(settings, "creditor_id", ""),
            "organization_name": getattr(settings, "company_name", "Verenigingen"),
            "default_currency": "EUR",
            "billing_cutoff_frequency": getattr(settings, "billing_cutoff_frequency", "Monthly"),
            "enable_sequential_coverage": getattr(settings, "enable_sequential_coverage", True),
        }
    except Exception:
        context.sepa_settings = {
            "creditor_id": "",
            "organization_name": "Verenigingen",
            "default_currency": "EUR",
            "billing_cutoff_frequency": "Monthly",
            "enable_sequential_coverage": True,
        }

    # Get workflow status with enhanced error handling
    try:
        from verenigingen.api.dues_invoice_workflow import get_workflow_status

        workflow_data = get_workflow_status()
        context.workflow_status = workflow_data
    except Exception as e:
        frappe.log_error(f"Workflow API failed: {str(e)}", "DuesManager Error")
        context.workflow_status = {
            "recent_batches": [],
            "pending_invoices": 0,
            "members_analysis": {
                "total_active_members": 0,
                "members_missing_invoices": 0,
                "sepa_eligible": 0,
            },
        }

    # Prepare JavaScript configuration
    context.js_config = frappe.as_json(
        {
            "user_roles": context.user_roles,
            "can_approve": context.can_approve,
            "can_generate_invoices": context.can_generate_invoices,
            "period_start": str(context.current_period_start),
            "period_end": str(context.current_period_end),
            "sepa_settings": context.sepa_settings,
        }
    )

    return context
