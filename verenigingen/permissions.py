"""
Verenigingen Permissions and Access Control System
==================================================

Comprehensive permission management system for the Verenigingen association
management platform. This module implements role-based access control,
hierarchical permissions, and member-specific access restrictions to ensure
data security and proper authorization throughout the system.

Primary Purpose:
    Provides granular access control for member data, financial information,
    administrative functions, and organizational hierarchy management. Implements
    security policies that respect member privacy while enabling necessary
    operational access for board members, administrators, and staff.

Key Features:
    * Member-based permission hierarchies with chapter and team-level access
    * Financial information access control with configurable privacy levels
    * Board member and administrative override capabilities
    * Dynamic permission queries for efficient database-level filtering
    * Team and volunteer management access control
    * Address and contact information privacy protection

Permission Hierarchies:
    1. **System Level**: System Managers and Verenigingen Administrators
    2. **Organization Level**: Verenigingen Staffs and operational staff
    3. **Chapter Level**: Chapter Board Members and local administrators
    4. **Team Level**: Team Leaders and volunteer coordinators
    5. **Member Level**: Individual member self-access and privacy controls

Business Rules:
    * Members can access their own data with full visibility
    * Board members can access members within their chapters with restrictions
    * Financial information access is governed by member privacy preferences
    * Administrative functions require appropriate role-based permissions
    * Termination and sensitive operations require elevated access levels

Security Framework:
    * SQL injection prevention through proper parameter escaping
    * Permission caching for performance optimization
    * Audit trail integration for sensitive operations
    * Multi-level validation for critical functions
    * Graceful fallback to standard Frappe permissions when appropriate

Integration Points:
    * Frappe Framework permission system for baseline security
    * Member DocType for personal data and privacy preferences
    * Chapter and Team DocTypes for organizational hierarchy
    * Volunteer management system for role-based access
    * Financial data access control for billing and payment information

Technical Implementation:
    Implements both document-level permissions (has_*_permission functions)
    and query-level filtering (get_*_permission_query functions) to ensure
    comprehensive access control at both application and database levels.
"""

import time
from functools import lru_cache

import frappe

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import (
    get_member_name_for_user,
    get_volunteer_for_member,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
)
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# Permission Caching System
# =========================


@lru_cache(maxsize=100)
def get_user_chapter_memberships_cached(user, cache_key=None):
    """Cache user's chapter memberships to reduce database queries

    Args:
        user: User email/ID
        cache_key: Optional cache invalidation key (timestamp)

    Returns:
        List of chapter names where user is a board member
    """
    if not user:
        return []

    try:
        user_chapters = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent as chapter_name
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.user = %s AND cbm.is_active = 1
        """,
            (user,),
            as_dict=True,
        )

        return [c.chapter_name for c in user_chapters]

    except Exception as e:
        frappe.log_error(f"Error getting user chapter memberships for {user}: {e}")
        return []


@lru_cache(maxsize=50)
def get_user_treasurer_chapters_cached(user, cache_key=None):
    """Cache user's treasurer positions to optimize permission checks

    Args:
        user: User email/ID
        cache_key: Optional cache invalidation key (timestamp)

    Returns:
        List of chapter names where user is treasurer
    """
    if not user:
        return []

    try:
        treasurer_chapters = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent as chapter_name
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            WHERE m.user = %s
            AND cbm.is_active = 1
            AND cr.permissions_level = 'Financial'
        """,
            (user,),
            as_dict=True,
        )

        return [c.chapter_name for c in treasurer_chapters]

    except Exception as e:
        frappe.log_error(f"Error getting user treasurer chapters for {user}: {e}")
        return []


def clear_permission_cache():
    """Clear permission caches - call when roles/memberships change"""
    try:
        get_user_chapter_memberships_cached.cache_clear()
        get_user_treasurer_chapters_cached.cache_clear()

        # Clear Frappe's internal cache as well
        if hasattr(frappe.local, "cache"):
            frappe.local.cache = {}

    except Exception as e:
        frappe.log_error(f"Error clearing permission cache: {e}")


