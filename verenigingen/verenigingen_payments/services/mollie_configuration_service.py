"""
Mollie Configuration Service

Centralized service for accessing Mollie Settings with caching and validation.
Eliminates duplicate settings access code across 28+ files.

Usage:
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        get_mollie_config
    )

    config = get_mollie_config()
    clearing_account = config.get_clearing_account()
    bank_account_gl = config.get_bank_account_gl()

Note: API keys are NOT cached for security reasons. Use Mollie Settings
      directly for API key access: frappe.get_single("Mollie Settings").get_active_api_key()
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _


class MollieConfigurationService:
    """
    Centralized Mollie Settings access with caching and validation.

    Provides cached access to Mollie Settings with automatic validation
    and consistent error handling. Uses Frappe's cache system for thread-safe
    multi-worker support.
    """

    CACHE_KEY = "mollie_settings_cache"
    CACHE_TTL_SECONDS = 300  # 5 minutes

    @classmethod
    def _load_settings_from_db(cls) -> Dict[str, Any]:
        """
        Load settings from database.

        Only caches non-sensitive configuration fields. Password fields
        (API keys) must be retrieved separately for security.
        """
        settings = frappe.get_single("Mollie Settings")

        # Only cache non-Password fields (per security best practices)
        return {
            "mollie_clearing_account": getattr(settings, "mollie_clearing_account", None),
            "mollie_bank_account": getattr(settings, "mollie_bank_account", None),
            "payment_processing_fees_account": getattr(settings, "payment_processing_fees_account", None),
            "test_mode": getattr(settings, "test_mode", True),
            "enable_subscriptions": getattr(settings, "enable_subscriptions", False),
            "enable_backend_api": getattr(settings, "enable_backend_api", False),
            "dues_payment_creation_mode": getattr(settings, "dues_payment_creation_mode", "Bank Transaction"),
        }

    @classmethod
    def clear_cache(cls):
        """
        Manually clear the settings cache.

        Called automatically when Mollie Settings are updated (via on_update hook).
        Can also be called manually when needed.
        """
        frappe.cache().delete_value(cls.CACHE_KEY)
        frappe.logger().info("Cleared Mollie Settings cache")

    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        """
        Get cached Mollie settings (thread-safe).

        Uses Frappe's cache system which is safe across multiple workers.

        Returns:
            Dict with Mollie Settings fields (immutable copy)

        Note: Returns a copy to prevent cache mutation. If you only need
              a single field, use specific getters (get_clearing_account(), etc.)
              for better performance.

        Example:
            settings = MollieConfigurationService.get_settings()
            test_mode = settings.get("test_mode")
        """
        cache = frappe.cache()
        settings = cache.get_value(cls.CACHE_KEY)

        if not settings:
            settings = cls._load_settings_from_db()
            cache.set_value(cls.CACHE_KEY, settings, expires_in_sec=cls.CACHE_TTL_SECONDS)
            frappe.logger().debug(f"Loaded Mollie settings into cache (TTL: {cls.CACHE_TTL_SECONDS}s)")

        return settings.copy()

    @classmethod
    def get_clearing_account(cls) -> str:
        """
        Get Mollie clearing account (GL Account) with validation.

        The clearing account is where Mollie payments are deposited before
        settlement to the physical bank account.

        Returns:
            GL Account name (e.g., "10460 - Mollie - NVV")

        Raises:
            frappe.ValidationError: If clearing account not configured

        Example:
            clearing_account = get_mollie_config().get_clearing_account()
        """
        settings = cls.get_settings()
        account = settings.get("mollie_clearing_account")

        if not account:
            frappe.throw(
                _(
                    "Mollie Clearing Account not configured in Mollie Settings. "
                    "Please configure it to track payments awaiting settlement."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def get_bank_account_gl(cls) -> str:
        """
        Get Mollie physical bank account (GL Account) with validation.

        The bank account is where settlement payouts from Mollie are deposited
        (typically Triodos account).

        Returns:
            GL Account name (e.g., "10440 - Triodos - NVV")

        Raises:
            frappe.ValidationError: If bank account not configured

        Example:
            bank_account = get_mollie_config().get_bank_account_gl()
        """
        settings = cls.get_settings()
        account = settings.get("mollie_bank_account")

        if not account:
            frappe.throw(
                _(
                    "Mollie Bank Account not configured in Mollie Settings. "
                    "Please configure it to specify where settlement deposits are received."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def get_fees_account_optional(cls) -> Optional[str]:
        """
        Get payment processing fees account (GL Account) without validation.

        Returns:
            GL Account name if configured, None otherwise

        Example:
            fees_account = get_mollie_config().get_fees_account_optional()
            if fees_account:
                # Create fee journal entry
        """
        settings = cls.get_settings()
        return settings.get("payment_processing_fees_account")

    @classmethod
    def get_fees_account(cls) -> str:
        """
        Get payment processing fees account (GL Account) with validation.

        Returns:
            GL Account name

        Raises:
            frappe.ValidationError: If fees account not configured

        Example:
            # Use this when fees account is required
            fees_account = get_mollie_config().get_fees_account()
        """
        settings = cls.get_settings()
        account = settings.get("payment_processing_fees_account")

        if not account:
            frappe.throw(
                _(
                    "Payment Processing Fees Account not configured in Mollie Settings. "
                    "Please configure it to enable fee accounting."
                ),
                title=_("Configuration Missing"),
            )

        return account

    @classmethod
    def is_test_mode(cls) -> bool:
        """
        Check if Mollie is in test mode.

        Returns:
            True if test mode enabled, False for live mode

        Example:
            if get_mollie_config().is_test_mode():
                # Using test API
        """
        settings = cls.get_settings()
        return bool(settings.get("test_mode", True))

    @classmethod
    def is_subscriptions_enabled(cls) -> bool:
        """
        Check if Mollie subscriptions are enabled.

        Returns:
            True if subscriptions enabled, False otherwise

        Example:
            if get_mollie_config().is_subscriptions_enabled():
                # Process subscription
        """
        settings = cls.get_settings()
        return bool(settings.get("enable_subscriptions", False))

    @classmethod
    def get_dues_payment_creation_mode(cls) -> str:
        """
        Get dues payment creation mode (Bank Transaction or Payment Entry).

        Returns:
            "Bank Transaction" (default) or "Payment Entry" (legacy mode)

        Example:
            mode = get_mollie_config().get_dues_payment_creation_mode()
            if mode == "Payment Entry":
                # Create Payment Entry directly (legacy)
            else:
                # Create Bank Transaction for reconciliation (default)
        """
        settings = cls.get_settings()
        return settings.get("dues_payment_creation_mode", "Bank Transaction")

    @classmethod
    def validate_configuration(cls) -> Dict[str, Any]:
        """
        Validate Mollie configuration completeness.

        Returns:
            Dict with validation results:
            {
                "valid": bool,
                "missing_fields": list,
                "warnings": list
            }

        Note: API key validation requires separate check via
              frappe.get_single("Mollie Settings").get_active_api_key()
              as password fields are not cached.

        Example:
            validation = get_mollie_config().validate_configuration()
            if not validation["valid"]:
                frappe.msgprint(f"Missing fields: {validation['missing_fields']}")
        """
        settings = cls.get_settings()
        missing_fields = []
        warnings = []

        # Check required fields (excluding API key - requires password field access)
        if not settings.get("mollie_clearing_account"):
            missing_fields.append("mollie_clearing_account")

        if not settings.get("mollie_bank_account"):
            missing_fields.append("mollie_bank_account")

        # Check optional but recommended fields
        if not settings.get("payment_processing_fees_account"):
            warnings.append("payment_processing_fees_account not configured - fee accounting disabled")

        return {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "warnings": warnings,
        }


def get_mollie_config() -> MollieConfigurationService:
    """
    Factory function to get MollieConfigurationService singleton.

    Returns:
        MollieConfigurationService instance

    Example:
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config
        )

        config = get_mollie_config()
        clearing_account = config.get_clearing_account()
    """
    return MollieConfigurationService
