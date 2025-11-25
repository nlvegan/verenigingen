# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class EventContactCampaign(Document):
    def validate(self):
        self.update_progress_stats()
        self.validate_dates()
        self.set_default_owner()

    def validate_dates(self):
        """Validate that end_date is after start_date."""
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                frappe.throw(_("Outreach End Date cannot be before Start Date"))

    def set_default_owner(self):
        """Set default owner_reference based on owner_type if not set."""
        if not self.owner_reference:
            if self.owner_type == "Chapter" and self.chapter:
                self.owner_reference = self.chapter
            elif self.owner_type == "User":
                self.owner_reference = frappe.session.user

    def update_progress_stats(self):
        """Calculate and update progress statistics based on contact_list."""
        if not self.contact_list:
            self.total_members = 0
            self.members_contacted = 0
            self.contact_progress = 0
            self.members_attending = 0
            self.members_not_attending = 0
            self.members_maybe = 0
            self.members_pending = 0
            return

        self.total_members = len(self.contact_list)
        self.members_contacted = sum(1 for m in self.contact_list if m.contacted)

        if self.total_members > 0:
            self.contact_progress = (self.members_contacted / self.total_members) * 100
        else:
            self.contact_progress = 0

        # Count responses
        self.members_attending = sum(
            1 for m in self.contact_list if m.response == "Will Attend"
        )
        self.members_not_attending = sum(
            1 for m in self.contact_list if m.response == "Cannot Attend"
        )
        self.members_maybe = sum(
            1 for m in self.contact_list if m.response == "Maybe"
        )
        self.members_pending = sum(
            1 for m in self.contact_list
            if m.response in ("No Response", "Left Message") or not m.response
        )

    def get_progress_dashboard_html(self):
        """Generate HTML for the progress dashboard."""
        total = cint(self.total_members) or 0
        contacted = cint(self.members_contacted) or 0
        progress = self.contact_progress or 0
        attending = cint(self.members_attending) or 0
        not_attending = cint(self.members_not_attending) or 0
        maybe = cint(self.members_maybe) or 0
        pending = cint(self.members_pending) or 0

        if total == 0:
            return """
            <div class="progress-dashboard" style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 15px;">
                <p style="color: #6c757d; margin: 0;">
                    <strong>No members in contact list.</strong><br>
                    Click "Import Contactable Members" to populate the list.
                </p>
            </div>
            """

        # Calculate progress bar width
        progress_width = min(progress, 100)

        return f"""
        <div class="progress-dashboard" style="padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 15px;">
            <div style="margin-bottom: 10px;">
                <strong>Contact Progress: {contacted}/{total} ({progress:.0f}%)</strong>
            </div>
            <div style="background: #e9ecef; border-radius: 4px; height: 20px; margin-bottom: 15px;">
                <div style="background: #28a745; height: 100%; border-radius: 4px; width: {progress_width}%; transition: width 0.3s;"></div>
            </div>
            <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                <span style="color: #28a745;"><strong>{attending}</strong> Will Attend</span>
                <span style="color: #dc3545;"><strong>{not_attending}</strong> Cannot Attend</span>
                <span style="color: #ffc107;"><strong>{maybe}</strong> Maybe</span>
                <span style="color: #6c757d;"><strong>{pending}</strong> No Response</span>
            </div>
        </div>
        """


@frappe.whitelist()
def get_contactable_members(chapter: str) -> list[dict]:
    """
    Get all contactable members for a chapter.

    Returns members where:
    - Member is active in the chapter (Chapter Member.status = 'Active', enabled = 1)
    - Member's overall status is 'Active'
    - Member has accepted optional communications (accepts_optional_communications = 1 or NULL)
    """
    if not chapter:
        frappe.throw(_("Please select a chapter first"))

    members = frappe.db.sql(
        """
        SELECT DISTINCT
            m.name as member,
            m.full_name as member_name,
            m.email,
            m.contact_number as phone
        FROM `tabMember` m
        INNER JOIN `tabChapter Member` cm ON cm.member = m.name
        INNER JOIN `tabChapter` c ON cm.parent = c.name
        WHERE c.name = %(chapter)s
            AND cm.status = 'Active'
            AND cm.enabled = 1
            AND m.status = 'Active'
            AND (m.accepts_optional_communications = 1 OR m.accepts_optional_communications IS NULL)
        ORDER BY m.full_name
        """,
        {"chapter": chapter},
        as_dict=True,
    )

    return members


