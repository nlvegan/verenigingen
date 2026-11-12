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
# The keys the payment-reminder API tests send through (#2053).
PAYMENT_REMINDER_KEYS = ("payment_reminder_friendly", "payment_reminder_urgent", "payment_failure")


def own_notification_keys(test, *keys):
    """Enable ``keys`` with no cooldown for ``test``; undo it (rows, master switch) afterwards."""
    from verenigingen.notification_registry import NOTIFICATION_KEYS
    from verenigingen.setup.notification_registry_setup import _registry_row

    config = frappe.get_single(DOCTYPE)
    snapshot = snapshot_notification_rows()
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


def snapshot_notification_rows():
    """Raw copy of the Email Notification Type rows, names and timestamps included."""
    return frappe.get_all(
        "Email Notification Type",
        filters=_row_filters(),
        fields=["*"],
        order_by="idx asc",
        limit_page_length=0,
    )


def restore_notification_rows(rows):
    """Put a ``snapshot_notification_rows`` copy back UNCOMMITTED, byte for byte (#2159).

    For a test whose own body does not commit (or whose commit is the harness's, at teardown): the
    surrounding rollback then undoes the edit and this restore leaves nothing behind. Re-saving the
    document instead (``config.set(...)`` + ``save()``) mints new row names and ``modified`` stamps,
    and the harness's drain commit made those permanent: the rows kept their content and lost their
    identity on every run. ``singleton_backup`` restores byte for byte too, but it COMMITS, which
    would also make permanent whatever else the test left uncommitted; use it where the test commits.
    """
    from verenigingen.tests.fixtures.enhanced_test_factory import suspend_insert_capture

    frappe.db.delete("Email Notification Type", _row_filters())
    if rows:
        frappe.db.delete("Email Notification Type", {"name": ("in", [r["name"] for r in rows])})
    with suspend_insert_capture():
        for row in rows:
            frappe.get_doc({**row, "doctype": "Email Notification Type"}).db_insert()
    frappe.clear_document_cache(DOCTYPE, DOCTYPE)


def _row_filters():
    return {"parent": DOCTYPE, "parenttype": DOCTYPE, "parentfield": "notification_types"}


def queued_mail_count(recipient):
    """Email Queue rows addressed to ``recipient``: what a real send leaves behind."""
    return frappe.db.count("Email Queue Recipient", {"recipient": recipient})


def _restore_notification_rows(snapshot, master, committed=()):
    restore_notification_rows(snapshot)  # byte for byte: names and stamps too (#2159)
    frappe.db.set_single_value(DOCTYPE, "master_email_enabled", master)
    if committed:
        raise AssertionError(
            "frappe.db.commit() ran while own_notification_keys was active, so the seeded "
            "notification rows and master switch are now permanent for later tests; remove the "
            "commit from the test (or the code it calls) rather than from this check"
        )
