"""
Hooks for Membership Dues Schedule to keep Member.current_dues_schedule synchronized
"""

import frappe
from frappe.utils import getdate, today


def update_member_current_dues_schedule(doc, method=None):
    """
    Update the Member's current_dues_schedule field when a dues schedule changes.
    This should be called on after_insert and on_update of Membership Dues Schedule.
    """
    if doc.is_template or not doc.member:
        return

    # Only update if this is an active schedule
    if doc.status != "Active":
        # If this schedule is being deactivated and it's the current one, clear it
        current = frappe.db.get_value("Member", doc.member, "current_dues_schedule")
        if current == doc.name:
            # Find another active schedule or clear the field
            other_active = frappe.get_all(
                "Membership Dues Schedule",
                filters={
                    "member": doc.member,
                    "status": "Active",
                    "is_template": 0,
                    "name": ["!=", doc.name],
                },
                order_by="creation desc",
                limit=1,
            )

            new_current = other_active[0].name if other_active else None
            frappe.db.set_value("Member", doc.member, "current_dues_schedule", new_current)
            # Don't commit here - let the calling transaction handle it

            frappe.logger().info(
                f"Updated Member {doc.member} current_dues_schedule from {doc.name} to {new_current}"
            )
        return

    try:
        # Use a single query to determine if this should be the current schedule
        # This avoids race conditions by checking the database state atomically
        current_schedule_data = frappe.db.sql(
            """
            SELECT
                m.current_dues_schedule,
                mds.status as current_status,
                mds.creation as current_creation
            FROM `tabMember` m
            LEFT JOIN `tabMembership Dues Schedule` mds
                ON m.current_dues_schedule = mds.name
            WHERE m.name = %s
            FOR UPDATE
        """,
            doc.member,
            as_dict=True,
        )

        if not current_schedule_data:
            return

        current_data = current_schedule_data[0]
        should_be_current = False

        # Case 1: No current schedule set
        if not current_data.current_dues_schedule:
            should_be_current = True

        # Case 2: Current schedule is not active
        elif current_data.current_status != "Active":
            should_be_current = True

        # Case 3: This is a newer active schedule (check by creation date)
        elif doc.creation > current_data.current_creation:
            should_be_current = True

        # Update if needed
        if should_be_current and current_data.current_dues_schedule != doc.name:
            frappe.db.set_value("Member", doc.member, "current_dues_schedule", doc.name)
            # Don't commit here - let the calling transaction handle it

            frappe.logger().info(f"Updated Member {doc.member} current_dues_schedule to {doc.name}")

    except Exception as e:
        frappe.log_error(f"Error updating member current_dues_schedule: {str(e)}", "Dues Schedule Hook Error")


def check_and_update_all_members_current_schedule(batch_size=100):
    """
    Utility function to check and update current_dues_schedule for all members.
    Can be run as a scheduled job or manually.

    Performance optimizations:
    - Processes members in batches to avoid memory issues
    - Uses bulk SQL updates where possible
    - Includes timing metrics for monitoring

    Args:
        batch_size (int): Number of members to process in each batch

    Returns:
        dict: Summary of the update operation including metrics
    """
    import time

    start_time = time.time()

    members_updated = 0
    errors = []
    total_members = 0

    # Process in batches to avoid memory issues with large datasets
    offset = 0

    while True:
        # Get batch of members
        members = frappe.get_all(
            "Member",
            filters={"status": "Active"},
            fields=["name", "current_dues_schedule"],
            limit=batch_size,
            start=offset,
        )

        if not members:
            break

        total_members += len(members)

        # Build a single query to get all active schedules for this batch
        member_names = [m.name for m in members]

        # Get all active schedules for these members in one query
        schedules_data = frappe.db.sql(
            """
            SELECT
                member,
                name as schedule_name,
                creation
            FROM `tabMembership Dues Schedule`
            WHERE member IN %(members)s
                AND status = 'Active'
                AND is_template = 0
            ORDER BY member, creation DESC
        """,
            {"members": member_names},
            as_dict=True,
        )

        # Group schedules by member
        schedules_by_member = {}
        for sched in schedules_data:
            if sched.member not in schedules_by_member:
                schedules_by_member[sched.member] = sched.schedule_name

        # Update members in this batch
        for member in members:
            try:
                correct_schedule = schedules_by_member.get(member.name)

                if correct_schedule and member.current_dues_schedule != correct_schedule:
                    # Schedule exists and needs updating
                    frappe.db.set_value("Member", member.name, "current_dues_schedule", correct_schedule)
                    members_updated += 1

                elif not correct_schedule and member.current_dues_schedule:
                    # No active schedule but member has one set - clear it
                    frappe.db.set_value("Member", member.name, "current_dues_schedule", None)
                    members_updated += 1

            except Exception as e:
                errors.append(f"Error updating {member.name}: {str(e)}")

        # Note: No explicit commit here - let the calling code manage transaction boundaries
        # This prevents issues when this function is called within a larger transaction

        # Move to next batch
        offset += batch_size

        # Log progress for long-running updates
        if total_members % 500 == 0 and total_members > 0:
            elapsed = time.time() - start_time
            frappe.logger().info(
                f"Dues schedule sync progress: {total_members} members checked, "
                f"{members_updated} updated, {elapsed:.2f}s elapsed"
            )

    # Calculate final metrics
    total_time = time.time() - start_time

    # Log summary
    frappe.logger().info(
        f"Dues schedule sync completed: {total_members} members checked, "
        f"{members_updated} updated in {total_time:.2f}s"
    )

    # Return detailed summary
    return {
        "members_checked": total_members,
        "members_updated": members_updated,
        "errors": errors,
        "execution_time": total_time,
        "avg_time_per_member": total_time / total_members if total_members > 0 else 0,
        "batch_size": batch_size,
    }


def run_bulk_sync_with_transaction(batch_size=100):
    """
    Wrapper function to run bulk sync with proper transaction management.
    Use this when calling from scheduled jobs or manual triggers.

    Args:
        batch_size (int): Number of members to process in each batch

    Returns:
        dict: Summary of the update operation
    """
    try:
        # Start a new transaction
        frappe.db.begin()

        # Run the sync
        result = check_and_update_all_members_current_schedule(batch_size)

        # Commit if successful
        frappe.db.commit()

        frappe.logger().info(f"Bulk sync completed successfully: {result}")
        return result

    except Exception as e:
        # Rollback on error
        frappe.db.rollback()
        frappe.log_error(f"Bulk sync failed: {str(e)}", "Dues Schedule Bulk Sync Error")
        raise
