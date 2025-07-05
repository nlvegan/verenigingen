# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
import frappe.utils
from frappe import _
from frappe.model.document import Document


class TeamMember(Document):
    def after_insert(self):
        """Assign Team Lead role when someone becomes a team leader"""
        if self.role_type == "Team Leader":
            self.assign_team_lead_role()

    def on_trash(self):
        """Remove Team Lead role if no longer on any team as leader"""
        if self.role_type == "Team Leader":
            self.remove_team_lead_role()

    def on_update(self):
        """Handle role changes when team member status changes"""
        if self.role_type == "Team Leader":
            # If marked inactive or past end date, check if role should be removed
            if not self.is_active or (
                self.to_date and frappe.utils.getdate(self.to_date) < frappe.utils.today()
            ):
                self.remove_team_lead_role()
            else:
                # If reactivated, ensure they have the role
                self.assign_team_lead_role()

    def validate(self):
        """Validate team member data"""
        self.validate_dates()
        self.validate_volunteer()
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

    def assign_team_lead_role(self):
        """Assign the Team Lead role to the volunteer's user"""
        if not self.volunteer:
            return

        # Get the member and user associated with this volunteer
        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
        if not volunteer_doc.member:
            return

        user = frappe.db.get_value("Member", volunteer_doc.member, "user")
        if not user:
            return

        # Check if user already has the role
        existing_role = frappe.db.exists("Has Role", {"parent": user, "role": "Team Lead"})

        if not existing_role:
            # Create the role assignment
            frappe.get_doc(
                {
                    "doctype": "Has Role",
                    "parent": user,
                    "parenttype": "User",
                    "parentfield": "roles",
                    "role": "Team Lead",
                }
            ).insert(ignore_permissions=True)

            frappe.msgprint(f"Assigned Team Lead role to {user}")

    def remove_team_lead_role(self):
        """Remove Team Lead role if user is no longer a team leader on any team"""
        if not self.volunteer:
            return

        # Get the member and user associated with this volunteer
        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
        if not volunteer_doc.member:
            return

        user = frappe.db.get_value("Member", volunteer_doc.member, "user")
        if not user:
            return

        # Check if this volunteer has any other ACTIVE team leader positions
        active_leader_positions = frappe.db.count(
            "Team Member",
            {
                "volunteer": self.volunteer,
                "name": ["!=", self.name],
                "role_type": "Team Leader",
                "is_active": 1,
                "to_date": ["is", "null"],
            },
        )

        # Also check for positions with future end dates
        future_leader_positions = frappe.db.count(
            "Team Member",
            {
                "volunteer": self.volunteer,
                "name": ["!=", self.name],
                "role_type": "Team Leader",
                "is_active": 1,
                "to_date": [">=", frappe.utils.today()],
            },
        )

        total_active_leader_positions = active_leader_positions + future_leader_positions

        # Only remove role if they're not a team leader on any other active teams
        if total_active_leader_positions == 0:
            # Remove the role assignment
            role_assignment = frappe.db.exists("Has Role", {"parent": user, "role": "Team Lead"})

            if role_assignment:
                frappe.delete_doc("Has Role", role_assignment, ignore_permissions=True)
                frappe.msgprint(f"Removed Team Lead role from {user}")

    def validate_team_leader_account(self):
        """Ensure team leader has a linked user account"""
        if self.volunteer and self.role_type == "Team Leader":
            volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
            if volunteer_doc.member:
                user = frappe.db.get_value("Member", volunteer_doc.member, "user")
                if not user:
                    frappe.msgprint(
                        f"Warning: Team Leader {self.volunteer} does not have a linked user account. Team Lead role cannot be assigned.",
                        indicator="orange",
                    )
