"""
SEPA Reconciliation Dashboard Page Controller
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
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


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for SEPA reconciliation dashboard"""
    # Only logged-in users with banking permissions can access
    if user == "Guest":
        return False

    # Check if user has banking or accounting role
    user_roles = frappe.get_roles(user)
    banking_roles = ["Accounts Manager", "Accounts User", Roles.SYSTEM_MANAGER, "Administrator"]

    return any(role in user_roles for role in banking_roles)
