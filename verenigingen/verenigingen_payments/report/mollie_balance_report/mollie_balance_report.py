"""
Mollie Balance Report
Provides comprehensive balance information from the Mollie Backend API
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

import frappe
from frappe import _
from frappe.utils import flt, formatdate, now_datetime


def execute(filters=None) -> tuple:
    """
    Execute the Mollie Balance Report

    Args:
        filters: Report filters (optional)

    Returns:
        tuple: (columns, data)
    """
    try:
        # Check if Mollie Settings is configured
        settings = frappe.get_single("Mollie Settings")
        if not settings.enable_backend_api:
            return get_columns(), [["Mollie Backend API is not enabled in Mollie Settings", "", "", "", ""]]

        # Check for Organization Access Token
        oat = settings.get_password("organization_access_token", raise_exception=False)
        if not oat:
            return get_columns(), [
                ["Organization Access Token not configured in Mollie Settings", "", "", "", ""]
            ]

        # Initialize the balances client
        from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

        balances_client = BalancesClient()

        # Get balance data
        columns = get_columns()
        data = get_balance_data(balances_client, filters)

        return columns, data

    except Exception as e:
        frappe.log_error(f"Mollie Balance Report error: {str(e)}", "Mollie Balance Report")
        return get_columns(), [[f"Error loading balance data: {str(e)}", "", "", "", ""]]


def get_columns() -> List[Dict[str, Any]]:
    """
    Define report columns

    Returns:
        List of column definitions
    """
    return [
        {"fieldname": "balance_id", "label": _("Balance ID"), "fieldtype": "Data", "width": 200},
        {"fieldname": "currency", "label": _("Currency"), "fieldtype": "Data", "width": 100},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {
            "fieldname": "available_amount",
            "label": _("Available Amount"),
            "fieldtype": "Currency",
            "width": 150,
            "options": "currency",
        },
        {
            "fieldname": "pending_amount",
            "label": _("Pending Amount"),
            "fieldtype": "Currency",
            "width": 150,
            "options": "currency",
        },
        {
            "fieldname": "total_balance",
            "label": _("Total Balance"),
            "fieldtype": "Currency",
            "width": 150,
            "options": "currency",
        },
        {
            "fieldname": "transfer_frequency",
            "label": _("Transfer Frequency"),
            "fieldtype": "Data",
            "width": 150,
        },
        {"fieldname": "last_updated", "label": _("Last Updated"), "fieldtype": "Datetime", "width": 150},
    ]


def get_balance_data(balances_client, filters=None) -> List[List[Any]]:
    """
    Get balance data from Mollie API

    Args:
        balances_client: BalancesClient instance
        filters: Report filters

    Returns:
        List of balance data rows
    """
    data = []

    try:
        # Get all balances
        balances = balances_client.list_balances()

        frappe.logger().info(f"Mollie Balance Report: Retrieved {len(balances)} balances")

        if not balances:
            return [["No balance data available", "", "", "", "", "", "", ""]]

        for balance in balances:
            # Extract balance information
            balance_id = getattr(balance, "id", "Unknown")
            currency = getattr(balance, "currency", "EUR")
            status = getattr(balance, "status", "unknown")

            # Get available amount
            available_amount = 0.0
            if hasattr(balance, "available_amount") and balance.available_amount:
                if hasattr(balance.available_amount, "decimal_value"):
                    available_amount = float(balance.available_amount.decimal_value)
                elif hasattr(balance.available_amount, "value"):
                    try:
                        available_amount = float(balance.available_amount.value)
                    except (ValueError, TypeError):
                        available_amount = 0.0

            # Get pending amount
            pending_amount = 0.0
            if hasattr(balance, "pending_amount") and balance.pending_amount:
                if hasattr(balance.pending_amount, "decimal_value"):
                    pending_amount = float(balance.pending_amount.decimal_value)
                elif hasattr(balance.pending_amount, "value"):
                    try:
                        pending_amount = float(balance.pending_amount.value)
                    except (ValueError, TypeError):
                        pending_amount = 0.0

            # Calculate total
            total_balance = available_amount + pending_amount

            # Get transfer frequency
            transfer_frequency = getattr(balance, "transfer_frequency", "Not set")

            # Get last updated time
            last_updated = getattr(balance, "created_at", "") or now_datetime().isoformat()

            # Format the row
            row = [
                balance_id,
                currency,
                status.title(),
                flt(available_amount, 2),
                flt(pending_amount, 2),
                flt(total_balance, 2),
                transfer_frequency.replace("-", " ").title() if transfer_frequency else "Not set",
                last_updated,
            ]

            data.append(row)

        # Sort by currency and then by balance ID
        data.sort(key=lambda x: (x[1], x[0]))

        frappe.logger().info(f"Mollie Balance Report: Processed {len(data)} balance records")

    except Exception as e:
        frappe.logger().error(f"Error getting balance data: {str(e)}")
        data = [[f"Error retrieving balance data: {str(e)}", "", "", "", "", "", "", ""]]

    return data


def get_chart_data(columns, data, filters=None):
    """
    Generate chart data for the report

    Args:
        columns: Report columns
        data: Report data
        filters: Report filters

    Returns:
        Dict with chart configuration
    """
    if not data or len(data) == 0 or (len(data) == 1 and "Error" in str(data[0][0])):
        return None

    try:
        # Prepare data for currency-based balance chart
        currency_totals = {}

        for row in data:
            if len(row) >= 6:
                currency = row[1]  # Currency column
                total_balance = row[5]  # Total balance column

                if currency and isinstance(total_balance, (int, float)):
                    if currency not in currency_totals:
                        currency_totals[currency] = 0
                    currency_totals[currency] += float(total_balance)

        if currency_totals:
            return {
                "data": {
                    "labels": list(currency_totals.keys()),
                    "datasets": [
                        {
                            "name": "Total Balance",
                            "values": [round(val, 2) for val in currency_totals.values()],
                        }
                    ],
                },
                "type": "donut",
                "height": 300,
                "colors": ["#28a745", "#17a2b8", "#ffc107", "#dc3545"],
            }

    except Exception as e:
        frappe.logger().error(f"Error generating chart data: {str(e)}")

    return None
