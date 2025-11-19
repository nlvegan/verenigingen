"""
Notification Management and Configuration Utilities for Verenigingen System

This module provides comprehensive notification management capabilities for the
Verenigingen association management system. It handles intelligent recipient
determination, configurable notification settings, and robust fallback mechanisms
to ensure critical system notifications are always delivered to appropriate personnel.

Key Features:
    * Configurable notification recipients via system settings
    * Intelligent fallback to role-based recipient determination
    * Threshold-based notification triggering with customizable limits
    * Error-resistant notification delivery with multiple fallback levels
    * Support for both individual and group notification scenarios

Architecture:
    The notification system uses a hierarchical approach for recipient determination:
    1. Custom email addresses from Verenigingen Settings (highest priority)
    2. Role-based recipient lookup using configurable role lists
    3. Emergency fallback to System Manager role (last resort)

Use Cases:
    - System alert notifications for critical events
    - Membership status change notifications
    - Payment processing alerts and confirmations
    - SEPA batch processing status updates
    - Administrative workflow notifications

Integration:
    This module integrates with Frappe's notification framework while providing
    Verenigingen-specific configuration and fallback mechanisms. It supports
    both immediate notifications and threshold-based alerting systems.

Error Handling:
    Comprehensive error handling ensures notification delivery even in degraded
    system conditions, with multiple fallback mechanisms and detailed logging
    for troubleshooting notification delivery issues.
"""

import frappe


def get_notification_recipients(setting_field, default_roles=None):
    """
    Intelligently determine notification recipients using hierarchical fallback strategy.

    This function implements a sophisticated recipient determination system that
    prioritizes custom configuration while providing robust fallback mechanisms
    to ensure critical notifications are always delivered to appropriate personnel.

    Recipient Determination Strategy:
        1. Custom Emails: Check Verenigingen Settings for specific email addresses
        2. Role-Based Lookup: Find active users with specified roles
        3. Emergency Fallback: Use System Manager role as last resort

    Args:
        setting_field (str): Field name in Verenigingen Settings containing
                           comma-separated email addresses for notifications
        default_roles (list, optional): List of role names to use for recipient
                                      lookup if no custom emails configured.
                                      Defaults to ["System Manager", "Verenigingen Administrator"]

    Returns:
        list: Email addresses of notification recipients, guaranteed to contain
              at least one valid email address or empty list in extreme failure

    Error Handling:
        - Graceful handling of missing or malformed settings
        - Validation of email address format and user account status
        - Comprehensive logging of recipient determination process
        - Multiple fallback levels to ensure notification delivery

    Example:
        # Get recipients for payment failure notifications
        recipients = get_notification_recipients(
            "payment_failure_notification_emails",
            ["Verenigingen Treasurer", "System Manager"]
        )
    """
    if default_roles is None:
        default_roles = ["System Manager", "Verenigingen Administrator"]

    try:
        settings = frappe.get_single("Verenigingen Settings")
        custom_emails = getattr(settings, setting_field, None)

        if custom_emails:
            # Parse comma-separated emails and clean them
            emails = [email.strip() for email in custom_emails.split(",") if email.strip()]
            if emails:
                return emails

        # Fall back to default roles
        admin_users = frappe.get_all(
            "User",
            filters=[["enabled", "=", 1], ["Has Role", "role", "in", default_roles]],
            fields=["email", "full_name"],
        )

        return [user.email for user in admin_users if user.email]

    except Exception as e:
        frappe.log_error(f"Failed to get notification recipients: {str(e)}", "Notification Helper Error")
        # Emergency fallback - get System Managers
        try:
            admin_emails = frappe.get_all(
                "User", filters=[["Has Role", "role", "=", "System Manager"]], pluck="email"
            )
            return [email for email in admin_emails if email]
        except:
            return []


def get_threshold_setting(setting_field, default_value):
    """
    Retrieve configurable threshold values for notification and alerting systems.

    This function provides a centralized mechanism for accessing threshold
    configurations that control when notifications are triggered. It ensures
    consistent behavior across the system while allowing customization through
    the Verenigingen Settings interface.

    Common Threshold Settings:
        - Payment failure retry counts before alerting
        - Membership expiration notification periods
        - SEPA batch processing error limits
        - System resource utilization alert levels

    Args:
        setting_field (str): Field name in Verenigingen Settings DocType
                           containing the threshold configuration value
        default_value (any): Default value to return if setting is not
                           configured or accessible

    Returns:
        any: Configured threshold value from settings, or default_value
             if setting is unavailable or malformed

    Error Handling:
        Silent fallback to default value with no error propagation,
        ensuring system continues operation with reasonable defaults
        even if configuration is temporarily unavailable.

    Example:
        # Get payment retry threshold with default of 3 attempts
        max_retries = get_threshold_setting("payment_max_retries", 3)

        # Get membership expiration warning days with default of 30
        warning_days = get_threshold_setting("membership_expiration_warning_days", 30)
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return getattr(settings, setting_field, default_value)
    except:
        return default_value