def get_cache_key():
    """Generate cache invalidation key based on current time (5 minute intervals)"""
    return int(time.time() // 300)  # 5-minute cache intervals


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def can_terminate_member_api(member_name: str):
    """Whitelisted API wrapper for can_terminate_member"""
    return can_terminate_member(member_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def can_access_termination_functions_api():
    """Whitelisted API wrapper for can_access_termination_functions"""
    return can_access_termination_functions()


@frappe.whitelist()
@development_only_api()
def test_team_member_access(team_name: str | None = None):
    """Test function to verify team member access permissions"""
    user = frappe.session.user

    # Get user's roles
    user_roles = frappe.get_roles(user)

    # Get user's member record
    member = get_member_name_for_user(user)
    if not member:
        return {"error": "No member record found", "user": user, "roles": user_roles}

    # Get user's volunteer record
    volunteer = get_volunteer_for_member(member)
    if not volunteer:
        return {"error": "No volunteer record found", "member": member, "roles": user_roles}

    # Get user's teams
    user_teams = frappe.db.sql(
        """
        SELECT DISTINCT parent, role_type, role
        FROM `tabTeam Member`
        WHERE volunteer = %s AND is_active = 1
    """,
        volunteer,
        as_dict=True,
    )

    result = {
        "user": user,
        "roles": user_roles,
        "member": member,
        "volunteer": volunteer,
        "teams": user_teams,
        "can_access_team": False,
        "portal_url": None,
    }

    if team_name:
        # Check if user can access specific team
        can_access = DocumentExistenceValidator.check_document_exists(
            "Team Member", {"parent": team_name, "volunteer": volunteer, "is_active": 1}
        )
        result["can_access_team"] = bool(can_access)
        result["requested_team"] = team_name

        if can_access:
            result["portal_url"] = f"/team_members?team={team_name}"

    return result


def _check_service_account_permission(user, doctype, permission_type="read"):
    """
    Check if user is a service account with proper DocPerm for the specified DocType.

    Service accounts (webhooks, background jobs) bypass chapter-based filtering
    and defer to standard Frappe DocPerm entries instead.

    Args:
        user: User email
        doctype: DocType name to check permissions for
        permission_type: Permission type (read, write, create, delete, submit, cancel)

    Returns:
        True if service account has permission
        False if service account lacks permission
        None if user is not a service account (caller should continue with normal permission logic)
    """
    user_roles = frappe.get_roles(user)
    service_roles = [Roles.WEBHOOK_USER]

    if not any(role in user_roles for role in service_roles):
        return None  # Not a service account, caller should continue with normal logic

    frappe.logger().debug(f"User {user} is a service account, checking DocPerm for {doctype}")

    perm_type = permission_type or "read"
    docperm_filters = {
        "parent": doctype,
        "role": ["in", service_roles],
        perm_type: 1,
    }
    has_docperm = frappe.db.exists("DocPerm", docperm_filters)

    if has_docperm:
        frappe.logger().debug(f"Service account {user} has DocPerm for {doctype} {perm_type}")
        return True

    frappe.logger().debug(f"Service account {user} lacks DocPerm for {doctype} {perm_type}")
    return False


def _get_board_chapters_for_member(member_name):
    """Return list of chapter names where member is an active board member.

    Queries Chapter Board Member → Volunteer → Member to find chapters
    where the given member holds an active board position.

    Args:
        member_name: Member document name

    Returns:
        List of chapter name strings (empty list on error or no results)
    """
    if not member_name:
        return []

    try:
        rows = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent as chapter_name
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE v.member = %s AND cbm.is_active = 1
            """,
            member_name,
            as_dict=True,
        )
        return [r.chapter_name for r in rows]
    except Exception as e:
        frappe.log_error(f"Error getting board chapters for member {member_name}: {e}")
        return []


def _is_member_in_chapters(member_name, chapter_names):
    """Check if a member has active membership in any of the given chapters.

    Args:
        member_name: Member document name to check
        chapter_names: List of chapter names to check against

    Returns:
        True if member is an active member in at least one of the chapters
    """
    if not member_name or not chapter_names:
        return False

    result = frappe.db.sql(
        """
        SELECT 1
        FROM `tabChapter Member`
        WHERE member = %s
          AND parent IN ({})
          AND status = 'Active'
        LIMIT 1
        """.format(
            ",".join(["%s"] * len(chapter_names))
        ),
        [member_name] + list(chapter_names),
    )
    return bool(result)


def _has_admin_access(user_roles, admin_role_set=None):
    """Check if user has any admin role.

    Centralizes the admin role check pattern used across 13+ permission functions.

    Args:
        user_roles: List of role names for the user (from frappe.get_roles())
        admin_role_set: Specific admin role set to check against.
            Defaults to Roles.ADMIN_ROLES if not provided.

    Returns:
        True if user has at least one admin role
    """
    if admin_role_set is None:
        admin_role_set = Roles.ADMIN_ROLES
    return any(role in user_roles for role in admin_role_set)


def _check_chapter_board_access(user, target_member_name):
    """Check if user has chapter board access to the target member.

    Composite helper: resolves user → member → board chapters, then checks
    whether the target member is in any of those chapters.

    Args:
        user: User email/ID
        target_member_name: Member name of the document being accessed

    Returns:
        True if user is a board member of a chapter containing the target member,
        False otherwise
    """
    user_member = get_member_name_for_user(user)
    if not user_member:
        frappe.logger().debug(f"User {user} has no Member record")
        return False

    board_chapters = _get_board_chapters_for_member(user_member)
    if not board_chapters:
        frappe.logger().debug(f"User {user} is not an active board member in any chapter")
        return False

    return _is_member_in_chapters(target_member_name, board_chapters)


def has_member_permission(doc, user=None, permission_type=None):
    """
    Direct permission check for Member doctype with chapter-based access control

    Permission Hierarchy:
    1. Admin roles (System Manager, Verenigingen Staff, Verenigingen Administrator) - Full access
    2. Service accounts (Webhooks) - Defer to standard DocPerm
    3. Chapter Board Members - Access to members in their chapters only
    4. Verenigingen Staff - Read-only access (limited by query conditions)
    5. Verenigingen Members - Access to own record only
    """
    if not user:
        user = frappe.session.user

    # Log for debugging
    frappe.logger().debug(f"Checking Member permissions for user {user} with roles {frappe.get_roles(user)}")

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    if _has_admin_access(user_roles):
        return True

    # Service accounts (webhooks, background jobs) defer to standard Frappe DocPerm
    service_result = _check_service_account_permission(user, "Member", permission_type)
    if service_result is not None:
        return service_result

    # Get the member record name being accessed
    member_name = doc.name if hasattr(doc, "name") else doc if isinstance(doc, str) else None
    if not member_name:
        frappe.logger().debug(f"Could not determine member name from doc: {doc}")
        return False

    # Chapter Board Members - can access members in their chapters only
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            # Use cached function to get user's chapters
            user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())

            if user_chapter_names:
                if _is_member_in_chapters(member_name, user_chapter_names):
                    return True

                # Fallback: check if user has a termination request for this member
                termination_requests = frappe.db.sql(
                    """
                    SELECT name
                    FROM `tabMembership Termination Request`
                    WHERE member = %s
                """,
                    member_name,
                    as_dict=True,
                )

                if termination_requests:
                    for req in termination_requests:
                        if has_membership_termination_request_permission(req.name, user, "read"):
                            frappe.logger().debug(
                                f"User {user} has termination request access for member {member_name}"
                            )
                            return True
            else:
                frappe.logger().debug(f"User {user} is not an active board member in any chapter")

        except Exception as e:
            frappe.log_error(f"Error checking chapter board member permissions: {str(e)}")

    # Verenigingen Staff - handled by query conditions, allow individual document access
    if Roles.VERENIGINGEN_STAFF in user_roles:
        frappe.logger().debug(f"User {user} has Verenigingen Staff role, allowing access")
        return True

    # For regular members, check if they own the record
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        # Get user's member record
        user_member = get_member_name_for_user(user)
        if user_member == member_name:
            frappe.logger().debug(f"User {user} accessing own member record")
            return True

        # Also check owner field for backward compatibility
        if isinstance(doc, str):
            owner = frappe.db.get_value("Member", doc, "owner")
            return owner == user
        else:
            return getattr(doc, "owner", None) == user

    # Return False for users without proper roles
    frappe.logger().debug(f"User {user} has no appropriate role for Member access")
    return False


def has_volunteer_permission(doc, user=None, permission_type=None):
    """
    Direct permission check for Volunteer doctype with member and chapter-based access control

    Permission Hierarchy:
    1. Admin roles (System Manager, etc.) - Full access
    2. Volunteer Manager - Full access
    3. Chapter Board Members - Access to volunteers in their chapters
    4. Team Leaders - Access to volunteers in their teams
    5. Verenigingen Members - Access to own volunteer record only
    """
    if not user:
        user = frappe.session.user

    frappe.logger().debug(f"Checking Volunteer permissions for user {user}")

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    if _has_admin_access(user_roles, Roles.VOLUNTEER_ADMIN_ROLES):
        return True

    # Service accounts (webhooks, background jobs) defer to standard Frappe DocPerm
    service_result = _check_service_account_permission(user, "Volunteer", permission_type)
    if service_result is not None:
        return service_result

    # Get the volunteer record name being accessed
    volunteer_name = doc.name if hasattr(doc, "name") else doc if isinstance(doc, str) else None
    if not volunteer_name:
        frappe.logger().debug(f"Could not determine volunteer name from doc: {doc}")
        return False

    # Get the volunteer's linked member
    volunteer_member = frappe.db.get_value("Volunteer", volunteer_name, "member")
    if not volunteer_member:
        frappe.logger().debug(f"Volunteer {volunteer_name} has no linked member")
        return False

    # Get current user's member record
    user_member = get_member_name_for_user(user)
    if not user_member:
        frappe.logger().debug(f"User {user} has no Member record")
        return False

    # Members can access their own volunteer record
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        if user_member == volunteer_member:
            frappe.logger().debug(f"User {user} accessing own volunteer record")
            return True

    # Chapter Board Members can access volunteers in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            board_chapters = _get_board_chapters_for_member(user_member)
            if board_chapters and _is_member_in_chapters(volunteer_member, board_chapters):
                return True
        except Exception as e:
            frappe.log_error(f"Error checking chapter board member permissions for volunteer: {str(e)}")

    # Team leaders can access volunteers on teams they lead. Leadership is derived
    # from the team data — an is_team_leader Team Role on an ACTIVE membership —
    # NOT from a role gate: production never assigns the "Team Leader" role
    # (leaders hold an is_team_leader Team Role, or are a Team.team_lead), so a
    # `Roles.TEAM_LEADER in user_roles` pre-filter would make this branch dead.
    # `tabTeam Member`.volunteer holds Volunteer docnames, so we join tabVolunteer
    # to resolve the leader by member (covering a member with multiple volunteers,
    # matching get_volunteer_permission_query); the target's Volunteer is
    # volunteer_name. The query self-limits to actual leaders, so running it for a
    # non-leader simply returns 0.
    try:
        team_overlap = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabTeam Member` tm1
            JOIN `tabTeam Role` tr1 ON tm1.team_role = tr1.name
            JOIN `tabVolunteer` lead_v ON tm1.volunteer = lead_v.name
            JOIN `tabTeam Member` tm2 ON tm1.parent = tm2.parent
            WHERE lead_v.member = %s AND tr1.is_team_leader = 1 AND tm1.status = 'Active'
            AND tm2.volunteer = %s AND tm2.status = 'Active'
        """,
            (user_member, volunteer_name),
            as_dict=True,
        )

        if team_overlap and team_overlap[0].count > 0:
            frappe.logger().debug(f"User {user} is team leader with access to volunteer {volunteer_name}")
            return True

    except Exception as e:
        frappe.log_error(f"Error checking team leader permissions for volunteer: {str(e)}")

    # No access granted
    frappe.logger().debug(f"User {user} has no appropriate access to volunteer {volunteer_name}")
    return False


def has_membership_permission(doc, user=None, permission_type=None):
    """Direct permission check for Membership doctype"""
    if not user:
        user = frappe.session.user

    # Log for debugging
    frappe.logger().debug(
        f"Checking Membership permissions for user {user} with roles {frappe.get_roles(user)}"
    )

    # Admin roles always have access
    if _has_admin_access(frappe.get_roles(user)):
        return True

    # Return True, NOT None, to mean "this controller has no objection".
    #
    # Frappe treats a falsy hook result as a DENY, not as "no opinion":
    # frappe/permissions.py::has_controller_permissions does
    #     if not controller_permission:
    #         return bool(controller_permission)
    # so `None` short-circuits the whole check to False. The previous `return None`
    # (documented as "fall back to standard permission system") therefore denied
    # doc-level access to every user outside Roles.ADMIN_ROLES, which silently made
    # this doctype's DocPerms for `Verenigingen Chapter Board Member` and
    # `Verenigingen Member` dead letters -- a board member could not insert the
    # Membership that approving an application creates, and the failure surfaced as
    # an empty "Error creating membership: " because frappe.PermissionError is raised
    # bare (frappe/model/document.py::raise_no_permission_to).
    #
    # Returning True does not widen anything: role-level DocPerms are evaluated
    # separately by has_permission() and still apply. This only stops the controller
    # from vetoing them. Same falsy-return class as PR #191, inverted -- there a
    # falsy result read as "unrestricted", here it read as "denied".
    return True


def _make_member_linked_permission(doctype, member_field="member"):
    """Build the (has_permission, permission_query) pair for a doctype that links to
    Member via a direct ``member`` Link field and must be member-scoped.

    The access policy is identical across such doctypes: admins/staff and service
    accounts pass through, a chapter board member reaches records for members in
    their chapters, and a regular member reaches only their own records. Donor and
    SEPA Mandate share this exact shape byte-for-byte, so both pairs are generated
    here instead of being maintained as copies.

    (Donation is excluded: it links two hops via Donor, not a direct ``member``
    field. Address is excluded: it links via Dynamic Link. Member is the base record
    itself. Those keep their own bespoke functions.)

    Args:
        doctype: The DocType name (e.g. "Donor", "SEPA Mandate").
        member_field: The Link-to-Member fieldname on the doctype (default "member").

    Returns:
        (has_permission, permission_query) — a has_permission(doc, user, permission_type)
        callable and a permission_query(user) callable, named after the doctype.
    """
    # doctype + member_field are interpolated into SQL (table name + column). They are
    # always hardcoded DocType/field literals today; guard the contract so this reusable
    # access-control primitive cannot be handed an injection vector by a future caller.
    if "`" in doctype:
        raise ValueError(f"Invalid doctype for permission factory: {doctype!r}")
    if not member_field.isidentifier():
        raise ValueError(f"member_field must be a valid identifier, got {member_field!r}")

    table = f"`tab{doctype}`"
    slug = doctype.lower().replace(" ", "_")

    def has_permission(doc, user=None, permission_type=None):
        if not user:
            user = frappe.session.user

        # Defense-in-depth: never grant access to a disabled user account that still
        # holds roles. Frappe normally blocks disabled users at login, but a disabled
        # user retaining roles would otherwise pass the checks below. Administrator is
        # always treated as enabled; get_value returns None for service accounts (NOT
        # == 0), so only an explicitly-disabled real User is denied here.
        if user not in ("Administrator", "Guest"):
            if frappe.db.get_value("User", user, "enabled") == 0:
                frappe.logger().debug(f"User {user} is disabled; denying {doctype} access")
                return False

        user_roles = frappe.get_roles(user)

        # Admin / staff roles always have access (org-wide)
        if _has_admin_access(user_roles):
            return True

        # Service accounts (webhooks, background jobs) defer to standard Frappe DocPerm
        service_result = _check_service_account_permission(user, doctype, permission_type)
        if service_result is not None:
            return service_result

        # Resolve the record's linked member
        if isinstance(doc, str):
            if not DocumentExistenceValidator.check_document_exists(doctype, doc):
                frappe.logger().debug(f"{doctype} record {doc} does not exist")
                return False
            linked_member = frappe.db.get_value(doctype, doc, member_field)
        else:
            linked_member = getattr(doc, member_field, None)

        if not linked_member:
            frappe.logger().debug(f"{doctype} record has no linked member")
            return False

        # A dangling member link (member deleted) is denied for non-admins.
        if not DocumentExistenceValidator.check_document_exists("Member", linked_member):
            frappe.logger().debug(f"Linked member {linked_member} no longer exists")
            return False

        # Chapter board members can access records for members in their chapters
        if Roles.CHAPTER_BOARD_MEMBER in user_roles:
            try:
                if _check_chapter_board_access(user, linked_member):
                    return True
            except Exception as e:
                frappe.logger().error(f"Error checking chapter board {doctype} permission: {str(e)}")

        # For regular members, grant only their own records
        if Roles.VERENIGINGEN_MEMBER in user_roles:
            try:
                user_member = get_member_name_for_user(user)
                if not user_member:
                    frappe.logger().debug(
                        f"User {user} has Verenigingen Member role but no member record found"
                    )
                    return False
                return linked_member == user_member
            except Exception as e:
                frappe.logger().error(f"Error checking {doctype} permission for user {user}: {str(e)}")
                return False

        # Users without proper roles see nothing
        return False

    def permission_query(user):
        if not user:
            user = frappe.session.user

        user_roles = frappe.get_roles(user)

        # Admin / staff roles get access to all records (org-wide)
        if _has_admin_access(user_roles):
            return ""  # No filter needed

        conditions = []

        # Chapter board members can see records for members in their chapters
        if Roles.CHAPTER_BOARD_MEMBER in user_roles:
            user_member = get_member_name_for_user(user)
            if user_member:
                board_chapters = _get_board_chapters_for_member(user_member)
                if board_chapters:
                    chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
                    conditions.append(
                        f"""
                    {table}.{member_field} IN (
                        SELECT cm.member
                        FROM `tabChapter Member` cm
                        WHERE cm.parent IN ({','.join(chapter_names)})
                          AND cm.status = 'Active'
                    )
                """
                    )

        # For regular members, limit to records linked to their own member record
        if Roles.VERENIGINGEN_MEMBER in user_roles:
            user_member = get_member_name_for_user(user)
            if user_member:
                conditions.append(f"{table}.{member_field} = {frappe.db.escape(user_member)}")

        if conditions:
            return f"({' OR '.join(conditions)})"

        # Users without proper roles see no records
        return "1=0"

    has_permission.__name__ = has_permission.__qualname__ = f"has_{slug}_permission"
    permission_query.__name__ = permission_query.__qualname__ = f"get_{slug}_permission_query"
    return has_permission, permission_query


# Donor and SEPA Mandate share the identical member-scoped policy; generate both pairs
# from the factory rather than maintaining byte-identical copies. The module-level names
# remain importable (e.g. `from verenigingen.permissions import has_donor_permission`) and
# resolvable by the hooks in hooks/permissions.py.
has_donor_permission, get_donor_permission_query = _make_member_linked_permission("Donor")
has_sepa_mandate_permission, get_sepa_mandate_permission_query = _make_member_linked_permission(
    "SEPA Mandate"
)


def has_donation_permission(doc, user=None, permission_type=None):
    """Direct permission check for Donation doctype

    Grants access to:
    - Admins (System Manager, Verenigingen Staff, Verenigingen Administrator)
    - Service accounts (Webhooks) - Defer to standard DocPerm
    - Chapter Board Members (for donations linked to donors/members in their chapters)
    - Members (for their own donation records)
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles always have access (org-wide)
    if _has_admin_access(user_roles):
        return True

    # Service accounts (webhooks, background jobs) defer to standard Frappe DocPerm
    service_result = _check_service_account_permission(user, "Donation", permission_type)
    if service_result is not None:
        return service_result

    # Get donation's donor and member
    if isinstance(doc, str):
        if not DocumentExistenceValidator.check_document_exists("Donation", doc):
            return False
        donor_name = frappe.db.get_value("Donation", doc, "donor")
    else:
        donor_name = getattr(doc, "donor", None)

    if not donor_name:
        return False

    # Get the member linked to this donor
    donor_member = frappe.db.get_value("Donor", donor_name, "member")
    if not donor_member:
        return False

    # Chapter Board Members can access donations for members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            if _check_chapter_board_access(user, donor_member):
                return True
        except Exception as e:
            frappe.logger().error(f"Error checking chapter board member donation permission: {str(e)}")

    # For regular members, check if donation is linked to their donor record
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        try:
            user_member = get_member_name_for_user(user)
            if not user_member:
                return False

            return donor_member == user_member

        except Exception as e:
            frappe.logger().error(f"Error checking donation permission for user {user}: {str(e)}")
            return False

    return False


def get_donation_permission_query(user):
    """Permission query for Donation doctype - limits records to those the user can access

    Filters for:
    - Admins: All records (no filter)
    - Chapter Board Members: Donations for members in their chapters
    - Members: Only their own donation records
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles get access to all records (org-wide)
    if _has_admin_access(user_roles):
        return ""  # No filter needed

    conditions = []

    # Chapter Board Members can see donations for members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        user_member = get_member_name_for_user(user)
        if user_member:
            board_chapters = _get_board_chapters_for_member(user_member)
            if board_chapters:
                chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
                conditions.append(
                    f"""
                    `tabDonation`.donor IN (
                        SELECT d.name
                        FROM `tabDonor` d
                        JOIN `tabChapter Member` cm ON cm.member = d.member
                        WHERE cm.parent IN ({','.join(chapter_names)})
                          AND cm.status = 'Active'
                    )
                """
                )

    # For regular members, limit to donations linked to their donor records
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        user_member = get_member_name_for_user(user)
        if user_member:
            conditions.append(
                f"""
                `tabDonation`.donor IN (
                    SELECT name FROM `tabDonor`
                    WHERE member = {frappe.db.escape(user_member)}
                )
            """
            )

    if conditions:
        return f"({' OR '.join(conditions)})"

    # Users without proper roles see no records
    return "1=0"


def has_address_permission(doc, user=None, permission_type=None):
    """Permission check for Address doctype - allows members to access their own addresses
    and chapter board members to access addresses of members in their chapters"""
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    if _has_admin_access(user_roles):
        return True

    # Handle both doc object and string (address name)
    address_name = doc.name if hasattr(doc, "name") else doc

    # Chapter Board Members can access addresses of members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            # Get member linked to this address via Dynamic Link
            address_member = frappe.db.get_value(
                "Dynamic Link",
                {"parent": address_name, "parenttype": "Address", "link_doctype": "Member"},
                "link_name",
            )

            if address_member and _check_chapter_board_access(user, address_member):
                return True
        except Exception as e:
            frappe.log_error(
                f"Error checking chapter board member address permission: {str(e)}", "Address Permission"
            )

    # Check if this address is linked to the user's own member record
    member_name = get_member_name_for_user(user)

    if member_name:
        # Check if address is linked to this member via Dynamic Link
        link_exists = DocumentExistenceValidator.check_document_exists(
            "Dynamic Link",
            {
                "parent": address_name,
                "parenttype": "Address",
                "link_doctype": "Member",
                "link_name": member_name,
            },
        )

        if link_exists:
            return True

        # Also check if this is the member's primary address
        member_primary_address = frappe.db.get_value("Member", member_name, "primary_address")
        if member_primary_address == address_name:
            return True

    # Fall back to standard Contact-based permissions. has_common_link needs the
    # Address document (it reads doc.links); this function also accepts a bare
    # address name as `doc`, so load the document in that case rather than handing
    # a string to has_common_link (which would raise AttributeError).
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        contact = frappe.get_doc("Contact", contact_name)
        address_doc = doc if hasattr(doc, "links") else frappe.get_doc("Address", address_name)
        return contact.has_common_link(address_doc)

    return False


def get_address_permission_query(user):
    """Permission query for Address - filters to show only member's addresses
    and addresses of members in the user's chapters (for board members)"""
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles see all
    if _has_admin_access(user_roles):
        return ""

    conditions = []

    # Find member by email or user field
    member_name = get_member_name_for_user(user)

    if member_name:
        # Add condition for addresses linked to this member
        escaped_member_name = frappe.db.escape(member_name)
        conditions.append(
            f"""
            `tabAddress`.name in (
                SELECT parent FROM `tabDynamic Link`
                WHERE parenttype = 'Address'
                AND link_doctype = 'Member'
                AND link_name = {escaped_member_name}
            )
        """
        )

    # Chapter Board Members can see addresses of members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles and member_name:
        board_chapters = _get_board_chapters_for_member(member_name)
        if board_chapters:
            chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
            conditions.append(
                f"""
                `tabAddress`.name in (
                    SELECT parent FROM `tabDynamic Link` dl
                    WHERE dl.parenttype = 'Address'
                    AND dl.link_doctype = 'Member'
                    AND dl.link_name IN (
                        SELECT cm.member
                        FROM `tabChapter Member` cm
                        WHERE cm.parent IN ({','.join(chapter_names)})
                          AND cm.status = 'Active'
                    )
                )
            """
            )

    # Also check Contact-based addresses (original ERPNext behavior)
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        escaped_contact_name = frappe.db.escape(contact_name)
        conditions.append(
            f"""
            `tabAddress`.name in (
                SELECT parent FROM `tabDynamic Link`
                WHERE parenttype = 'Address'
                AND link_doctype = 'Contact'
                AND link_name = {escaped_contact_name}
            )
        """
        )

    if conditions:
        return f"({' OR '.join(conditions)})"

    # No member or contact found - no access
    return "1=0"


def get_member_permission_query(user):
    """
    Permission query for Member doctype with chapter-based filtering

    Returns SQL WHERE conditions to filter Member list views based on user roles:
    - Admin roles: No restrictions (see all members)
    - Chapter Board Members: See members in their chapters only
    - Verenigingen Staff: No restrictions (handled by DocType permissions)
    - Verenigingen Members: See own record only
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles see all members
    if _has_admin_access(user_roles):
        return ""

    conditions = []

    # Chapter Board Members can see members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            user_member = get_member_name_for_user(user)
            if user_member:
                board_chapters = _get_board_chapters_for_member(user_member)
                if board_chapters:
                    chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
                    chapters_condition = f"""
                        (`tabMember`.name IN (
                            SELECT DISTINCT cm.member
                            FROM `tabChapter Member` cm
                            JOIN `tabMember` m ON m.name = cm.member
                            WHERE cm.parent IN ({','.join(chapter_names)})
                              AND cm.status = 'Active'
                              AND m.status NOT IN ('Quit', 'Banned', 'Deceased')
                        ))
                    """
                    conditions.append(chapters_condition)
                    frappe.logger().debug(f"Added chapter board member condition for user {user}")

        except Exception as e:
            frappe.log_error(f"Error building chapter board member query: {str(e)}")

    # Members can see their own records
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        # Check both user field and owner field for backward compatibility
        user_member_condition = f"""
            (`tabMember`.user = {frappe.db.escape(user)} OR `tabMember`.owner = {frappe.db.escape(user)})
        """
        conditions.append(user_member_condition)
        frappe.logger().debug(f"Added member self-access condition for user {user}")

    # Combine conditions with OR logic
    if conditions:
        final_condition = f"({' OR '.join(conditions)})"
        frappe.logger().debug(f"Final Member query condition for {user}: {final_condition}")
        return final_condition

    # No access if no conditions matched
    frappe.logger().debug(f"No Member access conditions matched for user {user}")
    return "1=0"


def get_membership_permission_query(user):
    """Permission query for Membership doctype with chapter-based filtering.

    Mirrors get_member_permission_query so Membership list visibility matches the
    scoping already applied to Member, Employee, Donor and Termination Request:
    - Admin roles: no restrictions (see all memberships)
    - Chapter Board Members: see memberships of members in their chapters only
    - Verenigingen Members: see their own membership records only
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles see all memberships
    if _has_admin_access(user_roles):
        return ""

    conditions = []

    # Chapter Board Members can see memberships of members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            user_member = get_member_name_for_user(user)
            if user_member:
                board_chapters = _get_board_chapters_for_member(user_member)
                if board_chapters:
                    chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
                    conditions.append(
                        f"""
                        (`tabMembership`.member IN (
                            SELECT DISTINCT cm.member
                            FROM `tabChapter Member` cm
                            JOIN `tabMember` m ON m.name = cm.member
                            WHERE cm.parent IN ({','.join(chapter_names)})
                              AND cm.status = 'Active'
                              AND m.status NOT IN ('Quit', 'Banned', 'Deceased')
                        ))
                        """
                    )
        except Exception as e:
            frappe.log_error(f"Error building membership chapter board query: {str(e)}")

    # Members can see their own membership records
    if Roles.VERENIGINGEN_MEMBER in user_roles:
        user_member = get_member_name_for_user(user)
        if user_member:
            conditions.append(f"`tabMembership`.member = {frappe.db.escape(user_member)}")

    # Combine conditions with OR logic
    if conditions:
        return f"({' OR '.join(conditions)})"

    # No access if no conditions matched
    return "1=0"


def _employee_board_chapter_condition(user):
    """SQL limiting `tabEmployee` to employees of members in the user's board chapters.

    Returns None when the user holds no active board seat. Shared by
    get_employee_permission_query and has_employee_permission so the list and
    document halves cannot drift apart.
    """
    user_member = get_member_name_for_user(user)
    if not user_member:
        return None

    board_chapters = _get_board_chapters_for_member(user_member)
    if not board_chapters:
        return None

    chapter_names = [frappe.db.escape(ch) for ch in board_chapters]
    return f"""
        (`tabEmployee`.name IN (
            SELECT DISTINCT m.employee
            FROM `tabMember` m
            JOIN `tabChapter Member` cm ON cm.member = m.name
            WHERE cm.parent IN ({','.join(chapter_names)})
              AND cm.status = 'Active'
              AND m.status NOT IN ('Quit', 'Banned', 'Deceased')
              AND m.employee IS NOT NULL
        ))
    """


def has_employee_permission(doc, user=None, ptype=None):
    """Document-level check for Employee. Mirrors get_employee_permission_query.

    The third parameter is named `ptype`, not `permission_type`, because that is the
    keyword frappe actually passes: has_controller_permissions calls
    frappe.call(method, doc=doc, ptype=ptype, ...) and frappe.call's get_newargs drops
    kwargs absent from the callee's signature. Every sibling in this module names it
    `permission_type` and therefore always receives None -- which matters for the ones
    that forward it into _check_service_account_permission, where
    `perm_type = permission_type or "read"` silently evaluates every operation as a
    read. This check ignores the value entirely, but it should not join that family.

    Employee had a permission query and NO has_permission hook. Those two halves
    have disjoint coverage -- frappe/model/db_query.py calls frappe.has_permission
    WITHOUT a doc, so the hook never runs for lists, and frappe.client.get calls
    doc.check_permission() (frappe/client.py:104), which never consults the query --
    so doc-level access fell entirely to DocPerms. fixtures/custom_docperm.json
    grants the ERPNext `Employee` role read with no if_owner, and 8 of the 11 role
    profiles hand out that role, so any volunteer could read any Employee record by
    name (date of birth, personal email, phone, address) while seeing none of them
    in any list view. MEASURED against production config before this fix:
    get_employee_permission_query -> "1=0", frappe.has_permission(read, doc=...) -> True.

    ERPNext's own answer to this is a User Permission per employee-user, which is
    why its DocPerm is deliberately broad. That mechanism cannot cover this app: the
    `Employee` role is granted by role profile to volunteers who have no Employee
    record at all, and a user with no User Permission is unrestricted, so the users
    most exposed are exactly the ones User Permissions would not reach.

    Access:
    - Admin / HR roles: all employees
    - The employee themselves (Employee.user_id): their own record
    - Chapter board members: employees of members in their chapters
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    if _has_admin_access(user_roles, Roles.HR_ADMIN_ROLES | {Roles.HR_USER}):
        return True

    # A document being inserted is not yet in the database, so there is nothing to
    # scope: creation is governed by the create DocPerm (HR roles only, both of which
    # short-circuit above). Test __islocal rather than "name is empty" -- the name is
    # empty today only because Employee uses a naming series and
    # frappe/model/document.py checks create permission BEFORE set_new_name(); a
    # switch to prompt naming, or any caller that assigns doc.name itself, would make
    # the name-based test silently start denying legitimate inserts.
    if not isinstance(doc, str) and doc.get("__islocal"):
        return True

    employee_name = doc if isinstance(doc, str) else getattr(doc, "name", None)
    if not employee_name:
        return True

    # The employee's own record. Employee Self Service depends on this.
    if frappe.db.get_value("Employee", employee_name, "user_id") == user:
        return True

    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        # Deliberately NOT wrapped in try/except. This is an authorization decision:
        # a swallowed failure here returns False, which is indistinguishable from
        # "policy says no" and is exactly the failure mode services/chapter/
        # chapter_utils.py documents at length when it stopped swallowing in
        # get_user_accessible_chapters -- and _employee_board_chapter_condition sits
        # on that same call chain via get_member_name_for_user. A permission check
        # that throws is visible; one that quietly denies is not. It is also unsafe
        # after a deadlock (1213), where the transaction is already dead.
        condition = _employee_board_chapter_condition(user)
        if condition and frappe.db.sql(
            f"SELECT name FROM `tabEmployee` WHERE name = %s AND {condition}", employee_name
        ):
            return True

    return False


def get_employee_permission_query(user):
    """
    Permission query for Employee doctype to restrict VBCM users to employees
    linked to members in their chapters only.

    Returns SQL WHERE conditions:
    - Admin / HR roles: No restrictions (see all employees)
    - The employee themselves: their own record
    - Chapter Board Members: employees linked to members in their chapters
    - Others: no access

    Kept in lockstep with has_employee_permission -- see its docstring for why both
    halves are required.
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles see all employees
    if _has_admin_access(user_roles, Roles.HR_ADMIN_ROLES | {Roles.HR_USER}):
        return ""

    conditions = []

    # An employee can always see their own record. This branch was missing, so the
    # fall-through below denied a plain employee their own record in list views
    # while DocPerms granted them every record by name -- wrong in both directions.
    #
    # Gated on actually having an Employee record so that a user without one still
    # falls through to "1=0" rather than to a condition that matches nothing. Same
    # result, but it keeps "no access" expressed as no access.
    if frappe.db.exists("Employee", {"user_id": user}):
        conditions.append(f"`tabEmployee`.user_id = {frappe.db.escape(user)}")

    # Chapter Board Members can only see employees for members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            board_condition = _employee_board_chapter_condition(user)
            if board_condition:
                conditions.append(board_condition)
        except Exception as e:
            frappe.log_error(f"Error building employee permission query: {str(e)}")

    if conditions:
        return f"({' OR '.join(conditions)})"

    # No access for non-admin, non-VBCM users
    return "1=0"


def can_view_financial_info(doctype, name=None, user=None):
    """Check if user can view financial information for a member"""
    if not user:
        user = frappe.session.user

    # System managers and Verenigingen managers can always view
    if Roles.SYSTEM_MANAGER in frappe.get_roles(user) or Roles.VERENIGINGEN_STAFF in frappe.get_roles(user):
        return True

    # Get the member for this user
    viewer_member = get_member_name_for_user(user)
    if not viewer_member:
        return False

    if not name:
        # Just checking general permission
        return False

    # Allow members to view their own financial info
    target_member = frappe.get_doc("Member", name)
    if target_member.user == user:
        return True

    # Check if viewer is a board member with financial permissions.
    # This is an INTERNAL permission-evaluation lookup: we read the target member's
    # chapter memberships to decide whether the viewer may see their financial info,
    # independent of the viewer's own read rights on Chapter Member.
    #
    # (The previous secure_document_operation wrapper passed a plain dict as its
    # "doc" argument; secure_document_operation builds an operation id from
    # doc.doctype, so a dict raised AttributeError before any query ran — the
    # except below then returned False for EVERY caller, wrongly denying legitimate
    # board members. This is the same defect already fixed in can_terminate_member.)
    try:
        target_member_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": target_member.name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
            limit=1,
        )
    except Exception as e:
        frappe.logger().error(f"Permission check query failed for member {target_member.name}: {str(e)}")
        return False
    if target_member_chapters:
        chapter = frappe.get_doc("Chapter", target_member_chapters[0].parent)
        return chapter.can_view_member_payments(viewer_member)

    # Not permitted
    return False


