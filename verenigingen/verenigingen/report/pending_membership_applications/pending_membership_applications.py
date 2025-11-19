import frappe
from frappe import _
from frappe.utils import add_days, today

from verenigingen.utils.member_utils import get_member_chapters


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
            "label": _("Application ID"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "Member",
            "width": 120,
        },
        {"label": _("Applicant Name"), "fieldname": "full_name", "fieldtype": "Data", "width": 150},
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
            "fieldname": "selected_membership_type",
            "fieldtype": "Data",
            "width": 130,
        },
        {"label": _("Age"), "fieldname": "age", "fieldtype": "Int", "width": 60},
        {
            "label": _("Volunteer Interest"),
            "fieldname": "volunteer_interest",
            "fieldtype": "Data",
            "width": 120,
        },
        {"label": _("Source"), "fieldname": "application_source", "fieldtype": "Data", "width": 100},
        {"label": _("Status"), "fieldname": "status_indicator", "fieldtype": "HTML", "width": 100},
    ]


def get_data(filters):
    """Get report data"""

    # Base conditions
    conditions = ["m.application_status = 'Pending'"]

    # Apply role-based chapter filtering
    user_chapter_condition = get_user_chapter_filter()
    if user_chapter_condition:
        conditions.append(user_chapter_condition)

    # Apply filters
    if filters:
        # Chapter filtering will be done post-query since we need to check Chapter Member table

        if filters.get("from_date"):
            conditions.append("DATE(m.application_date) >= %(from_date)s")

        if filters.get("to_date"):
            conditions.append("DATE(m.application_date) <= %(to_date)s")

        if filters.get("membership_type"):
            conditions.append("m.current_membership_type = %(membership_type)s")

        if filters.get("overdue_only"):
            overdue_date = add_days(today(), -14)
            conditions.append(f"DATE(m.application_date) < '{overdue_date}'")

        # Support for aging filter (7+ days)
        if filters.get("aging_only"):
            aging_date = add_days(today(), -7)
            conditions.append(f"DATE(m.application_date) < '{aging_date}'")

        # Support for days filter from URL parameters
        if filters.get("days_filter"):
            days = int(filters.get("days_filter"))
            cutoff_date = add_days(today(), -days)
            conditions.append(f"DATE(m.application_date) < '{cutoff_date}'")

    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    else:
        where_clause = ""

    data = frappe.db.sql(
        f"""
        SELECT
            m.name,
            m.full_name,
            m.email,
            m.application_date,
            DATEDIFF(CURDATE(), DATE(m.application_date)) as days_pending,
            m.current_membership_type as selected_membership_type,
            m.age,
            '' as interested_in_volunteering,
            '' as application_source,
            m.application_status
        FROM `tabMember` m
        {where_clause}
        ORDER BY m.application_date ASC
    """,
        filters or {},
        as_dict=True,
    )

    # Batch load member chapters to eliminate N+1 query pattern
    member_names = [row.get("name") for row in data if row.get("name")]
    member_chapters_map = {}

    if member_names:
        # Single query to get all chapter memberships
        chapter_memberships = frappe.db.sql(
            """
            SELECT cm.member, cm.parent as chapter_name
            FROM `tabChapter Member` cm
            WHERE cm.member IN %(member_names)s
            AND cm.status = 'Active'
            ORDER BY cm.member, cm.creation DESC
        """,
            {"member_names": member_names},
            as_dict=True,
        )

        # Group chapters by member
        for cm in chapter_memberships:
            if cm.member not in member_chapters_map:
                member_chapters_map[cm.member] = []
            member_chapters_map[cm.member].append(cm.chapter_name)

    # Process data
    processed_data = []
    for row in data:
        # Get pre-loaded member chapters
        member_chapters = member_chapters_map.get(row.get("name"), [])
        row["chapter"] = member_chapters[0] if member_chapters else "Unassigned"

        # Apply chapter filter if specified
        if filters and filters.get("chapter"):
            if filters.get("chapter") not in member_chapters:
                continue  # Skip this row

        # Add volunteer interest indicator
        row["volunteer_interest"] = "Yes" if row.get("interested_in_volunteering") else "No"

        # Add status indicator with color coding
        days_pending = row.get("days_pending") or 0
        if days_pending > 14:
            row["status_indicator"] = '<span class="indicator red">Overdue</span>'
        elif days_pending > 7:
            row["status_indicator"] = '<span class="indicator orange">Aging</span>'
        else:
            row["status_indicator"] = '<span class="indicator blue">Recent</span>'

        processed_data.append(row)

    return processed_data


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    total_pending = len(data)
    overdue_count = len([d for d in data if (d.get("days_pending") or 0) > 14])
    volunteer_interested = len([d for d in data if d.get("interested_in_volunteering")])

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
        {
            "value": f"{(volunteer_interested / total_pending * 100):.1f}%" if total_pending > 0 else "0%",
            "label": _("Volunteer Interest Rate"),
            "datatype": "Data",
        },
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


def get_user_chapter_filter():
    """Get chapter filter based on user's role and permissions"""
    from verenigingen.utils.chapter_utils import get_user_accessible_chapters

    user = frappe.session.user

    # Use existing utility to get user's accessible chapters with proper permissions
    accessible_chapters = get_user_accessible_chapters(
        user, required_permission_levels=["Admin", "Membership"]
    )

    # None means admin access (see all)
    if accessible_chapters is None:
        return None  # No filter - see all

    # Empty list means no access
    if not accessible_chapters:
        return "1=0"  # No access if user has no chapter permissions

    # Check for national chapter access (existing logic preserved)
    try:
        settings = frappe.get_single("Verenigingen Settings")
        national_chapter = getattr(settings, "national_chapter", None)
        if len(accessible_chapters) == 1 and accessible_chapters[0] == national_chapter and national_chapter:
            # National chapter access - can see all including unassigned
            return None
    except Exception:
        pass

    # Chapter-specific access - proper JOIN-based filtering for security
    chapter_list = "'" + "','".join(accessible_chapters) + "'"
    return f"""(
        EXISTS (
            SELECT 1 FROM `tabChapter Member` cm
            WHERE cm.member = m.name
            AND cm.parent IN ({chapter_list})
            AND cm.status = 'Active'
        ) OR m.preferred_chapter IN ({chapter_list})
        OR m.preferred_chapter IS NULL
        OR m.preferred_chapter = ''
    )"""
