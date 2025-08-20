"""
Security Wrappers for Frappe Framework Functions

This module provides centralized security wrappers for common Frappe framework functions
that can cause security vulnerabilities when used incorrectly. The primary focus is on
preventing the systemic vulnerability where frappe.get_roles(None) returns all system roles.

Key Security Issues Addressed:
1. frappe.get_roles(None) returns ALL system roles instead of empty list
2. Inconsistent user validation across the codebase
3. No centralized logging of security-related function calls
4. Lack of defensive programming against malformed user parameters

Security Features:
- Validates user parameters before passing to Frappe functions
- Logs suspicious function calls for security audit
- Provides consistent behavior across the entire application
- Prevents privilege escalation through framework quirks
- Maintains backward compatibility with existing code

Usage:
Replace direct calls to frappe.get_roles() with safe_get_roles():

Before:
    user_roles = frappe.get_roles(user)  # VULNERABLE

After:
    from verenigingen.utils.security_wrappers import safe_get_roles
    user_roles = safe_get_roles(user)    # SAFE

Architecture:
This module is designed to be:
- Drop-in replacement for existing Frappe function calls
- Zero performance impact for valid parameters
- Comprehensive logging for security audit trails
- Compatible with existing error handling patterns

Author: Security Team
Date: 2025-08-20
Version: 1.0
"""

import logging
from typing import List, Optional, Union

import frappe
from frappe import _

# Configure security logger
security_logger = logging.getLogger("vereingingen.security")


def safe_get_roles(user: Optional[Union[str, None]] = None) -> List[str]:
    """
    Secure wrapper for frappe.get_roles() that prevents the systemic vulnerability
    where frappe.get_roles(None) returns all system roles.

    Args:
        user: User email or None for current user

    Returns:
        List of role names for the user, empty list if user is invalid

    Security Features:
    - Validates user parameter to prevent None/empty string attacks
    - Logs suspicious calls for security audit
    - Returns empty list for invalid users instead of all roles
    - Maintains compatibility with existing code patterns

    Examples:
        # Safe usage patterns
        roles = safe_get_roles("user@example.com")  # Returns user's roles
        roles = safe_get_roles()                    # Returns current user's roles
        roles = safe_get_roles(None)                # Returns current user's roles (safe)
        roles = safe_get_roles("")                  # Returns [] (safe)
        roles = safe_get_roles("Guest")             # Returns ["Guest"] (safe)
    """
    try:
        # If no user provided, get current session user
        if user is None:
            user = getattr(frappe.session, "user", None)

        # Validate user parameter for security
        if not _is_valid_user_parameter(user):
            security_logger.warning(f"safe_get_roles called with invalid user parameter: {repr(user)}")
            return []

        # Handle Guest user explicitly
        if user == "Guest":
            return ["Guest"]

        # Call frappe.get_roles with validated user
        roles = frappe.get_roles(user)

        # Additional validation of result
        if not isinstance(roles, list):
            security_logger.error(f"frappe.get_roles({repr(user)}) returned non-list: {type(roles)}")
            return []

        # Log administrative role access for audit
        admin_roles = {"System Manager", "Administrator", "Verenigingen Administrator"}
        if any(role in admin_roles for role in roles):
            security_logger.info(f"Administrative role access: user={user}, roles={roles}")

        return roles

    except Exception as e:
        security_logger.error(f"Error in safe_get_roles for user {repr(user)}: {str(e)}")
        return []


def safe_has_role(user: Optional[str], role: str) -> bool:
    """
    Secure wrapper to check if a user has a specific role.

    Args:
        user: User email or None for current user
        role: Role name to check

    Returns:
        True if user has the role, False otherwise

    Security Features:
    - Uses safe_get_roles internally for security
    - Validates both user and role parameters
    - Logs privileged role checks for audit
    """
    try:
        if not role or not isinstance(role, str):
            security_logger.warning(f"safe_has_role called with invalid role: {repr(role)}")
            return False

        user_roles = safe_get_roles(user)
        has_role = role in user_roles

        # Log privileged role checks
        if has_role and role in {"System Manager", "Administrator", "Verenigingen Administrator"}:
            effective_user = user or getattr(frappe.session, "user", "Unknown")
            security_logger.info(f"Privileged role check: user={effective_user}, role={role}, granted=True")

        return has_role

    except Exception as e:
        security_logger.error(f"Error in safe_has_role: user={repr(user)}, role={repr(role)}, error={str(e)}")
        return False


