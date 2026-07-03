"""Skill aggregation queries for the Volunteer skills endpoints.

Extracted from ``verenigingen/doctype/volunteer/volunteer.py`` to keep the
controller focused on document behaviour (Controller Growth Prevention Policy).
The whitelisted ``get_all_skills_list`` endpoint in the controller delegates
here; keeping the endpoint there preserves its public frappe.call path.
"""

import frappe
from frappe.query_builder import DocType

from verenigingen.utils.error_handling import cache_with_ttl


@cache_with_ttl(ttl=3600)  # Cache for 1 hour - skills change infrequently
def get_all_skills_list_cached():
    """Get all skills using modern Query Builder for better type safety"""
    from frappe.query_builder.functions import Avg, Cast, Count
    from pypika.terms import Function

    # Define DocTypes for Query Builder
    VolunteerSkill = DocType("Volunteer Skill")
    Volunteer = DocType("Volunteer")

    try:
        # Modern Query Builder approach for better maintainability
        # NOTE: pypika Field has no .left() helper; use a SQL LEFT(field, 1)
        # function to extract the leading proficiency digit (mirrors the raw-SQL
        # fallback's LEFT(proficiency_level, 1)).
        query = (
            frappe.qb.from_(VolunteerSkill)
            .inner_join(Volunteer)
            .on(VolunteerSkill.parent == Volunteer.name)
            .select(
                VolunteerSkill.volunteer_skill,
                VolunteerSkill.skill_category,
                Count("*").as_("volunteer_count"),
                Avg(Cast(Function("LEFT", VolunteerSkill.proficiency_level, 1), "UNSIGNED")).as_("avg_level"),
            )
            .where(
                (VolunteerSkill.volunteer_skill.isnotnull())
                & (VolunteerSkill.volunteer_skill != "")
                & (Volunteer.status == "Active")
            )
            .groupby(VolunteerSkill.volunteer_skill, VolunteerSkill.skill_category)
            .orderby(Count("*"), order=frappe.qb.desc)
            .orderby(VolunteerSkill.volunteer_skill)
            .distinct()
        )

        skills = query.run(as_dict=True)
        return skills

    except Exception as e:
        # Fallback to original SQL if Query Builder fails
        frappe.log_error(f"Query Builder failed for skills query: {str(e)}")

        skills = frappe.db.sql(
            """
            SELECT DISTINCT
                volunteer_skill,
                skill_category,
                COUNT(*) as volunteer_count,
                AVG(CAST(LEFT(proficiency_level, 1) AS UNSIGNED)) as avg_level
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
                AND v.status = 'Active'
            GROUP BY volunteer_skill, skill_category
            ORDER BY volunteer_count DESC, volunteer_skill
        """,
            as_dict=True,
        )

        return skills
