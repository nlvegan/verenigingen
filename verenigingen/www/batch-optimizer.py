"""
Batch Optimizer Web Interface
User-friendly interface for creating optimized SEPA Direct Debit batches
"""

import frappe
from frappe import _


def get_context(context):
    """Set up context for batch optimizer page"""

    context.title = _("SEPA Direct Debit Batch Optimizer")
    context.parents = [{"title": _("Financial Management"), "name": "financial-management"}]

    # Check permissions
    if not frappe.has_permission("SEPA Direct Debit Batch", "create"):
        frappe.throw(_("You don't have permission to create SEPA Direct Debit Batches"))

    # Get current settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "batch_optimization_config") and settings.batch_optimization_config:
            context.current_config = frappe.parse_json(settings.batch_optimization_config)
        else:
            from verenigingen.api.dd_batch_optimizer import DEFAULT_CONFIG

            context.current_config = DEFAULT_CONFIG
    except Exception:
        from verenigingen.api.dd_batch_optimizer import DEFAULT_CONFIG

        context.current_config = DEFAULT_CONFIG

    # Get user roles for permission-based features
    context.user_roles = frappe.get_roles()
    context.can_approve = any(role in ["Finance Manager", "System Manager"] for role in context.user_roles)

    return context
