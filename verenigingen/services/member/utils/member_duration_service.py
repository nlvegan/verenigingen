# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Duration Service

Orchestrates membership duration calculation and update operations for Member documents.
Extracted from Member DocType methods for better separation of concerns.

This service handles:
- Calculating cumulative membership duration
- Force updating membership duration with proper flags
- Updating membership duration fields on demand

Uses the existing membership_duration_service utility functions for core calculations.
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.utils.membership_duration_service import (
    calculate_total_membership_days,
    format_duration_human_readable,
    update_member_duration_fields,
)

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberDurationService(StatelessService):
    """Service for orchestrating member duration calculation and update operations."""

    def calculate_cumulative_duration(self, member_doc: "Document") -> dict:
        """Calculate and set total membership duration in human-readable format.

        Calculates duration on-demand from Membership records (start_date, cancellation_date).
        No stored day counter - always calculates fresh from source data.

        Args:
            member_doc: The Member document

        Returns:
            dict: Result with success status, duration string, and years value
        """
        try:
            # Calculate fresh from Membership records
            total_days = calculate_total_membership_days(member_doc.name)

            # Format as human-readable duration (rounded to months)
            duration_formatted = format_duration_human_readable(total_days)

            # Update the member document field
            member_doc.cumulative_membership_duration = duration_formatted

            # Calculate years for backward compatibility
            duration_years = total_days / 365.25 if total_days > 0 else 0

            return {
                "success": True,
                "total_days": total_days,
                "duration": duration_formatted,
                "duration_years": duration_years,
            }

        except Exception as e:
            frappe.log_error(
                f"Error calculating cumulative membership duration for {member_doc.name}: {str(e)}",
                "Member Duration Service",
            )
            member_doc.cumulative_membership_duration = "Error calculating duration"
            return {
                "success": False,
                "error": str(e),
                "duration_years": 0,
            }

    def force_update_duration(self, member_doc: "Document") -> dict:
        """Force update membership duration - saves the document with appropriate flags.

        Sets the _force_duration_update flag, calculates duration, and saves with
        minimal logging to avoid activity log entries.

        Args:
            member_doc: The Member document

        Returns:
            dict: Result with success status and duration value
        """
        try:
            # Set flag to indicate forced update
            member_doc._force_duration_update = True

            # Calculate the duration
            calc_result = self.calculate_cumulative_duration(member_doc)

            if not calc_result.get("success"):
                return {
                    "success": False,
                    "error": calc_result.get("error", "Duration calculation failed"),
                }

            # Save with minimal logging to avoid activity log entries
            member_doc.flags.ignore_version = True
            member_doc.flags.ignore_links = True
            # Bypass after-submit validation for analytics fields only
            member_doc.flags.ignore_validate_update_after_submit = True
            member_doc.save()

            return {
                "success": True,
                "duration": member_doc.cumulative_membership_duration,
                "message": "Membership duration updated successfully",
            }

        except Exception as e:
            frappe.log_error(
                f"Error force updating membership duration for {member_doc.name}: {str(e)}",
                "Member Duration Service",
            )
            return {"success": False, "error": str(e)}

        finally:
            # Clear the flag
            if hasattr(member_doc, "_force_duration_update"):
                delattr(member_doc, "_force_duration_update")

    def update_duration(self, member_doc: "Document") -> dict:
        """Update the total membership days and human-readable duration.

        Uses the extracted service for consistent duration updates and saves
        with version tracking suppressed for automatic updates.

        Args:
            member_doc: The Member document

        Returns:
            dict: Result with success status and calculated values
        """
        try:
            # Use extracted utility to update duration fields
            result = update_member_duration_fields(member_doc)

            if result.get("success"):
                # Suppress version tracking for automatic duration updates
                # These are calculated fields updated by scheduler, not user actions
                member_doc.flags.ignore_version = True
                # Save the record - proper validation maintained
                member_doc.save()

            return result

        except Exception as e:
            frappe.log_error(
                f"Error updating membership duration for {member_doc.name}: {str(e)}",
                "Member Duration Service",
            )
            return {"success": False, "error": str(e)}

    def get_duration_years(self, member_doc: "Document") -> float:
        """Get the duration in years for backward compatibility.

        Args:
            member_doc: The Member document

        Returns:
            float: Duration in years
        """
        total_days = calculate_total_membership_days(member_doc.name)
        return total_days / 365.25 if total_days > 0 else 0


# Module-level singleton accessor
_service_instance: Optional[MemberDurationService] = None


def get_member_duration_service() -> MemberDurationService:
    """Get or create the MemberDurationService singleton.

    Returns:
        MemberDurationService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberDurationService()
    return _service_instance
