"""
Boot session handler for Verenigingen
Handles test mode setup and other session initialization
"""

import frappe


def boot_session(bootinfo):
    """
    Called when a user session starts
    Sets up test mode configuration if running in test context
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

    # Add any other boot session setup here
    pass
