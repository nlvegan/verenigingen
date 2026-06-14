# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
General Member API - General member management endpoints.

Extracted from member.py module-level functions for better organization.
Includes account creation, donor management, and testing utilities.

Functions:
    - create_member_user_account: Create user account for portal access
    - check_donor_exists: Check if donor record exists for member
    - create_donor_from_member: Create donor from member information
    - get_linked_donations: Find linked donor for viewing donations
    - test_member_form_functionality: Test member form functionality
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_member_user_account(member_name: str, send_welcome_email=True):
    """
    Create a user account for a member to access portal pages.

    EXTRACTED: Moved to MemberUserAccountService.create_member_user_account()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document
        send_welcome_email: Whether to send welcome email (default True)

    Returns:
        dict: Result dictionary with success, message, user, and action
    """
    from verenigingen.services.member.account.member_user_account_service import (
        get_member_user_account_service,
    )

    return get_member_user_account_service().create_member_user_account(member_name, send_welcome_email)


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def check_donor_exists(member_name: str):
    """Check if a donor record exists for this member"""
    from verenigingen.services.member.donor import get_donor_management_service

    return get_donor_management_service().check_donor_exists(member_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_donor_from_member(member_name: str):
    """
    Create a donor record from member information.

    EXTRACTED: Moved to MemberDonorIntegrationService.create_donor_from_member()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document

    Returns:
        dict: Result dictionary with success, message, and donor_name
    """
    from verenigingen.services.member.integration.member_donor_integration_service import (
        get_member_donor_integration_service,
    )

    return get_member_donor_integration_service().create_donor_from_member(member_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.UTILITY)
def test_member_form_functionality(member_name: str):
    """Delegate to extracted testing utility.

    Note: This is a testing/debugging utility intended for development.
    """
    from verenigingen.services.member.testing.member_test_utilities import test_member_form_functionality

    return test_member_form_functionality(member_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_linked_donations(member: str | None = None):
    """
    Find linked donor record for a member to view donations.

    Searches for a donor with matching email or name.

    Args:
        member: Member name/ID

    Returns:
        dict: Result with success status and donor name if found
    """
    if not member:
        return {"success": False, "message": "No member specified"}

    # First try to find a donor with the same email as the member
    member_doc = frappe.get_doc("Member", member)
    if member_doc.email:
        donors = frappe.get_all("Donor", filters={"donor_email": member_doc.email}, fields=["name"])

        if donors:
            return {"success": True, "donor": donors[0].name}

    # Then try to find by name
    if member_doc.full_name:
        donors = frappe.get_all(
            "Donor", filters={"donor_name": ["like", f"%{member_doc.full_name}%"]}, fields=["name"]
        )

        if donors:
            return {"success": True, "donor": donors[0].name}

    # No donor found
    return {"success": False, "message": "No donor record found for this member"}
