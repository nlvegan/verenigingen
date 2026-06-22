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
            fy_name = existing_fy[0].name
            debug_info.append(f"Fiscal year {fy_name} exists for date {transaction_date}")
            # A Fiscal Year row existing for the date is NOT sufficient: ERPNext's
            # get_fiscal_years(date, company=X) only returns a FY whose `companies`
            # child table is EMPTY (applies to all companies) or explicitly lists X.
            # If the located FY is restricted to OTHER companies, submitting a dated
            # document for `company` still raises FiscalYearError. Ensure `company`
            # is covered so the subsequent submit succeeds.
            _ensure_company_in_fiscal_year(fy_name, company, debug_info)
            return fy_name

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
            _ensure_company_in_fiscal_year(fy_name, company, debug_info)
            return fy_name

        # Reuse any Fiscal Year whose range overlaps the target calendar year
        # rather than creating a colliding one. erpnext v16's overlap guard
        # rejects an (unrestricted) calendar-year FY when ANY FY already overlaps
        # that range -- e.g. a company-scoped FY-<abbr>-<year> a sibling test
        # created, or a fiscal-year-offset FY that the today()-BETWEEN lookup
        # above does not return. Reusing it (and ensuring our company is covered)
        # keeps a single FY per year and avoids "overlapping with ..." failures.
        overlapping = frappe.db.sql(
            """
            SELECT name
            FROM `tabFiscal Year`
            WHERE year_start_date <= %(end)s AND year_end_date >= %(start)s
            AND disabled = 0
            LIMIT 1
            """,
            {"start": date(year, 1, 1), "end": date(year, 12, 31)},
            as_dict=True,
        )
        if overlapping:
            fy_name = overlapping[0].name
            debug_info.append(f"Reusing overlapping fiscal year {fy_name} for {year}")
            _ensure_company_in_fiscal_year(fy_name, company, debug_info)
            return fy_name

        # Permission check: Only allow auto-creation if user can create fiscal years
        if not frappe.has_permission("Fiscal Year", "create"):
            error_msg = (
                f"User {frappe.session.user} lacks permission to create Fiscal Year. "
                f"Please ask an administrator to create fiscal year {fy_name}."
            )
            debug_info.append(error_msg)
            raise frappe.PermissionError(error_msg)

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

        # Security: Automated fiscal year creation during eBoekhouden import - system context
        # Audit: All fiscal year creations are logged in debug_info for traceability
        try:
            fiscal_year.insert(ignore_permissions=True)
            debug_info.append(f"Created fiscal year {fy_name} for transactions in {year}")
        except frappe.DuplicateEntryError:
            # Another concurrent process created it - this is fine, use the existing one
            debug_info.append(f"Concurrent fiscal year creation detected for {fy_name}, using existing")

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


def _ensure_company_in_fiscal_year(fy_name, company, debug_info):
    """Make a Fiscal Year usable for ``company``.

    ERPNext's ``get_fiscal_years(date, company=X)`` returns a FY only when its
    ``companies`` child table is empty (global) or explicitly lists X. When a
    company-restricted FY covers the transaction date but does NOT list our
    company, document submission raises ``FiscalYearError`` even though the FY
    "exists". Append our company to the FY's ``companies`` table (idempotent)
    and clear the cached fiscal-year list so the next lookup sees the change.
    """
    company_rows = frappe.db.get_all("Fiscal Year Company", filters={"parent": fy_name}, pluck="company")
    # Empty companies table => FY already applies to every company; nothing to do.
    if not company_rows or company in company_rows:
        return

    fy = frappe.get_doc("Fiscal Year", fy_name)
    fy.append("companies", {"company": company})
    fy.save(ignore_permissions=True)
    # FiscalYear.on_update clears the "fiscal_years" cache; be explicit in case
    # this runs outside a normal document save context.
    frappe.cache().delete_key("fiscal_years")
    debug_info.append(f"Added company {company} to fiscal year {fy_name}")
