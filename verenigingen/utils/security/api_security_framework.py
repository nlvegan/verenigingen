"""
Comprehensive API Security Framework for Verenigingen Application

This framework provides a unified, layered security approach that standardizes
security controls across all API endpoints. It integrates authentication,
authorization, input validation, rate limiting, audit logging, and error handling
into a cohesive system designed specifically for association management operations.

Architecture:
- Decorator-based security layers
- Classification-driven security profiles
- Context-aware permission validation
- Performance-optimized implementation
- Comprehensive audit trails
"""

import json
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Union

import frappe
from frappe import _
from frappe.utils import cstr

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.error_handling import log_error

# Lazy import to avoid circular dependency - get_auth_manager imported when needed
from verenigingen.utils.security.csrf_protection import CSRFProtection

# Note: Removed SEPA rate limiter import - now using COR-based rate limiting
from verenigingen.utils.security.types import (
    AuditEventType,
    AuditSeverity,
    EnvironmentLevel,
    OperationType,
    SecurityLevel,
)
from verenigingen.utils.validation.api_validators import APIValidator


class SecurityProfile:
    """Security profile defining requirements for each security level"""

    def __init__(
        self,
        level: SecurityLevel,
        required_roles: List[str] = None,
        required_permissions: List[str] = None,
        requires_csrf: bool = True,
        requires_audit: bool = True,
        input_validation: bool = True,
        ip_restrictions: bool = False,
        business_hours_only: bool = False,
        max_request_size: int = 1024 * 1024,  # 1MB default
        allowed_methods: List[str] = None,
        allowed_environments: List[EnvironmentLevel] = None,
    ):
        self.level = level
        self.required_roles = required_roles or []
        self.required_permissions = required_permissions or []
        # Note: Rate limiting now handled entirely by COR records
        self.requires_csrf = requires_csrf
        self.requires_audit = requires_audit
        self.input_validation = input_validation
        self.ip_restrictions = ip_restrictions
        self.business_hours_only = business_hours_only
        self.max_request_size = max_request_size
        self.allowed_methods = allowed_methods or ["GET", "POST"]
        self.allowed_environments = allowed_environments or [
            EnvironmentLevel.PRODUCTION,
            EnvironmentLevel.STAGING,
            EnvironmentLevel.DEVELOPMENT,
        ]


