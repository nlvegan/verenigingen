"""
Base Role Profile Manager

Provides shared functionality for managing role profile assignments when users join/leave
organizational entities (chapters, teams, etc.) based on configurable role mappings.

This base class implements the common logic for role profile management, allowing
specialized implementations for different entity types while maintaining consistency
and avoiding code duplication.

Business Rules:
- When a user joins an entity, they get the associated role profile
- When a user leaves an entity, their role profile is removed (if no other entities require it)
- Multiple entities can share the same role profile requirements
- Users can have multiple role profiles from different entity positions

Architecture:
- Template Method pattern for specialization
- Configuration-driven entity-specific behavior
- Transaction management for atomic operations
- Comprehensive error handling and validation

Author: Verenigingen Development Team
Last Updated: 2025-08-26
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.query_builder import DocType

from verenigingen.utils.constants import Roles
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Error codes for standardized API responses
ERROR_CODES = {
    "VALIDATION_ERROR": "E001",
    "PERMISSION_ERROR": "E002",
    "NOT_FOUND": "E003",
    "CONFIGURATION_ERROR": "E004",
    "TRANSACTION_ERROR": "E005",
    "SYSTEM_ERROR": "E999",
}


@dataclass
class EntityConfig:
    """Configuration for entity-specific behavior"""

    entity_type: str  # "chapter" or "team"
    entity_label: str  # Human-readable label
    doctype: str  # Main DocType name (Chapter, Team)
    member_doctype: str  # Member DocType (Chapter Board Member, Team Member)
    role_doctype: str  # Role DocType (Chapter Role, Team Role)

    # Field mappings
    default_profile_field: str  # Field for default role profile
    enable_specific_field: str  # Field to enable role-specific profiles
    specific_profiles_field: str  # Child table field for role-specific profiles
    child_table_doctype: str  # Child table DocType name
    role_field_in_child: str  # Role field name in child table

    # Member lookup configuration
    member_enabled_field: str  # Field to check if member is enabled
    member_status_field: Optional[str]  # Optional status field
    member_status_active_value: Optional[str]  # Value for active status

    # Query fields
    member_role_field: str  # Role field in member DocType

    # Logging context
    log_context: str  # Context string for logging


class BaseRoleProfileManager(ABC):
    """Base class for role profile management across different entity types"""

    def __init__(self, config: EntityConfig):
        """Initialize with entity-specific configuration"""
        self.config = config
        # Validate required DocType fields exist
        self._validate_required_fields()

    def _validate_required_fields(self):
        """Validate that all required fields exist on configured DocTypes"""
        # Skip validation during tests or if in install/migrate mode
        if frappe.flags.in_test or frappe.flags.in_install or frappe.flags.in_migrate:
            return

        try:
            # Validate main entity DocType fields
            entity_fields = [
                self.config.default_profile_field,
                self.config.enable_specific_field,
            ]

            if self.config.specific_profiles_field:
                entity_fields.append(self.config.specific_profiles_field)

            validation_error = validate_doctype_fields(self.config.doctype, entity_fields)
            if validation_error:
                frappe.log_error(
                    title="Role Profile Manager Configuration Error",
                    message=f"Configuration error for {self.config.entity_label}: {validation_error['error']}",
                )
                # Don't throw during initialization - just log
                return

            # Validate member DocType fields
            member_fields = [self.config.member_role_field]
            if self.config.member_enabled_field:
                member_fields.append(self.config.member_enabled_field)
            if self.config.member_status_field:
                member_fields.append(self.config.member_status_field)

            validation_error = validate_doctype_fields(self.config.member_doctype, member_fields)
            if validation_error:
                frappe.log_error(
                    title="Role Profile Manager Configuration Error",
                    message=f"Configuration error for {self.config.member_doctype}: {validation_error['error']}",
                )
                return

            # Validate child table DocType fields
            child_fields = [self.config.role_field_in_child, "role_profile"]

            validation_error = validate_doctype_fields(self.config.child_table_doctype, child_fields)
            if validation_error:
                frappe.log_error(
                    title="Role Profile Manager Configuration Error",
                    message=f"Configuration error for {self.config.child_table_doctype}: {validation_error['error']}",
                )
                return

        except Exception as e:
            # Log but don't fail initialization
            frappe.log_error(
                title="Role Profile Manager Validation Error",
                message=f"Error validating fields for {self.config.entity_label}: {str(e)}",
            )

    def get_entity_role_profile_config(self, entity_name: str) -> Dict:
        """
        Get role profile configuration for an entity from database.

        Args:
            entity_name: Name of the entity (chapter/team)

        Returns:
            dict: Configuration with default_profile and role_specific_profiles
        """
        try:
            entity_doc = frappe.get_doc(self.config.doctype, entity_name)

            config = {
                "default_profile": entity_doc.get(self.config.default_profile_field),
                "enable_role_specific": entity_doc.get(self.config.enable_specific_field, False),
                "role_specific_profiles": {},
            }

            # If role-specific profiles are enabled, build mapping
            if config["enable_role_specific"] and entity_doc.get(self.config.specific_profiles_field):
                for row in entity_doc.get(self.config.specific_profiles_field, []):
                    role_field = row.get(self.config.role_field_in_child)
                    profile_field = row.get("role_profile")
                    if role_field and profile_field:
                        config["role_specific_profiles"][role_field] = profile_field

            return config

        except Exception as e:
            frappe.logger().warning(
                f"Could not get {self.config.entity_type} config for {entity_name}: {str(e)}"
            )
            return {"default_profile": None, "enable_role_specific": False, "role_specific_profiles": {}}

    def determine_role_profile_for_member(
        self, entity_name: str, role: Optional[str] = None
    ) -> Optional[str]:
        """
        Determine which role profile should be assigned to an entity member.

        Args:
            entity_name: Name of the entity
            role: Specific role (optional)

        Returns:
            str: Role profile name or None
        """
        # Check if entity exists first
        if not frappe.db.exists(self.config.doctype, entity_name):
            frappe.logger().warning(
                f"{self.config.log_context}: {self.config.entity_label} '{entity_name}' does not exist"
            )
            return None

        # Get entity configuration - this handles unconfigured entities gracefully
        config = self.get_entity_role_profile_config(entity_name)

        # Check for role-specific profile first
        if config["enable_role_specific"] and role:
            role_specific_profile = config["role_specific_profiles"].get(role)
            if role_specific_profile:
                # Validate role profile dependencies
                deps_error = validate_role_profile_dependencies(role_specific_profile, self.config)
                if deps_error:
                    frappe.logger().warning(
                        f"{self.config.log_context}: Role profile validation failed for {role_specific_profile}: {deps_error.get('error')}"
                    )
                    return None
                return role_specific_profile

        # Fall back to default profile
        if config["default_profile"]:
            # Validate default role profile dependencies
            deps_error = validate_role_profile_dependencies(config["default_profile"], self.config)
            if deps_error:
                frappe.logger().warning(
                    f"{self.config.log_context}: Default role profile validation failed for {config['default_profile']}: {deps_error.get('error')}"
                )
                return None
            return config["default_profile"]

        # No configuration found
        return None

    def assign_role_profile(self, user: str, entity_name: str, role: Optional[str] = None) -> Dict[str, Any]:
        """
        Assign role profile when user joins an entity.

        Args:
            user: User email/name
            entity_name: Name of the entity they're joining
            role: Specific role (optional)

        Returns:
            dict: Standardized success/failure result
        """
        # Input validation
        validation_error = self._validate_role_assignment_inputs(user, entity_name, role)
        if validation_error:
            return validation_error

        # Use a savepoint (not frappe.db.begin) so this nests safely inside the
        # caller's request-level transaction. frappe.db.begin() issues START
        # TRANSACTION, which raises ImplicitCommitError whenever the surrounding
        # request already has pending writes (e.g. when invoked from a document hook
        # or inside a test wrapper).
        save_point = "assign_role_profile"
        transaction_started = False
        try:
            frappe.db.savepoint(save_point)
            transaction_started = True

            # Determine role profile
            role_profile = self.determine_role_profile_for_member(entity_name, role)
            if not role_profile:
                frappe.db.rollback(save_point=save_point)
                return self._create_response(
                    success=True,
                    message=f"No role profile configured for {self.config.entity_type} {entity_name} (role: {role or 'default'})",
                    action="no_config",
                )

            # Validate role profile exists
            if not frappe.db.exists("Role Profile", role_profile):
                frappe.db.rollback(save_point=save_point)
                frappe.logger().warning(
                    f"Role Profile {role_profile} does not exist for {self.config.log_context}"
                )
                return self._create_response(
                    success=False,
                    error=f"Role Profile {role_profile} does not exist",
                    error_code=ERROR_CODES["NOT_FOUND"],
                )

            # Get user document with reload to prevent race conditions
            user_doc = frappe.get_doc("User", user)
            user_doc.reload()

            # Additional validation
            if not user_doc.enabled:
                frappe.db.rollback(save_point=save_point)
                return self._create_response(
                    success=False,
                    error=f"Cannot assign role profile to disabled user {user}",
                    error_code=ERROR_CODES["VALIDATION_ERROR"],
                )

            # Assign the role profile if not already assigned
            current_profiles = {rp.role_profile for rp in (user_doc.role_profiles or [])}
            if role_profile not in current_profiles:
                previous_role_profile = user_doc.role_profile_name or (next(iter(current_profiles), None))

                # Frappe v16 deprecated the single role_profile_name Link in favour of the
                # role_profiles child table. Setting role_profile_name alone is a no-op when
                # the child table is empty (User.move_role_profile_name_to_role_profiles
                # discards it), so write to the child table directly. We keep this manager's
                # single-profile semantics by replacing the table contents.
                user_doc.set("role_profiles", [{"role_profile": role_profile}])
                user_doc.role_profile_name = role_profile

                # Save with proper permission validation
                result = secure_document_operation(
                    operation="save",
                    doc=user_doc,
                    justification=f"Assign role profile '{role_profile}' to user {user} for {self.config.entity_type} {entity_name} - role profile management for organizational access control",
                    required_permissions=["User:write"],
                )
                if not result.success:
                    frappe.db.rollback(save_point=save_point)
                    return self._create_response(
                        success=False,
                        error=f"Failed to assign role profile: {'; '.join(result.errors)}",
                        error_code=ERROR_CODES["PERMISSION_ERROR"],
                    )

                # Clear user permissions cache to ensure new role profile takes effect
                frappe.cache().delete_key(f"user_roles:{user}")
                frappe.cache().delete_key(f"user_permissions:{user}")

                # Release the savepoint; the write persists with the request-level commit.
                frappe.db.release_savepoint(save_point)

                # Log the assignment
                self._log_role_assignment("assigned", role_profile, user, entity_name, role)

                return self._create_response(
                    success=True,
                    message=f"Assigned role profile '{role_profile}' to user",
                    role_profile=role_profile,
                    previous_role_profile=previous_role_profile,
                    action="assigned",
                )
            else:
                frappe.db.release_savepoint(save_point)
                return self._create_response(
                    success=True,
                    message=f"User already has role profile '{role_profile}'",
                    action="already_assigned",
                )

        except frappe.DoesNotExistError as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            return self._create_response(
                success=False, error=f"Record not found: {str(e)}", error_code=ERROR_CODES["NOT_FOUND"]
            )
        except frappe.PermissionError as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            return self._create_response(
                success=False,
                error=f"Permission denied: {str(e)}",
                error_code=ERROR_CODES["PERMISSION_ERROR"],
            )
        except frappe.ValidationError as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            return self._create_response(
                success=False,
                error=f"Validation failed: {str(e)}",
                error_code=ERROR_CODES["VALIDATION_ERROR"],
            )
        except Exception as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            error_msg = f"Error assigning role profile for {self.config.entity_type} {entity_name}: {str(e)}"
            frappe.log_error(
                title=f"{self.config.log_context} Assignment Error",
                message=frappe.get_traceback(),
            )
            return self._create_response(
                success=False, error=error_msg, error_code=ERROR_CODES["SYSTEM_ERROR"]
            )

    def remove_role_profile(self, user: str, entity_name: str, role: Optional[str] = None) -> Dict[str, Any]:
        """
        Remove role profile when user leaves an entity.

        Args:
            user: User email/name
            entity_name: Name of the entity they're leaving
            role: Specific role (optional)

        Returns:
            dict: Standardized success/failure result
        """
        # Input validation
        validation_error = self._validate_role_assignment_inputs(user, entity_name, role)
        if validation_error:
            return validation_error

        # Use a savepoint instead of frappe.db.begin() so this nests inside the
        # caller's request-level transaction (see assign_role_profile for rationale).
        save_point = "remove_role_profile"
        transaction_started = False
        try:
            frappe.db.savepoint(save_point)
            transaction_started = True

            # Determine role profile
            role_profile = self.determine_role_profile_for_member(entity_name, role)
            if not role_profile:
                frappe.db.rollback(save_point=save_point)
                return self._create_response(
                    success=True,
                    message=f"No role profile configured for {self.config.entity_type} {entity_name} (role: {role or 'default'})",
                    action="no_config",
                )

            # Check if user still belongs to other entities requiring this role profile
            other_entities_with_same_profile = self.get_entities_requiring_role_profile(
                role_profile, exclude_entity=entity_name
            )

            if other_entities_with_same_profile:
                # Check if user is still in any of those entities
                if self._user_still_in_other_entities(user, other_entities_with_same_profile):
                    frappe.db.rollback(save_point=save_point)
                    return self._create_response(
                        success=True,
                        message=f"User still in other {self.config.entity_type}s requiring '{role_profile}', keeping role profile",
                        action="kept",
                    )

            # Get user document with reload to prevent race conditions
            user_doc = frappe.get_doc("User", user)
            user_doc.reload()

            # Additional validation
            if not user_doc.enabled:
                frappe.db.rollback(save_point=save_point)
                return self._create_response(
                    success=False,
                    error=f"Cannot modify role profile for disabled user {user}",
                    error_code=ERROR_CODES["VALIDATION_ERROR"],
                )

            # Remove role profile if currently assigned. In Frappe v16 the assignment lives
            # in the role_profiles child table (role_profile_name is deprecated/cleared on
            # save), so check both for backwards compatibility.
            current_profiles = {rp.role_profile for rp in (user_doc.role_profiles or [])}
            if role_profile == user_doc.role_profile_name or role_profile in current_profiles:
                previous_role_profile = role_profile

                # Commit the transaction first (entity membership changes are already committed).
                # This commit releases the savepoint, so clear the flag to keep the except
                # handler from rolling back to a savepoint that no longer exists.
                frappe.db.commit()
                transaction_started = False

                # Log the removal intent
                self._log_role_assignment("removing", role_profile, user, entity_name, role)

                # Now recalculate the correct profile based on remaining positions
                # This ensures volunteers keep "Verenigingen Volunteer" profile if status is Active
                from verenigingen.utils.user_role_profile_calculator import sync_user_role_profile

                sync_result = sync_user_role_profile(user)

                if sync_result.get("success"):
                    new_profile = sync_result.get("new_profile")
                    # Clear user permissions cache
                    frappe.cache().delete_key(f"user_roles:{user}")
                    frappe.cache().delete_key(f"user_permissions:{user}")

                    return self._create_response(
                        success=True,
                        message=f"Updated role profile from '{previous_role_profile}' to '{new_profile}'",
                        previous_role_profile=previous_role_profile,
                        new_role_profile=new_profile,
                        action="recalculated",
                    )
                else:
                    # Sync could not compute a replacement profile (e.g. the user is no
                    # longer a member). Previously this path claimed the profile was
                    # "removed" while leaving it assigned. Explicitly strip the profile so
                    # the reported state matches reality.
                    frappe.logger().warning(
                        f"Failed to recalculate role profile for {user}: {sync_result.get('error')}"
                    )
                    self._strip_role_profile(user, role_profile)
                    frappe.cache().delete_key(f"user_roles:{user}")
                    frappe.cache().delete_key(f"user_permissions:{user}")
                    return self._create_response(
                        success=True,
                        message=f"Removed role profile '{role_profile}', recalculation pending",
                        previous_role_profile=previous_role_profile,
                        action="removed_pending_recalc",
                    )
            else:
                frappe.db.release_savepoint(save_point)
                return self._create_response(
                    success=True,
                    message=f"User does not have role profile '{role_profile}'",
                    action="not_assigned",
                )

        except Exception as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            error_msg = f"Error removing role profile for {self.config.entity_type} {entity_name}: {str(e)}"
            frappe.log_error(
                title=f"{self.config.log_context} Removal Error",
                message=frappe.get_traceback(),
            )
            return self._create_response(
                success=False, error=error_msg, error_code=ERROR_CODES["SYSTEM_ERROR"]
            )

    def _strip_role_profile(self, user: str, role_profile: str) -> None:
        """Remove a single role profile from a user.

        Handles both the Frappe v16 role_profiles child table (canonical) and the
        deprecated role_profile_name Link field for v15 compatibility.
        """
        user_doc = frappe.get_doc("User", user)
        remaining = [rp for rp in (user_doc.role_profiles or []) if rp.role_profile != role_profile]
        user_doc.set("role_profiles", [{"role_profile": rp.role_profile} for rp in remaining])
        if user_doc.role_profile_name == role_profile:
            user_doc.role_profile_name = None
        secure_document_operation(
            operation="save",
            doc=user_doc,
            justification=f"Remove role profile '{role_profile}' from user {user} - role profile management for organizational access control",
            required_permissions=["User:write"],
        )

    def bulk_assign_role_profiles(self, entity_name: str) -> Dict[str, Any]:
        """
        Bulk assign role profiles to all existing members of an entity.

        Args:
            entity_name: Name of the entity

        Returns:
            dict: Standardized result with details of all operations
        """
        # Use a savepoint instead of frappe.db.begin() so this nests inside the
        # caller's request-level transaction (see assign_role_profile for rationale).
        save_point = "bulk_assign_role_profiles"
        transaction_started = False
        try:
            frappe.db.savepoint(save_point)
            transaction_started = True

            # Verify entity has role profile configuration
            config = self.get_entity_role_profile_config(entity_name)
            if not config["default_profile"] and not config["role_specific_profiles"]:
                frappe.db.rollback(save_point=save_point)
                return self._create_response(
                    success=False,
                    error=f"No role profile configuration found for {self.config.entity_type} {entity_name}",
                    error_code=ERROR_CODES["CONFIGURATION_ERROR"],
                )

            # Get all active entity members
            members_data = self._get_bulk_members_data(entity_name)

            # Pre-load user documents
            user_docs = self._preload_user_documents(members_data)

            # Pre-determine role profiles
            role_profile_cache = self._build_role_profile_cache(entity_name, members_data)

            # Process each member
            results = []
            success_count = 0
            error_count = 0

            for member_data in members_data:
                result = self._process_bulk_member(member_data, user_docs, role_profile_cache, entity_name)
                results.append(result)

                if result["result"]["success"]:
                    success_count += 1
                else:
                    error_count += 1

            # Release or roll back the savepoint based on results
            if error_count == 0 or success_count > error_count:
                frappe.db.release_savepoint(save_point)
                status_message = f"Processed {len(results)} {self.config.entity_type} members: {success_count} successful, {error_count} errors"
                success = True
            else:
                frappe.db.rollback(save_point=save_point)
                status_message = f"Bulk operation failed: {error_count} errors out of {len(results)} members. Transaction rolled back."
                success = False

            return self._create_response(success=success, message=status_message, results=results)

        except Exception as e:
            if transaction_started:
                frappe.db.rollback(save_point=save_point)
            return self._create_response(success=False, error=str(e), error_code=ERROR_CODES["SYSTEM_ERROR"])

    def get_entities_requiring_role_profile(
        self, role_profile: str, exclude_entity: Optional[str] = None
    ) -> List[str]:
        """
        Get list of entities that require a specific role profile.

        Args:
            role_profile: Role profile name to search for
            exclude_entity: Entity to exclude from results

        Returns:
            list: Entity names that require this role profile
        """
        entities = []

        # Check entities with default profile
        configured_entities = frappe.get_all(
            self.config.doctype, filters={self.config.default_profile_field: role_profile}, fields=["name"]
        )

        for entity in configured_entities:
            if entity.name != exclude_entity:
                entities.append(entity.name)

        # Check entities with role-specific profiles using Query Builder
        ChildTable = DocType(self.config.child_table_doctype)

        role_specific_entities = (
            frappe.qb.from_(ChildTable)
            .select(ChildTable.parent)
            .distinct()
            .where((ChildTable.role_profile == role_profile) & (ChildTable.parent != (exclude_entity or "")))
        ).run(as_dict=True)

        for entity in role_specific_entities:
            if entity.parent not in entities:
                entities.append(entity.parent)

        return entities

    def get_entities_using_role_profile(self, role_profile: str) -> List[Dict[str, str]]:
        """
        Get all entities that are configured to use a specific role profile.

        Args:
            role_profile: Role profile name to search for

        Returns:
            List of dicts with entity info: [{"name": entity_name, "entity_label": display_name, "usage_type": type}]
        """
        entities_using_profile = []

        try:
            # Get entities with this as default profile
            default_profile_entities = frappe.get_all(
                self.config.doctype,
                filters={self.config.default_profile_field: role_profile},
                fields=["name"],
                order_by="name",
            )

            for entity in default_profile_entities:
                # Try to get display name
                try:
                    entity_doc = frappe.get_doc(self.config.doctype, entity.name)
                    display_name = entity_doc.get(f"{self.config.entity_type}_name", entity.name)
                except:
                    display_name = entity.name

                entities_using_profile.append(
                    {"name": entity.name, "entity_label": display_name, "usage_type": "default"}
                )

            # Get entities with this in role-specific assignments using Query Builder
            if hasattr(self.config, "child_table_doctype") and self.config.child_table_doctype:
                ChildTable = DocType(self.config.child_table_doctype)

                role_specific_assignments = (
                    frappe.qb.from_(ChildTable)
                    .select(ChildTable.parent, ChildTable[self.config.role_field_in_child])
                    .where(ChildTable.role_profile == role_profile)
                ).run(as_dict=True)

                for assignment in role_specific_assignments:
                    # Get display name for the entity
                    try:
                        entity_doc = frappe.get_doc(self.config.doctype, assignment.parent)
                        display_name = entity_doc.get(f"{self.config.entity_type}_name", assignment.parent)
                    except:
                        display_name = assignment.parent

                    role_name = assignment.get(self.config.role_field_in_child, "Unknown Role")
                    entities_using_profile.append(
                        {
                            "name": assignment.parent,
                            "entity_label": display_name,
                            "usage_type": f"role_specific ({role_name})",
                        }
                    )

        except Exception as e:
            frappe.logger().error(
                f"{self.config.log_context}: Error getting entities using role profile '{role_profile}': {str(e)}"
            )

        return entities_using_profile

    # Abstract methods to be implemented by subclasses
    @abstractmethod
    def _user_still_in_other_entities(self, user: str, other_entities: List[str]) -> bool:
        """Check if user is still active in other entities"""
        pass

    @abstractmethod
    def _get_bulk_members_data(self, entity_name: str) -> List[Dict]:
        """Get member data for bulk operations"""
        pass

    @abstractmethod
    def _get_user_from_member_doc(self, doc) -> Optional[str]:
        """Extract user from member document in hook context"""
        pass

    # Helper methods
    def _validate_role_assignment_inputs(
        self, user: str, entity_name: str, role: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate inputs for role assignment operations.

        Args:
            user: User email/name to validate
            entity_name: Entity name to validate
            role: Role name (optional)

        Returns:
            dict: Error response if validation fails, None if valid
        """
        # Basic input validation
        if not user or not isinstance(user, str) or not user.strip():
            return self._create_response(
                success=False,
                error="User parameter is required and must be a valid string",
                error_code=ERROR_CODES["VALIDATION_ERROR"],
            )

        if not entity_name or not isinstance(entity_name, str) or not entity_name.strip():
            return self._create_response(
                success=False,
                error=f"{self.config.entity_label} name is required and must be a valid string",
                error_code=ERROR_CODES["VALIDATION_ERROR"],
            )

        # Check if user exists
        try:
            if not frappe.db.exists("User", user):
                return self._create_response(
                    success=False, error=f"User '{user}' does not exist", error_code=ERROR_CODES["NOT_FOUND"]
                )
        except Exception as e:
            return self._create_response(
                success=False,
                error=f"Error validating user existence: {str(e)}",
                error_code=ERROR_CODES["SYSTEM_ERROR"],
            )

        # Check if entity exists
        try:
            if not frappe.db.exists(self.config.doctype, entity_name):
                return self._create_response(
                    success=False,
                    error=f"{self.config.entity_label} '{entity_name}' does not exist",
                    error_code=ERROR_CODES["NOT_FOUND"],
                )
        except Exception as e:
            return self._create_response(
                success=False,
                error=f"Error validating {self.config.entity_type} existence: {str(e)}",
                error_code=ERROR_CODES["SYSTEM_ERROR"],
            )

        # Role validation (if provided)
        if role is not None and (not isinstance(role, str) or len(role.strip()) > 100):
            return self._create_response(
                success=False,
                error="Role must be a string with maximum 100 characters",
                error_code=ERROR_CODES["VALIDATION_ERROR"],
            )

        return None  # All validations passed

    def _create_response(self, success: bool, **kwargs) -> Dict[str, Any]:
        """Create standardized API response"""
        response = {"success": success, "timestamp": frappe.utils.now()}
        response.update(kwargs)
        return response

    def _log_role_assignment(
        self, action: str, role_profile: str, user: str, entity_name: str, role: Optional[str]
    ):
        """Log role profile assignment/removal for audit trail"""
        frappe.logger().info(
            f"{self.config.log_context}: {action} '{role_profile}' to user {user} "
            f"for {self.config.entity_type} {entity_name} (role: {role or 'default'})"
        )

    def _preload_user_documents(self, members_data: List[Dict]) -> Dict[str, Dict]:
        """Pre-load user documents to prevent N+1 queries"""
        user_docs = {}
        users_to_load = [m.get("user") for m in members_data if m.get("user")]

        if users_to_load:
            User = DocType("User")
            user_data = (
                frappe.qb.from_(User)
                .select(User.name, User.role_profile_name, User.enabled)
                .where(User.name.isin(users_to_load))
            ).run(as_dict=True)

            user_docs = {u.name: u for u in user_data}

        return user_docs

    def _build_role_profile_cache(
        self, entity_name: str, members_data: List[Dict]
    ) -> Dict[str, Optional[str]]:
        """Build cache of role profiles to prevent repeated lookups"""
        role_profile_cache = {}

        for member in members_data:
            role = member.get(self.config.member_role_field)
            if role not in role_profile_cache:
                role_profile_cache[role] = self.determine_role_profile_for_member(entity_name, role)

        return role_profile_cache

    def _process_bulk_member(
        self, member_data: Dict, user_docs: Dict, role_profile_cache: Dict, entity_name: str
    ) -> Dict[str, Any]:
        """Process a single member in bulk operation"""
        user = member_data.get("user")
        member_id = member_data.get("member")
        role = member_data.get(self.config.member_role_field)

        if not user or user not in user_docs:
            return {
                "user": user,
                "member": member_id,
                "result": self._create_response(
                    success=False,
                    error=f"User {user} not found or disabled",
                    error_code=ERROR_CODES["NOT_FOUND"],
                ),
            }

        try:
            user_doc = user_docs[user]
            role_profile = role_profile_cache.get(role)

            if not role_profile:
                return {
                    "user": user,
                    "member": member_id,
                    "result": self._create_response(
                        success=True,
                        message=f"No role profile configured for {self.config.entity_type} {entity_name} (role: {role or 'default'})",
                        action="no_config",
                    ),
                }

            if user_doc.role_profile_name == role_profile:
                return {
                    "user": user,
                    "member": member_id,
                    "result": self._create_response(
                        success=True,
                        message=f"User already has role profile '{role_profile}'",
                        action="already_assigned",
                    ),
                }

            # Update role profile directly in batch
            frappe.db.set_value("User", user, "role_profile_name", role_profile)
            # Clear cache for batch operations
            frappe.cache().delete_key(f"user_roles:{user}")
            frappe.cache().delete_key(f"user_permissions:{user}")

            # Log bulk assignment
            frappe.logger().info(
                f"{self.config.log_context} (Bulk): Assigned '{role_profile}' to user {user} "
                f"for {self.config.entity_type} {entity_name} (role: {role or 'default'})"
            )

            return {
                "user": user,
                "member": member_id,
                "result": self._create_response(
                    success=True,
                    message=f"Assigned role profile '{role_profile}' to user",
                    role_profile=role_profile,
                    previous_role_profile=user_doc.role_profile_name,
                    action="assigned",
                ),
            }

        except Exception as e:
            return {
                "user": user,
                "member": member_id,
                "result": self._create_response(
                    success=False, error=str(e), error_code=ERROR_CODES["SYSTEM_ERROR"]
                ),
            }


