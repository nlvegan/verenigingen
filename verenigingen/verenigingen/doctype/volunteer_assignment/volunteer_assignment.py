# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import format_date


class VolunteerAssignment(Document):
    def get_title(self):
        """Generate a descriptive title for audit logs"""
        title_parts = []

        if self.assignment_type:
            title_parts.append(self.assignment_type)

        if self.role:
            title_parts.append(f"as {self.role}")

        if self.reference_name:
            title_parts.append(f"at {self.reference_name}")

        if self.start_date:
            if self.end_date:
                title_parts.append(f"({format_date(self.start_date)} - {format_date(self.end_date)})")
            else:
                title_parts.append(f"(from {format_date(self.start_date)})")

        if self.status and self.status != "Active":
            title_parts.append(f"[{self.status}]")

        return " ".join(title_parts) if title_parts else self.role or "Volunteer Assignment"

    def before_save(self):
        """Set title before saving for better audit logs"""
        # Ensure we have a descriptive title for the audit trail
        self.title = self.get_title()