@frappe.whitelist()
def import_contactable_members(docname: str) -> dict:
    """
    Import contactable members into an Event Contact Campaign.

    Args:
        docname: The name of the Event Contact Campaign document

    Returns:
        dict with status and count of members added
    """
    doc = frappe.get_doc("Event Contact Campaign", docname)

    if not doc.chapter:
        frappe.throw(_("Please select a chapter first"))

    # Get existing members in the contact list to avoid duplicates
    existing_members = {row.member for row in doc.contact_list}

    # Get contactable members
    members = get_contactable_members(doc.chapter)

    # Filter out already existing members
    new_members = [m for m in members if m["member"] not in existing_members]

    if not new_members:
        if members:
            return {
                "status": "info",
                "message": _("All {0} contactable members are already in the list").format(
                    len(members)
                ),
                "added": 0,
            }
        else:
            return {
                "status": "warning",
                "message": _("No contactable members found for this chapter"),
                "added": 0,
            }

    # Add new members to the contact list
    for member_data in new_members:
        doc.append(
            "contact_list",
            {
                "member": member_data["member"],
                "member_name": member_data["member_name"],
                "email": member_data["email"],
                "phone": member_data["phone"],
                "contacted": 0,
                "contact_method": "Not Contacted",
                "response": "No Response",
            },
        )

    doc.save()

    return {
        "status": "success",
        "message": _("Added {0} members to the contact list").format(len(new_members)),
        "added": len(new_members),
        "total": len(doc.contact_list),
    }


@frappe.whitelist()
def get_progress_dashboard(docname: str) -> str:
    """Get the progress dashboard HTML for a campaign."""
    doc = frappe.get_doc("Event Contact Campaign", docname)
    return doc.get_progress_dashboard_html()


@frappe.whitelist()
def get_available_volunteers(docname: str) -> list[dict]:
    """
    Get available volunteers based on the campaign's owner_type.

    - If owner_type is 'Chapter': Returns chapter board members
    - If owner_type is 'Team': Returns team members
    - If owner_type is 'User': Returns empty list (single user campaigns)

    Args:
        docname: The name of the Event Contact Campaign document

    Returns:
        list of dicts with volunteer info (name, volunteer_name)
    """
    doc = frappe.get_doc("Event Contact Campaign", docname)

    if doc.owner_type == "Chapter":
        # Get chapter board members
        chapter = doc.owner_reference or doc.chapter
        if not chapter:
            return []

        volunteers = frappe.db.sql(
            """
            SELECT DISTINCT
                cbm.volunteer as name,
                v.volunteer_name
            FROM `tabChapter Board Member` cbm
            INNER JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE cbm.parent = %(chapter)s
                AND cbm.is_active = 1
            ORDER BY v.volunteer_name
            """,
            {"chapter": chapter},
            as_dict=True,
        )
        return volunteers

    elif doc.owner_type == "Team":
        # Get team members
        team = doc.owner_reference
        if not team:
            return []

        volunteers = frappe.db.sql(
            """
            SELECT DISTINCT
                tm.volunteer as name,
                v.volunteer_name
            FROM `tabTeam Member` tm
            INNER JOIN `tabVolunteer` v ON tm.volunteer = v.name
            WHERE tm.parent = %(team)s
                AND tm.is_active = 1
            ORDER BY v.volunteer_name
            """,
            {"team": team},
            as_dict=True,
        )
        return volunteers

    # For User type or no owner, return empty list
    return []


