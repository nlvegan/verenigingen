"""Register the ``ponto_executed_on_cancelled_row`` notification type (#1848, #1907).

A key that has no row in Verenigingen Email Configuration counts as DISABLED, so without this
row the alert for a cancelled Ponto row that Ponto reports as executed would be skipped
silently. The row is Role-Based and names the admin roles, so the alert reaches them until
someone configures other recipients. (Role-Based with the roles field empty is not an option:
``get_recipients_for_notification`` calls ``.split`` on the stored None and raises.)
"""

import frappe

from verenigingen.utils.constants import Roles

NOTIFICATION_KEY = "ponto_executed_on_cancelled_row"


def execute():
    if not frappe.db.exists("DocType", "Verenigingen Email Configuration"):
        return

    config = frappe.get_single("Verenigingen Email Configuration")
    if any(nt.notification_key == NOTIFICATION_KEY for nt in config.notification_types):
        return

    from verenigingen.notification_registry import get_notification_meta

    meta = get_notification_meta(NOTIFICATION_KEY)
    config.append(
        "notification_types",
        {
            "notification_key": NOTIFICATION_KEY,
            "label": meta["label"],
            "category": meta["category"],
            "description": meta["description"],
            "priority": meta["priority"],
            "recipient_policy": meta["recipient_policy"],
            "recipient_roles": ", ".join(sorted(Roles.ADMIN_PAIR)),
            "enabled": 1,
            "cooldown_minutes": 0,
        },
    )
    config.flags.ignore_permissions = True
    config.save()
