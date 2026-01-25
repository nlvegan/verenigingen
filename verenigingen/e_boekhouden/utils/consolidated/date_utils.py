"""
Shared date utilities for E-Boekhouden integration.

This module contains cross-cutting date helpers used by invoices,
payments, and migrations. Centralizing these utilities ensures consistent
behavior across all E-Boekhouden import processes.
"""

from datetime import date

import frappe
from frappe.utils import getdate


def ensure_fiscal_year_exists(transaction_date, company, debug_info=None):
    """
    Ensure a fiscal year exists for the given transaction date.
    Creates one automatically if missing to prevent submission errors.

    Args:
        transaction_date: Date string or date object for the transaction
        company: Company name to check fiscal year for
        debug_info: Optional list to append debug messages

    Returns:
        str: Name of the fiscal year (existing or newly created)

    Note:
        Uses ignore_permissions for automated fiscal year creation during
        import processes. All creations are logged for audit purposes.

    Example:
        >>> debug_info = []
        >>> fy_name = ensure_fiscal_year_exists("2024-03-15", "My Company", debug_info)
        >>> print(fy_name)
        '2024'
    """
    if debug_info is None:
        debug_info = []

    try:
        # Convert to date object if string
        if isinstance(transaction_date, str):
            transaction_date = getdate(transaction_date)

        # Check if fiscal year already exists for this date
        # Note: Fiscal Years are global in ERPNext, not company-specific
        existing_fy = frappe.db.sql(
            """
            SELECT name, year_start_date, year_end_date
            FROM `tabFiscal Year`
            WHERE %s BETWEEN year_start_date AND year_end_date
            AND disabled = 0
            LIMIT 1
            """,
            (transaction_date,),
            as_dict=True,
        )

        if existing_fy:
            debug_info.append(f"Fiscal year {existing_fy[0].name} exists for date {transaction_date}")
            return existing_fy[0].name

        # No fiscal year found - create one for the calendar year
        year = transaction_date.year
        fy_name = str(year)

        # Check if this fiscal year name already exists (for another company)
        existing_fy_name = frappe.db.get_value(
            "Fiscal Year",
            {"name": fy_name},
            ["name", "year_start_date", "year_end_date"],
            as_dict=True,
        )

        if existing_fy_name:
            debug_info.append(
                f"Fiscal year {fy_name} already exists: {existing_fy_name.year_start_date} to {existing_fy_name.year_end_date}"
            )
            return fy_name

        # Create new fiscal year for calendar year (Jan 1 - Dec 31)
        year_start = date(year, 1, 1)
        year_end = date(year, 12, 31)

        debug_info.append(f"Creating fiscal year {fy_name} for {company}: {year_start} to {year_end}")

        fiscal_year = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": fy_name,
                "year_start_date": year_start,
                "year_end_date": year_end,
                "disabled": 0,
            }
        )

        # Note: Using ignore_permissions for automated fiscal year creation during imports
        # Audit: All fiscal year creations are logged in debug_info for traceability
        fiscal_year.insert(ignore_permissions=True)

        debug_info.append(f"Created fiscal year {fy_name} for transactions in {year}")

        return fy_name

    except Exception as e:
        error_msg = f"Failed to ensure fiscal year for {transaction_date}: {str(e)}"
        debug_info.append(error_msg)
        frappe.log_error(
            f"{error_msg}\n\nTraceback:\n{frappe.get_traceback()}",
            "Fiscal Year Auto-Creation Error",
        )
        # Re-raise so caller knows creation failed
        raise
