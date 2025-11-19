# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VolunteerSkill(Document):
    def validate(self):
        # Ensure proficiency level is valid
        if hasattr(self, "proficiency_level") and self.proficiency_level:
            level = (
                self.proficiency_level.split(" - ")[0]
                if " - " in self.proficiency_level
                else self.proficiency_level
            )
            try:
                level_value = int(level)
                if level_value < 1 or level_value > 5:
                    frappe.throw(_("Proficiency level must be between 1 and 5"))
            except ValueError:
                frappe.throw(_("Invalid proficiency level format"))
