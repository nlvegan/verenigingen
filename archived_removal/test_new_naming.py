#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_new_naming_pattern():
    """Test the new naming pattern helper function"""

    from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

    member_name = "Assoc-Member-2025-07-0025"
    membership_type = "Daglid"

    try:
        # Test the naming function
        new_name = generate_dues_schedule_name(member_name, membership_type)

        # Also show what it would be for a new member
        test_member = "Assoc-Member-2025-07-0026"
        new_member_name = generate_dues_schedule_name(test_member, membership_type)

        return {
            "success": True,
            "existing_member_next_schedule": new_name,
            "new_member_first_schedule": new_member_name,
            "pattern": "Schedule-{member}-{template}-{sequence:03d}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_create_from_template():
    """Test creating a schedule from template with new naming"""

    from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
        MembershipDuesSchedule,
    )

    member_name = "Assoc-Member-2025-07-0025"

    try:
        # This should use the new naming pattern
        new_schedule_name = MembershipDuesSchedule.create_from_template(member_name)

        return {
            "success": True,
            "message": "Schedule created successfully",
            "schedule_name": new_schedule_name,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
