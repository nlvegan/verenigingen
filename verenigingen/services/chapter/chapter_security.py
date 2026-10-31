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
    # the gate the approval permission check uses, board members could not
    # approve applications for their own chapter at all; it only ever appeared to
    # work for users who also held one of the admin/staff roles short-circuited above.
    #
    # Delegate rather than re-derive. chapter_permission_service.get_user_board_chapters
    # already resolves user -> Member -> Volunteer -> board roster, and is the lookup
    # the chapter dashboard trusts. Keeping a second implementation here is what let
    # the two silently diverge in the first place.
    #
    # This function always resolved identity strictly (Member.user link only, no
    # Member.email fallback), previously via an explicit `strict_user_link=True`
    # passed to the delegate below. #1546 maintainer ruling made that the delegate's
    # ONLY behavior (the fallback branch and its parameter were removed there), so
    # this call site no longer needs the keyword -- the identity rule is unchanged.
    from verenigingen.services.chapter.chapter_permission_service import get_user_board_chapters

    manageable_chapters = []

    for position in get_user_board_chapters(user):
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
        elif getattr(role_doc, "permissions_level", None) == "Admin":
            manageable_chapters.append(chapter_name)

    return manageable_chapters


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


def can_user_manage_application_record(application_name, user=None):
    """Can `user` review this Membership Application Submission?

    Keyed on the application's own `chapter` (#1765), not on a Chapter Member row: the
    application is not a Member and no Pending Chapter Member row exists for it. Who counts as
    holding a seat is get_user_manageable_chapters
    (it deliberately does not require the Chapter itself to be Active, see #1518).

    "All" is whatever get_user_manageable_chapters says: System Manager, Verenigingen
    Administrator, Staff and Verenigingen National Board Member. Admins may review any application,
    including one with no chapter. A board member
    may review only one whose chapter they manage. An unknown name is False, on the same path
    as a foreign one, so the two cannot be told apart.
    """
    if not user:
        user = frappe.session.user

    manageable_chapters = get_user_manageable_chapters(user)
    if manageable_chapters == "all":
        return True
    if not manageable_chapters:
        return False

    chapter = frappe.db.get_value("Membership Application Submission", str(application_name), "chapter")
    return bool(chapter) and chapter in manageable_chapters


def can_user_read_application_record(application_name, user=None):
    """Can `user` read this application? Any active seat on its chapter (Ruling N), admins any.
    The document-permission hook is the one rule (permissions.has_application_permission)."""
    from verenigingen.permissions import has_application_permission

    return bool(has_application_permission(frappe._dict(name=str(application_name)), user, "read"))


def validate_application_permission_or_throw(application_name, action="manage", user=None):
    """Throw PermissionError unless `user` may `action` the application: "read" follows any active seat
    on its chapter, every other action needs an Admin-level seat (can_user_manage_application_record).

    One message for "not yours" and "does not exist" (existence oracle, #1414/#1436).
    """
    allowed = can_user_read_application_record if action == "read" else can_user_manage_application_record
    if not allowed(application_name, user):
        frappe.throw(
            _("You don't have permission to {0} this application").format(action),
            frappe.PermissionError,
        )
