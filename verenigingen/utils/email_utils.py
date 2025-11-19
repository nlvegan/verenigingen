"""
Email Utilities for Verenigingen App

This module provides utility functions for email management that integrate
with the email fixtures and Frappe settings.
"""

import frappe

from verenigingen.fixtures.email_addresses import (
    get_email,
    get_environment_email,
    get_placeholder_email,
    get_support_email,
    get_test_email,
    is_dev_email,
    is_test_email,
)


def get_member_contact_email() -> str:
    """
    Get the member contact email with proper fallback chain.

    Returns:
        str: Member contact email address
    """
    try:
        # First, try to get from Verenigingen Settings
        settings_email = frappe.db.get_single_value("Verenigingen Settings", "member_contact_email")
        if settings_email and settings_email.strip():
            return settings_email.strip()
    except Exception:
        pass

    try:
        # Fallback to Company email
        company = frappe.defaults.get_global_default("company")
        if company:
            company_email = frappe.db.get_value("Company", company, "email")
            if company_email and company_email.strip():
                return company_email.strip()
    except Exception:
        pass

    # Final fallback to fixture
    return get_environment_email("member_administration", get_email("production", "member_administration"))


def get_support_contact_email() -> str:
    """
    Get the support contact email with proper fallback chain.

    Returns:
        str: Support contact email address
    """
    try:
        # Try to get from Company settings
        company = frappe.defaults.get_global_default("company")
        if company:
            company_email = frappe.db.get_value("Company", company, "email")
            if company_email and company_email.strip():
                return company_email.strip()
    except Exception:
        pass

    # Fallback to environment-appropriate email
    return get_environment_email("general_support", get_placeholder_email("support"))


def get_app_contact_email() -> str:
    """
    Get the main app contact email.

    Returns:
        str: App contact email address
    """
    return get_environment_email("app_contact", get_email("production", "app_contact"))


def get_notification_email() -> str:
    """
    Get email for system notifications.

    Returns:
        str: Notification email address
    """
    return get_environment_email("admin_notifications", get_email("production", "admin_notifications"))


def create_test_user_email(purpose: str, user_id: str = None) -> str:
    """
    Create a test user email address.

    Args:
        purpose: Purpose of the test user (admin, member, volunteer, etc.)
        user_id: Optional user ID to make email unique

    Returns:
        str: Test user email address
    """
    base_email = get_test_email(purpose)

    if user_id:
        # Insert user_id before the @ symbol
        local, domain = base_email.split("@", 1)
        return f"{local}.{user_id}@{domain}"

    return base_email


def sanitize_email_for_testing(email: str) -> str:
    """
    Convert a potentially real email to a safe test email.

    Args:
        email: Original email address

    Returns:
        str: Safe test email address
    """
    if is_test_email(email) or is_dev_email(email):
        return email

    # Convert to test email format
    if "@" in email:
        local_part = email.split("@")[0]
        # Create a test email based on the local part
        return f"{local_part}.test@example.com"

    return get_test_email("generic")


def get_email_for_context(context: dict) -> str:
    """
    Get appropriate email based on context (template context, etc.).

    Args:
        context: Context dictionary containing environment info

    Returns:
        str: Appropriate email address
    """
    # Check if we have member_contact_email in context
    if "member_contact_email" in context:
        return context["member_contact_email"]

    # Check if we have support_email in context
    if "support_email" in context:
        return context["support_email"]

    # Default to member contact email
    return get_member_contact_email()


def validate_email_usage(email: str, context: str = "") -> dict:
    """
    Validate that email usage is appropriate for the environment.

    Args:
        email: Email address to validate
        context: Context where the email is being used

    Returns:
        dict: Validation result with warnings/recommendations
    """
    result = {"is_valid": True, "warnings": [], "recommendations": [], "email_type": "unknown"}

    if is_test_email(email):
        result["email_type"] = "test"
        if "production" in context.lower():
            result["warnings"].append("Test email used in production context")
            result["recommendations"].append("Use production email configuration")
    elif is_dev_email(email):
        result["email_type"] = "development"
        if "production" in context.lower():
            result["warnings"].append("Development email used in production context")
            result["recommendations"].append("Use production email configuration")
    elif email in get_email("production", "app_contact"):
        result["email_type"] = "production"
    else:
        result["email_type"] = "unknown"
        result["warnings"].append("Unknown email type - not in fixtures")
        result["recommendations"].append("Add email to fixtures if it's a standard address")

    return result


# Template helper functions
def get_template_email_context() -> dict:
    """
    Get email context suitable for template rendering.

    Returns:
        dict: Email context for templates
    """
    return {
        "member_contact_email": get_member_contact_email(),
        "support_email": get_support_contact_email(),
        "app_contact_email": get_app_contact_email(),
    }


def update_template_context_with_emails(context: dict) -> dict:
    """
    Update template context with appropriate email addresses.

    Args:
        context: Existing template context

    Returns:
        dict: Updated context with email addresses
    """
    email_context = get_template_email_context()

    # Only update if not already present
    for key, value in email_context.items():
        if key not in context:
            context[key] = value

    return context
