# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberUserAccountService - User account creation for members

This service handles user account creation logic for members that was previously
in the Member DocType class. It provides direct user creation without the
request/approval workflow of AccountCreationManager.

Extracted from:
- Member.create_user() - lines 1485-1552 (68 LOC)

Architecture:
- Direct user creation (no request workflow)
- Dutch naming convention support
- Secure document operations
- Role and module assignment
- Ownership transfer

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
API method returns OperationResult[str] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- create_member_user_account: Returns OperationResult[str] (username created/linked)

Migration Status: ✅ COMPLETE (2025-11-24)
- API method migrated from dict-based to OperationResult pattern
- All security features and document operations preserved
- Type-safe error handling with comprehensive metadata

Legacy Methods (still throw exceptions):
- create_user_for_member: Direct user creation (throws ValidationError)
- create_user_account_if_needed: Hook-based creation (logs errors, doesn't throw)

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import TYPE_CHECKING

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.account.member_role_service import MemberRoleService
from verenigingen.utils.dutch_name_utils import get_full_last_name, is_dutch_installation
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberUserAccountService(StatelessService):
    """
    Service for creating user accounts for members.

    This service handles the direct creation of user accounts without the
    request/approval workflow, suitable for:
    - Manual member-to-user conversion
    - Quick user account creation from Member form
    - API-driven account creation
    """

    def __init__(self) -> None:
        """Initialize the member user account service."""
        super().__init__(service_name="MemberUserAccountService")

    def create_user_for_member(self, member_doc: "Document") -> str:
        """
        Create a user account for a member.

        This method performs direct user creation with:
        - Email validation
        - Existing user detection and linking
        - Dutch naming convention support
        - Secure user document creation
        - Role and module assignment
        - Ownership transfer to new user

        Args:
            member_doc: Member document object

        Returns:
            str: Username of created/linked user

        Raises:
            frappe.ValidationError: If email is missing or user creation fails
        """
        # Check if user already exists on member
        if member_doc.user:
            frappe.msgprint(_("User {0} already exists for this member").format(member_doc.user))
            return member_doc.user

        # Validate required fields are present
        if not member_doc.email:
            frappe.throw(_("Email is required to create a user"))

        if not member_doc.first_name:
            frappe.throw(_("First name is required to create a user"))

        if not member_doc.last_name:
            frappe.throw(_("Last name is required to create a user"))

        # Check if user with this email already exists
        if frappe.db.exists("User", member_doc.email):
            user = frappe.get_doc("User", member_doc.email)
            # Link existing user to member
            member_doc.user = user.name
            member_doc.save()
            frappe.msgprint(_("Linked to existing user {0}").format(user.name))
            return user.name

        # Create new user document
        user = frappe.new_doc("User")
        user.email = member_doc.email
        user.first_name = member_doc.first_name

        # Handle Dutch naming conventions for User creation
        if is_dutch_installation() and hasattr(member_doc, "tussenvoegsel") and member_doc.tussenvoegsel:
            # For Dutch installations, use combined last name with tussenvoegsel
            user.last_name = get_full_last_name(member_doc.last_name, member_doc.tussenvoegsel)
            # Don't use middle_name for User when we have tussenvoegsel
        else:
            # Standard naming for non-Dutch installations or when no tussenvoegsel
            user.last_name = member_doc.last_name
            if member_doc.middle_name:
                user.middle_name = member_doc.middle_name

        user.send_welcome_email = 1
        user.user_type = "System User"

        # Secure user creation with explicit permission validation
        user_result = secure_document_operation(
            operation="insert",
            doc=user,
            justification=f"Automated user creation for member {member_doc.name}",
            required_permissions=["User:create"],
        )

        if not user_result.success:
            frappe.throw(_("Failed to create user: {0}").format("; ".join(user_result.errors)))

        # Add member-specific roles after user is created
        MemberRoleService.add_member_roles_to_user(user.name)

        # Set allowed modules for member users
        MemberRoleService.set_member_user_modules(user.name)

        # Update user field on member document
        member_doc.user = user.name

        # Transfer ownership to the member's user account
        # This allows members to view and edit their own records
        if member_doc.owner != user.name:
            original_owner = member_doc.owner
            # Use direct database update to bypass "set only once" validation on owner field
            frappe.db.set_value("Member", member_doc.name, "owner", user.name, update_modified=False)
            member_doc.reload()
            self.logger.info(
                f"Transferred ownership of member {member_doc.name} from {original_owner} to {user.name}"
            )

        # Update user field and save member document with proper validation and audit trail
        if member_doc.user != user.name:
            member_doc.user = user.name
            member_doc.flags.ignore_validate_update_after_submit = True
            member_doc.flags.ignore_mandatory = False  # Keep validation
            member_doc.save()

        frappe.msgprint(_("User {0} created successfully").format(user.name))
        return user.name

    def create_member_user_account(
        self, member_name: str, send_welcome_email: bool = True
    ) -> OperationResult[str]:
        """
        Create a user account for a member - API-compatible wrapper.

        This is a wrapper around create_user_for_member() that matches the
        signature of the legacy member.py function for backward compatibility.

        Args:
            member_name: Name/ID of the member document
            send_welcome_email: Whether to send welcome email (default True)

        Returns:
            OperationResult[str]: Username on success with metadata:
                - user: Username created/linked
                - action: "created_new" or "linked_existing"

        Example:
            >>> result = MemberUserAccountService.create_member_user_account("Member-001")
            >>> if result.success:
            >>>     print(f"User created: {result.data}")

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Uses secure_document_operation for all document operations
        """
        try:
            # Get the member document
            member = frappe.get_doc("Member", member_name)

            # Check if user already exists
            if member.user:
                return OperationResult.fail(
                    _("User account already exists for this member"),
                    errors=["User already exists"],
                    user=member.user,
                )

            # Check if a user with this email already exists
            existing_user = frappe.db.get_value("User", {"email": member.email}, "name")
            if existing_user:
                # Link the existing user to the member
                member.user = existing_user
                member_result = secure_document_operation(
                    operation="save",
                    doc=member,
                    justification=f"Link existing user {existing_user} to member {member.name}",
                    required_permissions=["Member:write"],
                )

                if not member_result.success:
                    self.logger.error(f"Failed to link user to member: {'; '.join(member_result.errors)}")
                    frappe.throw(
                        _("Failed to link user to member: {0}").format("; ".join(member_result.errors))
                    )

                # Add member roles to existing user
                MemberRoleService.add_member_roles_to_user(existing_user)

                return OperationResult.ok(
                    existing_user,
                    message=_("Linked existing user account to member"),
                    action="linked_existing",
                )

            # Create new user
            user = frappe.new_doc("User")
            user.email = member.email
            user.first_name = member.first_name or ""
            user.last_name = member.last_name or ""
            user.full_name = member.full_name
            from verenigingen.utils.boolean_utils import cbool

            user.send_welcome_email = cbool(send_welcome_email)
            user.user_type = "System User"
            user.enabled = 1

            user_result = secure_document_operation(
                operation="insert",
                doc=user,
                justification=f"Automated user creation for member {member.name}",
                required_permissions=["User:create"],
            )

            if not user_result.success:
                self.logger.error(f"Failed to create user: {'; '.join(user_result.errors)}")
                frappe.throw(_("Failed to create user: {0}").format("; ".join(user_result.errors)))

            # Set allowed modules for member users
            MemberRoleService.set_member_user_modules(user.name)

            # Add member-specific roles
            MemberRoleService.add_member_roles_to_user(user.name)

            # Link user to member
            member.user = user.name
            member_link_result = secure_document_operation(
                operation="save",
                doc=member,
                justification=f"Link newly created user {user.name} to member {member.name}",
                required_permissions=["Member:write"],
            )

            if not member_link_result.success:
                self.logger.error(
                    f"Failed to link new user to member: {'; '.join(member_link_result.errors)}"
                )
                frappe.throw(
                    _("Failed to link new user to member: {0}").format("; ".join(member_link_result.errors))
                )

            self.logger.info(f"Created user account {user.name} for member {member.name}")

            return OperationResult.ok(
                user.name, message=_("User account created successfully"), action="created_new"
            )

        except Exception as e:
            self.logger.error(f"Error creating user account for member {member_name}: {str(e)}")
            return OperationResult.fail(
                _("Failed to create user account: {0}").format(str(e)), errors=[str(e)], member=member_name
            )

    def create_user_account_if_needed(self, member_doc: "Document") -> None:
        """
        Create user account for member if conditions are met.

        This method checks various conditions before creating a user account:
        - Not for application members (handled in approval process)
        - Only if user doesn't already exist
        - Requires email address
        - Only for active members or new members

        Args:
            member_doc: Member document object

        Returns:
            None (creates user account as side effect if conditions met)

        Note:
            - Does not raise exceptions (logs errors instead)
            - Used in after_save hook to auto-create accounts
            - Sends no welcome email (send_welcome_email=False)
        """
        try:
            # Don't create user for application members (handled in approval process)
            if member_doc.is_application_member():
                return

            # Don't create if user already exists
            if member_doc.user:
                return

            # Must have email to create user
            if not member_doc.email:
                return

            # Only create for active members
            if getattr(member_doc, "status", "") not in ["Active", ""]:
                return

            # Create user account using wrapper method
            result = self.create_member_user_account(member_doc.name, send_welcome_email=False)

            if result.get("success"):
                self.logger.info(f"Auto-created user account for manually created member {member_doc.name}")
            else:
                self.logger.warning(
                    f"Could not auto-create user account for member {member_doc.name}: "
                    f"{result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            self.logger.error(
                f"Error in create_user_account_if_needed for member {member_doc.name}: {str(e)}"
            )
            # Don't raise exception to avoid blocking member save


def get_member_user_account_service() -> MemberUserAccountService:
    """Get singleton instance of MemberUserAccountService"""
    return MemberUserAccountService()
