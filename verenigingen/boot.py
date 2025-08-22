"""
Session Boot Handler for Verenigingen System
============================================

Handles user session initialization and configuration setup for the Verenigingen
association management system. This module is automatically called by Frappe
framework during user session startup to configure system-specific settings,
test environment setup, and session-specific feature enablement.

Primary Functions:
    * Test environment configuration and email mocking setup
    * Session-specific feature flags and system behavior configuration
    * Development environment setup and debugging utilities
    * User context initialization for association-specific functionality

Key Features:
    * Automatic test mode detection and configuration
    * Email system mocking for testing environments
    * Session logging and debugging capabilities
    * Extensible framework for future session initialization needs

Integration Points:
    * Frappe framework session management system
    * Verenigingen test configuration and mocking utilities
    * Email system integration and testing infrastructure
    * System-wide logging and monitoring capabilities

Architecture Note:
    This module follows Frappe's boot session pattern and is automatically
    called during the user session initialization process. It provides a
    centralized location for system-wide session configuration.
"""

import frappe


def boot_session(bootinfo):
    """
    Initialize user session with Verenigingen-specific configuration.

    This function is automatically called by the Frappe framework during user
    session initialization. It sets up environment-specific configurations,
    particularly for test environments where email mocking and special behavior
    flags need to be enabled.

    Args:
        bootinfo (dict): Frappe boot information dictionary containing
                        session initialization data and user context

    Configuration Tasks:
        * Test mode detection and email mocking enablement
        * Session-specific feature flags for testing environments
        * Development environment debugging setup
        * System behavior modification for test scenarios

    Test Mode Features:
        * Automatic email mocking to prevent actual email sending during tests
        * Email muting flag activation for comprehensive test isolation
        * Test mode logging for debugging and verification
        * Integration with Verenigingen test configuration utilities

    Usage:
        Automatically called by Frappe framework - no direct invocation needed.
        Session setup occurs transparently during user login and session creation.

    Integration:
        Works in conjunction with verenigingen.tests.test_config module for
        comprehensive test environment setup and email system mocking.

    Extension Points:
        Additional session initialization logic can be added here for future
        features requiring session-specific setup or configuration.
    """
    # Check if we're in test mode
    if frappe.flags.get("in_test"):
        # Enable email mocking for tests
        from verenigingen.tests.test_config import enable_test_email_mocking

        enable_test_email_mocking()

        # Set additional test flags
        frappe.flags.mute_emails = True

        # Log that test mode is active
        frappe.logger().info("Verenigingen: Test mode active - emails are mocked")

    # Apply session patches to prevent "User None is disabled" errors
    # This must run early to intercept session resumption issues
    try:
        from verenigingen.monkey_patches.session_patch import apply_session_patches
        apply_session_patches()
    except Exception as e:
        frappe.logger().error(f"Failed to apply session patches: {str(e)}")
    
    # Return bootinfo for framework
    return bootinfo
