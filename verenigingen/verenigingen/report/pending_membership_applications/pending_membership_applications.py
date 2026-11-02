import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
    """Generate Pending Membership Applications Report"""

    columns = get_columns()
    data = get_data(filters)

    # Add summary statistics
    summary = get_summary(data)

    # Add chart data
    chart = get_chart_data(data)

    return columns, data, None, chart, summary


def get_columns():
    """Define report columns"""
    return [
        {
            "label": _("Application"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "Membership Application Submission",
            "width": 120,
        },
        {"label": _("Applicant Name"), "fieldname": "applicant_name", "fieldtype": "Data", "width": 150},
        {"label": _("Email"), "fieldname": "email", "fieldtype": "Data", "width": 150},
        {
            "label": _("Application Date"),
            "fieldname": "application_date",
            "fieldtype": "Datetime",
            "width": 140,
        },
        {"label": _("Days Pending"), "fieldname": "days_pending", "fieldtype": "Int", "width": 100},
        {
            "label": _("Chapter"),
            "fieldname": "chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 120,
        },
        {
            "label": _("Membership Type"),
            "fieldname": "membership_type",
            "fieldtype": "Link",
            "options": "Membership Type",
            "width": 130,
        },
        {"label": _("Source"), "fieldname": "source", "fieldtype": "Data", "width": 100},
        {"label": _("Status"), "fieldname": "status_indicator", "fieldtype": "HTML", "width": 100},
    ]


def get_data(filters):
    """Pending Review applications the caller may read, one row each.

    The rows come from `pending_review_applications`, i.e. `frappe.get_list` on the application, so
    a board member sees only the chapters of their seats (the MAS permission query) with no hand-made
    chapter filter here, oldest first (the oldest pending rows matter most). The report filters narrow that list afterwards.
    """
    from verenigingen.services.member.application.pending_applications import pending_review_applications

    filters = filters or {}
    rows = pending_review_applications(chapter=filters.get("chapter"), oldest_first=True)
    data = [_with_indicator(row) for row in rows if _passes_filters(row, filters)]
    for row in data:
        row["chapter"] = row["chapter"] or "Unassigned"
    return data


def _passes_filters(row, filters):
    """The date, type and age filters; each compares against the application's confirmation date."""
    applied = getdate(row["application_date"]) if row.get("application_date") else None
    if filters.get("from_date") and (not applied or applied < getdate(filters["from_date"])):
        return False
    if filters.get("to_date") and (not applied or applied > getdate(filters["to_date"])):
        return False
    if filters.get("membership_type") and row.get("membership_type") != filters["membership_type"]:
        return False
    older_than = _older_than_days(filters)
    return older_than is None or (row.get("days_pending") or 0) > older_than


def _older_than_days(filters):
    """The strictest of the overdue (14), aging (7) and custom day filters, or None when none is set."""
    limits = []
    if filters.get("overdue_only"):
        limits.append(14)
    if filters.get("aging_only"):
        limits.append(7)
    if filters.get("days_filter"):
        limits.append(int(filters["days_filter"]))
    return max(limits) if limits else None


def _with_indicator(row):
    """Colour-coded status: red over 14 days, orange over 7, blue otherwise."""
    days_pending = row.get("days_pending") or 0
    if days_pending > 14:
        row["status_indicator"] = '<span class="indicator red">Overdue</span>'
    elif days_pending > 7:
        row["status_indicator"] = '<span class="indicator orange">Aging</span>'
    else:
        row["status_indicator"] = '<span class="indicator blue">Recent</span>'
    return row


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    total_pending = len(data)
    overdue_count = len([d for d in data if (d.get("days_pending") or 0) > 14])

    avg_days_pending = sum((d.get("days_pending") or 0) for d in data) / len(data) if data else 0

    return [
        {"value": total_pending, "label": _("Total Pending"), "datatype": "Int"},
        {
            "value": overdue_count,
            "label": _("Overdue (>14 days)"),
            "datatype": "Int",
            "color": "red" if overdue_count > 0 else "green",
        },
        {"value": round(avg_days_pending, 1), "label": _("Average Days Pending"), "datatype": "Float"},
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by chapter
    chapter_counts = {}
    for row in data:
        chapter = row.get("chapter") or "Unassigned"
        chapter_counts[chapter] = chapter_counts.get(chapter, 0) + 1

    return {
        "data": {
            "labels": list(chapter_counts.keys()),
            "datasets": [{"name": _("Pending Applications"), "values": list(chapter_counts.values())}],
        },
        "type": "bar",
        "colors": ["#7cd6fd"],
    }
