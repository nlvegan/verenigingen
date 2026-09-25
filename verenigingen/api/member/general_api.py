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

    Matches the Donor via the authoritative ``Donor.member`` link field
    first (set by MemberDonorIntegrationService.create_donor_from_member),
    then falls back to an exact e-mail match.

    There is deliberately no name-based fallback. On production data
    (veg11, measured while fixing #1356) zero Donor records have ``member``
    or ``donor_email`` set, so a name match would be the ONLY signal that
    ever fires there -- and a member's ``full_name`` is free text that any
    number of unrelated donors can share (a common Dutch name), with
    nothing to disambiguate them. A member with a genuinely linked Donor
    now correctly needs that link (or a matching e-mail) rather than a
    same-name stranger being attached; staff can set ``Donor.member`` to
    resolve it. This is a visible UX change (a linked-but-unrecorded donor
    now shows "no donor" instead of a guess) but a safe one, since #1356's
    own measurement found zero members who were getting a correct match
    under the old logic.

    Each tier requires EXACTLY ONE match, and an AMBIGUOUS match (more than
    one) refuses IMMEDIATELY rather than falling through to a weaker tier:
    an earlier version of this fix let an ambiguous ``member`` link (two
    Donors both linked to the same Member) fall through to the e-mail
    tier, which then resolved via a completely unrelated Donor that merely
    shared the member's e-mail address -- see the #1356 review.

    Uses ``find_donors_by_field`` (services/member/donor/
    donor_member_reconciliation.py) -- the single canonical Donor-resolution
    query shared by every tiered lookup in the app (``get_donor_for_member``,
    ``DonorManagementService.check_donor_exists``, and this function) -- so
    there is exactly one place that decides what "an exact, unambiguous
    match" means (#1406).

    Args:
        member: Member name/ID

    Returns:
        dict: Result with success status and donor name if found
    """
    if not member:
        return {"success": False, "message": "No member specified"}

    from verenigingen.services.member.donor.donor_member_reconciliation import find_donors_by_field

    member_doc = frappe.get_doc("Member", member)

    matches = find_donors_by_field("member", member_doc.name)
    if len(matches) > 1:
        return {"success": False, "message": "Multiple donor records are linked to this member"}
    if matches:
        return {"success": True, "donor": matches[0].name}

    if member_doc.email:
        matches = find_donors_by_field("donor_email", member_doc.email)
        if len(matches) > 1:
            return {
                "success": False,
                "message": "Multiple donor records share this member's e-mail address",
            }
        if matches:
            return {"success": True, "donor": matches[0].name}

    # No donor found
    return {"success": False, "message": "No donor record found for this member"}
