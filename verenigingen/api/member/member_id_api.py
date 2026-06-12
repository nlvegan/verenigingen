# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member ID API - Member identification management endpoints.

Extracted from member.py module-level functions for better organization.
All functions delegate to MemberIDService for actual implementation.

Functions:
    - assign_missing_member_ids: Bulk assign IDs to members without them
    - debug_member_id_assignment: Debug ID assignment for a specific member
"""

import frappe

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_missing_member_ids():
    """Assign missing member IDs - delegates to MemberIDService"""
    from verenigingen.services.member.identification.member_id_service import get_member_id_service

    return get_member_id_service().assign_missing_member_ids()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def debug_member_id_assignment(member_name: str):
    """Debug member ID assignment - delegates to MemberIDService.

    Note: This is a debugging utility intended for development/troubleshooting.
    """
    from verenigingen.services.member.identification.member_id_service import get_member_id_service

    return get_member_id_service().debug_member_id_assignment(member_name)
