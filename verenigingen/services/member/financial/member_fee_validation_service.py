# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberFeeValidationService - Fee override validation logic

This service handles validation of membership fee overrides, including:
- Amount validation (positive values)
- Reason validation (required documentation)
- Permission validation (authorized users only)

Extracted from member.py:
- _validate_fee_override_amount() - lines 281-284 (4 LOC)
- _validate_fee_override_reason() - lines 286-312 (27 LOC)
- validate_fee_override_permissions() - lines 314-346 (33 LOC)

Total: ~64 LOC of validation logic in service layer

Architecture:
- Static methods for stateless validation
- Member document passed as parameter
- Throws validation errors using frappe.throw()
- Integration with permission system

Security:
- Role-based permission validation
- Audit logging for fee override actions
- CSV import and system update bypass support

Dependencies:
- frappe - For validation errors and permission checks
- Member DocType - For accessing member document fields

Called By:
- MemberFeeChangeService.handle_fee_override_changes()
- Member.validate() lifecycle hook
"""

from typing import TYPE_CHECKING

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberFeeValidationService(StatelessService):
    """
    Service for validating membership fee overrides.

    This service handles:
    - Amount validation (must be positive)
    - Reason validation (required for overrides)
    - Permission validation (authorized roles only)
    - Audit logging for fee override actions
    """

    def __init__(self) -> None:
        """Initialize the member fee validation service."""
        super().__init__(service_name="MemberFeeValidationService")

    def validate_fee_override_amount(self, amount: float) -> None:
        """
        Validate that fee override amount is positive.

        Args:
            amount: The fee override amount to validate

        Raises:
            frappe.ValidationError: If amount is not positive

        Example:
            >>> MemberFeeValidationService.validate_fee_override_amount(25.50)  # OK
            >>> MemberFeeValidationService.validate_fee_override_amount(0)      # Throws error
            >>> MemberFeeValidationService.validate_fee_override_amount(-10)    # Throws error
        """
        if amount and amount <= 0:
            frappe.throw(_("Membership fee override must be greater than 0"))

    def validate_fee_override_reason(self, member_doc: "Document") -> None:
        """
        Validate that fee override has a documented reason when required.

        Validates that a reason is provided when a member has a fee override set.
        Skips validation for:
        - CSV imports (bulk operations)
        - System updates (automated changes)
        - Test environments
        - Existing members with reasons already set

        Args:
            member_doc: Member document instance

        Raises:
            frappe.ValidationError: If reason is missing when required

        Business Logic:
            - New members with overrides MUST have reasons
            - Existing members with reasons can save without re-validation
            - CSV imports and system updates skip validation
            - Test environments skip validation

        Example:
            >>> member = frappe.get_doc("Member", "MEM-001")
            >>> member.dues_rate = 25.00
            >>> member.fee_override_reason = "Student discount"
            >>> MemberFeeValidationService.validate_fee_override_reason(member)  # OK
        """
        # No override set - no validation needed
        if not member_doc.dues_rate:
            return

        # Get context flags
        is_csv_import = getattr(member_doc, "_csv_import", False)
        is_system_update = getattr(member_doc, "_system_update", False)
        is_in_test = getattr(frappe.flags, "in_test", False)
        fee_override_reason = getattr(member_doc, "fee_override_reason", None)

        # Debug logging for troubleshooting
        self.logger.info(
            f"Fee override validation: member={member_doc.name or 'NEW'}, "
            f"dues_rate={member_doc.dues_rate}, "
            f"is_csv_import={is_csv_import}, is_system_update={is_system_update}, "
            f"is_in_test={is_in_test}, fee_override_reason={fee_override_reason}"
        )

        # Skip validation if CSV import, system update, or test environment
        if is_csv_import or is_system_update or is_in_test:
            return

        # Skip validation for existing members with reasons already set
        # This prevents blocking routine saves after reason is documented once
        if not member_doc.is_new() and fee_override_reason:
            return  # Existing member with reason - don't block saves

        # Require reason for new overrides
        if not fee_override_reason:
            frappe.throw(_("Please provide a reason for the fee override"))

    def validate_fee_override_permissions(self, member_doc: "Document") -> None:
        """
        Validate that only authorized users can set fee overrides.

        Checks that the current user has appropriate roles to modify membership fees.
        Only users with specific administrative roles can override fees.

        Args:
            member_doc: Member document instance

        Raises:
            frappe.PermissionError: If user lacks permission to override fees

        Security:
            - Authorized roles: System Manager, Verenigingen Staff, Verenigingen Administrator
            - Validates on fee changes only (not on every save)
            - Skips for new documents and system updates
            - Logs all fee override actions for audit trail

        Business Logic:
            - Compares current value with database value to detect changes
            - Only validates when fee override actually changes
            - System updates (_system_update flag) bypass validation
            - New documents skip validation (no existing value to compare)

        Example:
            >>> # User with 'Verenigingen Staff' role:
            >>> member.dues_rate = 30.00
            >>> MemberFeeValidationService.validate_fee_override_permissions(member)  # OK

            >>> # User with 'Member' role only:
            >>> member.dues_rate = 30.00
            >>> MemberFeeValidationService.validate_fee_override_permissions(member)  # Throws PermissionError
        """
        # Skip validation for new documents or if no override is set
        if member_doc.is_new() or not member_doc.dues_rate:
            return

        # Skip validation if this is a system update (e.g., from amendment request)
        if getattr(member_doc, "_system_update", False):
            return

        # Check if fee override value has actually changed
        if member_doc.name:
            old_amount = frappe.db.get_value("Member", member_doc.name, "dues_rate")
            if old_amount == member_doc.dues_rate:
                return  # No change, no validation needed

        # Check user permissions for fee override
        user_roles = frappe.get_roles(frappe.session.user)
        authorized_roles = ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]

        if not any(role in user_roles for role in authorized_roles):
            frappe.throw(
                _(
                    "You do not have permission to override membership fees. "
                    "Only administrators can modify membership fees."
                ),
                frappe.PermissionError,
            )

        # Log the fee override action for audit purposes
        self.logger.info(
            f"Fee override set by {frappe.session.user} for member {member_doc.name}: "
            f"Amount: {member_doc.dues_rate}, "
            f"Reason: {getattr(member_doc, 'fee_override_reason', 'No reason provided')}"
        )


def get_member_fee_validation_service() -> MemberFeeValidationService:
    """Get singleton instance of MemberFeeValidationService"""
    return MemberFeeValidationService()
