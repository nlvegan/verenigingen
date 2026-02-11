"""Backfill change_tags on existing MijnRood Sync Events.

Events created before the change_tags field was added will have NULL values.
This patch computes tags from event_type, mijnrood_table, and changed_fields JSON.
"""

import json

import frappe

from verenigingen.mijnrood_sync.services.polling_service import compute_change_tags


def execute():
    events = frappe.get_all(
        "MijnRood Sync Event",
        filters={"change_tags": ["is", "not set"]},
        fields=["name", "event_type", "mijnrood_table", "changed_fields"],
    )

    if not events:
        return

    for ev in events:
        changed = None
        if ev.changed_fields:
            try:
                changed = json.loads(ev.changed_fields)
            except (json.JSONDecodeError, ValueError):
                changed = None

        tags = compute_change_tags(ev.event_type, ev.mijnrood_table, changed)
        if tags:
            frappe.db.set_value("MijnRood Sync Event", ev.name, "change_tags", tags, update_modified=False)

    frappe.db.commit()
