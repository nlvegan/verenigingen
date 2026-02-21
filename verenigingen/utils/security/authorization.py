"""
Role-Based Access Control and Authorization System for SEPA Operations

This module provides comprehensive authorization checks, role-based access control,
and permission validation for sensitive SEPA operations with granular controls.

CONSOLIDATION NOTE:
As of January 2026, SEPA authorization now uses Role Profiles for consistency
with the main API Security Framework. The ROLE_PROFILE_PERMISSIONS mapping uses
the same Role Profile names as authorization_policy.py's ROLE_PROFILE_SECURITY_MAPPING.

Role Profile-based authorization:
- Uses User.role_profile_name (direct assignment)
- Cached with 5-minute TTL via authorization_engine.py
- Aligns with the 7-rule authorization decision chain
"""

from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import PermissionError as VerenigingenPermissionError, log_error
from verenigingen.utils.security.audit_logging import AuditEventType, AuditSeverity, log_security_event
from verenigingen.utils.security.authorization_engine import get_authorization_engine
from verenigingen.utils.security.types import OperationType


class SEPAPermissionLevel(Enum):
    """SEPA permission levels"""

    READ = "read"  # View SEPA data and reports
    VALIDATE = "validate"  # Validate invoices and mandates
    CREATE = "create"  # Create SEPA batches
    PROCESS = "process"  # Process and execute batches
    ADMIN = "admin"  # Full administrative access
    AUDIT = "audit"  # Audit and compliance access


class SEPAOperation(Enum):
    """SEPA operations requiring authorization"""

    # Batch Operations
    BATCH_CREATE = "batch_create"
    BATCH_VALIDATE = "batch_validate"
    BATCH_PROCESS = "batch_process"
    BATCH_CANCEL = "batch_cancel"
    BATCH_DELETE = "batch_delete"

    # Invoice Operations
    INVOICE_LOAD = "invoice_load"
    INVOICE_VALIDATE = "invoice_validate"
    INVOICE_EXCLUDE = "invoice_exclude"

    # XML Operations
    XML_GENERATE = "xml_generate"
    XML_PREVIEW = "xml_preview"
    XML_DOWNLOAD = "xml_download"

    # Analytics and Reporting
    ANALYTICS_VIEW = "analytics_view"
    REPORTS_GENERATE = "reports_generate"
    AUDIT_LOGS_VIEW = "audit_logs_view"

    # Administrative Operations
    SETTINGS_MODIFY = "settings_modify"
    PERMISSIONS_MODIFY = "permissions_modify"
    SYSTEM_MAINTENANCE = "system_maintenance"


