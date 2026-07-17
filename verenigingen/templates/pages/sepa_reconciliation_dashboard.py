"""
SEPA Reconciliation Dashboard Page Controller
"""

import frappe
from frappe import _

from verenigingen.utils.member_utils import require_login


def get_context(context):
    """Get context for SEPA reconciliation dashboard"""
    require_login()

    # Check user permissions for banking functions
    if not frappe.has_permission("Bank Transaction", "read"):
        frappe.throw(_("You don't have permission to access banking functions"), frappe.PermissionError)

    context.no_cache = 1
    context.title = _("SEPA Reconciliation Dashboard")
    context.show_sidebar = False

    return context
