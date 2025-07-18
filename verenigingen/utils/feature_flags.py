"""
Feature Flags for Verenigingen
Controls which features are enabled/disabled during migration
"""

import frappe
from frappe import _


def is_subscription_system_enabled():
    """
    Check if the legacy subscription system is enabled

    The subscription system has been replaced with the dues schedule system.
    Use the Membership Dues Schedule system instead.

    Returns:
        bool: True if subscription system should be active, False otherwise
    """
    # Check site config first
    if hasattr(frappe.conf, "enable_subscription_system"):
        return frappe.conf.enable_subscription_system

    # Check Verenigingen Settings
    try:
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "enable_subscription_system"):
            return settings.enable_subscription_system
    except:
        pass

    # Default to disabled (subscription system is deprecated)
    return False


def is_dues_schedule_system_enabled():
    """
    Check if the new dues schedule system is enabled

    Returns:
        bool: True if dues schedule system should be active, False otherwise
    """
    # Dues schedule is always enabled (it's the new default)
    return True


def get_payment_system_status():
    """
    Get the status of both payment systems

    Returns:
        dict: Status of subscription and dues schedule systems
    """
    return {
        "subscription_enabled": is_subscription_system_enabled(),
        "dues_schedule_enabled": is_dues_schedule_system_enabled(),
        "migration_mode": is_subscription_system_enabled() and is_dues_schedule_system_enabled(),
        "recommended_system": "dues_schedule",
        "migration_status": "subscription_system_deprecated",
    }


def check_feature_availability(feature_name):
    """
    Check if a specific feature is available

    Args:
        feature_name: Name of the feature to check

    Returns:
        bool: True if feature is available, False otherwise
    """
    feature_map = {
        "subscription_creation": is_subscription_system_enabled(),
        "subscription_invoicing": is_subscription_system_enabled(),
        "subscription_sync": is_subscription_system_enabled(),
        "dues_schedule_creation": True,
        "dues_schedule_invoicing": True,
        "member_portal": True,
        "admin_dashboard": True,
    }

    return feature_map.get(feature_name, False)


def get_deprecation_message(feature_name):
    """
    Get deprecation message for a feature

    Args:
        feature_name: Name of the deprecated feature

    Returns:
        str: Deprecation message
    """
    messages = {
        "subscription_creation": _(
            "Subscription creation is deprecated. Please use Membership Dues Schedule instead."
        ),
        "subscription_sync": _(
            "Subscription sync is deprecated. Payment data is now managed through Dues Schedules."
        ),
        "subscription_plan": _(
            "Subscription plans are deprecated. Use Membership Type billing settings instead."
        ),
        "subscription_invoicing": _(
            "Subscription-based invoicing is deprecated. Invoices are now generated from Dues Schedules."
        ),
    }

    return messages.get(
        feature_name, _("This feature has been deprecated. Please use the new Dues Schedule system.")
    )


def log_deprecated_usage(function_name, context=None):
    """
    Log usage of deprecated functionality

    Args:
        function_name: Name of the deprecated function
        context: Additional context information
    """
    if is_subscription_system_enabled():
        # Only log if subscription system is enabled (to avoid spam)
        return

    message = f"Deprecated function called: {function_name}"
    if context:
        message += f" | Context: {context}"

    frappe.log_error(message, "Deprecated Subscription Usage")


# Decorator for deprecated functions
def deprecated_subscription_function(func):
    """
    Decorator to mark functions as deprecated subscription functionality
    """

    def wrapper(*args, **kwargs):
        if not is_subscription_system_enabled():
            function_name = func.__name__
            log_deprecated_usage(function_name)
            frappe.msgprint(get_deprecation_message("subscription_creation"), indicator="orange", alert=True)
            return None
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = f"Updated to use dues schedule system: {func.__doc__ or ''}"
    return wrapper
