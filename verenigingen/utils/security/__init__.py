"""
Security Package for Verenigingen Operations

This package provides comprehensive security measures including:
- API Security Framework (decorators, authorization, rate limiting)
- CSRF protection
- Role-based authorization
- Comprehensive audit logging

All security measures are configured to work together seamlessly.

Architecture (see docs/REFACTOR_API_SECURITY_FRAMEWORK.md):
- types.py: Shared enums and data classes (lowest layer)
- authorization_policy.py: Pure authorization decision logic
- authorization_engine.py: Authorization I/O layer (uses policy)
- input_validator.py: Pure input validation
- environment_validator.py: Environment-based access control
- rate_limit_engine.py: Rate limiting with COR integration
- audit_emitter.py: Security audit event emission
- api_security_framework.py: Orchestrator (uses all above)
"""

# ============================================================================
# API Security Framework (orchestrator)
# ============================================================================
from .api_security_framework import (
    APISecurityFramework,
    FrappeWhitelistAdapter,
    api_security_framework,
    critical_api,
    get_frappe_whitelist_adapter,
    get_security_framework,
    high_security_api,
    public_api,
    standard_api,
    utility_api,
    webhook_api,
)

# ============================================================================
# Audit Emitter (simplified interface for API security)
# ============================================================================
from .audit_emitter import AuditEmitter, get_audit_emitter

# ============================================================================
# Legacy SEPA-specific security (maintained for backwards compatibility)
# ============================================================================
from .audit_logging import SEPAAuditLogger, audit_log, setup_audit_logging
from .authorization import (
    SEPAAuthorizationManager,
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
    setup_authorization,
)

# ============================================================================
# Authorization Engine (I/O layer for authorization)
# ============================================================================
from .authorization_engine import (
    AuthorizationEngine,
    get_authorization_engine,
    invalidate_user_role_cache,
)

# ============================================================================
# Pure logic modules (depend only on types)
# ============================================================================
from .authorization_policy import AuthorizationPolicy, get_authorization_policy
from .csrf_protection import CSRFProtection, require_csrf_token, setup_csrf_protection

# ============================================================================
# I/O layer modules (depend on types, may use Frappe)
# ============================================================================
from .environment_validator import EnvironmentValidator, get_environment_validator
from .input_validator import InputValidator, get_input_validator

# ============================================================================
# Rate Limit Engine (COR integration)
# ============================================================================
from .rate_limit_engine import RateLimitEngine, RateLimitResult, get_rate_limit_engine
from .types import (
    AuditEventType,
    AuditSeverity,
    AuthResult,
    EnvironmentLevel,
    ExecutionContext,
    OperationType,
    SecurityLevel,
    SecurityProfile,
)

__all__ = [
    # Types
    "SecurityLevel",
    "EnvironmentLevel",
    "OperationType",
    "ExecutionContext",
    "AuditEventType",
    "AuditSeverity",
    "AuthResult",
    "SecurityProfile",
    # Authorization Policy (pure logic)
    "AuthorizationPolicy",
    "get_authorization_policy",
    # Authorization Engine (I/O layer)
    "AuthorizationEngine",
    "get_authorization_engine",
    "invalidate_user_role_cache",
    # Rate Limit Engine
    "RateLimitEngine",
    "RateLimitResult",
    "get_rate_limit_engine",
    # Audit Emitter
    "AuditEmitter",
    "get_audit_emitter",
    # Input Validator (pure logic)
    "InputValidator",
    "get_input_validator",
    # Environment Validator
    "EnvironmentValidator",
    "get_environment_validator",
    # API Security Framework
    "APISecurityFramework",
    "api_security_framework",
    "get_security_framework",
    "FrappeWhitelistAdapter",
    "get_frappe_whitelist_adapter",
    # Convenience decorators
    "critical_api",
    "high_security_api",
    "standard_api",
    "utility_api",
    "public_api",
    "webhook_api",
    # CSRF Protection
    "CSRFProtection",
    "require_csrf_token",
    "setup_csrf_protection",
    # SEPA Authorization (legacy)
    "SEPAAuthorizationManager",
    "SEPAOperation",
    "SEPAPermissionLevel",
    "require_sepa_permission",
    "setup_authorization",
    # Audit Logging
    "SEPAAuditLogger",
    "audit_log",
    "setup_audit_logging",
    # Setup
    "setup_all_security",
]


def setup_all_security():
    """
    Setup all security measures during app initialization

    This function initializes and configures all security components:
    - CSRF protection
    - Rate limiting (via COR - Critical Operation Rules)
    - Authorization system
    - Audit logging
    """
    try:
        # Setup individual components
        setup_csrf_protection()
        # Rate limiting now handled by COR (Critical Operation Rules)
        # Configured in fixtures/critical_operation_rule*.json
        setup_authorization()
        setup_audit_logging()

        # Log successful security setup
        from .audit_logging import log_sepa_event
        from .types import AuditSeverity

        log_sepa_event(
            "security_system_initialized",
            details={
                "components": ["csrf_protection", "rate_limiting_cor", "authorization", "audit_logging"],
                "status": "all_components_active",
            },
            severity=AuditSeverity.INFO,
        )

        return True

    except Exception as e:
        import frappe

        frappe.log_error(f"Security setup failed: {str(e)}", "Security System Setup Error")
        return False
