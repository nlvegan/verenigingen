# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Financial API - Member financial and dues management endpoints.

Extracted from member.py module-level functions for better organization.
Provides endpoints for dues rate syncing, schedule details, and fee history.

Functions:
    - sync_member_dues_rate: Sync member's dues_rate with active schedule
    - get_current_dues_schedule_details: Get current dues schedule details
    - refresh_fee_change_history: Refresh fee change history from schedules
"""

import frappe

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def sync_member_dues_rate(member_name):
    """Sync member's dues_rate field with their active dues schedule"""
    try:
        # Get the member's active dues schedule using repository
        repo = DuesScheduleRepository()
        schedule = repo.get_active_schedule(member_name, fields=["name", "dues_rate"])

        if schedule:
            # Update member's dues_rate field
            member_doc = frappe.get_doc("Member", member_name)
            member_doc.dues_rate = schedule.dues_rate
            member_doc.save()
            return {
                "success": True,
                "message": f"Synced dues rate: {schedule.dues_rate}",
                "dues_rate": schedule.dues_rate,
            }
        else:
            return {"success": False, "message": "No active dues schedule found"}
    except Exception as e:
        frappe.log_error(f"Error syncing member dues rate: {str(e)}", "Member Dues Rate Sync")
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_current_dues_schedule_details(member):
    """Get current dues schedule details for a member"""
    try:
        # Get active dues schedule using repository
        repo = DuesScheduleRepository()
        dues_schedule = repo.get_active_schedule(
            member,
            fields=["name", "dues_rate", "billing_frequency", "next_invoice_date", "membership_type"],
        )

        if not dues_schedule:
            return {"has_schedule": False, "message": "No active dues schedule found"}

        # Get membership type details
        membership_type = None
        if dues_schedule.membership_type:
            membership_type = frappe.db.get_value(
                "Membership Type",
                dues_schedule.membership_type,
                ["membership_type_name", "description"],
                as_dict=True,
            )

        return {
            "has_schedule": True,
            "schedule_name": dues_schedule.name,
            "dues_rate": dues_schedule.dues_rate,
            "billing_frequency": dues_schedule.billing_frequency,
            "next_invoice_date": dues_schedule.next_invoice_date,
            "membership_type": dues_schedule.membership_type,
            "membership_type_name": membership_type.membership_type_name if membership_type else None,
            "membership_type_description": membership_type.description if membership_type else None,
        }

    except Exception as e:
        frappe.log_error(
            f"Error getting dues schedule details for member {member}: {str(e)}", "Dues Schedule Details"
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def refresh_fee_change_history(member_name):
    """
    Refresh fee change history from dues schedules with integrity checking.

    EXTRACTED: Moved to MemberHistoryUpdateService.refresh_fee_change_history()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document

    Returns:
        dict: Result dictionary with success, message, and statistics
    """
    from verenigingen.services.member.history.member_history_update_service import (
        get_member_history_update_service,
    )

    return get_member_history_update_service().refresh_fee_change_history(member_name)
