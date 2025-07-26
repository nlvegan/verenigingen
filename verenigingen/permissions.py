import frappe


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
    """Direct permission check for Member doctype"""
    if not user:
        user = frappe.session.user

    # Log for debugging
    frappe.logger().debug(f"Checking Member permissions for user {user} with roles {frappe.get_roles(user)}")

    # Admin roles always have access
    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting access")
        return True

    # Other permission checks would go here

    # Return None to fall back to standard permission system if no match
    return None


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
        # escaped_member_name = member_name.replace("'", "''")  # Simple SQL escaping
        conditions.append(
            """
            `tabAddress`.name in (
                SELECT parent FROM `tabDynamic Link`
                WHERE parenttype = 'Address'
                AND link_doctype = 'Member'
                AND link_name = '{escaped_member_name}'
            )
        """
        )

    # Also check Contact-based addresses (original ERPNext behavior)
    contact_name = frappe.db.get_value("Contact", {"email_id": user}, "name")
    if contact_name:
        # escaped_contact_name = contact_name.replace("'", "''")  # Simple SQL escaping
        conditions.append(
            """
            `tabAddress`.name in (
                SELECT parent FROM `tabDynamic Link`
                WHERE parenttype = 'Address'
                AND link_doctype = 'Contact'
                AND link_name = '{escaped_contact_name}'
            )
        """
        )

    if conditions:
        return f"({' OR '.join(conditions)})"

    # No member or contact found - no access
    return "1=0"


def get_member_permission_query(user):
    """Permission query for Member doctype"""
    if not user:
        user = frappe.session.user

    admin_roles = ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]
    if any(role in frappe.get_roles(user) for role in admin_roles):
        frappe.logger().debug(f"User {user} has admin role, granting full access")
        return ""

    # Other permission logic would go here

    # For debugging purposes, grant access to all
    return ""


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
            if chapter_doc.user_has_board_access(requesting_member):
                frappe.logger().debug(
                    f"User {user} has board access in member's chapter {member_chapters[0].parent}"
                )
                return True
        except Exception as e:
            frappe.logger().error(f"Error checking chapter board access: {str(e)}")

    # Check if user is a board member of the national chapter (if configured)
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "national_chapter") and settings.national_chapter:
            national_chapter_doc = frappe.get_doc("Chapter", settings.national_chapter)
            if national_chapter_doc.user_has_board_access(requesting_member):
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
    """Permission query for Membership Termination Request doctype"""
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
    # chapter_filter = " OR ".join([f"cm.parent = '{chapter}'" for chapter in user_chapters])
    return """EXISTS (
        SELECT 1 FROM `tabMember` m
        JOIN `tabChapter Member` cm ON cm.member = m.name
        WHERE m.name = `tabMembership Termination Request`.member
        AND cm.enabled = 1
        AND ({chapter_filter})
    )"""


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
    management_roles = ["Volunteer Coordinator", "Chapter Manager", "Chapter Board Member", "Team Leader"]

    conditions = []

    # Always allow access to own volunteer records
    conditions.append(f"`tabVolunteer`.member = '{requesting_member}'")

    # If user has management roles, allow broader access
    if any(role in user_roles for role in management_roles):
        # Board members can access volunteers in their chapters
        user_chapters = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.user = %s AND cbm.is_active = 1
        """,
            (user,),
            as_dict=True,
        )

        if user_chapters:
            chapter_list = "','".join([c.parent for c in user_chapters])
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
            WHERE v.member = %s AND tm.status = 'Active'
            AND tm.role_type = 'Leader'
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
