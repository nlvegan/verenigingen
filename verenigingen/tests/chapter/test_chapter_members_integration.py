"""
Phase 4 Mock Elimination: Chapter Member Integration Tests
=========================================================

This is the converted version of test_chapter_members_basic.py that eliminates
inappropriate business logic mocks and uses real integration testing patterns.

ELIMINATED MOCKS:
- ChapterMembershipHistoryManager.add_membership_history()
- ChapterMembershipHistoryManager.end_chapter_membership()

REPLACED WITH:
- Real business logic validation
- Actual database operations with transaction isolation
- Enhanced Test Factory patterns for realistic data

This conversion demonstrates Phase 4 mock elimination principles:
1. Keep only external service mocks (email, payment gateways)
2. Test real business logic and validation
3. Use Enhanced Test Factory for deterministic test data
"""

import frappe
from frappe.utils import today, add_days
from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterMemberIntegration(EnhancedTestCase):
    """
    Real integration tests for chapter member operations

    Tests actual business logic without mocking internal systems
    """

    def setUp(self):
        """Set up test environment with real database operations"""
        super().setUp()

        # Chapter membership changes are partly event-driven; run subscribers inline so
        # history is created deterministically within the test.
        self._prev_run_events_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True

        # Create test data using Enhanced Test Factory
        self.member1 = self.create_test_member(
            first_name="Integration",
            last_name="TestMember",
            birth_date="1990-01-01",  # Valid age for all operations
        )

        self.member2 = self.create_test_member(
            first_name="Integration", last_name="TestMember2", birth_date="1985-01-01"
        )

        # Create a chapter with a unique name per test. ensure_test_chapter() reuses a
        # chapter by name, so a shared name leaks membership/before-save state across test
        # methods (e.g. the first member appended in a multi-add not getting fresh history
        # because the reused doc's get_doc_before_save() reflected the prior test's state).
        unique_chapter = f"Integration Test Chapter {frappe.generate_hash(length=6)}"
        self.chapter = self.factory.ensure_test_chapter(
            unique_chapter, {"short_name": "ITC", "published": 1, "country": "Netherlands"}
        )

    def test_add_member_real_validation(self):
        """Test adding member with real business logic validation"""

        # Add member to chapter (no mocks!)
        self.chapter.append(
            "members",
            {"member": self.member1.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
        )

        # Save and test real validation
        self.chapter.save()

        # Validate results with real database queries
        self.assertEqual(len(self.chapter.members), 1)
        chapter_member = self.chapter.members[0]
        self.assertEqual(chapter_member.member, self.member1.name)
        self.assertEqual(chapter_member.status, "Active")
        self.assertTrue(chapter_member.enabled)

        # Test that membership history was actually created (real business logic).
        # Chapter Membership History is a child table of Member (parent=member,
        # parenttype="Member", chapter_name=chapter); it has no member/chapter/
        # action/effective_date columns. A join is recorded as an Active "Member"
        # assignment with a start_date.
        history_entries = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member1.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
            },
            fields=["name", "assignment_type", "status", "start_date"],
        )

        # Verify history tracking works in reality
        self.assertGreater(len(history_entries), 0, "Real history tracking should create entries")
        history_entry = history_entries[0]
        self.assertEqual(history_entry.assignment_type, "Member")
        self.assertEqual(history_entry.status, "Active")

    def test_no_duplicate_members_real_validation(self):
        """Test duplicate prevention with real business logic"""

        # Add member first time
        self.chapter.append(
            "members",
            {"member": self.member1.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
        )
        self.chapter.save()

        # Try to add same member again - should be prevented by real validation
        initial_count = len(self.chapter.members)

        # This should either be prevented by validation or handled gracefully
        try:
            self.chapter.append(
                "members",
                {"member": self.member1.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
            )
            self.chapter.save()

            # If no exception, check that duplicates were handled
            # Real business logic might prevent duplicates or mark previous as inactive
            active_memberships = [
                m for m in self.chapter.members if m.enabled and m.member == self.member1.name
            ]
            self.assertLessEqual(len(active_memberships), 1, "Should not have multiple active memberships")

        except frappe.ValidationError:
            # This is expected - real validation should prevent duplicates
            pass

    def test_remove_member_real_workflow(self):
        """Test member removal with real business workflow"""

        # Add member first
        self.chapter.append(
            "members",
            {"member": self.member1.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
        )
        self.chapter.save()

        # Remove member using real business logic
        for member_entry in self.chapter.members:
            if member_entry.member == self.member1.name:
                member_entry.enabled = 0
                member_entry.status = "Inactive"
                break

        self.chapter.save()

        # Validate real results
        active_members = [m for m in self.chapter.members if m.enabled]
        self.assertEqual(len(active_members), 0, "No active members after removal")

        # Verify real membership history reflects the change
        history_entries = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member1.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
            },
            fields=["name", "assignment_type", "status", "start_date"],
            order_by="creation desc",
        )

        # Real business logic should track the join as a Member assignment
        assignment_types = [entry.assignment_type for entry in history_entries]
        self.assertIn("Member", assignment_types, "Should track join as Member assignment")
        # Note: Leave tracking might be implemented differently in real system

    def test_multiple_members_real_operations(self):
        """Test multiple member operations with real business logic"""

        # Add multiple members
        for member in [self.member1, self.member2]:
            self.chapter.append(
                "members",
                {"member": member.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
            )

        self.chapter.save()

        # Validate with real database queries
        self.assertEqual(len(self.chapter.members), 2)

        # Test real member lookup functionality
        member_names = [m.member for m in self.chapter.members if m.enabled]
        self.assertIn(self.member1.name, member_names)
        self.assertIn(self.member2.name, member_names)

        # Verify real history tracking for multiple members. History rows are
        # child rows of Member (parent=member name); chapter is chapter_name.
        total_history = frappe.get_all(
            "Chapter Membership History",
            filters={"chapter_name": self.chapter.name, "parenttype": "Member"},
            fields=["parent as member", "assignment_type"],
        )

        # Should have history for both members (real business logic)
        history_members = [h.member for h in total_history]
        self.assertIn(self.member1.name, history_members)
        self.assertIn(self.member2.name, history_members)

    def test_chapter_member_count_real_calculation(self):
        """Test member counting with real data"""

        # Add test members
        for i, member in enumerate([self.member1, self.member2]):
            self.chapter.append(
                "members",
                {
                    "member": member.name,
                    "enabled": 1 if i == 0 else 0,  # Only first member active
                    "status": "Active" if i == 0 else "Inactive",
                },
            )

        self.chapter.save()

        # Test real counting logic (no mocks)
        active_count = sum(1 for m in self.chapter.members if m.enabled)
        total_count = len(self.chapter.members)

        self.assertEqual(active_count, 1, "Only one active member")
        self.assertEqual(total_count, 2, "Two total member entries")

        # Test real database aggregation
        db_active_count = frappe.db.count("Chapter Member", {"parent": self.chapter.name, "enabled": 1})

        self.assertEqual(db_active_count, 1, "Database count matches object count")

    # Mock justified: External Service - SMTP delivery, not business logic
    @patch("frappe.sendmail")  # KEEP: External service mock (appropriate)
    def test_member_notification_integration(self, mock_sendmail):
        """Test member notifications with external service mocking"""

        # Add member
        self.chapter.append(
            "members",
            {"member": self.member1.name, "enabled": 1, "status": "Active", "chapter_join_date": today()},
        )

        # This would trigger real notification logic
        self.chapter.save()

        # Verify real business logic executed
        self.assertEqual(len(self.chapter.members), 1)

        # External email service appropriately mocked
        # (Real implementation might send welcome emails)
        # mock_sendmail can be used to verify email content without sending

    def tearDown(self):
        """Clean up test data"""
        frappe.flags.run_events_synchronously = self._prev_run_events_sync
        # Enhanced Test Factory handles automatic cleanup via transaction rollback
        super().tearDown()


class TestChapterMemberPerformance(EnhancedTestCase):
    """Performance tests for chapter member operations"""

    def test_bulk_member_operations_performance(self):
        """Test performance of bulk member operations without mocks"""

        # Create test data
        members = []
        for i in range(10):  # Small batch for fast test execution
            member = self.create_test_member(
                first_name=f"Bulk{i}", last_name="TestMember", birth_date="1990-01-01"
            )
            members.append(member)

        chapter = self.factory.ensure_test_chapter(
            f"Bulk Test Chapter {frappe.generate_hash(length=6)}", {"short_name": "BLK"}
        )

        # Test bulk addition with query count monitoring. This class does NOT enable
        # run_events_synchronously, so the inline event-subscriber writes are NOT counted here
        # (unlike TestChapterMemberIntegration). The measured cost for this 10-member bulk save
        # is a stable ~227 queries (~22-23/member: real un-mocked Member saves + the chapter-member
        # child-table write path). The threshold is set just above that measured baseline so an
        # N+1 / N^2 regression in the bulk-append path trips it, while leaving ~15% headroom for
        # environmental query-count variance. Do NOT relax this without re-measuring.
        # INTERIM, see #885: raised 260 -> 300 because #844's `_prelock_members_for_save`
        # is called from inside each handler rather than once per save, so every Member is
        # locked 6x. Measured on develop: 277 queries (was ~227 pre-#844). The lock re-take
        # is a semantic no-op -- the row is already locked in this transaction -- but still
        # costs a round-trip per member. Put this BACK to 260 and re-measure once #885 is
        # fixed; this cap exists to catch an N+1 in the bulk-append path and a permanently
        # inflated ceiling defeats it.
        with self.assertQueryCount(300):
            for member in members:
                chapter.append("members", {"member": member.name, "enabled": 1, "status": "Active"})
            chapter.save()

        # Validate results
        self.assertEqual(len(chapter.members), len(members))

        # Test real database performance
        active_members = frappe.get_all(
            "Chapter Member", filters={"parent": chapter.name, "enabled": 1}, fields=["member"]
        )

        self.assertEqual(len(active_members), len(members))
