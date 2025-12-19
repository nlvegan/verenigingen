# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Configuration Service

Centralized service for accessing Ponto Settings with caching and validation.
Follows the pattern established by MollieConfigurationService.

Usage:
    from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
        get_ponto_config
    )

    config = get_ponto_config()
    client_id = config.get_active_client_id()
    mappings = config.get_enabled_account_mappings()

Note: Password fields (client_secret, webhook_secret) are NOT cached for security.
      Use Ponto Settings directly for password field access.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _


class PontoConfigurationService:
    """
    Centralized Ponto Settings access with caching and validation.

    Provides cached access to Ponto Settings with automatic validation
    and consistent error handling. Uses Frappe's cache system for thread-safe
    multi-worker support.
    """

    CACHE_KEY = "ponto_settings_cache"
    CACHE_TTL_SECONDS = 300  # 5 minutes

    # Roles allowed to access Ponto Settings (matches DocType permissions)
    ALLOWED_ROLES = {
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen Webhook User",
    }

    @classmethod
    def _load_settings_from_db(cls) -> Dict[str, Any]:
        """
        Load settings from database.

        Only caches non-sensitive configuration fields. Password fields
        must be retrieved separately for security.
        """
        settings = frappe.get_single("Ponto Settings")

        # Build list of bank account mappings (excluding sensitive data)
        bank_account_mappings = []
        for row in settings.bank_account_mappings:
            bank_account_mappings.append(
                {
                    "enabled": row.enabled,
                    "ponto_account_id": row.ponto_account_id,
                    "ponto_account_name": row.ponto_account_name,
                    "ponto_iban": row.ponto_iban,
                    "bank_account": row.bank_account,
                    "last_sync_time": row.last_sync_time,
                    "transactions_imported": row.transactions_imported,
                }
            )

        # Only cache non-Password fields (per security best practices)
        return {
            "sandbox_mode": getattr(settings, "sandbox_mode", True),
            "organization_id": getattr(settings, "organization_id", None),
            # Store which client_id is active, but not the secrets
            "sandbox_client_id": getattr(settings, "sandbox_client_id", None),
            "production_client_id": getattr(settings, "production_client_id", None),
            # Bank account mappings
            "bank_account_mappings": bank_account_mappings,
            # Webhook settings
            "enable_webhooks": getattr(settings, "enable_webhooks", False),
            "webhook_url": getattr(settings, "webhook_url", None),
            # Sync settings
            "auto_sync_enabled": getattr(settings, "auto_sync_enabled", False),
            "sync_interval_hours": getattr(settings, "sync_interval_hours", 6),
            "last_sync_time": getattr(settings, "last_sync_time", None),
        }

    @classmethod
    def clear_cache(cls):
        """
        Manually clear the settings cache.

        Called automatically when Ponto Settings are updated (via on_update hook).
        Can also be called manually when needed.
        """
        frappe.cache().delete_value(cls.CACHE_KEY)
        frappe.logger().info("Cleared Ponto Settings cache")

    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        """
        Get cached Ponto settings (thread-safe with security validation).

        Uses Frappe's cache system which is safe across multiple workers.
        Validates permissions and logs access for compliance.

        Returns:
            Dict with Ponto Settings fields (immutable copy)

        Raises:
            frappe.PermissionError: If user lacks read permission
        """
        # SECURITY: Validate user has permission to access configuration
        user_roles = set(frappe.get_roles())
        if not user_roles.intersection(cls.ALLOWED_ROLES):
            frappe.logger().warning(
                f"Unauthorized Ponto configuration access attempt by {frappe.session.user} "
                f"(roles: {user_roles})"
            )
            frappe.throw(
                _("Insufficient permissions to access Ponto configuration"),
                frappe.PermissionError,
            )

        cache = frappe.cache()
        settings = cache.get_value(cls.CACHE_KEY)

        if not settings:
            settings = cls._load_settings_from_db()
            cache.set_value(cls.CACHE_KEY, settings, expires_in_sec=cls.CACHE_TTL_SECONDS)

            frappe.logger().debug(
                f"Ponto configuration loaded by {frappe.session.user} "
                f"(cache miss, TTL: {cls.CACHE_TTL_SECONDS}s)"
            )
        else:
            frappe.logger().debug(f"Ponto configuration accessed by {frappe.session.user} (cache hit)")

        return settings.copy()

    @classmethod
    def is_sandbox_mode(cls) -> bool:
        """
        Check if Ponto is in sandbox mode.

        Returns:
            bool: True if sandbox mode enabled
        """
        settings = cls.get_settings()
        return bool(settings.get("sandbox_mode", True))

    @classmethod
    def get_active_client_id(cls) -> str:
        """
        Get the active OAuth2 client ID based on sandbox mode.

        Returns:
            str: Client ID for Ponto API authentication

        Raises:
            frappe.ValidationError: If client ID not configured
        """
        settings = cls.get_settings()
        is_sandbox = settings.get("sandbox_mode", True)

        if is_sandbox:
            client_id = settings.get("sandbox_client_id")
            env = "Sandbox"
        else:
            client_id = settings.get("production_client_id")
            env = "Production"

        if not client_id:
            frappe.throw(
                _(
                    f"Ponto {env} Client ID not configured. "
                    "Please configure OAuth2 credentials in Ponto Settings."
                ),
                title=_("Configuration Missing"),
            )

        return client_id

    @classmethod
    def get_active_client_secret(cls) -> str:
        """
        Get the active OAuth2 client secret based on sandbox mode.

        Note: Not cached for security. Fetches from database each time.

        Returns:
            str: Decrypted client secret for Ponto API authentication

        Raises:
            frappe.ValidationError: If client secret not configured
        """
        settings_doc = frappe.get_single("Ponto Settings")
        client_secret = settings_doc.get_active_client_secret()

        if not client_secret:
            env = "Sandbox" if settings_doc.sandbox_mode else "Production"
            frappe.throw(
                _(
                    f"Ponto {env} Client Secret not configured. "
                    "Please configure OAuth2 credentials in Ponto Settings."
                ),
                title=_("Configuration Missing"),
            )

        return client_secret

    @classmethod
    def get_enabled_account_mappings(cls) -> List[Dict[str, Any]]:
        """
        Get list of enabled bank account mappings.

        Returns:
            List of dicts with mapping details
        """
        settings = cls.get_settings()
        mappings = settings.get("bank_account_mappings", [])
        return [m for m in mappings if m.get("enabled")]

    @classmethod
    def get_all_account_mappings(cls) -> List[Dict[str, Any]]:
        """
        Get all bank account mappings (enabled and disabled).

        Returns:
            List of dicts with mapping details
        """
        settings = cls.get_settings()
        return settings.get("bank_account_mappings", [])

    @classmethod
    def get_mapping_for_ponto_account(cls, ponto_account_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the mapping for a specific Ponto account ID.

        Args:
            ponto_account_id: Ponto account UUID

        Returns:
            Mapping dict or None if not found
        """
        mappings = cls.get_all_account_mappings()
        for mapping in mappings:
            if mapping.get("ponto_account_id") == ponto_account_id:
                return mapping
        return None

    @classmethod
    def get_bank_account_for_ponto_account(cls, ponto_account_id: str) -> Optional[str]:
        """
        Get the ERPNext Bank Account for a Ponto account.

        Args:
            ponto_account_id: Ponto account UUID

        Returns:
            Bank Account name or None if not mapped/enabled
        """
        mapping = cls.get_mapping_for_ponto_account(ponto_account_id)
        if mapping and mapping.get("enabled") and mapping.get("bank_account"):
            return mapping.get("bank_account")
        return None

    @classmethod
    def get_first_enabled_ponto_account_id(cls) -> Optional[str]:
        """
        Get the first enabled Ponto account ID.

        Useful for operations that only support a single account.

        Returns:
            Ponto account UUID or None if no enabled mappings
        """
        mappings = cls.get_enabled_account_mappings()
        if mappings:
            return mappings[0].get("ponto_account_id")
        return None

    @classmethod
    def get_first_enabled_bank_account(cls) -> Optional[str]:
        """
        Get the Bank Account from the first enabled mapping.

        Returns:
            Bank Account name or None
        """
        mappings = cls.get_enabled_account_mappings()
        for mapping in mappings:
            if mapping.get("bank_account"):
                return mapping.get("bank_account")
        return None

    @classmethod
    def is_webhooks_enabled(cls) -> bool:
        """
        Check if webhooks are enabled.

        Returns:
            bool: True if webhooks enabled
        """
        settings = cls.get_settings()
        return bool(settings.get("enable_webhooks", False))

    @classmethod
    def is_auto_sync_enabled(cls) -> bool:
        """
        Check if automatic sync is enabled.

        Returns:
            bool: True if auto sync enabled
        """
        settings = cls.get_settings()
        return bool(settings.get("auto_sync_enabled", False))

    @classmethod
    def get_sync_interval_hours(cls) -> int:
        """
        Get sync interval in hours.

        Returns:
            int: Hours between syncs (default 6)
        """
        settings = cls.get_settings()
        return int(settings.get("sync_interval_hours", 6))

    @classmethod
    def get_default_company(cls) -> str:
        """
        Get default company for Ponto operations.

        Priority:
        1. Verenigingen Settings company
        2. Global Defaults company
        3. User default Company

        Returns:
            str: Company name

        Raises:
            frappe.ValidationError: If no company configured
        """
        company = None

        # Priority 1: Verenigingen Settings company
        try:
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            if hasattr(verenigingen_settings, "company") and verenigingen_settings.company:
                company = verenigingen_settings.company
        except Exception:
            pass

        # Priority 2: Global Defaults
        if not company:
            company = frappe.defaults.get_global_default("company")

        # Priority 3: User default
        if not company:
            company = frappe.defaults.get_user_default("Company")

        if not company:
            frappe.throw(
                _(
                    "No company configured. Please set company in Verenigingen Settings "
                    "or configure a default company."
                ),
                frappe.ValidationError,
            )

        return company

    @classmethod
    def validate_configuration(cls) -> Dict[str, Any]:
        """
        Validate Ponto configuration completeness.

        Returns:
            Dict with validation results:
            {
                "valid": bool,
                "missing_fields": list,
                "warnings": list
            }
        """
        settings = cls.get_settings()
        missing_fields = []
        warnings = []

        # Check credentials based on mode
        is_sandbox = settings.get("sandbox_mode", True)
        if is_sandbox:
            if not settings.get("sandbox_client_id"):
                missing_fields.append("sandbox_client_id")
        else:
            if not settings.get("production_client_id"):
                missing_fields.append("production_client_id")

        # Check for bank account mappings
        mappings = settings.get("bank_account_mappings", [])
        enabled_mappings = [m for m in mappings if m.get("enabled")]

        if not mappings:
            warnings.append("No Ponto accounts configured - use 'Fetch Accounts from Ponto' button")
        elif not enabled_mappings:
            warnings.append("No Ponto accounts enabled for sync")
        else:
            # Check if enabled mappings have bank accounts linked
            unmapped = [m for m in enabled_mappings if not m.get("bank_account")]
            if unmapped:
                warnings.append(
                    f"{len(unmapped)} enabled Ponto account(s) not linked to ERPNext Bank Account"
                )

        return {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "warnings": warnings,
        }

    @classmethod
    def update_last_sync_time(cls, ponto_account_id: str = None):
        """
        Update last sync time in settings.

        Args:
            ponto_account_id: Ponto account ID that was synced (updates mapping row)
        """
        from frappe.utils import now_datetime

        settings = frappe.get_single("Ponto Settings")
        settings.last_sync_time = now_datetime()

        # Also update the specific mapping row if account_id provided
        if ponto_account_id:
            for row in settings.bank_account_mappings:
                if row.ponto_account_id == ponto_account_id:
                    row.last_sync_time = now_datetime()
                    break

        settings.save(ignore_permissions=True)
        cls.clear_cache()

    @classmethod
    def increment_transactions_imported(cls, ponto_account_id: str, count: int):
        """
        Increment the transactions imported counter for an account.

        Args:
            ponto_account_id: Ponto account UUID
            count: Number of transactions to add
        """
        settings = frappe.get_single("Ponto Settings")
        for row in settings.bank_account_mappings:
            if row.ponto_account_id == ponto_account_id:
                row.transactions_imported = (row.transactions_imported or 0) + count
                break
        settings.save(ignore_permissions=True)
        cls.clear_cache()


def get_ponto_config() -> type:
    """
    Factory function to get PontoConfigurationService.

    Returns:
        PontoConfigurationService class (not instance, as all methods are classmethods)

    Example:
        config = get_ponto_config()
        client_id = config.get_active_client_id()
    """
    return PontoConfigurationService
