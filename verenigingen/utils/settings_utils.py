#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Settings Utilities for Verenigingen
====================================

Centralized settings retrieval with caching and error handling.
Eliminates scattered frappe.get_single() calls throughout the codebase.

Key Features:
- Cached settings retrieval for better performance
- Consistent error handling across all settings
- Type hints and comprehensive documentation
- Fallback mechanisms for missing settings

Usage:
    from verenigingen.utils.settings_utils import (
        get_verenigingen_settings,
        get_payments_settings,
        get_e_boekhouden_settings,
        get_mollie_settings
    )

    settings = get_verenigingen_settings()
    if settings:
        default_company = settings.get("company")

    # For payment/SEPA/financial settings
    pay_settings = get_payments_settings()
    if pay_settings:
        iban = pay_settings.get("company_iban")
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _


def get_verenigingen_settings() -> Optional[Dict[str, Any]]:
    """
    Get Verenigingen Settings with caching and error handling.

    CRITICAL: This function NEVER returns None. If settings don't exist,
    they are created automatically to ensure system stability.

    Returns:
        Dict with settings (guaranteed to exist)

    Error Handling:
        Creates settings if missing, logs errors but continues.
        Only returns None in catastrophic database failures.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        # Try to get existing settings
        settings = frappe.get_single("Verenigingen Settings")
        if settings:
            return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving Verenigingen Settings: {str(e)}")

    # Settings don't exist or failed to load - create them
    try:
        # Use direct import to avoid circular imports
        import importlib

        setup_module = importlib.import_module("verenigingen.setup")
        create_function = getattr(setup_module, "create_default_verenigingen_settings")

        frappe.logger().info("Creating default Verenigingen Settings")
        settings = create_function()

        if settings:
            # Clear cache and get fresh copy
            frappe.cache().delete_key("single:Verenigingen Settings")
            return frappe.get_doc("Verenigingen Settings").as_dict()

    except Exception as creation_error:
        frappe.logger().error(f"Failed to create Verenigingen Settings: {str(creation_error)}")

    # Last resort - return None only if everything failed
    frappe.logger().error("CRITICAL: Unable to load or create Verenigingen Settings")
    return None


def get_payments_settings() -> Optional[Dict[str, Any]]:
    """
    Get Verenigingen Payments Settings with caching and error handling.

    This DocType contains:
    - Financial settings (company IBAN, BIC, bank accounts)
    - SEPA Direct Debit configuration (creditor ID, mandate naming)
    - Batch processing settings
    - Invoicing and communications settings

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Creates settings if missing, logs errors but continues.
        Only returns None in catastrophic database failures.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        # Try to get existing settings
        settings = frappe.get_single("Verenigingen Payments Settings")
        if settings:
            return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving Verenigingen Payments Settings: {str(e)}")

    # Settings don't exist - create them with minimal defaults
    try:
        frappe.logger().info("Creating default Verenigingen Payments Settings")
        settings_doc = frappe.get_doc({
            "doctype": "Verenigingen Payments Settings",
        })
        settings_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Clear cache and get fresh copy
        frappe.cache().delete_key("single:Verenigingen Payments Settings")
        return frappe.get_doc("Verenigingen Payments Settings").as_dict()

    except Exception as creation_error:
        frappe.logger().error(f"Failed to create Verenigingen Payments Settings: {str(creation_error)}")

    # Last resort - return None only if everything failed
    frappe.logger().error("CRITICAL: Unable to load or create Verenigingen Payments Settings")
    return None


def get_e_boekhouden_settings() -> Optional[Dict[str, Any]]:
    """
    Get E-Boekhouden Settings with caching and error handling.

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Returns None on any database or access errors.
        Logs errors for debugging purposes.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving E-Boekhouden Settings: {str(e)}")
        return None


def get_mollie_settings(gateway_name: str = "Default") -> Optional[Dict[str, Any]]:
    """
    Get Mollie Settings for specified gateway with caching.

    Args:
        gateway_name: Name of the gateway settings to retrieve (default: "Default")

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Returns None if gateway not found or on database errors.
        Logs errors for debugging purposes.

    Performance:
        Uses frappe.get_cached_doc() for better performance.
    """
    try:
        if not frappe.db.exists("Mollie Settings", gateway_name):
            frappe.logger().warning(f"Mollie Settings '{gateway_name}' does not exist")
            return None

        settings = frappe.get_doc("Mollie Settings", gateway_name)
        return settings.as_dict()
    except Exception as e:
        frappe.logger().error(f"Error retrieving Mollie Settings '{gateway_name}': {str(e)}")
        return None


def get_system_settings() -> Optional[Dict[str, Any]]:
    """
    Get System Settings with caching and error handling.

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Returns None on any database or access errors.
        Logs errors for debugging purposes.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        settings = frappe.get_single("System Settings")
        return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving System Settings: {str(e)}")
        return None


