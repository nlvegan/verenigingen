"""
Email Address Fixtures for Verenigingen App

This module provides centralized email address management for the Verenigingen app.
It categorizes emails by their purpose and provides easy access methods.
"""

import os
from typing import Any, Dict

# Production/Live Email Addresses (these should be configurable)
PRODUCTION_EMAILS = {
    "app_contact": "info@verenigingen.org",
    "member_administration": "ledenadministratie@veganisme.org",
    "general_support": "info@vereniging.nl",
    "admin_notifications": "admin@veganisme.net",
}

# Test Email Addresses (safe for testing environments)
TEST_EMAILS = {
    "generic_test": "test@example.com",
    "admin_test": "test_admin@example.com",
    "member_test": "test_member@example.com",
    "guest_test": "test_guest@example.com",
    "volunteer_test": "test.volunteer.js@example.org",
    "donor_test": "test@example.com",
    "payment_test": "phase22payment@test.com",
    "invoice_test": "phase22invoice@test.com",
    "background_job_test": "phase22bg@test.com",
    "validation_test": "validation.test@example.com",
    "workflow_test": "workflow.test@example.com",
    "integration_test": "volunteer.integration@example.com",
}

# Development-specific Email Addresses (user-specific, temporary)
DEV_EMAILS = {
    "foppe": "foppe@veganisme.org",
    "fjdh_leden": "fjdh@leden.socialisten.org",
    "foppe_rsp": "foppe.haan@leden.rsp.nu",
}

# Placeholder/Example Email Addresses (for forms and documentation)
PLACEHOLDER_EMAILS = {
    "example_personal": "your.email@example.com",
    "example_support": "support@example.com",
    "example_complex": "test.email+tag@example.co.uk",
    "example_subdomain": "user@mail.example.com",
    "example_long": "very.long.email.address.for.testing.purposes@very.long.domain.name.example.com",
    "example_case": "Test.EMAIL@EXAMPLE.COM",
    "example_numbers": "user123@example123.com",
    "example_dots": "user.name.test@example.co.uk",
    "example_minimal": "a@b.co",
}

# Security Test Email Addresses (for security testing)
SECURITY_TEST_EMAILS = {
    "xss_test": "test@example.com",  # Used with XSS payloads in other fields
    "sql_injection_test": "hacked@evil.com",  # Used in SQL injection tests
    "ldap_injection_test": "test*)(mail=*))%00@example.com",
    "header_injection_test": "test@example.com\nBcc: hacker@evil.com",
    "email_injection_victim": "victim@example.com",
}


def get_email(category: str, key: str, fallback: str = None) -> str:
    """
    Get an email address from the fixtures.

    Args:
        category: The email category (production, test, dev, placeholder, security_test)
        key: The specific email key within the category
        fallback: Fallback email if key not found

    Returns:
        str: The email address

    Raises:
        KeyError: If category or key not found and no fallback provided
    """
    categories = {
        "production": PRODUCTION_EMAILS,
        "test": TEST_EMAILS,
        "dev": DEV_EMAILS,
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


def get_support_email(environment: str = None) -> str:
    """
    Get the appropriate support email based on environment.

    Args:
        environment: Environment name (production, development, test)

    Returns:
        str: Support email address
    """
    if environment == "production":
        return get_email("production", "member_administration")
    elif environment == "development":
        return get_email("placeholder", "example_support")
    else:
        return get_email("test", "generic_test")


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


def is_dev_email(email: str) -> bool:
    """
    Check if an email address is a development-specific email.

    Args:
        email: Email address to check

    Returns:
        bool: True if the email is a dev email
    """
    return email.lower() in {e.lower() for e in DEV_EMAILS.values()}


def get_all_emails() -> Dict[str, Dict[str, str]]:
    """
    Get all email fixtures organized by category.

    Returns:
        dict: All email fixtures
    """
    return {
        "production": PRODUCTION_EMAILS,
        "test": TEST_EMAILS,
        "dev": DEV_EMAILS,
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


# Environment-aware email retrieval
def get_environment_email(key: str, fallback: str = None) -> str:
    """
    Get email based on current environment.
    Checks environment variables to determine if we're in development/test.

    Args:
        key: Email key to retrieve
        fallback: Fallback email if not found

    Returns:
        str: Email address appropriate for current environment
    """
    # Check if we're in a development environment
    is_development = (
        os.getenv("FRAPPE_ENV") == "development"
        or os.getenv("ENVIRONMENT") == "development"
        or "dev.veganisme.net" in os.getenv("SITE_NAME", "")
    )

    if is_development:
        # Try to get from test emails first
        if key in TEST_EMAILS:
            return TEST_EMAILS[key]
        elif key in PLACEHOLDER_EMAILS:
            return PLACEHOLDER_EMAILS[key]

    # Try production emails
    if key in PRODUCTION_EMAILS:
        return PRODUCTION_EMAILS[key]

    # Return fallback or raise error
    if fallback:
        return fallback

    raise KeyError(f"Email key '{key}' not in any category")
