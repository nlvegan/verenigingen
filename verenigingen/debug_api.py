#!/usr/bin/env python3
"""
Debug API Functions Module
==========================

Provides debugging and testing utilities for the Verenigingen association management
system. This module contains development and troubleshooting functions that help
developers and administrators validate system functionality, test API endpoints,
and diagnose integration issues.

Primary Purpose:
    Development support tools for testing membership application workflows,
    API endpoint validation, and system integration verification.

Key Features:
    * Membership application testing with sample data
    * API endpoint validation and error handling testing
    * Integration workflow debugging capabilities
    * Development environment testing utilities

Security Note:
    This module contains debugging functions that should only be accessible
    in development environments. Production deployments should restrict access
    to these endpoints.

Usage Context:
    Primarily used during development, testing, and troubleshooting phases
    to validate system behavior and identify integration issues.
"""

import frappe
from frappe.utils import today

from verenigingen.api.membership_application import submit_application


@frappe.whitelist()
def test_membership_application():
    """
    Test membership application submission workflow with sample data.

    This debugging function creates a standardized test membership application
    to validate the entire application submission workflow, including data
    validation, member creation, and error handling.

    Test Scenario:
        Creates a test application with Dutch member data including:
        - Personal information (name, email, birth date)
        - Address details (Amsterdam-based test address)
        - Contact preferences and volunteering interest
        - Newsletter subscription preferences

    Returns:
        dict: Application submission result containing:
            - success (bool): Whether the application was processed successfully
            - member_record (str): Created member document name if successful
            - application_id (str): Application tracking ID if successful
            - error (str): Error message if submission failed
            - issues (list): Detailed validation issues if any

    Raises:
        Exception: Any unexpected errors during application processing

    Usage:
        Called via Frappe's web API for development testing:
        /api/method/verenigingen.debug_api.test_membership_application

    Note:
        Uses a fixed email address for duplicate testing scenarios.
        This function should only be available in development environments.
    """

    # Sample application data
    test_data = {
        "first_name": "Debug",
        "last_name": "Tester",
        "email": "debug.test.duplicate@example.com",  # Fixed email for duplicate test
        "birth_date": "1990-01-01",
        "address_line1": "123 Test Street",
        "city": "Amsterdam",
        "postal_code": "1234AB",
        "country": "Netherlands",
        "contact_number": "+31612345678",
        "interested_in_volunteering": 0,
        "newsletter_opt_in": 1,
        "application_source": "Website",
    }

    print("Testing membership application submission...")
    print("Application data:")
    for key, value in test_data.items():
        print(f"  {key}: {value}")

    print("\nCalling submit_application...")
    try:
        result = submit_application(**test_data)
        print(f"\nResult: {result}")

        if result.get("success"):
            print("\n✅ Success! Application submitted.")
            print(f"Member record: {result.get('member_record')}")
            print(f"Application ID: {result.get('application_id')}")
        else:
            print(f"\n❌ Failed: {result.get('error', 'Unknown error')}")
            if "message" in result:
                print(f"Message: {result['message']}")
            if "issues" in result:
                print(f"Issues: {result['issues']}")

        return result

    except Exception as e:
        print(f"\n💥 Exception: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}
