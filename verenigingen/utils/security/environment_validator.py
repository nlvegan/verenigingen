"""
Environment Validator for API Security Framework

Provides environment-based access control for API endpoints.

DEPENDENCY RULES:
- MAY import from types.py
- Uses frappe.conf for environment detection (I/O layer)
- MUST NOT import from higher-level modules (api_security_framework, etc.)
"""

import frappe
from frappe import _

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.types import EnvironmentLevel, SecurityProfile


class EnvironmentValidator:
    """
    Validate deployment environment for API access control.

    This class determines the current deployment environment and validates
    whether API access is permitted in that environment.

    INVARIANTS:
    - Defaults to PRODUCTION for safety (most restrictive)
    - Environment detection is deterministic for same configuration
    - All environment values are from EnvironmentLevel enum
    """

    def get_current_environment(self) -> EnvironmentLevel:
        """
        Detect the current deployment environment.

        Detection priority:
        1. Frappe developer_mode -> DEVELOPMENT
        2. deployment_environment config -> as configured
        3. environment config -> as configured
        4. Default -> PRODUCTION (safest)

        Returns:
            EnvironmentLevel: Current environment (DEVELOPMENT, STAGING, or PRODUCTION)
        """
        # Check Frappe developer mode first
        if frappe.conf.get("developer_mode", False):
            return EnvironmentLevel.DEVELOPMENT

        # Check custom environment configuration
        env = frappe.conf.get("deployment_environment")
        if env:
            try:
                return EnvironmentLevel(env.lower())
            except ValueError:
                pass  # Invalid environment, fall through to default

        # Check site-specific environment indicator
        site_env = frappe.conf.get("environment")
        if site_env:
            try:
                return EnvironmentLevel(site_env.lower())
            except ValueError:
                pass  # Invalid environment, fall through to default

        # Default to production for safety - restricts access by default
        return EnvironmentLevel.PRODUCTION

    def validate_access(
        self,
        profile: SecurityProfile,
        current_env: EnvironmentLevel = None,
    ) -> bool:
        """
        Validate that the current environment is allowed for this security profile.

        Args:
            profile: Security profile containing environment restrictions
            current_env: Current environment (detected if not provided)

        Returns:
            bool: True if access is allowed in current environment

        Raises:
            VPermissionError: If current environment is not allowed
        """
        if current_env is None:
            current_env = self.get_current_environment()

        if current_env not in profile.allowed_environments:
            allowed_envs = [env.value for env in profile.allowed_environments]
            raise VPermissionError(
                _(
                    f"Function not available in {current_env.value} environment. "
                    f"Allowed environments: {', '.join(allowed_envs)}"
                )
            )

        return True


# Singleton instance for convenience
_environment_validator = None


def get_environment_validator() -> EnvironmentValidator:
    """Get singleton EnvironmentValidator instance."""
    global _environment_validator
    if _environment_validator is None:
        _environment_validator = EnvironmentValidator()
    return _environment_validator
