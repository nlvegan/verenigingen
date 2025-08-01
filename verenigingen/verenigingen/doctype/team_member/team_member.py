# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
import frappe.utils
from frappe import _
from frappe.model.document import Document


class TeamMember(Document):
    def after_insert(self):
        """Assign Team Lead role when someone becomes a team leader"""
        if self.is_team_leader_role():
            self.assign_team_lead_role()

    def on_trash(self):
        """Remove Team Lead role if no longer on any team as leader"""
        if self.is_team_leader_role():
            self.remove_team_lead_role()

    def on_update(self):
        """Handle role changes when team member status changes"""
        if self.is_team_leader_role():
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
            try:
                # Create the role assignment with proper permission check
                if frappe.has_permission("User", "write", user) or frappe.session.user == "Administrator":
                    role_doc = frappe.get_doc(
                        {
                            "doctype": "Has Role",
                            "parent": user,
                            "parenttype": "User",
                            "parentfield": "roles",
                            "role": "Team Lead",
                        }
                    )
                    role_doc.insert()
                    frappe.logger().info(f"Assigned Team Lead role to {user}")
                else:
                    frappe.logger().warning(f"Insufficient permissions to assign Team Lead role to {user}")
            except Exception as e:
                frappe.log_error(
                    f"Failed to assign Team Lead role to {user}: {str(e)}", "Team Role Assignment Error"
                )

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
        # Get all team roles that are marked as team leader roles
        leader_roles = frappe.db.get_all("Team Role", {"is_team_leader": 1}, pluck="name")

        if not leader_roles:
            return  # No team leader roles defined

        active_leader_positions = frappe.db.count(
            "Team Member",
            {
                "volunteer": self.volunteer,
                "name": ["!=", self.name],
                "team_role": ["in", leader_roles],
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
                "team_role": ["in", leader_roles],
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
                try:
                    if frappe.has_permission("User", "write", user) or frappe.session.user == "Administrator":
                        frappe.delete_doc("Has Role", role_assignment)
                        frappe.logger().info(f"Removed Team Lead role from {user}")
                    else:
                        frappe.logger().warning(
                            f"Insufficient permissions to remove Team Lead role from {user}"
                        )
                except Exception as e:
                    frappe.log_error(
                        f"Failed to remove Team Lead role from {user}: {str(e)}", "Team Role Removal Error"
                    )

    def validate_team_leader_account(self):
        """Ensure team leader has a linked user account"""
        if self.volunteer and self.is_team_leader_role():
            volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
            if volunteer_doc.member:
                user = frappe.db.get_value("Member", volunteer_doc.member, "user")
                if not user:
                    frappe.msgprint(
                        f"Warning: Team Leader {self.volunteer} does not have a linked user account. Team Lead role cannot be assigned.",
                        indicator="orange",
                    )

    def is_team_leader_role(self):
        """Check if the assigned role is marked as a team leader role"""
        if not self.team_role:
            return False

        team_role_doc = frappe.get_cached_doc("Team Role", self.team_role)
        return team_role_doc.is_team_leader if team_role_doc else False

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
