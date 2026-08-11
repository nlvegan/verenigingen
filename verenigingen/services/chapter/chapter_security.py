"""
Chapter-based Security Utilities
Provides fine-grained permission control for chapter operations
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
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

    # System administrators and staff can manage all chapters
    if any(
        role in user_roles
        for role in [
            Roles.SYSTEM_MANAGER,
            Roles.VERENIGINGEN_ADMIN,
            Roles.VERENIGINGEN_STAFF,
            "Verenigingen National Board Member",
        ]
    ):
        return "all"

    # Board seats are held by a VOLUNTEER, not a Member: a member with a volunteer
    # profile is what gets registered on a chapter's board roster. This function used
    # to resolve the caller's Member and compare THAT name against
    # `Chapter Board Member.volunteer`, which holds a Volunteer name -- the two are
    # different namespaces (Assoc-Member-... vs Assoc-Vol-...), so the query never
    # matched and every board member was read as managing no chapters. Since this is
    # the gate `validate_chapter_permission_or_throw` uses, board members could not
    # approve applications for their own chapter at all; it only ever appeared to
    # work for users who also held one of the admin/staff roles short-circuited above.
    #
    # Delegate rather than re-derive. chapter_permission_service.get_user_board_chapters
    # already resolves user -> Member -> Volunteer -> board roster, and is the lookup
    # the chapter dashboard trusts. Keeping a second implementation here is what let
    # the two silently diverge in the first place.
    #
    # strict_user_link=True keeps the IDENTITY rule this function already had. The
    # delegate's default resolution falls back to matching Member.email when no
    # Member.user link matches, which would admit a User who merely shares an address
    # with a Member they are not linked to -- 126 such Members exist on this database,
    # one of whose volunteers holds an active board seat. That is a looser rule than
    # the gate guarding approvals, and adopting it here would have been an
    # authorization change smuggled in as a lookup fix. The board dashboard keeps the
    # fallback; this path does not.
    from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters

    manageable_chapters = []

    for position in get_user_board_chapters(user, strict_user_link=True):
        chapter_name = position.get("chapter_name")
        chapter_role = position.get("chapter_role")
        if not chapter_name or not chapter_role or chapter_name in manageable_chapters:
            continue

        # Unchanged acceptance rule -- this fix is about WHO is found, not about
        # widening what a board role may do. Note both arms are narrower than they
        # read: Chapter Role has no `can_approve_memberships` field, and
        # `permissions_level` offers only Basic/Financial/Admin, so in practice
        # "Admin" is the only level that grants approval today. Changing that is an
        # authorization decision, not a bug fix.
        role_doc = frappe.get_doc("Chapter Role", chapter_role)
        if getattr(role_doc, "can_approve_memberships", None):
            manageable_chapters.append(chapter_name)
        elif getattr(role_doc, "permissions_level", None) in ["Admin", "Membership"]:
            manageable_chapters.append(chapter_name)

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
