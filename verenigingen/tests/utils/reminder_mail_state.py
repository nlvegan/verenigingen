"""Put the notification state a payment-reminder test relies on into a known shape.

A reminder is only counted as sent when EmailService really queued it (#2015). That makes
three pieces of state matter that a skipped-counted-as-sent run used to hide: the registry
row for the key must exist and be enabled, the master switch must be on, and the per-recipient
cooldown (a Redis key, which a test rollback does NOT undo) must be clear. Tests that remind a
fixed address (e.g. ``overdue.member@example.com``) would otherwise be silenced by whichever
test reminded it first.
"""

import frappe

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows


def clear_email_cooldowns():
    cache = frappe.cache()
    for key in cache.get_keys("email_cooldown:*"):
        cache.delete_value(key)


def allow_reminder_sends(keys=("payment_reminder_friendly", "payment_reminder_urgent", "payment_failure")):
    """Seed registry rows, switch email on, enable ``keys`` with no cooldown, clear cooldown keys."""
    ensure_notification_registry_rows()
    config = frappe.get_single("Verenigingen Email Configuration")
    config.master_email_enabled = 1
    for row in config.notification_types:
        if row.notification_key in keys:
            row.enabled = 1
            row.cooldown_minutes = 0
    config.save()
    clear_email_cooldowns()
