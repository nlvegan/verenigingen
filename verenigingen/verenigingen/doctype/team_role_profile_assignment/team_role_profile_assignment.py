# Copyright (c) 2025, Vereniging Veganisme and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamRoleProfileAssignment(Document):
    """
    Child DocType for configuring role-specific profile assignments within teams.

    This allows teams to assign different role profiles based on the specific
    team role (e.g., Team Lead gets different permissions than Team Member).
    """

    def validate(self):
        """Validate the assignment configuration"""
        # Ensure the role profile exists
        if self.role_profile and not frappe.db.exists("Role Profile", self.role_profile):
            frappe.throw(f"Role Profile '{self.role_profile}' does not exist")

        # Ensure the team role exists
        if self.team_role and not frappe.db.exists("Team Role", self.team_role):
            frappe.throw(f"Team Role '{self.team_role}' does not exist")
