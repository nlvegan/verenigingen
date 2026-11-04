"""Let a test own the notification state its "the email was sent" claim depends on (#2010).

``EmailService`` reports a send it did not make (key disabled or unseeded, recipient in
cooldown, recipient opted out) as ``success=True`` with ``data["skipped"]``. A test that asserts
only success therefore passes without a mail ever being built, on whichever site has no
Email Notification Type row for its key. Local sites carry none, CI's fresh installs carry all of
them (#1998), so the same test checks different things in the two places.

``own_notification_keys`` makes the state the test's own: it seeds exactly the keys it names
(enabled, no cooldown), switches the master switch on, clears the Redis cooldown keys, and restores
the child rows afterwards. ``singleton_backup`` is not an option for the rows: it does not restore
child tables (#2029).
"""

import frappe

from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns

DOCTYPE = "Verenigingen Email Configuration"


def own_notification_keys(test, *keys):
    """Enable ``keys`` with no cooldown for ``test``; undo it (rows, master switch, cooldowns) afterwards."""
    from verenigingen.notification_registry import NOTIFICATION_KEYS
    from verenigingen.setup.notification_registry_setup import _registry_row

    config = frappe.get_single(DOCTYPE)
    snapshot = _snapshot_rows(config)
    master = config.master_email_enabled
    test.addCleanup(_restore_notification_rows, snapshot, master)

    config.set("notification_types", [r for r in config.notification_types if r.notification_key not in keys])
    for key in keys:
        row = _registry_row(key, NOTIFICATION_KEYS[key])
        row["cooldown_minutes"] = 0
        config.append("notification_types", row)
    config.master_email_enabled = 1
    config.save()
    clear_email_cooldowns()


def queued_mail_count(recipient):
    """Email Queue rows addressed to ``recipient``: what a real send leaves behind."""
    return frappe.db.count("Email Queue Recipient", {"recipient": recipient})


def _snapshot_rows(config):
    meta = frappe.get_meta("Email Notification Type")
    fields = [f.fieldname for f in meta.fields if f.fieldtype != "Section Break"]
    return [{f: r.get(f) for f in fields} for r in config.notification_types]


def _restore_notification_rows(snapshot, master):
    config = frappe.get_single(DOCTYPE)
    config.set("notification_types", snapshot)
    config.master_email_enabled = master
    config.save()
    clear_email_cooldowns()
