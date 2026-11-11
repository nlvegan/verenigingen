"""Register the ``mollie_forward_payment_staff_cancelled`` notification type (#2406).

A key that has no row in Verenigingen Email Configuration counts as DISABLED, so on an existing
site the staff alert for a Mollie payment delivered after staff cancelled its Payment Entry would
be skipped silently. A fresh install is seeded from the registry; this gives existing sites the
row. An existing row is never touched (an admin may have turned it off or set recipients).
"""

import frappe

from verenigingen.utils.constants import Roles

NOTIFICATION_KEY = "mollie_forward_payment_staff_cancelled"


def execute():
    if not frappe.db.exists("DocType", "Verenigingen Email Configuration"):
        return

    config = frappe.get_single("Verenigingen Email Configuration")
    if any(nt.notification_key == NOTIFICATION_KEY for nt in config.notification_types):
        return

    from verenigingen.notification_registry import DEFAULT_COOLDOWN_MINUTES, get_notification_meta

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
            "cooldown_minutes": meta.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES),
        },
    )
    config.flags.ignore_permissions = True
    config.save()
