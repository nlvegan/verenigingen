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

from verenigingen.utils.error_handling import (
    PermissionError as VPermissionError,
    ValidationError as VValidationError,
    log_error,
)
from verenigingen.utils.security.audit_emitter import AuditEmitter, get_audit_emitter
from verenigingen.utils.security.authorization_engine import (
    AuthorizationEngine,
    get_authorization_engine,
)
from verenigingen.utils.security.authorization_policy import (
    AuthorizationPolicy,
    get_authorization_policy,
)

# Lazy import to avoid circular dependency - get_auth_manager imported when needed
from verenigingen.utils.security.csrf_protection import CSRFProtection
from verenigingen.utils.security.environment_validator import (
    EnvironmentValidator,
    get_environment_validator,
)
from verenigingen.utils.security.frappe_whitelist_adapter import (
    FrappeWhitelistAdapter,
    get_frappe_whitelist_adapter,
)
from verenigingen.utils.security.input_validator import InputValidator, get_input_validator
from verenigingen.utils.security.rate_limit_engine import (
    RateLimitEngine,
    get_rate_limit_engine,
)
from verenigingen.utils.security.self_service_access_controller import (
    SelfServiceAccessController,
    get_self_service_controller,
)
from verenigingen.utils.security.types import (
    AuditEventType,
    AuditSeverity,
    EnvironmentLevel,
    ExecutionContext,
    OperationType,
    SecurityLevel,
    SecurityProfile,
)
from verenigingen.utils.validation.api_validators import APIValidator

# FrappeWhitelistAdapter is now imported from frappe_whitelist_adapter.py (Phase 3 refactoring)
# SecurityProfile is imported from types.py for better modularity


