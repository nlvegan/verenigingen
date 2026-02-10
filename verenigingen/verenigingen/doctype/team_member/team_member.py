# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
import frappe.utils
from frappe import _
from frappe.model.document import Document


class TeamMember(Document):
    # NOTE: after_insert(), on_update(), on_trash() are NOT called for child tables
    # managed via parent save. Team Lead role assignment and role profile sync are
    # handled by Team.on_update hooks (team_role_profile_hooks.py).

    def validate(self):
        """Validate team member data"""
        self.validate_dates()
        self.validate_volunteer()
        self.validate_unique_role()
        self.sync_status_and_active_flag()

    def validate_dates(self):
        """Validate start and end dates"""
        if self.to_date and self.from_date and self.to_date < self.from_date:
            frappe.throw(_("End date cannot be before start date"))

    def validate_volunteer(self):
        """Ensure a volunteer is assigned"""
        if not self.volunteer:
            frappe.throw(_("A volunteer must be assigned to the team member"))

    def sync_status_and_active_flag(self):
        """Ensure is_active and status are in sync"""
        if not self.is_active and self.status == "Active":
            self.status = "Inactive"
        elif self.is_active and self.status != "Active":
            self.is_active = 0

    def validate_unique_role(self):
        """Validate that unique roles are not assigned to multiple people in the same team"""
        if not self.team_role:
            return

        try:
            team_role_doc = frappe.get_cached_doc("Team Role", self.team_role)
            if not team_role_doc or not team_role_doc.is_unique:
                return
        except frappe.DoesNotExistError:
            frappe.throw(f"Team Role '{self.team_role}' does not exist. Please select a valid role.")
            return

        # CRITICAL FIX: self.parent can be None for new unsaved child docs
        # Only validate if we actually have a parent team to check against
        if not self.parent:
            return

        # Check if someone else in this team already has this unique role
        # Use count instead of fetching all records for better performance
        # Check for active members with no end date OR future end date
        existing_count = frappe.db.count(
            "Team Member",
            {
                "parent": self.parent,  # Same team
                "team_role": self.team_role,
                "name": ["!=", self.name or ""],
                "is_active": 1,
            },
        )

        # Also check for members with future end dates
        if existing_count == 0:
            existing_count += frappe.db.count(
                "Team Member",
                {
                    "parent": self.parent,
                    "team_role": self.team_role,
                    "name": ["!=", self.name or ""],
                    "is_active": 1,
                    "to_date": [">=", frappe.utils.today()],
                },
            )

        if existing_count > 0:
            # Only fetch names if we need to show them in error
            # Get active members without end date
            existing_members = frappe.db.get_all(
                "Team Member",
                {
                    "parent": self.parent,
                    "team_role": self.team_role,
                    "name": ["!=", self.name or ""],
                    "is_active": 1,
                    "to_date": ["is", "not set"],
                },
                ["volunteer_name"],
                limit=3,
            )

            # If not enough found, also get members with future end dates
            if len(existing_members) < 3:
                future_members = frappe.db.get_all(
                    "Team Member",
                    {
                        "parent": self.parent,
                        "team_role": self.team_role,
                        "name": ["!=", self.name or ""],
                        "is_active": 1,
                        "to_date": [">=", frappe.utils.today()],
                    },
                    ["volunteer_name"],
                    limit=3 - len(existing_members),
                )
                existing_members.extend(future_members)

            member_names = [member.volunteer_name for member in existing_members]
            if len(member_names) > 3:
                member_names = member_names[:3] + ["..."]

            frappe.throw(
                f"The role '{team_role_doc.role_name}' is marked as unique and is already assigned to: {', '.join(member_names)} in this team. "
                f"Please remove the existing assignment before assigning this role to another member.",
                title="Unique Role Violation",
            )

    # REMOVED: _send_team_member_added_notification, _send_team_member_removed_notification
    # These were called from the dead after_insert/on_trash methods above.
    # Team notifications are handled separately by the event subscriber system
    # (events/subscribers/team_subscribers.py).
