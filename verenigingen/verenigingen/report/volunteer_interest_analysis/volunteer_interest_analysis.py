# verenigingen/verenigingen/report/volunteer_interest_analysis/volunteer_interest_analysis.py

import frappe
from frappe import _


def execute(filters=None):
    """Generate Volunteer Interest Analysis Report"""

    columns = get_columns()
    data = get_data(filters)

    # Add summary
    summary = get_volunteer_summary(data)

    # Add charts
    chart = get_interest_distribution_chart(data)

    return columns, data, None, chart, summary


def get_columns():
    """Define report columns"""
    return [
        {
            "label": _("Member ID"),
            "fieldname": "name",
            "fieldtype": "Link",
            "options": "Member",
            "width": 120,
        },
        {"label": _("Name"), "fieldname": "full_name", "fieldtype": "Data", "width": 150},
        {"label": _("Email"), "fieldname": "email", "fieldtype": "Data", "width": 150},
        {
            "label": _("Chapter"),
            "fieldname": "primary_chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 120,
        },
        {"label": _("Member Since"), "fieldname": "member_since", "fieldtype": "Date", "width": 100},
        {
            "label": _("Availability"),
            "fieldname": "volunteer_availability",
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "label": _("Experience Level"),
            "fieldname": "volunteer_experience_level",
            "fieldtype": "Data",
            "width": 120,
        },
        {"label": _("Interest Areas"), "fieldname": "interest_areas", "fieldtype": "HTML", "width": 200},
        {"label": _("Skills"), "fieldname": "skills", "fieldtype": "HTML", "width": 200},
        {"label": _("Volunteer Status"), "fieldname": "volunteer_status", "fieldtype": "Data", "width": 100},
        {"label": _("Total Hours"), "fieldname": "total_hours", "fieldtype": "Float", "width": 90},
    ]


