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
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Union

import frappe
from frappe import _
from frappe.utils import cstr

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.error_handling import log_error
from verenigingen.utils.security.audit_logging import AuditEventType, AuditSeverity, get_audit_logger
from verenigingen.utils.security.authorization import SEPAOperation, get_auth_manager
from verenigingen.utils.security.csrf_protection import CSRFProtection
from verenigingen.utils.security.rate_limiting import get_rate_limiter
from verenigingen.utils.validation.api_validators import APIValidator


class SecurityLevel(Enum):
    """API Security Classification Levels"""

    CRITICAL = "critical"  # Financial transactions, member data changes, system administration
    HIGH = "high"  # Member data access, batch operations, administrative functions
    MEDIUM = "medium"  # Reporting, read-only operations, analytics
    LOW = "low"  # Public information, utility functions, health checks
    PUBLIC = "public"  # No authentication required


class OperationType(Enum):
    """Types of operations for context-aware security"""

    FINANCIAL = "financial"  # Payment processing, invoicing, SEPA operations
    MEMBER_DATA = "member_data"  # Member information access/modification
    ADMIN = "admin"  # System administration, settings
    REPORTING = "reporting"  # Data export, analytics, dashboards
    UTILITY = "utility"  # Health checks, status endpoints
    PUBLIC = "public"  # Public information, documentation


