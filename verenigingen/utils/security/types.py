"""
Security Framework Type Definitions

Centralized location for all enums and constants used across the security framework.
This module eliminates circular import issues and provides a single source of truth
for security-related type definitions.
"""

from enum import Enum


class SecurityLevel(Enum):
    """API Security Classification Levels"""

    CRITICAL = "critical"  # Financial transactions, member data changes, system administration
    HIGH = "high"  # Member data access, batch operations, administrative functions
    MEDIUM = "medium"  # Reporting, read-only operations, analytics
    LOW = "low"  # Public information, utility functions, health checks
    PUBLIC = "public"  # No authentication required


class EnvironmentLevel(Enum):
    """Deployment environment levels for environment-aware security"""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class OperationType(Enum):
    """Types of operations for context-aware security"""

    FINANCIAL = "financial"  # Payment processing, invoicing, SEPA operations
    MEMBER_DATA = "member_data"  # Member information access/modification
    ADMIN = "admin"  # System administration, settings
    REPORTING = "reporting"  # Data export, analytics, dashboards
    UTILITY = "utility"  # Health checks, status endpoints
    PUBLIC = "public"  # Public information, documentation
    WEBHOOK_PROCESSING = "webhook_processing"  # Webhook endpoints with configurable rate limits


class AuditEventType(Enum):
    """Audit event types for categorization"""

    # SEPA Operations (stored in SEPA Audit Log)
    SEPA_BATCH_CREATED = "sepa_batch_created"
    SEPA_BATCH_VALIDATED = "sepa_batch_validated"
    SEPA_BATCH_PROCESSED = "sepa_batch_processed"
    SEPA_BATCH_CANCELLED = "sepa_batch_cancelled"
    SEPA_XML_GENERATED = "sepa_xml_generated"
    SEPA_INVOICE_LOADED = "sepa_invoice_loaded"
    SEPA_MANDATE_VALIDATED = "sepa_mandate_validated"

    # Additional SEPA process types to match SEPA Audit Log options
    MANDATE_CREATION = "mandate_creation"
    BATCH_GENERATION = "batch_generation"
    BANK_SUBMISSION = "bank_submission"
    PAYMENT_PROCESSING = "payment_processing"

    # API and Security Events (stored in API Audit Log)
    API_CALL_SUCCESS = "api_call_success"
    API_CALL_FAILED = "api_call_failed"
    CSRF_VALIDATION_SUCCESS = "csrf_validation_success"
    CSRF_VALIDATION_FAILED = "csrf_validation_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    PERMISSION_DENIED = "permission_denied"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

    # Authentication Events (stored in API Audit Log)
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    SESSION_EXPIRED = "session_expired"
    FAILED_LOGIN_ATTEMPT = "failed_login_attempt"

    # Data Events (stored in API Audit Log)
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    DATA_EXPORT = "data_export"
    DATA_IMPORT = "data_import"
    DATA_MODIFICATION = "data_modification"

    # System Events (stored in API Audit Log)
    CONFIGURATION_CHANGE = "configuration_change"
    SYSTEM_ERROR = "system_error"
    PERFORMANCE_ALERT = "performance_alert"

    # Parameter Security Events
    PARAMETER_TAMPERING = "parameter_tampering"
    SELF_SERVICE_VIOLATION = "self_service_violation"
    BULK_DATA_ACCESS = "bulk_data_access"


class AuditSeverity(Enum):
    """Audit event severity levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# Lightweight security decorators without circular imports
def utility_api(operation_type: OperationType):
    """Lightweight security decorator for utility operations without circular dependencies"""

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            import frappe
            from frappe import _

            # Basic security checks without importing heavy modules
            if not frappe.session.user or frappe.session.user == "Guest":
                frappe.throw(_("Authentication required"), frappe.PermissionError)

            # Log API call for audit
            try:
                frappe.logger().info(
                    {
                        "event": "api_call",
                        "function": func.__name__,
                        "operation_type": operation_type.value,
                        "user": frappe.session.user,
                        "timestamp": frappe.utils.now(),
                    },
                    "API Security",
                )
            except Exception:
                pass  # Don't fail on logging errors

            return func(*args, **kwargs)

        return wrapper

    return decorator


def development_only_api(operation_type: OperationType):
    """Lightweight development-only decorator without circular dependencies"""

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            import frappe
            from frappe import _

            # Development-only check
            if not frappe.conf.developer_mode:
                frappe.throw(_("API only available in developer mode"), frappe.PermissionError)

            # Basic security checks
            if not frappe.session.user or frappe.session.user == "Guest":
                frappe.throw(_("Authentication required"), frappe.PermissionError)

            # Require admin permission for development APIs
            if not frappe.has_permission("System Manager"):
                frappe.throw(_("System Manager permission required"), frappe.PermissionError)

            # Log development API usage
            try:
                frappe.logger().info(
                    {
                        "event": "development_api_call",
                        "function": func.__name__,
                        "operation_type": operation_type.value,
                        "user": frappe.session.user,
                        "timestamp": frappe.utils.now(),
                    },
                    "Development API",
                )
            except Exception:
                pass  # Don't fail on logging errors

            return func(*args, **kwargs)

        return wrapper

    return decorator
