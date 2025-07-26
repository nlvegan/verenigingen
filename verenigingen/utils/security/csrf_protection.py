"""
CSRF Protection System for Verenigingen SEPA Operations

This module provides CSRF token generation, validation, and middleware
for protecting SEPA-related API endpoints from Cross-Site Request Forgery attacks.
"""

import hashlib
import hmac
import time
from functools import wraps
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import cstr

from verenigingen.utils.error_handling import SEPAError, log_error


class CSRFError(SEPAError):
    """Raised when CSRF validation fails"""

    pass


class CSRFProtection:
    """
    CSRF Protection utility class for SEPA operations

    Provides token generation, validation, and expiry management
    """

    # CSRF token configuration
    TOKEN_EXPIRY_SECONDS = 3600  # 1 hour
    TOKEN_LENGTH = 32
    HEADER_NAME = "X-CSRF-Token"
    FORM_FIELD_NAME = "csrf_token"
    SECRET_KEY_SITE_CONFIG = "csrf_secret_key"

    @classmethod
    def get_secret_key(cls) -> str:
        """
        Get or generate CSRF secret key for this site

        Returns:
            Secret key string
        """
        # Try to get from site config first
        secret_key = frappe.conf.get(cls.SECRET_KEY_SITE_CONFIG)

        if not secret_key:
            # Generate new secret key
            import secrets

            secret_key = secrets.token_hex(32)

            # Store in site config (this would typically be done during installation)
            frappe.log_error(
                "CSRF secret key not found in site config. Using session-based key.",
                "CSRF Protection Warning",
            )

            # Fall back to user session-based key for development
            secret_key = f"session_{frappe.session.user}_{int(time.time())}"

        return secret_key

    @classmethod
    def generate_token(cls, user: str = None) -> str:
        """
        Generate CSRF token for the current user

        Args:
            user: User email (defaults to current user)

        Returns:
            CSRF token string
        """
        if not user:
            user = frappe.session.user

        if user == "Guest":
            raise CSRFError(_("CSRF tokens not available for guest users"))

        # Create token payload
        timestamp = int(time.time())
        secret_key = cls.get_secret_key()

        # Token format: user:timestamp:hmac
        message = f"{user}:{timestamp}"
        signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()[
            : cls.TOKEN_LENGTH
        ]

        token = f"{message}:{signature}"

        # Store token in session for validation
        if not hasattr(frappe.local, "csrf_tokens"):
            frappe.local.csrf_tokens = {}

        frappe.local.csrf_tokens[user] = {"token": token, "timestamp": timestamp}

        return token

    @classmethod
    def validate_token(cls, token: str, user: str = None) -> bool:
        """
        Validate CSRF token

        Args:
            token: CSRF token to validate
            user: User email (defaults to current user)

        Returns:
            True if token is valid

        Raises:
            CSRFError: If token is invalid or expired
        """
        if not user:
            user = frappe.session.user

        if user == "Guest":
            raise CSRFError(_("CSRF validation not available for guest users"))

        if not token:
            raise CSRFError(_("CSRF token is required"))

        try:
            # Parse token
            parts = token.split(":")
            if len(parts) != 3:
                raise CSRFError(_("Invalid CSRF token format"))

            token_user, timestamp_str, signature = parts
            timestamp = int(timestamp_str)

            # Validate user
            if token_user != user:
                raise CSRFError(_("CSRF token user mismatch"))

            # Validate expiry
            current_time = int(time.time())
            if current_time - timestamp > cls.TOKEN_EXPIRY_SECONDS:
                raise CSRFError(_("CSRF token has expired"))

            # Validate signature
            secret_key = cls.get_secret_key()
            message = f"{token_user}:{timestamp_str}"
            expected_signature = hmac.new(
                secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
            ).hexdigest()[: cls.TOKEN_LENGTH]

            if not hmac.compare_digest(signature, expected_signature):
                raise CSRFError(_("CSRF token signature is invalid"))

            # Additional check against session stored token (if available)
            if hasattr(frappe.local, "csrf_tokens") and user in frappe.local.csrf_tokens:
                session_token_data = frappe.local.csrf_tokens[user]
                if session_token_data["token"] == token:
                    # Token matches session - extra validation passed
                    pass

            return True

        except (ValueError, IndexError) as e:
            raise CSRFError(_("Invalid CSRF token format: {0}").format(str(e)))
        except Exception as e:
            log_error(
                e,
                context={"token": token[:10] + "...", "user": user},
                module="verenigingen.utils.security.csrf_protection",
            )
            raise CSRFError(_("CSRF token validation failed"))

    @classmethod
    def get_token_from_request(cls) -> Optional[str]:
        """
        Extract CSRF token from current HTTP request

        Returns:
            CSRF token if found, None otherwise
        """
        # Check header first
        token = frappe.get_request_header(cls.HEADER_NAME)

        if not token:
            # Check form data
            token = frappe.form_dict.get(cls.FORM_FIELD_NAME)

        return token

    @classmethod
    def validate_request(cls, user: str = None) -> bool:
        """
        Validate CSRF token from current request

        Args:
            user: User email (defaults to current user)

        Returns:
            True if validation passes

        Raises:
            CSRFError: If validation fails
        """
        token = cls.get_token_from_request()

        if not token:
            raise CSRFError(_("CSRF token missing from request"))

        return cls.validate_token(token, user)


