"""
Security Framework Type Definitions

Centralized location for all enums and constants used across the security framework.
This module eliminates circular import issues and provides a single source of truth
for security-related type definitions.

DEPENDENCY RULES:
- This is the lowest layer of the security module
- No other security modules should be imported here
- All other security modules MAY import from this module
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


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


class ExecutionContext(Enum):
    """Execution contexts for scope-based rate limiting"""

    INTERACTIVE = "interactive"  # HTTP requests from users
    BACKGROUND_JOB = "background_job"  # Queued jobs via frappe.enqueue()
    SCHEDULED_TASK = "scheduled_task"  # Cron jobs from scheduler
    CLI = "cli"  # Bench commands, console, tests


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

    # Dues Invoice Workflow Events
    DUES_ANALYSIS_STARTED = "dues_analysis_started"
    DUES_ANALYSIS_COMPLETED = "dues_analysis_completed"
    INVOICE_GENERATION_STARTED = "invoice_generation_started"
    INVOICE_GENERATION_COMPLETED = "invoice_generation_completed"
    SEPA_BATCH_CREATION_STARTED = "sepa_batch_creation_started"

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
    AUDIT_SYSTEM_INITIALIZED = "audit_system_initialized"
    SECURITY_SYSTEM_INITIALIZED = "security_system_initialized"

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


# ============================================================================
# Data Classes for Security Framework Components
# ============================================================================


@dataclass
class AuthResult:
    """
    Result of an authorization decision.

    This is returned by AuthorizationPolicy.decide() and contains all information
    needed for audit logging and error reporting.

    Attributes:
        granted: Whether access was granted
        rule_matched: Which rule determined the outcome (e.g., "rule_4_role_profile", "rule_7_deny")
        auth_path: The authorization path for audit (e.g., "role_profile:Verenigingen Administrator")
        reason: Human-readable reason (especially for denials)
    """

    granted: bool
    rule_matched: str
    auth_path: str = ""
    reason: str = ""


@dataclass
class SecurityProfile:
    """
    Security profile defining requirements for each security level.

    This is a data transfer object that carries security configuration
    for an API endpoint. It does NOT contain business logic.
    """

    level: SecurityLevel
    # Note: Authorization is now handled via ROLE_PROFILE_SECURITY_MAPPING in authorization_policy.py
    # The required_roles field was removed as it was unused dead code
    required_permissions: List[str] = field(default_factory=list)
    requires_csrf: bool = True
    requires_audit: bool = True
    input_validation: bool = True
    ip_restrictions: bool = False
    business_hours_only: bool = False
    max_request_size: int = 1024 * 1024  # 1MB default
    allowed_methods: List[str] = field(default_factory=lambda: ["GET", "POST"])
    allowed_environments: Optional[List["EnvironmentLevel"]] = None

    def __post_init__(self):
        """Set default environments if not provided."""
        if self.allowed_environments is None:
            self.allowed_environments = [
                EnvironmentLevel.PRODUCTION,
                EnvironmentLevel.STAGING,
                EnvironmentLevel.DEVELOPMENT,
            ]


# Note: Security decorators (utility_api, development_only_api, etc.) are now
# in api_security_framework.py. Import from there:
#   from verenigingen.utils.security.api_security_framework import utility_api, development_only_api
