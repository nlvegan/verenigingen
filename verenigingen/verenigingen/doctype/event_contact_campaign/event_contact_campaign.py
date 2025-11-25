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

    def validate_dates(self):
        """Validate that end_date is after start_date and event_date is set for active campaigns."""
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                frappe.throw(_("Outreach End Date cannot be before Start Date"))

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

    # Query to get contactable members
    # We need to join Chapter Member (child table) with Member
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

    # Save the document
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


def get_permission_query_conditions(user=None):
    """
    Get permission query conditions for Event Contact Campaign.

    Controls which campaigns appear in list views based on user's role and chapter access.

    Access Rules:
    - System Manager / Verenigingen Administrator / Verenigingen Staff: See all campaigns
    - Verenigingen Chapter Board Member: See only campaigns for chapters they are a board member of
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

    # Chapter Board Members see campaigns for their chapters
    if "Verenigingen Chapter Board Member" in user_roles:
        # Get user's member record
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if member:
            # Get user's volunteer record
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
            if volunteer:
                # Get chapters where user is an active board member
                board_chapters = frappe.db.sql(
                    """
                    SELECT DISTINCT parent
                    FROM `tabChapter Board Member`
                    WHERE volunteer = %s AND is_active = 1
                    """,
                    volunteer,
                    as_list=True,
                )

                if board_chapters:
                    chapter_list = ", ".join(
                        [f"'{c[0]}'" for c in board_chapters]
                    )
                    return f"`tabEvent Contact Campaign`.chapter IN ({chapter_list})"

    # Default: no access
    return "1=0"


def has_permission(doc, ptype="read", user=None):
    """
    Control document-level access to Event Contact Campaign.

    Provides row-level security ensuring users can only access campaigns
    for chapters they have permission to manage.

    Access Rules:
    - System Manager / Verenigingen Administrator / Verenigingen Staff: Full access
    - Verenigingen Chapter Board Member: Access only to campaigns for their chapters
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

    # Chapter Board Members can access campaigns for their chapters
    if "Verenigingen Chapter Board Member" in user_roles:
        # Get the chapter from the document
        chapter = doc.chapter if hasattr(doc, "chapter") else None
        if not chapter:
            return False

        # Get user's member record
        member = frappe.db.get_value("Member", {"user": user}, "name")
        if not member:
            return False

        # Get user's volunteer record
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            return False

        # Check if this volunteer is an active board member of the campaign's chapter
        is_board_member = frappe.db.exists(
            "Chapter Board Member",
            {"parent": chapter, "volunteer": volunteer, "is_active": 1},
        )

        return bool(is_board_member)

    return False
