# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamRole(Document):
    def validate(self):
        """Validate the Team Role document before saving"""
        self.validate_unique_role()
        self.validate_team_leader_role()

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