class SEPAAuthorizationManager:
    """
    Comprehensive authorization manager for SEPA operations

    Provides Role Profile-based access control with granular permissions,
    context-aware authorization, and audit logging.

    CONSOLIDATION: Now uses Role Profile names that align with
    authorization_policy.py's ROLE_PROFILE_SECURITY_MAPPING.
    """

    # Role Profile-based permission matrix
    # Keys are Role Profile names from User.role_profile_name
    # Also includes individual Frappe role names for backwards compatibility
    # (used by the fallback in get_user_permissions() when no role profile matches)
    #
    # Aligns with authorization_policy.py's ROLE_PROFILE_SECURITY_MAPPING
    ROLE_PROFILE_PERMISSIONS = {
        # =========================================================================
        # Frappe System Roles (backwards compatibility)
        # =========================================================================
        # These entries allow users with individual Frappe roles (but no role
        # profile assignment) to still access SEPA operations via the backwards
        # compatibility fallback in get_user_permissions().
        #
        # System Manager: Frappe's built-in admin role - full SEPA access
        Roles.SYSTEM_MANAGER: [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
            SEPAPermissionLevel.ADMIN,
            SEPAPermissionLevel.AUDIT,
        ],
        # Verenigingen Governance Auditor: Individual Frappe role for audit access
        "Verenigingen Governance Auditor": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.AUDIT,
        ],
        # =========================================================================
        # Verenigingen Role Profiles (primary authorization)
        # =========================================================================
        # System Administrator: Full access to all SEPA operations
        "Verenigingen System Administrator": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
            SEPAPermissionLevel.ADMIN,
            SEPAPermissionLevel.AUDIT,
        ],
        # Administrator: Full operational access, no system admin
        Roles.VERENIGINGEN_ADMIN: [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
            SEPAPermissionLevel.AUDIT,
        ],
        # Treasurer: Full financial access including audit
        "Verenigingen Treasurer": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
            SEPAPermissionLevel.AUDIT,
        ],
        # National Board Member: Full operational access for national oversight
        "Verenigingen National Board Member": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
            SEPAPermissionLevel.AUDIT,
        ],
        # Staff: Operational access without audit
        Roles.VERENIGINGEN_STAFF: [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
            SEPAPermissionLevel.CREATE,
            SEPAPermissionLevel.PROCESS,
        ],
        # Chapter Board Member: Limited to read and validate
        "Verenigingen Chapter Board Member": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.VALIDATE,
        ],
        # Auditor: Read-only with audit access (was "Verenigingen Governance Auditor")
        "Verenigingen Auditor": [
            SEPAPermissionLevel.READ,
            SEPAPermissionLevel.AUDIT,
        ],
    }

    # Legacy alias for backwards compatibility during transition
    # TODO: Remove after verifying all usages are updated
    ROLE_PERMISSIONS = ROLE_PROFILE_PERMISSIONS

    # Operation permission requirements
    OPERATION_REQUIREMENTS = {
        SEPAOperation.BATCH_CREATE: SEPAPermissionLevel.CREATE,
        SEPAOperation.BATCH_VALIDATE: SEPAPermissionLevel.VALIDATE,
        SEPAOperation.BATCH_PROCESS: SEPAPermissionLevel.PROCESS,
        SEPAOperation.BATCH_CANCEL: SEPAPermissionLevel.PROCESS,
        SEPAOperation.BATCH_DELETE: SEPAPermissionLevel.ADMIN,
        SEPAOperation.INVOICE_LOAD: SEPAPermissionLevel.READ,
        SEPAOperation.INVOICE_VALIDATE: SEPAPermissionLevel.VALIDATE,
        SEPAOperation.INVOICE_EXCLUDE: SEPAPermissionLevel.CREATE,
        SEPAOperation.XML_GENERATE: SEPAPermissionLevel.PROCESS,
        SEPAOperation.XML_PREVIEW: SEPAPermissionLevel.READ,
        SEPAOperation.XML_DOWNLOAD: SEPAPermissionLevel.PROCESS,
        SEPAOperation.ANALYTICS_VIEW: SEPAPermissionLevel.READ,
        SEPAOperation.REPORTS_GENERATE: SEPAPermissionLevel.READ,
        SEPAOperation.AUDIT_LOGS_VIEW: SEPAPermissionLevel.AUDIT,
        SEPAOperation.SETTINGS_MODIFY: SEPAPermissionLevel.ADMIN,
        SEPAOperation.PERMISSIONS_MODIFY: SEPAPermissionLevel.ADMIN,
        SEPAOperation.SYSTEM_MAINTENANCE: SEPAPermissionLevel.ADMIN,
    }

    # Time-based restrictions (business hours)
    BUSINESS_HOURS_OPERATIONS = [SEPAOperation.BATCH_PROCESS, SEPAOperation.XML_GENERATE]

    # IP-based restrictions (if configured)
    IP_RESTRICTED_OPERATIONS = [
        SEPAOperation.BATCH_DELETE,
        SEPAOperation.SETTINGS_MODIFY,
        SEPAOperation.PERMISSIONS_MODIFY,
    ]

    def __init__(self):
        """Initialize authorization manager"""
        self.allowed_ips = self._get_allowed_ips()
        self.business_hours = self._get_business_hours()

    def _get_allowed_ips(self) -> List[str]:
        """Get allowed IP addresses from configuration"""
        try:
            # Get from site config or Verenigingen Payments Settings
            allowed_ips = frappe.conf.get("sepa_allowed_ips", [])

            # Also check Verenigingen Payments Settings
            settings_ips = frappe.db.get_single_value("Verenigingen Payments Settings", "sepa_allowed_ips")
            if settings_ips:
                settings_ips_list = [ip.strip() for ip in settings_ips.split(",") if ip.strip()]
                allowed_ips.extend(settings_ips_list)

            return list(set(allowed_ips))  # Remove duplicates

        except Exception:
            return []

    def _get_business_hours(self) -> Dict[str, Any]:
        """Get business hours configuration"""
        try:
            return {
                "enabled": frappe.conf.get("sepa_business_hours_enabled", False),
                "start_hour": frappe.conf.get("sepa_business_hours_start", 9),
                "end_hour": frappe.conf.get("sepa_business_hours_end", 17),
                "timezone": frappe.conf.get("sepa_business_hours_timezone", "Europe/Amsterdam"),
                "weekdays_only": frappe.conf.get("sepa_business_hours_weekdays_only", True),
            }
        except Exception:
            return {"enabled": False}

    def get_user_permissions(self, user: str = None) -> List[SEPAPermissionLevel]:
        """
        Get SEPA permission levels for user based on Role Profiles.

        Uses the authorization engine's cached role profile lookup for consistency
        with the main API Security Framework.

        Args:
            user: User email (defaults to current user)

        Returns:
            List of permission levels granted by the user's Role Profile
        """
        if not user:
            user = frappe.session.user

        # System users (Administrator, System) always have all permissions
        if user in ["Administrator", "System"]:
            return list(SEPAPermissionLevel)

        try:
            # Get user's role profiles from the authorization engine (cached)
            auth_engine = get_authorization_engine()
            user_role_profiles = auth_engine.get_user_role_profiles(user)
            permissions = set()

            # Check each assigned role profile
            for role_profile in user_role_profiles:
                if role_profile in self.ROLE_PROFILE_PERMISSIONS:
                    permissions.update(self.ROLE_PROFILE_PERMISSIONS[role_profile])

            # Fallback: Also check individual roles for backwards compatibility
            # This allows users with matching role names (but no role profile) to still work
            # TODO: Remove this fallback after migration is complete
            if not permissions:
                user_roles = frappe.get_roles(user)
                for role in user_roles:
                    if role in self.ROLE_PROFILE_PERMISSIONS:
                        permissions.update(self.ROLE_PROFILE_PERMISSIONS[role])

            return list(permissions)

        except Exception as e:
            log_error(e, context={"user": user}, module="verenigingen.utils.security.authorization")
            return []

    def has_permission(
        self, operation: SEPAOperation, user: str = None, context: Dict[str, Any] = None
    ) -> bool:
        """
        Check if user has permission for specific operation

        Args:
            operation: SEPA operation to check
            user: User email (defaults to current user)
            context: Additional context for authorization

        Returns:
            True if user has permission
        """
        if not user:
            user = frappe.session.user

        # System users always have permission
        if user in ["Administrator", "System"]:
            return True

        try:
            # Get required permission level
            required_level = self.OPERATION_REQUIREMENTS.get(operation)
            if not required_level:
                return False

            # Get user permissions
            user_permissions = self.get_user_permissions(user)

            # Check if user has required permission level
            if required_level not in user_permissions:
                return False

            # Additional context-based checks
            if not self._check_contextual_permissions(operation, user, context):
                return False

            return True

        except Exception as e:
            log_error(
                e,
                context={"operation": operation.value, "user": user, "context": context},
                module="verenigingen.utils.security.authorization",
            )
            return False

    def _check_contextual_permissions(
        self, operation: SEPAOperation, user: str, context: Dict[str, Any] = None
    ) -> bool:
        """
        Check contextual permissions (time, IP, etc.)

        Args:
            operation: SEPA operation
            user: User email
            context: Additional context

        Returns:
            True if contextual checks pass
        """
        try:
            # Business hours check
            if operation in self.BUSINESS_HOURS_OPERATIONS:
                if not self._check_business_hours():
                    log_security_event(
                        AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
                        details={
                            "reason": "outside_business_hours",
                            "operation": operation.value,
                            "user": user,
                        },
                        severity=AuditSeverity.WARNING,
                    )
                    return False

            # IP restriction check
            if operation in self.IP_RESTRICTED_OPERATIONS:
                if not self._check_ip_restrictions():
                    log_security_event(
                        AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT,
                        details={
                            "reason": "ip_restriction",
                            "operation": operation.value,
                            "user": user,
                            "ip": getattr(frappe.local, "request_ip", "unknown"),
                        },
                        severity=AuditSeverity.WARNING,
                    )
                    return False

            # Batch-specific checks
            if context and operation in [SEPAOperation.BATCH_PROCESS, SEPAOperation.BATCH_CANCEL]:
                if not self._check_batch_permissions(context, user):
                    return False

            return True

        except Exception as e:
            log_error(
                e,
                context={"operation": operation.value, "user": user},
                module="verenigingen.utils.security.authorization",
            )
            return False

    def _check_business_hours(self) -> bool:
        """Check if current time is within business hours"""
        if not self.business_hours.get("enabled"):
            return True

        try:
            from datetime import datetime

            import pytz

            # Get current time in configured timezone
            tz = pytz.timezone(self.business_hours.get("timezone", "Europe/Amsterdam"))
            current_time = datetime.now(tz)

            # Check weekdays only restriction
            if self.business_hours.get("weekdays_only") and current_time.weekday() >= 5:
                return False

            # Check hour range
            start_hour = self.business_hours.get("start_hour", 9)
            end_hour = self.business_hours.get("end_hour", 17)

            if not (start_hour <= current_time.hour < end_hour):
                return False

            return True

        except Exception:
            # If timezone check fails, allow operation
            return True

    def _check_ip_restrictions(self) -> bool:
        """Check if current IP is allowed for restricted operations"""
        if not self.allowed_ips:
            return True  # No restrictions configured

        try:
            current_ip = getattr(frappe.local, "request_ip", None)
            if not current_ip:
                return True  # Can't determine IP, allow operation

            # Check if IP is in allowed list
            return current_ip in self.allowed_ips

        except Exception:
            return True  # If IP check fails, allow operation

    def _check_batch_permissions(self, context: Dict[str, Any], user: str) -> bool:
        """Check batch-specific permissions"""
        try:
            batch_name = context.get("batch_name")
            if not batch_name:
                return True

            # Check if user created the batch or has admin permissions
            batch_doc = frappe.get_doc("Direct Debit Batch", batch_name)

            # Allow if user created the batch
            if batch_doc.owner == user:
                return True

            # Allow if user has admin permissions
            user_permissions = self.get_user_permissions(user)
            if SEPAPermissionLevel.ADMIN in user_permissions:
                return True

            # Allow if user has process permissions and batch is in appropriate status
            if SEPAPermissionLevel.PROCESS in user_permissions:
                if batch_doc.status in ["Draft", "Validated"]:
                    return True

            return False

        except Exception as e:
            log_error(
                e,
                context={"context": context, "user": user},
                module="verenigingen.utils.security.authorization",
            )
            return False

    def validate_operation(
        self,
        operation: SEPAOperation,
        user: str = None,
        context: Dict[str, Any] = None,
        raise_exception: bool = True,
    ) -> bool:
        """
        Validate operation with comprehensive checks and logging

        Args:
            operation: SEPA operation to validate
            user: User email (defaults to current user)
            context: Additional context
            raise_exception: Whether to raise exception if validation fails

        Returns:
            True if validation passes

        Raises:
            VerenigingenPermissionError: If validation fails and raise_exception=True
        """
        if not user:
            user = frappe.session.user

        try:
            # Check basic permission
            has_perm = self.has_permission(operation, user, context)

            if has_perm:
                # Log successful authorization
                log_security_event(
                    "sensitive_data_access",
                    details={
                        "operation": operation.value,
                        "user": user,
                        "context": context or {},
                        "authorization_result": "granted",
                        "resource_type": "sepa_operation",
                    },
                    severity="info",
                )
                return True
            else:
                # Log authorization failure
                log_security_event(
                    AuditEventType.PERMISSION_DENIED,
                    details={
                        "operation": operation.value,
                        "user": user,
                        "user_permissions": [p.value for p in self.get_user_permissions(user)],
                        "required_permission": self.OPERATION_REQUIREMENTS.get(operation, "unknown").value,
                        "context": context or {},
                    },
                    severity=AuditSeverity.WARNING,
                )

                if raise_exception:
                    raise VerenigingenPermissionError(
                        _("Access denied for operation '{0}'. Required permission: {1}").format(
                            operation.value, self.OPERATION_REQUIREMENTS.get(operation, "unknown").value
                        )
                    )

                return False

        except VerenigingenPermissionError:
            raise
        except Exception as e:
            log_error(
                e,
                context={"operation": operation.value, "user": user, "context": context},
                module="verenigingen.utils.security.authorization",
            )

            if raise_exception:
                raise VerenigingenPermissionError(
                    _("Authorization check failed for operation '{0}'").format(operation.value)
                )

            return False