def check_member_payment_access(member_name, user=None):
    """Check if a user can access payment information for a member"""
    if not user:
        user = frappe.session.user

    # Admins can access all
    if Roles.SYSTEM_MANAGER in frappe.get_roles(user) or Roles.VERENIGINGEN_STAFF in frappe.get_roles(user):
        return True

    # Allow members to view their own payment info
    member = frappe.get_doc("Member", member_name)
    if member.user == user:
        return True

    # Check permission category
    if member.permission_category == "Public":
        return True
    elif member.permission_category == "Admin Only":
        return False

    # For Board Only - check if user is on board with financial permissions
    viewer_member = get_member_name_for_user(user)
    if not viewer_member:
        return False

    # Get member's primary chapter from Chapter Member table
    member_chapters = frappe.get_all(
        "Chapter Member",
        filters={"member": member.name, "enabled": 1},
        fields=["parent"],
        order_by="chapter_join_date desc",
        limit=1,
    )
    if member_chapters:
        chapter = frappe.get_doc("Chapter", member_chapters[0].parent)
        return chapter.can_view_member_payments(viewer_member)

    return False


def can_terminate_member(member_name, user=None):
    """Check if user can terminate a specific member"""
    if not user:
        user = frappe.session.user

    # System managers and Association managers always can
    user_roles = frappe.get_roles(user)
    if _has_admin_access(user_roles, Roles.ADMIN_PAIR):
        return True

    # Get the member being terminated
    try:
        member_doc = frappe.get_doc("Member", member_name)
    except Exception:
        frappe.logger().error(f"Member {member_name} not found")
        return False

    # Get the user making the request as a member
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        frappe.logger().debug(f"User {user} is not a member")
        return False

    # Check if user is a board member of any of the member's chapters.
    # This is an INTERNAL permission-evaluation lookup: we must read the member's
    # chapter memberships to decide whether the requesting user may terminate
    # them, independent of the requesting user's own read rights on Chapter
    # Member. (The previous secure_document_operation wrapper passed a plain dict
    # as the "doc" and gated the lookup behind the requesting user's escalation
    # rights, so board members were wrongly denied — the lookup raised/returned
    # empty and can_terminate_member fell through to False.)
    try:
        # Check ALL chapters the member belongs to, not just the most recent.
        # A board member of ANY of the member's chapters may terminate them;
        # restricting to the single most-recently-joined chapter wrongly denied
        # board members of the member's other chapters.
        member_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_doc.name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
        )
    except Exception as e:
        frappe.logger().error(f"Permission evaluation query failed for member {member_doc.name}: {str(e)}")
        return False
    for member_chapter in member_chapters:
        try:
            chapter_doc = frappe.get_doc("Chapter", member_chapter.parent)
            if chapter_doc.is_board_member(member_name=requesting_member):
                frappe.logger().debug(
                    f"User {user} has board access in member's chapter {member_chapter.parent}"
                )
                return True
        except Exception as e:
            frappe.logger().error(f"Error checking chapter board access: {str(e)}")

    # Check if user is a board member of the national chapter (if configured)
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_board_chapter") and settings.national_board_chapter:
            national_chapter_doc = frappe.get_doc("Chapter", settings.national_board_chapter)
            if national_chapter_doc.is_board_member(member_name=requesting_member):
                frappe.logger().debug(f"User {user} has board access in national chapter")
                return True
    except Exception as e:
        frappe.logger().debug(f"No national chapter configured or error checking: {str(e)}")

    frappe.logger().debug(f"User {user} does not have termination permission for member {member_name}")
    return False