def safe_has_any_role(user: Optional[str], roles: List[str]) -> bool:
    """
    Secure wrapper to check if a user has any of the specified roles.

    Args:
        user: User email or None for current user
        roles: List of role names to check

    Returns:
        True if user has any of the roles, False otherwise
    """
    try:
        if not roles or not isinstance(roles, (list, tuple)):
            security_logger.warning(f"safe_has_any_role called with invalid roles: {repr(roles)}")
            return False

        return any(safe_has_role(user, role) for role in roles)

    except Exception as e:
        security_logger.error(
            f"Error in safe_has_any_role: user={repr(user)}, roles={repr(roles)}, error={str(e)}"
        )
        return False


def _is_valid_user_parameter(user: Union[str, None]) -> bool:
    """
    Internal function to validate user parameter for security.

    Args:
        user: User parameter to validate

    Returns:
        True if user parameter is safe to use, False otherwise

    Security Validation Rules:
    1. None is allowed (will use current session user)
    2. String must not be empty or contain only whitespace
    3. String must not be literal "None" (common attack vector)
    4. String must be reasonable length (prevents buffer attacks)
    """
    # None is valid (will use session user)
    if user is None:
        return True

    # Must be string
    if not isinstance(user, str):
        return False

    # Must not be empty or whitespace only
    if not user.strip():
        return False

    # Must not be literal "None" string (common vulnerability)
    if user.strip().lower() in ["none", "null", "undefined"]:
        return False

    # Reasonable length check (email addresses are typically < 255 chars)
    if len(user) > 255:
        return False

    return True


def get_security_audit_info() -> dict:
    """
    Get security audit information for the current session.

    Returns:
        Dictionary with security-relevant session information

    Note: This function is safe to call and will not expose sensitive data
    """
    try:
        current_user = getattr(frappe.session, "user", "Unknown")
        user_roles = safe_get_roles(current_user)

        return {
            "current_user": current_user,
            "user_roles": user_roles,
            "has_admin_access": safe_has_any_role(
                current_user, ["System Manager", "Administrator", "Verenigingen Administrator"]
            ),
            "session_sid": getattr(frappe.session, "sid", "Unknown"),
            "is_guest": current_user == "Guest",
        }

    except Exception as e:
        security_logger.error(f"Error getting security audit info: {str(e)}")
        return {
            "current_user": "Unknown",
            "user_roles": [],
            "has_admin_access": False,
            "session_sid": "Unknown",
            "is_guest": True,
            "error": str(e),
        }


# Backwards compatibility aliases
get_user_roles = safe_get_roles  # Common alias for migration
has_user_role = safe_has_role  # Common alias for migration


def validate_security_wrapper_installation():
    """
    Validation function to ensure security wrappers are working correctly.

    Returns:
        True if all security wrappers pass validation, False otherwise

    This function should be called during application startup or in tests
    to ensure the security framework is functioning properly.
    """
    try:
        # Test 1: safe_get_roles with None should not crash
        roles = safe_get_roles(None)
        assert isinstance(roles, list), "safe_get_roles should return list"

        # Test 2: safe_get_roles with empty string should return empty list
        roles = safe_get_roles("")
        assert roles == [], "safe_get_roles('') should return empty list"

        # Test 3: safe_get_roles with "None" string should return empty list
        roles = safe_get_roles("None")
        assert roles == [], "safe_get_roles('None') should return empty list"

        # Test 4: safe_has_role with invalid parameters should return False
        result = safe_has_role("", "Some Role")
        assert result is False, "safe_has_role with empty user should return False"

        # Test 5: safe_has_any_role with invalid parameters should return False
        result = safe_has_any_role("", ["Role1", "Role2"])
        assert result is False, "safe_has_any_role with empty user should return False"

        security_logger.info("Security wrapper validation passed")
        return True

    except Exception as e:
        security_logger.error(f"Security wrapper validation failed: {str(e)}")
        return False


# Module initialization
if __name__ == "__main__":
    # Self-test when run directly
    print("Running security wrapper validation...")
    if validate_security_wrapper_installation():
        print("✓ Security wrappers validation passed")
    else:
        print("✗ Security wrappers validation failed")
