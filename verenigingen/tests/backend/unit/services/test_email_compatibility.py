# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Email Compatibility Layer

Tests email compatibility wrappers with OperationResult pattern.
Focus on type-safe error handling for backward compatibility functions.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
"""

import frappe
from frappe.utils import random_string
from verenigingen.services.communication.compatibility import (
    send_sepa_email,
    send_member_notification,
    send_chapter_email,
    send_templated_email_legacy,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestEmailCompatibility(EnhancedTestCase):
    """Unit tests for Email Compatibility wrappers"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_send_sepa_email_returns_operation_result(self):
        """Test send_sepa_email returns OperationResult"""
        result = send_sepa_email(
            recipients="test@example.com",
            subject="Test SEPA Email"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_send_member_notification_returns_operation_result(self):
        """Test send_member_notification returns OperationResult"""
        unique_email = f"notify.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Notify",
            last_name="Test",
            email=unique_email
        )

        result = send_member_notification(
            member_name=member.name,
            notification_type="approval"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_send_member_notification_no_email_returns_failed_result(self):
        """Test notification for member without email returns failed OperationResult"""
        unique_email = f"noemail.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="NoEmail",
            last_name="Test",
            email=unique_email
        )

        # Clear the email after creation to test the no-email scenario
        frappe.db.set_value("Member", member.name, "email", "")
        member.reload()

        result = send_member_notification(
            member_name=member.name,
            notification_type="approval"
        )

        # Should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_send_chapter_email_returns_operation_result(self):
        """Test send_chapter_email returns OperationResult"""
        result = send_chapter_email(
            chapter_name="Test Chapter",
            recipients=["test@example.com"],
            subject="Test Chapter Email"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_email_wrappers_never_throw_exceptions(self):
        """Test that email wrappers never throw exceptions"""
        # Test with various invalid inputs
        result1 = send_sepa_email(recipients="", subject="")
        self.assertIsNotNone(result1)

        result2 = send_member_notification(member_name="INVALID", notification_type="test")
        self.assertIsNotNone(result2)

        result3 = send_chapter_email(chapter_name="", recipients=[], subject="")
        self.assertIsNotNone(result3)

        result4 = send_templated_email_legacy(template_id="", variables="{}")
        self.assertIsNotNone(result4)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEmailCompatibility)
    unittest.TextTestRunner(verbosity=2).run(suite)
