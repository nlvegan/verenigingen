"""
CSRF Protection Wrapper - Uses Frappe's Native Implementation

This module provides a thin compatibility wrapper around Frappe Framework's
native CSRF protection. The custom HMAC-based implementation has been archived
as it was redundant with Frappe's built-in functionality.

See archived/security_implementations/CSRF_ARCHIVAL_NOTES.md for details.
"""

import frappe
from frappe import _


class CSRFError(frappe.ValidationError):
    """Raised when CSRF validation fails"""

    pass


class CSRFProtection:
    """
    Compatibility wrapper for Frappe's native CSRF protection

    This class provides the same interface as the archived custom implementation
    but delegates all work to Frappe's native CSRF system.
    """

    # Constants for API compatibility
    HEADER_NAME = "X-Frappe-CSRF-Token"
    FORM_FIELD_NAME = "csrf_token"

    @classmethod
    def generate_token(cls, user: str = None) -> str:
        """
        Generate CSRF token using Frappe's native implementation

        Args:
            user: User email (ignored - uses current session user)

        Returns:
            CSRF token string from Frappe session
        """
        return frappe.sessions.get_csrf_token()

    @classmethod
    def validate_token(cls, token: str, user: str = None) -> bool:
        """
        Validate CSRF token against Frappe's session token

        Args:
            token: CSRF token to validate
            user: User email (ignored - uses current session)

        Returns:
            True if token is valid

        Raises:
            CSRFError: If token is invalid
        """
        if not token:
            raise CSRFError(_("CSRF token is required"))

        # Get expected token from session
        expected_token = frappe.session.data.get("csrf_token")

        if not expected_token:
            # No session token - either guest user or session not initialized
            if frappe.session.user == "Guest":
                raise CSRFError(_("CSRF validation not available for guest users"))
            raise CSRFError(_("No CSRF token in session"))

        # Validate token matches
        if token != expected_token:
            raise CSRFError(_("CSRF token is invalid"))

        return True

    @classmethod
    def get_token_from_request(cls) -> str:
        """
        Extract CSRF token from current HTTP request

        Returns:
            CSRF token if found, None otherwise
        """
        # Check Frappe's standard CSRF header
        token = frappe.get_request_header("X-Frappe-CSRF-Token")

        if not token:
            # Check custom header (for backwards compatibility)
            token = frappe.get_request_header("X-CSRF-Token")

        if not token:
            # Check form data
            token = frappe.form_dict.get("csrf_token")

        if not token:
            # Fallback to session token
            token = frappe.session.data.get("csrf_token")

        return token

    @classmethod
    def validate_request(cls, user: str = None) -> bool:
        """
        Validate CSRF token from current request

        NOTE: Frappe already validates CSRF automatically in auth.py:83-98
        for all POST/PUT/DELETE/PATCH requests. This method exists for
        explicit validation if needed, but is usually redundant.

        Args:
            user: User email (ignored - uses current session)

        Returns:
            True if validation passes

        Raises:
            CSRFError: If validation fails
        """
        # Skip validation if no request context (background jobs, migrations)
        if not hasattr(frappe.local, "request") or not frappe.local.request:
            return True

        # Skip for safe methods
        if frappe.request.method in ["GET", "HEAD", "OPTIONS", "TRACE"]:
            return True

        # Skip if CSRF is disabled in config
        if frappe.conf.get("ignore_csrf"):
            return True

        # Get token from request
        token = cls.get_token_from_request()

        if not token:
            raise CSRFError(_("CSRF token missing from request"))

        # Validate token
        return cls.validate_token(token)


# API endpoints for backwards compatibility
@frappe.whitelist(allow_guest=False)
def get_csrf_token():
    """
    API endpoint to get CSRF token for current user

    Returns:
        Dictionary with CSRF token and metadata
    """
    try:
        token = CSRFProtection.generate_token()

        return {
            "success": True,
            "csrf_token": token,
            "header_name": CSRFProtection.HEADER_NAME,
            "form_field_name": CSRFProtection.FORM_FIELD_NAME,
            "generated_at": frappe.utils.now(),
        }

    except Exception as e:
        frappe.log_error(f"Failed to generate CSRF token: {str(e)}", "CSRF Token Generation")
        return {"success": False, "error": _("Failed to generate CSRF token"), "message": str(e)}


@frappe.whitelist(allow_guest=False)
def validate_csrf_token(token: str):
    """
    API endpoint to validate CSRF token

    Args:
        token: CSRF token to validate

    Returns:
        Dictionary with validation result
    """
    try:
        is_valid = CSRFProtection.validate_token(token)

        return {"success": True, "valid": is_valid, "message": _("CSRF token is valid")}

    except CSRFError as e:
        return {
            "success": True,
            "valid": False,
            "error": str(e),
            "message": _("CSRF token validation failed"),
        }
    except Exception as e:
        frappe.log_error(f"CSRF validation error: {str(e)}", "CSRF Token Validation")
        return {"success": False, "error": _("CSRF validation system error"), "message": str(e)}


def require_csrf_token(func):
    """
    Compatibility decorator for CSRF token validation (no-op since Frappe handles this natively)

    NOTE: This decorator now does nothing. Frappe Framework automatically validates
    CSRF tokens for all POST/PUT/DELETE/PATCH requests in auth.py:83-98.

    This stub exists for backwards compatibility with code that imports this decorator.

    Usage:
        @frappe.whitelist()
        @require_csrf_token  # This is now redundant but won't break anything
        def my_api_function():
            # Function implementation
    """
    # Simply return the original function unchanged
    # Frappe's native CSRF protection handles validation automatically
    return func


def setup_csrf_protection():
    """
    Setup CSRF protection (no-op since using Frappe's native implementation)

    This function exists for backwards compatibility with initialization code.
    """
    pass