class SecurityProfile:
    """Security profile defining requirements for each security level"""

    def __init__(
        self,
        level: SecurityLevel,
        required_roles: List[str] = None,
        required_permissions: List[str] = None,
        rate_limit_config: Dict[str, int] = None,
        requires_csrf: bool = True,
        requires_audit: bool = True,
        input_validation: bool = True,
        ip_restrictions: bool = False,
        business_hours_only: bool = False,
        max_request_size: int = 1024 * 1024,  # 1MB default
        allowed_methods: List[str] = None,
    ):
        self.level = level
        self.required_roles = required_roles or []
        self.required_permissions = required_permissions or []
        self.rate_limit_config = rate_limit_config or {"requests": 100, "window_seconds": 3600}
        self.requires_csrf = requires_csrf
        self.requires_audit = requires_audit
        self.input_validation = input_validation
        self.ip_restrictions = ip_restrictions
        self.business_hours_only = business_hours_only
        self.max_request_size = max_request_size
        self.allowed_methods = allowed_methods or ["GET", "POST"]


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
            rate_limit_config={"requests": 10, "window_seconds": 3600},
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
            rate_limit_config={"requests": 50, "window_seconds": 3600},
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
            rate_limit_config={"requests": 200, "window_seconds": 3600},
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
            rate_limit_config={"requests": 500, "window_seconds": 3600},
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
            rate_limit_config={"requests": 1000, "window_seconds": 3600},
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
    }

    def __init__(self):
        """Initialize the security framework"""
        self.audit_logger = get_audit_logger()
        self.auth_manager = get_auth_manager()
        self.rate_limiter = get_rate_limiter()
        self.csrf_protection = CSRFProtection()

    def _safe_has_csrf_header(self) -> bool:
        """Safely check for CSRF headers, handling cases where there's no request context"""
        try:
            return bool(
                frappe.get_request_header("X-Frappe-CSRF-Token") or frappe.get_request_header("X-CSRF-Token")
            )
        except (RuntimeError, AttributeError):
            return False

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

        # Check required roles
        if profile.required_roles:
            user_roles = frappe.get_roles(user)
            if not any(role in user_roles for role in profile.required_roles):
                raise VPermissionError(
                    _("Access denied. Required roles: {0}").format(", ".join(profile.required_roles))
                )

        return True

    def validate_request_method(self, profile: SecurityProfile) -> bool:
        """Validate HTTP method is allowed"""
        if not frappe.request:
            return True

        method = frappe.request.method
        if method not in profile.allowed_methods:
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

        # Skip for GET requests
        if frappe.request and frappe.request.method == "GET":
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
        except Exception as e:
            # Log with more detail for debugging
            self.audit_logger.log_event(
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
        """Validate rate limits"""
        try:
            self.rate_limiter.check_rate_limit(operation_key)
            return True
        except Exception as e:
            self.audit_logger.log_event(
                AuditEventType.RATE_LIMIT_EXCEEDED,
                AuditSeverity.WARNING,
                details={"operation": operation_key, "error": str(e)},
            )
            raise VPermissionError(_("Rate limit exceeded"))

    def validate_input_data(self, profile: SecurityProfile, **kwargs) -> Dict[str, Any]:
        """Validate and sanitize input data"""
        if not profile.input_validation:
            return kwargs

        validated_data = {}

        for key, value in kwargs.items():
            # Skip None values
            if value is None:
                validated_data[key] = value
                continue

            # Sanitize string inputs
            if isinstance(value, str):
                validated_data[key] = APIValidator.sanitize_text(value, max_length=1000)
            elif isinstance(value, dict):
                # Recursively validate dict inputs
                validated_data[key] = self._validate_dict_input(value)
            elif isinstance(value, list):
                # Validate list inputs
                validated_data[key] = self._validate_list_input(value)
            else:
                validated_data[key] = value

        return validated_data

    def _validate_dict_input(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate dictionary input data"""
        validated = {}
        for key, value in data.items():
            if isinstance(value, str):
                validated[key] = APIValidator.sanitize_text(value, max_length=500)
            elif isinstance(value, dict):
                validated[key] = self._validate_dict_input(value)
            elif isinstance(value, list):
                validated[key] = self._validate_list_input(value)
            else:
                validated[key] = value
        return validated

    def _validate_list_input(self, data: List[Any]) -> List[Any]:
        """Validate list input data"""
        validated = []
        for item in data:
            if isinstance(item, str):
                validated.append(APIValidator.sanitize_text(item, max_length=500))
            elif isinstance(item, dict):
                validated.append(self._validate_dict_input(item))
            elif isinstance(item, list):
                validated.append(self._validate_list_input(item))
            else:
                validated.append(item)
        return validated

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

        self.audit_logger.log_event(event_type, severity, details=details)

    def create_security_response_headers(self, profile: SecurityProfile) -> Dict[str, str]:
        """Create security-related response headers"""
        headers = {}

        # Rate limit headers
        if hasattr(frappe.local, "response"):
            rate_headers = self.rate_limiter.get_rate_limit_headers("api_call")
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
    rate_limit: Dict[str, int] = None,
    validation_schema: Dict[str, Any] = None,
    audit_level: str = "standard",
    custom_validators: List[Callable] = None,
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
            if rate_limit:
                profile.rate_limit_config.update(rate_limit)

            try:
                # Security validations
                framework.validate_authentication(profile)
                framework.validate_request_method(profile)
                framework.validate_request_size(profile)
                framework.validate_csrf_token(profile, func)

                # Rate limiting
                operation_key = f"{func.__module__}.{func.__name__}"
                framework.validate_rate_limits(profile, operation_key)

                # Input validation
                validated_kwargs = framework.validate_input_data(profile, **kwargs)

                # Custom validators
                if custom_validators:
                    for validator in custom_validators:
                        validator(**validated_kwargs)

                # Execute function
                result = func(*args, **validated_kwargs)

                # Log successful execution
                execution_time = time.time() - start_time
                framework.log_audit_event(
                    profile,
                    func,
                    True,
                    execution_time,
                    user=frappe.session.user,
                    args_count=len(args),
                    kwargs_keys=list(validated_kwargs.keys()),
                )

                # Add security headers to response
                if hasattr(frappe.local, "response"):
                    headers = framework.create_security_response_headers(profile)
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

        return wrapper

    return decorator


# Convenience decorators for common security patterns
def critical_api(operation_type: OperationType = OperationType.FINANCIAL):
    """Decorator for critical security APIs (financial, admin)"""
    return api_security_framework(
        security_level=SecurityLevel.CRITICAL, operation_type=operation_type, audit_level="detailed"
    )


def high_security_api(operation_type: OperationType = OperationType.MEMBER_DATA):
    """Decorator for high security APIs (member data, batch operations)"""
    return api_security_framework(
        security_level=SecurityLevel.HIGH, operation_type=operation_type, audit_level="standard"
    )


def standard_api(operation_type: OperationType = OperationType.REPORTING):
    """Decorator for standard security APIs (reporting, read operations)"""
    return api_security_framework(
        security_level=SecurityLevel.MEDIUM, operation_type=operation_type, audit_level="standard"
    )


def utility_api(operation_type: OperationType = OperationType.UTILITY):
    """Decorator for utility APIs (health checks, status)"""
    return api_security_framework(
        security_level=SecurityLevel.LOW, operation_type=operation_type, audit_level="minimal"
    )


def public_api(operation_type: OperationType = OperationType.PUBLIC):
    """Decorator for public APIs (no authentication required)"""
    return api_security_framework(
        security_level=SecurityLevel.PUBLIC, operation_type=operation_type, audit_level="minimal"
    )


# API endpoint classification and migration utilities
@frappe.whitelist()
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
                "security_coverage": round(
                    (analysis["secured_endpoints"] / analysis["total_endpoints"]) * 100, 1
                )
                if analysis["total_endpoints"] > 0
                else 0,
                "high_priority_endpoints": len(
                    [r for r in analysis["recommendations"] if r["suggested_level"] in ["critical", "high"]]
                ),
                "total_recommendations": len(analysis["recommendations"]),
            },
        }

    except Exception as e:
        log_error(e, module="verenigingen.utils.security.api_security_framework")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_security_framework_status():
    """Get current security framework configuration and status"""
    # Require admin permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access framework status"), frappe.PermissionError)

    try:
        framework = get_security_framework()

        return {
            "success": True,
            "framework_version": "1.0.0",
            "security_levels": [level.value for level in SecurityLevel],
            "operation_types": [op.value for op in OperationType],
            "default_profiles": {
                level.value: {
                    "required_roles": profile.required_roles,
                    "rate_limit": profile.rate_limit_config,
                    "requires_csrf": profile.requires_csrf,
                    "requires_audit": profile.requires_audit,
                    "max_request_size": profile.max_request_size,
                }
                for level, profile in framework.SECURITY_PROFILES.items()
            },
            "components_status": {
                "audit_logger": framework.audit_logger is not None,
                "auth_manager": framework.auth_manager is not None,
                "rate_limiter": framework.rate_limiter is not None,
                "csrf_protection": framework.csrf_protection is not None,
            },
        }

    except Exception as e:
        log_error(e, module="verenigingen.utils.security.api_security_framework")
        return {"success": False, "error": str(e)}


def setup_api_security_framework():
    """Setup API security framework during app initialization"""
    # Initialize global framework
    global _security_framework
    _security_framework = APISecurityFramework()

    # Log setup completion
    _security_framework.audit_logger.log_event(
        "api_security_framework_initialized",
        AuditSeverity.INFO,
        details={
            "security_levels": [level.value for level in SecurityLevel],
            "operation_types": [op.value for op in OperationType],
            "components_loaded": True,
        },
    )
