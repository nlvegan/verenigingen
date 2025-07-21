"""
Test to verify email mocking is working correctly
"""

import unittest
import frappe
from verenigingen.tests.test_base import VerenigingenTestCase
from verenigingen.tests.test_utils import TestDataFactory


class TestEmailMocking(VerenigingenTestCase):
    """Test that email mocking prevents real emails from being sent"""
    
    def test_membership_application_no_real_emails(self):
        """Test that membership applications don't send real emails"""
        # Create a test member application
        test_member = TestDataFactory.create_test_member(
            first_name="EmailTest",
            last_name="NoSend",
            email="test-no-send@example.com",
            application_status="Pending"
        )
        self.track_test_record("Member", test_member.name)
        
        # Import the function that normally sends emails
        from verenigingen.verenigingen.web_form.membership_application import send_application_notifications
        
        # Call the notification function
        send_application_notifications(test_member)
        
        # Verify emails were captured but not actually sent
        emails = self.get_sent_emails(subject_contains="New Membership Application")
        self.assertGreater(len(emails), 0, "Should have captured at least one email")
        
        # Verify the email contains expected content
        email = emails[0]
        self.assertIn(test_member.full_name, email['subject'])
        self.assertIn(test_member.email, email['message'])
        
        print(f"✅ Successfully captured {len(emails)} emails without sending")
    
    def test_direct_sendmail_is_mocked(self):
        """Test that direct frappe.sendmail calls are mocked"""
        # Try to send an email directly
        frappe.sendmail(
            recipients=["test-direct@example.com"],
            subject="Test Direct Email",
            message="This should be mocked and not sent"
        )
        
        # Verify it was captured
        emails = self.get_sent_emails(to="test-direct@example.com")
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0]['subject'], "Test Direct Email")
        
        print("✅ Direct sendmail calls are properly mocked")
    
    def test_no_emails_sent_without_sendmail(self):
        """Test that no emails are sent when sendmail is not called"""
        # Create a member without triggering notifications
        test_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Silent",
            "last_name": "Test",
            "email": "silent-test@example.com",
            "status": "Active"
        })
        test_member.insert()
        self.track_test_record("Member", test_member.name)
        
        # Verify no emails were sent
        self.assert_no_emails_sent()
        
        print("✅ No emails sent when not triggered")


if __name__ == "__main__":
    # Run the test
    frappe.connect()
    frappe.set_user("Administrator")
    
    # Set test flags
    frappe.flags.in_test = True
    
    # Run tests
    unittest.main()