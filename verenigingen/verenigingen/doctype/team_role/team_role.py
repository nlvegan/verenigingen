# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamRole(Document):
    def validate(self):
        """Validate the Team Role document before saving"""
        self.validate_unique_role()
        self.validate_team_leader_role()

    def before_delete(self):
        """Prevent deletion if Team Role is actively used in team assignments"""
        self.validate_deletion_allowed()

    def on_trash(self):
        """Additional cleanup and validation before permanent deletion"""
        # Final check before deletion
        self.validate_deletion_allowed()

    def validate_unique_role(self):
        """If this role is being changed from non-unique to unique, validate existing assignments"""
        if not self.is_unique:
            return

        # Only validate if this is an existing role being changed to unique
        if self.is_new():
            return

        # Check if there are teams with multiple members having this role
        teams_with_duplicates = frappe.db.sql(
            """
            SELECT tm.parent as team_name, COUNT(*) as count
            FROM `tabTeam Member` tm
            INNER JOIN `tabTeam` t ON t.name = tm.parent
            WHERE tm.team_role = %s
            AND tm.is_active = 1
            AND t.status = 'Active'
            GROUP BY tm.parent
            HAVING COUNT(*) > 1
        """,
            (self.name,),
            as_dict=True,
        )

        if teams_with_duplicates:
            team_names = [team.team_name for team in teams_with_duplicates]
            frappe.throw(
                f"Cannot mark this role as unique because it is assigned to multiple members in teams: {', '.join(team_names)}. "
                f"Please ensure only one member per team has this role before marking it as unique.",
                title="Cannot Mark Role as Unique",
            )

    def validate_team_leader_role(self):
        """If this role is marked as team leader, validate leadership constraints"""
        if not self.is_team_leader:
            return

        # Team leader roles should typically be unique
        if not self.is_unique:
            frappe.msgprint(
                "Team Leader roles are typically marked as unique to prevent multiple leaders per team.",
                title="Recommendation",
                indicator="yellow",
            )

    def validate_deletion_allowed(self):
        """Validate that Team Role can be safely deleted"""

        # Check for active team assignments
        active_assignments = frappe.db.get_all(
            "Team Member",
            filters={"team_role": self.name, "is_active": 1},
            fields=["parent", "volunteer_name", "volunteer"],
        )

        if active_assignments:
            # Group by team for better error message
            teams_affected = {}
            for assignment in active_assignments:
                team_name = assignment.parent
                if team_name not in teams_affected:
                    teams_affected[team_name] = []
                teams_affected[team_name].append(assignment.volunteer_name or assignment.volunteer)

            team_details = []
            for team, members in teams_affected.items():
                team_details.append(f"{team}: {', '.join(members)}")

            frappe.throw(
                f"Cannot delete '{self.role_name}': actively assigned to {len(active_assignments)} members.",
                title="Cannot Delete Active Team Role",
            )

        # Check for inactive assignments (warn but don't block)
        inactive_assignments = frappe.db.count(
            "Team Member", filters={"team_role": self.name, "is_active": 0}
        )

        if inactive_assignments > 0:
            frappe.msgprint(
                f"Note: This Team Role has {inactive_assignments} inactive assignments that will be orphaned. "
                f"Consider reviewing these assignments before deletion.",
                title="Inactive Assignments Found",
                indicator="yellow",
            )

        # Check assignment history references
        history_references = frappe.db.count(
            "Assignment History", filters={"role": ["like", f"%{self.role_name}%"]}
        )

        if history_references > 0:
            frappe.msgprint(
                f"Note: This Team Role is referenced in {history_references} assignment history records. "
                f"These references will remain for historical tracking.",
                title="Assignment History References",
                indicator="blue",
            )

    def get_active_assignments(self):
        """Get all active team assignments for this role"""
        return frappe.db.get_all(
            "Team Member",
            filters={"team_role": self.name, "is_active": 1},
            fields=["parent", "volunteer", "volunteer_name", "from_date", "to_date"],
        )

    def can_be_deleted(self):
        """Check if this Team Role can be safely deleted"""
        try:
            self.validate_deletion_allowed()
            return True
        except frappe.ValidationError:
            return False

    @staticmethod
    def cleanup_orphaned_references():
        """Clean up any orphaned team_role references (utility method)"""

        # Find Team Members with invalid team_role references
        orphaned_refs = frappe.db.sql(
            """
            SELECT tm.name, tm.parent, tm.volunteer_name, tm.team_role
            FROM `tabTeam Member` tm
            LEFT JOIN `tabTeam Role` tr ON tm.team_role = tr.name
            WHERE tm.team_role IS NOT NULL
            AND tm.team_role != ''
            AND tr.name IS NULL
        """,
            as_dict=True,
        )

        if orphaned_refs:
            frappe.log_error(
                f"Found {len(orphaned_refs)} orphaned team_role references", "Team Role Orphaned References"
            )

            for ref in orphaned_refs:
                # Log the orphaned reference
                frappe.log_error(
                    f"Orphaned team_role reference: {ref.team_role} in Team {ref.parent} for {ref.volunteer_name}",
                    "Orphaned Team Role Reference",
                )

        return orphaned_refs