def _is_system_operation_authorized() -> bool:
    """
    Check if the current context is authorized for system operations that bypass permissions.

    Returns:
        bool: True if authorized for ignore_permissions=True operations  # Security: role-gated check
    """
    current_user = frappe.session.user
    user_roles = frappe.get_roles(current_user)

    # Allow system operations for administrators and system managers
    authorized_roles = ["Administrator", Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN]

    # Check if user has any authorized role
    has_authorized_role = any(role in user_roles for role in authorized_roles)

    # Additional context checks
    is_system_user = current_user in ["Administrator", "system"]

    return has_authorized_role or is_system_user


def safe_hook_execution(func, *args, timeout_seconds: int = 30, **kwargs):
    """
    Execute hook functions with timeout and error isolation.

    Args:
        func: Function to execute
        timeout_seconds: Maximum execution time

    Returns:
        Result of function or None if error
    """
    try:
        # Note: Frappe doesn't have built-in timeout support
        # This is a placeholder for future implementation
        result = func(*args, **kwargs)
        return result
    except Exception as e:
        frappe.logger().warning(f"Hook execution failed: {func.__name__}: {str(e)}")
        # Don't fail the main operation
        return None


def validate_doctype_fields(doctype: str, required_fields: List[str]) -> Optional[Dict[str, Any]]:
    """
    Validate that required fields exist on a DocType.

    Args:
        doctype: DocType name to validate
        required_fields: List of required field names

    Returns:
        dict: Error response if validation fails, None if valid
    """
    try:
        meta = frappe.get_meta(doctype)
        existing_fields = {f.fieldname for f in meta.fields}

        missing_fields = [f for f in required_fields if f not in existing_fields]

        if missing_fields:
            return {
                "success": False,
                "error": f"Missing required fields in {doctype}: {', '.join(missing_fields)}",
                "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
            }

        return None
    except Exception as e:
        return {
            "success": False,
            "error": f"Error validating {doctype} fields: {str(e)}",
            "error_code": ERROR_CODES["SYSTEM_ERROR"],
        }


