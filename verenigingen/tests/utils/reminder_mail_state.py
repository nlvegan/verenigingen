"""Put the notification state a payment-reminder test relies on into a known shape.

A reminder is only counted as sent when EmailService really queued it (#2015). That makes
three pieces of state matter that a skipped-counted-as-sent run used to hide: the registry
row for the key must exist and be enabled, the master switch must be on, and the per-recipient
cooldown (a Redis key, which a test rollback does NOT undo) must be clear. Tests that remind a
fixed address (e.g. ``overdue.member@example.com``) would otherwise be silenced by whichever
test reminded it first.
"""

import frappe


def clear_email_cooldowns():
    # get_keys() returns already-namespaced keys and delete_value() namespaces again, so
    # get_keys + delete_value deletes nothing; delete_keys() is the pair that works.
    frappe.cache().delete_keys("email_cooldown:*")


def ensure_outgoing_email_account(testcase):
    """A default outgoing Email Account, so a send is queued rather than refused.

    The code under test commits, so a created account would outlive the test and hand every
    later module in the shard an outgoing account (masking #1758/#1881). When this call
    creates the account, ``testcase`` is given a cleanup that deletes it and commits.
    """
    if frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
        return
    account = frappe.get_doc(
        {
            "doctype": "Email Account",
            "email_account_name": "Test Outgoing",
            "email_id": "test-outgoing@example.com",
            "enable_outgoing": 1,
            "default_outgoing": 1,
            "smtp_server": "localhost",
            "smtp_port": 25,
            "login_id_is_different": 0,
        }
    )
    account.flags.ignore_validate = True
    account.flags.ignore_mandatory = True
    account.insert()

    def _cleanup_created_email_account():
        frappe.delete_doc("Email Account", account.name, force=True)
        frappe.db.commit()

    testcase.addCleanup(_cleanup_created_email_account)


def configure_notification_key(key, enabled, cooldown_minutes):
    """Set one notification key's enable switch and cooldown on the email configuration."""
    config = frappe.get_single("Verenigingen Email Configuration")
    row = next(nt for nt in config.notification_types if nt.notification_key == key)
    row.enabled = enabled
    row.cooldown_minutes = cooldown_minutes
    config.save()
