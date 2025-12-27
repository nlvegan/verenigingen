"""
Email Address Utilities for Verenigingen App

This module provides centralized email address management for testing
and placeholder purposes. Production emails should come from Verenigingen
Settings or site configuration.
"""

from typing import Dict

import frappe

# Test Email Addresses (safe for testing environments)
TEST_EMAILS = {
    "generic_test": "test@example.com",
    "admin_test": "test_admin@example.com",
    "member_test": "test_member@example.com",
    "guest_test": "test_guest@example.com",
    "volunteer_test": "test.volunteer@example.org",
    "donor_test": "test_donor@example.com",
    "payment_test": "payment_test@example.com",
    "invoice_test": "invoice_test@example.com",
    "background_job_test": "background_job@example.com",
    "validation_test": "validation.test@example.com",
    "workflow_test": "workflow.test@example.com",
    "integration_test": "integration.test@example.com",
}

# Placeholder/Example Email Addresses (for forms and documentation)
PLACEHOLDER_EMAILS = {
    "example_personal": "your.email@example.com",
    "example_support": "support@example.com",
    "example_complex": "test.email+tag@example.co.uk",
    "example_subdomain": "user@mail.example.com",
    "example_long": "very.long.email.address@very.long.domain.example.com",
    "example_case": "Test.EMAIL@EXAMPLE.COM",
    "example_numbers": "user123@example123.com",
    "example_dots": "user.name.test@example.co.uk",
    "example_minimal": "a@b.co",
}

# Security Test Email Addresses (for security testing)
SECURITY_TEST_EMAILS = {
    "xss_test": "test@example.com",
    "sql_injection_test": "test_sql@example.com",
    "ldap_injection_test": "test_ldap@example.com",
    "header_injection_test": "test_header@example.com",
    "email_injection_victim": "victim@example.com",
}


def get_production_email(key: str) -> str:
    """
    Get a production email from Verenigingen Settings.

    Args:
        key: The email key (e.g., 'support_email', 'admin_email')

    Returns:
        str: The email address from settings, or empty string if not found
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return settings.get(key) or ""
    except Exception:
        return ""


def get_support_email() -> str:
    """
    Get the support email from settings.

    Returns:
        str: Support email address
    """
    # Try to get from Verenigingen Settings
    email = get_production_email("support_email")
    if email:
        return email

    # Fallback to default outgoing email account
    try:
        default_account = frappe.db.get_value(
            "Email Account",
            {"default_outgoing": 1, "enable_outgoing": 1},
            "email_id",
        )
        if default_account:
            return default_account
    except Exception:
        pass

    return ""


def get_email(category: str, key: str, fallback: str = None) -> str:
    """
    Get an email address from the fixtures.

    Args:
        category: The email category (test, placeholder, security_test)
        key: The specific email key within the category
        fallback: Fallback email if key not found

    Returns:
        str: The email address

    Raises:
        KeyError: If category or key not found and no fallback provided
    """
    categories = {
        "test": TEST_EMAILS,
        "placeholder": PLACEHOLDER_EMAILS,
        "security_test": SECURITY_TEST_EMAILS,
    }

    if category not in categories:
        if fallback:
            return fallback
        raise KeyError(f"Email category '{category}' not found")

    if key not in categories[category]:
        if fallback:
            return fallback
        raise KeyError(f"Email key '{key}' not in category '{category}'")

    return categories[category][key]


def get_test_email(purpose: str = "generic") -> str:
    """
    Get a test email for specific testing purposes.

    Args:
        purpose: Test purpose (generic, admin, member, volunteer, etc.)

    Returns:
        str: Test email address
    """
    key_mapping = {
        "generic": "generic_test",
        "admin": "admin_test",
        "member": "member_test",
        "guest": "guest_test",
        "volunteer": "volunteer_test",
        "donor": "donor_test",
        "payment": "payment_test",
        "invoice": "invoice_test",
        "workflow": "workflow_test",
        "validation": "validation_test",
    }

    key = key_mapping.get(purpose, "generic_test")
    return get_email("test", key)


def get_placeholder_email(context: str = "personal") -> str:
    """
    Get a placeholder email for forms and examples.

    Args:
        context: Context for the placeholder (personal, support, complex, etc.)

    Returns:
        str: Placeholder email address
    """
    key_mapping = {
        "personal": "example_personal",
        "support": "example_support",
        "complex": "example_complex",
        "subdomain": "example_subdomain",
        "long": "example_long",
        "case": "example_case",
        "numbers": "example_numbers",
        "dots": "example_dots",
        "minimal": "example_minimal",
    }

    key = key_mapping.get(context, "example_personal")
    return get_email("placeholder", key)


def is_test_email(email: str) -> bool:
    """
    Check if an email address is a test email.

    Args:
        email: Email address to check

    Returns:
        bool: True if the email is a test email
    """
    all_test_emails = set()
    all_test_emails.update(TEST_EMAILS.values())
    all_test_emails.update(PLACEHOLDER_EMAILS.values())
    all_test_emails.update(SECURITY_TEST_EMAILS.values())

    return email.lower() in {e.lower() for e in all_test_emails}


def get_all_emails() -> Dict[str, Dict[str, str]]:
    """
    Get all email fixtures organized by category.

    Returns:
        dict: All email fixtures
    """
    return {
        "test": TEST_EMAILS,
        "placeholder": PLACEHOLDER_EMAILS,
        "security_test": SECURITY_TEST_EMAILS,
    }


def get_emails_for_cleanup() -> list:
    """
    Get list of emails that should be cleaned up after tests.

    Returns:
        list: Email addresses that need cleanup
    """
    cleanup_emails = []
    cleanup_emails.extend(TEST_EMAILS.values())
    cleanup_emails.extend(SECURITY_TEST_EMAILS.values())

    return cleanup_emails


# Backwards compatibility aliases
def get_environment_email(key: str, fallback: str = None) -> str:
    """
    Get email based on current environment.
    Deprecated: Use get_test_email() or get_production_email() instead.
    """
    # Try test emails first
    if key in TEST_EMAILS:
        return TEST_EMAILS[key]
    if key in PLACEHOLDER_EMAILS:
        return PLACEHOLDER_EMAILS[key]

    if fallback:
        return fallback

    raise KeyError(f"Email key '{key}' not found")


def is_dev_email(email: str) -> bool:
    """
    Check if an email address is a development-specific email.
    Deprecated: Dev-specific emails are no longer tracked in code.

    Args:
        email: Email address to check

    Returns:
        bool: Always returns False (dev emails removed from codebase)
    """
    return False
