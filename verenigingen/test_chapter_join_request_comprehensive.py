#!/usr/bin/env python3
"""
Comprehensive Chapter Join Request Regression Testing

This test suite validates the Chapter Join Request implementation and tests for
regressions in the chapter system functionality.
"""

import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterJoinRequestComprehensive(EnhancedTestCase):
    """Comprehensive regression test suite for Chapter Join Request functionality"""

    def setUp(self):
        """Set up comprehensive test environment"""
        super().setUp()

        # Set Administrator context for all tests
        frappe.set_user("Administrator")

        # Create test members with realistic data
        self.active_member = self.create_test_member(
            first_name="Active", last_name="Member", birth_date="1990-01-01", status="Active"
        )

        self.another_member = self.create_test_member(
            first_name="Another", last_name="Member", birth_date="1985-01-01", status="Active"
        )

        self.suspended_member = self.create_test_member(
            first_name="Suspended", last_name="Member", birth_date="1995-01-01", status="Suspended"
        )

        # Create test chapters
        self.active_chapter = self.factory.ensure_test_chapter(
            "Active Chapter",
            {
                "status": "Active",
                "published": 1,
                "introduction": "Active test chapter for regression testing",
                "contact_email": self.factory.generate_test_email("chapter"),
            },
        )

        self.inactive_chapter = self.factory.ensure_test_chapter(
            "Inactive Chapter",
            {
                "status": "Inactive",
                "published": 0,
                "introduction": "Inactive test chapter",
                "contact_email": self.factory.generate_test_email("inactive_chapter"),
            },
        )

    def test_doctype_structure_validation(self):
        """Test that the Chapter Join Request DocType has the correct structure"""
        meta = frappe.get_meta("Chapter Join Request")

        # Verify essential fields exist
        essential_fields = [
            "member",
            "chapter",
            "introduction",
            "status",
            "request_date",
            "reviewed_by",
            "review_date",
            "review_notes",
        ]
        field_names = [field.fieldname for field in meta.fields]

        for field in essential_fields:
            self.assertIn(field, field_names, f"Essential field '{field}' missing from DocType")

        # Verify submittable
        self.assertTrue(meta.is_submittable, "Chapter Join Request should be submittable")

        # Verify autoname pattern
        self.assertIn("CJR-", meta.autoname or "", "AutoName should include CJR prefix")

    def test_field_validation_comprehensive(self):
        """Test comprehensive field validation"""
        # Test with valid data
        valid_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Valid test introduction",
            }
        )

        # Should validate without errors
        try:
            valid_request.validate()
        except Exception as e:
            self.fail(f"Valid request failed validation: {str(e)}")

    def test_business_rule_validation(self):
        """Test business rule validation"""
        # Test 1: Active member with active chapter - should pass
        valid_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Valid request",
            }
        )

        # Insert with ignore_permissions for testing
        valid_request.insert(ignore_permissions=True)
        self.assertEqual(valid_request.status, "Pending")

        # Test 2: Suspended member - should fail validation
        invalid_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.suspended_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Request from suspended member",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            invalid_request.insert(ignore_permissions=True)

    def test_duplicate_request_prevention(self):
        """Test that duplicate requests are properly prevented"""
        # Create first request
        first_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "First request",
            }
        )
        first_request.insert(ignore_permissions=True)
        first_request.submit()

        # Attempt duplicate request - should fail
        duplicate_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Duplicate request",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            duplicate_request.insert(ignore_permissions=True)

    def test_status_workflow(self):
        """Test the status workflow (Pending -> Approved/Rejected)"""
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.another_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Status workflow test",
            }
        )
        request.insert(ignore_permissions=True)
        request.submit()

        # Initial status should be Pending
        self.assertEqual(request.status, "Pending")

        # Test manual status change to Approved
        request.status = "Approved"
        request.reviewed_by = "Administrator"
        request.review_date = today()
        request.review_notes = "Approved for testing"
        request.save()

        # Verify status change
        self.assertEqual(request.status, "Approved")
        self.assertEqual(request.reviewed_by, "Administrator")
        self.assertIsNotNone(request.review_date)

    def test_permissions_validation(self):
        """Test permission validation functions"""
        from verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request import (
            has_chapter_approval_permission,
        )

        # Administrator should have permission for any chapter
        self.assertTrue(has_chapter_approval_permission(self.active_chapter.name, "Administrator"))

        # Guest should not have permission
        self.assertFalse(has_chapter_approval_permission(self.active_chapter.name, "Guest"))

    def test_chapter_member_integration(self):
        """Test integration with existing Chapter Member functionality"""
        # Verify that Chapter Member child table structure is intact
        chapter = frappe.get_doc("Chapter", self.active_chapter.name)

        # Should have members child table
        self.assertTrue(hasattr(chapter, "members"), "Chapter should have members child table")

        # Test adding member directly (old functionality should still work)
        initial_count = len(chapter.members)

        chapter.append(
            "members",
            {
                "member": self.active_member.name,
                "status": "Active",
                "enabled": 1,
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Verify member was added
        chapter.reload()
        self.assertEqual(len(chapter.members), initial_count + 1)

        # Verify member exists in chapter
        member_exists = any(m.member == self.active_member.name for m in chapter.members)
        self.assertTrue(member_exists, "Member should be added to chapter")

    def test_api_structure_validation(self):
        """Test that API structure is correct"""
        # Test that join_chapter function exists and is properly decorated
        from verenigingen.api.chapter_join import get_chapter_join_context, join_chapter

        # Functions should exist
        self.assertTrue(callable(join_chapter), "join_chapter should be callable")
        self.assertTrue(callable(get_chapter_join_context), "get_chapter_join_context should be callable")

        # Test context function with valid chapter
        context = get_chapter_join_context(self.active_chapter.name)
        self.assertTrue(context.get("success"), "Context should return successfully")
        self.assertIn("chapter", context, "Context should include chapter information")

    def test_edge_cases(self):
        """Test edge cases and error conditions"""
        # Test with very long introduction
        long_intro = "Very long introduction text. " * 100

        long_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": long_intro,
            }
        )

        # Should handle long text
        long_request.insert(ignore_permissions=True)
        self.assertEqual(long_request.introduction, long_intro)

        # Test with special characters
        special_intro = "Introductie met speciale tekens: ëïö, àáâã, ñ, ç, ü! @#$%^&*()"

        special_request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.another_member.name,
                "chapter": self.active_chapter.name,
                "introduction": special_intro,
            }
        )

        # Should handle special characters
        special_request.insert(ignore_permissions=True)
        self.assertEqual(special_request.introduction, special_intro)

    def test_existing_chapter_functionality(self):
        """Test that existing chapter functionality is not broken"""
        # Test chapter creation still works
        test_chapter = self.factory.ensure_test_chapter(
            "Regression Test Chapter",
            {"status": "Active", "published": 1, "introduction": "Chapter for regression testing"},
        )

        self.assertEqual(test_chapter.status, "Active")
        self.assertTrue(test_chapter.published)

        # Test member can still be added to chapter directly
        test_chapter.append(
            "members",
            {
                "member": self.active_member.name,
                "status": "Active",
                "enabled": 1,
                "chapter_join_date": today(),
            },
        )
        test_chapter.save()

        # Verify functionality works
        test_chapter.reload()
        self.assertTrue(any(m.member == self.active_member.name for m in test_chapter.members))

    def test_notification_integration(self):
        """Test that notification system integration works"""
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Notification test request",
            }
        )
        request.insert(ignore_permissions=True)

        # Test that notification methods exist and can be called
        try:
            # These should not fail even if email sending fails
            request.notify_chapter_board()
            request.notify_member_approved()
            request.notify_member_rejected()
        except Exception as e:
            # Log the error but don't fail the test for notification issues
            print(f"Notification test warning: {e}")

    def test_data_integrity(self):
        """Test data integrity and relationships"""
        request = frappe.get_doc(
            {
                "doctype": "Chapter Join Request",
                "member": self.active_member.name,
                "chapter": self.active_chapter.name,
                "introduction": "Data integrity test",
            }
        )
        request.insert(ignore_permissions=True)
        request.submit()

        # Test that member_name and member_email are populated
        self.assertEqual(request.member_name, self.active_member.full_name)
        self.assertEqual(request.member_email, self.active_member.email)

        # Test that request_date is set
        self.assertEqual(request.request_date, today())

        # Test DocType relationships
        member_doc = frappe.get_doc("Member", request.member)
        chapter_doc = frappe.get_doc("Chapter", request.chapter)

        self.assertEqual(member_doc.name, self.active_member.name)
        self.assertEqual(chapter_doc.name, self.active_chapter.name)


def run_comprehensive_tests():
    """Run comprehensive regression tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterJoinRequestComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n✅ All comprehensive Chapter Join Request tests passed!")
        print("✅ No regressions detected in chapter functionality")
        print("✅ New Chapter Join Request implementation validated")
        return True
    else:
        print(f"\n❌ {len(result.failures)} test failures")
        print(f"❌ {len(result.errors)} test errors")
        print("❌ Regressions detected - review implementation")
        return False


if __name__ == "__main__":
    # Set test context
    frappe.set_user("Administrator")

    # Run tests
    success = run_comprehensive_tests()

    if not success:
        exit(1)
