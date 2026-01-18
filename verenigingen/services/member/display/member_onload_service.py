# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Onload Service

Orchestrates all display updates when a Member document is loaded in the form view.
Extracted from Member DocType's onload() method.

This service handles:
- Chapter display updates
- Address display updates
- Other members at address display (household members)
- Volunteer details HTML generation
- Membership duration calculation

Each operation is isolated with error handling to ensure one failure
doesn't prevent other displays from loading.
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberOnloadService(StatelessService):
    """Service for orchestrating member form onload operations."""

    def execute_onload(self, member_doc: "Document") -> dict:
        """Execute all onload operations for a member document.

        Args:
            member_doc: The Member document being loaded

        Returns:
            dict: Summary of operations performed with any errors encountered
        """
        result = {
            "success": True,
            "operations": {},
            "errors": [],
        }

        # Skip for new/unsaved documents
        if member_doc.get("__islocal"):
            result["operations"]["skipped"] = "Document is new/unsaved"
            return result

        # Execute each operation with isolated error handling
        result["operations"]["chapter_display"] = self._update_chapter_display(member_doc)
        result["operations"]["address_display"] = self._update_address_display(member_doc)
        result["operations"]["household_members"] = self._update_household_members_display(member_doc)
        result["operations"]["volunteer_details"] = self._update_volunteer_details(member_doc)
        result["operations"]["membership_duration"] = self._update_membership_duration(member_doc)

        # Collect any errors
        for op_name, op_result in result["operations"].items():
            if isinstance(op_result, dict) and op_result.get("error"):
                result["errors"].append(f"{op_name}: {op_result['error']}")

        if result["errors"]:
            result["success"] = False

        return result

    def _update_chapter_display(self, member_doc: "Document") -> dict:
        """Update chapter display when form loads.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with success status
        """
        try:
            member_doc.update_current_chapter_display()
            return {"success": True}
        except Exception as e:
            frappe.log_error(
                f"Error updating chapter display in onload for {member_doc.name}: {e}",
                "Member Onload - Chapter Display",
            )
            return {"success": False, "error": str(e)}

    def _update_address_display(self, member_doc: "Document") -> dict:
        """Update address display when form loads.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with success status
        """
        try:
            member_doc.update_address_display()
            return {"success": True}
        except Exception as e:
            frappe.log_error(
                f"Error updating address display in onload for {member_doc.name}: {e}",
                "Member Onload - Address Display",
            )
            return {"success": False, "error": str(e)}

    def _update_household_members_display(self, member_doc: "Document") -> dict:
        """Update other members at address display.

        This operation may fail for users with limited permissions - that's acceptable.
        Permission errors are handled silently, other errors are logged.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with success status
        """
        try:
            member_doc.update_other_members_at_address_display()

            # Ensure the HTML field is included in the response
            if hasattr(member_doc, "other_members_at_address") and member_doc.other_members_at_address:
                member_doc.set_onload("other_members_at_address", member_doc.other_members_at_address)

            return {"success": True}
        except Exception as e:
            error_str = str(e)
            is_permission_error = "Access denied" in error_str or "permission" in error_str.lower()

            if not is_permission_error:
                frappe.log_error(
                    f"Error updating other members at address display in onload for {member_doc.name}: {e}",
                    "Member Onload - Household Members",
                )

            # Clear the field to prevent showing stale data
            member_doc.other_members_at_address = ""

            return {
                "success": False,
                "error": str(e),
                "is_permission_error": is_permission_error,
            }

    def _update_volunteer_details(self, member_doc: "Document") -> dict:
        """Update volunteer details HTML with assignment history.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with success status
        """
        try:
            from verenigingen.services.member.display.member_volunteer_display_service import (
                get_member_volunteer_display_service,
            )

            html = get_member_volunteer_display_service().generate_volunteer_details_html(member_doc)

            if html:
                member_doc.volunteer_details_html = html
                # Pass HTML to client via onload (same pattern as other_members_at_address)
                member_doc.set_onload("volunteer_details_html", html)

            return {"success": True, "has_content": bool(html)}
        except Exception as e:
            frappe.log_error(
                f"Error loading volunteer details HTML in onload for {member_doc.name}: {e}",
                "Member Onload - Volunteer Details",
            )
            return {"success": False, "error": str(e)}

    def _update_membership_duration(self, member_doc: "Document") -> dict:
        """Calculate membership duration on-demand from Membership records.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with success status
        """
        try:
            member_doc.calculate_cumulative_membership_duration()
            return {"success": True}
        except Exception as e:
            frappe.log_error(
                f"Error calculating membership duration in onload for {member_doc.name}: {e}",
                "Member Onload - Membership Duration",
            )
            return {"success": False, "error": str(e)}


# Module-level singleton accessor
_service_instance: Optional[MemberOnloadService] = None


def get_member_onload_service() -> MemberOnloadService:
    """Get or create the MemberOnloadService singleton.

    Returns:
        MemberOnloadService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberOnloadService()
    return _service_instance
