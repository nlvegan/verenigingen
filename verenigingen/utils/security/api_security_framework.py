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

import time
from dataclasses import replace as dataclass_replace
from functools import wraps
from typing import Any, Callable, Dict, List

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.error_handling import (
    PermissionError as VPermissionError,
    ValidationError as VValidationError,
)
from verenigingen.utils.security.audit_emitter import AuditEmitter, get_audit_emitter
from verenigingen.utils.security.authorization_engine import (
    AuthorizationEngine,
    get_authorization_engine,
)
from verenigingen.utils.security.authorization_policy import get_authorization_policy
from verenigingen.utils.security.environment_validator import (
    EnvironmentValidator,
    get_environment_validator,
)
from verenigingen.utils.security.frappe_whitelist_adapter import get_frappe_whitelist_adapter
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
            requires_audit=True,
            input_validation=True,
            ip_restrictions=True,
            business_hours_only=False,
            max_request_size=512 * 1024,  # 512KB
            allowed_methods=["POST"],
        ),
        SecurityLevel.HIGH: SecurityProfile(
            level=SecurityLevel.HIGH,
            requires_audit=True,
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=1024 * 1024,  # 1MB
            allowed_methods=["GET", "POST"],
        ),
        SecurityLevel.MEDIUM: SecurityProfile(
            level=SecurityLevel.MEDIUM,
            requires_audit=False,  # Reduce audit volume - only audit critical/high operations
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=2 * 1024 * 1024,  # 2MB
            allowed_methods=["GET", "POST"],
        ),
        SecurityLevel.LOW: SecurityProfile(
            level=SecurityLevel.LOW,
            requires_audit=False,  # No audit logging for low security operations
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=4 * 1024 * 1024,  # 4MB
            # SECURITY: Restrict to safe methods by default
            # PUT/DELETE require explicit opt-in via custom profile
            allowed_methods=["GET", "POST"],
        ),
        SecurityLevel.PUBLIC: SecurityProfile(
            level=SecurityLevel.PUBLIC,
            requires_audit=False,
            input_validation=True,
            ip_restrictions=False,
            business_hours_only=False,
            max_request_size=10 * 1024 * 1024,  # 10MB
            # SECURITY: Public endpoints should be read-focused
            # POST allowed for webhooks, OPTIONS for CORS preflight
            # PUT/DELETE require explicit opt-in via custom profile
            allowed_methods=["GET", "POST", "OPTIONS"],
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
        # NOTE: CSRF protection removed - Frappe handles this natively in auth.py

        # Validate role profile configuration on initialization
        self._validate_role_profile_configuration()

    def _get_audit_logger(self):
        """Lazily initialize audit logger to avoid circular dependency"""
        if self.audit_logger is None:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            self.audit_logger = get_audit_logger()
        return self.audit_logger

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

    def validate_ip_restrictions(self, profile: SecurityProfile) -> bool:
        """Enforce an optional IP allowlist for IP-restricted profiles.

        Profiles with ``ip_restrictions=True`` (currently CRITICAL) consult the
        site config key ``critical_api_ip_allowlist`` — a list of IPs/CIDRs. The
        control is opt-in: if no allowlist is configured the request proceeds
        (no behavioural change), but once an operator sets an allowlist it is
        actually enforced. The source IP comes from ``get_client_ip()``, which
        already resolves X-Forwarded-For only via trusted proxies, so it is not
        client-spoofable.

        Returns True if allowed; raises VPermissionError if the client IP is
        outside a configured allowlist.
        """
        if not profile.ip_restrictions or not frappe.request:
            return True

        allowlist = frappe.conf.get("critical_api_ip_allowlist")
        if not allowlist:
            # Not configured → control is dormant (documented, not a false promise)
            return True

        import ipaddress

        from verenigingen.utils.security.client_ip import get_client_ip

        client_ip = get_client_ip()
        try:
            client_addr = ipaddress.ip_address(client_ip)
        except ValueError:
            # Unparseable source IP under an active allowlist → deny (fail closed)
            frappe.logger("verenigingen.api_security").warning(
                f"IP_RESTRICTION_DENIED: unparseable client IP {client_ip!r}"
            )
            raise VPermissionError(_("Access denied from this network location."))

        for entry in allowlist:
            try:
                if "/" in str(entry):
                    if client_addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif client_addr == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                frappe.logger("verenigingen.api_security").warning(
                    f"Invalid critical_api_ip_allowlist entry: {entry!r}"
                )
                continue

        frappe.logger("verenigingen.api_security").warning(
            f"IP_RESTRICTION_DENIED: client IP {client_ip} not in allowlist"
        )
        raise VPermissionError(_("Access denied from this network location."))

    def validate_rate_limits(
        self, profile: SecurityProfile, operation_key: str, force_check: bool = False
    ) -> bool:
        """
        Validate rate limits using COR records with context-aware batch support.

        Args:
            profile: Security profile for the operation
            operation_key: Full operation key
            force_check: If True, bypass test environment skip (for testing rate limiting itself)

        Delegates to RateLimitEngine for the actual rate limit check.
        """
        try:
            # Detect execution context (keep on framework for backwards compatibility)
            context = self._detect_execution_context()

            # Delegate to rate limit engine with context
            result = self.rate_limiter.check_rate_limit(
                operation_key, context=context, force_check=force_check
            )

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

    def _validate_self_service_access(self, implicit_allowed: bool = False, **kwargs) -> bool:
        """
        Validate that user can only access their own data in self-service operations.

        Args:
            implicit_allowed: If True, allow operations without explicit member parameter

        Delegates to SelfServiceAccessController.
        """
        return self.self_service_controller.validate_access(implicit_allowed=implicit_allowed, **kwargs)

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

            # Absence of a per-operation Critical Operation Rule is the normal,
            # expected state: the endpoint simply uses its decorator preset (and
            # the rate-limit engine's _generic_api_fallback). Logged at debug only
            # as a naming-mismatch aid, NOT as an error. Treating absence as a
            # problem is what drove the seeding of one COR row per endpoint
            # (~2,600 rows); keep this quiet so sparse rules stay sustainable.
            frappe.logger("verenigingen.api_security").debug(
                f"No per-operation Critical Operation Rule for function '{func_name}' "
                f"(module '{module_name}'); using preset defaults. "
                f"Tried operation names: {potential_operation_names}."
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

        # CSRF token header for high security endpoints (using Frappe's native token)
        if profile.level in [SecurityLevel.CRITICAL, SecurityLevel.HIGH]:
            try:
                csrf_token = frappe.sessions.get_csrf_token()
                headers["X-CSRF-Token"] = csrf_token
            except Exception:
                pass  # Don't fail the request if CSRF token generation fails

        return headers


def _extract_doc_self_service_kwargs(args: tuple) -> Dict[str, Any]:
    """Extract member-identifying fields from a Document positional arg.

    When @api_security_framework wraps a Document instance method (called via
    frappe.handler.run_doc_method), the document is passed as args[0] and the
    request kwargs do not contain the member/volunteer fields the self-service
    validator looks for. Surface those fields from the document so the
    validator can verify ownership against the calling user.

    Returns an empty dict for non-doc-method calls (whitelisted module-level
    functions), preserving existing behaviour.
    """
    if not args or not isinstance(args[0], Document):
        return {}

    doc = args[0]
    extracted: Dict[str, Any] = {}

    # Direct identifiers on the document itself
    for field in ("member", "member_name", "volunteer"):
        value = getattr(doc, field, None)
        if value:
            extracted[field] = value
            break

    return extracted


# Global framework instance
_security_framework = None


def get_security_framework() -> APISecurityFramework:
    """Get global security framework instance"""
    global _security_framework
    if _security_framework is None:
        _security_framework = APISecurityFramework()
    return _security_framework


def _apply_operation_result_http_status(result) -> None:
    """Deliver a failing OperationResult's ``http_status`` as the actual HTTP status (#481).

    ``http_status`` used to be a number in the JSON body and nowhere else, so a result saying
    500 was delivered with a 200 and any caller checking the transport read it as success.
    This is the only frame that sees an OperationResult on its way out -- ``handle_api_error``
    cannot do it, because endpoints also ``return OperationResult.fail(...)`` directly without
    passing through its ``except`` branches.

    Narrow in one sense and NOT in another, and the second is the one to read before changing
    a caller. A result that does not name an ``http_status`` keeps its 200, and most
    ``OperationResult.fail()`` calls in the app name none -- so the 180 endpoints that merely
    touch OperationResult are untouched. But ``handle_api_error``'s four branches ALWAYS set
    one (400/403/400/500), so for the 39 endpoints where that decorator can fire, EVERY
    exception it catches now leaves as a non-200.

    That changes client behaviour, not just a number. Read from frappe/public/js/frappe/
    request.js (mechanism confirmed at frappe/utils/response.py:150; the JS consequences are
    read, not observed -- no HTTP request was made against this tree):

      * 500 -> request.js:215 routes to frappe.request.report_error(), i.e. the traceback /
        report-issue dialog, instead of the endpoint's own friendly message;
      * 403 -> request.js:150 shows a generic "Not permitted", and for a Guest session calls
        frappe.app.handle_session_expired() -- a login redirect. One guest-facing endpoint is
        in scope: membership_application.suggest_chapters_for_postal_code;
      * 400 -> no statusCode handler, falls through to the generic error path.

    This does NOT affect durability. ``frappe/app.py:428`` commits on POST/PUT/DELETE whatever
    the status is; only a raised exception reaches the rollback at ``app.py:147``.
    """
    if getattr(result, "success", True):
        # Clear, do not merely skip. These endpoints call each other: an outer one that
        # recovers from an inner one's failure would otherwise emit a success body under the
        # inner 4xx, because frappe/utils/response.py:150 consumes whatever is left here and
        # the outer frame never gets to overrule it.
        frappe.local.response.pop("http_status_code", None)
        return
    status = getattr(result, "http_status", None)
    if status:
        frappe.local.response["http_status_code"] = status


def api_security_framework(
    security_level: SecurityLevel = None,
    operation_type: OperationType = None,
    permissions: List[str] = None,
    validation_schema: Dict[str, Any] = None,
    audit_level: str = "standard",
    custom_validators: List[Callable] = None,
    allowed_environments: List[EnvironmentLevel] = None,
    self_service_only: bool = False,
    self_service_implicit_allowed: bool = False,
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
        self_service_only: If True, users can only access their own data
        self_service_implicit_allowed: If True with self_service_only, allows operations
            without explicit member parameter (defaults to current user's member)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            framework = get_security_framework()

            # Determine security level
            level = security_level or framework.classify_endpoint(func, operation_type)
            # SECURITY: copy the profile before applying per-endpoint overrides.
            # get_security_profile() returns the shared class-level SECURITY_PROFILES
            # instance; mutating it in place would leak an endpoint's overrides
            # (allowed_environments, max_request_size) onto every other endpoint that
            # shares the same SecurityLevel. A dev-only endpoint would poison the LOW
            # profile's allowed_environments and 403 all self-service/utility endpoints
            # in production; a custom max_request_size would raise the size limit for
            # every other MEDIUM endpoint. Copy makes the override request-local.
            profile = dataclass_replace(framework.get_security_profile(level))

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
                framework.validate_ip_restrictions(profile)
                # NOTE: CSRF validation handled natively by Frappe (auth.py)

                # Rate limiting
                operation_key = f"{func.__module__}.{func.__name__}"
                framework.validate_rate_limits(profile, operation_key)

                # Self-service validation (if enabled)
                if self_service_only:
                    # Doc-method calls (run_doc_method) pass the document as args[0]
                    # and have no member/volunteer kwarg — surface it from the doc so
                    # the validator can match it against the caller's member.
                    self_service_kwargs = {**_extract_doc_self_service_kwargs(args), **kwargs}

                    framework._validate_self_service_access(
                        implicit_allowed=self_service_implicit_allowed, **self_service_kwargs
                    )

                    # Enhanced content validation for TOCTOU protection.
                    # Resolve the caller's member with the canonical user-first
                    # resolver (Member.user, then Member.email) — matching the
                    # ownership gate. An email-only lookup silently skipped this
                    # deep check for members whose Member.user differs from their
                    # login email, disabling TOCTOU protection for that class of user.
                    current_user = frappe.session.user
                    if current_user not in ("Administrator", "Guest"):
                        user_member = framework.self_service_controller.get_user_member(current_user)
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
                # Use scrub_sensitive=True to prevent traceback/exception metadata
                # from leaking into HTTP responses (e.g. from OperationResult.from_exception)
                #
                # Guard on callable(), not hasattr(): a frappe._dict (e.g. from
                # frappe.db.get_value(as_dict=True)) sets __getattr__ = dict.get, so
                # `result.to_dict` returns None for the missing key and hasattr() is
                # True -> calling it would raise "'NoneType' object is not callable".
                # callable(getattr(result, "to_dict", None)) is False for any dict /
                # frappe._dict, so those serialise as-is; only real OperationResult-like
                # objects (with a bound to_dict method) get converted.
                #
                # Contract: any object returned from a @*_api endpoint that exposes a
                # callable `to_dict` MUST accept a `scrub_sensitive` keyword (as
                # OperationResult does). We intentionally do NOT fall back to a no-arg
                # to_dict() on TypeError — that would mask a genuine signature mismatch.
                to_dict = getattr(result, "to_dict", None)
                if callable(to_dict):
                    _apply_operation_result_http_status(result)
                    return to_dict(scrub_sensitive=True)
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
#
# Security Level Selection Guide:
# ┌─────────────────┬────────────────────────────────────────────────────────────┐
# │ Decorator       │ Use Case                                                   │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @critical_api   │ Financial transactions (SEPA, payments, invoicing)        │
# │                 │ POST-only, IP restrictions, detailed audit, 512KB limit   │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @high_security  │ Member data access, batch operations, exports             │
# │                 │ GET/POST allowed, standard audit, 1MB limit               │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @standard_api   │ Reporting, dashboards, read-only operations               │
# │                 │ No CSRF/audit overhead, 2MB limit                         │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @utility_api    │ Health checks, status endpoints, internal tools           │
# │                 │ Minimal security, 4MB limit                               │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @public_api     │ Guest-accessible endpoints (membership forms, webhooks)   │
# │                 │ No authentication, 10MB limit, OPTIONS for CORS           │
# ├─────────────────┼────────────────────────────────────────────────────────────┤
# │ @development_   │ Debug/test utilities - blocked in production              │
# │ only_api        │                                                           │
# └─────────────────┴────────────────────────────────────────────────────────────┘


def critical_api(operation_type: OperationType = OperationType.FINANCIAL, self_service_only: bool = False):
    """
    Decorator for critical security APIs requiring maximum protection.

    Use for: SEPA batch processing, payment submissions, financial transactions,
    system administration operations.

    Security features:
    - CSRF validation required
    - Detailed audit logging (full request/response)
    - IP restrictions enabled (configurable whitelist)
    - POST-only (no GET requests - prevents CSRF via URL)
    - 512KB max request size
    - Rate limiting enforced

    Example:
        @frappe.whitelist()
        @critical_api(operation_type=OperationType.FINANCIAL)
        def submit_sepa_batch(batch_id: str):
            ...

    Args:
        operation_type: Classification for rate limiting (default: FINANCIAL)
        self_service_only: If True, users can only access their own data
    """
    return api_security_framework(
        security_level=SecurityLevel.CRITICAL,
        operation_type=operation_type,
        audit_level="detailed",
        self_service_only=self_service_only,
    )


def high_security_api(
    operation_type: OperationType = OperationType.MEMBER_DATA, self_service_only: bool = False
):
    """
    Decorator for high security APIs that need audit trails but allow read access.

    Use for: Member data lookups, batch exports, administrative queries,
    operations that need audit logging but aren't strictly write-only.

    Security features:
    - CSRF validation required
    - Standard audit logging (key fields only)
    - No IP restrictions (allows broader access than critical)
    - GET and POST allowed (enables data retrieval)
    - 1MB max request size
    - Rate limiting enforced

    Key difference from @critical_api:
    - Allows GET requests (for data retrieval)
    - No IP restrictions (for member self-service portals)
    - Larger payload limit (for batch operations)

    Example:
        @frappe.whitelist()
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def get_member_payment_history(member_id: str):
            ...

    Args:
        operation_type: Classification for rate limiting (default: MEMBER_DATA)
        self_service_only: If True, users can only access their own data
    """
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
    self_service_implicit_allowed: bool = False,
    max_request_size: int = None,
):
    """
    Decorator for standard authenticated APIs without audit overhead.

    Use for: Reporting endpoints, dashboard data, analytics queries,
    read-only operations where audit logging is unnecessary.

    Security features:
    - Authentication required (not guest-accessible)
    - No CSRF validation (read operations)
    - No audit logging (reduces overhead)
    - Input validation enabled
    - 2MB max request size (or custom via max_request_size)
    - Rate limiting enforced

    Key difference from @high_security_api:
    - No audit trail (for high-volume read operations)
    - No CSRF overhead (safe for GET requests)

    Usage patterns:
        @standard_api                                    # Simplest form
        @standard_api()                                  # Equivalent
        @standard_api(operation_type=OperationType.REPORTING)
        @standard_api(self_service_only=True)           # User can only see own data
        @standard_api(self_service_only=True, self_service_implicit_allowed=True)
                                                         # Portal endpoint that derives
                                                         # member from session.user
        @standard_api(max_request_size=10*1024*1024)    # Custom payload limit

    Example:
        @frappe.whitelist()
        @standard_api
        def get_dashboard_stats():
            ...

    Args:
        operation_type: Classification for rate limiting (default: REPORTING)
        self_service_only: If True, users can only access their own data
        self_service_implicit_allowed: When `self_service_only=True`, allows
            the endpoint to operate on session user's member without an
            explicit `member` kwarg (defaults to False). Required for portal
            endpoints like `submit_expense` that derive the member from
            `frappe.session.user` rather than accepting a `member` argument.
        max_request_size: Override default 2MB limit
    """
    # Handle both @standard_api and @standard_api() usage patterns
    if func_or_operation_type is None:
        # Called as @standard_api()
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            self_service_implicit_allowed=self_service_implicit_allowed,
            max_request_size=max_request_size,
        )
    elif callable(func_or_operation_type):
        # Called as @standard_api (without parentheses)
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            self_service_implicit_allowed=self_service_implicit_allowed,
            max_request_size=max_request_size,
        )(func_or_operation_type)
    else:
        # Called as @standard_api(operation_type=...) - func_or_operation_type is the operation_type
        return api_security_framework(
            security_level=SecurityLevel.MEDIUM,
            operation_type=func_or_operation_type,
            audit_level="standard",
            self_service_only=self_service_only,
            self_service_implicit_allowed=self_service_implicit_allowed,
            max_request_size=max_request_size,
        )


def self_service_api(
    operation_type: OperationType = OperationType.MEMBER_DATA,
    implicit_allowed: bool = False,
    audit_level: str = "standard",
):
    """
    Decorator for endpoints a user can only invoke on their OWN data.

    Use for: member fee/type adjustments, profile updates, expense submissions,
    or any other action where the caller acts on a record they own. Sits below
    @standard_api (MEDIUM) on the auth ladder so plain `Verenigingen Member`
    users can call it — ownership is enforced by SelfServiceAccessController,
    not by role tier.

    Auth model:
        - Authentication required (rejects Guest)
        - LOW security level — any authenticated user passes auth
        - self_service_only=True — caller's member must match the target

    OWNERSHIP CONTRACT (important):
        The framework only understands member/volunteer identifiers (member,
        member_name, member_id, volunteer[/_name/_id]). If your endpoint decides
        what to act on from a DIFFERENT identifier — customer, donor, membership,
        mandate, payment_plan, a bare `name`, etc. — the framework CANNOT verify
        ownership of it, and (with implicit_allowed=True) the call is admitted as
        implicit self-service. Such endpoints MUST perform their own ownership
        check (resolve the entity to a member and compare to the session user).
        All current implicit_allowed endpoints do this; keep it that way.

    Args:
        operation_type: Classification for rate limiting / audit context
        implicit_allowed: If True, endpoint may operate on session user's
            member without an explicit member parameter (e.g. portal endpoints
            that derive the member from frappe.session.user). Default False
            requires the target member be passed explicitly or be available
            on a Document positional arg (for doc-method calls).
        audit_level: "standard" (default), "detailed", or "minimal"

    Example:
        @frappe.whitelist()
        @self_service_api(operation_type=OperationType.FINANCIAL,
                          implicit_allowed=True)
        def submit_fee_adjustment_request(new_amount, reason=""):
            member = get_current_user_member_name()  # session-derived
            ...
    """
    return api_security_framework(
        security_level=SecurityLevel.LOW,
        operation_type=operation_type,
        self_service_only=True,
        self_service_implicit_allowed=implicit_allowed,
        audit_level=audit_level,
    )


def utility_api(func_or_operation_type=None, *, operation_type: OperationType = OperationType.UTILITY):
    """
    Decorator for low-security utility endpoints.

    Use for: Health checks, status endpoints, internal tooling,
    operations that need authentication but minimal overhead.

    Security features:
    - Authentication required
    - No CSRF validation
    - No audit logging
    - Input validation enabled
    - 4MB max request size
    - Minimal rate limiting

    Key difference from @standard_api:
    - Even less overhead (for internal tools)
    - Larger payload limit

    Usage patterns:
        @utility_api
        @utility_api()
        @utility_api(operation_type=OperationType.UTILITY)

    Example:
        @frappe.whitelist()
        @utility_api
        def health_check():
            return {"status": "ok"}

    Args:
        operation_type: Classification for rate limiting (default: UTILITY)
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
    Decorator for guest-accessible APIs (no authentication required).

    Use for: Membership application forms, public information,
    webhook endpoints, CORS-enabled APIs.

    Security features:
    - NO authentication (guest access allowed)
    - No CSRF validation
    - No audit logging
    - Input validation enabled (critical for untrusted input!)
    - 10MB max request size
    - GET, POST, and OPTIONS allowed (OPTIONS for CORS preflight)
    - Rate limiting enforced (important for abuse prevention)

    IMPORTANT: Since these endpoints are unauthenticated, ensure:
    - Strict input validation (untrusted data)
    - Rate limiting is properly configured
    - No sensitive data exposure

    Usage patterns:
        @public_api
        @public_api()
        @public_api(operation_type=OperationType.WEBHOOK_PROCESSING)

    Example:
        @frappe.whitelist(allow_guest=True)
        @public_api
        def get_membership_types():
            ...

    Note: Must be combined with @frappe.whitelist(allow_guest=True)

    Args:
        operation_type: Classification for rate limiting (default: PUBLIC)
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
    """
    Decorator for development-only APIs that are blocked in production.

    Use for: Test utilities, debug endpoints, development tools,
    database inspection, security analysis functions.

    Security features:
    - BLOCKED in production/staging environments
    - Only accessible when FRAPPE_ENV=development
    - Minimal audit logging
    - Authentication required (System Manager typically)

    Environment detection:
    - Checks FRAPPE_ENV environment variable
    - Falls back to site configuration
    - Throws PermissionError if accessed in production

    Example:
        @frappe.whitelist()
        @development_only_api(operation_type=OperationType.UTILITY)
        def analyze_security_status():
            # Only runs in development
            ...

    Args:
        operation_type: Classification for rate limiting (default: UTILITY)
        security_level: Override security level (default: LOW)
    """
    return api_security_framework(
        security_level=security_level,
        operation_type=operation_type,
        audit_level="minimal",
        allowed_environments=[EnvironmentLevel.DEVELOPMENT],
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
