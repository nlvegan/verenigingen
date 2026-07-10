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

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberValidationService(StatelessService):
    """Service for orchestrating member validation operations."""

    def _log_validation_error(
        self,
        error_code: str,
        validation: str,
        message: str,
        member_name: str,
        exception: Exception = None,
        **context,
    ):
        """Log validation error with structured context for observability."""
        error_msg = f"[{error_code}] {message} | member={member_name} | validation={validation}"
        if exception:
            error_msg += f" | error={str(exception)}"
        for key, value in context.items():
            error_msg += f" | {key}={value}"
        frappe.log_error(error_msg, f"Validation [{error_code}]")

    def execute_validation(self, member_doc: "Document") -> OperationResult[Dict[str, Any]]:
        """Execute all validation operations for a member document.

        Args:
            member_doc: The Member document being validated

        Returns:
            OperationResult: Summary of validations performed with success/failure status
        """
        validations = {}
        errors = []

        # 1. Core validations (always required)
        validations["core_fields"] = self._validate_core_fields(member_doc)

        # 2. Membership duration calculation (conditional)
        validations["duration"] = self._update_duration_if_needed(member_doc)

        # 3. Payment and business validations
        validations["payment"] = self._validate_payment_fields(member_doc)

        # 4. Member ID and fee override validations
        validations["member_id"] = self._validate_member_id_and_fees(member_doc)

        # 5. Status field synchronization (conditional)
        validations["status_sync"] = self._sync_status_fields_if_needed(member_doc)

        # Collect any errors
        for val_name, val_result in validations.items():
            if isinstance(val_result, dict) and val_result.get("error"):
                errors.append(f"{val_name}: {val_result['error']}")

        if errors:
            return OperationResult.fail(
                "Member validation failed",
                errors=errors,
                error_code="VALIDATION_001",
                validations=validations,
            )

        return OperationResult.ok(validations, member=member_doc.name)

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
                self._log_validation_error(
                    error_code="VALIDATION_DUR",
                    validation="membership_duration",
                    message="Error calculating membership duration",
                    member_name=member_doc.name,
                    exception=e,
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