def can_access_termination_functions(user=None):
    """Check if user can access general termination functions"""
    if not user:
        user = frappe.session.user

    # System managers and Association managers always can
    user_roles = frappe.get_roles(user)
    if _has_admin_access(user_roles, Roles.ADMIN_PAIR):
        return True

    # Check if user is a board member of any chapter
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        return False

    # Check for active board positions
    volunteer_records = frappe.get_all("Volunteer", filters={"member": requesting_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["name"],
        )

        if board_positions:
            return True

    return False


def get_chapter_member_permission_query(user):
    """Permission query for Chapter Member doctype"""
    if not user:
        user = frappe.session.user

    # Admin roles get full access
    if _has_admin_access(frappe.get_roles(user)):
        return ""

    # Allow users to see Chapter Member records for:
    # 1. Their own member record
    # 2. Chapters where they have board access
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        return "1=0"  # No access if not a member

    # Get chapters where user has board access
    user_chapters = []
    volunteer_records = frappe.get_all("Volunteer", filters={"member": requesting_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["parent"],
        )

        for position in board_positions:
            if position.parent not in user_chapters:
                user_chapters.append(position.parent)

    # Build permission filter (escape values to prevent SQL injection)
    conditions = [f"`tabChapter Member`.member = {frappe.db.escape(requesting_member)}"]  # Own records

    if user_chapters:
        escaped_chapters = [frappe.db.escape(chapter) for chapter in user_chapters]
        chapter_conditions = " OR ".join(
            [f"`tabChapter Member`.parent = {chapter}" for chapter in escaped_chapters]
        )
        conditions.append(f"({chapter_conditions})")  # Board access chapters

    return f"({' OR '.join(conditions)})"


def get_termination_permission_query(user):
    """
    Permission query for Membership Termination Request doctype
    Chapter Board Members can only see termination requests for their chapter members
    """
    if not user:
        user = frappe.session.user

    # Admin roles get full access
    if _has_admin_access(frappe.get_roles(user)):
        return ""

    # Board members get filtered access based on their chapters
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        return "1=0"  # No access if not a member

    # Get chapters where user has board access
    user_chapters = []
    volunteer_records = frappe.get_all("Volunteer", filters={"member": requesting_member}, fields=["name"])

    for volunteer_record in volunteer_records:
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_record.name, "is_active": 1},
            fields=["parent"],
        )

        for position in board_positions:
            if position.parent not in user_chapters:
                user_chapters.append(position.parent)

    # Add national chapter if configured
    try:
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        if national_chapter and national_chapter not in user_chapters:
            user_chapters.append(national_chapter)
    except Exception:
        pass

    if not user_chapters:
        return "1=0"  # No access if not on any board

    # Return filter to only show termination requests for members in their chapters
    escaped_chapters = [frappe.db.escape(chapter) for chapter in user_chapters]
    chapter_filter = " OR ".join([f"cm.parent = {chapter}" for chapter in escaped_chapters])

    return f"""EXISTS (
        SELECT 1 FROM `tabMember` m
        JOIN `tabChapter Member` cm ON cm.member = m.name
        WHERE m.name = `tabMembership Termination Request`.member
        AND cm.enabled = 1
        AND ({chapter_filter})
    )"""


