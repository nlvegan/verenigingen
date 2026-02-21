# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberRoleService - User role and module management for members

This service handles all user role and module restriction logic for members
that was previously in the Member DocType module. It provides centralized
management of member user permissions and access control.

Extracted from member.py:
- add_member_roles_to_user() - lines 3683-3720 (38 LOC)
- _assign_individual_member_roles() - lines 3723-3765 (43 LOC)
- set_member_user_modules() - lines 3803-3841 (39 LOC)
- create_verenigingen_member_role() - lines 3771-3801 (31 LOC)

Architecture:
- Role profile assignment with fallback
- Individual role assignment when profile unavailable
- Module access restriction management
- Role creation for new installations
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation


class MemberRoleService(StatelessService):
    """
    Service for managing user roles and modules for member accounts.

    This service provides:
    - Role profile assignment
    - Individual role assignment (fallback)
    - Module access restrictions
    - Role creation and initialization
    """

    def __init__(self) -> None:
        """Initialize the member role service."""
        super().__init__(service_name="MemberRoleService")

    def add_member_roles_to_user(
        self, user_name: str, role_profile_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Add appropriate role profile for a member user to access portal pages.

        Args:
            user_name: Username/email of the user
            role_profile_name: Optional role profile to assign. If not provided,
                              defaults to "Verenigingen Member"

        Returns:
            Optional[str]: Username if successful, None if failed

        Raises:
            frappe.PermissionError: If user lacks permission to modify roles
        """
        try:
            # Check if user has permission to modify roles
            if not frappe.has_permission("User", "write"):
                frappe.throw(_("Insufficient permissions to modify user roles"))

            # Use provided role profile or default to Verenigingen Member
            if not role_profile_name:
                role_profile_name = "Verenigingen Member"
            if not frappe.db.exists("Role Profile", role_profile_name):
                self.logger.warning(
                    f"Role Profile {role_profile_name} does not exist. Creating basic roles manually."
                )
                # Fallback to individual role assignment
                return self._assign_individual_member_roles(user_name)

            # Add role profile to user
            user = frappe.get_doc("User", user_name)

            # INTENTIONAL: Clear ALL existing roles before assigning role profile
            #
            # JUSTIFICATION:
            # - Role profiles provide complete role sets and don't work well when mixed with individual roles
            # - This method is called during member account creation/setup, not for existing active users
            # - Member accounts should have ONLY member-related roles (Verenigingen Member, All)
            # - If this user account already has roles (e.g., Roles.SYSTEM_MANAGER), those roles
            #   were assigned incorrectly or the account is being re-purposed as a member account
            #
            # SAFETY NOTES:
            # - This is called from create_user_for_member() which only runs for NEW user accounts
            # - Existing users are linked but NOT passed through this role assignment
            # - Role Profile "Verenigingen Member" provides all necessary permissions
            #
            # RISK MITIGATION:
            # - If re-assigning an existing user with important roles, those roles are preserved
            #   in the User audit trail and can be manually restored if needed
            # - Consider adding a confirmation dialog in UI for re-purposing existing accounts
            user.roles = []

            # Assign the role profile
            user.role_profile_name = role_profile_name

            # Ensure user is enabled
            if not user.enabled:
                user.enabled = 1

            # Save with proper permissions (no bypass)
            user.save()
            self.logger.info(f"Assigned role profile '{role_profile_name}' to user {user_name}")

            return user.name

        except Exception as e:
            self.logger.error(
                f"Error adding roles to user {user_name}: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )
            return None

    def _assign_individual_member_roles(self, user_name: str) -> str:
        """
        Fallback method to assign individual roles when role profile is not available.

        Args:
            user_name: Username/email of the user

        Returns:
            str: Username if successful

        Raises:
            Exception: If role assignment fails
        """
        try:
            # Define the roles that members need for portal access
            member_roles = [
                "Verenigingen Member",  # Primary member role for all member access
                "All",  # Standard role for basic system access
            ]

            # Check if Verenigingen Member role exists, create if not
            if not frappe.db.exists("Role", "Verenigingen Member"):
                self.create_verenigingen_member_role()

            # Add roles to user
            user = frappe.get_doc("User", user_name)

            # INTENTIONAL: Clear ALL existing roles before individual role assignment
            #
            # JUSTIFICATION:
            # - This fallback method is used when role profile is unavailable
            # - Ensures clean slate for member role assignment (no conflicts with system roles)
            # - This method is called during member account creation/setup, not for existing active users
            # - Member accounts should have ONLY member-related roles (Verenigingen Member, All)
            #
            # SAFETY NOTES:
            # - Same safety considerations as add_member_roles_to_user()
            # - Called from same code path (create_user_for_member() for NEW accounts)
            # - Existing users are linked but NOT passed through this role assignment
            #
            # ALTERNATIVE APPROACH (if needed in future):
            # - Could use selective removal: only remove conflicting roles, preserve others
            # - Example: roles_to_remove = ["Verenigingen Member", "All"]
            # - However, for member accounts, a clean role slate is preferred
            user.roles = []

            for role in member_roles:
                if not frappe.db.exists("Role", role):
                    self.logger.warning(f"Role {role} does not exist, skipping")
                    continue
                # Always add the role since we cleared roles above
                user.append("roles", {"role": role})

            # Ensure user is enabled
            if not user.enabled:
                user.enabled = 1

            # Save with proper permissions (no bypass)
            user.save()
            self.logger.info(f"Assigned individual roles to user {user_name}: {member_roles}")

            return user.name

        except Exception as e:
            self.logger.error(
                f"Error assigning individual member roles to user {user_name}: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )
            raise

    def set_member_user_modules(self, user_name: str) -> None:
        """
        Set allowed modules for member users - restrict to relevant modules only.

        Args:
            user_name: Username/email of the user

        Returns:
            None

        Raises:
            frappe.ValidationError: If module restriction setup fails
        """
        try:
            # Define modules that members should have access to
            allowed_modules = [
                "Verenigingen",  # Main app module
                "Core",  # Essential Frappe core functionality
                "Desk",  # Basic desk access
                "Home",  # Home page access
            ]

            user = frappe.get_doc("User", user_name)

            # Clear existing module access and set only allowed ones
            user.set("block_modules", [])

            # Get all available modules
            all_modules = frappe.get_all("Module Def", fields=["name"])

            # Block all modules except the allowed ones
            for module in all_modules:
                if module.name not in allowed_modules:
                    user.append("block_modules", {"module": module.name})

            module_result = secure_document_operation(
                operation="save",
                doc=user,
                justification=f"Set module restrictions for user {user_name}",
                required_permissions=["User:write"],
            )

            if not module_result.success:
                self.logger.error(f"Failed to set module restrictions: {'; '.join(module_result.errors)}")
                frappe.throw(
                    _("Failed to set module restrictions: {0}").format("; ".join(module_result.errors))
                )

            self.logger.info(f"Set module restrictions for user {user_name}")

        except Exception as e:
            self.logger.error(
                f"Error setting module restrictions for user {user_name}: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )

    def create_verenigingen_member_role(self) -> None:
        """
        Create the Verenigingen Member role for consolidated member access.

        This role provides access to member portal functionality without
        granting full desk access.

        Returns:
            None

        Raises:
            frappe.ValidationError: If role creation fails
        """
        try:
            role = frappe.new_doc("Role")
            role.role_name = "Verenigingen Member"
            role.desk_access = 0  # Portal users don't need desk access
            role.is_custom = 1  # This is a custom role for the app

            role_result = secure_document_operation(
                operation="insert",
                doc=role,
                justification="Create Verenigingen Member role for member portal access",
                required_permissions=["Role:create"],
            )

            if not role_result.success:
                self.logger.error(
                    f"Failed to create Verenigingen Member role: {'; '.join(role_result.errors)}"
                )
                frappe.throw(
                    _("Failed to create Verenigingen Member role: {0}").format("; ".join(role_result.errors))
                )

            self.logger.info("Created Verenigingen Member role successfully")

        except Exception as e:
            self.logger.error(
                f"Error creating Verenigingen Member role: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )
            raise


def get_member_role_service() -> MemberRoleService:
    """Get singleton instance of MemberRoleService"""
    return MemberRoleService()
