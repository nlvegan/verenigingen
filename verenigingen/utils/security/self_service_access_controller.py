"""
Self-Service Access Controller for API Security Framework

Validates that users can only access their own data in self-service operations.
Provides TOCTOU protection through deep request content validation.

DEPENDENCY RULES:
- MAY import from types.py
- MAY use Frappe for DB access and session info
- MUST NOT import from api_security_framework.py (to avoid circular imports)
"""

from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.types import AuditEventType, AuditSeverity


class SelfServiceAccessController:
    """
    Controls self-service access for API operations.

    Ensures users can only access and modify their own data.
    Provides defense-in-depth against parameter tampering attacks.

    INVARIANTS:
    - System users (Administrator, Guest) bypass validation
    - Users must have a linked Member record for self-service operations
    - Target member in request must match user's member record
    - Deep inspection catches nested member/volunteer references
    """

    # Fields that identify a member in request parameters
    MEMBER_FIELDS = ["member", "member_name", "member_id", "volunteer"]

    # Fields that are checked in deep content validation
    MEMBER_CONTENT_FIELDS = ["member", "member_name", "member_id"]
    VOLUNTEER_CONTENT_FIELDS = ["volunteer", "volunteer_name", "volunteer_id"]

    def __init__(self, audit_logger: Optional[Callable] = None, get_client_ip: Optional[Callable] = None):
        """
        Initialize the controller.

        Args:
            audit_logger: Function to log audit events (injectable for testing)
            get_client_ip: Function to get client IP (injectable for testing)
        """
        self._audit_logger = audit_logger
        self._get_client_ip_func = get_client_ip

    def _get_audit_logger(self):
        """Get audit logger, lazily initializing if needed."""
        if self._audit_logger is None:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            self._audit_logger = get_audit_logger()
        return self._audit_logger

    def _get_client_ip(self) -> str:
        """Get client IP address, using injected function or default."""
        if self._get_client_ip_func:
            return self._get_client_ip_func()

        try:
            if hasattr(frappe.local, "request") and frappe.local.request:
                return frappe.local.request.environ.get("REMOTE_ADDR", "unknown")
        except (AttributeError, RuntimeError):
            pass
        return "test_environment"

    def get_user_member(self, user: str = None) -> Optional[str]:
        """
        Get the member record linked to a user.

        Args:
            user: User email (defaults to current session user)

        Returns:
            Member name or None if not found
        """
        if not user:
            user = frappe.session.user

        try:
            return frappe.db.get_value("Member", {"email": user}, "name")
        except Exception:
            return None

    def get_volunteer_member(self, volunteer_name: str) -> Optional[str]:
        """
        Get the member linked to a volunteer record.

        Args:
            volunteer_name: Name of the volunteer document

        Returns:
            Member name or None if not found
        """
        try:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
            if hasattr(volunteer_doc, "member") and volunteer_doc.member:
                return volunteer_doc.member
        except Exception:
            pass
        return None

    def validate_access(self, **kwargs) -> bool:
        """
        Validate that user can only access their own data in self-service operations.

        Args:
            **kwargs: Request parameters to validate

        Returns:
            True if access is allowed

        Raises:
            VPermissionError: If access is denied
        """
        current_user = frappe.session.user

        # Skip validation for system users
        if current_user in ("Administrator", "Guest"):
            return True

        # Get user's member record
        user_member = self.get_user_member(current_user)

        # Find target member from request parameters
        target_member = self._extract_target_member(**kwargs)

        # Handle implicit self-service (no explicit target)
        if not target_member:
            return self._handle_implicit_self_service(current_user, user_member)

        # Validate explicit target access
        return self._validate_target_access(target_member, user_member)

    def _extract_target_member(self, **kwargs) -> Optional[str]:
        """
        Extract target member from request parameters.

        Args:
            **kwargs: Request parameters

        Returns:
            Target member name or None
        """
        for field in self.MEMBER_FIELDS:
            if field in kwargs and kwargs[field]:
                if field == "volunteer":
                    # For volunteer operations, get the linked member
                    return self.get_volunteer_member(kwargs[field])
                else:
                    return kwargs[field]
        return None

    def _handle_implicit_self_service(self, current_user: str, user_member: Optional[str]) -> bool:
        """
        Handle self-service operations without explicit member target.

        Args:
            current_user: Current session user
            user_member: User's linked member record

        Returns:
            True if implicit self-service is allowed

        Raises:
            VPermissionError: If user has no member record
        """
        if not user_member:
            raise VPermissionError(
                _(
                    "Access denied: No member record found for user. "
                    "Self-service operations require valid member account."
                )
            )

        # Log for monitoring - implicit self-service should be rare
        frappe.logger("verenigingen.api_security").info(
            f"Implicit self-service operation detected for user {current_user}. "
            f"Consider adding explicit member identification to API parameters for better security."
        )

        return True

    def _validate_target_access(self, target_member: str, user_member: Optional[str]) -> bool:
        """
        Validate access to explicit target member.

        Args:
            target_member: Target member from request
            user_member: User's linked member record

        Returns:
            True if access is allowed

        Raises:
            VPermissionError: If access is denied
        """
        if user_member:
            if target_member != user_member:
                raise VPermissionError(
                    _("Access denied: You can only perform this operation on your own data")
                )
        else:
            raise VPermissionError(_("Access denied: Unable to verify member access for this user"))

        return True

    def validate_request_content(self, user_member: str, **kwargs) -> bool:
        """
        Deep validation of request content for self-service operations.

        This catches parameter tampering where users try to access other users' data
        through nested structures. Provides TOCTOU protection.

        Args:
            user_member: User's linked member record
            **kwargs: Request parameters to validate

        Returns:
            True if content is valid

        Raises:
            VPermissionError: If violations are found
        """
        violations = self._inspect_content(user_member, **kwargs)

        if violations:
            self._log_violations(user_member, violations)
            raise VPermissionError(
                _(
                    "Access denied: Self-service operations can only be performed on your own data. "
                    "Attempted access to other member/volunteer data has been logged."
                )
            )

        return True

    def _inspect_content(self, user_member: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Recursively inspect request content for unauthorized member/volunteer references.

        Args:
            user_member: User's linked member record
            **kwargs: Request parameters

        Returns:
            List of violations found
        """
        violations = []

        def inspect_data(data, path=""):
            """Recursively inspect data for member/volunteer references"""
            if isinstance(data, dict):
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key

                    # Check for member-related fields
                    if key in self.MEMBER_CONTENT_FIELDS:
                        if value and value != user_member:
                            violations.append(
                                {"field": current_path, "attempted_value": value, "user_member": user_member}
                            )

                    # Check for volunteer-related fields
                    elif key in self.VOLUNTEER_CONTENT_FIELDS:
                        if value:
                            volunteer_member = self._check_volunteer_member(value)
                            if volunteer_member == "invalid":
                                violations.append(
                                    {
                                        "field": current_path,
                                        "attempted_value": value,
                                        "error": "Invalid volunteer reference",
                                    }
                                )
                            elif volunteer_member and volunteer_member != user_member:
                                violations.append(
                                    {
                                        "field": current_path,
                                        "attempted_value": value,
                                        "linked_member": volunteer_member,
                                        "user_member": user_member,
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

        return violations

    def _check_volunteer_member(self, volunteer_name: str) -> Optional[str]:
        """
        Check what member a volunteer is linked to.

        Args:
            volunteer_name: Name of volunteer document

        Returns:
            Member name, "invalid" if volunteer doesn't exist, or None if no link
        """
        try:
            volunteer_member = frappe.db.get_value("Volunteer", volunteer_name, "member")
            return volunteer_member
        except Exception:
            return "invalid"

    def _log_violations(self, user_member: str, violations: List[Dict[str, Any]]) -> None:
        """
        Log self-service violations for security auditing.

        Args:
            user_member: User's linked member record
            violations: List of violations found
        """
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


# Singleton instance for convenience
_self_service_controller: Optional[SelfServiceAccessController] = None


def get_self_service_controller() -> SelfServiceAccessController:
    """Get singleton SelfServiceAccessController instance."""
    global _self_service_controller
    if _self_service_controller is None:
        _self_service_controller = SelfServiceAccessController()
    return _self_service_controller
