"""
Batch Optimizer Web Interface
User-friendly interface for creating optimized SEPA Direct Debit batches
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles


def get_context(context):
    """Set up context for batch optimizer page"""

    context.title = _("SEPA Direct Debit Batch Optimizer")
    context.parents = [{"title": _("Financial Management"), "name": "financial-management"}]

    # Check permissions
    if not frappe.has_permission("Direct Debit Batch", "create"):
        frappe.throw(_("You don't have permission to create SEPA Direct Debit Batches"))

    # Get current settings. batch_optimization_config lives on Verenigingen
    # Payments Settings (migrated there), which is also where the optimizer
    # endpoint writes it and the scheduler reads it.
    try:
        from verenigingen.utils.settings_utils import get_payments_settings

        settings = get_payments_settings()
        if hasattr(settings, "batch_optimization_config") and settings.batch_optimization_config:
            context.current_config = frappe.parse_json(settings.batch_optimization_config)
        else:
            from verenigingen.verenigingen_payments.api.dd_batch_optimizer import DEFAULT_CONFIG

            context.current_config = DEFAULT_CONFIG
    except Exception:
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import DEFAULT_CONFIG

        context.current_config = DEFAULT_CONFIG

    # Get user roles for permission-based features
    context.user_roles = frappe.get_roles()
    context.can_approve = any(
        role in ["Verenigingen Financial Manager", Roles.SYSTEM_MANAGER] for role in context.user_roles
    )

    return context
