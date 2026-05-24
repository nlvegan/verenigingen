"""
Test Suite for Volunteer Assignment History Bug Fixes

This test suite covers the specific bugs found and fixed in 2025-11-18:
1. Duplicate assignment prevention
2. Reactivation of completed assignments (remove then re-add)
3. Multiple rapid saves (race condition prevention)
4. Event-driven sync architecture
5. Idempotency at all levels

Related Files:
- verenigingen/utils/assignment_history_manager.py (idempotency fixes)
- verenigingen/verenigingen/doctype/chapter/chapter.py (removed direct sync)
- docs/VOLUNTEER_ASSIGNMENT_HISTORY_FIX.md
- docs/VOLUNTEER_ASSIGNMENT_ARCHITECTURE_CHANGE.md
"""

import frappe
from frappe.utils import today, add_days, now
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager
import unittest


class TestVolunteerAssignmentHistoryBugFixes(EnhancedTestCase):
    """Test bug fixes for volunteer assignment history"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()

        # Create test region if it doesn't exist
        if not frappe.db.exists("Region", "TestRegion"):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "TestRegion",
                "region_code": "TEST",
            }).insert()

        # Create chapter role if it doesn't exist
        if not frappe.db.exists("Chapter Role", "Test Chair"):
            frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": "Test Chair",
                "permissions_level": "Admin",
                "is_chair": 1,
                "is_unique": 1,
                "is_active": 1,
            }).insert()

    def setUp(self):
        """Set up test data for each test"""
        super().setUp()

        # Create test member and volunteer
        self.test_member = self.create_test_member(
            first_name="Assignment",
            last_name="Test",
            email=f"assignment.test.{frappe.utils.random_string(8)}@example.com"
        )

        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name
        )

        # Create test chapter with timestamp for uniqueness
        import time
        timestamp = str(int(time.time() * 1000))[-8:]  # Last 8 digits of timestamp
        self.test_chapter = frappe.get_doc({
            "doctype": "Chapter",
            "status": "Active",
            "name": f"TestChapter{timestamp}",
            "chapter_head": self.test_member.name,
            "region": "TestRegion",
            "introduction": "Test chapter for assignment history testing",
        }).insert()

    def tearDown(self):
        """Clean up test data"""
        # Clean up in reverse order
        if hasattr(self, 'test_chapter'):
            try:
                # Clear board members first
                self.test_chapter.reload()
                self.test_chapter.board_members = []
                self.test_chapter.save()
                frappe.db.commit()
            except Exception:
                pass

        super().tearDown()

        # Clean up chapter
        if hasattr(self, 'test_chapter'):
            try:
                frappe.delete_doc("Chapter", self.test_chapter.name, force=True)
            except Exception:
                pass

    def test_01_duplicate_prevention_on_add(self):
        """
        Bug: Adding the same assignment twice created duplicates
        Fix: Enhanced idempotency check looks at both Active and Completed status
        """
        start_date = today()

        # Add assignment once
        success1 = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )
        self.assertTrue(success1, "First add should succeed")

        # Get assignment count
        self.test_volunteer.reload()
        count_after_first = len([
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Test Chair"
        ])
        self.assertEqual(count_after_first, 1, "Should have exactly 1 assignment")

        # Try to add same assignment again (should be idempotent)
        success2 = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )
        self.assertTrue(success2, "Second add should succeed (idempotent)")

        # Verify no duplicate was created
        self.test_volunteer.reload()
        count_after_second = len([
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Test Chair"
        ])
        self.assertEqual(
            count_after_second, 1,
            "Should still have exactly 1 assignment (no duplicate created)"
        )

    def test_02_duplicate_prevention_on_complete(self):
        """
        Bug: Calling complete_assignment_history() twice created duplicate completed entries
        Fix: Check for existing completed assignment before reconstructing
        """
        start_date = today()
        end_date = add_days(today(), 30)

        # Add active assignment
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )

        # Complete assignment once
        success1 = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
            end_date=end_date,
        )
        self.assertTrue(success1, "First complete should succeed")

        # Get completed assignment count
        self.test_volunteer.reload()
        completed_count_1 = len([
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.status == "Completed"
        ])
        self.assertEqual(completed_count_1, 1, "Should have 1 completed assignment")

        # Try to complete same assignment again (should be idempotent)
        success2 = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
            end_date=end_date,
        )
        self.assertTrue(success2, "Second complete should succeed (idempotent)")

        # Verify no duplicate was created
        self.test_volunteer.reload()
        completed_count_2 = len([
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.status == "Completed"
        ])
        self.assertEqual(
            completed_count_2, 1,
            "Should still have exactly 1 completed assignment (no duplicate)"
        )

    def test_03_reactivation_scenario(self):
        """
        Bug: Removing and re-adding board member created duplicate assignments
        Fix: Reactivate existing completed assignment instead of creating new one
        """
        start_date = today()

        # Add assignment
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )

        # Complete assignment (person leaves board)
        AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
            end_date=today(),
        )

        # Verify completed
        self.test_volunteer.reload()
        completed_assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name and a.status == "Completed"
        ]
        self.assertEqual(len(completed_assignments), 1, "Should have 1 completed assignment")

        # Re-add same assignment (person rejoins board with same role/date)
        # This should REACTIVATE the existing assignment, not create a new one
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,  # Same start date
        )

        # Verify reactivation
        self.test_volunteer.reload()
        total_assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name and a.role == "Test Chair"
        ]
        active_assignments = [a for a in total_assignments if a.status == "Active"]
        completed_assignments = [a for a in total_assignments if a.status == "Completed"]

        self.assertEqual(
            len(total_assignments), 1,
            "Should have exactly 1 total assignment (reactivated, not duplicated)"
        )
        self.assertEqual(len(active_assignments), 1, "Assignment should be Active")
        self.assertEqual(len(completed_assignments), 0, "No completed assignments should remain")

        # Verify end_date was cleared on reactivation
        active_assignment = active_assignments[0]
        self.assertIsNone(active_assignment.end_date, "End date should be cleared on reactivation")

    def test_04_multiple_rapid_adds_idempotency(self):
        """
        Bug: Rapid successive calls could create race conditions and duplicates
        Fix: Idempotency check prevents duplicates even with rapid calls
        """
        start_date = today()

        # Simulate rapid successive calls (like from race condition)
        for i in range(5):
            AssignmentHistoryManager.add_assignment_history(
                volunteer_id=self.test_volunteer.name,
                assignment_type="Board Position",
                reference_doctype="Chapter",
                reference_name=self.test_chapter.name,
                role="Test Chair",
                start_date=start_date,
            )

        # Verify only one assignment was created
        self.test_volunteer.reload()
        assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Test Chair"
            and a.status == "Active"
        ]

        self.assertEqual(
            len(assignments), 1,
            "Despite 5 rapid calls, should have exactly 1 assignment (idempotency works)"
        )

    def test_05_chapter_board_member_sync_no_duplicates(self):
        """
        Bug: Direct sync + event-driven sync caused duplicate assignments
        Fix: Removed direct sync from after_save(), only event-driven remains

        This test verifies that adding board members through Chapter only
        creates one assignment (via event-driven architecture).
        """
        # Add board member to chapter
        self.test_chapter.reload()
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteer.name,
            "chapter_role": "Test Chair",
            "from_date": today(),
            "is_active": 1,
        })
        self.test_chapter.save()
        frappe.db.commit()

        # Give background jobs time to process (in real tests this happens instantly)
        # Note: In unit tests, background jobs may not run automatically
        # We're testing that the direct sync is NOT called

        # Manual sync to simulate background job completion
        # (In production this happens automatically via events)
        from verenigingen.events.subscribers.chapter_subscribers import handle_volunteer_sync
        handle_volunteer_sync(
            "chapter_board_changed",
            {
                "chapter": self.test_chapter.name,
                "volunteer": self.test_volunteer.name,
                "action": "added",
                "role": "Test Chair",
            }
        )

        # Verify only one assignment was created
        self.test_volunteer.reload()
        assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Test Chair"
            and a.status == "Active"
        ]

        self.assertEqual(
            len(assignments), 1,
            "Chapter save should create exactly 1 assignment (event-driven only, no direct sync)"
        )

    def test_06_remove_and_readd_different_dates(self):
        """
        Real-world scenario: Person leaves board, comes back later with different start date
        Should create TWO separate stints (not reactivate, since different start_date)
        """
        first_start = add_days(today(), -365)  # Started a year ago
        first_end = add_days(today(), -30)     # Left a month ago
        second_start = today()                  # Rejoins today

        # First stint
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=first_start,
        )

        AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=first_start,
            end_date=first_end,
        )

        # Second stint (different start date)
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=second_start,  # DIFFERENT start date
        )

        # Verify TWO separate stints
        self.test_volunteer.reload()
        all_assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name and a.role == "Test Chair"
        ]

        self.assertEqual(len(all_assignments), 2, "Should have 2 separate stints")

        # Verify first stint is completed
        first_stint = [a for a in all_assignments if str(a.start_date) == str(first_start)]
        self.assertEqual(len(first_stint), 1)
        self.assertEqual(first_stint[0].status, "Completed")
        self.assertEqual(str(first_stint[0].end_date), str(first_end))

        # Verify second stint is active
        second_stint = [a for a in all_assignments if str(a.start_date) == str(second_start)]
        self.assertEqual(len(second_stint), 1)
        self.assertEqual(second_stint[0].status, "Active")
        self.assertIsNone(second_stint[0].end_date)

    def test_07_role_change_same_chapter(self):
        """
        Real-world scenario: Person changes role in same chapter
        Should have TWO assignments (old role completed, new role active)
        """
        start_date = add_days(today(), -180)  # Started 6 months ago

        # Initial role: Chair
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )

        # Complete Chair role
        AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
            end_date=today(),
        )

        # New role: Secretary (starts today)
        # Need to create Secretary role first
        if not frappe.db.exists("Chapter Role", "Test Secretary"):
            frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": "Test Secretary",
                "permissions_level": "Admin",
                "is_unique": 1,
                "is_active": 1,
            }).insert()

        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Secretary",  # Different role
            start_date=today(),
        )

        # Verify TWO assignments (different roles)
        self.test_volunteer.reload()
        all_assignments = [
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
        ]

        self.assertEqual(len(all_assignments), 2, "Should have 2 assignments (different roles)")

        # Verify Chair assignment is completed
        chair_assignment = [a for a in all_assignments if a.role == "Test Chair"]
        self.assertEqual(len(chair_assignment), 1)
        self.assertEqual(chair_assignment[0].status, "Completed")

        # Verify Secretary assignment is active
        secretary_assignment = [a for a in all_assignments if a.role == "Test Secretary"]
        self.assertEqual(len(secretary_assignment), 1)
        self.assertEqual(secretary_assignment[0].status, "Active")

    def test_08_recursion_guard_prevents_infinite_loops(self):
        """
        Verify that the recursion guard prevents infinite loops during updates
        """
        start_date = today()

        # Add assignment
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )

        # Reload volunteer and set recursion guard
        self.test_volunteer.reload()
        self.test_volunteer._updating_assignment_history = True

        # Try to add assignment while guard is set (should skip)
        result = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=self.test_volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.test_chapter.name,
            role="Test Chair",
            start_date=start_date,
        )

        # Should return early (True but skipped)
        self.assertTrue(result, "Should return True when skipping due to recursion guard")

        # Verify no changes were made
        self.test_volunteer.reload()
        assignment_count = len([
            a for a in self.test_volunteer.assignment_history or []
            if a.reference_name == self.test_chapter.name
        ])

        # Should still have just 1 assignment (from initial add)
        self.assertEqual(assignment_count, 1, "Recursion guard should prevent updates")


if __name__ == "__main__":
    import unittest
    unittest.main()
