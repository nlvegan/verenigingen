"""
Test cleanup utilities for Verenigingen app.
Provides functions to clean up test data that may be left behind after test runs.
"""

import frappe


@frappe.whitelist()
def cleanup_test_roles():
    """
    Clean up test roles that may be left behind after test runs.
    Can be called via: bench --site site execute verenigingen.utils.test_cleanup.cleanup_test_roles
    """
    test_role_patterns = ["_Test Role", "_Test Role 2", "_Test Role 3", "_Test Role 4"]

    chapter_role_patterns = [
        "Test Role%",
        "Board Role%",
        "Chair Role%",
        "Test Admin Role%",
        "Test Board Role%",
    ]

    deleted_roles = []

    # Clean up standard test roles
    for role_name in test_role_patterns:
        try:
            if frappe.db.exists("Role", role_name):
                # First, remove any user role assignments
                frappe.db.delete("Has Role", {"role": role_name})

                # Then delete the role itself
                frappe.delete_doc("Role", role_name, ignore_permissions=True)
                deleted_roles.append(role_name)
                frappe.logger().info(f"Deleted test role: {role_name}")

        except Exception as e:
            frappe.logger().error(f"Error deleting role {role_name}: {str(e)}")

    # Clean up Chapter Roles with test patterns
    for pattern in chapter_role_patterns:
        try:
            chapter_roles = frappe.get_all(
                "Chapter Role", filters={"role_name": ["like", pattern]}, fields=["name", "role_name"]
            )

            for role in chapter_roles:
                try:
                    frappe.delete_doc("Chapter Role", role.name, ignore_permissions=True)
                    deleted_roles.append(f"Chapter Role: {role.role_name}")
                    frappe.logger().info(f"Deleted test chapter role: {role.role_name}")
                except Exception as e:
                    frappe.logger().error(f"Error deleting chapter role {role.role_name}: {str(e)}")

        except Exception as e:
            frappe.logger().error(f"Error querying chapter roles with pattern {pattern}: {str(e)}")

    # Commit the transaction
    frappe.db.commit()

    return {"success": True, "deleted_count": len(deleted_roles), "deleted_roles": deleted_roles}


@frappe.whitelist()
def cleanup_all_test_data():
    """
    Comprehensive cleanup of all test data including roles, members, chapters, etc.
    Use with caution - only run on development environments.
    """
    if frappe.conf.get("developer_mode") != 1:
        frappe.throw("This function can only be run in developer mode")

    results = {
        "roles": cleanup_test_roles(),
        "members": cleanup_test_members(),
        "chapters": cleanup_test_chapters(),
    }

    return results


def cleanup_test_members():
    """Clean up test members with email patterns like test@example.com"""
    test_patterns = ["%test@example.com", "%@test.com", "test_%@%"]

    deleted_members = []

    for pattern in test_patterns:
        try:
            members = frappe.get_all("Member", filters={"email": ["like", pattern]}, fields=["name", "email"])

            for member in members:
                try:
                    frappe.delete_doc("Member", member.name, ignore_permissions=True)
                    deleted_members.append(member.email)
                    frappe.logger().info(f"Deleted test member: {member.email}")
                except Exception as e:
                    frappe.logger().error(f"Error deleting member {member.email}: {str(e)}")

        except Exception as e:
            frappe.logger().error(f"Error querying members with pattern {pattern}: {str(e)}")

    return {"deleted_count": len(deleted_members), "deleted_members": deleted_members}


def cleanup_test_chapters():
    """Clean up test chapters"""
    test_patterns = ["Test Chapter%", "%Test%"]

    deleted_chapters = []

    for pattern in test_patterns:
        try:
            chapters = frappe.get_all("Chapter", filters={"name": ["like", pattern]}, fields=["name"])

            for chapter in chapters:
                try:
                    frappe.delete_doc("Chapter", chapter.name, ignore_permissions=True)
                    deleted_chapters.append(chapter.name)
                    frappe.logger().info(f"Deleted test chapter: {chapter.name}")
                except Exception as e:
                    frappe.logger().error(f"Error deleting chapter {chapter.name}: {str(e)}")

        except Exception as e:
            frappe.logger().error(f"Error querying chapters with pattern {pattern}: {str(e)}")

    return {"deleted_count": len(deleted_chapters), "deleted_chapters": deleted_chapters}
