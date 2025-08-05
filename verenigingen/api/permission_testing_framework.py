"""
Permission Testing Framework

Provides utilities for testing and validating DocType permissions across different user roles.
"""

import frappe


@frappe.whitelist()
def validate_membership_dues_schedule_permissions():
    """Test permissions for membership dues schedule"""

    current_user = frappe.session.user
    current_roles = frappe.get_roles(current_user)

    result = {
        "current_user": current_user,
        "current_roles": current_roles,
        "is_system_manager": "System Manager" in current_roles,
        "is_admin_role": any(
            role in current_roles for role in ["Verenigingen Administrator", "Verenigingen Manager"]
        ),
        "test_results": [],
        "permission_debug": [],
    }

    # Get a sample dues schedule that should NOT be accessible
    other_schedule = frappe.db.sql(
        """
        SELECT name, member, is_template, member_name
        FROM `tabMembership Dues Schedule`
        WHERE is_template = 0
        LIMIT 1
    """,
        as_dict=True,
    )

    if other_schedule:
        schedule_name = other_schedule[0].name
        schedule_member = other_schedule[0].member

        test_result = {
            "schedule_name": schedule_name,
            "schedule_member": schedule_member,
            "member_user": None,
            "should_have_access": False,
            "permission_result": None,
            "error": None,
        }

        # Check if current user is linked to this member
        if schedule_member:
            member_user = frappe.db.get_value("Member", schedule_member, "user")
            test_result["member_user"] = member_user
            test_result["should_have_access"] = member_user == current_user

        # Test the has_permission function directly with detailed debugging
        try:
            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                has_permission,
            )

            # Get the actual document
            doc = frappe.get_doc("Membership Dues Schedule", schedule_name)

            # Debug the permission function step by step
            debug_info = {
                "doc_name": doc.name,
                "doc_member": getattr(doc, "member", None),
                "doc_is_template": getattr(doc, "is_template", None),
                "current_user": current_user,
                "system_manager_check": "System Manager" in frappe.get_roles(current_user),
                "admin_roles_check": any(
                    role in frappe.get_roles(current_user)
                    for role in ["Verenigingen Administrator", "Verenigingen Manager"]
                ),
                "template_check": getattr(doc, "is_template", False),
                "member_user_lookup": None,
                "user_matches_member": False,
            }

            # Check member-user relationship
            if hasattr(doc, "member") and doc.member:
                debug_info["member_user_lookup"] = frappe.db.get_value("Member", doc.member, "user")
                debug_info["user_matches_member"] = debug_info["member_user_lookup"] == current_user

            result["permission_debug"].append(debug_info)

            # Test permission function
            permission_result = has_permission(doc, current_user, "read")
            test_result["permission_result"] = permission_result

        except Exception as e:
            test_result["error"] = str(e)

        result["test_results"].append(test_result)

    # Test template access
    template_schedule = frappe.db.sql(
        """
        SELECT name, is_template
        FROM `tabMembership Dues Schedule`
        WHERE is_template = 1
        LIMIT 1
    """,
        as_dict=True,
    )

    if template_schedule:
        template_name = template_schedule[0].name

        template_test = {
            "schedule_name": template_name,
            "is_template": True,
            "should_have_access": True,
            "permission_result": None,
            "error": None,
        }

        try:
            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                has_permission,
            )

            template_doc = frappe.get_doc("Membership Dues Schedule", template_name)
            template_permission = has_permission(template_doc, current_user, "read")
            template_test["permission_result"] = template_permission

        except Exception as e:
            template_test["error"] = str(e)

        result["test_results"].append(template_test)

    return result


@frappe.whitelist()
def validate_doctype_list_access():
    """Test what happens when accessing the doctype list"""

    current_user = frappe.session.user
    current_roles = frappe.get_roles(current_user)

    try:
        # Try to get all membership dues schedules (this should trigger permission checks)
        schedules = frappe.get_list(
            "Membership Dues Schedule", fields=["name", "member", "is_template", "member_name"], limit=5
        )

        return {
            "current_user": current_user,
            "current_roles": current_roles,
            "accessible_schedules": schedules,
            "total_accessible": len(schedules),
        }
    except Exception as e:
        return {"current_user": current_user, "current_roles": current_roles, "error": str(e)}


@frappe.whitelist()
def validate_permissions_for_user(test_user_email):
    """Test permissions as a different user"""

    # Temporarily switch user context
    original_user = frappe.session.user

    try:
        # Check if user exists
        if not frappe.db.exists("User", test_user_email):
            return {"error": f"User {test_user_email} does not exist"}

        # Switch user context
        frappe.set_user(test_user_email)

        # Get user info
        current_user = frappe.session.user
        current_roles = frappe.get_roles(current_user)

        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": current_user}, "name")

        # Test list access
        schedules = frappe.get_list(
            "Membership Dues Schedule", fields=["name", "member", "is_template", "member_name"], limit=20
        )  # Increased limit to see more results

        return {
            "test_user": current_user,
            "test_roles": current_roles,
            "user_member_record": user_member,
            "accessible_schedules": schedules,
            "total_accessible": len(schedules),
            "templates_in_results": len([s for s in schedules if s.get("is_template")]),
            "non_templates_in_results": len([s for s in schedules if not s.get("is_template")]),
            "own_schedules_in_results": len([s for s in schedules if s.get("member") == user_member]),
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        # Always restore original user
        frappe.set_user(original_user)
