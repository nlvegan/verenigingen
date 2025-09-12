"""
Chapter-based Security Utilities
Provides fine-grained permission control for chapter operations
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


def get_user_manageable_chapters(user=None):
    """
    Get chapters that the current user can manage membership applications for

    Returns:
        list: List of chapter names user can manage, or 'all' for administrators
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # System administrators can manage all chapters
    if any(
        role in user_roles
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen National Board Member"]
    ):
        return "all"

    # Get member record for user
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        return []

    manageable_chapters = []

    # Get chapters where user is a board member with membership permissions
    board_positions = frappe.db.sql(
        """
        SELECT DISTINCT cbm.parent as chapter_name, cbm.chapter_role
        FROM `tabChapter Board Member` cbm
        WHERE cbm.volunteer = %s
        AND cbm.enabled = 1
        AND cbm.is_active = 1
    """,
        (user_member,),
        as_dict=True,
    )

    for position in board_positions:
        # Check if the chapter role has membership management permissions
        role_doc = frappe.get_doc("Chapter Role", position.chapter_role)
        if hasattr(role_doc, "can_approve_memberships") and role_doc.can_approve_memberships:
            manageable_chapters.append(position.chapter_name)
        elif hasattr(role_doc, "permissions_level") and role_doc.permissions_level in ["Admin", "Membership"]:
            manageable_chapters.append(position.chapter_name)

    return manageable_chapters


def can_user_manage_application(member_name, user=None):
    """
    Check if user can manage a specific membership application

    Args:
        member_name (str): Name of the member whose application to check
        user (str, optional): User to check permissions for. Defaults to current user.

    Returns:
        bool: True if user can manage this application
    """
    if not user:
        user = frappe.session.user

    manageable_chapters = get_user_manageable_chapters(user)

    # Administrators can manage all applications
    if manageable_chapters == "all":
        return True

    if not manageable_chapters:
        return False

    # Get the chapter(s) associated with this member's application
    member_chapters = frappe.db.sql(
        """
        SELECT DISTINCT cm.parent as chapter_name
        FROM `tabChapter Member` cm
        WHERE cm.member = %s
        AND cm.enabled = 1
        AND cm.status = 'Active'
    """,
        (member_name,),
        as_dict=True,
    )

    # If member has no chapter assignment, only national board can manage
    if not member_chapters:
        return False

    # Check if user can manage any of the member's chapters
    member_chapter_names = [ch.chapter_name for ch in member_chapters]
    return any(chapter in manageable_chapters for chapter in member_chapter_names)


def filter_applications_by_permission(applications, user=None):
    """
    Filter list of applications to only include those user can manage

    Args:
        applications (list): List of application dictionaries
        user (str, optional): User to check permissions for

    Returns:
        list: Filtered applications list
    """
    if not user:
        user = frappe.session.user

    manageable_chapters = get_user_manageable_chapters(user)

    # Administrators see all applications
    if manageable_chapters == "all":
        return applications

    if not manageable_chapters:
        return []

    filtered_applications = []
    for app in applications:
        if can_user_manage_application(app.get("name"), user):
            filtered_applications.append(app)

    return filtered_applications


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_user_chapter_permissions():
    """
    API endpoint to get current user's chapter management permissions
    Used by frontend to show/hide UI elements

    Returns:
        dict: User's chapter permissions and capabilities
    """
    user = frappe.session.user
    manageable_chapters = get_user_manageable_chapters(user)

    return {
        "manageable_chapters": manageable_chapters,
        "is_admin": manageable_chapters == "all",
        "can_manage_applications": bool(manageable_chapters),
        "chapter_count": len(manageable_chapters) if isinstance(manageable_chapters, list) else "all",
    }


def validate_chapter_permission_or_throw(member_name, action="manage", user=None):
    """
    Validate chapter permission or throw exception

    Args:
        member_name (str): Member name to check
        action (str): Action being attempted (for error messages)
        user (str, optional): User to check

    Raises:
        frappe.PermissionError: If user lacks permission
    """
    if not can_user_manage_application(member_name, user):
        frappe.throw(
            _("You don't have permission to {0} applications for this member's chapter").format(action),
            frappe.PermissionError,
        )