def get_data(filters):
    """Get volunteer interest data"""

    conditions = ["m.interested_in_volunteering = 1"]

    # Apply filters
    if filters:
        # Chapter filtering will be done post-query

        if filters.get("availability"):
            conditions.append("m.volunteer_availability = %(availability)s")

        if filters.get("experience_level"):
            conditions.append("m.volunteer_experience_level = %(experience_level)s")

        if filters.get("has_volunteer_record"):
            conditions.append("v.name IS NOT NULL")

        if filters.get("active_only"):
            conditions.append("m.status = 'Active'")

    " AND ".join(conditions)

    # Main query
    data = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            m.email,
            m.member_since,
            m.volunteer_availability,
            m.volunteer_experience_level,
            v.name as volunteer_id,
            v.status as volunteer_status
        FROM `tabMember` m
        LEFT JOIN `tabVolunteer` v ON v.member = m.name
        WHERE {where_clause}
        ORDER BY m.member_since DESC
    """,
        filters,
        as_dict=True,
    )

    # Get interest areas and skills for each member
    processed_data = []
    for row in data:
        # Get member chapters
        member_chapters = get_member_chapters(row.name)
        row["chapter"] = member_chapters[0] if member_chapters else "Unassigned"

        # Apply chapter filter if specified
        if filters and filters.get("chapter"):
            if filters.get("chapter") not in member_chapters:
                continue  # Skip this row
        # Get interest areas
        interests = frappe.get_all(
            "Member Volunteer Interest",
            filters={"parent": row.name},
            fields=["interest_area", "experience_level"],
            order_by="idx",
        )

        if interests:
            interest_html = "<small><ul style='margin:0;padding-left:15px;'>"
            for interest in interests[:5]:  # Limit to 5
                level = f" ({interest.experience_level})" if interest.experience_level else ""
                interest_html += f"<li>{interest.interest_area}{level}</li>"
            if len(interests) > 5:
                interest_html += f"<li><em>+{len(interests) - 5} more...</em></li>"
            interest_html += "</ul></small>"
            row["interest_areas"] = interest_html
        else:
            row["interest_areas"] = "<small><em>Not specified</em></small>"

        # Get skills
        skills = frappe.get_all(
            "Member Volunteer Skill",
            filters={"parent": row.name},
            fields=["skill_name", "proficiency_level"],
            order_by="idx",
        )

        if skills:
            skill_html = "<small><ul style='margin:0;padding-left:15px;'>"
            for skill in skills[:5]:  # Limit to 5
                level = f" - {skill.proficiency_level}" if skill.proficiency_level else ""
                skill_html += f"<li>{skill.skill_name}{level}</li>"
            if len(skills) > 5:
                skill_html += f"<li><em>+{len(skills) - 5} more...</em></li>"
            skill_html += "</ul></small>"
            row["skills"] = skill_html
        else:
            row["skills"] = "<small><em>Not specified</em></small>"

        # Get volunteer hours if volunteer record exists
        if row.volunteer_id:
            hours = frappe.db.sql(
                """
                SELECT SUM(hours) as total
                FROM `tabVolunteer Assignment`
                WHERE parent = %s AND status = 'Completed'
            """,
                row.volunteer_id,
            )[0][0]
            row["total_hours"] = hours or 0
        else:
            row["total_hours"] = 0
            row["volunteer_status"] = "No Record"

        # Add processed row to results
        processed_data.append(row)

    return processed_data


def get_volunteer_summary(data):
    """Get summary statistics"""
    if not data:
        return []

    total_interested = len(data)
    with_volunteer_record = len([d for d in data if d.get("volunteer_id")])
    active_volunteers = len([d for d in data if d.get("volunteer_status") == "Active"])
    total_hours = sum(d.get("total_hours", 0) for d in data)

    # Count by availability
    availability_counts = {}
    for row in data:
        avail = row.get("volunteer_availability") or "Not Specified"
        availability_counts[avail] = availability_counts.get(avail, 0) + 1

    # Most common availability
    most_common_avail = (
        max(availability_counts.items(), key=lambda x: x[1])[0] if availability_counts else "N/A"
    )

    return [
        {"value": total_interested, "label": _("Total Interested"), "datatype": "Int"},
        {"value": with_volunteer_record, "label": _("Volunteer Records Created"), "datatype": "Int"},
        {
            "value": active_volunteers,
            "label": _("Active Volunteers"),
            "datatype": "Int",
            "color": "green" if active_volunteers > 0 else "red",
        },
        {
            "value": f"{(with_volunteer_record / total_interested * 100):.1f}%"
            if total_interested > 0
            else "0%",
            "label": _("Activation Rate"),
            "datatype": "Data",
        },
        {"value": total_hours, "label": _("Total Volunteer Hours"), "datatype": "Float"},
        {"value": most_common_avail, "label": _("Most Common Availability"), "datatype": "Data"},
    ]


def get_interest_distribution_chart(data):
    """Get chart showing distribution of volunteer interests"""
    if not data:
        return None

    # Count interests across all volunteers
    interest_counts = {}
    skill_categories = {}

    for row in data:
        # Get interest areas for counting
        interests = frappe.get_all(
            "Member Volunteer Interest", filters={"parent": row.name}, fields=["interest_area"]
        )

        for interest in interests:
            area = interest.interest_area
            interest_counts[area] = interest_counts.get(area, 0) + 1

        # Count skill categories
        skills = frappe.get_all(
            "Volunteer Skill",
            filters={"parent": row.get("volunteer_id")} if row.get("volunteer_id") else {"parent": ""},
            fields=["skill_category"],
        )

        for skill in skills:
            cat = skill.skill_category or "Other"
            skill_categories[cat] = skill_categories.get(cat, 0) + 1

    # Get top 10 interest areas
    top_interests = sorted(interest_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    if not top_interests:
        return None

    return {
        "data": {
            "labels": [item[0] for item in top_interests],
            "datasets": [
                {"name": _("Volunteer Interest Areas"), "values": [item[1] for item in top_interests]}
            ],
        },
        "type": "bar",
        "colors": ["#7cd6fd"],
        "height": 300,
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
