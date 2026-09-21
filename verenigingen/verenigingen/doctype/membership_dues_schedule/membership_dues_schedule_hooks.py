"""
Hooks for Membership Dues Schedule to keep Member.current_dues_schedule synchronized
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.utils.transaction_errors import release_savepoint_if_present, rollback_to_savepoint


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
            # Security: Cross-document update in hook context.
            # Must use db.set_value to update Member from Dues Schedule hook.
            # Full save() would trigger Member hooks causing potential recursion.
            # Transaction commit handled by calling code (doc_events).
            frappe.db.set_value("Member", doc.member, "current_dues_schedule", new_current)

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
        elif current_data.current_creation and getdate(doc.creation) > getdate(current_data.current_creation):
            should_be_current = True

        # Update if needed
        if should_be_current and current_data.current_dues_schedule != doc.name:
            # Security: Cross-document update in hook context.
            # Uses db.set_value to update Member from Dues Schedule hook.
            # Row-level locking (FOR UPDATE) prevents race conditions.
            # Transaction commit handled by calling code (doc_events).
            frappe.db.set_value("Member", doc.member, "current_dues_schedule", doc.name)

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
                    # Security: Bulk sync operation updating reference field.
                    # Uses db.set_value for performance (many members) and to avoid
                    # triggering validation hooks on each member individually.
                    # Transaction managed by run_bulk_sync_with_transaction() wrapper.
                    frappe.db.set_value("Member", member.name, "current_dues_schedule", correct_schedule)
                    members_updated += 1

                elif not correct_schedule and member.current_dues_schedule:
                    # Security: Same pattern - clearing stale reference in bulk.
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
    # #1143 / #1171 review: a frappe.db.begin() used to sit here. It raised
    # ImplicitCommitError against any connection with pending writes, so it
    # was deleted -- but deleting it alone was WRONG: the bare commit()/
    # rollback() below act on the WHOLE ambient connection, not just this
    # function's own writes. Pre-#1143, begin()'s crash meant those calls were
    # UNREACHABLE against a caller with pending writes; post-#1143-alone they
    # became reachable and would silently commit (or discard) someone else's
    # unrelated, unvalidated work. There is no row lock here, so a SAVEPOINT
    # is the correct tool: it scopes commit/rollback to this function's own
    # writes only, leaving any ambient pending work exactly as the caller
    # left it either way.
    savepoint_name = "run_bulk_sync_with_transaction_" + frappe.generate_hash(length=10)
    frappe.db.savepoint(savepoint_name)
    try:
        # Run the sync
        result = check_and_update_all_members_current_schedule(batch_size)

        # Release (not commit): never force an early commit of the ambient
        # transaction -- whatever the caller already had pending stays
        # pending, exactly as it would if this function had never run.
        release_savepoint_if_present(savepoint_name)

        frappe.logger().info(f"Bulk sync completed successfully: {result}")
        return result

    except Exception as e:
        # Roll back to the savepoint (not the whole connection) on error --
        # see the savepoint-creation comment above for why a bare
        # frappe.db.rollback() here would be wrong. Via the canonical helper
        # (#561): a hand-written frappe.db.rollback(save_point=...) can itself
        # raise 1305 if a 1213 deadlock or a nested commit already destroyed
        # the savepoint, which would replace `e` before the bare `raise`
        # below ever runs. This handler does not need a separate
        # `except NON_RESUMABLE_DB_ERRORS: raise` above it -- it already
        # re-raises unconditionally regardless of exception type, so no type
        # test is needed to decide whether to propagate.
        rollback_to_savepoint(savepoint_name)
        frappe.log_error(f"Bulk sync failed: {str(e)}", "Dues Schedule Bulk Sync Error")
        raise