def get_domain_settings() -> Optional[Dict[str, Any]]:
    """
    Get Domain Settings with caching and error handling.

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Returns None on any database or access errors.
        Logs errors for debugging purposes.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        settings = frappe.get_single("Domain Settings")
        return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving Domain Settings: {str(e)}")
        return None


def get_brand_settings() -> Optional[Dict[str, Any]]:
    """
    Get Brand Settings with caching and error handling.

    Returns:
        Dict with settings if found, None if error occurs

    Error Handling:
        Returns None on any database or access errors.
        Logs errors for debugging purposes.

    Performance:
        Uses frappe.get_single() for settings retrieval.
    """
    try:
        settings = frappe.get_single("Brand Settings")
        return settings
    except Exception as e:
        frappe.logger().error(f"Error retrieving Brand Settings: {str(e)}")
        return None


# Convenience functions for commonly accessed setting values


def get_default_company() -> Optional[str]:
    """
    Get default company from Verenigingen Settings.

    Returns:
        Company name if found, None otherwise
    """
    settings = get_verenigingen_settings()
    if settings:
        return settings.get("company")
    return None


def get_support_email() -> Optional[str]:
    """
    Get support email from System Settings.

    Returns:
        Support email if found, None otherwise
    """
    settings = get_system_settings()
    if settings:
        return settings.get("email_footer_address")
    return None


def get_e_boekhouden_api_credentials() -> Optional[Dict[str, str]]:
    """
    Get E-Boekhouden API credentials safely.

    Returns:
        Dict with 'username' and 'security_code' if found, None otherwise

    Security:
        Uses get_password() method for secure credential retrieval
    """
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        if not settings:
            return None

        # Get the actual document for secure password retrieval
        settings_doc = frappe.get_doc("E-Boekhouden Settings")

        return {
            "username": settings.get("username"),
            "security_code": (
                settings_doc.get_password("security_code")
                if hasattr(settings_doc.__class__, "get_password")
                else None
            ),
        }
    except Exception as e:
        frappe.logger().error(f"Error retrieving E-Boekhouden API credentials: {str(e)}")
        return None


def get_mollie_api_key(gateway_name: str = "Default") -> Optional[str]:
    """
    Get Mollie API key securely.

    Args:
        gateway_name: Name of the gateway settings (default: "Default")

    Returns:
        API key if found, None otherwise

    Security:
        Uses get_password() method for secure credential retrieval
    """
    try:
        if not frappe.db.exists("Mollie Settings", gateway_name):
            return None

        settings = frappe.get_doc("Mollie Settings", gateway_name)
        if hasattr(settings.__class__, "get_password"):
            return settings.get_password("api_key")
        return settings.get("api_key")
    except Exception as e:
        frappe.logger().error(f"Error retrieving Mollie API key for '{gateway_name}': {str(e)}")
        return None


def is_e_boekhouden_enabled() -> bool:
    """
    Check if E-Boekhouden integration is enabled.

    Returns:
        True if enabled, False otherwise
    """
    settings = get_e_boekhouden_settings()
    if settings:
        return bool(settings.get("enable_e_boekhouden"))
    return False


def is_mollie_enabled(gateway_name: str = "Default") -> bool:
    """
    Check if Mollie integration is enabled for specified gateway.

    Args:
        gateway_name: Name of the gateway settings (default: "Default")

    Returns:
        True if enabled and configured, False otherwise
    """
    settings = get_mollie_settings(gateway_name)
    if settings:
        return bool(settings.get("enabled")) and bool(settings.get("api_key"))
    return False


# Cache invalidation utilities


def clear_settings_cache():
    """
    Clear all settings cache for immediate refresh.

    Use this after making changes to any settings DocTypes.
    """
    try:
        # Clear specific settings caches
        cache_keys = [
            "Verenigingen Settings",
            "Verenigingen Payments Settings",
            "E-Boekhouden Settings",
            "System Settings",
            "Domain Settings",
            "Brand Settings",
        ]

        for key in cache_keys:
            try:
                frappe.cache().delete_key(f"single:{key}")
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache delete failed for '{key}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for '{key}': {e}")

        frappe.logger().info("Settings cache cleared successfully")

    except Exception as e:
        frappe.logger().error(f"Error clearing settings cache: {str(e)}")


def refresh_settings_cache():
    """
    Refresh all settings cache by clearing and reloading.

    Use this to ensure latest settings are loaded.
    """
    clear_settings_cache()

    # Preload commonly used settings
    get_verenigingen_settings()
    get_payments_settings()
    get_e_boekhouden_settings()
    get_system_settings()

    frappe.logger().info("Settings cache refreshed successfully")
