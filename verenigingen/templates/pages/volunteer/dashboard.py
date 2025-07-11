import frappe
from frappe import _
from frappe.utils import add_months, flt, today

from verenigingen.utils.error_handling import cache_with_ttl, handle_api_error
from verenigingen.utils.performance_monitoring import monitor_performance
from verenigingen.utils.performance_utils import QueryOptimizer


def get_context(context):
    """Get context for volunteer dashboard page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the volunteer dashboard"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Volunteer Dashboard")

    # Get current user's volunteer record
    volunteer = get_user_volunteer_record()
    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        return context

    context.volunteer = volunteer

    # Get volunteer profile info
    context.volunteer_profile = get_volunteer_profile(volunteer.name)

    # Get volunteer's organizations
    context.organizations = get_volunteer_organizations(volunteer.name)

    # Get recent activities
    context.recent_activities = get_recent_activities(volunteer.name)

    # Get expense summary
    context.expense_summary = get_expense_summary(volunteer.name)

    # Get upcoming assignments/activities
    context.upcoming_activities = get_upcoming_activities(volunteer.name)

    return context


@cache_with_ttl(ttl=300)
@monitor_performance
def get_user_volunteer_record():
    """Get volunteer record for current user with caching"""
    user_email = frappe.session.user

    # First try to find by linked member
    member = frappe.db.get_value("Member", {"email": user_email}, "name")
    if member:
        volunteer = frappe.db.get_value(
            "Volunteer", {"member": member}, ["name", "volunteer_name", "member"], as_dict=True
        )
        if volunteer:
            return volunteer

    # Try to find volunteer directly by email
    volunteer = frappe.db.get_value(
        "Volunteer", {"email": user_email}, ["name", "volunteer_name", "member"], as_dict=True
    )
    if volunteer:
        return volunteer

    return None


def get_volunteer_profile(volunteer_name):
    """Get detailed volunteer profile information"""
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

    profile = {
        "name": volunteer_doc.name,
        "volunteer_name": volunteer_doc.volunteer_name,
        "status": getattr(volunteer_doc, "status", "Active"),
        "joined_date": getattr(volunteer_doc, "creation", None),
        "email": None,
        "phone": getattr(volunteer_doc, "phone", None),
        "member_info": None,
    }

    # Get email from member or volunteer record
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        member = frappe.get_doc("Member", volunteer_doc.member)
        profile["email"] = member.email
        profile["member_info"] = {
            "member_id": member.member_id,
            "full_name": member.full_name,
            "membership_status": getattr(member, "status", "Active"),
        }
    else:
        profile["email"] = getattr(volunteer_doc, "email", None)

    # Get interests
    profile["interests"] = frappe.get_all(
        "Volunteer Interest Area",
        filters={"parent": volunteer_name},
        fields=["interest_area"],
        order_by="interest_area",
    )

    # Get skills
    profile["skills"] = frappe.get_all(
        "Volunteer Skill",
        filters={"parent": volunteer_name},
        fields=["skill_category", "volunteer_skill", "proficiency_level"],
        order_by="skill_category, volunteer_skill",
    )

    return profile


@cache_with_ttl(ttl=600)
@monitor_performance
def get_volunteer_organizations(volunteer_name):
    """Get chapters and teams the volunteer belongs to with optimized queries"""
    organizations = {"chapters": [], "teams": []}

    # Get volunteer member info in one query
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        # Use single JOIN query for chapters
        chapter_data = frappe.db.sql(
            """
            SELECT c.name, c.chapter_name, cm.chapter_join_date
            FROM `tabChapter Member` cm
            JOIN `tabChapter` c ON cm.parent = c.name
            WHERE cm.member = %s AND cm.enabled = 1
            ORDER BY cm.chapter_join_date DESC
        """,
            [volunteer_doc.member],
            as_dict=True,
        )

        for chapter in chapter_data:
            organizations["chapters"].append(
                {
                    "name": chapter.name,
                    "chapter_name": chapter.chapter_name or chapter.name,
                    "join_date": chapter.chapter_join_date,
                }
            )

    # Use single JOIN query for teams
    team_data = frappe.db.sql(
        """
        SELECT t.name, t.team_name, tm.role_type, tm.from_date
        FROM `tabTeam Member` tm
        JOIN `tabTeam` t ON tm.parent = t.name
        WHERE tm.volunteer = %s AND tm.status = 'Active'
        ORDER BY tm.from_date DESC
    """,
        [volunteer_name],
        as_dict=True,
    )

    for team in team_data:
        organizations["teams"].append(
            {
                "name": team.name,
                "team_name": team.team_name or team.name,
                "role": team.role_type,
                "joined_date": team.from_date,
            }
        )

    return organizations


def get_recent_activities(volunteer_name):
    """Get recent volunteer activities"""
    activities = []

    # Get recent assignments
    assignments = frappe.get_all(
        "Volunteer Assignment",
        filters={"parent": volunteer_name},
        fields=["name", "start_date", "assignment_type", "role", "status"],
        order_by="start_date desc",
        limit=5,
    )

    for assignment in assignments:
        activities.append(
            {
                "type": "assignment",
                "title": assignment.assignment_type,
                "description": assignment.role,
                "date": assignment.start_date,
                "status": assignment.status,
                "icon": "fa-tasks",
            }
        )

    # Get recent expenses
    expenses = frappe.get_all(
        "Volunteer Expense",
        filters={"volunteer": volunteer_name, "docstatus": ["!=", 2]},
        fields=["name", "expense_date", "description", "amount", "status"],
        order_by="expense_date desc",
        limit=3,
    )

    for expense in expenses:
        activities.append(
            {
                "type": "expense",
                "title": f"Expense: €{expense.amount:.2f}",
                "description": expense.description,
                "date": expense.expense_date,
                "status": expense.status,
                "icon": "fa-receipt",
            }
        )

    # Sort all activities by date
    activities.sort(key=lambda x: x["date"] if x["date"] else today(), reverse=True)

    return activities[:8]  # Return most recent 8 activities


@cache_with_ttl(ttl=300)
@monitor_performance
def get_expense_summary(volunteer_name):
    """Get expense summary for the volunteer with optimized aggregation"""
    from_date = add_months(today(), -12)
    recent_date = add_months(today(), -1)

    # Use SQL aggregation for better performance
    summary_data = frappe.db.sql(
        """
        SELECT
            SUM(CASE WHEN status IN ('Submitted', 'Approved') THEN amount ELSE 0 END) as total_submitted,
            SUM(CASE WHEN status = 'Approved' THEN amount ELSE 0 END) as total_approved,
            COUNT(CASE WHEN status = 'Submitted' THEN 1 END) as pending_count,
            COUNT(CASE WHEN expense_date >= %s THEN 1 END) as recent_count
        FROM `tabVolunteer Expense`
        WHERE volunteer = %s
        AND expense_date >= %s
        AND docstatus != 2
    """,
        [recent_date, volunteer_name, from_date],
        as_dict=True,
    )

    if summary_data:
        summary = summary_data[0]
        summary["pending_amount"] = flt(summary["total_approved"]) - flt(summary["total_submitted"])
        # Convert decimals to float for JSON serialization
        for key in ["total_submitted", "total_approved"]:
            summary[key] = flt(summary[key])
        return summary

    return {
        "total_submitted": 0,
        "total_approved": 0,
        "pending_count": 0,
        "recent_count": 0,
        "pending_amount": 0,
    }


def get_upcoming_activities(volunteer_name):
    """Get upcoming activities and assignments"""
    upcoming = []

    # Get future assignments
    future_assignments = frappe.get_all(
        "Volunteer Assignment",
        filters={"parent": volunteer_name, "start_date": [">", today()], "status": ["in", ["Active"]]},
        fields=["name", "start_date", "assignment_type", "role"],
        order_by="start_date asc",
        limit=5,
    )

    for assignment in future_assignments:
        upcoming.append(
            {
                "title": assignment.assignment_type,
                "description": assignment.role,
                "date": assignment.start_date,
                "type": "assignment",
            }
        )

    return upcoming
