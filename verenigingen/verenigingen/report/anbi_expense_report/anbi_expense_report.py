# Copyright (c) 2025, NVV and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(data)

    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "category",
            "label": _("ANBI Category"),
            "fieldtype": "Data",
            "width": 250,
        },
        {
            "fieldname": "account_number",
            "label": _("Account"),
            "fieldtype": "Data",
            "width": 80,
        },
        {
            "fieldname": "personnel_costs",
            "label": _("Personnel Costs"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "other_expenses",
            "label": _("Other Expenses"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "total",
            "label": _("Total"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "percentage",
            "label": _("% of Total"),
            "fieldtype": "Percent",
            "width": 100,
        },
    ]


def get_data(filters):
    if not filters:
        filters = {}

    company = filters.get("company") or get_default_company()
    fiscal_year = filters.get("fiscal_year")

    if not fiscal_year:
        fiscal_year = frappe.defaults.get_user_default("fiscal_year")

    # Get fiscal year dates
    fy_dates = frappe.db.get_value(
        "Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True
    )

    if not fy_dates:
        return []

    # ANBI categories mapping
    anbi_categories = {
        "61": {
            "name": "Besteed aan doelstellingen",
            "description": "Program costs",
        },
        "62": {
            "name": "Kosten werving baten",
            "description": "Fundraising costs",
        },
        "63": {
            "name": "Beheer en administratie",
            "description": "Administration costs",
        },
    }

    # Get GL expenses grouped by ANBI parent
    gl_expenses = get_gl_expenses_by_anbi_parent(
        company, fy_dates.year_start_date, fy_dates.year_end_date
    )

    # Get personnel allocations
    personnel = get_personnel_allocations(fiscal_year)

    # Build result rows
    data = []
    grand_total = 0

    for acc_num in ["61", "62", "63"]:
        cat = anbi_categories[acc_num]
        personnel_cost = personnel.get(acc_num, 0)
        other_cost = gl_expenses.get(acc_num, 0)
        total = personnel_cost + other_cost
        grand_total += total

        data.append(
            {
                "category": cat["name"],
                "account_number": acc_num,
                "personnel_costs": personnel_cost,
                "other_expenses": other_cost,
                "total": total,
                "percentage": 0,  # Calculate after we have grand total
            }
        )

    # Calculate percentages
    for row in data:
        if grand_total > 0:
            row["percentage"] = (row["total"] / grand_total) * 100

    # Add total row
    total_personnel = sum(row["personnel_costs"] for row in data)
    total_other = sum(row["other_expenses"] for row in data)

    data.append(
        {
            "category": _("TOTAL"),
            "account_number": "",
            "personnel_costs": total_personnel,
            "other_expenses": total_other,
            "total": grand_total,
            "percentage": 100 if grand_total > 0 else 0,
            "is_total": True,
        }
    )

    return data


def get_gl_expenses_by_anbi_parent(company, from_date, to_date):
    """Get GL expenses grouped by ANBI parent account (61, 62, 63).

    Excludes personnel cost accounts (64xx) as those come from Staff ANBI Allocation.
    """
    # Find all expense accounts under 61, 62, 63 parents
    # Debit = expense, so we sum debit - credit for expense accounts

    result = frappe.db.sql(
        """
        SELECT
            SUBSTRING(parent_acc.account_number, 1, 2) as anbi_parent,
            SUM(gl.debit - gl.credit) as total_expense
        FROM `tabGL Entry` gl
        JOIN `tabAccount` acc ON gl.account = acc.name
        JOIN `tabAccount` parent_acc ON acc.parent_account = parent_acc.name
        WHERE gl.company = %s
        AND gl.posting_date BETWEEN %s AND %s
        AND gl.is_cancelled = 0
        AND parent_acc.account_number IN ('61', '62', '63')
        AND acc.account_number NOT LIKE '64%%'
        GROUP BY SUBSTRING(parent_acc.account_number, 1, 2)
        """,
        (company, from_date, to_date),
        as_dict=True,
    )

    return {row.anbi_parent: row.total_expense or 0 for row in result}


def get_personnel_allocations(fiscal_year):
    """Get personnel cost totals from Staff ANBI Allocation records."""
    allocations = frappe.get_all(
        "Staff ANBI Allocation",
        filters={"fiscal_year": fiscal_year},
        fields=["amount_doelstelling", "amount_werving", "amount_beheer"],
    )

    totals = {"61": 0, "62": 0, "63": 0}

    for alloc in allocations:
        totals["61"] += alloc.amount_doelstelling or 0
        totals["62"] += alloc.amount_werving or 0
        totals["63"] += alloc.amount_beheer or 0

    return totals


def get_default_company():
    """Get company from Verenigingen Settings or Global Defaults."""
    company = frappe.db.get_single_value("Verenigingen Settings", "company")
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company")
    return company


def get_chart(data):
    """Generate pie chart for ANBI category breakdown."""
    if not data or len(data) < 3:
        return None

    # Exclude total row
    category_data = [row for row in data if not row.get("is_total")]

    labels = [row["category"] for row in category_data]
    values = [row["total"] for row in category_data]

    return {
        "data": {"labels": labels, "datasets": [{"values": values}]},
        "type": "pie",
        "colors": ["#5e64ff", "#ffa00a", "#29cd42"],
    }


def get_summary(data):
    """Generate summary cards."""
    if not data:
        return []

    # Find total row
    total_row = next((row for row in data if row.get("is_total")), None)
    if not total_row:
        return []

    # Find doelstelling row for percentage
    doelstelling = next(
        (row for row in data if row.get("account_number") == "61"), None
    )

    summary = [
        {
            "value": total_row["total"],
            "label": _("Total Expenses"),
            "datatype": "Currency",
        },
        {
            "value": total_row["personnel_costs"],
            "label": _("Personnel Costs"),
            "datatype": "Currency",
        },
        {
            "value": total_row["other_expenses"],
            "label": _("Other Expenses"),
            "datatype": "Currency",
        },
    ]

    if doelstelling:
        summary.append(
            {
                "value": doelstelling["percentage"],
                "label": _("% to Mission"),
                "datatype": "Percent",
                "indicator": "green" if doelstelling["percentage"] >= 70 else "orange",
            }
        )

    return summary
