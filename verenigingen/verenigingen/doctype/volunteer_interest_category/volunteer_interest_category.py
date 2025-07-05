# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VolunteerInterestCategory(Document):
    def autoname(self):
        # Auto-naming is handled by field 'category_name'
        pass

    def validate(self):
        # Validate parent category doesn't create a circular reference
        if self.parent_category:
            if self.parent_category == self.name:
                frappe.throw(_("Parent category cannot be the same as the category itself"))

            # Check for circular reference
            parent = self.parent_category
            while parent:
                parent_doc = frappe.get_doc("Volunteer Interest Category", parent)
                if parent_doc.parent_category == self.name:
                    frappe.throw(_("Circular reference detected in parent categories"))
                parent = parent_doc.parent_category if parent_doc.parent_category else None
