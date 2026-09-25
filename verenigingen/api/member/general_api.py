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

    Matches the Donor via the authoritative ``Donor.member`` link field first
    (set by MemberDonorIntegrationService.create_donor_from_member), then
    falls back to an exact e-mail match, then an exact full_name match.

    Each tier requires EXACTLY ONE match. A fuzzy/substring name match with
    no ambiguity guard let a member's own free-text full_name (e.g. "Jan")
    silently attach an unrelated donor's ("Jan de Vries") donations to the
    wrong member; see #1356. None of the three signals below is a
    wildcard/LIKE query, so there is nothing to escape.

    Args:
        member: Member name/ID

    Returns:
        dict: Result with success status and donor name if found
    """
    if not member:
        return {"success": False, "message": "No member specified"}

    member_doc = frappe.get_doc("Member", member)

    donor = _find_unambiguous_donor("member", member_doc.name)
    if donor:
        return {"success": True, "donor": donor}

    if member_doc.email:
        donor = _find_unambiguous_donor("donor_email", member_doc.email)
        if donor:
            return {"success": True, "donor": donor}

    if member_doc.full_name:
        donor = _find_unambiguous_donor("donor_name", member_doc.full_name)
        if donor:
            return {"success": True, "donor": donor}

    # No donor found
    return {"success": False, "message": "No donor record found for this member"}


def _find_unambiguous_donor(fieldname: str, value: str) -> str | None:
    """Return the single Donor matching ``fieldname == value``, or None.

    Returns None both when there is no match and when there is more than
    one -- an ambiguous match must never be resolved by picking the first
    result arbitrarily (see #1356).
    """
    donors = frappe.get_all("Donor", filters={fieldname: value}, fields=["name"])
    if len(donors) == 1:
        return donors[0].name
    return None
