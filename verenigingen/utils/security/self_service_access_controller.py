"""
Self-Service Access Controller for API Security Framework

Validates that users can only access their own data in self-service operations.
Provides TOCTOU protection through deep request content validation.

DEPENDENCY RULES:
- MAY import from types.py
- MAY use Frappe for DB access and session info
- MUST NOT import from api_security_framework.py (to avoid circular imports)
"""

import json
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.client_ip import get_client_ip as centralized_get_client_ip
from verenigingen.utils.security.types import AuditEventType, AuditSeverity


def _try_parse_json(value: str):
    """Best-effort parse of a JSON-encoded string.

    Returns the parsed object on success, or None if the string is not JSON.
    Used by the self-service content inspector to see member/volunteer
    references hidden inside JSON string payloads.
    """
    if not value or value[0] not in "[{":
        # Fast reject: only object/array JSON payloads can contain nested
        # member/volunteer references. Skips the exception cost for plain
        # scalars, member names, IBANs, etc.
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


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
        """
        Get client IP address with trusted proxy support.

        Uses injected function for testing, otherwise falls back to
        centralized client_ip module for consistent IP detection.
        """
        if self._get_client_ip_func:
            return self._get_client_ip_func()

        return centralized_get_client_ip()

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
            # Use the canonical resolver (Member.user first, Member.email fallback)
            # so the framework's ownership gate matches what the endpoint bodies
            # resolve via get_current_user_member_name. Resolving email-only here
            # wrongly locked out members linked via Member.user whose Member.email
            # differs from their login.
            from verenigingen.utils.member_utils import get_member_name_for_user

            return get_member_name_for_user(user)
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

    def validate_access(self, implicit_allowed: bool = False, **kwargs) -> bool:
        """
        Validate that user can only access their own data in self-service operations.

        Args:
            implicit_allowed: If True, allow operations without explicit member parameter
                (the operation will default to the current user's member). If False
                (default), operations MUST have an explicit member parameter.
            **kwargs: Request parameters to validate

        Returns:
            True if access is allowed

        Raises:
            VPermissionError: If access is denied

        SECURITY NOTE:
        implicit_allowed=False (default) is the safe choice. Only set to True for
        endpoints that are explicitly designed to operate on "current user's data"
        without a member parameter (e.g., get_my_profile, update_my_preferences).
        """
        current_user = frappe.session.user

        # Skip validation for system users
        if current_user in ("Administrator", "Guest"):
            return True

        # Get user's member record
        user_member = self.get_user_member(current_user)

        # Collect EVERY explicit member/volunteer identifier present in the request.
        # Validating only the first one let an attacker pass a matching `member`
        # while smuggling a foreign `member_id`/`volunteer` that the endpoint then
        # acts on. Every explicit target must resolve to the caller's own member.
        explicit_targets = self._extract_target_members(**kwargs)

        # Handle implicit self-service (no explicit target)
        if not explicit_targets:
            return self._handle_implicit_self_service(current_user, user_member, implicit_allowed)

        # Validate explicit target access - all identifiers must match the caller.
        for field, target_member in explicit_targets:
            # An explicit volunteer/member reference that cannot be resolved to a
            # member (nonexistent, or no member link) is a foreign/invalid target,
            # not "no target" - fail closed rather than collapsing to implicit self.
            if target_member is None:
                raise VPermissionError(
                    _("Access denied: unable to verify your ownership of '{0}'").format(field)
                )
            self._validate_target_access(target_member, user_member)

        return True

    def _extract_target_members(self, **kwargs) -> List[tuple]:
        """
        Extract ALL target member identifiers from request parameters.

        Args:
            **kwargs: Request parameters

        Returns:
            List of (field_name, resolved_member_or_None) tuples for every member/
            volunteer identifier present in the request. `volunteer` values are
            resolved to their linked member (None if unresolvable).
        """
        targets = []
        for field in self.MEMBER_FIELDS:
            if field in kwargs and kwargs[field]:
                if field == "volunteer":
                    # For volunteer operations, resolve the linked member.
                    targets.append((field, self.get_volunteer_member(kwargs[field])))
                else:
                    targets.append((field, kwargs[field]))
        return targets

    def _handle_implicit_self_service(
        self, current_user: str, user_member: Optional[str], implicit_allowed: bool
    ) -> bool:
        """
        Handle self-service operations without explicit member target.

        Args:
            current_user: Current session user
            user_member: User's linked member record
            implicit_allowed: Whether implicit self-service is allowed for this endpoint

        Returns:
            True if implicit self-service is allowed

        Raises:
            VPermissionError: If implicit self-service is not allowed or user has no member record
        """
        # SECURITY: Reject implicit self-service unless explicitly allowed
        # This prevents accidental "any member can call this" vulnerabilities
        if not implicit_allowed:
            raise VPermissionError(
                _(
                    "Access denied: This self-service operation requires an explicit member parameter. "
                    "Please specify which member record this operation should act on."
                )
            )

        if not user_member:
            raise VPermissionError(
                _(
                    "Access denied: No member record found for user. "
                    "Self-service operations require valid member account."
                )
            )

        # Log for monitoring - implicit self-service operations
        frappe.logger("verenigingen.api_security").debug(
            f"Implicit self-service operation for user {current_user} (member: {user_member})"
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
            if isinstance(data, str):
                # Frappe delivers nested / child-table payloads as JSON strings.
                # Parse them so member/volunteer references hidden inside a JSON
                # string (e.g. data='{"member":"VICTIM"}') are not invisible to
                # the ownership inspection.
                parsed = _try_parse_json(data)
                if isinstance(parsed, (dict, list)):
                    inspect_data(parsed, path)
                return

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

                    # Recursively check nested structures (dict/list) and
                    # JSON-encoded strings.
                    else:
                        inspect_data(value, current_path)

            elif isinstance(data, list):
                for i, item in enumerate(data):
                    inspect_data(item, f"{path}[{i}]")

        # Inspect all parameters, including top-level scalar member/volunteer
        # identifiers (member_id, member_name, volunteer_id, ...) which were
        # previously skipped because only dict/list values were recursed into.
        inspect_data(kwargs)

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
