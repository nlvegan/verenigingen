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
    """

    # Global cache version - increment to invalidate all cached profiles
    _cache_version = 1

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

            # Method 1: Get role profile directly assigned to user in User DocType
            user_role_profile = frappe.db.get_value("User", user, "role_profile_name")
            if user_role_profile:
                # Verify the role profile actually exists
                if frappe.db.exists("Role Profile", user_role_profile):
                    role_profiles.append(user_role_profile)
                    frappe.logger("verenigingen.api_security").debug(
                        f"Found direct role profile assignment: {user_role_profile}"
                    )
                else:
                    frappe.logger("verenigingen.api_security").warning(
                        f"User {user} has invalid role profile assignment: {user_role_profile}"
                    )

            # Note: We intentionally do NOT query role intersections as that would
            # give elevated access to users who happen to have overlapping roles.
            # Only direct role profile assignments grant security level access.

            # Cache the result (empty list means user has no role profiles)
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

    def _get_versioned_cache_key(self, user: str) -> str:
        """
        Get versioned cache key for user role profiles.

        Using versioned keys allows O(1) bulk invalidation by incrementing
        the version number, rather than scanning for all user keys.
        """
        return f"user_role_profiles_v{self._cache_version}:{user}"

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
            # Increment version to invalidate all cached profiles
            # This is O(1) rather than O(N) key deletion
            AuthorizationEngine._cache_version += 1
            frappe.logger("verenigingen.api_security").info(
                f"Incremented cache version to {AuthorizationEngine._cache_version}, "
                "all role profile caches invalidated"
            )

    @classmethod
    def get_cache_version(cls) -> int:
        """Get current cache version (useful for debugging)."""
        return cls._cache_version


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
