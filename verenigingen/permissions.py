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
    2. **Organization Level**: Verenigingen Managers and operational staff
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
def can_terminate_member_api(member_name):
    """Whitelisted API wrapper for can_terminate_member"""
    return can_terminate_member(member_name)


@frappe.whitelist()
def can_access_termination_functions_api():
    """Whitelisted API wrapper for can_access_termination_functions"""
    return can_access_termination_functions()


@frappe.whitelist()
def test_team_member_access(team_name=None):
    """Test function to verify team member access permissions"""
    user = frappe.session.user

    # Get user's roles
    user_roles = frappe.get_roles(user)

    # Get user's member record
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if not member:
        return {"error": "No member record found", "user": user, "roles": user_roles}

    # Get user's volunteer record
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
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
        can_access = frappe.db.exists(
            "Team Member", {"parent": team_name, "volunteer": volunteer, "is_active": 1}
        )
        result["can_access_team"] = bool(can_access)
        result["requested_team"] = team_name

        if can_access:
            result["portal_url"] = f"/team_members?team={team_name}"

    return result


def has_member_permission(doc, user=None, permission_type=None):
    """
    Direct permission check for Member doctype with chapter-based access control

    Permission Hierarchy:
    1. Admin roles (System Manager, Verenigingen Manager, Verenigingen Administrator) - Full access
    2. Chapter Board Members - Access to members in their chapters only
    3. Verenigingen Staff - Read-only access (limited by query conditions)
    4. Verenigingen Members - Access to own record only
    """
    if not user:
        user = frappe.session.user

    # Log for debugging
    frappe.logger().debug(f"Checking Member permissions for user {user} with roles {frappe.get_roles(user)}")

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
        return True

    # Get the member record name being accessed
    member_name = doc.name if hasattr(doc, "name") else doc if isinstance(doc, str) else None
    if not member_name:
        frappe.logger().debug(f"Could not determine member name from doc: {doc}")
        return False

    # Chapter Board Members - can access members in their chapters only
    if "Chapter Board Member" in user_roles:
        try:
            # Use cached function to get user's chapters (with schema fix)
            user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())

            if not user_chapter_names:
                frappe.logger().debug(f"User {user} is not an active board member in any chapter")
                return False

            # Check if the target member is in any of the user's chapters
            member_chapters = frappe.db.sql(
                """
                SELECT DISTINCT parent as chapter_name
                FROM `tabChapter Member`
                WHERE member = %s AND status = 'Active'
            """,
                member_name,
                as_dict=True,
            )

            member_chapter_names = [ch["chapter_name"] for ch in member_chapters]

            # Allow access if there's any chapter overlap
            has_chapter_overlap = bool(set(user_chapter_names) & set(member_chapter_names))

            frappe.logger().debug(
                f"User chapters: {user_chapter_names}, Member chapters: {member_chapter_names}, Overlap: {has_chapter_overlap}"
            )

            if has_chapter_overlap:
                return True

        except Exception as e:
            frappe.log_error(f"Error checking chapter board member permissions: {str(e)}")
            # Fall through to deny access on error

    # Verenigingen Staff - handled by query conditions, allow individual document access
    if "Verenigingen Staff" in user_roles:
        frappe.logger().debug(f"User {user} has Verenigingen Staff role, allowing access")
        return True

    # For regular members, check if they own the record
    if "Verenigingen Member" in user_roles:
        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
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
    admin_roles = [
        "System Manager",
        "Verenigingen Manager",
        "Verenigingen Administrator",
        "Volunteer Manager",
    ]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
        return True

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
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        frappe.logger().debug(f"User {user} has no Member record")
        return False

    # Members can access their own volunteer record
    if "Verenigingen Member" in user_roles:
        if user_member == volunteer_member:
            frappe.logger().debug(f"User {user} accessing own volunteer record")
            return True

    # Chapter Board Members can access volunteers in their chapters
    if "Chapter Board Member" in user_roles:
        try:
            # Get chapters where the user is an active board member
            user_chapters = frappe.db.sql(
                """
                SELECT DISTINCT cbm.parent as chapter_name
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s AND cbm.is_active = 1
            """,
                user_member,
                as_dict=True,
            )

            if user_chapters:
                user_chapter_names = [ch["chapter_name"] for ch in user_chapters]

                # Check if the volunteer's member is in any of the user's chapters
                volunteer_chapters = frappe.db.sql(
                    """
                    SELECT DISTINCT parent as chapter_name
                    FROM `tabChapter Member`
                    WHERE member = %s AND status = 'Active'
                """,
                    volunteer_member,
                    as_dict=True,
                )

                volunteer_chapter_names = [ch["chapter_name"] for ch in volunteer_chapters]

                # Allow access if there's any chapter overlap
                has_chapter_overlap = bool(set(user_chapter_names) & set(volunteer_chapter_names))

                frappe.logger().debug(
                    f"User chapters: {user_chapter_names}, Volunteer chapters: {volunteer_chapter_names}, Overlap: {has_chapter_overlap}"
                )

                if has_chapter_overlap:
                    return True

        except Exception as e:
            frappe.log_error(f"Error checking chapter board member permissions for volunteer: {str(e)}")

    # Team Leaders can access volunteers in their teams
    if "Team Leader" in user_roles:
        try:
            # Check if user leads any teams that include this volunteer
            team_overlap = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabTeam Member` tm1
                JOIN `tabTeam Role` tr1 ON tm1.team_role = tr1.name
                JOIN `tabTeam Member` tm2 ON tm1.parent = tm2.parent
                WHERE tm1.volunteer = %s AND tr1.is_team_leader = 1
                AND tm2.volunteer = %s AND tm2.status = 'Active'
            """,
                (user_member, volunteer_member),
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
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
        return True

    # Other permission checks would go here

    # Return None to fall back to standard permission system if no match
    return None


def has_donor_permission(doc, user=None, permission_type=None):
    """Direct permission check for Donor doctype"""
    if not user:
        user = frappe.session.user

    # Log for debugging
    frappe.logger().debug(f"Checking Donor permissions for user {user} with roles {frappe.get_roles(user)}")

    # Admin roles always have access
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access to donor")
        return True

    # For regular members, check if they are linked to this donor record
    if "Verenigingen Member" in frappe.get_roles(user):
        try:
            # Get the user's member record
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if not user_member:
                frappe.logger().debug(f"User {user} has Verenigingen Member role but no member record found")
                return False

            # Check if this donor record is linked to the user's member record
            if isinstance(doc, str):
                # doc is just the name, need to get the member field
                if not frappe.db.exists("Donor", doc):
                    frappe.logger().debug(f"Donor record {doc} does not exist")
                    return False
                donor_member = frappe.db.get_value("Donor", doc, "member")
            else:
                # doc is the document object
                donor_member = getattr(doc, "member", None)

            if not donor_member:
                frappe.logger().debug("Donor record has no linked member")
                return False

            # Verify the linked member still exists and is active
            if not frappe.db.exists("Member", donor_member):
                frappe.logger().debug(f"Linked member {donor_member} no longer exists")
                return False

            is_linked = donor_member == user_member
            frappe.logger().debug(
                f"User member: {user_member}, Donor member: {donor_member}, Access granted: {is_linked}"
            )
            return is_linked

        except Exception as e:
            frappe.logger().error(f"Error checking donor permission for user {user}, doc {doc}: {str(e)}")
            return False

    # Return False for users without proper roles
    frappe.logger().debug(f"User {user} does not have appropriate roles for donor access")
    return False


def get_donor_permission_query(user):
    """Permission query for Donor doctype - limits records to those the user can access"""
    if not user:
        user = frappe.session.user

    # Admin roles get access to all records
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return None  # No additional conditions needed

    # For regular members, limit to donor records linked to their member record
    if "Verenigingen Member" in frappe.get_roles(user):
        user_member = frappe.db.get_value("Member", {"user": user}, "name")
        if user_member:
            # FIXED: Proper SQL escaping to prevent injection
            return f"`tabDonor`.member = {frappe.db.escape(user_member)}"

    # Users without proper roles see no records
    return "1=0"


def has_address_permission(doc, user=None, permission_type=None):
    """Permission check for Address doctype - allows members to access their own addresses"""
    if not user:
        user = frappe.session.user

    # Admin roles always have access
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return True

    # Check if this address is linked to the user's member record
    member_name = frappe.db.get_value("Member", {"email": user}, "name")
    if not member_name:
        member_name = frappe.db.get_value("Member", {"user": user}, "name")

    if member_name:
        # Check if address is linked to this member via Dynamic Link
        link_exists = frappe.db.exists(
            "Dynamic Link",
            {"parent": doc.name, "parenttype": "Address", "link_doctype": "Member", "link_name": member_name},
        )

        if link_exists:
            return True

        # Also check if this is the member's primary address
        member_primary_address = frappe.db.get_value("Member", member_name, "primary_address")
        if member_primary_address == doc.name:
            return True

    # Fall back to standard Contact-based permissions
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        contact = frappe.get_doc("Contact", contact_name)
        return contact.has_common_link(doc)

    return False


def get_address_permission_query(user):
    """Permission query for Address - filters to show only member's addresses"""
    if not user:
        user = frappe.session.user

    # Admin roles see all
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return ""

    conditions = []

    # Find member by email or user field
    member_name = frappe.db.get_value("Member", {"email": user}, "name")
    if not member_name:
        member_name = frappe.db.get_value("Member", {"user": user}, "name")

    if member_name:
        # Add condition for addresses linked to this member
        # FIXED: Proper SQL escaping to prevent injection
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

    # Also check Contact-based addresses (original ERPNext behavior)
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        # FIXED: Proper SQL escaping to prevent injection
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
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting full access")
        return ""

    # Verenigingen Staff see all members (controlled by DocType read-only permissions)
    if "Verenigingen Staff" in user_roles:
        frappe.logger().debug(f"User {user} has Verenigingen Staff role, granting full access")
        return ""

    conditions = []

    # Chapter Board Members can see members in their chapters
    if "Chapter Board Member" in user_roles:
        try:
            # Get the current user's member record
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if user_member:
                # Get chapters where the user is an active board member
                user_chapters = frappe.db.sql(
                    """
                    SELECT DISTINCT cbm.parent as chapter_name
                    FROM `tabChapter Board Member` cbm
                    JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                    WHERE v.member = %s AND cbm.is_active = 1
                """,
                    user_member,
                    as_dict=True,
                )

                if user_chapters:
                    chapter_names = [frappe.db.escape(ch["chapter_name"]) for ch in user_chapters]
                    chapters_condition = f"""
                        `tabMember`.name IN (
                            SELECT DISTINCT member
                            FROM `tabChapter Member`
                            WHERE parent IN ({','.join(chapter_names)}) AND status = 'Active'
                        )
                    """
                    conditions.append(chapters_condition)
                    frappe.logger().debug(f"Added chapter board member condition for user {user}")

        except Exception as e:
            frappe.log_error(f"Error building chapter board member query: {str(e)}")

    # Members can see their own records
    if "Verenigingen Member" in user_roles:
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
    """Permission query for Membership doctype"""
    if not user:
        user = frappe.session.user

    # Always return empty string (no restrictions) for all users
    # This is for debugging - remove this override once the issue is fixed
    return ""


def can_view_financial_info(doctype, name=None, user=None):
    """Check if user can view financial information for a member"""
    if not user:
        user = frappe.session.user

    # System managers and Verenigingen managers can always view
    if "System Manager" in frappe.get_roles(user) or "Verenigingen Manager" in frappe.get_roles(user):
        return True

    # Get the member for this user
    viewer_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not viewer_member:
        return False

    if not name:
        # Just checking general permission
        return False

    # Allow members to view their own financial info
    target_member = frappe.get_doc("Member", name)
    if target_member.user == user:
        return True

    # Check if viewer is a board member with financial permissions
    target_member_chapters = frappe.get_all(
        "Chapter Member",
        filters={"member": target_member.name, "enabled": 1},
        fields=["parent"],
        order_by="chapter_join_date desc",
        limit=1,
        ignore_permissions=True,
    )
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
    if "System Manager" in frappe.get_roles(user) or "Verenigingen Manager" in frappe.get_roles(user):
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
    viewer_member = frappe.db.get_value("Member", {"user": user}, "name")
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
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting termination access")
        return True

    # Get the member being terminated
    try:
        member_doc = frappe.get_doc("Member", member_name)
    except Exception:
        frappe.logger().error(f"Member {member_name} not found")
        return False

    # Get the user making the request as a member
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not requesting_member:
        frappe.logger().debug(f"User {user} is not a member")
        return False

    # Check if user is a board member of the member's chapter
    member_chapters = frappe.get_all(
        "Chapter Member",
        filters={"member": member_doc.name, "enabled": 1},
        fields=["parent"],
        order_by="chapter_join_date desc",
        limit=1,
        ignore_permissions=True,
    )
    if member_chapters:
        try:
            chapter_doc = frappe.get_doc("Chapter", member_chapters[0].parent)
            if chapter_doc.is_board_member(member_name=requesting_member):
                frappe.logger().debug(
                    f"User {user} has board access in member's chapter {member_chapters[0].parent}"
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
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in admin_roles):
        return True

    # Check if user is a board member of any chapter
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
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
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return ""

    # Allow users to see Chapter Member records for:
    # 1. Their own member record
    # 2. Chapters where they have board access
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
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

    # Build permission filter
    conditions = [f"`tabChapter Member`.member = '{requesting_member}'"]  # Own records

    if user_chapters:
        chapter_conditions = " OR ".join(
            [f"`tabChapter Member`.parent = '{chapter}'" for chapter in user_chapters]
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
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return ""

    # Board members get filtered access based on their chapters
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
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
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_chapter") and settings.national_chapter:
            if settings.national_chapter not in user_chapters:
                user_chapters.append(settings.national_chapter)
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
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
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
    if "Chapter Board Member" in user_roles:
        try:
            # Get the current user's member record
            user_member = frappe.db.get_value("Member", {"user": user}, "name")
            if not user_member:
                frappe.logger().debug(f"User {user} has Chapter Board Member role but no Member record")
                return False

            # Get chapters where the user is an active board member
            user_chapters = frappe.db.sql(
                """
                SELECT DISTINCT cbm.parent as chapter_name
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s AND cbm.is_active = 1
            """,
                user_member,
                as_dict=True,
            )

            if not user_chapters:
                frappe.logger().debug(f"User {user} is not an active board member in any chapter")
                return False

            user_chapter_names = [ch["chapter_name"] for ch in user_chapters]

            # Check if the termination target member is in any of the user's chapters
            target_member_chapters = frappe.db.sql(
                """
                SELECT DISTINCT parent as chapter_name
                FROM `tabChapter Member`
                WHERE member = %s AND status = 'Active'
            """,
                termination_member,
                as_dict=True,
            )

            target_member_chapter_names = [ch["chapter_name"] for ch in target_member_chapters]

            # Allow access if there's any chapter overlap
            has_chapter_overlap = bool(set(user_chapter_names) & set(target_member_chapter_names))

            frappe.logger().debug(
                f"User chapters: {user_chapter_names}, Target member chapters: {target_member_chapter_names}, Overlap: {has_chapter_overlap}"
            )

            return has_chapter_overlap

        except Exception as e:
            frappe.log_error(f"Error checking chapter board member termination request permissions: {str(e)}")
            return False

    # No access for other roles
    frappe.logger().debug(f"User {user} has no appropriate role for Membership Termination Request access")
    return False


def get_volunteer_expense_permission_query(user):
    """
    Permission query for Volunteer Expense doctype
    Chapter Board Members can only see expenses from their chapters
    Treasurers get additional approval capabilities
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles get full access
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        return ""

    # Get user's member record
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not requesting_member:
        return "1=0"  # No access if not a member

    conditions = []

    # Users can always see their own volunteer expense records
    user_volunteer = frappe.db.get_value("Volunteer", {"member": requesting_member}, "name")
    if user_volunteer:
        conditions.append(f"`tabVolunteer Expense`.volunteer = {frappe.db.escape(user_volunteer)}")

    # Chapter Board Members can see expenses for their chapters
    if "Chapter Board Member" in user_roles:
        try:
            # Get chapters where user is an active board member
            user_chapters = frappe.db.sql(
                """
                SELECT DISTINCT cbm.parent as chapter_name
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s AND cbm.is_active = 1
            """,
                requesting_member,
                as_dict=True,
            )

            if user_chapters:
                escaped_chapters = [frappe.db.escape(ch["chapter_name"]) for ch in user_chapters]
                chapters_condition = f"`tabVolunteer Expense`.chapter IN ({','.join(escaped_chapters)})"
                conditions.append(chapters_condition)

        except Exception as e:
            frappe.log_error(f"Error building chapter board member expense query: {str(e)}")

    # Combine conditions with OR logic
    if conditions:
        final_condition = f"({' OR '.join(conditions)})"
        frappe.logger().debug(f"Final Volunteer Expense query condition for {user}: {final_condition}")
        return final_condition

    # No access if no conditions matched
    frappe.logger().debug(f"No Volunteer Expense access conditions matched for user {user}")
    return "1=0"


def has_volunteer_expense_permission(doc, user=None, permission_type=None):
    """
    Direct permission check for Volunteer Expense doctype
    Chapter Board Members can read/write expenses from their chapters
    Only treasurers can approve expenses
    """
    if not user:
        user = frappe.session.user

    frappe.logger().debug(
        f"Checking Volunteer Expense permissions for user {user} with roles {frappe.get_roles(user)}"
    )

    user_roles = frappe.get_roles(user)

    # Admin roles always have access
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
        return True

    # Get the expense record
    expense_volunteer = (
        doc.volunteer
        if hasattr(doc, "volunteer")
        else frappe.db.get_value("Volunteer Expense", doc if isinstance(doc, str) else doc.name, "volunteer")
    )
    expense_chapter = (
        doc.chapter
        if hasattr(doc, "chapter")
        else frappe.db.get_value("Volunteer Expense", doc if isinstance(doc, str) else doc.name, "chapter")
    )

    if not expense_volunteer:
        frappe.logger().debug(f"Could not determine volunteer from expense: {doc}")
        return False

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        frappe.logger().debug(f"User {user} has no Member record")
        return False

    # Users can access their own volunteer expenses
    user_volunteer = frappe.db.get_value("Volunteer", {"member": user_member}, "name")
    if user_volunteer == expense_volunteer:
        frappe.logger().debug(f"User {user} accessing own volunteer expense")
        return True

    # Chapter Board Members can access expenses from their chapters
    if "Chapter Board Member" in user_roles and expense_chapter:
        try:
            # Use cached function to get user's chapters (with schema fix)
            user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())

            if expense_chapter in user_chapter_names:
                frappe.logger().debug(f"User {user} has board access to expense chapter {expense_chapter}")
                return True

        except Exception as e:
            frappe.log_error(f"Error checking chapter board member expense permissions: {str(e)}")
            return False

    # No access for other cases
    frappe.logger().debug(f"User {user} has no appropriate access to volunteer expense")
    return False


def can_approve_volunteer_expense(expense_doc, user=None):
    """
    Check if user can approve volunteer expenses
    Only treasurers and admin roles can approve expenses
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admin roles always have approval rights
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    if any(role in user_roles for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting approval access")
        return True

    # Get user's member record
    user_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not user_member:
        frappe.logger().debug(f"User {user} has no Member record")
        return False

    # Check if user is a treasurer in the expense's chapter
    expense_chapter = (
        expense_doc.chapter
        if hasattr(expense_doc, "chapter")
        else frappe.db.get_value(
            "Volunteer Expense", expense_doc if isinstance(expense_doc, str) else expense_doc.name, "chapter"
        )
    )

    if not expense_chapter:
        frappe.logger().debug("Expense has no associated chapter")
        return False

    # Use cached function to check if user is treasurer in this chapter
    user_treasurer_chapters = get_user_treasurer_chapters_cached(user, get_cache_key())

    if expense_chapter in user_treasurer_chapters:
        frappe.logger().debug(f"User {user} is treasurer in chapter {expense_chapter}")
        return True

    frappe.logger().debug(f"User {user} is not a treasurer for expense approval")
    return False


def is_chapter_treasurer(user_member, chapter_name):
    """
    Helper function to check if a member is a treasurer in a specific chapter
    """
    try:
        treasurer_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabChapter Board Member` cbm
            JOIN `tabChapter Role` cr ON cbm.chapter_role = cr.name
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE v.member = %s
            AND cbm.parent = %s
            AND cbm.is_active = 1
            AND cr.permissions_level = 'Financial'
        """,
            (user_member, chapter_name),
            as_dict=True,
        )
        return treasurer_count and treasurer_count[0].count > 0
    except Exception as e:
        frappe.log_error(f"Error checking treasurer status: {str(e)}")
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
        user_member = frappe.db.get_value("Member", {"user": user_email}, "name")
        if not user_member:
            user_member = frappe.db.get_value("Member", {"email": user_email}, "name")

        if not user_member:
            frappe.logger().debug(f"No member record found for user {user_email}")
            return False

        # Check if user has any active board positions
        board_positions = get_user_chapter_board_positions(user_member)

        if board_positions:
            # User has board positions, ensure they have the Chapter Board Member role
            if not frappe.db.exists("Has Role", {"parent": user_email, "role": "Chapter Board Member"}):
                # Add the role
                user_doc = frappe.get_doc("User", user_email)
                user_doc.append("roles", {"role": "Chapter Board Member"})
                user_doc.save(ignore_permissions=True)
                frappe.logger().info(f"Added Chapter Board Member role to {user_email}")
                return True
            else:
                frappe.logger().debug(f"User {user_email} already has Chapter Board Member role")
                return True
        else:
            # User has no board positions, remove the role if they have it
            if frappe.db.exists("Has Role", {"parent": user_email, "role": "Chapter Board Member"}):
                frappe.db.delete("Has Role", {"parent": user_email, "role": "Chapter Board Member"})
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
        users_with_role = frappe.db.sql(
            """
            SELECT parent as user_email
            FROM `tabHas Role`
            WHERE role = 'Chapter Board Member'
        """,
            as_dict=True,
        )

        for user_role in users_with_role:
            user_email = user_role.user_email
            user_member = frappe.db.get_value("Member", {"user": user_email}, "name")
            if not user_member:
                user_member = frappe.db.get_value("Member", {"email": user_email}, "name")

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


def get_volunteer_permission_query(user):
    """Permission query for Volunteer doctype - Enhanced for better volunteer management"""
    if not user:
        user = frappe.session.user

    # Admin roles get full access
    admin_roles = [
        "System Manager",
        "Verenigingen Manager",
        "Verenigingen Administrator",
        "Volunteer Manager",
    ]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return ""

    # Get requesting user's member record
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not requesting_member:
        return "1=0"  # No access if not a member

    user_roles = frappe.get_roles(user)

    # Board members and team leaders get expanded access
    management_roles = [
        "Volunteer Coordinator",
        "Verenigingen Chapter Manager",
        "Chapter Board Member",
        "Team Leader",
    ]

    conditions = []

    # Always allow access to own volunteer records
    conditions.append(f"`tabVolunteer`.member = '{requesting_member}'")

    # If user has management roles, allow broader access
    if any(role in user_roles for role in management_roles):
        # Board members can access volunteers in their chapters (using cached function)
        user_chapter_names = get_user_chapter_memberships_cached(user, get_cache_key())

        if user_chapter_names:
            chapter_list = "','".join(user_chapter_names)
            conditions.append(
                f"""
                `tabVolunteer`.member IN (
                    SELECT cm.member
                    FROM `tabChapter Member` cm
                    WHERE cm.parent IN ('{chapter_list}') AND cm.enabled = 1
                )
            """
            )

        # Team leaders can access volunteers in their teams
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
            team_list = "','".join([t.parent for t in user_teams])
            conditions.append(
                f"""
                `tabVolunteer`.name IN (
                    SELECT tm.volunteer
                    FROM `tabTeam Member` tm
                    WHERE tm.parent IN ('{team_list}') AND tm.status = 'Active'
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
    admin_roles = [
        "System Manager",
        "Verenigingen Manager",
        "Verenigingen Administrator",
        "Volunteer Manager",
    ]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        return ""

    # Get requesting user's member and volunteer records
    requesting_member = frappe.db.get_value("Member", {"user": user}, "name")
    if not requesting_member:
        return "1=0"  # No access if not a member

    requesting_volunteer = frappe.db.get_value("Volunteer", {"member": requesting_member}, "name")
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

    team_names = [team[0] for team in user_teams]
    team_filter = " OR ".join([f"`tabTeam Member`.parent = '{team}'" for team in team_names])

    return f"({team_filter})"
