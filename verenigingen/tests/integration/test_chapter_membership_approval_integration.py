"""
Integration tests for chapter membership approval workflow.

Tests the actual code paths without mocking to verify:
1. No AttributeError when accessing chapter assignments
2. No duplicate chapter membership history entries
3. Correct status transitions from Pending to Active
"""

import frappe
from frappe.utils import today, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterMembershipApprovalIntegration(EnhancedTestCase):
    """Integration tests for chapter membership during member approval"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test chapter manually (Chapter uses autoname='prompt')
        chapter_name = f"Test Chapter {int(now_datetime().timestamp())}"
        self.test_chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": chapter_name
        })
        self.test_chapter.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Standard Member"):
            membership_type = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Standard Member",
                "amount": 25.0
            })
            membership_type.insert(ignore_permissions=True)
            frappe.db.commit()

    def test_member_approval_no_attribute_error(self):
        """
        Test that member approval doesn't throw AttributeError for chapter_assignments.

        This verifies the fix for the bug where member.py tried to access
        self.chapter_assignments which doesn't exist.
        """
        # Create pending member with application
        member = self.create_test_member(
            first_name="Test",
            last_name="ApprovalUser",
            email=f"test_approval_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member"
        )

        # Create pending chapter membership
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(
            chapter_member,
            "Should create pending chapter membership"
        )

        # Reload member to ensure we have fresh data
        member.reload()

        # This should NOT throw AttributeError about chapter_assignments
        try:
            # Simulate approval - create membership
            membership = member.create_membership_on_approval(
                create_invoice=False,  # Skip invoice creation to simplify test
                approval_fields={
                    "application_status": "Approved",
                    "status": "Active",
                    "reviewed_by": frappe.session.user,
                    "review_date": now_datetime(),
                    "member_since": today()
                }
            )

            # If we got here without AttributeError, test passes
            self.assertIsNotNone(membership, "Membership should be created")

        except AttributeError as e:
            if "chapter_assignments" in str(e):
                self.fail(
                    f"AttributeError with 'chapter_assignments': {e}\n"
                    "The fix to remove chapter_assignments access didn't work!"
                )
            else:
                # Re-raise if it's a different AttributeError
                raise

    def test_no_duplicate_chapter_membership_history(self):
        """
        Test that chapter membership history doesn't create duplicates.

        This verifies the fix where chapter_member.py on_update hook
        now passes status=self.status instead of defaulting to "Active",
        preventing duplicate entries.
        """
        # Create pending member
        member = self.create_test_member(
            first_name="Test",
            last_name="HistoryUser",
            email=f"test_history_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member"
        )

        # Create pending chapter membership
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # Reload and check initial history
        member.reload()
        initial_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]

        self.assertEqual(
            len(initial_history),
            1,
            f"Should have exactly 1 history entry after pending creation, got {len(initial_history)}"
        )

        self.assertEqual(
            initial_history[0].status,
            "Pending",
            "Initial history entry should have Pending status"
        )

        # Activate the chapter membership
        from verenigingen.utils.application_helpers import activate_pending_chapter_membership

        activate_pending_chapter_membership(member, self.test_chapter.name)

        # Reload and check final history
        member.reload()
        final_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]

        # Key assertion: Should still be 1 entry, just updated to Active
        self.assertEqual(
            len(final_history),
            1,
            f"Should have exactly 1 history entry after activation (status updated, not duplicated). "
            f"Got {len(final_history)} entries:\n"
            + "\n".join([f"  - Status: {h.status}, Type: {h.assignment_type}" for h in final_history])
        )

        self.assertEqual(
            final_history[0].status,
            "Active",
            "History entry should be updated to Active status"
        )

    def test_chapter_member_status_field_used_correctly(self):
        """
        Test that chapter_member.py on_update hook uses actual status field.

        Verifies that when a Chapter Member is created with status="Pending",
        the history entry also gets status="Pending" (not defaulting to "Active").
        """
        # Create member
        member = self.create_test_member(
            first_name="Test",
            last_name="StatusUser",
            email=f"test_status_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01"
        )

        # Manually create Chapter Member with Pending status using secure operations
        from verenigingen.utils.secure_operations import secure_document_operation

        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        chapter_doc.append("members", {
            "member": member.name,
            "chapter_join_date": today(),
            "enabled": 1,
            "status": "Pending"
        })

        result = secure_document_operation(
            operation="save",
            doc=chapter_doc,
            justification="Test chapter member status field usage",
            required_permissions=["Chapter:write"],
        )
        self.assertTrue(result.success, f"Should save chapter: {'; '.join(result.errors) if not result.success else ''}")

        # Check that history entry was created with Pending status
        member.reload()
        history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]

        self.assertEqual(len(history), 1, "Should create exactly 1 history entry")
        self.assertEqual(
            history[0].status,
            "Pending",
            "History entry should use the actual status='Pending' from Chapter Member record, "
            "not default to 'Active'"
        )

    def test_full_approval_workflow_integration(self):
        """
        End-to-end test of the full approval workflow.

        Tests the complete flow:
        1. Create pending member with chapter preference
        2. Create pending chapter membership
        3. Approve member
        4. Verify chapter membership activated
        5. Verify no duplicate history entries
        """
        # 1. Create pending member application
        member = self.create_test_member(
            first_name="Test",
            last_name="WorkflowUser",
            email=f"test_workflow_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member"
        )

        # 2. Create pending chapter membership (simulates application form)
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # 3. Verify initial state
        member.reload()
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        pending_members = [m for m in chapter_doc.members if m.member == member.name and m.status == "Pending"]

        self.assertEqual(len(pending_members), 1, "Should have 1 pending Chapter Member record")

        initial_history_count = len([
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ])
        self.assertEqual(initial_history_count, 1, "Should have 1 pending history entry")

        # 4. Approve member (simulates approval API call)
        try:
            membership = member.create_membership_on_approval(
                create_invoice=False,
                approval_fields={
                    "application_status": "Approved",
                    "status": "Active",
                    "reviewed_by": frappe.session.user,
                    "review_date": now_datetime(),
                    "member_since": today()
                }
            )
            self.assertIsNotNone(membership, "Should create membership")
        except AttributeError as e:
            if "chapter_assignments" in str(e):
                self.fail(f"AttributeError during approval: {e}")
            raise

        # 5. Activate chapter membership (simulates what approval_subscribers.py does)
        from verenigingen.utils.application_helpers import activate_pending_chapter_membership

        activate_pending_chapter_membership(member, self.test_chapter.name)

        # 6. Verify final state
        member.reload()
        chapter_doc.reload()

        # Check Chapter Member status is Active
        active_members = [m for m in chapter_doc.members if m.member == member.name and m.status == "Active"]
        self.assertEqual(len(active_members), 1, "Should have 1 active Chapter Member record")

        # Check history - should still be 1 entry, updated to Active
        final_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]

        self.assertEqual(
            len(final_history),
            1,
            f"Should have exactly 1 history entry (updated, not duplicated). Got {len(final_history)}:\n"
            + "\n".join([f"  - Status: {h.status}, Assignment: {h.assignment_type}" for h in final_history])
        )

        self.assertEqual(
            final_history[0].status,
            "Active",
            "History entry should be Active after approval"
        )

        # 7. Verify member status
        self.assertEqual(member.application_status, "Approved", "Member should be approved")
        self.assertEqual(member.status, "Active", "Member should be active")


def run_tests():
    """Helper to run these tests standalone"""
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMembershipApprovalIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
