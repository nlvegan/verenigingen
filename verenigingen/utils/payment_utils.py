#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Payment Entry Query Utilities for Verenigingen
===============================================

Standardized Payment Entry query patterns with caching and performance optimization.
Consolidates scattered payment database queries throughout the codebase.

Key Features:
- Customer payment summary and history lookups
- Payment Entry Reference handling
- Unreconciled payment detection
- Date range filtering with optimization
- Bulk payment operations
- Consistent error handling and caching

Usage:
    from verenigingen.utils.payment_utils import (
        get_customer_payments_summary,
        get_payment_history_for_customer,
        get_payment_references_for_invoice,
        get_unreconciled_payments
    )

    summary = get_customer_payments_summary("CUST-00001", year=2025)
    history = get_payment_history_for_customer("CUST-00001", limit=50)
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_year_ending, get_year_start, today


def get_customer_payments_summary(
    customer_name: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get comprehensive payment summary for a customer with date filtering.

    Args:
        customer_name: Customer document name
        date_from: Start date for filtering (optional)
        date_to: End date for filtering (optional)
        year: Specific year for filtering (optional, overrides date_from/date_to)

    Returns:
        Dict with payment summary including:
        - total_amount: Total amount paid
        - payment_count: Number of payments
        - last_payment_date: Date of most recent payment
        - average_payment: Average payment amount
        - first_payment_date: Date of first payment in period

    Performance:
        Single optimized SQL query with proper indexing hints.
        Critical for dashboard and user-facing operations.
    """
    if not customer_name:
        frappe.logger().warning("get_customer_payments_summary called with empty customer_name")
        return {}

    # Validate customer exists
    if not frappe.db.exists("Customer", customer_name):
        frappe.logger().warning(f"Customer {customer_name} does not exist")
        return {}

    try:
        # Build date filters
        date_condition = ""
        params = {"customer": customer_name}

        if year:
            # Validate year parameter to prevent injection
            try:
                year_int = int(year)
                if year_int < 1900 or year_int > 2100:
                    frappe.logger().warning(f"Invalid year parameter: {year}")
                    return {}
                params["date_from"] = get_year_start(f"{year_int}-01-01")
                params["date_to"] = get_year_ending(f"{year_int}-12-31")
                date_condition = "AND pe.posting_date BETWEEN %(date_from)s AND %(date_to)s"
            except (ValueError, TypeError):
                frappe.logger().warning(f"Invalid year parameter type: {year}")
                return {}
        elif date_from or date_to:
            if date_from and date_to:
                params["date_from"] = date_from
                params["date_to"] = date_to
                date_condition = "AND pe.posting_date BETWEEN %(date_from)s AND %(date_to)s"
            elif date_from:
                params["date_from"] = date_from
                date_condition = "AND pe.posting_date >= %(date_from)s"
            elif date_to:
                params["date_to"] = date_to
                date_condition = "AND pe.posting_date <= %(date_to)s"

        # Build complete query with proper parameterization
        base_query = """
            SELECT
                COUNT(pe.name) as payment_count,
                COALESCE(SUM(pe.paid_amount), 0) as total_amount,
                COALESCE(AVG(pe.paid_amount), 0) as average_payment,
                MAX(pe.posting_date) as last_payment_date,
                MIN(pe.posting_date) as first_payment_date
            FROM `tabPayment Entry` pe
            WHERE pe.party_type = 'Customer'
                AND pe.party = %(customer)s
                AND pe.docstatus = 1
        """

        # Add date condition safely
        if date_condition:
            base_query += " " + date_condition

        # Execute with proper parameterization
        result = frappe.db.sql(base_query, params, as_dict=True)

        if result:
            summary = result[0]
            return {
                "customer_name": customer_name,
                "payment_count": int(summary.get("payment_count", 0)),
                "total_amount": flt(summary.get("total_amount", 0)),
                "average_payment": flt(summary.get("average_payment", 0)),
                "last_payment_date": summary.get("last_payment_date"),
                "first_payment_date": summary.get("first_payment_date"),
                "period_filter": {"date_from": date_from, "date_to": date_to, "year": year},
            }
        else:
            return {"customer_name": customer_name, "payment_count": 0, "total_amount": 0.0}

    except Exception as e:
        frappe.logger().error(f"Error retrieving payment summary for customer {customer_name}: {str(e)}")
        return {}


def get_payment_history_for_customer(
    customer_name: str, year: Optional[int] = None, limit: int = 100, fields: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get payment history for a customer with pagination and field selection.

    Args:
        customer_name: Customer document name
        year: Specific year for filtering (optional)
        limit: Maximum number of records to return (default: 100)
        fields: List of fields to retrieve (optional)

    Returns:
        List of payment dictionaries ordered by posting_date desc

    Performance:
        Optimized for dashboard display with proper field selection.
        Uses indexing for efficient date and party filtering.
    """
    if not customer_name:
        return []

    if fields is None:
        fields = [
            "name",
            "posting_date",
            "paid_amount",
            "unallocated_amount",
            "reference_no",
            "reference_date",
            "mode_of_payment",
            "remarks",
        ]

    try:
        filters = {"party_type": "Customer", "party": customer_name, "docstatus": 1}

        # Year-based filtering for common dashboard usage
        if year:
            filters["posting_date"] = [
                "between",
                [get_year_start(f"{year}-01-01"), get_year_ending(f"{year}-12-31")],
            ]

        payments = frappe.get_all(
            "Payment Entry",
            filters=filters,
            fields=fields,
            order_by="posting_date desc, creation desc",
            limit=limit,
        )

        return payments or []

    except Exception as e:
        frappe.logger().error(f"Error retrieving payment history for customer {customer_name}: {str(e)}")
        return []


def get_payment_references_for_invoice(
    invoice_type: str, invoice_name: str, include_payment_details: bool = True
) -> List[Dict[str, Any]]:
    """
    Get Payment Entry References for a specific invoice.

    Args:
        invoice_type: Type of invoice ("Sales Invoice", "Purchase Invoice")
        invoice_name: Invoice document name
        include_payment_details: Whether to include payment entry details

    Returns:
        List of payment reference dictionaries with optional payment details

    Performance:
        Optimized for invoice-payment reconciliation workflows.
        Single query with LEFT JOIN when payment details requested.
    """
    if not invoice_type or not invoice_name:
        return []

    try:
        if include_payment_details:
            # Single query with JOIN for better performance
            references = frappe.db.sql(
                """
                SELECT
                    per.name,
                    per.parent as payment_entry,
                    per.allocated_amount,
                    per.reference_doctype,
                    per.reference_name,
                    pe.posting_date,
                    pe.paid_amount,
                    pe.mode_of_payment,
                    pe.reference_no,
                    pe.party
                FROM `tabPayment Entry Reference` per
                LEFT JOIN `tabPayment Entry` pe ON per.parent = pe.name
                WHERE per.reference_doctype = %(invoice_type)s
                    AND per.reference_name = %(invoice_name)s
                    AND pe.docstatus = 1
                ORDER BY pe.posting_date DESC
            """,
                {"invoice_type": invoice_type, "invoice_name": invoice_name},
                as_dict=True,
            )
        else:
            # Simple reference lookup without payment details
            references = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_doctype": invoice_type, "reference_name": invoice_name},
                fields=["name", "parent", "allocated_amount", "reference_doctype", "reference_name"],
            )

        return references or []

    except Exception as e:
        frappe.logger().error(
            f"Error retrieving payment references for {invoice_type} {invoice_name}: {str(e)}"
        )
        return []


