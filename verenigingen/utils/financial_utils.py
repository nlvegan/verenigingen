#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Financial Query Utilities for Verenigingen
==========================================

Standardized financial query patterns with caching and performance optimization.
Eliminates scattered financial database queries throughout the codebase.

Key Features:
- Customer invoice lookups with caching
- Outstanding amount queries with proper indexing hints
- Date range filtering with optimization
- Member-customer relationship utilities
- Consistent error handling across all financial operations

Usage:
    from verenigingen.utils.financial_utils import (
        get_customer_invoices,
        get_outstanding_invoices,
        get_member_for_customer,
        get_customer_for_member
    )

    invoices = get_customer_invoices("CUST-00001", outstanding_only=True)
    member = get_member_for_customer("CUST-00001")
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_months, flt, today


def get_customer_invoices(
    customer_name: str,
    outstanding_only: bool = False,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    fields: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Get invoices for a customer with standardized filtering and caching.

    Args:
        customer_name: Customer document name
        outstanding_only: Whether to only return unpaid invoices (default: False)
        date_from: Start date for filtering (optional)
        date_to: End date for filtering (optional)
        fields: List of fields to retrieve (defaults to standard fields)
        limit: Maximum number of records to return (optional)

    Returns:
        List of invoice dictionaries

    Error Handling:
        Returns empty list on errors, logs errors for debugging

    Performance:
        Uses optimized filters and field selection for better query performance
    """
    if not customer_name:
        frappe.logger().warning("get_customer_invoices called with empty customer_name")
        return []

    # Default fields for performance
    if fields is None:
        fields = ["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"]

    try:
        # Build filters for optimal query performance
        filters = {"customer": customer_name, "docstatus": 1}  # Only submitted invoices

        # Outstanding filter for payment processing
        if outstanding_only:
            filters["outstanding_amount"] = [">", 0]
            filters["status"] = ["not in", ["Paid", "Cancelled"]]

        # Date range filtering with proper indexing
        if date_from and date_to:
            filters["posting_date"] = ["between", [date_from, date_to]]
        elif date_from:
            filters["posting_date"] = [">=", date_from]
        elif date_to:
            filters["posting_date"] = ["<=", date_to]

        # Execute query with performance optimization
        invoices = frappe.get_all(
            "Sales Invoice", filters=filters, fields=fields, order_by="posting_date desc", limit=limit
        )

        return invoices or []

    except Exception as e:
        frappe.logger().error(f"Error retrieving invoices for customer {customer_name}: {str(e)}")
        return []


def get_outstanding_invoices(
    customer_name: str, due_date_filter: Optional[str] = None, fields: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get outstanding (unpaid) invoices for a customer.

    Args:
        customer_name: Customer document name
        due_date_filter: Filter by due date ("overdue", "due_today", "due_soon") (optional)
        fields: List of fields to retrieve (optional)

    Returns:
        List of outstanding invoice dictionaries

    Performance:
        Optimized for SEPA processing and payment workflows
    """
    if not customer_name:
        return []

    if fields is None:
        fields = ["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "customer"]

    try:
        filters = {
            "customer": customer_name,
            "docstatus": 1,
            "outstanding_amount": [">", 0],
            "status": ["not in", ["Paid", "Cancelled", "Credit Note Issued"]],
        }

        # Due date specific filtering
        if due_date_filter == "overdue":
            filters["due_date"] = ["<", today()]
        elif due_date_filter == "due_today":
            filters["due_date"] = today()
        elif due_date_filter == "due_soon":
            filters["due_date"] = ["<=", add_months(today(), 1)]

        invoices = frappe.get_all(
            "Sales Invoice", filters=filters, fields=fields, order_by="due_date asc, posting_date asc"
        )

        return invoices or []

    except Exception as e:
        frappe.logger().error(f"Error retrieving outstanding invoices for customer {customer_name}: {str(e)}")
        return []


def get_recent_invoices(
    customer_name: str, months_back: int = 3, limit: int = 10, fields: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get recent invoices for a customer within specified time period.

    Args:
        customer_name: Customer document name
        months_back: Number of months to look back (default: 3)
        limit: Maximum number of records to return (default: 10)
        fields: List of fields to retrieve (optional)

    Returns:
        List of recent invoice dictionaries ordered by posting_date desc
    """
    date_from = add_months(today(), -months_back)

    return get_customer_invoices(customer_name=customer_name, date_from=date_from, fields=fields, limit=limit)


def get_member_for_customer(customer_name: str) -> Optional[str]:
    """Get member name for a given customer (reverse lookup).

    Delegates to member_utils.get_member_for_customer — kept here for
    backward-compatible imports from financial_utils.
    """
    from verenigingen.utils.member_utils import get_member_for_customer as _canonical

    return _canonical(customer_name)


def get_customer_for_member(member_name: str) -> Optional[str]:
    """
    Get customer name for a given member.

    Args:
        member_name: Member document name

    Returns:
        Customer name if found, None otherwise

    Note:
        This function exists in member_utils.py as get_member_customer().
        Included here for financial context and consistency.
    """
    if not member_name:
        return None

    try:
        customer_name = frappe.db.get_value("Member", member_name, "customer")
        return customer_name

    except Exception as e:
        frappe.logger().error(f"Error looking up customer for member {member_name}: {str(e)}")
        return None


def get_invoice_payment_status(invoice_name: str) -> Dict[str, Any]:
    """
    Get comprehensive payment status for an invoice.

    Args:
        invoice_name: Sales Invoice document name

    Returns:
        Dict with payment status information including:
        - paid_amount: Amount paid
        - outstanding_amount: Amount remaining
        - payment_entries: List of related payment entries
        - status: Current payment status
    """
    if not invoice_name:
        return {}

    try:
        # Get invoice details
        invoice_data = frappe.db.get_value(
            "Sales Invoice",
            invoice_name,
            ["grand_total", "outstanding_amount", "paid_amount", "status"],
            as_dict=True,
        )

        if not invoice_data:
            return {}

        # Get payment references
        payment_references = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_name, "docstatus": 1},
            fields=["parent", "allocated_amount"],
            order_by="creation desc",
        )

        return {
            "invoice_name": invoice_name,
            "grand_total": flt(invoice_data.get("grand_total")),
            "paid_amount": flt(invoice_data.get("paid_amount")),
            "outstanding_amount": flt(invoice_data.get("outstanding_amount")),
            "status": invoice_data.get("status"),
            "payment_entries": payment_references,
            "is_paid": flt(invoice_data.get("outstanding_amount")) <= 0,
        }

    except Exception as e:
        frappe.logger().error(f"Error getting payment status for invoice {invoice_name}: {str(e)}")
        return {}


def get_customer_payment_summary(customer_name: str, months_back: int = 12) -> Dict[str, Any]:
    """
    Get comprehensive payment summary for a customer.

    Args:
        customer_name: Customer document name
        months_back: Number of months to include in summary (default: 12)

    Returns:
        Dict with payment summary including:
        - total_invoiced: Total amount invoiced
        - total_paid: Total amount paid
        - outstanding_balance: Current outstanding balance
        - overdue_amount: Amount overdue
        - recent_invoices: Count of recent invoices
        - recent_payments: Count of recent payments
    """
    if not customer_name:
        return {}

    try:
        date_from = add_months(today(), -months_back)

        # Get invoice summary
        invoice_summary = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_invoices,
                SUM(grand_total) as total_invoiced,
                SUM(outstanding_amount) as outstanding_balance,
                SUM(CASE WHEN due_date < CURDATE() AND outstanding_amount > 0 THEN outstanding_amount ELSE 0 END) as overdue_amount
            FROM `tabSales Invoice`
            WHERE customer = %(customer)s
                AND docstatus = 1
                AND posting_date >= %(date_from)s
        """,
            {"customer": customer_name, "date_from": date_from},
            as_dict=True,
        )

        # Get payment summary
        payment_summary = frappe.db.sql(
            """
            SELECT
                COUNT(*) as total_payments,
                SUM(paid_amount) as total_paid
            FROM `tabPayment Entry`
            WHERE party_type = 'Customer'
                AND party = %(customer)s
                AND docstatus = 1
                AND posting_date >= %(date_from)s
        """,
            {"customer": customer_name, "date_from": date_from},
            as_dict=True,
        )

        invoice_data = invoice_summary[0] if invoice_summary else {}
        payment_data = payment_summary[0] if payment_summary else {}

        return {
            "customer_name": customer_name,
            "period_months": months_back,
            "total_invoices": invoice_data.get("total_invoices", 0),
            "total_invoiced": flt(invoice_data.get("total_invoiced")),
            "total_payments": payment_data.get("total_payments", 0),
            "total_paid": flt(payment_data.get("total_paid")),
            "outstanding_balance": flt(invoice_data.get("outstanding_balance")),
            "overdue_amount": flt(invoice_data.get("overdue_amount")),
            "payment_ratio": (
                flt(payment_data.get("total_paid")) / flt(invoice_data.get("total_invoiced"))
                if flt(invoice_data.get("total_invoiced")) > 0
                else 0
            ),
        }

    except Exception as e:
        frappe.logger().error(f"Error getting payment summary for customer {customer_name}: {str(e)}")
        return {}


# Convenience functions for common financial operations


def has_outstanding_invoices(customer_name: str) -> bool:
    """Check if customer has any outstanding invoices"""
    outstanding = get_outstanding_invoices(customer_name, fields=["name"])
    return len(outstanding) > 0


def get_total_outstanding_amount(customer_name: str) -> float:
    """Get total outstanding amount for customer"""
    try:
        result = frappe.db.sql(
            """
            SELECT SUM(outstanding_amount) as total
            FROM `tabSales Invoice`
            WHERE customer = %(customer)s
                AND docstatus = 1
                AND outstanding_amount > 0
        """,
            {"customer": customer_name},
            as_dict=True,
        )

        return flt(result[0].get("total")) if result else 0.0

    except Exception as e:
        frappe.logger().error(f"Error calculating outstanding amount for {customer_name}: {str(e)}")
        return 0.0


def is_customer_overdue(customer_name: str) -> bool:
    """Check if customer has any overdue invoices"""
    overdue = get_outstanding_invoices(customer_name, due_date_filter="overdue", fields=["name"])
    return len(overdue) > 0


# Cache management utilities


def invalidate_customer_cache(customer_name: str):
    """
    Invalidate all cached financial data for a customer.
    Call this when customer financial data changes.
    """
    try:
        # Clear any cached queries related to this customer
        cache_keys = [
            f"customer_invoices:{customer_name}",
            f"outstanding_invoices:{customer_name}",
            f"payment_summary:{customer_name}",
        ]

        for key in cache_keys:
            try:
                frappe.cache().delete_key(key)
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache delete failed for '{key}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for '{key}': {e}")

        frappe.logger().info(f"Financial cache cleared for customer {customer_name}")

    except Exception as e:
        frappe.logger().error(f"Error clearing financial cache for {customer_name}: {str(e)}")


def refresh_financial_cache():
    """Refresh all financial data caches"""
    try:
        # Clear all financial cache keys
        cache_pattern_keys = ["customer_invoices:*", "outstanding_invoices:*", "payment_summary:*"]

        for pattern in cache_pattern_keys:
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

        frappe.logger().info("All financial caches refreshed")

    except Exception as e:
        frappe.logger().error(f"Error refreshing financial caches: {str(e)}")
