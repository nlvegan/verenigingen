# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Validation Service

Orchestrates all validation operations for a Member document.
Extracted from Member DocType's validate() method.

This service handles:
- Core field validations (name, full name, status, age)
- Membership duration calculation (conditional)
- Payment and business validations
- Member ID change validation
- Fee override change handling
- Status field synchronization
- Application status clearing
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberValidationService(StatelessService):
    """Service for orchestrating member validation operations."""

    def execute_validation(self, member_doc: "Document") -> dict:
        """Execute all validation operations for a member document.

        Args:
            member_doc: The Member document being validated

        Returns:
            dict: Summary of validations performed
        """
        result = {
            "success": True,
            "validations": {},
            "errors": [],
        }

        # 1. Core validations (always required)
        result["validations"]["core_fields"] = self._validate_core_fields(member_doc)

        # 2. Membership duration calculation (conditional)
        result["validations"]["duration"] = self._update_duration_if_needed(member_doc)

        # 3. Payment and business validations
        result["validations"]["payment"] = self._validate_payment_fields(member_doc)

        # 4. Member ID and fee override validations
        result["validations"]["member_id"] = self._validate_member_id_and_fees(member_doc)

        # 5. Status field synchronization (conditional)
        result["validations"]["status_sync"] = self._sync_status_fields_if_needed(member_doc)

        # 6. Application status clearing (conditional)
        result["validations"]["application_status"] = self._clear_application_status_if_needed(member_doc)

        # Collect any errors
        for val_name, val_result in result["validations"].items():
            if isinstance(val_result, dict) and val_result.get("error"):
                result["errors"].append(f"{val_name}: {val_result['error']}")

        if result["errors"]:
            result["success"] = False

        return result

    def _validate_core_fields(self, member_doc: "Document") -> dict:
        """Validate core member fields.

        Args:
            member_doc: The Member document

        Returns:
            dict: Validation result
        """
        try:
            from verenigingen.services.member.core.member_status_service import (
                update_member_membership_status,
            )
            from verenigingen.services.member.utils.member_age_service import (
                update_member_age_field,
                validate_member_age_requirements,
            )
            from verenigingen.utils.dutch_name_service import (
                update_member_full_name,
                validate_member_name_fields,
            )

            # Validate name fields
            validate_member_name_fields(member_doc)

            # Update computed full name
            update_member_full_name(member_doc)

            # Update membership status based on active memberships
            update_member_membership_status(member_doc)

            # Update age field and validate age requirements
            update_member_age_field(member_doc)
            validate_member_age_requirements(member_doc)

            return {"success": True}
        except Exception as e:
            # Re-raise validation errors as they should block the save
            raise

    def _update_duration_if_needed(self, member_doc: "Document") -> dict:
        """Update membership duration if explicitly requested or for new members.

        Daily scheduler handles routine duration updates to avoid on-visit field changes.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        should_update = getattr(member_doc, "_force_duration_update", False) or member_doc.is_new()

        if should_update:
            try:
                member_doc.calculate_cumulative_membership_duration()
                return {"success": True, "updated": True}
            except Exception as e:
                frappe.log_error(
                    f"Error calculating membership duration for {member_doc.name}: {str(e)}",
                    "Member Validation - Duration",
                )
                return {"success": False, "error": str(e)}

        return {"success": True, "updated": False, "reason": "not_needed"}

    def _validate_payment_fields(self, member_doc: "Document") -> dict:
        """Validate payment method and bank details.

        Args:
            member_doc: The Member document

        Returns:
            dict: Validation result
        """
        try:
            # These methods are on the member doc itself (from mixins)
            member_doc.validate_payment_method()
            member_doc.set_payment_reference()
            member_doc.validate_bank_details()

            return {"success": True}
        except Exception as e:
            # Re-raise validation errors as they should block the save
            raise

    def _validate_member_id_and_fees(self, member_doc: "Document") -> dict:
        """Validate member ID changes and handle fee override changes.

        Args:
            member_doc: The Member document

        Returns:
            dict: Validation result
        """
        try:
            from verenigingen.verenigingen.doctype.member.member_id_manager import (
                validate_member_id_change,
            )

            # Validate member ID changes
            validate_member_id_change(member_doc)

            # Handle fee override changes
            member_doc.handle_fee_override_changes()

            return {"success": True}
        except Exception as e:
            # Re-raise validation errors as they should block the save
            raise

    def _sync_status_fields_if_needed(self, member_doc: "Document") -> dict:
        """Synchronize status fields unless explicitly flagged to skip.

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        # Skip status sync if explicitly flagged (e.g., during approve/reject operations)
        if getattr(member_doc.flags, "ignore_status_validation", False):
            return {"success": True, "skipped": True, "reason": "ignore_status_validation"}

        try:
            from verenigingen.services.member.core.member_status_service import (
                sync_member_status_fields,
            )

            sync_member_status_fields(member_doc)
            return {"success": True, "synced": True}
        except Exception as e:
            # Re-raise validation errors as they should block the save
            raise

    def _clear_application_status_if_needed(self, member_doc: "Document") -> dict:
        """Clear application_status once member leaves application workflow.

        Application workflow states are: Pending, Under Review, Approved, Rejected, Payment Pending
        Once member becomes Active, Terminated, Suspended, etc., application_status is no longer relevant.

        IMPORTANT: Don't clear if we're in an explicit approve/reject operation
        (ignore_status_validation flag) or if status is "Rejected" (rejected status
        should preserve application_status)

        Args:
            member_doc: The Member document

        Returns:
            dict: Operation result
        """
        # Check conditions for clearing
        should_skip = getattr(member_doc.flags, "ignore_status_validation", False)
        status_allows_clear = member_doc.status not in ["Pending", "Rejected"]
        app_status_is_workflow = member_doc.application_status in [
            "Pending",
            "Under Review",
            "Approved",
            "Payment Pending",
        ]

        if should_skip:
            return {"success": True, "cleared": False, "reason": "ignore_status_validation"}

        if status_allows_clear and app_status_is_workflow:
            member_doc.application_status = None
            return {"success": True, "cleared": True}

        return {"success": True, "cleared": False, "reason": "conditions_not_met"}


# Module-level singleton accessor
_service_instance: Optional[MemberValidationService] = None


def get_member_validation_service() -> MemberValidationService:
    """Get or create the MemberValidationService singleton.

    Returns:
        MemberValidationService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberValidationService()
    return _service_instance
