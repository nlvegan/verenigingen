# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import logging
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document

logger = logging.getLogger(__name__)


class SecurityLevelMapping(Document):
    """
    Security Level Mapping DocType for runtime security configuration

    This DocType allows System Managers to configure which Role Profiles
    have access to different security levels and operation contexts,
    solving the challenge of context-aware security without hardcoding.
    """

    def validate(self):
        """Validate the security level mapping configuration"""
        self.validate_role_profile_exists()
        self.validate_context_validation_method()
        self.validate_date_range()
        self.validate_additional_conditions()

    def validate_role_profile_exists(self):
        """Ensure the referenced role profile exists"""
        if self.role_profile:
            if not frappe.db.exists("Role Profile", self.role_profile):
                frappe.throw(_("Role Profile '{0}' does not exist").format(self.role_profile))

    def validate_context_validation_method(self):
        """Validate context validation method if specified"""
        if self.context_validation_method:
            # Check if the method exists in the security framework
            try:
                from verenigingen.utils.security.context_validators import get_context_validator

                validator = get_context_validator(self.context_validation_method)
                if not validator:
                    frappe.throw(
                        _("Context validation method '{0}' not found").format(self.context_validation_method)
                    )
            except ImportError:
                # Module doesn't exist yet, that's ok during initial setup
                pass

    def validate_date_range(self):
        """Validate effective date range"""
        if self.effective_from and self.effective_to:
            if self.effective_to < self.effective_from:
                frappe.throw(_("Effective To date cannot be before Effective From date"))

    def validate_additional_conditions(self):
        """Basic validation of additional conditions code"""
        if self.additional_conditions:
            # Basic syntax check - try to compile the code
            try:
                compile(self.additional_conditions, "<additional_conditions>", "exec")
            except SyntaxError as e:
                frappe.throw(_("Syntax error in additional conditions: {0}").format(str(e)))

    def on_update(self):
        """Handle mapping updates with cache clearing"""
        # Log security mapping changes for audit trail
        frappe.logger("verenigingen.security").info(
            f"Security Level Mapping '{self.name}' updated: {self.security_level} -> {self.role_profile} "
            f"for context '{self.operation_context}' by {frappe.session.user}"
        )

        # Clear security framework cache
        self.clear_security_cache()

    def clear_security_cache(self):
        """Clear all security-related caches"""
        cache_keys = [
            "security_level_mappings",
            f"security_mapping_{self.security_level}_{self.operation_context}",
            "role_profile_security_map",
        ]

        for key in cache_keys:
            frappe.cache().delete_value(key)

    @staticmethod
    def get_security_access(
        user: str, security_level: str, operation_context: str = None, operation_data: Dict[str, Any] = None
    ) -> bool:
        """
        Check if user has access based on security level and context

        Args:
            user: User ID
            security_level: Required security level (Critical, High, Medium, Low, Public, Contextual)
            operation_context: Operation context (financial, member_data, etc.)
            operation_data: Additional data for context validation

        Returns:
            bool: True if user has access
        """
        try:
            # Get user's role profiles
            user_role_profiles = SecurityLevelMapping.get_user_role_profiles(user)
            if not user_role_profiles:
                return False

            # Get applicable mappings
            mappings = SecurityLevelMapping.get_applicable_mappings(security_level, operation_context)

            if not mappings:
                logger.warning(
                    f"No security mappings found for level '{security_level}', context '{operation_context}'"
                )
                return False

            # Check if user has any of the required role profiles
            for mapping in mappings:
                if mapping.role_profile in user_role_profiles:
                    # Check if mapping is currently effective
                    if not SecurityLevelMapping.is_mapping_effective(mapping):
                        continue

                    # Apply context-specific validation if needed
                    if mapping.context_validation_method or mapping.additional_conditions:
                        if SecurityLevelMapping.validate_context_access(mapping, user, operation_data):
                            return True
                    else:
                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking security access for user {user}: {e}")
            # Fail secure - deny access on error
            return False

    @staticmethod
    def get_user_role_profiles(user: str) -> list:
        """Get all role profiles for a user"""
        try:
            # Get role profiles directly assigned to user
            user_doc = frappe.get_doc("User", user)
            role_profiles = []

            for role_profile in user_doc.get("role_profiles", []):
                role_profiles.append(role_profile.role_profile)

            return role_profiles

        except Exception as e:
            logger.error(f"Error getting role profiles for user {user}: {e}")
            return []

    @staticmethod
    def get_applicable_mappings(security_level: str, operation_context: str = None):
        """Get security mappings applicable to the given criteria"""
        cache_key = f"security_mappings_{security_level}_{operation_context}"
        mappings = frappe.cache().get_value(cache_key)

        if not mappings:
            filters = {"security_level": security_level, "effective_from": ["<=", frappe.utils.today()]}

            # Add context filter if specified
            if operation_context:
                filters["operation_context"] = operation_context

            # Include mappings with no end date or future end date
            or_filters = [{"effective_to": ["is", "not set"]}, {"effective_to": [">=", frappe.utils.today()]}]

            mappings = frappe.get_all(
                "Security Level Mapping",
                filters=filters,
                or_filters=or_filters,
                fields=["*"],
                order_by="priority desc, creation desc",
            )

            # Cache for 5 minutes
            frappe.cache().set_value(cache_key, mappings, expires_in_sec=300)

        return mappings

    @staticmethod
    def is_mapping_effective(mapping) -> bool:
        """Check if mapping is currently effective based on dates"""
        today = frappe.utils.today()

        # Check effective from date
        if mapping.get("effective_from") and mapping.effective_from > today:
            return False

        # Check effective to date
        if mapping.get("effective_to") and mapping.effective_to < today:
            return False

        return True

    @staticmethod
    def validate_context_access(mapping, user: str, operation_data: Dict[str, Any] = None) -> bool:
        """Validate context-specific access rules"""
        try:
            # First try context validation method
            if mapping.get("context_validation_method"):
                from verenigingen.utils.security.context_validators import get_context_validator

                validator = get_context_validator(mapping.context_validation_method)
                if validator:
                    return validator(user, operation_data or {})

            # Then try additional conditions
            if mapping.get("additional_conditions"):
                # Create safe execution context
                context = {
                    "user": user,
                    "operation_data": operation_data or {},
                    "frappe": frappe,
                    "logger": logger,
                }

                # Execute additional conditions
                exec(mapping.additional_conditions, {"__builtins__": {}}, context)

                # Look for result variable
                return context.get("result", False)

            return True

        except Exception as e:
            logger.error(f"Error validating context access: {e}")
            # Fail secure
            return False


def get_security_level_mappings_for_export() -> list:
    """Get all security level mappings for fixture export"""
    return frappe.get_all(
        "Security Level Mapping", fields=["*"], order_by="security_level, operation_context, priority desc"
    )
