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
"""

from typing import TYPE_CHECKING

import frappe
from frappe import _

from verenigingen.services.member.account.member_role_service import MemberRoleService
from verenigingen.utils.dutch_name_utils import get_full_last_name, is_dutch_installation
from verenigingen.utils.secure_operations import secure_document_operation

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberUserAccountService:
    """
    Service for creating user accounts for members.

    This service handles the direct creation of user accounts without the
    request/approval workflow, suitable for:
    - Manual member-to-user conversion
    - Quick user account creation from Member form
    - API-driven account creation
    """

    @staticmethod
    def create_user_for_member(member_doc: "Document") -> str:
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
            member_doc.owner = user.name
            frappe.logger().info(
                f"Transferred ownership of member {member_doc.name} from {original_owner} to {user.name}"
            )

        # Save member document with proper validation and audit trail
        # Using flags to avoid triggering unnecessary business logic
        member_doc.flags.ignore_validate_update_after_submit = True
        member_doc.flags.ignore_mandatory = False  # Keep validation
        member_doc.save()

        frappe.msgprint(_("User {0} created successfully").format(user.name))
        return user.name


def get_member_user_account_service() -> MemberUserAccountService:
    """Get singleton instance of MemberUserAccountService"""
    return MemberUserAccountService()
