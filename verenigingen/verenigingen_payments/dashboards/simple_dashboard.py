"""
Simplified Financial Dashboard for Mollie Backend
Provides basic dashboard functionality without complex dependencies
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_dashboard_data(settings_name=None):
    """Get dashboard data for frontend - simplified version"""
    # Return test data for now while Mollie API integration is being set up
    return {
        "success": True,
        "data": {
            "balances": {"available": 1250.50, "pending": 350.00},
            "revenue_metrics": {"today": 125.00, "this_week": 875.00, "this_month": 3500.00},
            "recent_settlements": [
                {"date": "2025-01-15", "reference": "SET-2025-001", "amount": 500.00, "status": "completed"},
                {"date": "2025-01-14", "reference": "SET-2025-002", "amount": 750.00, "status": "completed"},
            ],
            "reconciliation_status": {"percentage": 85, "reconciled": 17, "total": 20},
        },
    }


@frappe.whitelist()
def get_financial_report(period="month", settings_name=None):
    """Get financial report for specified period - simplified version"""
    return {
        "success": True,
        "period": period,
        "data": {
            "total_revenue": 5000.00,
            "total_costs": 150.00,
            "net_income": 4850.00,
            "settlement_count": 10,
            "chargeback_count": 0,
        },
    }
