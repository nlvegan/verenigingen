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
import unittest


class TestChapterMembershipApprovalIntegration(EnhancedTestCase):
    """Integration tests for chapter membership during member approval"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test chapter manually (Chapter uses autoname='prompt')
        chapter_name = f"Test Chapter {int(now_datetime().timestamp())}"
        self.test_chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": chapter_name,
            "status": "Active",
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

    def _create_test_chapter(self, name):
        """Create a test chapter with ignore_permissions for test setup."""
        chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": name,
            "status": "Active",
        })
        chapter.insert(ignore_permissions=True)
        frappe.db.commit()
        return chapter

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

    def test_canonical_approval_activates_chapter_membership(self):
        """
        Test that the canonical membership approval path correctly activates
        pending chapter memberships.

        Repointed from MemberLifecycleService to the canonical API in T4.1
        step 4. The SQL query in _activate_pending_chapter_memberships
        finds Chapter Member rows by member+status='Pending' (parent column
        carries the chapter; Chapter Member is a child table). Earlier
        versions of this code used a non-existent 'chapter' column and the
        regression this test guards is that bug.

        Regression test for: Chapter Member status staying "Pending" after approval.
        """
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
        )

        # 1. Create pending member application
        member = self.create_test_member(
            first_name="Test",
            last_name="LifecycleServiceUser",
            email=f"test_lifecycle_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member"
        )

        # 2. Create pending chapter membership (simulates application form submission)
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # 3. Verify initial state - Chapter Member should be Pending
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        pending_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(pending_members), 1, "Should have 1 Chapter Member record")
        self.assertEqual(pending_members[0].status, "Pending", "Initial status should be Pending")

        # 4. Verify the SQL query that was buggy now works correctly
        pending_chapters = frappe.db.sql(
            """
            SELECT parent as chapter, name
            FROM `tabChapter Member`
            WHERE member = %s AND status = 'Pending'
            """,
            (member.name,),
            as_dict=True,
        )
        self.assertEqual(
            len(pending_chapters), 1,
            f"SQL query should find 1 pending chapter membership. "
            f"This tests the fix for the 'unknown column chapter' bug."
        )
        self.assertEqual(
            pending_chapters[0].chapter, self.test_chapter.name,
            "Query should correctly return chapter name via 'parent as chapter'"
        )

        # 5. Now approve via the canonical API.
        member.reload()
        approve_membership_application(
            member_name=member.name, membership_type="Standard Member", chapter=None
        )

        # 6. Verify chapter membership status changed to Active.
        chapter_doc.reload()
        active_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(active_members), 1, "Should still have 1 Chapter Member record")
        self.assertEqual(
            active_members[0].status, "Active",
            "Chapter Member status should be 'Active' after canonical approval. "
            "If this is 'Pending', _activate_pending_chapter_memberships didn't fire."
        )

        # 8. Verify member is now approved
        member.reload()
        self.assertEqual(member.application_status, "Approved", "Member should be approved")
        self.assertEqual(member.status, "Active", "Member should be active")

    def test_canonical_approval_handles_multiple_pending_chapters(self):
        """
        Test that the canonical approval path activates ALL pending chapter
        memberships, not just one.

        Repointed to the canonical API in T4.1 step 4. Verifies the loop in
        _activate_pending_chapter_memberships correctly processes multiple
        pending Chapter Member rows for a single member.
        """
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
        )

        # Create a second test chapter
        second_chapter = self._create_test_chapter(f"Test Chapter 2 {int(now_datetime().timestamp())}")
        second_chapter_name = second_chapter.name

        # 1. Create pending member
        member = self.create_test_member(
            first_name="Test",
            last_name="MultiChapterUser",
            email=f"test_multi_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member"
        )

        # 2. Create pending chapter memberships in BOTH chapters
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        cm1 = create_pending_chapter_membership(member, self.test_chapter.name)
        cm2 = create_pending_chapter_membership(member, second_chapter_name)
        self.assertIsNotNone(cm1, "Should create first pending chapter membership")
        self.assertIsNotNone(cm2, "Should create second pending chapter membership")

        # 3. Verify both are Pending
        pending_count = frappe.db.count(
            "Chapter Member",
            {"member": member.name, "status": "Pending"}
        )
        self.assertEqual(pending_count, 2, "Should have 2 pending chapter memberships")

        # 4. Approve via the canonical API.
        member.reload()
        approve_membership_application(
            member_name=member.name, membership_type="Standard Member", chapter=None
        )

        # 5. Verify BOTH chapter memberships are now Active
        active_count = frappe.db.count(
            "Chapter Member",
            {"member": member.name, "status": "Active"}
        )
        pending_count = frappe.db.count(
            "Chapter Member",
            {"member": member.name, "status": "Pending"}
        )

        self.assertEqual(
            active_count, 2,
            f"Both chapter memberships should be Active. Found {active_count} active, {pending_count} pending."
        )
        self.assertEqual(
            pending_count, 0,
            "No chapter memberships should remain Pending after approval."
        )

    def test_termination_sets_active_chapter_membership_to_inactive(self):
        """
        Test that termination sets Active chapter membership status to 'Inactive'.

        Verifies that disable_chapter_memberships_safe() sets both:
        - enabled = 0
        - status = 'Inactive'

        Regression test for: Chapter Member status staying 'Active' after termination
        (only enabled flag was being set to 0, not status)
        """
        from verenigingen.utils.termination_integration import disable_chapter_memberships_safe

        # 1. Create active member with Active chapter membership
        member = self.create_test_member(
            first_name="Test",
            last_name="TerminationActiveUser",
            email=f"test_term_active_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved"
        )

        # 2. Create Active chapter membership
        from verenigingen.utils.application_helpers import create_active_chapter_membership

        chapter_member = create_active_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create active chapter membership")

        # 3. Verify initial state - Chapter Member should be Active with enabled=1
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        active_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(active_members), 1, "Should have 1 Chapter Member record")
        self.assertEqual(active_members[0].status, "Active", "Initial status should be Active")
        self.assertEqual(active_members[0].enabled, 1, "Initial enabled should be 1")

        # 4. Disable chapter membership (simulates termination)
        disabled_count = disable_chapter_memberships_safe(
            member.name,
            today(),
            "Member terminated - Test"
        )

        self.assertEqual(disabled_count, 1, "Should disable 1 chapter membership")

        # 5. Verify final state - Chapter Member should be Inactive with enabled=0
        chapter_doc.reload()
        disabled_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(disabled_members), 1, "Should still have 1 Chapter Member record")
        self.assertEqual(
            disabled_members[0].enabled, 0,
            "enabled flag should be 0 after termination"
        )
        self.assertEqual(
            disabled_members[0].status, "Inactive",
            "status should be 'Inactive' after termination, not 'Active'. "
            "The termination code should set both enabled=0 AND status='Inactive'."
        )
        self.assertIsNotNone(
            disabled_members[0].leave_reason,
            "leave_reason should be set"
        )

    def test_termination_sets_pending_chapter_membership_to_inactive(self):
        """
        Test that termination sets Pending chapter membership status to 'Inactive'.

        When a member with a Pending chapter membership is terminated (e.g., application
        rejected but using termination flow, or admin action), the chapter membership
        should be set to Inactive, not left as Pending.

        Regression test for: Pending chapter memberships not being properly handled during termination
        """
        from verenigingen.utils.termination_integration import disable_chapter_memberships_safe

        # 1. Create pending member
        member = self.create_test_member(
            first_name="Test",
            last_name="TerminationPendingUser",
            email=f"test_term_pending_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending"
        )

        # 2. Create Pending chapter membership
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # 3. Verify initial state - Chapter Member should be Pending with enabled=1
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        pending_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(pending_members), 1, "Should have 1 Chapter Member record")
        self.assertEqual(pending_members[0].status, "Pending", "Initial status should be Pending")
        self.assertEqual(pending_members[0].enabled, 1, "Initial enabled should be 1")

        # 4. Disable chapter membership (simulates termination/rejection)
        disabled_count = disable_chapter_memberships_safe(
            member.name,
            today(),
            "Application rejected - Test"
        )

        self.assertEqual(disabled_count, 1, "Should disable 1 chapter membership")

        # 5. Verify final state - Chapter Member should be Inactive with enabled=0
        chapter_doc.reload()
        disabled_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(disabled_members), 1, "Should still have 1 Chapter Member record")
        self.assertEqual(
            disabled_members[0].enabled, 0,
            "enabled flag should be 0 after termination"
        )
        self.assertEqual(
            disabled_members[0].status, "Inactive",
            "status should be 'Inactive' after termination, not 'Pending'. "
            "Pending members should also be set to Inactive when disabled."
        )

    def test_termination_operation_sets_chapter_status_inactive(self):
        """
        Test the full DisableChapterMembershipsOperation sets status to Inactive.

        Tests the complete operation path used during actual termination workflow.
        """
        from verenigingen.utils.termination_operations import DisableChapterMembershipsOperation
        from verenigingen.utils.termination_operations import TerminationResults

        # 1. Create active member with chapter membership
        member = self.create_test_member(
            first_name="Test",
            last_name="OperationUser",
            email=f"test_operation_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved"
        )

        # 2. Create Active chapter membership
        from verenigingen.utils.application_helpers import create_active_chapter_membership

        chapter_member = create_active_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create active chapter membership")

        # 3. Create termination request
        termination_request = frappe.get_doc({
            "doctype": "Membership Termination Request",
            "member": member.name,
            "termination_type": "Voluntary",
            "termination_reason": "Test termination",
            "member_request_date": today(),
            "termination_date": today()
        })
        termination_request.insert()

        # 4. Execute the DisableChapterMembershipsOperation
        operation = DisableChapterMembershipsOperation(member.name, termination_request)
        results = TerminationResults()
        operation.execute(results)

        # 5. Verify Chapter Member is now Inactive
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        disabled_members = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(disabled_members), 1, "Should have 1 Chapter Member record")
        self.assertEqual(
            disabled_members[0].status, "Inactive",
            "DisableChapterMembershipsOperation should set status to 'Inactive'"
        )
        self.assertEqual(
            disabled_members[0].enabled, 0,
            "DisableChapterMembershipsOperation should set enabled to 0"
        )

        # 6. Verify the action was recorded
        self.assertTrue(
            any("chapter membership" in action.lower() for action in results.actions_taken),
            f"Should record chapter membership action. Actions: {results.actions_taken}"
        )

    def test_termination_updates_member_chapter_history(self):
        """
        Test that termination updates the Member's chapter_membership_history via
        the centralized ChapterMembershipHistoryManager.

        Verifies that disable_chapter_memberships_safe() updates both:
        1. Chapter Member child table (on Chapter doc)
        2. Member.chapter_membership_history (end_date and status='Quit')
        """
        from verenigingen.utils.termination_integration import disable_chapter_memberships_safe
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        # 1. Create active member
        member = self.create_test_member(
            first_name="Test",
            last_name="HistoryUpdateUser",
            email=f"test_history_update_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved"
        )

        # 2. Create Active chapter membership AND add history entry
        from verenigingen.utils.application_helpers import create_active_chapter_membership

        chapter_member = create_active_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create active chapter membership")

        # Ensure history entry exists (create_active_chapter_membership should do this, but verify)
        member.reload()
        initial_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
        ]

        # If no history exists, add one manually for the test
        if not initial_history:
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member.name,
                chapter_name=self.test_chapter.name,
                assignment_type="Member",
                start_date=today(),
                status="Active",
                reason="Test membership"
            )
            member.reload()
            initial_history = [
                h for h in (member.chapter_membership_history or [])
                if h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
            ]

        self.assertEqual(len(initial_history), 1, "Should have 1 history entry before termination")
        self.assertEqual(initial_history[0].status, "Active", "Initial history status should be Active")
        self.assertIsNone(initial_history[0].end_date, "Initial history should have no end_date")

        # 3. Disable chapter membership (simulates termination)
        disabled_count = disable_chapter_memberships_safe(
            member.name,
            today(),
            "Member terminated - Integration test"
        )

        self.assertEqual(disabled_count, 1, "Should disable 1 chapter membership")

        # 4. Verify Member's chapter_membership_history was updated
        member.reload()
        final_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
        ]

        self.assertEqual(len(final_history), 1, "Should still have 1 history entry (updated, not duplicated)")
        self.assertEqual(
            final_history[0].status, "Quit",
            "History status should be 'Quit' after termination. "
            "The termination code should use ChapterMembershipHistoryManager.terminate_chapter_membership()."
        )
        self.assertIsNotNone(
            final_history[0].end_date,
            "History end_date should be set after termination"
        )
        self.assertEqual(
            str(final_history[0].end_date), str(today()),
            "History end_date should match termination date"
        )

    def test_termination_handles_pending_history_status(self):
        """
        Test that termination also terminates Pending history entries, not just Active.

        When a member with a Pending chapter membership is terminated (e.g., application
        rejected via termination flow), the history should also be set to Terminated.
        """
        from verenigingen.utils.termination_integration import disable_chapter_memberships_safe
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        # 1. Create pending member
        member = self.create_test_member(
            first_name="Test",
            last_name="PendingHistoryUser",
            email=f"test_pending_history_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending"
        )

        # 2. Create Pending chapter membership
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # 3. Verify history entry is Pending
        member.reload()
        initial_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
        ]
        self.assertEqual(len(initial_history), 1, "Should have 1 history entry")
        self.assertEqual(initial_history[0].status, "Pending", "Initial history should be Pending")

        # 4. Disable chapter membership (simulates termination)
        disabled_count = disable_chapter_memberships_safe(
            member.name,
            today(),
            "Application rejected - Test"
        )
        self.assertEqual(disabled_count, 1, "Should disable 1 chapter membership")

        # 5. Verify history was updated from Pending to Terminated
        member.reload()
        final_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
        ]
        self.assertEqual(len(final_history), 1, "Should still have 1 history entry")
        self.assertEqual(
            final_history[0].status, "Quit",
            "Pending history should be set to 'Quit', not left as 'Pending'. "
            "terminate_chapter_membership() should handle both Active and Pending statuses."
        )

    def test_termination_is_idempotent(self):
        """
        Test that calling termination twice is safe and idempotent.

        Second call should return True (already terminated) without creating duplicates.
        """
        from verenigingen.utils.termination_integration import disable_chapter_memberships_safe
        from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

        # 1. Create active member with chapter membership and history
        member = self.create_test_member(
            first_name="Test",
            last_name="IdempotentUser",
            email=f"test_idempotent_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved"
        )

        from verenigingen.utils.application_helpers import create_active_chapter_membership

        chapter_member = create_active_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create active chapter membership")

        # Ensure history exists
        member.reload()
        if not any(
            h.chapter_name == self.test_chapter.name and h.assignment_type == "Member"
            for h in (member.chapter_membership_history or [])
        ):
            ChapterMembershipHistoryManager.add_membership_history(
                member_id=member.name,
                chapter_name=self.test_chapter.name,
                assignment_type="Member",
                start_date=today(),
                status="Active"
            )

        # 2. First termination call
        disabled_count_1 = disable_chapter_memberships_safe(
            member.name,
            today(),
            "First termination"
        )
        self.assertEqual(disabled_count_1, 1, "First call should disable 1 membership")

        # 3. Second call to disable_chapter_memberships_safe() - should be idempotent
        member.reload()
        history_count_after_first = len([
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ])

        disabled_count_2 = disable_chapter_memberships_safe(
            member.name,
            today(),
            "Second termination attempt"
        )
        self.assertEqual(
            disabled_count_2, 0,
            "Second call should find no enabled memberships to disable"
        )

        # 4. Also test the history manager directly for idempotency
        result = ChapterMembershipHistoryManager.terminate_chapter_membership(
            member_id=member.name,
            chapter_name=self.test_chapter.name,
            assignment_type="Member",
            end_date=today(),
            reason="Third termination attempt via history manager"
        )
        self.assertTrue(result, "History manager should return True (already terminated)")

        # 5. Verify no duplicate history entries
        member.reload()
        final_history = [
            h for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]
        self.assertEqual(
            len(final_history), history_count_after_first,
            "Should not create duplicate history entries on second termination call"
        )


    def test_rejection_removes_pending_chapter_membership(self):
        """
        Test that rejecting a membership application removes the pending
        Chapter Member record AND terminates the history entry.
        """
        from verenigingen.utils.application_helpers import (
            create_pending_chapter_membership,
            remove_all_pending_chapter_memberships,
        )

        # Create pending member with chapter membership
        member = self.create_test_member(
            first_name="Test",
            last_name="RejectionUser",
            email=f"test_rejection_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member",
        )

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member, "Should create pending chapter membership")

        # Verify initial state
        member.reload()
        initial_history = [
            h
            for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]
        self.assertEqual(len(initial_history), 1, "Should have 1 history entry before rejection")
        self.assertEqual(initial_history[0].status, "Pending", "History should be Pending")

        # Simulate rejection cleanup
        removed = remove_all_pending_chapter_memberships(member)
        self.assertEqual(removed, [self.test_chapter.name], "Should remove chapter membership")

        # Verify Chapter Member record is gone
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        pending = [m for m in chapter_doc.members if m.member == member.name and m.status == "Pending"]
        self.assertEqual(len(pending), 0, "No pending Chapter Member records should remain")

        # Verify history is Terminated with end_date
        member.reload()
        final_history = [
            h
            for h in (member.chapter_membership_history or [])
            if h.chapter_name == self.test_chapter.name
        ]
        self.assertEqual(len(final_history), 1, "Should still have 1 history entry (updated)")
        self.assertEqual(
            final_history[0].status,
            "Quit",
            "History should be Terminated after rejection",
        )
        self.assertIsNotNone(final_history[0].end_date, "History end_date should be set")

    def test_rejection_removes_all_pending_chapter_memberships(self):
        """
        Test that rejection removes pending memberships from ALL chapters,
        not just one.
        """
        from verenigingen.utils.application_helpers import (
            create_pending_chapter_membership,
            remove_all_pending_chapter_memberships,
        )

        # Create second chapter
        second_chapter = self.create_test_chapter(
            chapter_name=f"Test Chapter 2 {int(now_datetime().timestamp())}"
        )
        second_chapter_name = second_chapter.name

        # Create pending member
        member = self.create_test_member(
            first_name="Test",
            last_name="MultiRejectionUser",
            email=f"test_multi_reject_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member",
        )

        # Create pending memberships in both chapters
        cm1 = create_pending_chapter_membership(member, self.test_chapter.name)
        cm2 = create_pending_chapter_membership(member, second_chapter_name)
        self.assertIsNotNone(cm1)
        self.assertIsNotNone(cm2)

        # Verify 2 pending Chapter Member records exist
        pending_count = frappe.db.count(
            "Chapter Member", {"member": member.name, "status": "Pending"}
        )
        self.assertEqual(pending_count, 2, "Should have 2 pending chapter memberships")

        # Remove all pending memberships
        removed = remove_all_pending_chapter_memberships(member)
        self.assertEqual(len(removed), 2, "Should remove both chapter memberships")

        # Verify no pending records remain
        remaining = frappe.db.count(
            "Chapter Member", {"member": member.name, "status": "Pending"}
        )
        self.assertEqual(remaining, 0, "No pending Chapter Member records should remain")

        # Verify both history entries are Terminated
        member.reload()
        for chapter_name in [self.test_chapter.name, second_chapter_name]:
            history = [
                h
                for h in (member.chapter_membership_history or [])
                if h.chapter_name == chapter_name
            ]
            self.assertEqual(len(history), 1, f"Should have 1 history entry for {chapter_name}")
            self.assertEqual(
                history[0].status,
                "Quit",
                f"History for {chapter_name} should be Terminated",
            )

    def test_rejection_with_no_pending_chapter_membership(self):
        """
        Test that rejection cleanup doesn't error when member has no pending
        chapter memberships.
        """
        from verenigingen.utils.application_helpers import remove_all_pending_chapter_memberships

        # Create pending member with NO chapter membership
        member = self.create_test_member(
            first_name="Test",
            last_name="NoChapterUser",
            email=f"test_no_chapter_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
        )

        # Should not error and return empty list
        removed = remove_all_pending_chapter_memberships(member)
        self.assertEqual(removed, [], "Should return empty list when no pending memberships")

    def test_rejection_cleanup_none_member(self):
        """
        Test that remove_all_pending_chapter_memberships handles None member gracefully.
        """
        from verenigingen.utils.application_helpers import remove_all_pending_chapter_memberships

        removed = remove_all_pending_chapter_memberships(None)
        self.assertEqual(removed, [], "Should return empty list for None member")

    def test_rejection_partial_failure_still_removes_others(self):
        """
        Test that if one chapter removal fails, remaining chapters are still processed.

        Simulates partial failure by creating a pending Chapter Member record
        pointing to a non-existent chapter (orphaned data), alongside a valid one.
        """
        from verenigingen.utils.application_helpers import (
            create_pending_chapter_membership,
            remove_all_pending_chapter_memberships,
        )

        # Create pending member with valid chapter membership
        member = self.create_test_member(
            first_name="Test",
            last_name="PartialFailUser",
            email=f"test_partial_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"TEST-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member",
        )

        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member)

        # Insert an orphaned Chapter Member row pointing to a fake chapter
        # (simulates data inconsistency where chapter was deleted but child row remains)
        fake_chapter_name = f"Deleted Chapter {int(now_datetime().timestamp())}"
        frappe.db.sql(
            """INSERT INTO `tabChapter Member`
               (name, parent, parenttype, parentfield, member, status, idx)
               VALUES (%s, %s, 'Chapter', 'members', %s, 'Pending', 99)""",
            (frappe.generate_hash(length=10), fake_chapter_name, member.name),
        )
        frappe.db.commit()

        # Should still remove the valid chapter even though fake one will fail
        removed = remove_all_pending_chapter_memberships(member)
        self.assertIn(
            self.test_chapter.name,
            removed,
            "Valid chapter should still be removed despite fake chapter failure",
        )

        # Clean up orphaned row
        frappe.db.sql(
            "DELETE FROM `tabChapter Member` WHERE parent = %s AND member = %s",
            (fake_chapter_name, member.name),
        )
        frappe.db.commit()


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
