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

        # Unique per test: ensure_test_chapter() is a get-or-create keyed on the
        # document name, and this class both appends roster rows and flips the
        # chapter's status. "Test Chapter" was claimed by four files and
        # "Inactive Chapter" by two, so whichever ran first owned the row (#533).
        # Every use below goes through .name, so there is no literal to break.
        self.test_chapter = self.factory.ensure_test_chapter(
            f"Test Chapter {frappe.generate_hash(length=6)}",
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
            f"Inactive Chapter {frappe.generate_hash(length=6)}",
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
        # TODO: This test requires proper security framework authentication
        # The has_chapter_approval_permission() function requires authentication
        # Error: "Authentication required for this endpoint"
        # Needs investigation of proper test user role setup for API security framework
        self.skipTest("API security framework authentication needs proper test user role configuration")

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

    def _pending_request_that_cannot_be_assigned(self, member):
        """A submitted Pending request whose approval's assignment step must fail (#1632).

        Real writers only (no set_value): the member is put in the chapter, then
        disable_chapter_memberships_safe disables the row, a request is submitted while the
        member is still Active, and suspend_member_safe suspends the member. Approval then
        reaches assign_member_to_chapter, which refuses to re-enable a suspended member's row.
        """
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
            suspend_member_safe,
        )

        chapter = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter.append(
            "members",
            {"member": member.name, "status": "Active", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()
        disable_chapter_memberships_safe(member.name, today(), "test leave")
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": member.name,
                "chapter": self.test_chapter.name,
                "introduction": "Rejoin while suspended",
            }
        )
        request.insert()
        request.submit()
        suspend_member_safe(member.name, "test suspension", suspend_user=False, suspend_teams=False)
        return request

    def _chapter_member_rows(self, member):
        return frappe.get_all(
            "Chapter Member",
            filters={"parent": self.test_chapter.name, "member": member.name},
            fields=["enabled", "status"],
        )

    def test_failed_assignment_leaves_request_pending_via_wrapper(self):
        """#1632: the wrapper swallows the failure, so the Approved save must not outlive it."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            approve_join_request,
        )

        self.expectErrorLog("Failed to approve join request")
        request = self._pending_request_that_cannot_be_assigned(self.test_member)

        result = approve_join_request(request.name)

        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", request.name, "status"), "Pending")
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member)], [0])

    def test_failed_assignment_raises_and_resets_in_memory_status(self):
        request = self._pending_request_that_cannot_be_assigned(self.test_member)
        doc = frappe.get_doc("Chapter Join Request", request.name)

        with self.assertRaises(frappe.ValidationError):
            doc.approve_request()

        self.assertEqual(doc.status, "Pending")
        self.assertIsNone(frappe.db.get_value("Chapter Join Request", request.name, "reviewed_by"))

    def test_bulk_approve_one_failure_keeps_the_successes(self):
        """#1632: in bulk, a failing request is undone alone; its siblings stay Approved."""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        bad = self._pending_request_that_cannot_be_assigned(self.test_member)
        good = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Healthy request",
            }
        )
        good.insert()
        good.submit()

        bulk_approve_requests([good.name, bad.name])
        self._assert_good_approved_bad_pending(good, bad)

    def _assert_good_approved_bad_pending(self, good, bad):
        self.assertEqual(frappe.db.get_value("Chapter Join Request", good.name, "status"), "Approved")
        self.assertTrue(frappe.db.get_value("Chapter Join Request", good.name, "reviewed_by"))
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member2)], [1])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", bad.name, "status"), "Pending")
        self.assertIsNone(frappe.db.get_value("Chapter Join Request", bad.name, "reviewed_by"))
        self.assertEqual([r.enabled for r in self._chapter_member_rows(self.test_member)], [0])

    def test_bulk_approve_failing_request_first_keeps_the_successes(self):
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            bulk_approve_requests,
        )

        bad = self._pending_request_that_cannot_be_assigned(self.test_member)
        good = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Healthy request",
            }
        )
        good.insert()
        good.submit()

        bulk_approve_requests([bad.name, good.name])
        self._assert_good_approved_bad_pending(good, bad)

    def test_lock_timeout_during_assignment_leaves_request_pending(self):
        """#1632 review F1: a 1205 keeps the transaction live, so it must be rolled back too."""
        from unittest.mock import patch  # Mock justified: injects the DB error no fixture can produce

        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            approve_join_request,
        )

        self.expectErrorLog("Failed to approve join request")
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.test_member2.name,
                "chapter": self.test_chapter.name,
                "introduction": "Timeout request",
            }
        )
        request.insert()
        request.submit()

        target = (
            "verenigingen.services.chapter.chapter_membership_manager."
            "ChapterMembershipManager.assign_member_to_chapter"
        )
        with patch(target, side_effect=frappe.QueryTimeoutError("1205")):
            result = approve_join_request(request.name)

        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.get_value("Chapter Join Request", request.name, "status"), "Pending")

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
        chapter.reload()  # Ensure fresh data

        # Ensure Department sync is up to date (may have been created by previous test)
        chapter._sync_department()

        # Clear any members from previous tests (no per-method rollback)
        chapter.members = []

        # Verify member exists before adding
        if not frappe.db.exists("Member", self.test_member.name):
            self.fail(f"Test member {self.test_member.name} does not exist")

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
        # TODO: This test requires proper security framework authentication
        # The API requires medium security level but test user has only Guest role
        # Error: "Access denied. Required security level: medium. Your access: Individual roles: All, Guest"
        # Needs investigation of proper test user role setup for API security framework
        self.skipTest("API security framework authentication needs proper test user role configuration")

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
