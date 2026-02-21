"""
Authorization Policy for API Security Framework

Pure decision logic for authorization. No Frappe I/O.

DEPENDENCY RULES:
- MAY import from types.py ONLY
- MUST NOT import frappe or any I/O modules
- MUST NOT access session, database, or cache
- All inputs must be passed as parameters
- All outputs are AuthResult dataclass

This module can be tested in complete isolation from Frappe.
"""

from typing import Dict, List

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.types import AuthResult, SecurityLevel


class AuthorizationPolicy:
    """
    Pure authorization decision table - no Frappe, no cache, no I/O.

    INVARIANTS:
    - Deny by default (Rule 7 always exists as final rule)
    - Every decision returns auth_path for audit trail
    - Error categories are consistent (AuthDenied, AuthExpired, etc.)
    - No side effects - pure function from inputs to AuthResult

    Authorization Decision Table
    ============================

    The authorization model uses a priority-ordered decision chain. The FIRST
    matching rule grants access; if no rule matches, access is denied.

    Priority | Rule                           | Levels Affected      | Description
    ---------|--------------------------------|----------------------|----------------------------------
    1        | PUBLIC level                   | PUBLIC only          | No authentication required
    2        | Guest check                    | All except PUBLIC    | Reject unauthenticated users
    3        | LOW level                      | LOW only             | Any authenticated user allowed
    4        | Role Profile (primary)         | MEDIUM, HIGH, CRIT   | User's assigned role profile grants access
    5        | Individual Role (secondary)    | MEDIUM, HIGH, CRIT   | User role name matches profile name in mapping
    6        | System Manager exception       | MEDIUM only          | System Manager gets MEDIUM access
    7        | DENY                           | All                  | No matching rule found
    """

    # Role Profile to Security Level mapping
    # This replaces hardcoded role lists with role profile-based access
    ROLE_PROFILE_SECURITY_MAPPING: Dict[str, List[SecurityLevel]] = {
        "Verenigingen System Administrator": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],
        Roles.VERENIGINGEN_ADMIN: [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],
        "Verenigingen Treasurer": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
        ],  # Full financial access
        "Verenigingen National Board Member": [
            SecurityLevel.CRITICAL,
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
        ],  # National oversight
        Roles.VERENIGINGEN_STAFF: [
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],
        "Verenigingen Chapter Board Member": [
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],  # + contextual for their chapter (HIGH for member data access)
        "Verenigingen Auditor": [
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],  # Audit/compliance access
        "Verenigingen Team Leader": [
            SecurityLevel.LOW,
        ],  # + contextual for their team
        "Verenigingen Member": [
            SecurityLevel.LOW,
        ],
        "Verenigingen Volunteer": [
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
        ],  # MEDIUM for self_service_only operations
        "Verenigingen Webhook User": [
            SecurityLevel.HIGH,
            SecurityLevel.MEDIUM,
            SecurityLevel.LOW,
            SecurityLevel.PUBLIC,
        ],  # Service account for webhooks and background automation
    }

    def role_profile_grants_access(self, role_profile: str, required_level: SecurityLevel) -> bool:
        """Check if a role profile grants access to the required security level."""
        allowed_levels = self.ROLE_PROFILE_SECURITY_MAPPING.get(role_profile, [])
        return required_level in allowed_levels

    def decide(
        self,
        required_level: SecurityLevel,
        user_profiles: List[str],
        user_roles: List[str],
        is_authenticated: bool,
    ) -> AuthResult:
        """
        Pure authorization decision function.

        Implements the 7-rule decision table. Returns the FIRST matching rule.

        Args:
            required_level: Security level required for the operation
            user_profiles: List of role profile names assigned to the user
            user_roles: List of individual role names assigned to the user
            is_authenticated: True if user is not Guest

        Returns:
            AuthResult with granted, rule_matched, auth_path, and reason
        """
        # ===== RULE 1: PUBLIC level - no authentication required =====
        if required_level == SecurityLevel.PUBLIC:
            return AuthResult(
                granted=True,
                rule_matched="rule_1_public",
                auth_path="public_access",
                reason="PUBLIC level requires no authentication",
            )

        # ===== RULE 2: Reject unauthenticated users =====
        if not is_authenticated:
            return AuthResult(
                granted=False,
                rule_matched="rule_2_guest_denied",
                auth_path="",
                reason="Authentication required for this endpoint",
            )

        # ===== RULE 3: LOW level - any authenticated user =====
        if required_level == SecurityLevel.LOW:
            return AuthResult(
                granted=True,
                rule_matched="rule_3_any_authenticated",
                auth_path="authenticated_user",
                reason="LOW level allows any authenticated user",
            )

        # ===== RULE 4: Primary - Role Profile authorization =====
        for profile_name in user_profiles:
            if self.role_profile_grants_access(profile_name, required_level):
                return AuthResult(
                    granted=True,
                    rule_matched="rule_4_role_profile",
                    auth_path=f"role_profile:{profile_name}",
                    reason=f"Role profile {profile_name} grants {required_level.value} access",
                )

        # ===== RULE 5: Secondary - Individual role matches profile name =====
        # This supports backwards compatibility where role names match profile names
        for role in user_roles:
            allowed_levels = self.ROLE_PROFILE_SECURITY_MAPPING.get(role, [])
            if required_level in allowed_levels:
                return AuthResult(
                    granted=True,
                    rule_matched="rule_5_individual_role",
                    auth_path=f"individual_role:{role}",
                    reason=f"Individual role {role} grants {required_level.value} access",
                )

        # ===== RULE 6: System Manager exception for MEDIUM =====
        if Roles.SYSTEM_MANAGER in user_roles and required_level == SecurityLevel.MEDIUM:
            return AuthResult(
                granted=True,
                rule_matched="rule_6_system_manager",
                auth_path="system_manager_exception",
                reason="System Manager has implicit MEDIUM access",
            )

        # ===== RULE 7: DENY - No matching authorization rule =====
        return AuthResult(
            granted=False,
            rule_matched="rule_7_deny",
            auth_path="",
            reason=f"No authorization rule grants {required_level.value} access",
        )


# Singleton instance for convenience
_authorization_policy = None


def get_authorization_policy() -> AuthorizationPolicy:
    """Get singleton AuthorizationPolicy instance."""
    global _authorization_policy
    if _authorization_policy is None:
        _authorization_policy = AuthorizationPolicy()
    return _authorization_policy