@frappe.whitelist()
def distribute_members(docname: str, volunteer_ids: str = None) -> dict:
    """
    Distribute members in the contact list among selected volunteers.

    Members are distributed evenly using round-robin assignment.
    Only unassigned members are distributed.

    Args:
        docname: The name of the Event Contact Campaign document
        volunteer_ids: JSON string of volunteer IDs to distribute among.
                      If not provided, uses all available volunteers.

    Returns:
        dict with status and distribution summary
    """
    import json

    doc = frappe.get_doc("Event Contact Campaign", docname)

    if not doc.contact_list:
        return {
            "status": "warning",
            "message": _("No members in contact list to distribute"),
        }

    # Get volunteers to distribute among
    if volunteer_ids:
        volunteers = json.loads(volunteer_ids)
    else:
        available = get_available_volunteers(docname)
        volunteers = [v["name"] for v in available]

    if not volunteers:
        return {
            "status": "warning",
            "message": _("No volunteers available. Please select a Team or Chapter as campaign owner."),
        }

    # Get unassigned members
    unassigned_rows = [row for row in doc.contact_list if not row.assigned_to]

    if not unassigned_rows:
        return {
            "status": "info",
            "message": _("All members are already assigned"),
        }

    # Distribute using round-robin
    for idx, row in enumerate(unassigned_rows):
        volunteer_idx = idx % len(volunteers)
        row.assigned_to = volunteers[volunteer_idx]
        # Fetch volunteer name
        row.assigned_to_name = frappe.db.get_value(
            "Volunteer", volunteers[volunteer_idx], "volunteer_name"
        )

    doc.save()

    # Calculate distribution summary
    distribution = {}
    for row in doc.contact_list:
        if row.assigned_to:
            name = row.assigned_to_name or row.assigned_to
            distribution[name] = distribution.get(name, 0) + 1

    summary = ", ".join([f"{name}: {count}" for name, count in distribution.items()])

    return {
        "status": "success",
        "message": _("Distributed {0} members among {1} volunteers").format(
            len(unassigned_rows), len(volunteers)
        ),
        "distribution": summary,
        "assigned_count": len(unassigned_rows),
    }


@frappe.whitelist()
def clear_assignments(docname: str) -> dict:
    """
    Clear all volunteer assignments from the contact list.

    Args:
        docname: The name of the Event Contact Campaign document

    Returns:
        dict with status and count of cleared assignments
    """
    doc = frappe.get_doc("Event Contact Campaign", docname)

    cleared = 0
    for row in doc.contact_list:
        if row.assigned_to:
            row.assigned_to = None
            row.assigned_to_name = None
            cleared += 1

    if cleared:
        doc.save()

    return {
        "status": "success" if cleared else "info",
        "message": _("Cleared {0} assignments").format(cleared) if cleared else _("No assignments to clear"),
        "cleared": cleared,
    }


def _get_user_volunteer(user: str):
    """Get the volunteer record for a user, if any."""
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if member:
        return frappe.db.get_value("Volunteer", {"member": member}, "name")
    return None


def _is_chapter_board_member(volunteer: str, chapter: str) -> bool:
    """Check if a volunteer is an active board member of a chapter."""
    return bool(
        frappe.db.exists(
            "Chapter Board Member",
            {"parent": chapter, "volunteer": volunteer, "is_active": 1},
        )
    )


def _is_team_member(volunteer: str, team: str) -> bool:
    """Check if a volunteer is an active member of a team."""
    return bool(
        frappe.db.exists(
            "Team Member",
            {"parent": team, "volunteer": volunteer, "is_active": 1},
        )
    )


