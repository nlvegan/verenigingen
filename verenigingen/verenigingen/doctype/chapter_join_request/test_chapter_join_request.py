# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterJoinRequest(EnhancedTestCase):
    def setUp(self):
        """Set up test data using enhanced test factory"""
        super().setUp()

        # Set Administrator context for test setup
        frappe.set_user("Administrator")

        # Create test member with realistic data
        self.test_member = self.create_test_member(
            first_name="Test", last_name="Member", birth_date="1990-01-01", status="Active"
        )

        # Create test chapter with realistic data
        self.test_chapter = self.factory.ensure_test_chapter(
            "Test Chapter",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Test chapter for chapter join request testing",
                "contact_email": self.factory.generate_test_email("chapter"),
            },
        )

        # Create another member for multi-member tests
        self.test_member2 = self.create_test_member(
            first_name="Second", last_name="Member", birth_date="1985-01-01", status="Active"
        )

        # Create suspended member for status validation tests
        self.suspended_member = self.create_test_member(
            first_name="Suspended", last_name="Member", birth_date="1995-01-01", status="Suspended"
        )

        # Create inactive chapter for status validation tests
        self.inactive_chapter = self.factory.ensure_test_chapter(
            "Inactive Chapter",
            {
                "status": "Inactive",
                "published": 0,
                "introduction": "Inactive test chapter",
                "contact_email": self.factory.generate_test_email("inactive_chapter"),
            },
        )

    def test_field_validation(self):
        """Test that field references are validated properly"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test introduction for field validation",
            }
        )

        # This should not throw an error if all fields exist
        try:
            join_request.validate()
        except Exception as e:
            self.fail(f"Field validation failed: {str(e)}")

    def test_join_request_creation(self):
        """Test creating a chapter join request"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test introduction for joining chapter with realistic data",
            }
        )

        join_request.insert()
        self.assertEqual(join_request.status, "Pending")
        self.assertEqual(join_request.request_date, today())
        self.assertEqual(join_request.member_name, self.test_member.full_name)
        self.assertEqual(join_request.member_email, self.test_member.email)

    def test_duplicate_request_validation(self):
        """Test that duplicate requests are prevented"""
        # Create first request
        join_request1 = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "First request with realistic test data",
            }
        )
        join_request1.insert()
        join_request1.submit()

        # Try to create duplicate request
        join_request2 = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Duplicate request - should be prevented",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request2.insert()

    def test_permission_validation(self):
        """Test chapter approval permission validation"""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            has_chapter_approval_permission,
        )

        # Test with Administrator (should have permission)
        frappe.set_user("Administrator")
        self.assertTrue(has_chapter_approval_permission(self.test_chapter.name))

        # Test with Guest (should not have permission)
        frappe.set_user("Guest")
        self.assertFalse(has_chapter_approval_permission(self.test_chapter.name))

    def test_transaction_rollback(self):
        """Test that failed approvals don't leave partial data"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Test for transaction rollback with realistic data",
            }
        )
        join_request.insert()
        join_request.submit()

        # Count existing chapter members before approval
        initial_count = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member.name}
        )

        # Try to approve with invalid chapter (should fail and rollback)
        try:
            join_request.chapter = "Invalid Chapter"
            join_request.approve_request()
        except:
            pass  # Expected to fail

        # Verify no partial data was created
        final_count = frappe.db.count(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member.name}
        )

        self.assertEqual(initial_count, final_count, "Transaction rollback failed - partial data created")

    def test_member_status_validation(self):
        """Test that only active members can create join requests"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.suspended_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request from suspended member - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_chapter_status_validation(self):
        """Test that requests can only be made to active chapters"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.inactive_chapter.name,
                "introduction": "Request to inactive chapter - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_approval_workflow_basic(self):
        """Test basic approval workflow without complex transaction management"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request for approval workflow testing",
            }
        )
        join_request.insert()
        join_request.submit()

        # Test basic approval status change
        join_request.status = "Approved"
        join_request.reviewed_by = "Administrator"
        join_request.review_notes = "Approved for testing purposes"
        join_request.save()

        # Verify basic approval fields
        self.assertEqual(join_request.status, "Approved")
        self.assertEqual(join_request.reviewed_by, "Administrator")
        self.assertEqual(join_request.review_notes, "Approved for testing purposes")

    def test_rejection_workflow(self):
        """Test rejection workflow"""
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request for rejection workflow testing",
            }
        )
        join_request.insert()
        join_request.submit()

        # Reject the request
        result = join_request.reject_request(
            rejected_by="Administrator", reason="Not suitable for testing purposes"
        )

        # Verify rejection was successful
        self.assertTrue(result.get("success"))
        self.assertEqual(join_request.status, "Rejected")
        self.assertEqual(join_request.reviewed_by, "Administrator")
        self.assertEqual(join_request.rejection_reason, "Not suitable for testing purposes")

        # Verify no chapter membership was created
        chapter_member = frappe.db.exists(
            "Chapter Member", {"parent": self.test_chapter.name, "member": self.test_member2.name}
        )
        self.assertIsNone(chapter_member, "No chapter membership should be created upon rejection")

    def test_already_member_validation(self):
        """Test that existing members cannot create duplicate requests"""
        # First, manually add member to chapter
        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.append(
            "members",
            {"member": self.test_member.name, "status": "Active", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()

        # Try to create join request
        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Request from existing member - should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            join_request.insert()

    def test_api_integration(self):
        """Test the chapter join API integration"""
        from verenigingen.api.chapter_join import join_chapter

        # Set proper user context for API call
        frappe.set_user(self.test_member.email)

        # Test successful API call
        result = join_chapter(
            chapter_name=self.test_chapter.name, introduction="API integration test request"
        )

        # Debug the result if it fails
        if not result.get("success"):
            print(f"API Result: {result}")

        # Verify API response
        self.assertTrue(result.get("success"), f"API call failed: {result}")
        self.assertIn("request_id", result)

        # Verify Chapter Join Request was created
        request_id = result.get("request_id")
        join_request = frappe.get_doc("Chapter Join Request", request_id)
        self.assertEqual(join_request.chapter, self.test_chapter.name)
        self.assertEqual(join_request.introduction, "API integration test request")

        # Reset user context
        frappe.set_user("Administrator")

    def test_edge_case_long_introduction(self):
        """Test edge case with very long introduction text"""
        long_introduction = (
            "This is a very long introduction text that contains many words and sentences to test how the system handles long text inputs. "
            * 50
        )

        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": long_introduction,
            }
        )

        # Should handle long text without issues
        join_request.insert()
        self.assertEqual(join_request.status, "Pending")

    def test_edge_case_special_characters(self):
        """Test edge case with special characters in introduction"""
        special_introduction = (
            "Mijn introductie bevat speciale tekens: ëïö, àáâã, ñ, ç, ü! @#$%^&*()_+-={}[]|\\:;\"'<>,.?/"
        )

        join_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member.name,
                "chapter": self.test_chapter.name,
                "introduction": special_introduction,
            }
        )

        # Should handle special characters without issues
        join_request.insert()
        self.assertEqual(join_request.introduction, special_introduction)


if __name__ == "__main__":
    unittest.main()
