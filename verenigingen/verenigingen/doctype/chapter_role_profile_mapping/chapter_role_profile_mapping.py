# Copyright (c) 2025, Vereniging Veganisme and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ChapterRoleProfileMapping(Document):
    """
    Child DocType for configuring role-specific profile assignments within chapter boards.

    This allows chapters to assign different role profiles based on the specific
    board role (e.g., Chapter Treasurer gets different permissions than Secretary).
    """

    def validate(self):
        """Validate the mapping configuration"""
        # Ensure the role profile exists
        if self.role_profile and not frappe.db.exists("Role Profile", self.role_profile):
            frappe.throw(f"Role Profile '{self.role_profile}' does not exist")

        # Ensure the chapter role exists
        if self.chapter_role and not frappe.db.exists("Chapter Role", self.chapter_role):
            frappe.throw(f"Chapter Role '{self.chapter_role}' does not exist")
