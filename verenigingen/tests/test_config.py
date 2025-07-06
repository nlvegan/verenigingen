"""
Global test configuration for Verenigingen
Sets up email mocking and other test settings
"""

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
    """Disable global email mocking"""
    global _original_sendmail
    if _original_sendmail:
        frappe.sendmail = _original_sendmail
        _original_sendmail = None


# Auto-enable email mocking when this module is imported in test context
if hasattr(frappe, 'flags') and frappe.flags.get('in_test'):
    enable_test_email_mocking()