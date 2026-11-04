"""
Global test configuration for Verenigingen
Sets up email mocking and other test settings
"""

from contextlib import contextmanager

import frappe
from unittest.mock import patch


def setup_global_test_config():
    """Set up global test configuration including email mocking"""
    # Set test flags
    frappe.flags.in_test = True
    frappe.flags.mute_emails = True
    
    # Disable actual email sending
    frappe.conf.disable_email_sending = True
    
    # Clear email queue
    if frappe.db:
        try:
            frappe.db.delete("Email Queue")
            frappe.db.commit()
        except Exception:
            pass


# Monkey patch frappe.sendmail to prevent emails during any test
_original_sendmail = None


def mock_sendmail(*args, **kwargs):
    """Mock sendmail that does nothing"""
    # Log the email that would have been sent (for debugging)
    if frappe.flags.in_test:
        recipients = kwargs.get('recipients', args[0] if args else None)
        subject = kwargs.get('subject', args[2] if len(args) > 2 else 'No subject')
        print(f"[TEST MODE] Email blocked: To={recipients}, Subject={subject}")
    return None


def enable_test_email_mocking():
    """Enable global email mocking for tests"""
    global _original_sendmail
    if not _original_sendmail:
        _original_sendmail = frappe.sendmail
        frappe.sendmail = mock_sendmail


def disable_test_email_mocking():
    """Disable global email mocking.

    Returns whether mocking WAS on, to hand to ``restore_test_email_mocking``. Cleaning up with
    ``enable_test_email_mocking`` instead forces the mock on in a process that had it off, and
    every later test then sees no Email Queue row (#2060).
    """
    global _original_sendmail
    was_mocked = _original_sendmail is not None
    if was_mocked:
        frappe.sendmail = _original_sendmail
        _original_sendmail = None
    return was_mocked


def restore_test_email_mocking(was_mocked):
    """Put mocking back as ``disable_test_email_mocking`` found it: on only if it was on."""
    if was_mocked:
        enable_test_email_mocking()


@contextmanager
def email_mocking_disabled():
    was_mocked = disable_test_email_mocking()
    try:
        yield
    finally:
        restore_test_email_mocking(was_mocked)


# No import-time enable (#2060): importing this module from a test file is collection, not a
# request to mock. The old auto-enable ran inside whichever module imported it first, so a
# disable/restore pair around a real send then "restored" a mock nobody had asked for, and every
# later module in the process saw no Email Queue rows. boot.py enables explicitly where wanted.