class APISecurityFramework:
    """
    Main API Security Framework Class

    Provides comprehensive security controls with standardized patterns
    for all API endpoints in the Verenigingen application.
    """

    # Predefined security profiles
    SECURITY_PROFILES = {
        SecurityLevel.CRITICAL: SecurityProfile(
            level=SecurityLevel.CRITICAL,
            required_roles=["System Manager", "Verenigingen Administrator"],
            requires_csrf=True,
            requires_audit=True,
            input_validation=True,
            ip_restrictions=True,
            business_hours_only=False,
            max_request_size=512 * 1024,  # 512KB
            allowed_methods=["POST"],
        ),
        SecurityLevel.HIGH: SecurityProfile(
            level=SecurityLevel.HIGH,
            required_roles=["System Manager", "Verenigingen Administrator", "Verenigingen Manager"],
            requires_csrf=True,
            requires_audit=True,
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=1024 * 1024,  # 1MB
            allowed_methods=["GET", "POST"],
        ),
        SecurityLevel.MEDIUM: SecurityProfile(
            level=SecurityLevel.MEDIUM,
            required_roles=[
                "System Manager",
                "Verenigingen Administrator",
                "Verenigingen Manager",
                "Verenigingen Staff",
            ],
            requires_csrf=False,  # Most read operations
            requires_audit=False,  # Reduce audit volume - only audit critical/high operations
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=2 * 1024 * 1024,  # 2MB
            allowed_methods=["GET", "POST"],
        ),
        SecurityLevel.LOW: SecurityProfile(
            level=SecurityLevel.LOW,
            required_roles=[],  # Any authenticated user
            requires_csrf=False,
            requires_audit=False,  # No audit logging for low security operations
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=4 * 1024 * 1024,  # 4MB
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        ),
        SecurityLevel.PUBLIC: SecurityProfile(
            level=SecurityLevel.PUBLIC,
            required_roles=[],
            requires_csrf=False,
            requires_audit=False,
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=10 * 1024 * 1024,  # 10MB
            allowed_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        ),
    }

    # Operation type to security level mapping
    OPERATION_SECURITY_MAPPING = {
        OperationType.FINANCIAL: SecurityLevel.CRITICAL,
        OperationType.MEMBER_DATA: SecurityLevel.HIGH,
        OperationType.ADMIN: SecurityLevel.CRITICAL,
        OperationType.REPORTING: SecurityLevel.MEDIUM,
        OperationType.UTILITY: SecurityLevel.LOW,
        OperationType.PUBLIC: SecurityLevel.PUBLIC,
        OperationType.WEBHOOK_PROCESSING: SecurityLevel.PUBLIC,  # Special handling for configurable rate limits
    }

    # Role Profile to Security Level mapping
    # This replaces hardcoded role lists with role profile-based access
    ROLE_PROFILE_SECURITY_MAPPING = {
        "Verenigingen System Administrator": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],
        "Verenigingen Administrator": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],
        "Verenigingen Treasurer": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
        ],  # Full financial access
        "Verenigingen National Board Member": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
        ],  # National oversight
        "Verenigingen Manager": [SecurityLevel.HIGH, SecurityLevel.MEDIUM, SecurityLevel.LOW],
        "Verenigingen Board Member": [
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],  # + contextual for their chapter
        "Verenigingen Kascommissie": [SecurityLevel.MEDIUM, SecurityLevel.LOW],  # Audit/compliance access
        "Verenigingen Staff": [SecurityLevel.MEDIUM, SecurityLevel.LOW],
        "Verenigingen Team Leader": [SecurityLevel.LOW],  # + contextual for their team
        "Verenigingen Auditor": [SecurityLevel.LOW],  # Read-only audit access
        "Verenigingen Member": [SecurityLevel.LOW],
        "Verenigingen Volunteer": [
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],  # MEDIUM for self_service_only operations
        "Verenigingen Webhook User": [SecurityLevel.PUBLIC, SecurityLevel.LOW],
    }

    def __init__(self):
        """Initialize the security framework"""
        # Initialize audit logger as None to avoid circular dependency
        # It will be lazily initialized when first needed
        self.audit_logger = None
        self.auth_manager = None  # Lazy loading to avoid circular import
        # Note: Removed SEPA rate limiter - now using COR-based rate limiting directly
        self.csrf_protection = CSRFProtection()

        # Validate role profile configuration on initialization
        self._validate_role_profile_configuration()

    def _get_audit_logger(self):
        """Lazily initialize audit logger to avoid circular dependency"""
        if self.audit_logger is None:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            self.audit_logger = get_audit_logger()
        return self.audit_logger

    def _safe_has_csrf_header(self) -> bool:
        """Safely check for CSRF headers, handling cases where there's no request context"""
        try:
            return bool(
                frappe.get_request_header("X-Frappe-CSRF-Token") or frappe.get_request_header("X-CSRF-Token")
            )
        except (RuntimeError, AttributeError):
            return False

    def _is_api_key_authentication(self) -> bool:
        """Check if the current request is using API key authentication"""
        try:
            auth_header = frappe.get_request_header("Authorization")
            frappe.logger("verenigingen.api_security").info(
                f"API key detection: Authorization header = {auth_header[:20] + '...' if auth_header else 'None'}"
            )
            if auth_header and auth_header.startswith("token "):
                frappe.logger("verenigingen.api_security").info("API key authentication detected")
                return True
            frappe.logger("verenigingen.api_security").info("No API key authentication detected")
            return False
        except (RuntimeError, AttributeError) as e:
            frappe.logger("verenigingen.api_security").info(f"API key detection error: {e}")
            return False

    def _get_client_ip(self) -> str:
        """Get client IP address, handling test environments gracefully"""
        try:
            if hasattr(frappe.local, "request") and frappe.local.request:
                return frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
        except (AttributeError, RuntimeError):
            pass
        return "test_environment"

    def get_security_profile(self, level: SecurityLevel) -> SecurityProfile:
        """Get security profile for given level"""
        return self.SECURITY_PROFILES.get(level, self.SECURITY_PROFILES[SecurityLevel.MEDIUM])

    def classify_endpoint(
        self, func: Callable, operation_type: OperationType = None, custom_level: SecurityLevel = None
    ) -> SecurityLevel:
        """
        Classify endpoint security level based on operation type or custom override

        Args:
            func: Function to classify
            operation_type: Type of operation
            custom_level: Override security level

        Returns:
            SecurityLevel for the endpoint
        """
        if custom_level:
            return custom_level

        if operation_type:
            return self.OPERATION_SECURITY_MAPPING.get(operation_type, SecurityLevel.MEDIUM)

        # Heuristic classification based on function name and module
        func_name = func.__name__.lower()
        # module_name = getattr(func, "__module__", "").lower()  # Unused variable

        # Critical operations
        if any(keyword in func_name for keyword in ["create", "delete", "process", "execute", "admin"]):
            if any(keyword in func_name for keyword in ["batch", "sepa", "payment", "financial"]):
                return SecurityLevel.CRITICAL

        # High security operations
        if any(keyword in func_name for keyword in ["member", "user", "update", "modify"]):
            return SecurityLevel.HIGH

        # Medium security operations
        if any(keyword in func_name for keyword in ["get", "list", "report", "analytics"]):
            return SecurityLevel.MEDIUM

        # Default to medium security
        return SecurityLevel.MEDIUM

    def get_current_environment(self) -> EnvironmentLevel:
        """
        Detect the current deployment environment.

        Returns:
            EnvironmentLevel: Current environment (DEVELOPMENT, STAGING, or PRODUCTION)
        """
        # Check Frappe developer mode first
        if frappe.conf.get("developer_mode", False):
            return EnvironmentLevel.DEVELOPMENT

        # Check custom environment configuration
        env = frappe.conf.get("deployment_environment")
        if env:
            try:
                return EnvironmentLevel(env.lower())
            except ValueError:
                pass  # Invalid environment, fall through to default

        # Check site-specific environment indicator
        site_env = frappe.conf.get("environment")
        if site_env:
            try:
                return EnvironmentLevel(site_env.lower())
            except ValueError:
                pass  # Invalid environment, fall through to default

        # Default to production for safety - restricts access by default
        return EnvironmentLevel.PRODUCTION

    def validate_environment_access(
        self, profile: SecurityProfile, current_env: EnvironmentLevel = None
    ) -> bool:
        """
        Validate that the current environment is allowed for this security profile.

        Args:
            profile: Security profile containing environment restrictions
            current_env: Current environment (detected if not provided)

        Returns:
            bool: True if access is allowed in current environment

        Raises:
            VPermissionError: If current environment is not allowed
        """
        if current_env is None:
            current_env = self.get_current_environment()

        if current_env not in profile.allowed_environments:
            allowed_envs = [env.value for env in profile.allowed_environments]
            raise VPermissionError(
                _(
                    f"Function not available in {current_env.value} environment. "
                    f"Allowed environments: {', '.join(allowed_envs)}"
                )
            )

        return True

    def _validate_role_profile_configuration(self):
        """Validate that all configured role profiles exist in the system"""
        try:
            missing_profiles = []
            invalid_mappings = []

            for profile_name, security_levels in self.ROLE_PROFILE_SECURITY_MAPPING.items():
                # Check if role profile exists
                if not frappe.db.exists("Role Profile", profile_name):
                    missing_profiles.append(profile_name)

                # Check if security levels are valid
                for level in security_levels:
                    if not isinstance(level, SecurityLevel):
                        invalid_mappings.append(f"{profile_name}: {level}")

            # Log warnings for missing profiles but don't fail initialization
            if missing_profiles:
                frappe.logger("verenigingen.api_security").warning(
                    f"Security framework configured with non-existent role profiles: {missing_profiles}. "
                    f"These will be ignored until role profiles are created."
                )

            if invalid_mappings:
                frappe.logger("verenigingen.api_security").error(
                    f"Invalid security level mappings found: {invalid_mappings}"
                )

            # Log successful validation
            valid_profiles = [
                p for p in self.ROLE_PROFILE_SECURITY_MAPPING.keys() if p not in missing_profiles
            ]
            if valid_profiles:
                frappe.logger("verenigingen.api_security").debug(
                    f"Security framework initialized with {len(valid_profiles)} valid role profile mappings"
                )

        except Exception as e:
            # Don't fail initialization, but log the error
            frappe.logger("verenigingen.api_security").error(
                f"Error validating role profile configuration: {str(e)}"
            )

    def _get_user_role_profiles(self, user: str = None) -> List[str]:
        """Get user's role profiles from Frappe's Role Profile system with caching"""
        if not user:
            user = frappe.session.user

        # Use cache to avoid repeated database queries (5 minute cache)
        cache_key = f"user_role_profiles:{user}"
        cached_profiles = frappe.cache.get_value(cache_key)

        if cached_profiles is not None:
            return cached_profiles

        # SECURITY FIX: Get user's directly assigned role profiles only
        try:
            role_profiles = []

            # Method 1: Get role profile directly assigned to user in User DocType
            user_role_profile = frappe.db.get_value("User", user, "role_profile_name")
            if user_role_profile:
                # Verify the role profile actually exists
                if frappe.db.exists("Role Profile", user_role_profile):
                    role_profiles.append(user_role_profile)
                    frappe.logger("verenigingen.api_security").debug(
                        f"Found direct role profile assignment: {user_role_profile}"
                    )
                else:
                    frappe.logger("verenigingen.api_security").warning(
                        f"User {user} has invalid role profile assignment: {user_role_profile}"
                    )

            # Note: We intentionally do NOT query role intersections as that would
            # create privilege escalation vulnerabilities (QCE finding)

            # Cache the result for 24 hours (role profiles are static data)
            frappe.cache.set_value(cache_key, role_profiles, expires_in_sec=86400)

            return role_profiles

        except Exception as e:
            frappe.logger("verenigingen.api_security").error(
                f"Failed to get role profiles for user {user}: {str(e)}"
            )
            return []

    @staticmethod
    def invalidate_user_role_cache(user: str = None):
        """Invalidate cached role profiles for a user (or all users if none specified)"""
        if user:
            # Invalidate specific user's cache
            cache_key = f"user_role_profiles:{user}"
            frappe.cache.delete_value(cache_key)
            frappe.logger("verenigingen.api_security").info(
                f"Invalidated role profile cache for user: {user}"
            )
        else:
            # Invalidate all user role profile caches (nuclear option)
            # Get all cache keys matching the pattern and delete them
            try:
                import redis

                redis_client = frappe.cache.redis_client
                pattern = "user_role_profiles:*"
                keys = redis_client.keys(pattern)
                if keys:
                    redis_client.delete(*keys)
                    frappe.logger("verenigingen.api_security").info(
                        f"Invalidated {len(keys)} user role profile cache entries"
                    )
            except Exception as e:
                frappe.logger("verenigingen.api_security").error(
                    f"Failed to invalidate role profile caches: {str(e)}"
                )

    def _role_profile_grants_access(self, role_profile: str, required_level: SecurityLevel) -> bool:
        """Check if a role profile grants access to the required security level"""
        allowed_levels = self.ROLE_PROFILE_SECURITY_MAPPING.get(role_profile, [])
        return required_level in allowed_levels

    def _validate_role_profile_access(self, required_level: SecurityLevel, user: str = None) -> bool:
        """Check if user's role profiles grant required security level"""
        user_profiles = self._get_user_role_profiles(user)

        for profile in user_profiles:
            if self._role_profile_grants_access(profile, required_level):
                frappe.logger("verenigingen.api_security").debug(
                    f"Access granted via role profile: {profile} → {required_level.value}"
                )
                return True

        frappe.logger("verenigingen.api_security").debug(
            f"Access denied: User role profiles {user_profiles} do not grant {required_level.value} access"
        )
        return False

    def validate_authentication(self, profile: SecurityProfile, user: str = None) -> bool:
        """Validate user authentication and authorization"""
        if not user:
            user = frappe.session.user

        # Public endpoints don't require authentication
        if profile.level == SecurityLevel.PUBLIC:
            return True

        # Check if user is authenticated
        if user == "Guest":
            raise VPermissionError(_("Authentication required for this endpoint"))

        # Primary authorization: Check role profile access
        if self._validate_role_profile_access(profile.level, user):
            return True

        # Fallback authorization: Check hardcoded required roles (for backwards compatibility)
        if profile.required_roles:
            user_roles = frappe.get_roles(user)
            if any(role in user_roles for role in profile.required_roles):
                frappe.logger("verenigingen.api_security").debug(
                    f"Access granted via fallback hardcoded roles: {profile.required_roles}"
                )
                return True

        # Get user roles once for efficiency
        user_roles = frappe.get_roles(user)

        # System Manager should have access to low and medium security operations
        try:
            has_system_manager = "System Manager" in user_roles
            is_low_or_medium = profile.level in [SecurityLevel.LOW, SecurityLevel.MEDIUM]

            frappe.logger("verenigingen.api_security").info(
                f"System Manager check: has_role={has_system_manager}, level={profile.level.value}, is_low_or_medium={is_low_or_medium}"
            )

            if has_system_manager and is_low_or_medium:
                frappe.logger("verenigingen.api_security").info(
                    f"Access granted: System Manager has access to {profile.level.value} operations"
                )
                return True
        except Exception as e:
            frappe.logger("verenigingen.api_security").error(f"Error in System Manager check: {str(e)}")

        # Collect user info for error message
        user_profiles = self._get_user_role_profiles(user)

        # Deny access with detailed error message
        error_details = []
        if user_profiles:
            error_details.append(f"Role profiles: {', '.join(user_profiles)}")
        if user_roles:
            error_details.append(f"Individual roles: {', '.join(user_roles)}")

        raise VPermissionError(
            _("Access denied. Required security level: {0}. Your access: {1}").format(
                profile.level.value, "; ".join(error_details) if error_details else "No roles assigned"
            )
        )

        return False

    def validate_request_method(self, profile: SecurityProfile) -> bool:
        """Validate HTTP method is allowed"""
        if not frappe.request:
            return True

        method = frappe.request.method

        # DEBUG: Add detailed logging for method detection issues
        # Safely check for JSON data without triggering Werkzeug's JSON parsing
        has_json_data = False
        if hasattr(frappe.request, "content_type"):
            content_type = getattr(frappe.request, "content_type", "")
            has_json_data = content_type and "application/json" in content_type

        debug_info = {
            "detected_method": method,
            "allowed_methods": list(profile.allowed_methods),
            "request_headers": dict(frappe.request.headers) if hasattr(frappe.request, "headers") else {},
            "content_type": getattr(frappe.request, "content_type", "N/A"),
            "has_form_data": bool(getattr(frappe.request, "form", None)),
            "has_json_data": has_json_data,
            "request_url": getattr(frappe.request, "url", "N/A"),
        }

        frappe.logger("verenigingen.api_security").info(f"HTTP Method Validation Debug: {debug_info}")

        if method not in profile.allowed_methods:
            # Enhanced error with debug info
            error_msg = _("Method {0} not allowed. Allowed methods: {1}. Debug: {2}").format(
                method, ", ".join(profile.allowed_methods), debug_info
            )
            frappe.logger("verenigingen.api_security").error(f"Method validation failed: {error_msg}")
            raise VPermissionError(error_msg)

        return True

    def validate_request_size(self, profile: SecurityProfile) -> bool:
        """Validate request size limits"""
        if not frappe.request:
            return True

        content_length = frappe.request.headers.get("Content-Length")
        if content_length:
            try:
                size = int(content_length)
                if size > profile.max_request_size:
                    raise VValidationError(
                        _("Request too large. Maximum size: {0} bytes").format(profile.max_request_size)
                    )
            except ValueError:
                pass  # Invalid content-length header

        return True

    def validate_csrf_token(self, profile: SecurityProfile, func: Callable = None) -> bool:
        """Validate CSRF token if required"""
        if not profile.requires_csrf:
            return True

        # Skip CSRF validation when there's no HTTP request context (migrations, background jobs)
        if not hasattr(frappe, "request") or not frappe.request:
            return True

        # Skip for GET requests
        if frappe.request and frappe.request.method == "GET":
            return True

        # Skip CSRF validation if explicitly disabled (for testing)
        if frappe.conf.get("disable_csrf_protection"):
            return True

        # Skip for test environment detection
        if hasattr(frappe, "flags") and getattr(frappe.flags, "in_test", False):
            return True

        # Skip for migration context (when functions are called during migrations)
        if hasattr(frappe, "flags") and getattr(frappe.flags, "in_migrate", False):
            return True

        # Skip CSRF validation for API key authentication
        # API keys are not vulnerable to CSRF attacks since they're not browser-based
        if self._is_api_key_authentication():
            frappe.logger("verenigingen.api_security").info(
                "Skipping CSRF validation for API key authentication"
            )
            return True

        # Skip for specific functions that have compatibility issues
        if func and hasattr(func, "__name__"):
            func_name = func.__name__.lower()

            # Skip for membership operations that have CSRF compatibility issues
            skip_csrf_functions = [
                "approve_membership_application",
                "reject_membership_application",
                "create_membership_from_application",
                "update_membership_status",
            ]
            if func_name in skip_csrf_functions:
                return True

            # Skip for read-only operations (methods starting with 'get_', 'list_', 'check_', 'validate_')
            read_only_prefixes = ["get_", "list_", "check_", "validate_", "test_", "analyze_"]
            if any(func_name.startswith(prefix) for prefix in read_only_prefixes):
                return True

        try:
            self.csrf_protection.validate_request()
            return True
        except RuntimeError as e:
            # Handle cases where request object is not bound (migration, background jobs)
            if "object is not bound" in str(e):
                frappe.logger("verenigingen.api_security").debug(
                    f"CSRF validation skipped - no request context: {str(e)}"
                )
                return True
            # Re-raise other runtime errors
            raise VPermissionError(_("CSRF validation failed: {0}").format(str(e)))
        except Exception as e:
            # Log with more detail for debugging
            self._get_audit_logger().log_event(
                AuditEventType.CSRF_VALIDATION_FAILED,
                AuditSeverity.WARNING,
                details={
                    "error": str(e),
                    "ip": getattr(frappe.local, "request_ip", "unknown"),
                    "function": func.__name__ if func else "unknown",
                    "method": frappe.request.method if frappe.request else "unknown",
                    "has_csrf_header": self._safe_has_csrf_header(),
                },
            )
            raise VPermissionError(_("CSRF validation failed: {0}").format(str(e)))

    def validate_rate_limits(self, profile: SecurityProfile, operation_key: str) -> bool:
        """Validate rate limits using COR records"""
        try:
            # Extract operation name from operation key
            # e.g., "verenigingen.integrations.mollie.api.payment_webhook.handle_mollie_payment_webhook"
            # -> "handle_mollie_payment_webhook"
            operation_name = operation_key.split(".")[-1] if "." in operation_key else operation_key

            # Try to find specific COR record for this operation
            cor_record = frappe.db.get_value(
                "Critical Operation Rule",
                {"operation_name": operation_name, "enabled": 1},
                ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"],
                as_dict=True,
            )

            # If no specific COR found, use generic fallback
            if not cor_record:
                cor_record = frappe.db.get_value(
                    "Critical Operation Rule",
                    {"operation_name": "_generic_api_fallback", "enabled": 1},
                    ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"],
                    as_dict=True,
                )

            # If still no COR found, refuse to proceed (no hardcoded fallback)
            if not cor_record:
                raise VPermissionError(
                    _("No rate limiting configuration found for operation: {0}").format(operation_name)
                )

            # Apply COR-based rate limiting
            max_calls = cor_record.rate_limit_calls
            period_seconds = cor_record.rate_limit_period_seconds
            scope = cor_record.rate_limit_scope or "per_user"

            # Build cache key based on scope
            if scope == "global":
                cache_key = f"cor_rate_limit:{operation_name}"
            elif scope == "per_ip":
                client_ip = frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
                cache_key = f"cor_rate_limit:{operation_name}:{client_ip}"
            else:  # per_user (default)
                cache_key = f"cor_rate_limit:{operation_name}:{frappe.session.user}"

            # Check current usage (ensure it's an integer)
            current_count = int(frappe.cache().get(cache_key) or 0)

            if current_count >= max_calls:
                raise VPermissionError(
                    _("Rate limit exceeded: {0}/{1} requests per {2} seconds for {3}").format(
                        current_count, max_calls, period_seconds, operation_name
                    )
                )

            # Increment counter with appropriate expiry
            frappe.cache().setex(cache_key, period_seconds, current_count + 1)
            return True

        except Exception as e:
            self._get_audit_logger().log_event(
                AuditEventType.RATE_LIMIT_EXCEEDED,
                AuditSeverity.WARNING,
                details={"operation": operation_key, "error": str(e)},
            )
            if isinstance(e, VPermissionError):
                raise  # Re-raise rate limit errors as-is
            else:
                raise VPermissionError(_("Rate limit validation failed: {0}").format(str(e)))

    def get_cor_rate_limit_headers(self, operation_key: str) -> Dict[str, str]:
        """Get COR-based rate limit headers for HTTP responses"""
        try:
            # Extract operation name from operation key
            operation_name = operation_key.split(".")[-1] if "." in operation_key else operation_key

            # Try to find specific COR record for this operation
            cor_record = frappe.db.get_value(
                "Critical Operation Rule",
                {"operation_name": operation_name, "enabled": 1},
                ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"],
                as_dict=True,
            )

            # If no specific COR found, use generic fallback
            if not cor_record:
                cor_record = frappe.db.get_value(
                    "Critical Operation Rule",
                    {"operation_name": "_generic_api_fallback", "enabled": 1},
                    ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"],
                    as_dict=True,
                )

            # If still no COR found, return empty headers
            if not cor_record:
                return {}

            max_calls = cor_record.rate_limit_calls
            period_seconds = cor_record.rate_limit_period_seconds
            scope = cor_record.rate_limit_scope or "per_user"

            # Build cache key based on scope (same logic as validate_rate_limits)
            if scope == "global":
                cache_key = f"cor_rate_limit:{operation_name}"
            elif scope == "per_ip":
                client_ip = frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
                cache_key = f"cor_rate_limit:{operation_name}:{client_ip}"
            else:  # per_user (default)
                cache_key = f"cor_rate_limit:{operation_name}:{frappe.session.user}"

            # Get current usage without modifying it
            current_count = int(frappe.cache().get(cache_key) or 0)
            remaining = max(0, max_calls - current_count)

            # Calculate reset time (current time + period)
            import time

            reset_time = int(time.time() + period_seconds)

            return {
                "X-RateLimit-Limit": str(max_calls),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_time),
                "X-RateLimit-Window": str(period_seconds),
            }

        except Exception as e:
            # Log the error but don't fail the request
            frappe.log_error(f"Failed to get COR rate limit headers: {str(e)}", "Rate Limiting Headers")
            return {}

    def validate_input_data(
        self, profile: SecurityProfile, operation_type: OperationType = None, **kwargs
    ) -> Dict[str, Any]:
        """Validate and sanitize input data"""
        if not profile.input_validation:
            return kwargs

        validated_data = {}

        # Determine appropriate max_length based on operation type
        max_length = 1000  # default
        if operation_type == OperationType.MEMBER_DATA:
            max_length = 5000  # Allow larger data for membership applications and member data
        elif operation_type == OperationType.REPORTING:
            max_length = 2000  # Allow larger data for reports

        for key, value in kwargs.items():
            # Skip None values
            if value is None:
                validated_data[key] = value
                continue

            # Sanitize string inputs
            if isinstance(value, str):
                # Decode HTML entities first (common issue with form submissions)
                import html

                decoded_value = html.unescape(value)
                validated_data[key] = APIValidator.sanitize_text(decoded_value, max_length=max_length)
            elif isinstance(value, dict):
                # Recursively validate dict inputs
                validated_data[key] = self._validate_dict_input(value, max_length)
            elif isinstance(value, list):
                # Validate list inputs
                validated_data[key] = self._validate_list_input(value, max_length)
            else:
                validated_data[key] = value

        return validated_data

    def _validate_dict_input(self, data: Dict[str, Any], max_length: int = 500) -> Dict[str, Any]:
        """Validate dictionary input data"""
        validated = {}
        for key, value in data.items():
            if isinstance(value, str):
                import html

                decoded_value = html.unescape(value)
                validated[key] = APIValidator.sanitize_text(decoded_value, max_length=max_length)
            elif isinstance(value, dict):
                validated[key] = self._validate_dict_input(value, max_length)
            elif isinstance(value, list):
                validated[key] = self._validate_list_input(value, max_length)
            else:
                validated[key] = value
        return validated

    def _validate_list_input(self, data: List[Any], max_length: int = 500) -> List[Any]:
        """Validate list input data"""
        validated = []
        for item in data:
            if isinstance(item, str):
                import html

                decoded_item = html.unescape(item)
                validated.append(APIValidator.sanitize_text(decoded_item, max_length=max_length))
            elif isinstance(item, dict):
                validated.append(self._validate_dict_input(item, max_length))
            elif isinstance(item, list):
                validated.append(self._validate_list_input(item, max_length))
            else:
                validated.append(item)
        return validated

    def _validate_self_service_access(self, **kwargs) -> bool:
        """Validate that user can only access their own data in self-service operations"""
        current_user = frappe.session.user

        # Skip validation for system users
        if current_user in ("Administrator", "Guest"):
            return True

        # Get user's member record
        try:
            user_member = frappe.db.get_value("Member", {"email": current_user}, "name")
        except Exception:
            user_member = None

        # Check various patterns for member identification in kwargs
        target_member = None
        member_fields = ["member", "member_name", "member_id", "volunteer"]

        for field in member_fields:
            if field in kwargs and kwargs[field]:
                if field == "volunteer":
                    # For volunteer operations, get the linked member
                    try:
                        volunteer_doc = frappe.get_doc("Volunteer", kwargs[field])
                        if hasattr(volunteer_doc, "member") and volunteer_doc.member:
                            target_member = volunteer_doc.member
                    except Exception:
                        pass
                else:
                    target_member = kwargs[field]
                break

        # SECURITY FIX: Handle implicit self-service operations more carefully
        if not target_member:
            # For truly implicit self-service operations (like expense submission), validate carefully
            if not user_member:
                raise VPermissionError(
                    _(
                        "Access denied: No member record found for user. Self-service operations require valid member account."
                    )
                )

            # Log this case for monitoring - implicit self-service should be rare
            frappe.logger("verenigingen.api_security").info(
                f"Implicit self-service operation detected for user {current_user}. "
                f"Consider adding explicit member identification to API parameters for better security."
            )

            # Allow implicit self-service but only for users with valid member records
            return True

        # If we found a target member, validate access
        if target_member and user_member:
            if target_member != user_member:
                raise VPermissionError(
                    _("Access denied: You can only perform this operation on your own data")
                )
        elif target_member and not user_member:
            raise VPermissionError(_("Access denied: Unable to verify member access for this user"))

        return True

    def _validate_self_service_request_content(self, user_member, **kwargs) -> bool:
        """
        Deep validation of request content for self-service operations.
        This catches parameter tampering where users try to access other users' data.
        """
        violations = []

        def inspect_data(data, path=""):
            """Recursively inspect data for member/volunteer references"""
            if isinstance(data, dict):
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key

                    # Check for member-related fields
                    if key in ["member", "member_name", "member_id"]:
                        if value and value != user_member:
                            violations.append(
                                {"field": current_path, "attempted_value": value, "user_member": user_member}
                            )

                    # Check for volunteer-related fields
                    elif key in ["volunteer", "volunteer_name", "volunteer_id"]:
                        if value:
                            try:
                                # Get member linked to this volunteer
                                volunteer_member = frappe.db.get_value("Volunteer", value, "member")
                                if volunteer_member and volunteer_member != user_member:
                                    violations.append(
                                        {
                                            "field": current_path,
                                            "attempted_value": value,
                                            "linked_member": volunteer_member,
                                            "user_member": user_member,
                                        }
                                    )
                            except Exception:
                                # If volunteer doesn't exist, that's also suspicious
                                violations.append(
                                    {
                                        "field": current_path,
                                        "attempted_value": value,
                                        "error": "Invalid volunteer reference",
                                    }
                                )

                    # Recursively check nested structures
                    elif isinstance(value, (dict, list)):
                        inspect_data(value, current_path)

            elif isinstance(data, list):
                for i, item in enumerate(data):
                    inspect_data(item, f"{path}[{i}]")

        # Inspect all parameters
        for key, value in kwargs.items():
            if isinstance(value, (dict, list)):
                inspect_data(value, key)

        # If violations found, log and raise error
        if violations:
            self._get_audit_logger().log_event(
                AuditEventType.SELF_SERVICE_VIOLATION,
                AuditSeverity.ERROR,
                details={
                    "user": frappe.session.user,
                    "user_member": user_member,
                    "violations": violations,
                    "function": getattr(frappe.local, "form_dict", {}).get("cmd", "unknown"),
                    "ip_address": self._get_client_ip(),
                },
            )

            raise VPermissionError(
                _(
                    "Access denied: Self-service operations can only be performed on your own data. "
                    "Attempted access to other member/volunteer data has been logged."
                )
            )

        return True

    def check_critical_operation_integration(self, func: Callable, **kwargs) -> dict:
        """
        Check if this API function should use critical operations framework (with caching)

        This integrates the API security framework with the critical operations registry
        to provide enhanced security for operations that have been classified as critical.
        """
        func_name = func.__name__
        module_name = func.__module__

        # Cache the operation check to avoid repeated registry lookups
        cache_key = f"critical_op_check:{module_name}.{func_name}"
        cached_result = frappe.cache.get_value(cache_key)

        if cached_result is not None:
            return cached_result

        # Import here to avoid circular dependencies
        try:
            from verenigingen.utils.secure_operations import get_critical_operations_registry

            registry = get_critical_operations_registry()

            # Check various potential operation names
            potential_operation_names = [
                func_name,
                f"{module_name.split('.')[-1]}_{func_name}",
                f"api_{func_name}",
            ]

            for operation_name in potential_operation_names:
                config = registry.get_operation_config(operation_name)
                if config:
                    result = {
                        "is_critical": True,
                        "operation_name": operation_name,
                        "config": config,
                        "business_rules_enabled": config.get("business_rules", {}).get("enabled", False),
                    }
                    # Cache the result for 10 minutes
                    frappe.cache.set_value(cache_key, result, expires_in_sec=600)
                    return result

            # Log when operation rules aren't found to help with debugging
            frappe.logger("verenigingen.api_security").info(
                f"Critical Operation Rule lookup failed for function '{func_name}' from module '{module_name}'. "
                f"Tried operation names: {potential_operation_names}. "
                f"This indicates either missing Critical Operation Rule fixture data or incorrect naming conventions."
            )

        except Exception as e:
            frappe.logger("verenigingen.api_security").warning(
                f"Failed to check critical operation integration: {str(e)}"
            )

        # Cache the "not critical" result too (shorter cache time)
        result = {"is_critical": False}
        frappe.cache.set_value(cache_key, result, expires_in_sec=300)
        return result

    def validate_critical_operation_business_rules(self, operation_info: dict, **kwargs) -> List[str]:
        """Validate business rules for critical operations"""
        if not operation_info.get("is_critical") or not operation_info.get("business_rules_enabled"):
            return []

        try:
            from verenigingen.utils.secure_operations import get_critical_operations_registry

            registry = get_critical_operations_registry()

            return registry.validate_business_rules(operation_info["operation_name"], **kwargs)

        except Exception as e:
            frappe.logger("verenigingen.api_security").error(
                f"Failed to validate critical operation business rules: {str(e)}"
            )
            return []

    def log_audit_event(
        self,
        profile: SecurityProfile,
        func: Callable,
        success: bool,
        execution_time: float = None,
        error: str = None,
        **context,
    ):
        """Log audit event for API call"""
        if not profile.requires_audit:
            return

        # Skip audit logging for read-only operations to prevent unnecessary audit clutter
        # Only log operations that modify data or access sensitive information
        func_name = func.__name__.lower()
        read_only_prefixes = [
            "get_",
            "list_",
            "check_",
            "validate_",
            "test_",
            "analyze_",
            "can_",
            "has_",
            "is_",
            "show_",
            "display_",
            "view_",
            "fetch_",
        ]

        # Skip audit logging for read-only functions unless they failed or access sensitive data
        if success and any(func_name.startswith(prefix) for prefix in read_only_prefixes):
            # Only log read-only operations if they're high security or critical
            if profile.level not in [SecurityLevel.CRITICAL, SecurityLevel.HIGH]:
                return

            # Skip common status/permission check functions that don't access sensitive data
            skip_functions = [
                "can_suspend_member",
                "get_suspension_status",
                "can_terminate_member",
                "is_chapter_management_enabled",
                "check_donor_exists",
                "get_member_termination_status",
                "check_sepa_mandate_status",
            ]

            if func_name in skip_functions:
                return

        event_type = "api_call_success" if success else "api_call_failed"
        severity = AuditSeverity.INFO if success else AuditSeverity.ERROR

        details = {
            "function": func.__name__,
            "module": func.__module__,
            "security_level": profile.level.value,
            "execution_time_ms": round(execution_time * 1000, 2) if execution_time else None,
            **context,
        }

        if error:
            details["error"] = str(error)

        self._get_audit_logger().log_event(event_type, severity, details=details)

    def create_security_response_headers(
        self, profile: SecurityProfile, operation_key: str = None
    ) -> Dict[str, str]:
        """Create security-related response headers"""
        headers = {}

        # Rate limit headers - COR-based implementation
        if hasattr(frappe.local, "response") and operation_key:
            rate_headers = self.get_cor_rate_limit_headers(operation_key)
            headers.update(rate_headers)

        # Security headers
        headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
            }
        )

        # CSRF token header for high security endpoints
        if profile.level in [SecurityLevel.CRITICAL, SecurityLevel.HIGH]:
            try:
                csrf_token = self.csrf_protection.generate_token()
                headers["X-CSRF-Token"] = csrf_token
            except Exception:
                pass  # Don't fail the request if CSRF token generation fails

        return headers


