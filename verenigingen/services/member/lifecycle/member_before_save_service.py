# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Before Save Service

Orchestrates all operations that need to execute before a Member document is saved.
Extracted from Member DocType's before_save() method.

This service handles:
- Performance optimization (metadata caching, link batching)
- Member/Application ID generation
- Chapter display updates
- Address field normalization
- Counter reset handling
- Application status defaults
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberBeforeSaveService(StatelessService):
    """Service for orchestrating member before-save operations."""

    def execute_before_save(self, member_doc: "Document") -> dict:
        """Execute all before-save operations for a member document.

        Args:
            member_doc: The Member document being saved

        Returns:
            dict: Summary of operations performed
        """
        result = {
            "success": True,
            "operations": {},
            "errors": [],
        }

        # 1. Apply safe performance optimizations
        result["operations"]["optimization"] = self._apply_performance_optimization(member_doc)

        # 2. Handle ID generation (member ID or application ID)
        result["operations"]["id_generation"] = self._handle_id_generation(member_doc)

        # 3. Update chapter display when necessary
        result["operations"]["chapter_display"] = self._update_chapter_display_if_needed(member_doc)

        # 4. Update computed address fields
        result["operations"]["address_fields"] = self._update_address_fields(member_doc)

        # 5. Clear counter reset flag
        result["operations"]["counter_reset"] = self._clear_counter_reset_flag(member_doc)

        # 6. Set application status defaults
        result["operations"]["status_defaults"] = self._set_application_status_defaults(member_doc)

        # Collect any errors
        for op_name, op_result in result["operations"].items():
            if isinstance(op_result, dict) and op_result.get("error"):
                result["errors"].append(f"{op_name}: {op_result['error']}")

        if result["errors"]:
            result["success"] = False

        return result

    def _apply_performance_optimization(self, member_doc: "Document") -> dict:
        """Apply safe performance optimizations for member creation.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        try:
            from verenigingen.utils.safe_member_optimizer import safe_member_optimizer

            safe_member_optimizer.optimize_member_creation(member_doc)
            return {"success": True}
        except Exception as e:
            # Log but don't fail member creation if optimization fails
            frappe.log_error(
                f"Safe member optimization failed for {member_doc.name}: {str(e)}",
                "Member Before Save - Optimization",
            )
            return {"success": False, "error": str(e), "non_blocking": True}

    def _handle_id_generation(self, member_doc: "Document") -> dict:
        """Handle member ID or application ID generation.

        Member IDs are only assigned to approved members to prevent premature ID allocation.
        Application IDs are assigned for tracking pending applications.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result with ID generation details
        """
        from verenigingen.services.member.core.member_id_service import (
            generate_application_id,
            generate_member_id,
        )

        result = {"success": True, "action": None, "id_generated": None}

        if member_doc.member_id:
            frappe.logger().debug(f"Member {member_doc.name} already has member_id: {member_doc.member_id}")
            result["action"] = "already_has_member_id"
            return result

        # Check if member should have a member ID
        if member_doc.should_have_member_id():
            frappe.logger().info(
                f"Generating member ID for {member_doc.name} - "
                f"application_status: {getattr(member_doc, 'application_status', 'None')}, "
                f"is_application: {member_doc.is_application_member()}"
            )
            member_doc.member_id = generate_member_id()
            frappe.logger().info(f"Generated member ID: {member_doc.member_id} for {member_doc.name}")
            result["action"] = "generated_member_id"
            result["id_generated"] = member_doc.member_id

        # Check if application member needs application ID
        elif member_doc.is_application_member() and not member_doc.application_id:
            member_doc.application_id = generate_application_id()
            result["action"] = "generated_application_id"
            result["id_generated"] = member_doc.application_id

        else:
            result["action"] = "no_id_needed"

        return result

    def _update_chapter_display_if_needed(self, member_doc: "Document") -> dict:
        """Update chapter display only when necessary to optimize performance.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        try:
            if member_doc._should_update_chapter_display():
                member_doc.update_current_chapter_display()
                return {"success": True, "updated": True}
            return {"success": True, "updated": False}
        except Exception as e:
            frappe.log_error(
                f"Error updating chapter display for {member_doc.name}: {str(e)}",
                "Member Before Save - Chapter Display",
            )
            return {"success": False, "error": str(e)}

    def _update_address_fields(self, member_doc: "Document") -> dict:
        """Update computed address fields for efficient member matching.

        Creates normalized fingerprints for duplicate detection.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        try:
            member_doc._update_computed_address_fields()
            return {"success": True}
        except Exception as e:
            frappe.log_error(
                f"Error updating address fields for {member_doc.name}: {str(e)}",
                "Member Before Save - Address Fields",
            )
            return {"success": False, "error": str(e)}

    def _clear_counter_reset_flag(self, member_doc: "Document") -> dict:
        """Clear counter reset flag after processing to prevent repeated resets.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        if hasattr(member_doc, "reset_counter_to") and member_doc.reset_counter_to:
            member_doc.reset_counter_to = None
            return {"success": True, "cleared": True}
        return {"success": True, "cleared": False}

    def _set_application_status_defaults(self, member_doc: "Document") -> dict:
        """Ensure application status is properly set based on member state.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        try:
            from verenigingen.services.member.core.member_status_service import (
                set_member_application_status_defaults,
            )

            set_member_application_status_defaults(member_doc)
            return {"success": True}
        except Exception as e:
            frappe.log_error(
                f"Error setting application status defaults for {member_doc.name}: {str(e)}",
                "Member Before Save - Status Defaults",
            )
            return {"success": False, "error": str(e)}


# Module-level singleton accessor
_service_instance: Optional[MemberBeforeSaveService] = None


def get_member_before_save_service() -> MemberBeforeSaveService:
    """Get or create the MemberBeforeSaveService singleton.

    Returns:
        MemberBeforeSaveService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberBeforeSaveService()
    return _service_instance