def has_membership_termination_request_permission(doc, user=None, permission_type=None):
    """
    Direct permission check for Membership Termination Request doctype
    Chapter Board Members can create, read, and write termination requests for their chapter members
    """
    if not user:
        user = frappe.session.user

    frappe.logger().debug(
        f"Checking Membership Termination Request permissions for user {user} with roles {frappe.get_roles(user)}"
    )

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    if _has_admin_access(user_roles):
        return True

    # Get the member being terminated
    termination_member = (
        doc.member
        if hasattr(doc, "member")
        else frappe.db.get_value(
            "Membership Termination Request", doc if isinstance(doc, str) else doc.name, "member"
        )
    )

    if not termination_member:
        frappe.logger().debug(f"Could not determine member from termination request: {doc}")
        return False

    # Chapter Board Members - can access termination requests for members in their chapters
    if Roles.CHAPTER_BOARD_MEMBER in user_roles:
        try:
            has_access = _check_chapter_board_access(user, termination_member)
            frappe.logger().debug(
                f"Chapter board access for user {user} to termination member {termination_member}: {has_access}"
            )
            return has_access
        except Exception as e:
            frappe.log_error(f"Error checking chapter board member termination request permissions: {str(e)}")
            return False

    # No access for other roles
    frappe.logger().debug(f"User {user} has no appropriate role for Membership Termination Request access")
    return False


