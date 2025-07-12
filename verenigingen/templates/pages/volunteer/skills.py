import frappe
from frappe import _


def get_context(context):
    """Get context for volunteer skills browse page"""

    # Require login for this page (optional - you can remove this for public access)
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the skills directory"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Skills Directory")

    # Get all skills grouped by category
    context.skills_by_category = get_skills_grouped_by_category()

    # Get summary statistics
    context.skills_stats = get_skills_statistics()

    # Handle search if requested
    search_skill = frappe.form_dict.get("skill", "")
    search_category = frappe.form_dict.get("category", "")
    min_level = frappe.form_dict.get("min_level", "")

    context.search_results = None
    context.search_params = {"skill": search_skill, "category": search_category, "min_level": min_level}

    # Perform search if any parameters provided
    if search_skill or search_category or min_level:
        try:
            # Use the search function from volunteer.py
            from verenigingen.verenigingen.doctype.volunteer.volunteer import search_volunteers_by_skill

            context.search_results = search_volunteers_by_skill(
                skill_name=search_skill or "",
                category=search_category if search_category else None,
                min_level=int(min_level) if min_level.isdigit() else None,
            )
        except Exception as e:
            frappe.log_error(f"Error in skills search: {str(e)}")
            context.search_error = _("An error occurred while searching. Please try again.")

    return context


def get_skills_grouped_by_category():
    """Get all skills grouped by category with volunteer counts"""
    try:
        skills = frappe.db.sql(
            """
            SELECT
                vs.skill_category,
                vs.volunteer_skill,
                COUNT(*) as volunteer_count,
                AVG(CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED)) as avg_level,
                GROUP_CONCAT(DISTINCT v.volunteer_name ORDER BY v.volunteer_name SEPARATOR ', ') as volunteer_names
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
            GROUP BY vs.skill_category, vs.volunteer_skill
            ORDER BY vs.skill_category, volunteer_count DESC, vs.volunteer_skill
        """,
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


def get_skills_statistics():
    """Get overall skills statistics"""
    try:
        stats = frappe.db.sql(
            """
            SELECT
                COUNT(DISTINCT vs.volunteer_skill) as total_unique_skills,
                COUNT(DISTINCT vs.parent) as volunteers_with_skills,
                COUNT(*) as total_skill_entries,
                COUNT(DISTINCT vs.skill_category) as skill_categories
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
        """,
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


@frappe.whitelist()
def search_skills(skill_name="", category="", min_level=""):
    """API endpoint for skills search (can be called via AJAX)"""
    from verenigingen.verenigingen.doctype.volunteer.volunteer import search_volunteers_by_skill

    try:
        results = search_volunteers_by_skill(
            skill_name=skill_name,
            category=category if category else None,
            min_level=int(min_level) if min_level.isdigit() else None,
        )
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        frappe.log_error(f"Error in skills search API: {str(e)}")
        return {"success": False, "error": str(e), "results": [], "count": 0}
