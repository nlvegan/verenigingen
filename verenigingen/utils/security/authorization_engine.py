"""
Authorization Engine for API Security Framework

Provides the I/O layer for authorization: fetches user data from Frappe,
manages caching, and delegates decisions to AuthorizationPolicy.

DEPENDENCY RULES:
- MAY import from types.py, authorization_policy.py
- MAY use Frappe for DB/cache access
- MUST NOT import from api_security_framework.py (to avoid circular imports)
"""

from typing import List, Optional

import frappe

from verenigingen.utils.security.authorization_policy import (
    AuthorizationPolicy,
    get_authorization_policy,
)
from verenigingen.utils.security.types import AuthResult, SecurityLevel


class AuthorizationEngine:
    """
    I/O layer for authorization. Fetches roles/profiles, delegates to policy.

    INVARIANTS:
    - All authorization decisions go through AuthorizationPolicy.decide()
    - User role profiles are cached with versioned keys for efficient invalidation
    - Cache is invalidated on role changes via invalidate_user_cache()

    MULTI-WORKER SAFETY:
    - Cache version is stored in Redis (not process memory) so all workers
      share the same version. This ensures cache invalidation works correctly
      in multi-worker deployments (e.g., gunicorn with multiple workers).
    """

    # Redis key for shared cache version (not process-local)
    CACHE_VERSION_KEY = "auth_engine:role_profile_cache_version"

    def __init__(self, policy: AuthorizationPolicy = None):
        """
        Initialize authorization engine.

        Args:
            policy: Authorization policy to use (injectable for testing)
        """
        self.policy = policy or get_authorization_policy()

    def authorize(self, user: str, level: SecurityLevel) -> AuthResult:
        """
        Authorize a user for a given security level.

        This is the main entry point for authorization checks.

        Args:
            user: User to authorize (defaults to current session user if None)
            level: Required security level

        Returns:
            AuthResult with authorization decision
        """
        if not user:
            user = frappe.session.user

        # Fetch user data (I/O layer)
        user_profiles = self.get_user_role_profiles(user)
        user_roles = frappe.get_roles(user)
        is_authenticated = user != "Guest"

        # Delegate to pure policy for decision
        return self.policy.decide(
            required_level=level,
            user_profiles=user_profiles,
            user_roles=user_roles,
            is_authenticated=is_authenticated,
        )

    def get_user_role_profiles(self, user: str = None) -> List[str]:
        """
        Get user's role profiles from Frappe's Role Profile system with caching.

        Uses versioned cache keys to avoid O(N) Redis KEYS on bulk invalidation.

        Args:
            user: User to get profiles for (defaults to current session user)

        Returns:
            List of role profile names assigned to the user
        """
        if not user:
            user = frappe.session.user

        # Use versioned cache key
        cache_key = self._get_versioned_cache_key(user)
        cached_profiles = frappe.cache.get_value(cache_key)

        if cached_profiles is not None:
            return cached_profiles

        # SECURITY FIX: Get user's directly assigned role profiles only
        try:
            role_profiles = []

            # Gather directly-assigned role profiles. Frappe v16 stores assignments in the
            # role_profiles child table (Table MultiSelect) and deprecates/clears the single
            # role_profile_name Link. Reading only role_profile_name would return nothing on
            # v16 and silently deny all role-profile-based security access, so read both.
            candidate_profiles = []
            user_role_profile = frappe.db.get_value("User", user, "role_profile_name")
            if user_role_profile:
                candidate_profiles.append(user_role_profile)
            # Read the role_profiles child table via raw SQL rather than
            # frappe.get_all("User Role Profile", ...). get_all loads the child
            # doctype's controller/meta, which can raise
            # ``KeyError: ('DocType', 'User Role Profile')`` against a corrupted
            # in-process doctype cache once a neighbouring test poisons it mid-run
            # (observed worker-wide in CI). That exception was swallowed below and
            # the user silently lost ALL role-profile-based access -- a fail-closed
            # security regression. Raw SQL on the child table needs no meta/controller
            # load, so it is immune to that cache pollution.
            candidate_profiles.extend(
                row[0]
                for row in frappe.db.sql(
                    """
                    SELECT role_profile
                    FROM `tabUser Role Profile`
                    WHERE parent = %s AND parenttype = 'User'
                    """,
                    (user,),
                )
            )

            seen = set()
            for profile in candidate_profiles:
                if not profile or profile in seen:
                    continue
                seen.add(profile)
                # Verify the role profile actually exists
                if frappe.db.exists("Role Profile", profile):
                    role_profiles.append(profile)
                    frappe.logger("verenigingen.api_security").debug(
                        f"Found direct role profile assignment: {profile}"
                    )
                else:
                    frappe.logger("verenigingen.api_security").warning(
                        f"User {user} has invalid role profile assignment: {profile}"
                    )

            # Note: We intentionally do NOT query role intersections as that would
            # give elevated access to users who happen to have overlapping roles.
            # Only direct role profile assignments grant security level access.

            # Cache the result (empty list means user has no role profiles)
            # TTL: 5 minutes (300s) - short cache for security-sensitive data
            # Shorter TTL ensures role profile changes are picked up quickly
            # vs. long TTL (24h) which would delay security changes
            frappe.cache.set_value(cache_key, role_profiles, expires_in_sec=300)

            frappe.logger("verenigingen.api_security").debug(
                f"User {user} role profiles (cached): {role_profiles}"
            )

            return role_profiles

        except Exception as e:
            frappe.logger("verenigingen.api_security").error(
                f"Error getting role profiles for {user}: {str(e)}"
            )
            return []

    def _get_cache_version(self) -> int:
        """
        Get current cache version from Redis (shared across all workers).

        If no version exists in Redis, initializes to 1.
        """
        version = frappe.cache.get_value(self.CACHE_VERSION_KEY)
        if version is None:
            # Initialize version in Redis
            frappe.cache.set_value(self.CACHE_VERSION_KEY, 1)
            return 1
        return int(version)

    def _get_versioned_cache_key(self, user: str) -> str:
        """
        Get versioned cache key for user role profiles.

        Using versioned keys allows O(1) bulk invalidation by incrementing
        the version number, rather than scanning for all user keys.

        The version is stored in Redis so all workers share the same version.
        """
        version = self._get_cache_version()
        return f"user_role_profiles_v{version}:{user}"

    def invalidate_user_cache(self, user: str = None):
        """
        Invalidate cached role profiles for a user or all users.

        Args:
            user: Specific user to invalidate, or None to invalidate all
        """
        if user:
            # Invalidate specific user
            cache_key = self._get_versioned_cache_key(user)
            frappe.cache.delete_value(cache_key)
            frappe.logger("verenigingen.api_security").debug(
                f"Invalidated role profile cache for user: {user}"
            )
        else:
            # Increment version in Redis to invalidate all cached profiles
            # This is O(1) rather than O(N) key deletion
            # All workers will see the new version since it's stored in Redis
            current_version = self._get_cache_version()
            new_version = current_version + 1
            frappe.cache.set_value(self.CACHE_VERSION_KEY, new_version)
            frappe.logger("verenigingen.api_security").info(
                f"Incremented cache version to {new_version}, "
                "all role profile caches invalidated (shared across all workers)"
            )

    @classmethod
    def get_cache_version(cls) -> int:
        """Get current cache version from Redis (useful for debugging)."""
        version = frappe.cache.get_value(cls.CACHE_VERSION_KEY)
        return int(version) if version is not None else 1


# Singleton instance for convenience
_authorization_engine: Optional[AuthorizationEngine] = None


def get_authorization_engine() -> AuthorizationEngine:
    """Get singleton AuthorizationEngine instance."""
    global _authorization_engine
    if _authorization_engine is None:
        _authorization_engine = AuthorizationEngine()
    return _authorization_engine


def invalidate_user_role_cache(user: str = None):
    """
    Convenience function to invalidate user role cache.

    Can be called from hooks or other modules without importing the class.

    Args:
        user: Specific user to invalidate, or None to invalidate all
    """
    get_authorization_engine().invalidate_user_cache(user)