class APISecurityFramework:
    """
    Main API Security Framework Class

    Provides comprehensive security controls with standardized patterns
    for all API endpoints in the Verenigingen application.
    """

    # Predefined security profiles
    # Note: Authorization is handled via ROLE_PROFILE_SECURITY_MAPPING in authorization_policy.py
    # These profiles define operational constraints, not role-based access control
    SECURITY_PROFILES = {
        SecurityLevel.CRITICAL: SecurityProfile(
            level=SecurityLevel.CRITICAL,
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
    # Now delegated to AuthorizationPolicy for pure logic separation
    # This property maintains backwards compatibility
    @property
    def ROLE_PROFILE_SECURITY_MAPPING(self):
        """Get mapping from AuthorizationPolicy (backwards compatibility)."""
        return get_authorization_policy().ROLE_PROFILE_SECURITY_MAPPING

    def __init__(
        self,
        auth_engine: AuthorizationEngine = None,
        rate_limiter: RateLimitEngine = None,
        audit_emitter: AuditEmitter = None,
        input_validator: InputValidator = None,
        environment_validator: EnvironmentValidator = None,
        self_service_controller: SelfServiceAccessController = None,
    ):
        """
        Initialize the security framework with injectable components.

        All components are optional and will use singleton instances if not provided.
        This allows for easy testing by injecting mock components.

        Args:
            auth_engine: Authorization engine (uses singleton if None)
            rate_limiter: Rate limit engine (uses singleton if None)
            audit_emitter: Audit emitter (uses singleton if None)
            input_validator: Input validator (uses singleton if None)
            environment_validator: Environment validator (uses singleton if None)
            self_service_controller: Self-service access controller (uses singleton if None)
        """
        # Injectable components with sensible defaults
        self.auth_engine = auth_engine or get_authorization_engine()
        self.rate_limiter = rate_limiter or get_rate_limit_engine()
        self.audit_emitter = audit_emitter or get_audit_emitter()
        self.input_validator = input_validator or get_input_validator()
        self.environment_validator = environment_validator or get_environment_validator()
        self.self_service_controller = self_service_controller or get_self_service_controller()

        # Legacy components (keeping for backwards compatibility)
        self.audit_logger = None  # Lazy initialization
        self.auth_manager = None  # Lazy loading to avoid circular import
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
            # SECURITY: Only log presence and type, never log token content
            has_header = bool(auth_header)
            is_token_auth = has_header and auth_header.startswith("token ")
            frappe.logger("verenigingen.api_security").debug(
                f"API key detection: header_present={has_header}, is_token_auth={is_token_auth}"
            )
            return is_token_auth
        except (RuntimeError, AttributeError) as e:
            frappe.logger("verenigingen.api_security").debug(f"API key detection error: {type(e).__name__}")
            return False

    def _get_client_ip(self) -> str:
        """Get client IP address, handling test environments gracefully"""
        try:
            if hasattr(frappe.local, "request") and frappe.local.request:
                return frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
        except (AttributeError, RuntimeError):
            pass
        return "test_environment"

    # NOTE: _get_cor_config was removed in Phase 2 refactoring.
    # COR config is now fetched by RateLimitEngine._get_cor_config()
    # which is called via self.rate_limiter.check_rate_limit()

    def _detect_execution_context(self) -> ExecutionContext:
        """
        Detect the execution context to determine appropriate rate limiting.

        Returns:
            ExecutionContext: The detected execution context
        """
        # Check if we're in a background job context
        # Background jobs are queued via frappe.enqueue() and have specific flags
        if getattr(frappe.flags, "in_background_job", False):
            return ExecutionContext.BACKGROUND_JOB

        # Check for bulk operations flag (set during bulk imports/processing)
        if getattr(frappe.flags, "bulk_account_creation", False):
            return ExecutionContext.BACKGROUND_JOB

        # Check for scheduled task context (cron jobs)
        if getattr(frappe.flags, "in_scheduler", False):
            return ExecutionContext.SCHEDULED_TASK

        # If we're in test mode, treat as CLI
        if frappe.flags.in_test:
            return ExecutionContext.CLI

        # Check if there's an active HTTP request
        # Background jobs don't have HTTP requests - they're called via RQ workers
        has_http_request = False
        try:
            has_http_request = (
                hasattr(frappe.local, "request")
                and frappe.local.request is not None
                and hasattr(frappe.local.request, "method")
            )
        except (AttributeError, RuntimeError):
            has_http_request = False

        if has_http_request:
            return ExecutionContext.INTERACTIVE

        # No HTTP request - could be background job or CLI
        # If this function was called with @frappe.whitelist() but has no HTTP request,
        # it's almost certainly a background job (enqueued via frappe.enqueue)
        # Check if we're running in an RQ worker context
        import sys

        if "rq.worker" in sys.modules or "rq" in str(sys.argv):
            return ExecutionContext.BACKGROUND_JOB

        # Default to CLI for all other contexts (bench commands, console, etc.)
        return ExecutionContext.CLI

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

        Delegates to EnvironmentValidator.

        Returns:
            EnvironmentLevel: Current environment (DEVELOPMENT, STAGING, or PRODUCTION)
        """
        validator = get_environment_validator()
        return validator.get_current_environment()

    def validate_environment_access(
        self, profile: SecurityProfile, current_env: EnvironmentLevel = None
    ) -> bool:
        """
        Validate that the current environment is allowed for this security profile.

        Delegates to EnvironmentValidator.

        Args:
            profile: Security profile containing environment restrictions
            current_env: Current environment (detected if not provided)

        Returns:
            bool: True if access is allowed in current environment

        Raises:
            VPermissionError: If current environment is not allowed
        """
        validator = get_environment_validator()
        return validator.validate_access(profile, current_env)

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
        """
        Get user's role profiles from Frappe's Role Profile system.

        Delegates to AuthorizationEngine for actual implementation.
        """
        return self.auth_engine.get_user_role_profiles(user)

    @staticmethod
    def invalidate_user_role_cache(user: str = None):
        """
        Invalidate cached role profiles for a user (or all users if none specified).

        Delegates to authorization_engine.invalidate_user_role_cache().
        """
        from verenigingen.utils.security.authorization_engine import invalidate_user_role_cache

        invalidate_user_role_cache(user)

    def _role_profile_grants_access(self, role_profile: str, required_level: SecurityLevel) -> bool:
        """Check if a role profile grants access to the required security level.

        Delegates to AuthorizationPolicy.
        """
        policy = get_authorization_policy()
        return policy.role_profile_grants_access(role_profile, required_level)

    def _validate_role_profile_access(self, required_level: SecurityLevel, user: str = None) -> bool:
        """Check if user's role profiles grant required security level."""
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
        """
        Validate user authentication and authorization.

        Delegates to AuthorizationEngine for the actual authorization check.
        See AuthorizationPolicy for the decision table documentation.

        Args:
            profile: SecurityProfile with the required security level
            user: User to validate (defaults to current session user)

        Returns:
            True if authorized

        Raises:
            VPermissionError: If authorization fails
        """
        if not user:
            user = frappe.session.user

        # Delegate to authorization engine
        result = self.auth_engine.authorize(user, profile.level)

        # Log the result
        if result.granted:
            frappe.logger("verenigingen.api_security").debug(
                f"AUTH_GRANTED: user={user} level={profile.level.value} "
                f"rule={result.rule_matched} path={result.auth_path}"
            )
            return True

        # Handle denial - get user info for logging
        user_profiles = self.auth_engine.get_user_role_profiles(user)
        user_roles = frappe.get_roles(user)

        frappe.logger("verenigingen.api_security").warning(
            f"AUTH_DENIED: user={user} level={profile.level.value} "
            f"rule={result.rule_matched} "
            f"profiles={user_profiles} roles={user_roles[:5]}..."  # Truncate for log safety
        )

        # Return generic error to client (avoid information leakage)
        # Detailed info is in server logs for debugging
        if frappe.conf.get("developer_mode"):
            # In dev mode, show details for debugging
            raise VPermissionError(
                _("Access denied. Required: {0}. Your profiles: {1}, roles: {2}").format(
                    profile.level.value,
                    user_profiles or "none",
                    ", ".join(user_roles[:5]) + ("..." if len(user_roles) > 5 else ""),
                )
            )
        else:
            # In production, return generic message
            raise VPermissionError(_("Access denied. You do not have permission for this operation."))

    # Headers that are safe to log (no secrets, tokens, or PII)
    SAFE_HEADERS_FOR_LOGGING = frozenset(
        [
            "content-type",
            "content-length",
            "accept",
            "accept-encoding",
            "accept-language",
            "user-agent",
            "host",
            "origin",
            "referer",
            "x-requested-with",
        ]
    )

    def _get_safe_headers_for_logging(self) -> dict:
        """
        Extract only safe headers for logging.

        SECURITY: Never log Authorization, Cookie, X-Frappe-CSRF-Token, or other
        headers that may contain secrets, tokens, or session identifiers.
        """
        if not frappe.request or not hasattr(frappe.request, "headers"):
            return {}

        safe_headers = {}
        for header_name, header_value in frappe.request.headers:
            if header_name.lower() in self.SAFE_HEADERS_FOR_LOGGING:
                safe_headers[header_name] = header_value
        return safe_headers

    def validate_request_method(self, profile: SecurityProfile) -> bool:
        """Validate HTTP method is allowed"""
        if not frappe.request:
            return True

        method = frappe.request.method

        if method not in profile.allowed_methods:
            # Log failure with safe debug info only (no sensitive headers)
            debug_info = {
                "detected_method": method,
                "allowed_methods": list(profile.allowed_methods),
                "content_type": getattr(frappe.request, "content_type", "N/A"),
                "request_url": getattr(frappe.request, "url", "N/A"),
            }
            frappe.logger("verenigingen.api_security").warning(
                f"Method validation failed: {method} not in {profile.allowed_methods}"
            )
            # Error message to user should not include debug info
            raise VPermissionError(
                _("Method {0} not allowed. Allowed methods: {1}").format(
                    method, ", ".join(profile.allowed_methods)
                )
            )

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
            # These are called internally during the membership application flow
            # where the user context switches but original request lacks CSRF token
            skip_csrf_functions = [
                "approve_membership_application",
                "reject_membership_application",
                "create_membership_from_application",
                "update_membership_status",
                "create_volunteer_from_member",  # Called during application when wants_to_volunteer=True
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
        """
        Validate rate limits using COR records with context-aware batch support.

        Delegates to RateLimitEngine for the actual rate limit check.
        """
        try:
            # Detect execution context (keep on framework for backwards compatibility)
            context = self._detect_execution_context()

            # Delegate to rate limit engine with context
            result = self.rate_limiter.check_rate_limit(operation_key, context=context)

            if not result.allowed:
                # Log rate limit exceeded via audit emitter
                self.audit_emitter.log_rate_limit_exceeded(
                    user=frappe.session.user,
                    operation=operation_key,
                    current_count=result.current_count,
                    max_calls=result.max_calls,
                )
                raise VPermissionError(
                    _("Rate limit exceeded: {0}/{1} requests per {2} seconds for {3}").format(
                        result.current_count,
                        result.max_calls,
                        result.period_seconds,
                        operation_key.split(".")[-1] if "." in operation_key else operation_key,
                    )
                )

            return True

        except VPermissionError:
            raise  # Re-raise rate limit errors as-is
        except Exception as e:
            self._get_audit_logger().log_event(
                AuditEventType.RATE_LIMIT_EXCEEDED,
                AuditSeverity.WARNING,
                details={"operation": operation_key, "error": str(e)},
            )
            raise VPermissionError(_("Rate limit validation failed: {0}").format(str(e)))

    def get_cor_rate_limit_headers(self, operation_key: str) -> Dict[str, str]:
        """
        Get COR-based rate limit headers for HTTP responses.

        Delegates to RateLimitEngine for header generation.
        """
        return self.rate_limiter.get_rate_limit_headers(operation_key)

    def validate_input_data(
        self, profile: SecurityProfile, operation_type: OperationType = None, **kwargs
    ) -> Dict[str, Any]:
        """
        Validate and sanitize input data.

        Delegates to InputValidator for actual validation logic.
        """
        if not profile.input_validation:
            return kwargs

        return self.input_validator.validate(operation_type=operation_type, **kwargs)

    def _validate_dict_input(self, data: Dict[str, Any], max_length: int = 500) -> Dict[str, Any]:
        """Validate dictionary input data. Delegates to InputValidator."""
        return self.input_validator.validate_dict(data, max_length)

    def _validate_list_input(self, data: List[Any], max_length: int = 500) -> List[Any]:
        """Validate list input data. Delegates to InputValidator."""
        return self.input_validator.validate_list(data, max_length)

    def _validate_self_service_access(self, **kwargs) -> bool:
        """
        Validate that user can only access their own data in self-service operations.

        Delegates to SelfServiceAccessController.
        """
        return self.self_service_controller.validate_access(**kwargs)

    def _validate_self_service_request_content(self, user_member, **kwargs) -> bool:
        """
        Deep validation of request content for self-service operations.

        Delegates to SelfServiceAccessController.
        """
        return self.self_service_controller.validate_request_content(user_member, **kwargs)

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
        """
        Log audit event for API call.

        Delegates to AuditEmitter which handles filtering logic for
        read-only operations and skip lists.
        """
        if not profile.requires_audit:
            return

        self.audit_emitter.log_api_call(
            func=func,
            security_level=profile.level,
            success=success,
            execution_time=execution_time,
            error=error,
            **context,
        )

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
        # Note: X-XSS-Protection is intentionally NOT included because:
        # - It's deprecated and removed from modern browsers (Chrome 78+, Edge 79+)
        # - The browser's built-in XSS filter could be exploited in some cases
        # - Content-Security-Policy is the modern replacement
        # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-XSS-Protection
        headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
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
    permissions: List[str] = None,
    validation_schema: Dict[str, Any] = None,
    audit_level: str = "standard",
    custom_validators: List[Callable] = None,
    allowed_environments: List[EnvironmentLevel] = None,
    self_service_only: bool = False,
    max_request_size: int = None,
):
    """
    Comprehensive API Security Decorator

    Applies layered security controls to API endpoints based on classification
    and configuration. This is the main decorator that should be used on all
    API endpoints.

    Authorization is handled via ROLE_PROFILE_SECURITY_MAPPING in authorization_policy.py,
    not through role parameters on individual endpoints.

    Usage:
        @frappe.whitelist()
        @api_security_framework(
            security_level=SecurityLevel.HIGH,
            operation_type=OperationType.MEMBER_DATA,
            audit_level="detailed"
        )
        def my_secure_api_function(param1, param2):
            return {"result": "success"}

    Args:
        security_level: Override security classification
        operation_type: Type of operation for automatic classification
        permissions: Additional permission requirements
        validation_schema: Custom validation schema
        audit_level: Audit logging level (standard, detailed, minimal)
        custom_validators: Additional custom validation functions
        max_request_size: Override maximum request size in bytes (e.g., 10*1024*1024 for 10MB)
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
            if allowed_environments:
                profile.allowed_environments = allowed_environments
            if max_request_size is not None:
                profile.max_request_size = max_request_size

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

                # Convert OperationResult to dict for JSON serialization
                if hasattr(result, "to_dict"):
                    return result.to_dict()
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

        # Register wrapper with Frappe's whitelist system using the adapter
        # This handles all the complex logic for attribute preservation and registration
        adapter = get_frappe_whitelist_adapter()
        adapter.register_wrapper(wrapper, func)

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
    max_request_size: int = None,
):
    """
    Decorator for standard security APIs (reporting, read operations)

    Can be used as:
    - @standard_api
    - @standard_api()
    - @standard_api(operation_type=OperationType.PUBLIC)
    - @standard_api(operation_type=OperationType.REPORTING, self_service_only=True)
    - @standard_api(operation_type=OperationType.MEMBER_DATA, max_request_size=10*1024*1024)
    """
    # Handle both @standard_api and @standard_api() usage patterns
    if func_or_operation_type is None:
        # Called as @standard_api()
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            max_request_size=max_request_size,
        )
    elif callable(func_or_operation_type):
        # Called as @standard_api (without parentheses)
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            max_request_size=max_request_size,
        )(func_or_operation_type)
    else:
        # Called as @standard_api(operation_type=...) - func_or_operation_type is the operation_type
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=func_or_operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            max_request_size=max_request_size,
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
    if "System Manager" not in frappe.get_roles():
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
    if "System Manager" not in frappe.get_roles():
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
    if "System Manager" not in frappe.get_roles():
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