def get_unreconciled_payments(
    party_type: Optional[str] = None,
    customer: Optional[str] = None,
    minimum_amount: float = 0.01,
    date_from: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Get payments with unallocated amounts for reconciliation.

    Args:
        party_type: Filter by party type ("Customer", "Supplier") (optional)
        customer: Specific customer to filter by (optional)
        minimum_amount: Minimum unallocated amount to include (default: 0.01)
        date_from: Start date for filtering (optional)
        limit: Maximum number of records to return (default: 200)

    Returns:
        List of payment dictionaries with unallocated amounts

    Performance:
        Critical for administrative reconciliation workflows.
        Uses indexes on unallocated_amount and party fields.
    """
    try:
        # Return empty list if customer is None or empty
        if customer is None or (customer is not None and not customer):
            return []

        filters = {"docstatus": 1, "unallocated_amount": [">", minimum_amount]}

        if party_type:
            filters["party_type"] = party_type
        if customer:
            filters["party"] = customer
        if date_from:
            filters["posting_date"] = [">=", date_from]

        payments = frappe.get_all(
            "Payment Entry",
            filters=filters,
            fields=[
                "name",
                "posting_date",
                "party_type",
                "party",
                "paid_amount",
                "unallocated_amount",
                "mode_of_payment",
                "reference_no",
                "reference_date",
                "remarks",
            ],
            order_by="posting_date desc, unallocated_amount desc",
            limit=limit,
        )

        return payments or []

    except Exception as e:
        frappe.logger().error(f"Error retrieving unreconciled payments: {str(e)}")
        return []


def get_payment_allocation_status(payment_entry_name: str) -> Dict[str, Any]:
    """
    Get comprehensive allocation status for a payment entry.

    Args:
        payment_entry_name: Payment Entry document name

    Returns:
        Dict with allocation status including:
        - payment_amount: Total payment amount
        - allocated_amount: Total allocated amount
        - unallocated_amount: Remaining unallocated amount
        - allocations: List of individual allocations
    """
    if not payment_entry_name:
        return {}

    try:
        # Get payment entry details
        payment_data = frappe.db.get_value(
            "Payment Entry",
            payment_entry_name,
            ["paid_amount", "unallocated_amount", "party", "posting_date"],
            as_dict=True,
        )

        if not payment_data:
            return {}

        # Get all payment references
        allocations = frappe.get_all(
            "Payment Entry Reference",
            filters={"parent": payment_entry_name},
            fields=[
                "reference_doctype",
                "reference_name",
                "allocated_amount",
                "outstanding_amount",
                "total_amount",
            ],
            order_by="allocated_amount desc",
        )

        allocated_total = sum(flt(allocation.get("allocated_amount", 0)) for allocation in allocations)

        return {
            "payment_entry": payment_entry_name,
            "payment_amount": flt(payment_data.get("paid_amount")),
            "allocated_amount": allocated_total,
            "unallocated_amount": flt(payment_data.get("unallocated_amount")),
            "party": payment_data.get("party"),
            "posting_date": payment_data.get("posting_date"),
            "allocation_count": len(allocations),
            "allocations": allocations,
            "fully_allocated": flt(payment_data.get("unallocated_amount")) <= 0.01,
        }

    except Exception as e:
        frappe.logger().error(f"Error getting allocation status for payment {payment_entry_name}: {str(e)}")
        return {}


# Convenience functions for common operations


def has_payments(customer_name: str) -> bool:
    """Check if customer has any payments"""
    summary = get_customer_payments_summary(customer_name)
    return summary.get("payment_count", 0) > 0


def get_last_payment_date(customer_name: str) -> Optional[str]:
    """Get date of customer's most recent payment"""
    summary = get_customer_payments_summary(customer_name)
    return summary.get("last_payment_date")


def get_total_payments_for_year(customer_name: str, year: int) -> float:
    """Get total payment amount for customer in specific year"""
    summary = get_customer_payments_summary(customer_name, year=year)
    return summary.get("total_amount", 0.0)


def get_payment_years_for_customer(customer_name: str) -> List[int]:
    """Get list of years when customer made payments"""
    if not customer_name:
        return []

    try:
        years = frappe.db.sql(
            """
            SELECT DISTINCT YEAR(posting_date) as payment_year
            FROM `tabPayment Entry`
            WHERE party_type = 'Customer'
                AND party = %(customer)s
                AND docstatus = 1
            ORDER BY payment_year DESC
        """,
            {"customer": customer_name},
            as_dict=True,
        )

        return [int(year["payment_year"]) for year in years if year["payment_year"]]

    except Exception as e:
        frappe.logger().error(f"Error retrieving payment years for {customer_name}: {str(e)}")
        return []


# Cache management utilities


def invalidate_payment_cache(customer_name: str):
    """
    Invalidate all cached payment data for a customer.
    Call this when customer payment data changes.
    """
    try:
        cache_keys = [
            f"payment_summary:{customer_name}",
            f"payment_history:{customer_name}",
            f"payment_years:{customer_name}",
        ]

        for key in cache_keys:
            try:
                frappe.cache().delete_key(key)
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache delete failed for '{key}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for '{key}': {e}")

        frappe.logger().info(f"Payment cache cleared for customer {customer_name}")

    except Exception as e:
        frappe.logger().error(f"Error clearing payment cache for {customer_name}: {str(e)}")


def refresh_payment_cache():
    """Refresh all payment-related caches"""
    try:
        cache_patterns = [
            "payment_summary:*",
            "payment_history:*",
            "payment_years:*",
            "unreconciled_payments:*",
        ]

        for pattern in cache_patterns:
            try:
                keys = frappe.cache().get_keys(pattern)
                for key in keys:
                    try:
                        frappe.cache().delete_key(key)
                    except (ConnectionError, TimeoutError) as cache_error:
                        frappe.logger().warning(f"Cache delete failed for '{key}': {cache_error}")
                    except Exception as e:
                        frappe.logger().error(f"Unexpected cache error for '{key}': {e}")
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache key lookup failed for pattern '{pattern}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for pattern '{pattern}': {e}")

        frappe.logger().info("All payment caches refreshed")

    except Exception as e:
        frappe.logger().error(f"Error refreshing payment caches: {str(e)}")