def validate_entity_configuration(config: EntityConfig, entity_name: str) -> Optional[Dict[str, Any]]:
    """
    Validate that an entity's role profile configuration is coherent and functional.

    Args:
        config: EntityConfig with field mappings
        entity_name: Name of the entity to validate

    Returns:
        dict: Error response if validation fails, None if valid
    """
    try:
        # Check if entity exists
        if not frappe.db.exists(config.doctype, entity_name):
            return {
                "success": False,
                "error": f"{config.entity_label} '{entity_name}' does not exist",
                "error_code": ERROR_CODES["NOT_FOUND"],
            }

        # Get entity configuration
        entity_config = frappe.db.get_value(
            config.doctype,
            entity_name,
            [
                config.default_profile_field,
                config.enable_specific_field,
            ],
            as_dict=True,
        )

        if not entity_config:
            return {
                "success": False,
                "error": f"Could not retrieve configuration for {config.entity_label} '{entity_name}'",
                "error_code": ERROR_CODES["SYSTEM_ERROR"],
            }

        default_profile = entity_config.get(config.default_profile_field)
        enable_specific = entity_config.get(config.enable_specific_field)

        # Validate default role profile exists if configured
        if default_profile and not frappe.db.exists("Role Profile", default_profile):
            return {
                "success": False,
                "error": f"Default role profile '{default_profile}' does not exist for {config.entity_label} '{entity_name}'",
                "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
            }

        # If role-specific profiles are enabled, validate the configuration
        if enable_specific:
            # Check if any role-specific profiles are configured
            specific_profiles = frappe.get_all(
                config.child_table_doctype,
                filters={"parent": entity_name},
                fields=[config.role_field_in_child, "role_profile"],
            )

            if not specific_profiles:
                return {
                    "success": False,
                    "error": f"Role-specific profiles are enabled but no mappings configured for {config.entity_label} '{entity_name}'",
                    "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
                }

            # Validate each role-specific profile
            for profile_config in specific_profiles:
                role = profile_config.get(config.role_field_in_child)
                role_profile = profile_config.get("role_profile")

                # Validate role exists
                if role and not frappe.db.exists(config.role_doctype, role):
                    return {
                        "success": False,
                        "error": f"Role '{role}' is not present in role-specific configuration for {config.entity_label} '{entity_name}'",
                        "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
                    }

                # Validate role profile exists
                if role_profile and not frappe.db.exists("Role Profile", role_profile):
                    return {
                        "success": False,
                        "error": f"Role profile '{role_profile}' for role '{role}' does not exist for {config.entity_label} '{entity_name}'",
                        "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
                    }

        # Check for configuration coherence
        if not default_profile and not enable_specific:
            return {
                "success": False,
                "error": f"No role profile configuration found for {config.entity_label} '{entity_name}'. Either set a default profile or enable role-specific profiles",
                "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
            }

        return None

    except Exception as e:
        return {
            "success": False,
            "error": f"Error validating {config.entity_label} configuration: {str(e)}",
            "error_code": ERROR_CODES["SYSTEM_ERROR"],
        }


