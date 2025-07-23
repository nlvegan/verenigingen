from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def execute(filters=None):
    """Generate New Members Report"""

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
            "label": _("Member ID"),
            "fieldname": "member_name",
            "fieldtype": "Link",
            "options": "Member",
            "width": 120,
        },
        {"label": _("Member Name"), "fieldname": "member_full_name", "fieldtype": "Data", "width": 180},
        {"label": _("Email"), "fieldname": "member_email", "fieldtype": "Data", "width": 200},
        {
            "label": _("Chapter"),
            "fieldname": "primary_chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 150,
        },
        {"label": _("Membership Type"), "fieldname": "membership_type", "fieldtype": "Data", "width": 130},
        {"label": _("Member Since"), "fieldname": "member_since", "fieldtype": "Date", "width": 120},
        {"label": _("Days Active"), "fieldname": "days_active", "fieldtype": "Int", "width": 100},
        {
            "label": _("Assigned By"),
            "fieldname": "chapter_assigned_by",
            "fieldtype": "Link",
            "options": "User",
            "width": 120,
        },
        {"label": _("Status"), "fieldname": "status_indicator", "fieldtype": "HTML", "width": 100},
    ]


def get_data(filters):
    """Get report data using Frappe ORM methods"""

    # Calculate date threshold for "new" members (default 30 days)
    days_threshold = 30
    if filters and filters.get("days_threshold"):
        days_threshold = int(filters.get("days_threshold"))

    threshold_date = add_days(today(), -days_threshold)

    # Base filters for new members
    member_filters = {"status": "Active"}

    # Apply additional filters
    if filters:
        if filters.get("chapter"):
            member_filters["primary_chapter"] = filters.get("chapter")

        if filters.get("membership_type"):
            # We'll filter this after getting membership data
            pass

        if filters.get("from_date"):
            threshold_date = max(getdate(threshold_date), getdate(filters.get("from_date")))

        if filters.get("to_date"):
            # Filter members who became active before this date
            pass

    # Get members who became active recently
    # We'll look at both creation date and earliest membership start date
    recent_members = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=[
            "name",
            "full_name",
            "email",
            "status",
            "creation",
            "chapter_assigned_by",
            "previous_chapter",
        ],
        order_by="creation desc",
    )

    if not recent_members:
        return []

    # Apply user-based chapter filtering
    user_chapters = get_user_accessible_chapters()

    data = []
    for member in recent_members:
        # Get membership information
        membership_info = get_member_membership_info(member.name)
        member_since = membership_info.get("member_since")
        membership_type = membership_info.get("membership_type")

        # Skip if member_since is not within threshold
        if member_since and getdate(member_since) < getdate(threshold_date):
            continue

        # If no membership found, use creation date
        if not member_since:
            member_since = member.creation
            if getdate(member_since) < getdate(threshold_date):
                continue

        # Apply membership type filter
        if filters and filters.get("membership_type"):
            if membership_type != filters.get("membership_type"):
                continue

        # Apply to_date filter
        if filters and filters.get("to_date"):
            if getdate(member_since) > getdate(filters.get("to_date")):
                continue

        # Get primary chapter using new chapter system
        member_chapters = member.get_current_chapters()
        primary_chapter = member_chapters[0]["chapter"] if member_chapters else None

        # Apply user access filtering
        if user_chapters is not None:  # None means see all
            if primary_chapter and primary_chapter not in user_chapters:
                # Check if user has national access
                try:
                    settings = frappe.get_single("Verenigingen Settings")
                    if (
                        hasattr(settings, "national_board_chapter")
                        and settings.national_board_chapter in user_chapters
                    ):
                        pass  # User has national access
                    else:
                        continue  # Skip this member
                except Exception:
                    continue

        # Calculate days active
        days_active = (getdate(today()) - getdate(member_since)).days

        # Determine if this is a new member or recent chapter change
        is_chapter_change = False
        # Chapter change detection removed since chapter_assigned_date field was removed
        # This now only shows new members, not chapter changes

        # Build row data
        row = {
            "member_name": member.name,
            "member_full_name": member.full_name,
            "member_email": member.email,
            "primary_chapter": primary_chapter,
            "membership_type": membership_type,
            "member_since": member_since,
            "days_active": days_active,
            "chapter_assigned_by": member.chapter_assigned_by,
            "status_indicator": get_status_indicator(days_active, is_chapter_change),
        }

        data.append(row)

    # Sort by member_since date (newest first)
    data.sort(key=lambda x: getdate(x["member_since"]), reverse=True)

    return data


