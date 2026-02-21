# Copyright (c) 2025, Molekuul and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from verenigingen.utils.constants import Roles


def execute(filters=None):
    """
    Database Table Size Analysis Report

    Shows detailed breakdown of database storage usage by table with visual indicators.
    """
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart_data(data)

    return columns, data, None, chart


def get_columns():
    """Define report columns"""
    return [
        {"fieldname": "table_name", "label": _("Table Name"), "fieldtype": "Data", "width": 250},
        {"fieldname": "doctype", "label": _("DocType"), "fieldtype": "Data", "width": 200},
        {"fieldname": "row_count", "label": _("Rows"), "fieldtype": "Int", "width": 100},
        {
            "fieldname": "data_size_mb",
            "label": _("Data (MB)"),
            "fieldtype": "Float",
            "width": 120,
            "precision": 2,
        },
        {
            "fieldname": "index_size_mb",
            "label": _("Index (MB)"),
            "fieldtype": "Float",
            "width": 120,
            "precision": 2,
        },
        {
            "fieldname": "total_size_mb",
            "label": _("Total (MB)"),
            "fieldtype": "Float",
            "width": 120,
            "precision": 2,
        },
        {"fieldname": "avg_row_size", "label": _("Avg Row Size (bytes)"), "fieldtype": "Int", "width": 150},
        {"fieldname": "percentage", "label": _("% of Total"), "fieldtype": "Percent", "width": 100},
        {"fieldname": "engine", "label": _("Engine"), "fieldtype": "Data", "width": 80},
        {"fieldname": "table_type", "label": _("Type"), "fieldtype": "Data", "width": 100},
    ]


def get_data(filters=None):
    """Get table size data from database"""

    # Get table statistics
    table_stats = frappe.db.sql(
        """
        SELECT
            TABLE_NAME as table_name,
            TABLE_ROWS as row_count,
            ROUND(DATA_LENGTH / 1024 / 1024, 2) as data_size_mb,
            ROUND(INDEX_LENGTH / 1024 / 1024, 2) as index_size_mb,
            ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) as total_size_mb,
            ROUND(DATA_LENGTH / NULLIF(TABLE_ROWS, 0), 0) as avg_row_size,
            ENGINE as engine
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
        AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC
    """,
        (frappe.conf.db_name,),
        as_dict=True,
    )

    # Calculate total size for percentage calculation
    total_db_size = sum(t.total_size_mb for t in table_stats)

    # Add calculated fields
    for row in table_stats:
        # Determine DocType name from table name
        if row.table_name.startswith("tab"):
            doctype = row.table_name[3:]  # Remove 'tab' prefix
            # Handle child tables
            if " " in doctype:
                row.table_type = "Child Table"
            else:
                row.table_type = "DocType"
            row.doctype = doctype
        elif row.table_name.startswith("__"):
            row.table_type = "System"
            row.doctype = "System Table"
        else:
            row.table_type = "Other"
            row.doctype = "-"

        # Calculate percentage
        row.percentage = (row.total_size_mb / total_db_size * 100) if total_db_size > 0 else 0

        # Ensure avg_row_size is not None
        if row.avg_row_size is None:
            row.avg_row_size = 0

    # Apply filters if provided
    if filters:
        if filters.get("table_type"):
            table_stats = [t for t in table_stats if t.table_type == filters.get("table_type")]

        if filters.get("min_size_mb"):
            min_size = float(filters.get("min_size_mb"))
            table_stats = [t for t in table_stats if t.total_size_mb >= min_size]

        if filters.get("doctype_filter"):
            doctype_filter = filters.get("doctype_filter").lower()
            table_stats = [t for t in table_stats if doctype_filter in t.doctype.lower()]

    return table_stats


def get_chart_data(data):
    """Generate chart data for visualization"""

    # Get top 15 tables by size for the chart
    top_tables = sorted(data, key=lambda x: x.total_size_mb, reverse=True)[:15]

    return {
        "data": {
            "labels": [t.doctype if t.doctype != "-" else t.table_name for t in top_tables],
            "datasets": [
                {"name": "Data Size (MB)", "values": [t.data_size_mb for t in top_tables]},
                {"name": "Index Size (MB)", "values": [t.index_size_mb for t in top_tables]},
            ],
        },
        "type": "bar",
        "colors": ["#4C9AFF", "#FFA94D"],
        "barOptions": {"stacked": 1},
        "height": 300,
        "axisOptions": {"xIsSeries": 1},
    }


@frappe.whitelist()
def optimize_all_tables():
    """
    Run OPTIMIZE TABLE on all tables to reclaim space.

    Security: System Manager only
    Returns: Count of optimized tables
    """
    # Security check
    if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can optimize tables"), frappe.PermissionError)

    # Get all table names
    tables = frappe.db.sql(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
        AND TABLE_TYPE = 'BASE TABLE'
    """,
        (frappe.conf.db_name,),
        as_dict=True,
    )

    optimized_count = 0
    errors = []

    for table in tables:
        try:
            frappe.db.sql(f"OPTIMIZE TABLE `{table.TABLE_NAME}`")
            optimized_count += 1
        except Exception as e:
            errors.append({"table": table.TABLE_NAME, "error": str(e)})
            frappe.log_error(f"Failed to optimize table {table.TABLE_NAME}: {e}", "Table Optimization Error")

    frappe.logger("verenigingen.database_analysis").info(
        f"Optimized {optimized_count} tables, {len(errors)} errors"
    )

    return {"optimized_count": optimized_count, "total_tables": len(tables), "errors": errors}


@frappe.whitelist()
def analyze_all_tables():
    """
    Run ANALYZE TABLE on all tables to update statistics.

    Security: System Manager only
    Returns: Count of analyzed tables
    """
    # Security check
    if frappe.session.user != "Administrator" and Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can analyze tables"), frappe.PermissionError)

    # Get all table names
    tables = frappe.db.sql(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s
        AND TABLE_TYPE = 'BASE TABLE'
    """,
        (frappe.conf.db_name,),
        as_dict=True,
    )

    analyzed_count = 0
    errors = []

    for table in tables:
        try:
            frappe.db.sql(f"ANALYZE TABLE `{table.TABLE_NAME}`")
            analyzed_count += 1
        except Exception as e:
            errors.append({"table": table.TABLE_NAME, "error": str(e)})
            frappe.log_error(f"Failed to analyze table {table.TABLE_NAME}: {e}", "Table Analysis Error")

    frappe.logger("verenigingen.database_analysis").info(
        f"Analyzed {analyzed_count} tables, {len(errors)} errors"
    )

    return {"analyzed_count": analyzed_count, "total_tables": len(tables), "errors": errors}