def get_user_chapter_board_positions(user_member):
    """
    Get all active board positions for a user across all chapters
    Returns list of dicts with chapter_name, chapter_role, and permissions_level
    """
    try:
        positions = frappe.db.sql(
            """
            SELECT
                cbm.parent as chapter_name,
                cbm.chapter_role,
                cr.permissions_level,
                cr.role_name
            FROM `tabChapter Board Member` cbm
            JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE v.member = %s
            AND cbm.is_active = 1
            ORDER BY cbm.parent, cr.permissions_level
        """,
            user_member,
            as_dict=True,
        )
        return positions
    except Exception as e:
        frappe.log_error(f"Error getting user board positions: {str(e)}")
        return []


def assign_chapter_board_role(user_email):
    """
    Automatically assign Chapter Board Member role to users with active board positions
    This should be called when chapter board positions are created/updated
    """
    try:
        # Get user's member record
        user_member = get_member_name_for_user(user_email)
        if not user_member:
            frappe.logger().debug(f"No member record found for user {user_email}")
            return False

        # Check if user has any active board positions
        board_positions = get_user_chapter_board_positions(user_member)

        if board_positions:
            # User has board positions, ensure they have the Chapter Board Member role
            if not DocumentExistenceValidator.check_document_exists(
                "Has Role", {"parent": user_email, "role": Roles.CHAPTER_BOARD_MEMBER}
            ):
                # Add role via direct child table insert
                # NOTE: We use direct insert rather than loading/saving User doc to avoid
                # triggering validation on ALL existing user roles (which causes issues like
                # "Could not find Row #7: Role: Bank Reconciliation User")
                # validator-skip: child-table-direct-insert (intentional - see comment above)
                #
                # SECURITY JUSTIFICATION: ignore_permissions=True is acceptable here because:
                # 1. This is a system operation triggered by business events (board position changes)
                # 2. Only assigns a specific role (Verenigingen Chapter Board Member) - not arbitrary roles
                # 3. Assignment based on validated business logic (active board positions)
                # 4. Comprehensive audit logging below for security compliance
                # 5. Function is not directly exposed as API - called internally from hooks
                frappe.get_doc(
                    {
                        "doctype": "Has Role",
                        "parent": user_email,
                        "parenttype": "User",
                        "parentfield": "roles",
                        "role": Roles.CHAPTER_BOARD_MEMBER,
                    }
                    # Security: Internal hook function - protected by has_permission check on Chapter Board Member doc
                ).insert(ignore_permissions=True)

                # Audit log for security
                frappe.logger().info(
                    f"SECURITY AUDIT: Added Chapter Board Member role to {user_email} "
                    f"based on active board positions - User: {frappe.session.user}"
                )

                # Clear permission cache so new role takes effect immediately
                frappe.clear_cache(user=user_email)

                return True
            else:
                frappe.logger().debug(f"User {user_email} already has Chapter Board Member role")
                return True
        else:
            # User has no board positions, remove the role if they have it
            if DocumentExistenceValidator.check_document_exists(
                "Has Role", {"parent": user_email, "role": Roles.CHAPTER_BOARD_MEMBER}
            ):
                frappe.db.delete("Has Role", {"parent": user_email, "role": Roles.CHAPTER_BOARD_MEMBER})
                frappe.logger().info(f"Removed Chapter Board Member role from {user_email}")
                return True
            else:
                frappe.logger().debug(f"User {user_email} doesn't have Chapter Board Member role to remove")
                return False

    except Exception as e:
        frappe.log_error(f"Error assigning chapter board role to {user_email}: {str(e)}")
        return False


