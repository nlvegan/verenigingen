"""
Security Package for Verenigingen SEPA Operations

This package provides comprehensive security measures for SEPA operations including:
- CSRF protection
- Rate limiting
- Role-based authorization
- Comprehensive audit logging

All security measures are configured to work together seamlessly.
"""

from .audit_logging import AuditEventType, AuditSeverity, SEPAAuditLogger, audit_log, setup_audit_logging
from .authorization import (
    SEPAAuthorizationManager,
    SEPAOperation,
    SEPAPermissionLevel,
    require_sepa_permission,
    setup_authorization,
)
from .csrf_protection import CSRFProtection, require_csrf_token, setup_csrf_protection
from .rate_limiting import RateLimiter, rate_limit, setup_rate_limiting

__all__ = [
    # CSRF Protection
    "CSRFProtection",
    "require_csrf_token",
    "setup_csrf_protection",
    # Rate Limiting
    "RateLimiter",
    "rate_limit",
    "setup_rate_limiting",
    # Authorization
    "SEPAAuthorizationManager",
    "SEPAOperation",
    "SEPAPermissionLevel",
    "require_sepa_permission",
    "setup_authorization",
    # Audit Logging
    "SEPAAuditLogger",
    "AuditEventType",
    "AuditSeverity",
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
    - Rate limiting
    - Authorization system
    - Audit logging
    """
    try:
        # Setup individual components
        setup_csrf_protection()
        setup_rate_limiting()
        setup_authorization()
        setup_audit_logging()

        # Log successful security setup
        from .audit_logging import AuditSeverity, log_sepa_event

        log_sepa_event(
            "security_system_initialized",
            details={
                "components": ["csrf_protection", "rate_limiting", "authorization", "audit_logging"],
                "status": "all_components_active",
            },
            severity=AuditSeverity.INFO,
        )

        return True

    except Exception as e:
        import frappe

        frappe.log_error(f"Security setup failed: {str(e)}", "Security System Setup Error")
        return False
