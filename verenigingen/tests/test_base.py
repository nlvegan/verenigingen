"""
Base test class for Verenigingen tests
Automatically mocks email sending to prevent real emails during tests
"""

import unittest
import frappe
from verenigingen.tests.test_utils import mock_email_sending, setup_test_environment, cleanup_test_data


class VerenigingenTestCase(unittest.TestCase):
    """Base test case with automatic email mocking and test data cleanup"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test class - runs once before all tests"""
        frappe.set_user("Administrator")
        frappe.flags.in_test = True
        frappe.flags.mute_emails = True
    
    def setUp(self):
        """Set up each test - runs before each test method"""
        # Set up test environment
        setup_test_environment()
        
        # Start email mocking
        self.email_mock = mock_email_sending()
        self.mock_email_queue = self.email_mock.__enter__()
        
        # Store test data for cleanup
        self.test_records = []
    
    def tearDown(self):
        """Clean up after each test"""
        # Stop email mocking
        self.email_mock.__exit__(None, None, None)
        
        # Clean up any test records created
        for doctype, name in self.test_records:
            try:
                if frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        
        # Rollback any uncommitted changes
        frappe.db.rollback()
    
    def track_test_record(self, doctype, name):
        """Track a test record for cleanup"""
        self.test_records.append((doctype, name))
    
    def assert_email_sent(self, to=None, subject_contains=None, count=None):
        """Assert that emails were sent matching criteria"""
        return self.mock_email_queue.assert_email_sent(to=to, subject_contains=subject_contains, count=count)
    
    def assert_no_emails_sent(self):
        """Assert that no emails were sent"""
        return self.mock_email_queue.assert_no_emails_sent()
    
    def get_sent_emails(self, to=None, subject_contains=None):
        """Get sent emails with optional filtering"""
        return self.mock_email_queue.get_sent_emails(to=to, subject_contains=subject_contains)