def update_all_chapter_board_roles():
    """
    Update Chapter Board Member roles for all users based on their current board positions
    This can be run as a maintenance function
    """
    try:
        # Get all users with active board positions
        board_members = frappe.db.sql(
            """
            SELECT DISTINCT m.user, m.email
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE cbm.is_active = 1
            AND m.user IS NOT NULL
            AND m.user != ''
        """,
            as_dict=True,
        )

        success_count = 0
        for member in board_members:
            user_email = member.user or member.email
            if user_email and assign_chapter_board_role(user_email):
                success_count += 1

        # Also check for users who should have the role removed
        for user_email in _users_with_chapter_board_role():
            user_member = get_member_name_for_user(user_email)
            if user_member:
                board_positions = get_user_chapter_board_positions(user_member)
                if not board_positions:
                    # User has role but no active board positions
                    assign_chapter_board_role(user_email)  # This will remove the role

        frappe.logger().info(f"Updated chapter board roles for {success_count} users")
        return success_count

    except Exception as e:
        frappe.log_error(f"Error updating all chapter board roles: {str(e)}")
        return 0


def _users_with_chapter_board_role():
    """Return user emails that currently hold the Chapter Board Member role."""
    rows = frappe.db.sql(
        "SELECT parent as user_email FROM `tabHas Role` WHERE role = %s AND parenttype = 'User'",
        Roles.CHAPTER_BOARD_MEMBER,
        as_dict=True,
    )
    return [r.user_email for r in rows]