def _get_user_chapters(volunteer: str) -> list[str]:
    """Get all chapters where the volunteer is an active board member."""
    chapters = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabChapter Board Member`
        WHERE volunteer = %s AND is_active = 1
        """,
        volunteer,
        as_list=True,
    )
    return [c[0] for c in chapters]


def _get_user_teams(volunteer: str) -> list[str]:
    """Get all teams where the volunteer is an active member."""
    teams = frappe.db.sql(
        """
        SELECT DISTINCT parent
        FROM `tabTeam Member`
        WHERE volunteer = %s AND is_active = 1
        """,
        volunteer,
        as_list=True,
    )
    return [t[0] for t in teams]


def get_permission_query_conditions(user=None):
    """
    Get permission query conditions for Event Contact Campaign.

    Controls which campaigns appear in list views based on user's role and access.

    Access Rules:
    - System Manager / Verenigingen Administrator / Verenigingen Staff: See all campaigns
    - Verenigingen Chapter Board Member: See campaigns where:
      - owner_type = 'Chapter' AND owner_reference is a chapter they are board member of
      - OR chapter field is a chapter they are board member of
    - Team members: See campaigns where owner_type = 'Team' AND they are a member of that team
    - Others: No access
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admins and staff see all campaigns
    if any(
        role in user_roles
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
    ):
        return ""

    conditions = []

    # Get user's volunteer record
    volunteer = _get_user_volunteer(user)

    if volunteer:
        # Chapter Board Members see campaigns for their chapters
        if "Verenigingen Chapter Board Member" in user_roles:
            chapters = _get_user_chapters(volunteer)
            if chapters:
                chapter_list = ", ".join([f"'{c}'" for c in chapters])
                # Access if chapter field matches OR (owner_type='Chapter' AND owner_reference matches)
                conditions.append(
                    f"(`tabEvent Contact Campaign`.chapter IN ({chapter_list}) "
                    f"OR (`tabEvent Contact Campaign`.owner_type = 'Chapter' "
                    f"AND `tabEvent Contact Campaign`.owner_reference IN ({chapter_list})))"
                )

        # Team members see campaigns owned by their teams
        teams = _get_user_teams(volunteer)
        if teams:
            team_list = ", ".join([f"'{t}'" for t in teams])
            conditions.append(
                f"(`tabEvent Contact Campaign`.owner_type = 'Team' "
                f"AND `tabEvent Contact Campaign`.owner_reference IN ({team_list}))"
            )

    if conditions:
        return " OR ".join(conditions)

    # Default: no access
    return "1=0"


def has_permission(doc, ptype="read", user=None):
    """
    Control document-level access to Event Contact Campaign.

    Provides row-level security ensuring users can only access campaigns
    they have permission to manage based on chapter board membership or team membership.

    Access Rules:
    - System Manager / Verenigingen Administrator / Verenigingen Staff: Full access
    - Verenigingen Chapter Board Member: Access if they are board member of campaign's chapter
      or if owner_type='Chapter' and they are board member of owner_reference
    - Team members: Access if owner_type='Team' and they are member of that team
    - Others: No access
    """
    if not user:
        user = frappe.session.user

    user_roles = frappe.get_roles(user)

    # Admins and staff have full access
    if any(
        role in user_roles
        for role in ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
    ):
        return True

    # Get user's volunteer record
    volunteer = _get_user_volunteer(user)
    if not volunteer:
        return False

    # Get document attributes
    chapter = doc.chapter if hasattr(doc, "chapter") else None
    owner_type = doc.owner_type if hasattr(doc, "owner_type") else None
    owner_reference = doc.owner_reference if hasattr(doc, "owner_reference") else None

    # Check chapter board membership
    if "Verenigingen Chapter Board Member" in user_roles:
        # Access via chapter field
        if chapter and _is_chapter_board_member(volunteer, chapter):
            return True
        # Access via owner_reference when owner_type is Chapter
        if owner_type == "Chapter" and owner_reference:
            if _is_chapter_board_member(volunteer, owner_reference):
                return True

    # Check team membership
    if owner_type == "Team" and owner_reference:
        if _is_team_member(volunteer, owner_reference):
            return True

    return False
