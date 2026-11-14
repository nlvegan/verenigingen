"""Cancel the dues schedules a docstatus-2 Membership cancel left Paused (#2134).

Membership.on_cancel used to pause the member's schedule; it now cancels it. A schedule left Paused
by an earlier cancel stays billing-dead and, being Paused, blocks the member's next schedule.

Only those are moved. The discriminator is two facts that must BOTH hold: the schedule's notes carry
the line the old on_cancel wrote, "Membership <the schedule's own membership> cancelled on <date>",
and that Membership is docstatus 2. A schedule paused by staff ("Member requested pause", a payment
plan, ...) has neither, and a Paused schedule whose Membership is still live is not a cancel's leftover.
Idempotent: a moved schedule is no longer Paused.
"""

import re

import frappe


def execute():
    paused = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Paused",
            "is_template": 0,
            "membership": ["is", "set"],
            "notes": ["like", "%cancelled on%"],
        },
        fields=["name", "membership", "notes"],
    )
    for schedule in paused:
        if not _paused_by_membership_cancel(schedule):
            continue
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule.name,
            {
                "status": "Cancelled",
                "notes": (
                    f"{schedule.notes}\n\nCancelled: Membership {schedule.membership} was cancelled (#2134)"
                ),
            },
        )


def _paused_by_membership_cancel(schedule):
    date = r"\d{4}-\d{2}-\d{2}"
    old_note = rf"Paused on {date}: Membership {re.escape(schedule.membership)} cancelled on {date}"
    if not re.search(old_note, schedule.notes or ""):
        return False
    return frappe.db.get_value("Membership", schedule.membership, "docstatus") == 2
