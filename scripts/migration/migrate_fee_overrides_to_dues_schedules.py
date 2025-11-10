"""
Legacy Migration Script - Fee Overrides to Dues Schedules

This migration was completed in earlier versions of the system.
The fee_override_* fields have been removed from the Member doctype.

This stub exists only to support legacy test cases.
"""

import frappe
from frappe.utils import today


def migrate_member_override(member_data):
    """
    Stub function for test compatibility.

    Original purpose: Migrated old fee_override_* fields to Membership Dues Schedule.
    This migration has been completed and the source fields no longer exist.

    Args:
        member_data: Dict with member information including dues_rate and fee_override_reason
    """
    # This is a stub - the actual migration was completed in earlier versions
    # The function exists only to support test_fee_override_migration.py

    member_id = member_data.get("name")
    dues_rate = member_data.get("dues_rate")
    override_reason = member_data.get("fee_override_reason")
    override_date = member_data.get("fee_override_date") or today()

    if not member_id or not dues_rate or not override_reason:
        return

    # Check if schedule already exists
    existing = frappe.db.exists(
        "Membership Dues Schedule",
        {
            "member": member_id,
            "custom_amount_reason": ["like", f"%{override_reason}%"]
        }
    )

    if existing:
        return

    # Create a dues schedule for testing purposes
    try:
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": member_id,
            "dues_rate": dues_rate,
            "custom_amount_reason": f"Migrated fee override: {override_reason}",
            "start_date": override_date,
            "billing_interval": "Annual",
            "is_active": 1
        })
        schedule.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error creating dues schedule for {member_id}: {str(e)}")