def get_volunteer_permission_query(user):
    """Permission query for Volunteer doctype - Enhanced for better volunteer management"""
    if not user:
        user = frappe.session.user

    # Admin roles get full access
    user_roles = frappe.get_roles(user)
    if _has_admin_access(user_roles, Roles.VOLUNTEER_ADMIN_ROLES):
        return ""

    # Get requesting user's member record
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        return "1=0"  # No access if not a member

    # Chapter-wide access is gated on the (genuinely-assigned) board/chapter roles.
    # Team-leader access is NOT role-gated — see the team block below.
    chapter_management_roles = [
        Roles.VOLUNTEER_COORDINATOR,
        Roles.CHAPTER_MANAGER,
        Roles.CHAPTER_BOARD_MEMBER,
    ]

    conditions = []

    # Always allow access to own volunteer records (escape to prevent SQL injection)
    conditions.append(f"`tabVolunteer`.member = {frappe.db.escape(requesting_member)}")

    # Board members / chapter managers can access volunteers in their chapters.
    if any(role in user_roles for role in chapter_management_roles):
        # Board members can access volunteers in their chapters (using cached function)
        user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())

        if user_chapter_names:
            # Escape each chapter name (Chapter uses prompt-based naming, so names
            # are user-controlled — raw interpolation would be SQL-injectable).
            # frappe.db.escape() adds the surrounding quotes.
            chapter_list = ", ".join(frappe.db.escape(c) for c in user_chapter_names)
            conditions.append(
                f"""
                `tabVolunteer`.member IN (
                    SELECT cm.member
                    FROM `tabChapter Member` cm
                    WHERE cm.parent IN ({chapter_list})
                      AND cm.enabled = 1
                      AND cm.status = 'Active'
                )
            """
            )

    # Team leaders can access volunteers in teams they lead. This is derived from the
    # team data (an is_team_leader Team Role on an active membership) and is NOT gated
    # on a role: production never assigns the "Team Leader" role, so a role gate would
    # make it dead. The query self-limits — a non-leader's user_teams is empty and
    # nothing is added.
    user_teams = frappe.db.sql(
        """
        SELECT DISTINCT tm.parent
        FROM `tabTeam Member` tm
        JOIN `tabVolunteer` v ON tm.volunteer = v.name
        JOIN `tabTeam Role` tr ON tm.team_role = tr.name
        WHERE v.member = %s AND tm.status = 'Active'
        AND tr.is_team_leader = 1
    """,
        (requesting_member,),
        as_dict=True,
    )

    if user_teams:
        # Escape each team name (Team names are user-controlled via team_name).
        # frappe.db.escape() adds the surrounding quotes.
        team_list = ", ".join(frappe.db.escape(t.parent) for t in user_teams)
        conditions.append(
            f"""
            `tabVolunteer`.name IN (
                SELECT tm.volunteer
                FROM `tabTeam Member` tm
                WHERE tm.parent IN ({team_list}) AND tm.status = 'Active'
            )
        """
        )

    # Join conditions with OR
    if len(conditions) > 1:
        return f"({' OR '.join(conditions)})"
    else:
        return conditions[0] if conditions else "1=0"


def get_team_member_permission_query(user):
    """Permission query for Team Member doctype"""
    if not user:
        user = frappe.session.user

    # Admin roles get full access
    if _has_admin_access(frappe.get_roles(user), Roles.VOLUNTEER_ADMIN_ROLES):
        return ""

    # Get requesting user's member and volunteer records
    requesting_member = get_member_name_for_user(user)
    if not requesting_member:
        return "1=0"  # No access if not a member

    requesting_volunteer = get_volunteer_for_member(requesting_member)
    if not requesting_volunteer:
        return "1=0"  # No access if not a volunteer

    # Users can view team members for teams where they are members themselves
    # This allows team members to see other members of their teams
    user_teams = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabTeam Member`
        WHERE volunteer = %s AND is_active = 1
    """,
        requesting_volunteer,
    )

    if not user_teams:
        return "1=0"  # No access if not a member of any team

    # Escape team names to prevent SQL injection (defense in depth)
    team_names = [frappe.db.escape(team[0]) for team in user_teams]
    team_filter = " OR ".join([f"`tabTeam Member`.parent = {team}" for team in team_names])

    return f"({team_filter})"


def has_expense_claim_permission(doc, user=None, permission_type=None):
    """Permission check for Expense Claim doctype

    Grants access to:
    - Admins (System Manager, HR Manager, Verenigingen Staff, Verenigingen Administrator)
    - Expense Approvers: Can see expense claims for chapters they are board members of
    - Employees: Can see their own expense claims
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles can see all
    if _has_admin_access(user_roles, Roles.HR_ADMIN_ROLES):
        return True

    # Get expense claim chapter
    if isinstance(doc, str):
        expense_chapter = frappe.db.get_value("Expense Claim", doc, "custom_chapter")
        expense_employee = frappe.db.get_value("Expense Claim", doc, "employee")
    else:
        expense_chapter = getattr(doc, "custom_chapter", None)
        expense_employee = getattr(doc, "employee", None)

    # Employees can see their own expense claims
    if expense_employee:
        employee_user = frappe.db.get_value("Employee", expense_employee, "user_id")
        if employee_user == user:
            return True

    # Expense approvers can see expense claims for their chapters
    if Roles.EXPENSE_APPROVER in user_roles:
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        # National expense claims are intentionally not attributed to a chapter
        # (custom_chapter is empty). Their approvers are the board of the configured
        # national_board_chapter, so resolve that as the effective chapter for the
        # access check.
        effective_chapter = expense_chapter
        if not effective_chapter:
            effective_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")

        if effective_chapter:
            accessible_chapters = get_user_accessible_chapters(user)

            # None means admin access (already handled above)
            if accessible_chapters is None:
                return True

            # Check if effective chapter is in accessible list
            if accessible_chapters and effective_chapter in accessible_chapters:
                return True

    return False


def get_expense_claim_permission_query(user):
    """Permission query for Expense Claim doctype - limits records to those the user can access

    Filters for:
    - Admins: All records (no filter)
    - Expense Approvers: Expense claims for chapters they are board members of
    - Employees: Their own expense claims
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles see all
    if _has_admin_access(user_roles, Roles.HR_ADMIN_ROLES):
        return ""

    conditions = []

    # Employees can see their own expense claims
    employee_name = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if employee_name:
        conditions.append(f"`tabExpense Claim`.employee = {frappe.db.escape(employee_name)}")

    # Expense Approvers can see expense claims for their chapters
    if Roles.EXPENSE_APPROVER in user_roles:
        from verenigingen.services.chapter.chapter_utils import get_user_accessible_chapters

        accessible_chapters = get_user_accessible_chapters(user)

        # None means admin access (already handled above)
        if accessible_chapters is None:
            return ""

        # Add chapter filter for accessible chapters
        if accessible_chapters:
            chapter_names = [frappe.db.escape(ch) for ch in accessible_chapters]
            conditions.append(f"`tabExpense Claim`.custom_chapter IN ({','.join(chapter_names)})")

            # National expense claims have no custom_chapter; board members of the
            # configured national_board_chapter approve them, so include unattributed
            # claims for them.
            national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
            if national_chapter and national_chapter in accessible_chapters:
                conditions.append(
                    "(`tabExpense Claim`.custom_chapter IS NULL " "OR `tabExpense Claim`.custom_chapter = '')"
                )

    if conditions:
        return f"({' OR '.join(conditions)})"

    # Users without proper roles see no records
    return "1=0"
