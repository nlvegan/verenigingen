"""
Mollie Dashboard API
Standalone API endpoints for the Mollie financial dashboard
"""

import json

import frappe
from frappe import _


@frappe.whitelist()
def test_api():
    """Simple test endpoint to verify API whitelist is working"""
    return {"success": True, "message": "Mollie Dashboard API is working", "timestamp": frappe.utils.now()}


@frappe.whitelist()
def get_dashboard_data():
    """Get dashboard data for frontend"""
    try:
        # Check if Mollie Settings is configured
        settings = frappe.get_single("Mollie Settings")
        if not settings.enable_backend_api:
            return {
                "success": False,
                "error": "Mollie Backend API is not enabled. Please enable it in Mollie Settings.",
            }

        # Additional debugging information
        oat = settings.get_password("organization_access_token", raise_exception=False)
        if not oat:
            return {
                "success": False,
                "error": "Organization Access Token is not configured. Please configure it in Mollie Settings.",
            }

        # Import and use the dashboard class
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard

        dashboard = FinancialDashboard()
        summary = dashboard.get_dashboard_summary()

        # Transform the summary for the frontend
        return {
            "success": True,
            "data": {
                "balances": {
                    "available": summary["balance_overview"]["total_available_eur"],
                    "pending": summary["balance_overview"]["total_pending_eur"],
                },
                "revenue_metrics": {
                    "this_week": summary["revenue_analysis"]["current_month"]["total_revenue"]
                    / 4,  # Approximation
                    "this_month": summary["revenue_analysis"]["current_month"]["total_revenue"],
                    "this_quarter": summary["revenue_analysis"]["ytd"]["total_revenue"]
                    / 4,  # Rough quarterly approximation
                },
                "recent_settlements": [],  # Will be populated from settlement_metrics
                "reconciliation_status": {
                    "percentage": summary["reconciliation_status"].get("success_rate_30d", 0),
                    "reconciled": 0,
                    "total": 0,
                },
            },
        }
    except Exception as e:
        frappe.log_error(f"Dashboard error: {str(e)}", "Mollie Dashboard")
        return {"success": False, "error": f"Failed to load dashboard: {str(e)}"}


@frappe.whitelist()
def get_financial_report(period: str = "month"):
    """Get financial report for specified period"""
    try:
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard

        dashboard = FinancialDashboard()
        return dashboard.get_financial_report(period)
    except Exception as e:
        frappe.log_error(f"Financial report error: {str(e)}", "Mollie Dashboard")
        return {"success": False, "error": f"Failed to generate report: {str(e)}"}