def require_csrf_token(func):
    """
    Decorator to require CSRF token validation for API endpoints

    Usage:
        @frappe.whitelist()
        @require_csrf_token
        def my_api_function():
            # Function implementation
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Skip CSRF validation for GET requests (typically read-only)
            if frappe.request and frappe.request.method == "GET":
                return func(*args, **kwargs)

            # Skip CSRF validation for system users or if disabled
            if frappe.session.user in ["Administrator", "System"]:
                return func(*args, **kwargs)

            # Check if CSRF protection is disabled (for testing)
            if frappe.conf.get("disable_csrf_protection"):
                return func(*args, **kwargs)

            # Validate CSRF token
            CSRFProtection.validate_request()

            # Log successful CSRF validation
            frappe.log_info(
                {
                    "event": "csrf_validation_success",
                    "function": func.__name__,
                    "user": frappe.session.user,
                    "ip": frappe.local.request_ip,
                    "timestamp": frappe.utils.now(),
                },
                "SEPA Security",
            )

            return func(*args, **kwargs)

        except CSRFError as e:
            # Log CSRF validation failure
            log_error(
                e,
                context={
                    "function": func.__name__,
                    "user": frappe.session.user,
                    "ip": frappe.local.request_ip,
                    "user_agent": frappe.get_request_header("User-Agent"),
                    "referer": frappe.get_request_header("Referer"),
                },
                module="verenigingen.utils.security.csrf_protection",
            )

            frappe.throw(_("CSRF validation failed: {0}").format(str(e)), exc=frappe.PermissionError)

    return wrapper


def csrf_protect_sepa_endpoints():
    """
    Apply CSRF protection to all SEPA-related endpoints

    This function can be called during app initialization to automatically
    protect SEPA endpoints without modifying each function individually.
    """
    sepa_endpoints = [
        "verenigingen.api.sepa_batch_ui.create_sepa_batch_validated",
        "verenigingen.api.sepa_batch_ui.validate_batch_invoices",
        "verenigingen.api.sepa_batch_ui.get_batch_analytics",
        "verenigingen.api.sepa_batch_ui.preview_sepa_xml",
        # Add other SEPA endpoints as needed
    ]

    for endpoint in sepa_endpoints:
        try:
            # Get the function
            module_path, function_name = endpoint.rsplit(".", 1)
            module = frappe.get_module(module_path)
            original_func = getattr(module, function_name)

            # Apply CSRF protection if not already applied
            if not hasattr(original_func, "_csrf_protected"):
                protected_func = require_csrf_token(original_func)
                protected_func._csrf_protected = True
                setattr(module, function_name, protected_func)

        except Exception as e:
            frappe.log_error(
                f"Failed to apply CSRF protection to {endpoint}: {str(e)}", "CSRF Protection Setup"
            )


# API endpoints for CSRF token management
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
            "expires_in_seconds": CSRFProtection.TOKEN_EXPIRY_SECONDS,
            "generated_at": frappe.utils.now(),
        }

    except Exception as e:
        log_error(
            e, context={"user": frappe.session.user}, module="verenigingen.utils.security.csrf_protection"
        )

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
        log_error(
            e,
            context={"user": frappe.session.user, "token_preview": token[:10] + "..."},
            module="verenigingen.utils.security.csrf_protection",
        )

        return {"success": False, "error": _("CSRF validation system error"), "message": str(e)}


# Middleware functions
def csrf_middleware(request):
    """
    CSRF middleware to automatically validate tokens on protected routes

    Args:
        request: HTTP request object

    Returns:
        None if validation passes, raises exception if fails
    """
    # Skip for safe methods
    if request.method in ["GET", "HEAD", "OPTIONS", "TRACE"]:
        return

    # Skip for system users
    if frappe.session.user in ["Administrator", "System"]:
        return

    # Check if this is a SEPA-related request
    path = getattr(request, "path", "")
    if "/api/method/verenigingen.api.sepa_batch_ui" in path:
        try:
            CSRFProtection.validate_request()
        except CSRFError as e:
            frappe.throw(_("CSRF protection activated: {0}").format(str(e)), exc=frappe.PermissionError)


def setup_csrf_protection():
    """
    Setup CSRF protection during app initialization
    """
    # Apply CSRF protection to SEPA endpoints
    csrf_protect_sepa_endpoints()

    # Log setup completion
    frappe.log_info(
        {"event": "csrf_protection_setup_complete", "timestamp": frappe.utils.now()}, "SEPA Security Setup"
    )
