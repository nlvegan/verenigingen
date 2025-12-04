"""
Volunteer Activity Service

Handles volunteer activity management including adding activities, ending activities,
and activity lifecycle operations.

Business Logic:
    - Activities must have valid start/end dates
    - Activities can be linked to reference documents (events, tasks, etc.)
    - Hours tracking and estimation
    - Activity status management (Active → Completed)

Author: Verenigingen Development Team
License: MIT
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService


class VolunteerActivityService(StatelessService):
    """Service for managing volunteer activities"""

    def __init__(self, volunteer_name: str):
        """Initialize service for specific volunteer

        Args:
            volunteer_name: Volunteer record name
        """
        super().__init__(service_name="VolunteerActivityService")
        self.volunteer_name = volunteer_name
        self.volunteer_doc = None  # Lazy loaded

    def add_activity(
        self,
        activity_type: str,
        role: str,
        description: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        reference_doctype: Optional[str] = None,
        reference_name: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> str:
        """Add a new volunteer activity

        Args:
            activity_type: Type of activity (e.g., 'Event Support', 'Committee Work')
            role: Role in the activity
            description: Activity description
            start_date: Activity start date (defaults to today)
            end_date: Activity end date (optional, for planned activities)
            reference_doctype: Reference document type (e.g., 'Event')
            reference_name: Reference document name
            estimated_hours: Estimated hours for activity
            notes: Additional notes

        Returns:
            str: Name of created Volunteer Activity record

        Raises:
            frappe.ValidationError: If validation fails
        """
        try:
            # Validate required fields
            if not activity_type:
                frappe.throw(_("Activity Type is required"))

            if not role:
                frappe.throw(_("Role is required"))

            # Normalize dates
            start_date = getdate(start_date) if start_date else today()
            end_date = getdate(end_date) if end_date else None

            # Validate date range using consistent validator
            if end_date:
                from verenigingen.utils.validation_utilities import DateRangeValidator

                DateRangeValidator.validate_date_range(
                    start_date,
                    end_date,
                    allow_past_start=True,  # Activities can start in the past
                    allow_equal_dates=True,  # Same-day activities are valid
                    throw_on_error=True,
                )

            # Create Volunteer Activity document
            activity = frappe.get_doc(
                {
                    "doctype": "Volunteer Activity",
                    "volunteer": self.volunteer_name,
                    "activity_type": activity_type,
                    "role": role,
                    "description": description,
                    "start_date": start_date,
                    "end_date": end_date,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "estimated_hours": estimated_hours,
                    "notes": notes,
                    "status": "Active",
                }
            )

            activity.insert()

            self.logger.info(f"Added activity {activity.name} for volunteer {self.volunteer_name}")

            return activity.name

        except frappe.ValidationError:
            # ValidationErrors already have user-friendly messages, just re-raise
            raise
        except Exception as e:
            self.logger.error(f"Error adding activity for volunteer {self.volunteer_name}: {str(e)}")
            # Preserve stack trace for debugging
            frappe.throw(
                _("Failed to add volunteer activity: {0}").format(str(e)),
                exc=e,  # Preserve original exception for stack trace
            )

    def end_activity(
        self, activity_name: str, end_date: Optional[str] = None, notes: Optional[str] = None
    ) -> None:
        """End a volunteer activity

        Args:
            activity_name: Name of the Volunteer Activity to end
            end_date: End date (defaults to today)
            notes: Additional notes about activity completion

        Raises:
            frappe.DoesNotExistError: If activity not found
            frappe.ValidationError: If activity doesn't belong to volunteer
        """
        try:
            # Load and validate activity
            activity = frappe.get_doc("Volunteer Activity", activity_name)

            # Verify activity belongs to this volunteer
            if activity.volunteer != self.volunteer_name:
                frappe.throw(
                    _("Activity {0} does not belong to volunteer {1}").format(
                        activity_name, self.volunteer_name
                    )
                )

            # Normalize end date
            end_date = getdate(end_date) if end_date else getdate(today())

            # Validate date range using consistent validator
            from verenigingen.utils.validation_utilities import DateRangeValidator

            DateRangeValidator.validate_date_range(
                activity.start_date,
                end_date,
                allow_past_start=True,  # Activities can start in the past
                allow_equal_dates=True,  # Same-day activities are valid
                throw_on_error=True,
            )

            # Update activity
            activity.end_date = end_date
            activity.status = "Completed"

            # Add notes if provided
            if notes:
                existing_notes = activity.notes or ""
                activity.notes = f"{existing_notes}\n\nCompleted: {notes}" if existing_notes else notes

            activity.save()

            self.logger.info(f"Ended activity {activity_name} for volunteer {self.volunteer_name}")

        except frappe.DoesNotExistError:
            frappe.throw(_("Volunteer Activity {0} not found").format(activity_name))
        except frappe.ValidationError:
            # ValidationErrors already have user-friendly messages, just re-raise
            raise
        except Exception as e:
            self.logger.error(
                f"Error ending activity {activity_name} for volunteer {self.volunteer_name}: {str(e)}"
            )
            # Preserve stack trace for debugging
            frappe.throw(
                _("Failed to end volunteer activity: {0}").format(str(e)),
                exc=e,  # Preserve original exception for stack trace
            )

    def _load_volunteer(self):
        """Lazy load volunteer document"""
        if not self.volunteer_doc:
            self.volunteer_doc = frappe.get_doc("Volunteer", self.volunteer_name)
        return self.volunteer_doc