# Global authorization manager instance
_auth_manager = None


def get_auth_manager() -> SEPAAuthorizationManager:
    """Get global authorization manager instance"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = SEPAAuthorizationManager()
    return _auth_manager


# Authorization decorators
def require_sepa_permission(operation: SEPAOperation, context_param: str = None):
    """
    Decorator to require specific SEPA permission for API endpoints

    Usage:
        @frappe.whitelist()
        @require_sepa_permission(SEPAOperation.BATCH_CREATE)
        def create_sepa_batch():
            # Function implementation

        @frappe.whitelist()
        @require_sepa_permission(SEPAOperation.BATCH_PROCESS, context_param="batch_name")
        def process_batch(batch_name):
            # Function implementation
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                auth_manager = get_auth_manager()

                # Build context from parameters if specified
                context = {}
                if context_param and context_param in kwargs:
                    context[context_param] = kwargs[context_param]

                # Validate operation
                auth_manager.validate_operation(operation, context=context)

                return func(*args, **kwargs)

            except VerenigingenPermissionError as e:
                frappe.throw(str(e), exc=frappe.PermissionError)
            except Exception as e:
                log_error(
                    e,
                    context={"function": func.__name__, "operation": operation.value},
                    module="verenigingen.utils.security.authorization",
                )
                frappe.throw(_("Authorization check failed"), exc=frappe.PermissionError)

        return wrapper

    return decorator


