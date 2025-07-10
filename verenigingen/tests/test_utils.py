"""
Test utilities for Verenigingen test suite
Provides common test helpers including email mocking
"""

import frappe
from unittest.mock import Mock, patch
from contextlib import contextmanager
from frappe.tests.utils import FrappeTestCase


class BaseTestCase(FrappeTestCase):
    """Base test case for Verenigingen tests"""
    pass


class MockEmailQueue:
    """Mock email queue to capture emails without sending them"""
    
    def __init__(self):
        self.sent_emails = []
    
    def reset(self):
        """Reset the email queue"""
        self.sent_emails = []
    
    def sendmail(self, recipients=None, sender=None, subject=None, message=None, 
                 reference_doctype=None, reference_name=None, unsubscribe_param=None,
                 unsubscribe_method=None, attachments=None, content=None, 
                 send_after=None, now=False, **kwargs):
        """Mock sendmail function that captures email data"""
        email_data = {
            'recipients': recipients if isinstance(recipients, list) else [recipients],
            'sender': sender,
            'subject': subject,
            'message': message or content,
            'reference_doctype': reference_doctype,
            'reference_name': reference_name,
            'now': now,
            'attachments': attachments,
            **kwargs
        }
        self.sent_emails.append(email_data)
        return Mock(name="email_queue_doc")
    
    def get_sent_emails(self, to=None, subject_contains=None):
        """Get sent emails with optional filtering"""
        emails = self.sent_emails
        
        if to:
            emails = [e for e in emails if to in e.get('recipients', [])]
        
        if subject_contains:
            emails = [e for e in emails if subject_contains in (e.get('subject') or '')]
        
        return emails
    
    def assert_email_sent(self, to=None, subject_contains=None, count=None):
        """Assert that emails were sent matching criteria"""
        matching_emails = self.get_sent_emails(to=to, subject_contains=subject_contains)
        
        if count is not None:
            assert len(matching_emails) == count, \
                f"Expected {count} emails, but found {len(matching_emails)}"
        else:
            assert len(matching_emails) > 0, \
                f"No emails found matching criteria (to={to}, subject_contains={subject_contains})"
        
        return matching_emails
    
    def assert_no_emails_sent(self):
        """Assert that no emails were sent"""
        assert len(self.sent_emails) == 0, \
            f"Expected no emails, but {len(self.sent_emails)} were sent"


# Global email queue instance
mock_email_queue = MockEmailQueue()


@contextmanager
def mock_email_sending():
    """Context manager to mock email sending in tests"""
    mock_email_queue.reset()
    
    with patch('frappe.sendmail', side_effect=mock_email_queue.sendmail):
        with patch('frappe.core.doctype.email_queue.email_queue.send_one', return_value=None):
            with patch('frappe.email.queue.send', return_value=None):
                yield mock_email_queue


def setup_test_environment():
    """Set up common test environment"""
    frappe.set_user("Administrator")
    
    # Ensure we're in test mode
    if not frappe.flags.in_test:
        frappe.flags.in_test = True
    
    # Disable email sending globally for tests
    frappe.flags.mute_emails = True
    
    # Clear any existing email queue
    frappe.db.delete("Email Queue")
    frappe.db.commit()


def cleanup_test_data(*doctypes):
    """Clean up test data for specified doctypes"""
    for doctype in doctypes:
        # Delete test records
        test_records = frappe.get_all(
            doctype,
            filters=[
                ["name", "like", "TEST-%"],
                ["name", "like", "%-TEST-%"],
                ["name", "like", "%-test-%"]
            ],
            pluck="name"
        )
        
        for record in test_records:
            try:
                frappe.delete_doc(doctype, record, force=True, ignore_permissions=True)
            except Exception:
                pass
    
    frappe.db.commit()


class TestDataFactory:
    """Factory for creating test data"""
    
    @staticmethod
    def create_test_user(email=None, first_name="Test", last_name="User", roles=None):
        """Create a test user with specified roles"""
        if not email:
            email = f"test-{frappe.generate_hash(length=8)}@example.com"
        
        if frappe.db.exists("User", email):
            return frappe.get_doc("User", email)
        
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "new_password": "test_password_123",
            "roles": [{"role": role} for role in (roles or [])]
        })
        user.insert(ignore_permissions=True)
        return user
    
    @staticmethod
    def create_test_member(email=None, **kwargs):
        """Create a test member"""
        if not email:
            email = f"test-member-{frappe.generate_hash(length=8)}@example.com"
        
        member_data = {
            "doctype": "Member",
            "first_name": kwargs.get("first_name", "Test"),
            "last_name": kwargs.get("last_name", f"Member-{frappe.generate_hash(length=4)}"),
            "email": email,
            "status": kwargs.get("status", "Active"),
            "application_status": kwargs.get("application_status", "Approved"),
            "member_since": kwargs.get("member_since", frappe.utils.today()),
        }
        member_data.update(kwargs)
        
        member = frappe.get_doc(member_data)
        member.insert(ignore_permissions=True)
        return member


def with_test_cleanup(*doctypes):
    """Decorator to ensure test data cleanup after test execution"""
    def decorator(test_func):
        def wrapper(*args, **kwargs):
            try:
                return test_func(*args, **kwargs)
            finally:
                cleanup_test_data(*doctypes)
        return wrapper
    return decorator