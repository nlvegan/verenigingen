"""
Chapter Dues Split Report

Shows membership dues income grouped by chapter with calculated split between
chapter and national allocations. Used for financial planning and journal entry generation.
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from verenigingen.verenigingen.domain.chapter_dues import DuesAllocationService


def execute(filters: Optional[Dict] = None) -> Tuple[List[Dict], List[Dict]]:
    """
    Execute the Chapter Dues Split report.

    Args:
        filters: Report filters (from_date, to_date, chapter, company)

    Returns:
        columns: List of column definitions
        data: List of data rows
    """
    columns = get_columns(filters)
    data = get_data(filters)

    return columns, data


def get_columns(filters: Optional[Dict]) -> List[Dict]:
    """Define report columns."""
    return [
        {
            "fieldname": "chapter",
            "label": _("Chapter"),
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 180,
        },
        {"fieldname": "total_invoices", "label": _("Invoice Count"), "fieldtype": "Int", "width": 100},
        {"fieldname": "total_amount", "label": _("Total Dues"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "chapter_percentage", "label": _("Chapter %"), "fieldtype": "Percent", "width": 100},
        {"fieldname": "chapter_amount", "label": _("Chapter Amount"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "national_percentage", "label": _("National %"), "fieldtype": "Percent", "width": 100},
        {
            "fieldname": "national_amount",
            "label": _("National Amount"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {"fieldname": "uses_custom_split", "label": _("Custom Split"), "fieldtype": "Check", "width": 100},
    ]


def get_data(filters: Optional[Dict]) -> List[Dict]:
    """
    Get report data grouped by chapter.

    Logic:
        1. Query submitted Sales Invoices with custom_member_chapter
        2. Group by chapter and sum grand_total
        3. Calculate split for each chapter using configured percentages
        4. Return rows with chapter totals and splits
    """
    # Set default date range to current fiscal year if not provided
    if not filters.get("from_date"):
        filters["from_date"] = get_first_day(today())
    if not filters.get("to_date"):
        filters["to_date"] = get_last_day(today())

    # Build query conditions
    conditions = ["si.docstatus = 1"]  # Only submitted invoices

    if filters.get("from_date"):
        conditions.append("si.posting_date >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("si.posting_date <= %(to_date)s")
    if filters.get("chapter"):
        conditions.append("si.custom_member_chapter = %(chapter)s")
    if filters.get("company"):
        conditions.append("si.company = %(company)s")

    # Only include invoices with a chapter assigned
    conditions.append("si.custom_member_chapter IS NOT NULL")
    conditions.append("si.custom_member_chapter != ''")

    where_clause = " AND ".join(conditions)

    # Query aggregated data by chapter
    query = f"""
        SELECT
            si.custom_member_chapter as chapter,
            COUNT(si.name) as total_invoices,
            SUM(si.grand_total) as total_amount
        FROM `tabSales Invoice` si
        WHERE {where_clause}
        GROUP BY si.custom_member_chapter
        ORDER BY si.custom_member_chapter
    """

    chapter_data = frappe.db.sql(query, filters, as_dict=True)

    # Use domain service for calculations (avoids N+1 queries, consistent logic)
    allocation_service = DuesAllocationService()

    # Prepare batch input
    chapter_amounts = {row["chapter"]: flt(row["total_amount"]) for row in chapter_data}

    # Batch calculate all allocations (single query for all chapter configs)
    allocations_map = allocation_service.batch_calculate(chapter_amounts)

    # Get chapter configs to check for custom splits
    chapter_names = list(chapter_amounts.keys())
    chapter_configs = {}
    if chapter_names:
        configs = frappe.db.get_all(
            "Chapter", filters={"name": ["in", chapter_names]}, fields=["name", "chapter_split_percentage"]
        )
        chapter_configs = {c.name: c.chapter_split_percentage for c in configs}

    # Build report data
    data = []
    for row in chapter_data:
        chapter_name = row["chapter"]
        allocation = allocations_map[chapter_name]

        # Chapter has custom split only if value is not None AND not 0
        chapter_pct = chapter_configs.get(chapter_name)
        has_custom_split = chapter_pct is not None and chapter_pct != 0

        data.append(
            {
                "chapter": chapter_name,
                "total_invoices": row["total_invoices"],
                **allocation.to_dict(),
                "uses_custom_split": 1 if has_custom_split else 0,
            }
        )

    return data