# Convenience decorators for common operations
def require_sepa_read(func):
    """Require SEPA read permission"""
    return require_sepa_permission(SEPAOperation.ANALYTICS_VIEW)(func)


def require_sepa_create(func):
    """Require SEPA create permission"""
    return require_sepa_permission(SEPAOperation.BATCH_CREATE)(func)


def require_sepa_process(func):
    """Require SEPA process permission"""
    return require_sepa_permission(SEPAOperation.BATCH_PROCESS)(func)


def require_sepa_admin(func):
    """Require SEPA admin permission"""
    return require_sepa_permission(SEPAOperation.SETTINGS_MODIFY)(func)


# API endpoints for permission management
@frappe.whitelist(allow_guest=False)
def get_user_sepa_permissions(user: str = None):
    # Utility operation: SEPA permission retrieval
    """
    Get SEPA permissions for user based on Role Profile assignment.

    Permissions are now determined by the user's Role Profile (User.role_profile_name)
    rather than individual role memberships.

    Args:
        user: User email (defaults to current user)

    Returns:
        Dictionary with user permissions, role profiles, and available operations
    """
    try:
        auth_manager = get_auth_manager()
        auth_engine = get_authorization_engine()

        if not user:
            user = frappe.session.user

        # Check if current user can view other user's permissions
        if user != frappe.session.user:
            current_permissions = auth_manager.get_user_permissions()
            if SEPAPermissionLevel.ADMIN not in current_permissions:
                frappe.throw(_("Access denied"), frappe.PermissionError)

        permissions = auth_manager.get_user_permissions(user)
        user_role_profiles = auth_engine.get_user_role_profiles(user)
        user_roles = frappe.get_roles(user)  # Include for backwards compatibility

        # Get available operations
        available_operations = {}
        for operation in SEPAOperation:
            available_operations[operation.value] = auth_manager.has_permission(operation, user)

        return {
            "success": True,
            "user": user,
            "permissions": [p.value for p in permissions],
            "role_profiles": user_role_profiles,  # Primary: Role Profile-based auth
            "roles": user_roles,  # Legacy: kept for backwards compatibility
            "available_operations": available_operations,
        }

    except Exception as e:
        log_error(e, context={"user": user}, module="verenigingen.utils.security.authorization")

        return {"success": False, "error": _("Failed to get user permissions"), "message": str(e)}


