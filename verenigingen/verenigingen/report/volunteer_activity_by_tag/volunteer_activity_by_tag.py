# Copyright (c) 2025, Verenigingen and contributors
# License: GNU General Public License v3

import frappe
from frappe import _
from frappe.utils import get_url_to_form


def execute(filters=None):
    """
    Tag Ecosystem Report - Bottom-up discovery of volunteer activities

    Shows which volunteers are working on what topics, enabling organic
    collaboration discovery across chapters and the organization.
    """
    columns = get_columns()
    data = get_data(filters)
    chart = get_tag_distribution_chart(data) if data else None
    message = get_summary_message(data, filters)

    return columns, data, message, chart


def get_columns():
    """Define report columns"""
    return [
        {"label": _("Tag"), "fieldname": "tag", "fieldtype": "Link", "options": "Activity Tag", "width": 150},
        {
            "label": _("Volunteer"),
            "fieldname": "volunteer",
            "fieldtype": "Link",
            "options": "Volunteer",
            "width": 120,
        },
        {"label": _("Volunteer Name"), "fieldname": "volunteer_name", "fieldtype": "Data", "width": 150},
        {
            "label": _("Chapter"),
            "fieldname": "chapter",
            "fieldtype": "Link",
            "options": "Chapter",
            "width": 120,
        },
        {"label": _("Activity Type"), "fieldname": "activity_type", "fieldtype": "Data", "width": 120},
        {"label": _("Activity Scope"), "fieldname": "activity_scope", "fieldtype": "Data", "width": 100},
        {"label": _("Role"), "fieldname": "role", "fieldtype": "Data", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 80},
        {"label": _("Start Date"), "fieldname": "start_date", "fieldtype": "Date", "width": 100},
        {"label": _("Hours"), "fieldname": "actual_hours", "fieldtype": "Float", "width": 80},
        {
            "label": _("Activity"),
            "fieldname": "activity_name",
            "fieldtype": "Link",
            "options": "Volunteer Activity",
            "width": 100,
            "hidden": 1,
        },
    ]


def get_data(filters):
    """Get volunteer activities grouped by tags"""

    conditions = ["1=1"]

    if filters:
        if filters.get("tag"):
            conditions.append("vat.tag = %(tag)s")

        if filters.get("chapter"):
            conditions.append(
                """
                EXISTS (
                    SELECT 1 FROM `tabChapter Membership History` cmh
                    WHERE cmh.parent = v.member
                    AND cmh.chapter_name = %(chapter)s
                    AND cmh.status = 'Active'
                    AND cmh.end_date IS NULL
                )
            """
            )

        if filters.get("activity_type"):
            conditions.append("va.activity_type = %(activity_type)s")

        if filters.get("activity_scope"):
            conditions.append("va.activity_scope = %(activity_scope)s")

        if filters.get("status"):
            conditions.append("va.status = %(status)s")
        else:
            # Default to active if no status filter
            conditions.append("va.status IN ('Active', 'Completed')")

        if filters.get("from_date"):
            conditions.append("va.start_date >= %(from_date)s")

        if filters.get("to_date"):
            conditions.append("va.start_date <= %(to_date)s")

    where_clause = " AND ".join(conditions)

    data = frappe.db.sql(
        f"""
        SELECT
            vat.tag,
            va.volunteer,
            v.volunteer_name,
            (SELECT GROUP_CONCAT(DISTINCT cmh.chapter_name SEPARATOR ', ')
             FROM `tabChapter Membership History` cmh
             WHERE cmh.parent = v.member
             AND cmh.status = 'Active'
             AND cmh.end_date IS NULL
            ) as chapter,
            va.activity_type,
            va.activity_scope,
            va.role,
            va.status,
            va.start_date,
            va.actual_hours,
            va.name as activity_name
        FROM `tabVolunteer Activity` va
        INNER JOIN `tabVolunteer Activity Tag` vat ON vat.parent = va.name
        INNER JOIN `tabVolunteer` v ON v.name = va.volunteer
        WHERE {where_clause}
        GROUP BY va.name, vat.tag
        ORDER BY vat.tag, v.volunteer_name, va.start_date DESC
    """,
        filters,
        as_dict=1,
    )

    return data


def get_tag_distribution_chart(data):
    """Create chart showing activity distribution by tag"""

    # Count activities per tag
    tag_counts = {}
    for row in data:
        tag = row.get("tag")
        if tag:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort by count
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    if not sorted_tags:
        return None

    return {
        "data": {
            "labels": [tag[0] for tag in sorted_tags],
            "datasets": [{"name": _("Activities"), "values": [tag[1] for tag in sorted_tags]}],
        },
        "type": "bar",
        "colors": ["#7cd6fd"],
        "barOptions": {"stacked": 0},
    }


def get_summary_message(data, filters):
    """Generate summary statistics"""

    if not data:
        return _("No activities found matching the filters.")

    # Calculate statistics
    unique_tags = len(set(row.get("tag") for row in data if row.get("tag")))
    unique_volunteers = len(set(row.get("volunteer") for row in data if row.get("volunteer")))
    # Handle comma-separated chapters
    all_chapters = set()
    for row in data:
        if row.get("chapter"):
            for chapter in row.get("chapter", "").split(", "):
                if chapter.strip():
                    all_chapters.add(chapter.strip())
    unique_chapters = len(all_chapters)
    total_activities = len(data)
    total_hours = sum(row.get("actual_hours", 0) or 0 for row in data)

    # Find tags with high activity but no movement (for future enhancement)
    tag_activity_counts = {}
    for row in data:
        tag = row.get("tag")
        if tag:
            tag_activity_counts[tag] = tag_activity_counts.get(tag, 0) + 1

    high_activity_tags = [
        tag
        for tag, count in tag_activity_counts.items()
        if count >= 5  # 5+ activities might warrant a movement
    ]

    message = f"""
    <div style='padding: 10px; background: #f8f9fa; border-left: 3px solid #7cd6fd;'>
        <h4 style='margin-top: 0;'>Tag Ecosystem Summary</h4>
        <ul style='margin: 5px 0;'>
            <li><strong>{unique_tags}</strong> unique tags</li>
            <li><strong>{unique_volunteers}</strong> volunteers involved</li>
            <li><strong>{unique_chapters}</strong> chapters represented</li>
            <li><strong>{total_activities}</strong> activities tracked</li>
            <li><strong>{total_hours:.1f}</strong> total volunteer hours</li>
        </ul>
    """

    if high_activity_tags and not filters.get("tag"):
        message += f"""
        <p style='margin: 10px 0 5px 0; color: #666;'>
            <strong>High Activity Tags:</strong> {', '.join(high_activity_tags[:5])}
        </p>
        <p style='margin: 5px 0 0 0; font-size: 0.9em; color: #666;'>
            💡 These tags show significant activity and might warrant creating a Movement for coordination.
        </p>
        """

    message += "</div>"

    return message
