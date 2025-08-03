import frappe


@frappe.whitelist()
def test_foppe_specific_permissions():
    """Test permissions specifically for foppe user"""

    test_user = "foppe@veganisme.org"

    try:
        # Get user details without switching context
        user_exists = frappe.db.exists("User", test_user)
        if not user_exists:
            return {"error": f"User {test_user} does not exist"}

        user_roles = frappe.get_roles(test_user)
        user_member = frappe.db.get_value("Member", {"user": test_user}, "name")

        # Test our query permission function directly
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            get_permission_query_conditions,
        )

        query_condition = get_permission_query_conditions(test_user)

        # Get schedules that should be accessible based on our query condition
        if query_condition:
            sql = f"""
                SELECT name, member, is_template, member_name
                FROM `tabMembership Dues Schedule`
                WHERE {query_condition}
                LIMIT 20
            """
        else:
            sql = """
                SELECT name, member, is_template, member_name
                FROM `tabMembership Dues Schedule`
                LIMIT 20
            """

        accessible_schedules = frappe.db.sql(sql, as_dict=True)

        return {
            "test_user": test_user,
            "user_exists": user_exists,
            "user_roles": user_roles,
            "user_member_record": user_member,
            "query_condition": query_condition,
            "accessible_schedules": accessible_schedules,
            "total_accessible": len(accessible_schedules),
            "templates_in_results": len([s for s in accessible_schedules if s.get("is_template")]),
            "non_templates_in_results": len([s for s in accessible_schedules if not s.get("is_template")]),
            "own_schedules_in_results": len(
                [s for s in accessible_schedules if s.get("member") == user_member]
            ),
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}
