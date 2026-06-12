# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Re-sync Contribution Amendment Requests whose Mollie sync silently died.

The sync gated on Member.mollie_mandate_id (never populated), so applied
amendments stayed at mollie_sync_status="In Progress" forever. With the
gate fixed, re-enqueue the LATEST stuck amendment per member (so an older
amount cannot overwrite a newer one) and mark older stuck ones Skipped.
"""

import frappe


def partition_stuck_amendments(rows):
    """Split stuck amendments (ascending creation order) into
    (resync_names, skip_names): the latest per member is re-synced, older
    ones are skipped so a stale amount can never overwrite a newer one."""
    latest_per_member = {}
    for row in rows:  # ascending creation -> last write wins
        latest_per_member[row.member] = row.name
    resync = list(latest_per_member.values())
    skip = [row.name for row in rows if row.name not in set(resync)]
    return resync, skip


def execute():
    stuck = frappe.get_all(
        "Contribution Amendment Request",
        filters={
            "status": "Applied",
            "mollie_sync_completed": 0,
            "mollie_sync_status": ["in", ["Queued", "In Progress", "Failed"]],
        },
        fields=["name", "member"],
        order_by="creation asc",
    )
    if not stuck:
        return

    resync, skip = partition_stuck_amendments(stuck)

    for name in skip:
        frappe.db.set_value(
            "Contribution Amendment Request",
            name,
            "mollie_sync_status",
            "Skipped",
            update_modified=False,
        )

    for name in resync:
        frappe.db.set_value(
            "Contribution Amendment Request",
            name,
            "mollie_sync_status",
            "Not Started",
            update_modified=False,
        )
        frappe.enqueue(
            "verenigingen.verenigingen_payments.mollie.events.amendment_events.sync_mollie_subscription_on_amendment_applied",
            queue="default",
            timeout=60,
            doc={"doctype": "Contribution Amendment Request", "name": name},
            is_async=True,
            job_name=f"mollie_sync_{name}",
            job_id=f"mollie_sync_resync_{name}",
            deduplicate=True,
            enqueue_after_commit=True,
        )

    frappe.db.commit()
    print(f"Re-enqueued Mollie sync for {len(resync)} amendment(s), skipped {len(skip)} older one(s)")
