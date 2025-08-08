import frappe
from frappe import _
from frappe.utils import add_days, getdate, today


def execute(filters=None):
    """Generate Recent Chapter Changes Report"""
    # NOTE: This report needs to be updated to use Chapter Membership History
    # since the chapter_assigned_date field has been removed from Member doctype

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
        {
            "label": _("Previous Chapter"),
            "fieldname": "previous_chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 150,
        },
        {
            "label": _("Current Chapter"),
            "fieldname": "current_chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 150,
        },
        # Field removed - using chapter membership history instead
        # {
        #     "label": _("Change Date"),
        #     "fieldname": "chapter_assigned_date",
        #     "fieldtype": "Datetime",
        #     "width": 140
        # },
        {
            "label": _("Changed By"),
            "fieldname": "chapter_assigned_by",
            "fieldtype": "Link",
            "options": "User",
            "width": 120,
        },
        {"label": _("Reason"), "fieldname": "chapter_change_reason", "fieldtype": "Small Text", "width": 200},
        {"label": _("Days Ago"), "fieldname": "days_ago", "fieldtype": "Int", "width": 80},
        {"label": _("Change Type"), "fieldname": "change_type", "fieldtype": "HTML", "width": 120},
        {"label": _("Contact"), "fieldname": "member_email", "fieldtype": "Data", "width": 180},
    ]


def get_data(filters):
    """Get report data for recent chapter changes"""

    # Calculate date threshold for "recent" changes (default 30 days)
    days_threshold = 30
    if filters and filters.get("days_threshold"):
        days_threshold = int(filters.get("days_threshold"))

    threshold_date = add_days(today(), -days_threshold)

    # Base filters for members with recent chapter changes
    member_filters = {"modified": [">=", threshold_date]}

    # Apply additional filters
    if filters:
        if filters.get("current_chapter"):
            # For current chapter filtering, we'll filter the results after getting member chapters
            pass

        if filters.get("previous_chapter"):
            member_filters["previous_chapter"] = filters.get("previous_chapter")

        if filters.get("changed_by"):
            member_filters["chapter_assigned_by"] = filters.get("changed_by")

        if filters.get("from_date"):
            filter_from_date = getdate(filters.get("from_date"))
            if filter_from_date > getdate(threshold_date):
                member_filters["modified"] = [">=", filter_from_date]

        if filters.get("to_date"):
            if "modified" in member_filters and isinstance(member_filters["modified"], list):
                # Already has a from date filter
                from_date = member_filters["modified"][1]
                member_filters["modified"] = ["between", [from_date, filters.get("to_date")]]
            else:
                member_filters["modified"] = ["<=", filters.get("to_date")]

    # Get members with recent chapter changes
    recent_changes = frappe.get_all(
        "Member",
        filters=member_filters,
        fields=[
            "name",
            "full_name",
            "email",
            "previous_chapter",
            "chapter_assigned_by",
            "chapter_change_reason",
            "modified",
        ],
        order_by="modified desc",
    )

    if not recent_changes:
        return []

    # Apply user-based access filtering
    user_chapters = get_user_accessible_chapters()

    data = []
    for member in recent_changes:
        # Get member's current chapters
        current_chapters = get_member_chapters(member.name)
        primary_chapter = current_chapters[0] if current_chapters else None

        # Apply current chapter filter if specified
        if filters and filters.get("current_chapter"):
            if filters.get("current_chapter") not in current_chapters:
                continue

        # Apply user access filtering
        if user_chapters is not None:  # None means see all
            # Check if user can see this member's current or previous chapter
            can_see_current = not primary_chapter or primary_chapter in user_chapters
            can_see_previous = not member.previous_chapter or member.previous_chapter in user_chapters

            # If user has national access, they can see all
            has_national_access = False
            try:
                settings = frappe.get_single("Verenigingen Settings")
                if (
                    hasattr(settings, "national_board_chapter")
                    and settings.national_board_chapter in user_chapters
                ):
                    has_national_access = True
            except Exception:
                pass

            if not has_national_access and not (can_see_current or can_see_previous):
                continue

        # Calculate days ago
        change_date = member.modified
        if hasattr(change_date, "date"):
            change_date = change_date.date()
        days_ago = (getdate(today()) - getdate(change_date)).days

        # Determine change type
        change_type = get_change_type(member.previous_chapter, primary_chapter)

        # Build row data
        row = {
            "member_name": member.name,
            "member_full_name": member.full_name,
            "member_email": member.email,
            "previous_chapter": member.previous_chapter or _("Unassigned"),
            "current_chapter": primary_chapter or _("Unassigned"),
            "modified": member.modified,
            "chapter_assigned_by": member.chapter_assigned_by,
            "chapter_change_reason": member.chapter_change_reason,
            "days_ago": days_ago,
            "change_type": change_type,
        }

        data.append(row)

    return data


def get_change_type(previous_chapter, current_chapter):
    """Determine the type of chapter change"""
    if not previous_chapter and current_chapter:
        return '<span class="indicator green">Initial Assignment</span>'
    elif previous_chapter and not current_chapter:
        return '<span class="indicator red">Removed from Chapter</span>'
    elif previous_chapter and current_chapter:
        return '<span class="indicator blue">Chapter Transfer</span>'
    else:
        return '<span class="indicator grey">Unknown</span>'


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
                "Verenigingen Chapter Board Member",
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
                    "Verenigingen Chapter Board Member",
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

    total_changes = len(data)

    # Count change types
    initial_assignments = len([d for d in data if "Initial Assignment" in d.get("change_type", "")])
    transfers = len([d for d in data if "Chapter Transfer" in d.get("change_type", "")])
    len([d for d in data if "Removed from Chapter" in d.get("change_type", "")])

    # Most active changer
    changers = {}
    for row in data:
        changer = row.get("chapter_assigned_by") or "System"
        changers[changer] = changers.get(changer, 0) + 1

    most_active_changer = max(changers.items(), key=lambda x: x[1]) if changers else ("None", 0)

    # Recent activity (last 7 days)
    recent_activity = len([d for d in data if d.get("days_ago", 0) <= 7])

    return [
        {"value": total_changes, "label": _("Total Chapter Changes"), "datatype": "Int", "color": "blue"},
        {
            "value": initial_assignments,
            "label": _("Initial Assignments"),
            "datatype": "Int",
            "color": "green",
        },
        {"value": transfers, "label": _("Chapter Transfers"), "datatype": "Int", "color": "orange"},
        {"value": recent_activity, "label": _("Changes (Last 7 Days)"), "datatype": "Int", "color": "purple"},
        {
            "value": f"{most_active_changer[0]} ({most_active_changer[1]})",
            "label": _("Most Active Changer"),
            "datatype": "Data",
        },
    ]


def get_chart_data(data):
    """Get chart data for visualization"""
    if not data:
        return None

    # Group by change type
    change_types = {}
    for row in data:
        change_type = row.get("change_type", "Unknown")
        # Extract text from HTML
        if "Initial Assignment" in change_type:
            simple_type = "Initial Assignment"
        elif "Chapter Transfer" in change_type:
            simple_type = "Chapter Transfer"
        elif "Removed from Chapter" in change_type:
            simple_type = "Removed from Chapter"
        else:
            simple_type = "Other"

        change_types[simple_type] = change_types.get(simple_type, 0) + 1

    return {
        "data": {
            "labels": list(change_types.keys()),
            "datasets": [{"name": _("Chapter Changes"), "values": list(change_types.values())}],
        },
        "type": "donut",
        "colors": ["#28a745", "#007bf", "#dc3545", "#6c757d"],
    }


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
