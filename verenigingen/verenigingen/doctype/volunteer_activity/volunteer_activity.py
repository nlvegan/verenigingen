# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class VolunteerActivity(Document):
    def validate(self):
        """Validate activity data"""
        # Validate dates
        if self.end_date and self.start_date and self.end_date < self.start_date:
            frappe.throw(_("End date cannot be before start date"))

        # Update volunteer record when activity is added or status changes
        self.update_volunteer_record()

    def update_volunteer_record(self):
        """Update volunteer record when activity is added or changed"""
        if not self.volunteer:
            return

        volunteer = frappe.get_doc("Volunteer", self.volunteer)

        # If status changed to inactive, we need to reflect in volunteer's assignment history
        if (
            self.has_value_changed("status")
            and self.status != "Active"
            and self.get_db_value("status") == "Active"
        ):
            # Add to assignment history
            volunteer.append(
                "assignment_history",
                {
                    "assignment_type": "Project",
                    "reference_doctype": self.reference_doctype or "Volunteer Activity",
                    "reference_name": self.reference_name or self.name,
                    "role": self.role,
                    "start_date": self.start_date,
                    "end_date": self.end_date or frappe.utils.today(),
                    "status": self.status,
                    "estimated_hours": self.estimated_hours,
                    "actual_hours": self.actual_hours,
                    "notes": self.notes,
                },
            )
            volunteer.save()

    def on_trash(self):
        """Update volunteer record when activity is deleted"""
        if not self.volunteer:
            return

        volunteer = frappe.get_doc("Volunteer", self.volunteer)

        # Check if this activity is in assignment history
        for idx, assignment in enumerate(volunteer.assignment_history):
            if (
                assignment.reference_doctype == "Volunteer Activity"
                and assignment.reference_name == self.name
            ):
                volunteer.assignment_history.remove(assignment)
                volunteer.save()
                break
