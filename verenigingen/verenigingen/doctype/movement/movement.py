# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url_to_form, getdate, today


class Movement(Document):
    def validate(self):
        """Validation and auto-updates"""
        self.update_member_count()

    def on_update(self):
        """Update display fields after save"""
        self.update_tag_discovery()
        self.update_activity_summary()

    def update_member_count(self):
        """Update member statistics HTML"""
        if not self.members:
            self.member_count_html = "<p style='color: #999;'>No members yet</p>"
            return

        active_count = sum(1 for m in self.members if m.status == "Active")
        total_count = len(self.members)

        # Get chapter distribution
        chapter_counts = {}
        for member in self.members:
            if member.status != "Active":
                continue
            volunteer = frappe.get_cached_doc("Volunteer", member.volunteer)
            if volunteer.member:
                # Get member's chapters - Chapter Member is a child table of Chapter
                # So we need to find Chapter records that have this member
                chapters = frappe.db.sql(
                    """
                    SELECT c.name
                    FROM `tabChapter` c
                    INNER JOIN `tabChapter Member` cm ON cm.parent = c.name
                    WHERE cm.member = %s AND cm.enabled = 1
                    """,
                    volunteer.member,
                    as_dict=1,
                )
                for ch in chapters:
                    chapter_counts[ch.name] = chapter_counts.get(ch.name, 0) + 1

        html = f"""
        <div style='padding: 10px; background: #f8f9fa; border-radius: 4px;'>
            <p style='margin: 0 0 10px 0;'>
                <strong>{active_count}</strong> active member{'s' if active_count != 1 else ''}
                {f'({total_count - active_count} inactive)' if total_count > active_count else ''}
            </p>
        """

        if chapter_counts:
            html += "<p style='margin: 0; font-size: 0.9em; color: #666;'><strong>Chapter Distribution:</strong><br/>"
            for chapter, count in sorted(chapter_counts.items(), key=lambda x: x[1], reverse=True):
                html += f"• {chapter}: {count}<br/>"
            html += "</p>"

        html += "</div>"
        self.member_count_html = html

    def update_tag_discovery(self):
        """Show volunteers using related tags who aren't members"""
        if not self.related_tags:
            self.tag_discovery_info = "<p style='color: #999;'>Add tags to enable discovery</p>"
            return

        tag_names = [t.tag for t in self.related_tags]
        member_volunteers = [m.volunteer for m in self.members]

        # Find activities with these tags
        discovered = frappe.db.sql(
            """
            SELECT DISTINCT
                va.volunteer,
                v.volunteer_name,
                COUNT(DISTINCT va.name) as activity_count
            FROM `tabVolunteer Activity` va
            INNER JOIN `tabVolunteer Activity Tag` vat ON vat.parent = va.name
            INNER JOIN `tabVolunteer` v ON v.name = va.volunteer
            WHERE vat.tag IN %(tags)s
                AND va.status IN ('Active', 'Completed')
                AND va.volunteer NOT IN %(members)s
            GROUP BY va.volunteer
            ORDER BY activity_count DESC
            LIMIT 10
        """,
            {"tags": tag_names, "members": member_volunteers or ["__none__"]},
            as_dict=1,
        )

        if not discovered:
            self.tag_discovery_info = (
                "<p style='color: #999;'>No additional volunteers found using these tags</p>"
            )
            return

        html = f"""
        <div style='padding: 10px; background: #fff3cd; border-left: 3px solid #ffc107; border-radius: 4px;'>
            <p style='margin: 0 0 10px 0;'><strong>💡 Discovered Volunteers</strong></p>
            <p style='margin: 0 0 10px 0; font-size: 0.9em;'>
                {len(discovered)} volunteer{'s' if len(discovered) != 1 else ''} using related tags (not members yet):
            </p>
            <ul style='margin: 0; padding-left: 20px; font-size: 0.9em;'>
        """

        for vol in discovered[:5]:
            url = get_url_to_form("Volunteer", vol.volunteer)
            html += f"""
                <li>
                    <a href='{url}' target='_blank'>{vol.volunteer_name}</a>
                    ({vol.activity_count} activit{'ies' if vol.activity_count > 1 else 'y'})
                </li>
            """

        if len(discovered) > 5:
            html += f"<li style='color: #666;'>...and {len(discovered) - 5} more</li>"

        html += """
            </ul>
            <p style='margin: 10px 0 0 0; font-size: 0.85em; color: #666;'>
                Consider inviting them to join this movement
            </p>
        </div>
        """

        self.tag_discovery_info = html

    def update_activity_summary(self):
        """Show activity metrics for this movement"""

        # Get activities linked to this movement
        direct_activities = frappe.get_all(
            "Volunteer Activity", filters={"movement": self.name}, fields=["status", "actual_hours"]
        )

        # Get activities with related tags
        tag_names = [t.tag for t in self.related_tags] if self.related_tags else []
        tagged_activities = []

        if tag_names:
            tagged_activities = frappe.db.sql(
                """
                SELECT DISTINCT
                    va.status,
                    va.actual_hours
                FROM `tabVolunteer Activity` va
                INNER JOIN `tabVolunteer Activity Tag` vat ON vat.parent = va.name
                WHERE vat.tag IN %(tags)s
                    AND (va.movement IS NULL OR va.movement != %(movement)s)
            """,
                {"tags": tag_names, "movement": self.name},
                as_dict=1,
            )

        all_activities = direct_activities + tagged_activities

        if not all_activities:
            self.activity_summary_html = "<p style='color: #999;'>No activities yet</p>"
            return

        active_count = sum(1 for a in all_activities if a.status == "Active")
        completed_count = sum(1 for a in all_activities if a.status == "Completed")
        total_hours = sum(a.actual_hours or 0 for a in all_activities)

        html = f"""
        <div style='padding: 10px; background: #f8f9fa; border-radius: 4px;'>
            <div style='display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 10px;'>
                <div>
                    <div style='font-size: 24px; font-weight: bold; color: #51cf66;'>{active_count}</div>
                    <div style='font-size: 0.85em; color: #666;'>Active Activities</div>
                </div>
                <div>
                    <div style='font-size: 24px; font-weight: bold; color: #868e96;'>{completed_count}</div>
                    <div style='font-size: 0.85em; color: #666;'>Completed</div>
                </div>
                <div>
                    <div style='font-size: 24px; font-weight: bold; color: #5e64ff;'>{total_hours:.0f}</div>
                    <div style='font-size: 0.85em; color: #666;'>Total Hours</div>
                </div>
            </div>
            <p style='margin: 10px 0 0 0; font-size: 0.85em; color: #666;'>
                {len(direct_activities)} directly linked |
                {len(tagged_activities)} discovered via tags
            </p>
        </div>
        """

        self.activity_summary_html = html

    @frappe.whitelist()
    def suggest_potential_members(self):
        """API method to get suggested members based on tags"""
        if not self.related_tags:
            return []

        tag_names = [t.tag for t in self.related_tags]
        member_volunteers = [m.volunteer for m in self.members]

        suggestions = frappe.db.sql(
            """
            SELECT
                va.volunteer,
                v.volunteer_name,
                v.email,
                COUNT(DISTINCT va.name) as activity_count,
                GROUP_CONCAT(DISTINCT vat.tag SEPARATOR ', ') as matching_tags
            FROM `tabVolunteer Activity` va
            INNER JOIN `tabVolunteer Activity Tag` vat ON vat.parent = va.name
            INNER JOIN `tabVolunteer` v ON v.name = va.volunteer
            WHERE vat.tag IN %(tags)s
                AND va.status IN ('Active', 'Completed')
                AND va.volunteer NOT IN %(members)s
            GROUP BY va.volunteer
            HAVING activity_count >= 2
            ORDER BY activity_count DESC
        """,
            {"tags": tag_names, "members": member_volunteers or ["__none__"]},
            as_dict=1,
        )

        return suggestions
