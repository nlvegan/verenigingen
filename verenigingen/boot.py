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
    session initialization. It does NOT touch email mocking or mute flags: a session
    boot under test used to do that process-wide and never undo it (#2062).

    Args:
        bootinfo (dict): Frappe boot information dictionary containing
                        session initialization data and user context

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
    # No test-mode block (#2062): this used to enable the process-wide sendmail mock and set
    # mute_emails on every session boot under in_test, and nothing undid either, so one test that
    # booted a session left every later Email Queue assertion in the process seeing no row. A test
    # that wants a mock installs its own in scope (EnhancedTestCase, @patch).

    # Apply Firefox session cache corruption fix
    try:
        from verenigingen.session_cache_fix import apply_firefox_cache_fix

        # Fix is auto-applied on import
    except Exception as e:
        frappe.logger().error(f"Could not load Firefox cache fix: {e}")

    # Authentication issue resolved via CSRF secret key in site config
    # The "User None is disabled" error was fixed by adding csrf_secret_key
    # to prevent session corruption during tab switching

    # Return bootinfo for framework
    return bootinfo
