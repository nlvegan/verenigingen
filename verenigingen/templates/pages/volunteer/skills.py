import frappe
from frappe import _

from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters
from verenigingen.utils.member_utils import require_login


def get_context(context):
    """Get context for volunteer skills browse page - restricted to chapter board members"""
    require_login()

    # skills.html renders the header logo; every other page exposes it as organization_logo
    from verenigingen.verenigingen.doctype.brand_settings.brand_settings import get_organization_logo

    context["organization_logo"] = get_organization_logo()
    context["no_cache"] = 1
    context["show_sidebar"] = True
    context["title"] = _("Skills Directory")

    # Get user's board chapters using the same logic as chapter_dashboard
    user_chapters = get_user_board_chapters()

    if not user_chapters:
        error_msg = _(
            "You must be a chapter board member to access the skills directory. Please contact your chapter administrator."
        )
        context["error_message"] = error_msg
        context["no_access"] = True
        return context

    # Get member IDs from user's chapters
    chapter_names = [ch.get("chapter_name") for ch in user_chapters]
    chapter_member_ids = get_chapter_member_ids(chapter_names)

    context["user_chapters"] = user_chapters
    context["chapter_member_ids"] = chapter_member_ids
    context["no_access"] = False

    # Get all skills grouped by category (filtered by chapter members)
    context["skills_by_category"] = get_skills_grouped_by_category(chapter_member_ids)

    # Get summary statistics (filtered by chapter members)
    context["skills_stats"] = get_skills_statistics(chapter_member_ids)

    # Handle search if requested
    search_skill = frappe.form_dict.get("skill", "")
    search_category = frappe.form_dict.get("category", "")
    min_level = frappe.form_dict.get("min_level", "")

    context["search_results"] = None
    context["search_params"] = {"skill": search_skill, "category": search_category, "min_level": min_level}

    # Perform search if any parameters provided
    if search_skill or search_category or min_level:
        try:
            # Search only within chapter members
            context["search_results"] = search_volunteers_by_skill_filtered(
                skill_name=search_skill or "",
                category=search_category if search_category else None,
                min_level=int(min_level) if min_level.isdigit() else None,
                member_ids=chapter_member_ids,
            )
        except Exception as e:
            frappe.log_error(f"Error in skills search: {str(e)}")
            context["search_error"] = _("An error occurred while searching. Please try again.")

    return context


def get_chapter_member_ids(chapter_names):
    """Get all member IDs from the specified chapters"""
    if not chapter_names:
        return []

    members = frappe.db.sql(
        """
        SELECT DISTINCT cm.member
        FROM `tabChapter Member` cm
        WHERE cm.parent IN %(chapters)s
        AND cm.enabled = 1
    """,
        {"chapters": chapter_names},
        as_list=True,
    )

    return [m[0] for m in members]


def search_volunteers_by_skill_filtered(skill_name="", category="", min_level=None, member_ids=None):
    """Search volunteers by skill - filtered by chapter members"""
    if not member_ids:
        return []

    # Build query conditions
    conditions = ["v.member IN %(member_ids)s", "v.status IN ('Active', 'New')"]
    params = {"member_ids": member_ids}

    if skill_name:
        conditions.append("vs.volunteer_skill LIKE %(skill_pattern)s")
        params["skill_pattern"] = f"%{skill_name}%"

    if category:
        conditions.append("vs.skill_category = %(category)s")
        params["category"] = category

    if min_level:
        conditions.append("CAST(LEFT(COALESCE(vs.proficiency_level, '1'), 1) AS UNSIGNED) >= %(min_level)s")
        params["min_level"] = min_level

    where_clause = " AND ".join(conditions)

    results = frappe.db.sql(
        f"""
        SELECT
            v.name as volunteer_id,
            v.volunteer_name,
            vs.volunteer_skill,
            vs.skill_category,
            vs.proficiency_level
        FROM `tabVolunteer` v
        INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name
        WHERE {where_clause}
        ORDER BY v.volunteer_name, vs.volunteer_skill
    """,
        params,
        as_dict=True,
    )

    return results


def get_skills_grouped_by_category(member_ids=None):
    """Get all skills grouped by category with volunteer counts - filtered by chapter members"""
    if not member_ids:
        return {}

    try:
        skills = frappe.db.sql(
            """
            SELECT
                COALESCE(vs.skill_category, 'Other') as skill_category,
                vs.volunteer_skill,
                COUNT(*) as volunteer_count,
                AVG(CAST(LEFT(COALESCE(vs.proficiency_level, '1'), 1) AS UNSIGNED)) as avg_level,
                GROUP_CONCAT(DISTINCT v.volunteer_name ORDER BY v.volunteer_name SEPARATOR ', ') as volunteer_names
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status IN ('Active', 'New')
                AND v.member IN %(member_ids)s
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
                AND TRIM(vs.volunteer_skill) != ''
            GROUP BY COALESCE(vs.skill_category, 'Other'), vs.volunteer_skill
            ORDER BY skill_category, volunteer_count DESC, vs.volunteer_skill
        """,
            {"member_ids": member_ids},
            as_dict=True,
        )

        # Group by category
        grouped = {}
        for skill in skills:
            category = skill.skill_category or "Other"
            if category not in grouped:
                grouped[category] = []

            # Truncate volunteer names if too long
            volunteer_names = skill.volunteer_names or ""
            if len(volunteer_names) > 100:
                names_list = volunteer_names.split(", ")
                if len(names_list) > 3:
                    volunteer_names = ", ".join(names_list[:3]) + f" and {len(names_list) - 3} others"

            skill_data = {
                "skill_name": skill.volunteer_skill,
                "volunteer_count": skill.volunteer_count,
                "avg_level": round(skill.avg_level, 1) if skill.avg_level else 0,
                "volunteer_names": volunteer_names,
            }
            grouped[category].append(skill_data)

        return grouped

    except Exception as e:
        frappe.log_error(f"Error getting skills by category: {str(e)}")
        return {}


def get_skills_statistics(member_ids=None):
    """Get overall skills statistics - filtered by chapter members"""
    if not member_ids:
        return {
            "total_unique_skills": 0,
            "volunteers_with_skills": 0,
            "total_skill_entries": 0,
            "skill_categories": 0,
        }

    try:
        stats = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT vs.volunteer_skill) as total_unique_skills,
                COUNT(DISTINCT vs.parent) as volunteers_with_skills,
                COUNT(*) as total_skill_entries,
                COUNT(DISTINCT COALESCE(vs.skill_category, 'Other')) as skill_categories
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status IN ('Active', 'New')
                AND v.member IN %(member_ids)s
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
                AND TRIM(vs.volunteer_skill) != ''
        """,
            {"member_ids": member_ids},
            as_dict=True,
        )

        if stats:
            return stats[0]
        else:
            return {
                "total_unique_skills": 0,
                "volunteers_with_skills": 0,
                "total_skill_entries": 0,
                "skill_categories": 0,
            }

    except Exception as e:
        frappe.log_error(f"Error getting skills statistics: {str(e)}")
        return {
            "total_unique_skills": 0,
            "volunteers_with_skills": 0,
            "total_skill_entries": 0,
            "skill_categories": 0,
        }
