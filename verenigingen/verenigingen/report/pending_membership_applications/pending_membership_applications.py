import frappe
from frappe import _
from frappe.utils import add_days, today


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

    " AND ".join(conditions)

    data = frappe.db.sql(
        """
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
        WHERE {where_clause}
        ORDER BY m.application_date ASC
    """,
        filters or {},
        as_dict=True,
    )

    # Process data
    processed_data = []
    for row in data:
        # Get member chapters
        member_chapters = get_member_chapters(row.get("name"))
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
    user = frappe.session.user

    # System managers and Association/Membership managers see all
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No filter - see all

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return "1=0"  # No access if not a member

    # Get chapters where user has board access with membership permissions
    user_chapters = []
    volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["parent", "chapter_role"],
        )

        for position in board_positions:
            # Check if the role has membership permissions
            try:
                role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                if role_doc.permissions_level in ["Admin", "Membership"]:
                    if position.parent not in user_chapters:
                        user_chapters.append(position.parent)
            except Exception:
                continue

    # Add national chapter if configured and user has access
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_chapter") and settings.national_chapter:
            # Check if user has board access to national chapter
            national_board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={
                    "parent": settings.national_chapter,
                    "volunteer": ["in", [v.name for v in volunteer_records]],
                    "is_active": 1,
                },
                fields=["chapter_role"],
            )

            for position in national_board_positions:
                try:
                    role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                    if role_doc.permissions_level in ["Admin", "Membership"]:
                        if settings.national_chapter not in user_chapters:
                            user_chapters.append(settings.national_chapter)
                        break
                except Exception:
                    continue
    except Exception:
        pass

    if not user_chapters:
        return "1=0"  # No access if not on any board with membership permissions

    # Return filter for user's chapters, including null/empty chapters for national access
    if len(user_chapters) == 1 and user_chapters[0] == getattr(
        frappe.get_single("Verenigingen Settings"), "national_chapter", None
    ):
        # National chapter access - can see all including unassigned
        return None
    else:
        # Chapter-specific access - will be filtered post-query using Chapter Member table
        # For now, return no restriction and filter in Python
        return None


def get_member_chapters(member_name):
    """Get list of chapters a member belongs to"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
        )
        return [ch.parent for ch in chapters]
    except Exception:
        return []
