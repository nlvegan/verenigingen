"""
Mollie Balance Report

Provides balance information from Mollie in Frappe report format.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard


def execute(filters=None):
    """
    Execute the Mollie Balance Report

    Returns:
        tuple: (columns, data)
    """
    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Get report columns"""
    return [
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 100},
        {"label": _("Available Balance"), "fieldname": "available", "fieldtype": "Currency", "width": 150},
        {"label": _("Pending Balance"), "fieldname": "pending", "fieldtype": "Currency", "width": 150},
        {"label": _("Total Balance"), "fieldname": "total", "fieldtype": "Currency", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Last Updated"), "fieldname": "last_updated", "fieldtype": "Datetime", "width": 160},
    ]


def get_data(filters=None):
    """Get balance data from Mollie dashboard"""
    data = []

    try:
        # Check if Mollie is configured
        settings = frappe.get_single("Mollie Settings")
        if not settings.enable_backend_api:
            frappe.msgprint(_("Mollie Backend API is not enabled. Please enable it in Mollie Settings."))
            return data

        oat = settings.get_password("organization_access_token", raise_exception=False)
        if not oat:
            frappe.msgprint(
                _("Organization Access Token is not configured. Please configure it in Mollie Settings.")
            )
            return data

        # Get dashboard data
        dashboard = FinancialDashboard()
        summary = dashboard.get_dashboard_summary()

        balance_overview = summary.get("balance_overview", {})

        if balance_overview.get("balances"):
            for balance in balance_overview["balances"]:
                available = flt(balance.get("available", 0))
                pending = flt(balance.get("pending", 0))

                data.append(
                    {
                        "currency": balance.get("currency", "EUR"),
                        "available": available,
                        "pending": pending,
                        "total": available + pending,
                        "status": balance.get("status", "active"),
                        "last_updated": balance_overview.get("last_updated"),
                    }
                )
        else:
            # Fallback to summary data
            available = flt(balance_overview.get("total_available_eur", 0))
            pending = flt(balance_overview.get("total_pending_eur", 0))

            data.append(
                {
                    "currency": "EUR",
                    "available": available,
                    "pending": pending,
                    "total": available + pending,
                    "status": balance_overview.get("health_status", "unknown"),
                    "last_updated": balance_overview.get("last_updated"),
                }
            )

    except Exception as e:
        frappe.log_error(f"Mollie Balance Report error: {str(e)}", "Mollie Balance Report")
        frappe.msgprint(_("Error loading Mollie balance data: {0}").format(str(e)))

    return data
