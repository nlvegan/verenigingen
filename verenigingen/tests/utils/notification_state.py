"""Let a test own the notification state its "the email was sent" claim depends on (#2010).

``EmailService`` reports a send it did not make (key disabled or unseeded, recipient in
cooldown, recipient opted out) as ``success=True`` with ``data["skipped"]``. A test that asserts
only success therefore passes without a mail ever being built, on whichever site has no
Email Notification Type row for its key. Local sites carry none, CI's fresh installs carry all of
them (#1998), so the same test checks different things in the two places.

``own_notification_keys`` makes the state the test's own: it seeds exactly the keys it names
(enabled, cooldown 0, so Redis is never read), switches the master switch on, and restores the
child rows and the switch afterwards. ``singleton_backup`` restores child tables since #2091, but it
commits, so it would make a leak permanent; this helper restores uncommitted instead (#2029, #2159).

Caveat: the restore is uncommitted, like the seed, so the surrounding rollback undoes both. A
``frappe.db.commit()`` inside the test body (or in code it calls) makes the seed permanent for every
later class, and the uncommitted restore cannot undo it. The helper does not commit to work around
that; it notices the commit at cleanup and fails the test, so the leak is loud instead of silent.
"""

import frappe

DOCTYPE = "Verenigingen Email Configuration"


def own_notification_keys(test, *keys):
    """Enable ``keys`` with no cooldown for ``test``; undo it (rows, master switch) afterwards."""
    from verenigingen.notification_registry import NOTIFICATION_KEYS
    from verenigingen.setup.notification_registry_setup import _registry_row

    config = frappe.get_single(DOCTYPE)
    snapshot = _snapshot_rows(config)
    master = config.master_email_enabled
    committed = []
    frappe.db.before_commit.add(lambda: committed.append(True))  # runs on commit, dropped on rollback
    test.addCleanup(_restore_notification_rows, snapshot, master, committed)

    config.set("notification_types", [r for r in config.notification_types if r.notification_key not in keys])
    for key in keys:
        row = _registry_row(key, NOTIFICATION_KEYS[key])
        row["cooldown_minutes"] = 0
        config.append("notification_types", row)
    config.master_email_enabled = 1
    config.save()


def queued_mail_count(recipient):
    """Email Queue rows addressed to ``recipient``: what a real send leaves behind."""
    return frappe.db.count("Email Queue Recipient", {"recipient": recipient})


def _snapshot_rows(config):
    meta = frappe.get_meta("Email Notification Type")
    fields = [f.fieldname for f in meta.fields if f.fieldtype != "Section Break"]
    return [{f: r.get(f) for f in fields} for r in config.notification_types]


def _restore_notification_rows(snapshot, master, committed=()):
    config = frappe.get_single(DOCTYPE)
    config.set("notification_types", snapshot)
    config.master_email_enabled = master
    config.save()
    if committed:
        raise AssertionError(
            "frappe.db.commit() ran while own_notification_keys was active, so the seeded "
            "notification rows and master switch are now permanent for later tests; remove the "
            "commit from the test (or the code it calls) rather than from this check"
        )
