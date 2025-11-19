#!/usr/bin/env python3

import frappe


def generate_dues_schedule_name(member_name, membership_type):
    """
    Generate a new dues schedule name with the pattern:
    Schedule-{member_name}-{membership_type}-{sequence}

    Args:
        member_name: Name of the member (e.g., 'Assoc-Member-2025-07-0025')
        membership_type: Name of the membership type (e.g., 'Daglid')

    Returns:
        str: Generated schedule name (e.g., 'Schedule-Assoc-Member-2025-07-0025-Daglid-001')
    """

    # Count existing schedules for this member-template combination
    existing_count = frappe.db.count(
        "Membership Dues Schedule",
        {"member": member_name, "membership_type": membership_type, "is_template": 0},
    )

    # Next sequence number
    sequence = existing_count + 1

    # Generate the name
    schedule_name = f"Schedule-{member_name}-{membership_type}-{sequence:03d}"

    # Ensure uniqueness (in case of race conditions or manual schedules)
    while frappe.db.exists("Membership Dues Schedule", {"schedule_name": schedule_name}):
        sequence += 1
        schedule_name = f"Schedule-{member_name}-{membership_type}-{sequence:03d}"

    return schedule_name
