"""
API endpoints for volunteer skills management and search
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_skills_overview():
    """Get comprehensive skills overview for dashboards and reports"""
    try:
        # Get skills by category with counts
        skills_by_category = frappe.db.sql(
            """
            SELECT
                vs.skill_category,
                COUNT(DISTINCT vs.volunteer_skill) as unique_skills,
                COUNT(DISTINCT vs.parent) as volunteer_count,
                AVG(CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED)) as avg_proficiency,
                GROUP_CONCAT(DISTINCT vs.volunteer_skill ORDER BY vs.volunteer_skill) as skills_list
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
            GROUP BY vs.skill_category
            ORDER BY volunteer_count DESC
        """,
            as_dict=True,
        )

        # Get top skills across all categories
        top_skills = frappe.db.sql(
            """
            SELECT
                vs.volunteer_skill,
                vs.skill_category,
                COUNT(*) as volunteer_count,
                AVG(CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED)) as avg_level
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
            GROUP BY vs.volunteer_skill, vs.skill_category
            ORDER BY volunteer_count DESC, avg_level DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get skills in development
        development_skills = frappe.db.sql(
            """
            SELECT
                vdg.skill,
                COUNT(*) as learner_count,
                AVG(CAST(vdg.current_level AS UNSIGNED)) as avg_current_level,
                AVG(CAST(vdg.target_level AS UNSIGNED)) as avg_target_level
            FROM `tabVolunteer Development Goal` vdg
            INNER JOIN `tabVolunteer` v ON vdg.parent = v.name
            WHERE v.status = 'Active'
                AND vdg.skill IS NOT NULL
                AND vdg.skill != ''
            GROUP BY vdg.skill
            ORDER BY learner_count DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "skills_by_category": skills_by_category,
            "top_skills": top_skills,
            "development_skills": development_skills,
        }

    except Exception as e:
        frappe.log_error(f"Error getting skills overview: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "skills_by_category": [],
            "top_skills": [],
            "development_skills": [],
        }


@frappe.whitelist()
def search_volunteers_advanced(filters=None):
    """Advanced volunteer search with multiple skill filters

    Args:
        filters: JSON string with search criteria:
        {
            'skills': ['Python', 'Leadership'],  # Must have ALL these skills
            'categories': ['Technical', 'Leadership'],  # Skills in ANY of these categories
            'min_level': 3,  # Minimum proficiency level
            'max_results': 50,
            'include_contact': False  # Include email/phone in results
        }
    """
    import json

    try:
        if isinstance(filters, str):
            filters = json.loads(filters)
        if not filters:
            filters = {}

        skills = filters.get("skills", [])
        categories = filters.get("categories", [])
        min_level = filters.get("min_level")
        max_results = filters.get("max_results", 50)
        include_contact = filters.get("include_contact", False)

        conditions = ["v.status = 'Active'"]
        params = {"max_results": max_results}

        # Build the query based on filters
        joins = []

        if skills or categories or min_level:
            joins.append("INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name")

            skill_conditions = []

            if skills:
                # For multiple skills, we need to ensure volunteer has ALL specified skills
                skill_placeholders = []
                for i, skill in enumerate(skills):
                    param_name = f"skill_{i}"
                    skill_placeholders.append(f"%({param_name})s")
                    params[param_name] = skill
                skill_conditions.append(f"vs.volunteer_skill IN ({', '.join(skill_placeholders)})")

            if categories:
                cat_placeholders = []
                for i, cat in enumerate(categories):
                    param_name = f"cat_{i}"
                    cat_placeholders.append(f"%({param_name})s")
                    params[param_name] = cat
                skill_conditions.append(f"vs.skill_category IN ({', '.join(cat_placeholders)})")

            if min_level:
                skill_conditions.append("CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) >= %(min_level)s")
                params["min_level"] = min_level

            if skill_conditions:
                conditions.extend(skill_conditions)

        # Select fields based on privacy settings
        select_fields = ["DISTINCT v.name", "v.volunteer_name", "v.status"]

        if include_contact:
            select_fields.extend(["v.email", "v.phone"])

        # Add skills summary
        if joins:
            select_fields.append(
                """
                GROUP_CONCAT(DISTINCT CONCAT(vs.volunteer_skill, ' (', vs.proficiency_level, ')')
                    ORDER BY vs.skill_category, vs.volunteer_skill SEPARATOR ', ') as skills_summary
            """
            )

        join_clause = " ".join(joins)
        where_clause = " AND ".join(conditions)

        # Special handling for multiple required skills
        if len(skills) > 1:
            # Create named parameters for skills
            skill_placeholders = []
            for i, skill in enumerate(skills):
                param_name = f"multi_skill_{i}"
                skill_placeholders.append(f"%({param_name})s")
                params[param_name] = skill

            # Use HAVING clause to ensure volunteer has ALL required skills
            query = f"""
                SELECT {', '.join(select_fields)}
                FROM `tabVolunteer` v
                {join_clause}
                WHERE {where_clause}
                GROUP BY v.name
                HAVING COUNT(DISTINCT CASE WHEN vs.volunteer_skill IN ({', '.join(skill_placeholders)}) THEN vs.volunteer_skill END) = %(skill_count)s
                ORDER BY v.volunteer_name
                LIMIT %(max_results)s
            """
            params["skill_count"] = len(skills)
        else:
            query = f"""
                SELECT {', '.join(select_fields)}
                FROM `tabVolunteer` v
                {join_clause}
                WHERE {where_clause}
                GROUP BY v.name
                ORDER BY v.volunteer_name
                LIMIT %(max_results)s
            """

        volunteers = frappe.db.sql(query, params, as_dict=True)

        return {
            "success": True,
            "volunteers": volunteers,
            "count": len(volunteers),
            "filters_applied": filters,
        }

    except Exception as e:
        frappe.log_error(f"Error in advanced volunteer search: {str(e)}")
        return {"success": False, "error": str(e), "volunteers": [], "count": 0}


@frappe.whitelist()
def get_skill_recommendations(volunteer_name, limit=10):
    """Get skill recommendations for a volunteer based on similar volunteers

    Args:
        volunteer_name: Name of the volunteer
        limit: Maximum number of recommendations
    """
    try:
        # Get current volunteer's skills
        current_skills = frappe.get_all(
            "Volunteer Skill",
            filters={"parent": volunteer_name},
            fields=["volunteer_skill", "skill_category"],
        )

        if not current_skills:
            return {
                "success": True,
                "recommendations": [],
                "message": "No current skills found to base recommendations on",
            }

        current_skill_names = [s.volunteer_skill for s in current_skills]
        current_categories = list(set([s.skill_category for s in current_skills]))

        # Find volunteers with similar skills
        similar_volunteers = frappe.db.sql(
            """
            SELECT DISTINCT vs.parent as volunteer_name
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IN %(current_skills)s
                AND vs.parent != %(volunteer_name)s
        """,
            {"current_skills": current_skill_names, "volunteer_name": volunteer_name},
            as_dict=True,
        )

        if not similar_volunteers:
            return {"success": True, "recommendations": [], "message": "No similar volunteers found"}

        similar_volunteer_names = [v.volunteer_name for v in similar_volunteers]

        # Get skills that similar volunteers have but current volunteer doesn't
        recommendations = frappe.db.sql(
            """
            SELECT
                vs.volunteer_skill,
                vs.skill_category,
                COUNT(DISTINCT vs.parent) as volunteer_count,
                AVG(CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED)) as avg_level
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.parent IN %(similar_volunteers)s
                AND vs.volunteer_skill NOT IN %(current_skills)s
                AND (vs.skill_category IN %(current_categories)s OR vs.skill_category IS NULL)
            GROUP BY vs.volunteer_skill, vs.skill_category
            ORDER BY volunteer_count DESC, avg_level DESC
            LIMIT %(limit)s
        """,
            {
                "similar_volunteers": similar_volunteer_names,
                "current_skills": current_skill_names,
                "current_categories": current_categories,
                "limit": limit,
            },
            as_dict=True,
        )

        return {
            "success": True,
            "recommendations": recommendations,
            "similar_volunteers_count": len(similar_volunteers),
            "current_skills_count": len(current_skills),
        }

    except Exception as e:
        frappe.log_error(f"Error getting skill recommendations: {str(e)}")
        return {"success": False, "error": str(e), "recommendations": []}


@frappe.whitelist()
def get_skill_gaps_analysis():
    """Analyze skill gaps in the organization"""
    try:
        # Get skills that are in development but have few current practitioners
        skill_gaps = frappe.db.sql(
            """
            SELECT
                vdg.skill,
                COUNT(DISTINCT vdg.parent) as learners_count,
                COALESCE(current_skills.practitioners_count, 0) as current_practitioners,
                AVG(CAST(vdg.current_level AS UNSIGNED)) as avg_current_level,
                AVG(CAST(vdg.target_level AS UNSIGNED)) as avg_target_level
            FROM `tabVolunteer Development Goal` vdg
            INNER JOIN `tabVolunteer` v ON vdg.parent = v.name
            LEFT JOIN (
                SELECT
                    volunteer_skill,
                    COUNT(DISTINCT parent) as practitioners_count
                FROM `tabVolunteer Skill` vs2
                INNER JOIN `tabVolunteer` v2 ON vs2.parent = v2.name
                WHERE v2.status = 'Active'
                    AND CAST(LEFT(vs2.proficiency_level, 1) AS UNSIGNED) >= 3
                GROUP BY volunteer_skill
            ) current_skills ON vdg.skill = current_skills.volunteer_skill
            WHERE v.status = 'Active'
                AND vdg.skill IS NOT NULL
                AND vdg.skill != ''
            GROUP BY vdg.skill
            HAVING COUNT(DISTINCT vdg.parent) > COALESCE(MAX(current_skills.practitioners_count), 0)
            ORDER BY (COUNT(DISTINCT vdg.parent) - COALESCE(MAX(current_skills.practitioners_count), 0)) DESC, COUNT(DISTINCT vdg.parent) DESC
            LIMIT 15
        """,
            as_dict=True,
        )

        # Get categories with lowest volunteer coverage
        category_gaps = frappe.db.sql(
            """
            SELECT
                skill_category,
                COUNT(DISTINCT parent) as volunteer_count,
                COUNT(DISTINCT volunteer_skill) as skill_count,
                AVG(CAST(LEFT(proficiency_level, 1) AS UNSIGNED)) as avg_proficiency
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
            GROUP BY skill_category
            ORDER BY volunteer_count ASC, avg_proficiency ASC
        """,
            as_dict=True,
        )

        return {"success": True, "skill_gaps": skill_gaps or [], "category_gaps": category_gaps or []}

    except Exception as e:
        frappe.log_error(f"Error in skill gaps analysis: {str(e)}")
        return {"success": False, "error": str(e), "skill_gaps": [], "category_gaps": []}


@frappe.whitelist()
def export_skills_data(format_type="json"):
    """Export skills data for external analysis

    Args:
        format_type: 'json' or 'csv'
    """
    try:
        # Get comprehensive skills data
        skills_data = frappe.db.sql(
            """
            SELECT
                v.name as volunteer_id,
                v.volunteer_name,
                v.status as volunteer_status,
                vs.volunteer_skill,
                vs.skill_category,
                vs.proficiency_level,
                vs.experience_years,
                vs.certifications,
                v.creation as volunteer_created,
                vs.creation as skill_added
            FROM `tabVolunteer Skill` vs
            INNER JOIN `tabVolunteer` v ON vs.parent = v.name
            WHERE v.status = 'Active'
                AND vs.volunteer_skill IS NOT NULL
                AND vs.volunteer_skill != ''
            ORDER BY v.volunteer_name, vs.skill_category, vs.volunteer_skill
        """,
            as_dict=True,
        )

        if format_type.lower() == "csv":
            import csv
            import io

            output = io.StringIO()
            if skills_data:
                writer = csv.DictWriter(output, fieldnames=skills_data[0].keys())
                writer.writeheader()
                writer.writerows(skills_data)

            return {
                "success": True,
                "format": "csv",
                "data": output.getvalue(),
                "filename": f'volunteer_skills_export_{frappe.utils.now_datetime().strftime("%Y%m%d_%H%M%S")}.csv',
            }
        else:
            return {"success": True, "format": "json", "data": skills_data, "count": len(skills_data)}

    except Exception as e:
        frappe.log_error(f"Error exporting skills data: {str(e)}")
        return {"success": False, "error": str(e), "data": []}
