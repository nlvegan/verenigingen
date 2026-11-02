"""Seed Verenigingen Email Configuration with a row for every registry key (#1959).

A key with no row counts as DISABLED (``is_notification_enabled`` is False), so on a fresh
install, where patches.txt is not run, every alert sent with a ``notification_key`` was skipped
silently. This is the same row "Sync Registry" adds, minus the dialog.
"""

import frappe

from verenigingen.notification_registry import DEFAULT_COOLDOWN_MINUTES
from verenigingen.utils.constants import Roles


def ensure_notification_registry_rows():
    """Add an enabled row for each registry key that has none. Existing rows are left alone."""
    if not frappe.db.exists("DocType", "Verenigingen Email Configuration"):
        return

    from verenigingen.notification_registry import NOTIFICATION_KEYS

    config = frappe.get_single("Verenigingen Email Configuration")
    existing = {nt.notification_key for nt in config.notification_types}
    missing = [key for key in NOTIFICATION_KEYS if key not in existing]
    for key in missing:
        config.append("notification_types", _registry_row(key, NOTIFICATION_KEYS[key]))

    if missing:
        config.flags.ignore_permissions = True
        config.save()


def _registry_row(key, meta):
    row = {
        "notification_key": key,
        "label": meta["label"],
        "category": meta["category"],
        "description": meta["description"],
        "priority": meta["priority"],
        "recipient_policy": meta["recipient_policy"],
        "cooldown_minutes": meta.get("cooldown_minutes", DEFAULT_COOLDOWN_MINUTES),
        "enabled": 1,
    }
    if meta["recipient_policy"] == "Role-Based":
        # Role-Based with the roles field empty makes get_recipients_for_notification raise
        # (.split on None), so name the admin roles until someone configures others.
        row["recipient_roles"] = ", ".join(sorted(Roles.ADMIN_PAIR))
    return row
