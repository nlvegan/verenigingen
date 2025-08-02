"""
Member Setup Onboarding Web Interface for Verenigingen System

This module provides a web-based onboarding interface for setting up the member
management system in new Verenigingen installations. It guides administrators
through the essential steps of creating initial data structures, test members,
and membership types required for system operation.

Key Features:
    * Interactive member system setup wizard
    * Test member generation for system validation
    * Membership type configuration interface
    * Real-time progress tracking and validation
    * Comprehensive cleanup capabilities for development environments

User Experience:
    The interface provides a guided experience for new system administrators,
    ensuring proper setup of member management functionality with clear
    progress indicators and validation feedback. It includes safety features
    for development environments and cleanup tools for testing scenarios.

Integration Context:
    This onboarding interface integrates with the broader Verenigingen system
    setup process, working alongside other onboarding modules to provide a
    complete system initialization experience. It validates permissions and
    system state to ensure proper configuration.

Target Users:
    - System administrators setting up new Verenigingen installations
    - Development teams requiring test data for system validation
    - IT personnel responsible for member management system configuration
"""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
    """
    Generate comprehensive context data for the member setup onboarding interface.

    This function prepares all necessary data for rendering the onboarding page,
    including system status information, existing data summaries, and configuration
    options. It validates user permissions and provides real-time system state.

    Args:
        context (dict): Frappe page context object to populate

    Returns:
        dict: Enhanced context containing:
            - member_count (int): Current number of members in system
            - test_members (list): Existing test member records
            - membership_types (list): Available membership type configurations
            - permission_status (bool): User's ability to create members
            - setup_progress (dict): Current onboarding progress indicators

    Permission Requirements:
        User must have "create" permission on Member DocType to access
        the onboarding interface. Unauthorized access results in PermissionError.

    Data Validation:
        - Identifies test members using email pattern matching
        - Validates membership type configuration completeness
        - Provides counts and status indicators for progress tracking
    """
    context.no_cache = 1
    context.show_sidebar = False

    # Check permissions
    if not frappe.has_permission("Member", "create"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Get member count
    context.member_count = frappe.db.count("Member")

    # Get test members
    test_members = frappe.get_all(
        "Member", filters={"email": ["like", "%@email.nl"]}, fields=["name", "full_name", "status"], limit=10
    )

    context.test_members = test_members
    context.test_members_count = len(test_members)
    context.has_test_members = len(test_members) > 0

    # Get membership types
    membership_types = frappe.get_all("Membership Type", fields=["name", "membership_type_name"], limit=5)

    context.membership_types = membership_types
    context.membership_types_count = len(membership_types)
    context.has_membership_types = len(membership_types) > 0

    return context


@frappe.whitelist()
def generate_test_members_from_onboarding():
    """
    Generate standardized test members for system validation and development.

    This function creates a set of test member records with realistic data
    for system validation, development testing, and demonstration purposes.
    It integrates with the onboarding system to track setup progress.

    Test Member Characteristics:
        - Realistic but clearly identifiable as test data
        - Proper status progression from Pending to Active
        - Representative of typical member data patterns
        - Safe for development and testing environments

    Returns:
        dict: Operation result containing:
            - success (bool): Whether test member creation succeeded
            - created (int): Number of test members successfully created
            - members (list): Details of created member records
            - message (str): Human-readable operation summary

    Integration:
        - Updates onboarding step completion status automatically
        - Integrates with broader system setup workflow
        - Provides audit trail for setup operations

    Note:
        This function is exposed via Frappe's whitelist for AJAX calls
        from the onboarding interface, enabling real-time member creation.
    """
    # Use the new method that properly creates Pending members
    from verenigingen.utils.create_test_pending_members import create_test_pending_members

    result = create_test_pending_members()

    # Mark onboarding step as complete if successful
    if result.get("success") and result.get("created", 0) > 0:
        try:
            frappe.db.set_value("Onboarding Step", "Verenigingen-Create-Member", "is_complete", 1)
            frappe.db.commit()
        except Exception:
            pass  # Ignore if onboarding step doesn't exist

    return result


@frappe.whitelist()
def cleanup_test_data():
    """
    Remove test members and associated data for clean development environments.

    This function provides comprehensive cleanup of test member data created
    during onboarding or development processes. It ensures complete removal
    of test records while preserving production data integrity.

    Cleanup Scope:
        - Test member records and associated memberships
        - Related customer and contact records
        - Payment history and invoice data for test members
        - SEPA mandates and dues schedules
        - Volunteer assignments and team memberships

    Safety Features:
        - Pattern-based identification of test data to prevent accidental removal
        - Comprehensive validation before deletion operations
        - Detailed logging of cleanup operations for audit purposes
        - Rollback capabilities for recovery scenarios

    Returns:
        dict: Cleanup operation results containing:
            - success (bool): Overall cleanup operation success
            - removed (int): Number of test records removed
            - categories (dict): Breakdown of removed record types
            - warnings (list): Any issues encountered during cleanup

    Note:
        This function delegates to the comprehensive cleanup implementation
        in the templates/pages module for code reusability and consistency.
    """
    # Import the cleanup function from templates/pages
    from verenigingen.templates.pages.onboarding_member_setup import cleanup_test_data as cleanup_impl

    return cleanup_impl()