def validate_role_profile_dependencies(role_profile: str, config: EntityConfig) -> Optional[Dict[str, Any]]:
    """
    Validate role profile dependencies to prevent issues before assignment.

    Args:
        role_profile: Role profile name to validate
        config: EntityConfig for logging context

    Returns:
        dict: Error response if validation fails, None if valid
    """
    try:
        # Check if role profile exists
        if not frappe.db.exists("Role Profile", role_profile):
            return {
                "success": False,
                "error": f"Role Profile '{role_profile}' does not exist",
                "error_code": ERROR_CODES["NOT_FOUND"],
            }

        # Get role profile document to check its configuration
        role_profile_doc = frappe.get_doc("Role Profile", role_profile)

        # Check if role profile has any roles configured
        if not role_profile_doc.roles:
            return {
                "success": False,
                "error": f"Role Profile '{role_profile}' has no roles configured",
                "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
            }

        # Validate all roles in the profile exist
        for role_entry in role_profile_doc.roles:
            if not frappe.db.exists("Role", role_entry.role):
                return {
                    "success": False,
                    "error": f"Role '{role_entry.role}' in Role Profile '{role_profile}' does not exist",
                    "error_code": ERROR_CODES["CONFIGURATION_ERROR"],
                }

        return None

    except Exception as e:
        return {
            "success": False,
            "error": f"Error validating role profile dependencies for {config.log_context}: {str(e)}",
            "error_code": ERROR_CODES["SYSTEM_ERROR"],
        }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def validate_system_configuration() -> Dict[str, Any]:
    """
    Validate the entire role profile system configuration.
    Checks all teams and chapters for configuration coherence.

    Returns:
        dict: Validation results with any errors found
    """
    validation_results = {
        "success": True,
        "errors": [],
        "warnings": [],
        "teams_checked": 0,
        "chapters_checked": 0,
    }

    try:
        from verenigingen.services.chapter.chapter_role_profile_manager import (
            CHAPTER_CONFIG,
            _chapter_manager,
        )
        from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG, _team_manager

        # Validate all teams
        teams = frappe.get_all("Team", fields=["name"])
        for team in teams:
            team_name = team["name"]
            validation_results["teams_checked"] += 1

            # Skip if no role profile configuration
            team_config = frappe.db.get_value(
                "Team", team_name, ["default_role_profile", "enable_role_specific_profiles"], as_dict=True
            )

            if not team_config.get("default_role_profile") and not team_config.get(
                "enable_role_specific_profiles"
            ):
                validation_results["warnings"].append(f"Team '{team_name}' has no role profile configuration")
                continue

            error = validate_entity_configuration(TEAM_CONFIG, team_name)
            if error:
                validation_results["errors"].append(f"Team '{team_name}': {error['error']}")
                validation_results["success"] = False

        # Validate all chapters
        chapters = frappe.get_all("Chapter", fields=["name"])
        for chapter in chapters:
            chapter_name = chapter["name"]
            validation_results["chapters_checked"] += 1

            # Skip if no role profile configuration
            chapter_config = frappe.db.get_value(
                "Chapter",
                chapter_name,
                ["default_board_role_profile", "enable_board_role_specific_profiles"],
                as_dict=True,
            )

            if not chapter_config.get("default_board_role_profile") and not chapter_config.get(
                "enable_board_role_specific_profiles"
            ):
                validation_results["warnings"].append(
                    f"Chapter '{chapter_name}' has no board role profile configuration"
                )
                continue

            error = validate_entity_configuration(CHAPTER_CONFIG, chapter_name)
            if error:
                validation_results["errors"].append(f"Chapter '{chapter_name}': {error['error']}")
                validation_results["success"] = False

        # Summary
        validation_results["summary"] = (
            f"Validated {validation_results['teams_checked']} teams and "
            f"{validation_results['chapters_checked']} chapters. "
            f"Found {len(validation_results['errors'])} errors and "
            f"{len(validation_results['warnings'])} warnings."
        )

    except Exception as e:
        validation_results["success"] = False
        validation_results["errors"].append(f"System validation failed: {str(e)}")
        validation_results["summary"] = "System validation encountered a critical error"

    return validation_results


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def validate_all_role_profiles() -> Dict[str, Any]:
    """
    Validate all role profiles in the system for completeness and dependencies.

    Returns:
        dict: Validation results with any role profile issues
    """
    validation_results = {"success": True, "errors": [], "warnings": [], "profiles_checked": 0}

    try:
        from verenigingen.utils.team_role_profile_manager import TEAM_CONFIG

        # Get all role profiles
        role_profiles = frappe.get_all("Role Profile", fields=["name"])

        for profile in role_profiles:
            profile_name = profile["name"]
            validation_results["profiles_checked"] += 1

            # Validate this role profile
            error = validate_role_profile_dependencies(profile_name, TEAM_CONFIG)
            if error:
                validation_results["errors"].append(f"Role Profile '{profile_name}': {error['error']}")
                validation_results["success"] = False

        # Summary
        validation_results["summary"] = (
            f"Validated {validation_results['profiles_checked']} role profiles. "
            f"Found {len(validation_results['errors'])} errors."
        )

    except Exception as e:
        validation_results["success"] = False
        validation_results["errors"].append(f"Role profile validation failed: {str(e)}")
        validation_results["summary"] = "Role profile validation encountered a critical error"

    return validation_results
