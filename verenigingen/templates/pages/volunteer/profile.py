import frappe
from frappe import _

from verenigingen.utils.member_utils import require_login


def get_context(context):
    """Get context for volunteer profile page"""
    require_login()

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Volunteer Profile")

    # Get current user's volunteer record
    volunteer = get_user_volunteer_record()
    if not volunteer:
        context.error_message = _(
            "No volunteer record found for your account. Please contact your chapter administrator."
        )
        return context

    context.volunteer = volunteer

    # Get detailed volunteer profile info
    context.volunteer_profile = get_volunteer_profile(volunteer.name)

    # Get volunteer's organizations
    context.organizations = get_volunteer_organizations(volunteer.name)

    return context


def get_user_volunteer_record():
    """Get volunteer record for current user"""
    user_email = frappe.session.user

    # First try to find by linked member
    member = frappe.db.get_value("Member", {"email": user_email}, "name")
    if member:
        volunteer = frappe.db.get_value(
            "Volunteer", {"member": member}, ["name", "volunteer_name"], as_dict=True
        )
        if volunteer:
            return volunteer

    # Try to find volunteer directly by email
    volunteer = frappe.db.get_value(
        "Volunteer", {"email": user_email}, ["name", "volunteer_name"], as_dict=True
    )
    if volunteer:
        return volunteer

    return None


def get_volunteer_profile(volunteer_name):
    """Get detailed volunteer profile information"""
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

    profile = {
        "name": volunteer_doc.name,
        "volunteer_name": volunteer_doc.volunteer_name,
        "status": getattr(volunteer_doc, "status", "Active"),
        "joined_date": getattr(volunteer_doc, "creation", None),
        "email": None,
        "phone": getattr(volunteer_doc, "phone", None),
        "member_info": None,
    }

    # Get email from member or volunteer record
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        member = frappe.get_doc("Member", volunteer_doc.member)
        profile["email"] = member.email
        profile["member_info"] = {
            "member_id": member.member_id,
            "full_name": member.full_name,
            "membership_status": getattr(member, "status", "Active"),
        }
    else:
        profile["email"] = getattr(volunteer_doc, "email", None)

    # Get interests
    profile["interests"] = frappe.get_all(
        "Volunteer Interest Area",
        filters={"parent": volunteer_name},
        fields=["interest_area"],
        order_by="interest_area",
    )

    # Get skills
    profile["skills"] = frappe.get_all(
        "Volunteer Skill",
        filters={"parent": volunteer_name},
        fields=["skill_category", "volunteer_skill", "proficiency_level"],
        order_by="skill_category, volunteer_skill",
    )

    return profile


def get_volunteer_organizations(volunteer_name):
    """Get chapters and teams the volunteer belongs to"""
    organizations = {"chapters": [], "teams": []}

    # Get chapters through member relationship
    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
    if hasattr(volunteer_doc, "member") and volunteer_doc.member:
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"member": volunteer_doc.member, "enabled": 1},
            fields=["parent", "chapter_join_date"],
        )

        for cm in chapter_members:
            # cm.parent IS the Chapter's name (Chapter Member rows are parented by
            # the Chapter), so no lookup is needed to obtain the Chapter's name.
            organizations["chapters"].append(
                {
                    "name": cm.parent,
                    "chapter_name": cm.parent,
                    "join_date": cm.chapter_join_date,
                }
            )

    # Get teams where volunteer is active
    team_members = frappe.get_all(
        "Team Member",
        filters={"volunteer": volunteer_name, "status": "Active"},
        fields=["parent", "role_type", "from_date"],
    )

    for tm in team_members:
        # tm.parent IS the Team's name (Team Member rows are parented by the
        # Team), so no lookup is needed to obtain the Team's name.
        organizations["teams"].append(
            {
                "name": tm.parent,
                "team_name": tm.parent,
                "role": tm.role_type,
                "joined_date": tm.from_date,
            }
        )

    return organizations
