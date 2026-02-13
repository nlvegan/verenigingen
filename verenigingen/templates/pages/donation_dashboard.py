# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from verenigingen.services.donation.dashboard_service import DonationDashboardService


def get_context(context):
    if not frappe.has_permission("Donation", "read") or not frappe.has_permission(
        "Periodic Donation Agreement", "read"
    ):
        frappe.throw(_("You do not have permission to access this page"), frappe.PermissionError)

    anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
    if not anbi_enabled:
        context.anbi_disabled = True
        return context

    context.no_cache = 1
    context.show_sidebar = True

    service = DonationDashboardService()
    try:
        context.update(service.get_dashboard_context())
    except Exception as e:
        frappe.log_error(f"Error loading donation dashboard: {e!s}")
        context.error = _("Failed to load dashboard data")

    return context
