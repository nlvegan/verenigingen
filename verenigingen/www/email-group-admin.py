#!/usr/bin/env python3
"""
Email Group Administration Page Controller
"""

import frappe
from frappe import _


def get_context(context):
    """
    Context for the email group administration page
    """
    # Check permissions - only allow System Manager or Verenigingen Manager
    if not ("System Manager" in frappe.get_roles() or "Verenigingen Manager" in frappe.get_roles()):
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    # Basic context
    context.no_cache = 1
    context.show_sidebar = False

    # Add breadcrumbs
    context.parents = [{"name": "Home", "route": "/"}, {"name": "Administration", "route": "/admin"}]

    return context
