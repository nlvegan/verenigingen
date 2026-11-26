"""Give the test process a default outgoing mail account, the way CI's site has one.

``frappe.sendmail`` raises ``OutgoingEmailError: Please setup default outgoing Email
Account`` when no enabled default outgoing account exists. Whether one exists is ambient
site state: CI's ``site_config.json`` (``.github/helper/db/mariadb.json``) carries
``mail_server`` / ``mail_login`` / ``auto_email_id``, which Frappe turns into an
outgoing account (``EmailAccount.find_from_config``); the local ``test_site_N`` sites
carry none, and only some of them happen to hold a DB Email Account (#1758).

This mirrors CI's mechanism instead of writing an Email Account row: it sets the same
``frappe.conf`` keys for the duration of one test class and only when the site has no
usable default outgoing account already, so it is a no-op wherever one exists. Nothing is
persisted, and nothing is sent: ``frappe.sendmail`` queues an Email Queue row and no
SMTP connection is opened unless a test sends with ``now=True``.

Scope, so nobody reads this as more than it is:

* It covers ``frappe.sendmail`` / ``EmailAccount.find_outgoing`` paths only.
  ``EmailService._has_active_email_account`` reads DB Email Account rows only, so a code
  path that checks it ("No active email account configured") is NOT fixed by this.
* It is applied in ``setUpClass`` of ``VereningingenTestCase`` and ``EnhancedTestCase``.
  Plain ``unittest.TestCase`` / bare ``FrappeTestCase`` classes (about 13 mail-related
  ones) get no cover.
"""

import frappe

# The values CI's .github/helper/db/mariadb.json uses.
_CI_MAIL_CONFIG = {
    "mail_server": "localhost",
    "mail_port": 2525,
    "mail_login": "test@example.com",
    "mail_password": "test",
    "auto_email_id": "test@example.com",
}


def ensure_outgoing_mail_account(test_class) -> None:
    """Make ``find_outgoing`` succeed for ``test_class``'s tests; undo it afterwards."""
    if _has_outgoing_account():
        return

    previous = {key: frappe.conf.get(key) for key in _CI_MAIL_CONFIG}
    for key, value in _CI_MAIL_CONFIG.items():
        frappe.conf[key] = value
    test_class.addClassCleanup(_restore_mail_config, previous)


def _has_outgoing_account() -> bool:
    """True when Frappe already resolves a default outgoing account for this site."""
    from frappe.email.doctype.email_account.email_account import EmailAccount

    # find_default_outgoing is uncached and returns a muted-mail dummy when mute_emails
    # is set, which also makes sendmail work, so no conf is needed then either.
    return bool(EmailAccount.find_default_outgoing())


def _restore_mail_config(previous: dict) -> None:
    for key, value in previous.items():
        if value is None:
            frappe.conf.pop(key, None)
        else:
            frappe.conf[key] = value
    # find_outgoing caches a config-derived account on frappe.local; drop it so a later
    # class that expects "no account" does not inherit this one's.
    frappe.local.outgoing_email_account = {}