@frappe.whitelist()
def check_sepa_operation_permission(operation: str, context: str = None):
    # Utility operation: SEPA operation permission check
    """
    Check permission for specific SEPA operation

    Args:
        operation: Operation name
        context: JSON string with context data

    Returns:
        Dictionary with permission check result
    """
    try:
        import json

        # Parse operation
        try:
            operation_enum = SEPAOperation(operation)
        except ValueError:
            return {
                "success": False,
                "allowed": False,
                "error": _("Invalid operation: {0}").format(operation),
            }

        # Parse context
        context_data = {}
        if context:
            try:
                context_data = json.loads(context)
            except json.JSONDecodeError:
                return {"success": False, "allowed": False, "error": _("Invalid context data")}

        # Check permission
        auth_manager = get_auth_manager()
        allowed = auth_manager.has_permission(operation_enum, context=context_data)

        return {"success": True, "operation": operation, "allowed": allowed, "user": frappe.session.user}

    except Exception as e:
        log_error(
            e,
            context={"operation": operation, "context": context},
            module="verenigingen.utils.security.authorization",
        )

        return {"success": False, "allowed": False, "error": _("Permission check failed"), "message": str(e)}


def require_role(roles):
    """Simple role-based authorization decorator"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            if not frappe.session.user or frappe.session.user == "Guest":
                frappe.throw(_("Authentication required"), frappe.PermissionError)

            user_roles = frappe.get_roles(frappe.session.user)
            if not any(role in user_roles for role in roles):
                frappe.throw(_("Insufficient permissions"), frappe.PermissionError)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def setup_authorization():
    """
    Setup authorization system during app initialization
    """
    # Initialize global authorization manager
    global _auth_manager
    _auth_manager = SEPAAuthorizationManager()

    # Log setup completion
    log_security_event(
        AuditEventType.CONFIGURATION_CHANGE.value,
        details={
            "configuration_type": "authorization_system_initialized",
            "role_profile_permissions": {
                k: [p.value for p in v] for k, v in _auth_manager.ROLE_PROFILE_PERMISSIONS.items()
            },
            "operation_requirements": {
                k.value: v.value for k, v in _auth_manager.OPERATION_REQUIREMENTS.items()
            },
        },
        severity="info",
    )