def get_member_membership_info(member_name):
    """Get membership information for a member"""
    try:
        # Get the earliest active membership to determine "member since" date
        earliest_membership = frappe.get_value(
            "Membership", {"member": member_name}, ["from_date", "membership_type"], order_by="from_date"
        )

        if earliest_membership:
            return {"member_since": earliest_membership[0], "membership_type": earliest_membership[1]}

        # If no membership found, get current membership
        current_membership = frappe.get_value(
            "Membership", {"member": member_name, "status": "Active"}, ["from_date", "membership_type"]
        )

        if current_membership:
            return {"member_since": current_membership[0], "membership_type": current_membership[1]}

        return {"member_since": None, "membership_type": "No Membership"}

    except Exception:
        return {"member_since": None, "membership_type": "Unknown"}


def get_status_indicator(days_active, is_chapter_change):
    """Generate status indicator with color coding"""
    if is_chapter_change:
        return '<span class="indicator blue">Chapter Change</span>'
    elif days_active <= 7:
        return '<span class="indicator green">Very New</span>'
    elif days_active <= 14:
        return '<span class="indicator blue">New</span>'
    elif days_active <= 30:
        return '<span class="indicator orange">Recent</span>'
    else:
        return '<span class="indicator grey">Established</span>'


def get_user_accessible_chapters():
    """Get chapters accessible to current user"""
    user = frappe.session.user

    # System managers and Association/Membership managers see all
    admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No filter - see all

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return []  # No access if not a member

    # Get chapters where user has board access with membership or admin permissions
    user_chapters = []
    try:
        volunteer_records = frappe.get_all("Volunteer", filters={"member": user_member}, fields=["name"])

        for volunteer_record in volunteer_records:
            board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_record.name, "is_active": 1},
                fields=["parent", "chapter_role"],
            )

            for position in board_positions:
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
            if hasattr(settings, "national_board_chapter") and settings.national_board_chapter:
                national_board_positions = frappe.get_all(
                    "Chapter Board Member",
                    filters={
                        "parent": settings.national_board_chapter,
                        "volunteer": [v.name for v in volunteer_records],
                        "is_active": 1,
                    },
                    fields=["chapter_role"],
                )

                for position in national_board_positions:
                    try:
                        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
                        if role_doc.permissions_level in ["Admin", "Membership"]:
                            if settings.national_board_chapter not in user_chapters:
                                user_chapters.append(settings.national_board_chapter)
                            break
                    except Exception:
                        continue
        except Exception:
            pass
    except Exception:
        pass

    return user_chapters if user_chapters else []


def get_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    total_new_members = len(data)
    very_new_count = len([d for d in data if d.get("days_active", 0) <= 7])
    recent_changes = len([d for d in data if "Chapter Change" in d.get("status_indicator", "")])

    # Group by chapter
    chapters = {}
    for row in data:
        chapter = row.get("primary_chapter") or "Unassigned"
        chapters[chapter] = chapters.get(chapter, 0) + 1

    most_active_chapter = max(chapters.items(), key=lambda x: x[1]) if chapters else ("None", 0)

    # Calculate average days active
    avg_days_active = sum(d.get("days_active", 0) for d in data) / len(data) if data else 0

    return [
        {"value": total_new_members, "label": _("Total New Members"), "datatype": "Int", "color": "green"},
        {"value": very_new_count, "label": _("Very New (≤7 days)"), "datatype": "Int", "color": "blue"},
        {"value": recent_changes, "label": _("Recent Chapter Changes"), "datatype": "Int", "color": "orange"},
        {
            "value": f"{most_active_chapter[0]} ({most_active_chapter[1]})",
            "label": _("Most Active Chapter"),
            "datatype": "Data",
        },
        {"value": round(avg_days_active, 1), "label": _("Average Days Active"), "datatype": "Float"},
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by week for trend analysis
    weekly_data = {}
    for row in data:
        member_since = getdate(row.get("member_since"))
        # Get the start of the week (Monday)
        week_start = member_since - timedelta(days=member_since.weekday())
        week_key = week_start.strftime("%Y-%m-%d")
        weekly_data[week_key] = weekly_data.get(week_key, 0) + 1

    # Sort by date and get last 8 weeks
    sorted_weeks = sorted(weekly_data.items())[-8:]

    return {
        "data": {
            "labels": [week[0] for week in sorted_weeks],
            "datasets": [{"name": _("New Members"), "values": [week[1] for week in sorted_weeks]}],
        },
        "type": "line",
        "colors": ["#28a745"],
    }
