# File: verenigingen/patches/v2_1/backfill_membership_commitment_end_date.py
"""
Backfill commitment_end_date for existing Membership records.

This patch is required after consolidating membership end date fields.
The commitment_end_date field tracks when members can quit (typically 1 year
from membership start for welcome gift recipients).
"""

import frappe
from frappe.utils import add_to_date, getdate


def execute():
    """
    Backfill commitment_end_date for all existing Membership records
    that don't have this field set.
    """
    frappe.logger().info("Starting backfill of membership commitment_end_date...")

    # Get all submitted memberships without commitment_end_date
    memberships = frappe.get_all(
        "Membership",
        filters={
            "docstatus": 1,
            "commitment_end_date": ["is", "not set"],
        },
        fields=["name", "start_date"],
        order_by="creation asc",
    )

    if not memberships:
        frappe.logger().info("No memberships need backfilling - all up to date")
        return

    frappe.logger().info(f"Found {len(memberships)} memberships to backfill")

    updated_count = 0
    skipped_count = 0

    for membership in memberships:
        if not membership.start_date:
            frappe.logger().warning(f"Membership {membership.name} has no start_date - skipping")
            skipped_count += 1
            continue

        try:
            # Calculate commitment end date as 1 year from start
            start_date = getdate(membership.start_date)
            commitment_date = add_to_date(start_date, months=12)

            # Update without triggering validation or modifying timestamp
            frappe.db.set_value(
                "Membership",
                membership.name,
                "commitment_end_date",
                commitment_date,
                update_modified=False,
            )

            updated_count += 1

            # Log every 100 records for progress tracking
            if updated_count % 100 == 0:
                frappe.logger().info(f"Processed {updated_count} memberships...")

        except Exception as e:
            frappe.logger().error(f"Failed to update membership {membership.name}: {str(e)}")
            skipped_count += 1
            continue

    # Commit the changes
    frappe.db.commit()

    frappe.logger().info(f"Backfill complete: {updated_count} updated, {skipped_count} skipped")

    # Create a log entry for audit trail
    frappe.logger().info(
        f"Membership commitment_end_date backfill completed successfully. "
        f"Updated: {updated_count}, Skipped: {skipped_count}"
    )