# Global framework instance
_security_framework = None


def get_security_framework() -> APISecurityFramework:
    """Get global security framework instance"""
    global _security_framework
    if _security_framework is None:
        _security_framework = APISecurityFramework()
    return _security_framework


def api_security_framework(
    security_level: SecurityLevel = None,
    operation_type: OperationType = None,
    roles: List[str] = None,
    permissions: List[str] = None,
    validation_schema: Dict[str, Any] = None,
    audit_level: str = "standard",
    custom_validators: List[Callable] = None,
    allowed_environments: List[EnvironmentLevel] = None,
    self_service_only: bool = False,
):
    """
    Comprehensive API Security Decorator

    Applies layered security controls to API endpoints based on classification
    and configuration. This is the main decorator that should be used on all
    API endpoints.

    Usage:
        @frappe.whitelist()
        @api_security_framework(
            security_level=SecurityLevel.HIGH,
            operation_type=OperationType.MEMBER_DATA,
            roles=["Verenigingen Administrator"],
            audit_level="detailed"
        )
        def my_secure_api_function(param1, param2):
            return {"result": "success"}

    Args:
        security_level: Override security classification
        operation_type: Type of operation for automatic classification
        roles: Additional role requirements
        permissions: Additional permission requirements
        rate_limit: Custom rate limit configuration
        validation_schema: Custom validation schema
        audit_level: Audit logging level (standard, detailed, minimal)
        custom_validators: Additional custom validation functions
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            framework = get_security_framework()

            # Determine security level
            level = security_level or framework.classify_endpoint(func, operation_type)
            profile = framework.get_security_profile(level)

            # Override profile settings if specified
            if roles:
                profile.required_roles.extend(roles)
            if allowed_environments:
                profile.allowed_environments = allowed_environments

            try:
                # Environment validation (first check - blocks early if environment not allowed)
                framework.validate_environment_access(profile)

                # Security validations
                framework.validate_authentication(profile)
                framework.validate_request_method(profile)
                framework.validate_request_size(profile)
                framework.validate_csrf_token(profile, func)

                # Rate limiting
                operation_key = f"{func.__module__}.{func.__name__}"
                framework.validate_rate_limits(profile, operation_key)

                # Self-service validation (if enabled)
                if self_service_only:
                    framework._validate_self_service_access(**kwargs)

                    # Enhanced content validation for TOCTOU protection
                    current_user = frappe.session.user
                    if current_user not in ("Administrator", "Guest"):
                        user_member = frappe.db.get_value("Member", {"email": current_user}, "name")
                        if user_member:
                            framework._validate_self_service_request_content(user_member, **kwargs)

                # Input validation
                validated_kwargs = framework.validate_input_data(profile, operation_type, **kwargs)

                # Critical operation integration (new)
                critical_op_info = framework.check_critical_operation_integration(func, **validated_kwargs)

                # Business rule validation for critical operations
                if critical_op_info.get("is_critical"):
                    business_rule_violations = framework.validate_critical_operation_business_rules(
                        critical_op_info, **validated_kwargs
                    )

                    if business_rule_violations:
                        # Log business rule violations
                        for violation in business_rule_violations:
                            frappe.logger("verenigingen.api_security").warning(
                                f"BUSINESS_RULE_VIOLATION: {violation} in API {func.__name__}"
                            )

                        # For critical operations, consider failing early
                        if critical_op_info.get("config", {}).get("security_level") == "critical":
                            raise VValidationError(
                                _("Critical business rule violations: {0}").format(
                                    "; ".join(business_rule_violations)
                                )
                            )

                # Custom validators
                if custom_validators:
                    for validator in custom_validators:
                        validator(**validated_kwargs)

                # Execute function
                result = func(*args, **validated_kwargs)

                # Log successful execution with critical operation context
                execution_time = time.time() - start_time
                audit_context = {
                    "user": frappe.session.user,
                    "args_count": len(args),
                    "kwargs_keys": list(validated_kwargs.keys()),
                }

                # Add critical operation context to audit
                if critical_op_info.get("is_critical"):
                    audit_context.update(
                        {
                            "critical_operation": critical_op_info["operation_name"],
                            "critical_operation_config": critical_op_info["config"]["security_level"],
                            "business_rules_validated": critical_op_info.get("business_rules_enabled", False),
                        }
                    )

                framework.log_audit_event(profile, func, True, execution_time, **audit_context)

                # Add security headers to response
                if hasattr(frappe.local, "response"):
                    headers = framework.create_security_response_headers(profile, operation_key)
                    frappe.local.response.setdefault("headers", {}).update(headers)

                return result

            except Exception as e:
                # Log failed execution
                execution_time = time.time() - start_time
                framework.log_audit_event(
                    profile,
                    func,
                    False,
                    execution_time,
                    error=str(e),
                    user=frappe.session.user,
                    args_count=len(args),
                    kwargs_keys=list(kwargs.keys()),
                )

                # Re-raise the exception
                raise

        # Mark function as security-protected
        wrapper._security_protected = True
        wrapper._security_level = security_level
        wrapper._operation_type = operation_type

        # Preserve Frappe whitelist attribute (critical for admin tools)
        # Enhanced preservation logic to handle all Frappe whitelist scenarios

        # First, check direct attribute
        if hasattr(func, "__func_is_whitelisted__"):
            wrapper.__func_is_whitelisted__ = func.__func_is_whitelisted__
            frappe.logger("verenigingen.security").debug(
                f"Preserved __func_is_whitelisted__ from func: {func.__func_is_whitelisted__}"
            )

        # Check for allow_guest attribute (legacy pattern)
        elif hasattr(func, "allow_guest") and func.allow_guest:
            wrapper.__func_is_whitelisted__ = True
            frappe.logger("verenigingen.security").debug("Set __func_is_whitelisted__ from allow_guest")

        # Check wrapped function if exists
        elif hasattr(func, "__wrapped__"):
            wrapped_func = func.__wrapped__
            if hasattr(wrapped_func, "__func_is_whitelisted__"):
                wrapper.__func_is_whitelisted__ = wrapped_func.__func_is_whitelisted__
                frappe.logger("verenigingen.security").debug(
                    f"Preserved __func_is_whitelisted__ from wrapped: {wrapped_func.__func_is_whitelisted__}"
                )

            # Go deeper if needed
            elif hasattr(wrapped_func, "__wrapped__") and hasattr(
                wrapped_func.__wrapped__, "__func_is_whitelisted__"
            ):
                wrapper.__func_is_whitelisted__ = wrapped_func.__wrapped__.__func_is_whitelisted__
                frappe.logger("verenigingen.security").debug(
                    f"Preserved __func_is_whitelisted__ from deep wrapped: {wrapped_func.__wrapped__.__func_is_whitelisted__}"
                )

        # Force set to True if we know this function should be whitelisted
        # This is a fallback for cases where the attribute chain is broken
        if not hasattr(wrapper, "__func_is_whitelisted__"):
            # Check if this function is explicitly in frappe's whitelist registry
            method_path = f"{func.__module__}.{func.__name__}"
            if method_path in getattr(frappe, "_whitelisted_methods", set()):
                wrapper.__func_is_whitelisted__ = True
                frappe.logger("verenigingen.security").debug(
                    f"Set __func_is_whitelisted__ from whitelist registry for {method_path}"
                )
            else:
                # As a last resort, assume True since our decorator is typically only used on whitelisted functions
                wrapper.__func_is_whitelisted__ = True
                frappe.logger("verenigingen.security").debug(
                    f"Fallback: Set __func_is_whitelisted__ = True for {method_path}"
                )

        # Also preserve other common Frappe attributes
        for attr in ["allow_guest", "_original_func_name"]:
            if hasattr(func, attr):
                setattr(wrapper, attr, getattr(func, attr))

        return wrapper

    return decorator


# Convenience decorators for common security patterns
def critical_api(operation_type: OperationType = OperationType.FINANCIAL, self_service_only: bool = False):
    """Decorator for critical security APIs (financial, admin)"""
    return api_security_framework(
        security_level=SecurityLevel.CRITICAL,
        operation_type=operation_type,
        audit_level="detailed",
        self_service_only=self_service_only,
    )


def high_security_api(
    operation_type: OperationType = OperationType.MEMBER_DATA, self_service_only: bool = False
):
    """Decorator for high security APIs (member data, batch operations)"""
    return api_security_framework(
        security_level=SecurityLevel.HIGH,
        operation_type=operation_type,
        audit_level="standard",
        self_service_only=self_service_only,
    )


def standard_api(
    func_or_operation_type=None,
    *,
    operation_type: OperationType = OperationType.REPORTING,
    self_service_only: bool = False,
):
    """
    Decorator for standard security APIs (reporting, read operations)

    Can be used as:
    - @standard_api
    - @standard_api()
    - @standard_api(operation_type=OperationType.PUBLIC)
    - @standard_api(operation_type=OperationType.REPORTING, self_service_only=True)
    """
    # Handle both @standard_api and @standard_api() usage patterns
    if func_or_operation_type is None:
        # Called as @standard_api()
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
        )
    elif callable(func_or_operation_type):
        # Called as @standard_api (without parentheses)
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
        )(func_or_operation_type)
    else:
        # Called as @standard_api(operation_type=...) - func_or_operation_type is the operation_type
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=func_or_operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
        )


def utility_api(func_or_operation_type=None, *, operation_type: OperationType = OperationType.UTILITY):
    """
    Decorator for utility APIs (health checks, status)

    Can be used as:
    - @utility_api
    - @utility_api()
    - @utility_api(operation_type=OperationType.UTILITY)
    """
    # Handle both @utility_api and @utility_api() usage patterns
    if func_or_operation_type is None:
        # Called as @utility_api()
        return api_security_framework(
            security_level=SecurityLevel.LOW, operation_type=operation_type, audit_level="minimal"
        )
    elif callable(func_or_operation_type):
        # Called as @utility_api (without parentheses)
        return api_security_framework(
            security_level=SecurityLevel.LOW, operation_type=operation_type, audit_level="minimal"
        )(func_or_operation_type)
    else:
        # Called as @utility_api(operation_type=...) - func_or_operation_type is the operation_type
        return api_security_framework(
            security_level=SecurityLevel.LOW, operation_type=func_or_operation_type, audit_level="minimal"
        )


def public_api(func_or_operation_type=None, *, operation_type: OperationType = OperationType.PUBLIC):
    """
    Decorator for public APIs (no authentication required)

    Can be used as:
    - @public_api
    - @public_api()
    - @public_api(operation_type=OperationType.PUBLIC)
    """
    # Handle both @public_api and @public_api() usage patterns
    if func_or_operation_type is None:
        # Called as @public_api()
        return api_security_framework(
            security_level=SecurityLevel.PUBLIC, operation_type=operation_type, audit_level="minimal"
        )
    elif callable(func_or_operation_type):
        # Called as @public_api (without parentheses)
        return api_security_framework(
            security_level=SecurityLevel.PUBLIC, operation_type=operation_type, audit_level="minimal"
        )(func_or_operation_type)
    else:
        # Called as @public_api(operation_type=...) - func_or_operation_type is the operation_type
        return api_security_framework(
            security_level=SecurityLevel.PUBLIC, operation_type=func_or_operation_type, audit_level="minimal"
        )


def development_only_api(
    operation_type: OperationType = OperationType.UTILITY,
    security_level: SecurityLevel = SecurityLevel.LOW,
):
    """Decorator for development-only APIs (test utilities, debug functions)"""
    return api_security_framework(
        security_level=security_level,
        operation_type=operation_type,
        audit_level="minimal",
        allowed_environments=[EnvironmentLevel.DEVELOPMENT],
    )


# API endpoint classification and migration utilities
@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def analyze_api_security_status():
    """
    Analyze current API security status across all endpoints

    Returns comprehensive report of security coverage and recommendations
    """
    # Require admin permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access security analysis"), frappe.PermissionError)

    try:
        framework = get_security_framework()

        # Scan all API files
        import importlib
        import inspect
        import os

        api_path = os.path.join(frappe.get_app_path("verenigingen"), "api")
        analysis = {
            "total_endpoints": 0,
            "secured_endpoints": 0,
            "unsecured_endpoints": 0,
            "security_levels": {level.value: 0 for level in SecurityLevel},
            "recommendations": [],
            "endpoints_by_file": {},
        }

        for root, dirs, files in os.walk(api_path):
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    module_path = f"verenigingen.api.{file[:-3]}"
                    try:
                        module = importlib.import_module(module_path)
                        file_endpoints = []

                        for name, func in inspect.getmembers(module, inspect.isfunction):
                            if hasattr(func, "__wrapped__") or name.startswith("_"):
                                continue

                            # Check if function has @frappe.whitelist()
                            if hasattr(func, "allow_guest") or "@frappe.whitelist" in str(func):
                                analysis["total_endpoints"] += 1

                                # Check if security-protected
                                if hasattr(func, "_security_protected"):
                                    analysis["secured_endpoints"] += 1
                                    level = getattr(func, "_security_level", SecurityLevel.MEDIUM)
                                    analysis["security_levels"][level.value] += 1
                                else:
                                    analysis["unsecured_endpoints"] += 1
                                    # Classify for recommendation
                                    suggested_level = framework.classify_endpoint(func)
                                    analysis["recommendations"].append(
                                        {
                                            "function": f"{module_path}.{name}",
                                            "suggested_level": suggested_level.value,
                                            "reason": "Unprotected API endpoint",
                                        }
                                    )

                                file_endpoints.append(
                                    {
                                        "name": name,
                                        "secured": hasattr(func, "_security_protected"),
                                        "level": getattr(func, "_security_level", None),
                                    }
                                )

                        if file_endpoints:
                            analysis["endpoints_by_file"][file] = file_endpoints

                    except Exception as e:
                        frappe.log_error(f"Failed to analyze module {module_path}: {str(e)}")

        return {
            "success": True,
            "analysis": analysis,
            "summary": {
                "security_coverage": (
                    round((analysis["secured_endpoints"] / analysis["total_endpoints"]) * 100, 1)
                    if analysis["total_endpoints"] > 0
                    else 0
                ),
                "high_priority_endpoints": len(
                    [r for r in analysis["recommendations"] if r["suggested_level"] in ["critical", "high"]]
                ),
                "total_recommendations": len(analysis["recommendations"]),
            },
        }

    except Exception as e:
        log_error(e, module="verenigingen.utils.security.api_security_framework")
        return {"success": False, "error": str(e)}


# Environment-Aware Decorator Shortcuts


def staging_and_dev_api(
    operation_type: OperationType = OperationType.UTILITY,
    security_level: SecurityLevel = SecurityLevel.MEDIUM,
):
    """Decorator for staging and development APIs (testing, validation)"""
    return api_security_framework(
        security_level=security_level,
        operation_type=operation_type,
        audit_level="standard",
        allowed_environments=[EnvironmentLevel.STAGING, EnvironmentLevel.DEVELOPMENT],
    )


def non_production_api(
    operation_type: OperationType = OperationType.ADMIN,
    security_level: SecurityLevel = SecurityLevel.HIGH,
):
    """Decorator for non-production APIs (dangerous admin functions)"""
    return api_security_framework(
        security_level=security_level,
        operation_type=operation_type,
        audit_level="detailed",
        allowed_environments=[EnvironmentLevel.STAGING, EnvironmentLevel.DEVELOPMENT],
    )


def webhook_api(
    operation_type: OperationType = OperationType.FINANCIAL,
):
    """
    Decorator for webhook APIs (payment processors, external integrations)

    Provides secure webhook processing with proper authentication and authorization
    without requiring admin permissions.
    """
    return api_security_framework(
        security_level=SecurityLevel.MEDIUM,  # Medium security - not admin level
        operation_type=operation_type,
        audit_level="standard",
    )


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def get_security_framework_status():
    """Get current security framework configuration and status"""
    # Require admin permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access framework status"), frappe.PermissionError)

    try:
        framework = get_security_framework()

        return {
            "success": True,
            "framework_version": "1.1.0",
            "current_environment": framework.get_current_environment().value,
            "security_levels": [level.value for level in SecurityLevel],
            "operation_types": [op.value for op in OperationType],
            "environment_levels": [env.value for env in EnvironmentLevel],
            "default_profiles": {
                level.value: {
                    "required_roles": profile.required_roles,
                    "requires_csrf": profile.requires_csrf,
                    "requires_audit": profile.requires_audit,
                    "max_request_size": profile.max_request_size,
                }
                for level, profile in framework.SECURITY_PROFILES.items()
            },
            "components_status": {
                "audit_logger": framework.audit_logger is not None,
                "auth_manager": framework.auth_manager is not None,
                "cor_rate_limiting": True,  # Now using COR-based rate limiting
                "csrf_protection": framework.csrf_protection is not None,
            },
        }

    except Exception as e:
        log_error(e, module="verenigingen.utils.security.api_security_framework")
        return {"success": False, "error": str(e)}


def validate_deployment_environment():
    """
    Validate environment configuration and log for operational visibility.

    This function ensures the security framework correctly detects the deployment
    environment and provides operational visibility for production deployments.
    """
    try:
        framework = get_security_framework()
        detected_env = framework.get_current_environment()

        # Log for operational visibility
        frappe.logger().info(f"Security Framework: Environment detected as {detected_env.value}")

        # Check for explicit environment expectation
        expected = frappe.conf.get("expected_environment")
        if expected:
            expected_normalized = expected.lower()
            if expected_normalized != detected_env.value:
                frappe.logger().warning(
                    f"Environment mismatch detected: "
                    f"Expected '{expected}', but detected '{detected_env.value}'. "
                    f"This may indicate configuration issues."
                )
            else:
                frappe.logger().info(
                    f"Environment validation passed: {detected_env.value} matches expected configuration"
                )

        # Log security implications
        if detected_env == EnvironmentLevel.DEVELOPMENT:
            frappe.logger().info("Security Framework: Development mode - debug functions enabled")
        elif detected_env == EnvironmentLevel.PRODUCTION:
            frappe.logger().info("Security Framework: Production mode - debug functions restricted")
        else:
            frappe.logger().info(
                f"Security Framework: {detected_env.value} mode - intermediate security level"
            )

        # Log configuration sources
        config_sources = []
        if frappe.conf.get("developer_mode", False):
            config_sources.append("developer_mode=True")
        if frappe.conf.get("deployment_environment"):
            config_sources.append(f"deployment_environment={frappe.conf.get('deployment_environment')}")
        if frappe.conf.get("environment"):
            config_sources.append(f"environment={frappe.conf.get('environment')}")

        if config_sources:
            frappe.logger().debug(f"Environment detection sources: {', '.join(config_sources)}")
        else:
            frappe.logger().debug("Environment detection: Using secure default (PRODUCTION)")

        return {
            "detected_environment": detected_env.value,
            "expected_environment": expected,
            "validation_passed": not expected or expected.lower() == detected_env.value,
            "config_sources": config_sources,
        }

    except Exception as e:
        frappe.logger().error(f"Environment validation failed: {str(e)}")
        # Don't fail startup on validation error, but log it
        return {"detected_environment": "unknown", "validation_passed": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def get_user_security_profile_analysis(email=None):
    """
    Analyze user's security profile and access levels (admin/debugging utility)

    Args:
        email: User email to analyze (defaults to current user)

    Returns:
        Dict containing user's role profiles, security levels, and access analysis
    """
    # Require System Manager permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access security profile analysis"), frappe.PermissionError)

    try:
        if not email:
            email = frappe.session.user

        framework = get_security_framework()

        # Get user's role profiles
        user_role_profiles = framework._get_user_role_profiles(email)
        user_individual_roles = frappe.get_roles(email)

        # Analyze security level access
        security_level_access = {}
        for level in SecurityLevel:
            has_access = framework._validate_role_profile_access(level, email)
            granting_profiles = []

            for profile in user_role_profiles:
                if framework._role_profile_grants_access(profile, level):
                    granting_profiles.append(profile)

            security_level_access[level.value] = {
                "has_access": has_access,
                "granting_profiles": granting_profiles,
            }

        # Operation type analysis
        operation_type_access = {}
        for op_type, security_level in framework.OPERATION_SECURITY_MAPPING.items():
            has_access = framework._validate_role_profile_access(security_level, email)
            operation_type_access[op_type.value] = {
                "required_security_level": security_level.value,
                "has_access": has_access,
            }

        return {
            "success": True,
            "user_email": email,
            "role_profiles": user_role_profiles,
            "individual_roles": user_individual_roles,
            "security_level_access": security_level_access,
            "operation_type_access": operation_type_access,
            "role_profile_mappings": dict(framework.ROLE_PROFILE_SECURITY_MAPPING),
            "analysis_timestamp": frappe.utils.now(),
        }

    except Exception as e:
        log_error(e, module="verenigingen.utils.security.api_security_framework")
        return {"success": False, "error": str(e)}


def setup_api_security_framework():
    """Setup API security framework during app initialization"""
    # Initialize global framework
    global _security_framework
    _security_framework = APISecurityFramework()

    # Validate environment configuration
    env_validation = validate_deployment_environment()

    # Log setup completion with environment info
    _security_framework._get_audit_logger().log_event(
        "api_security_framework_initialized",
        AuditSeverity.INFO,
        details={
            "security_levels": [level.value for level in SecurityLevel],
            "operation_types": [op.value for op in OperationType],
            "components_loaded": True,
            "environment_validation": env_validation,
        },
    )
