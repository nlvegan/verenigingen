"""
Comprehensive tests for chapter assignment with cleanup functionality.
Tests all scenarios including edge cases and error conditions.
"""

import unittest

import frappe
from frappe.utils import today

from verenigingen.verenigingen.doctype.chapter.chapter import assign_member_to_chapter_with_cleanup


class TestChapterAssignmentComprehensive(unittest.TestCase):
    """Comprehensive test suite for chapter assignment functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test chapters
        cls.test_chapters = []
        for i in range(3):
            chapter_name = f"Test Chapter {i + 1}"
            if not frappe.db.exists("Chapter", chapter_name):
                chapter = frappe.get_doc(
                    {
                        "doctype": "Chapter",
                        "name": chapter_name,
                        "region": "Test Region",
                        "published": 1,
                        "postal_codes": f"{1000 + i}-{1999 + i}",
                        "introduction": f"Test chapter {i + 1} for assignment testing"}
                )
                chapter.insert()
            cls.test_chapters.append(chapter_name)

        # Create test members
        cls.test_members = []
        for i in range(5):
            member_name = f"TEST-MEMBER-{i + 1:03d}"
            if not frappe.db.exists("Member", member_name):
                member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "member_id": member_name,
                        "first_name": f"Test{i + 1}",
                        "last_name": "Member",
                        "email": f"test{i + 1}@example.com",
                        "birth_date": "1990-01-01",
                        "status": "Active"}
                )
                member.insert()
                member.submit()
            cls.test_members.append(member_name)

    def setUp(self):
        """Set up for each test"""
        # Clean up any existing chapter memberships for test members
        for member in self.test_members:
            self._cleanup_member_assignments(member)

    def tearDown(self):
        """Clean up after each test"""
        # Clean up any test data created during tests
        for member in self.test_members:
            self._cleanup_member_assignments(member)

    def _cleanup_member_assignments(self, member_name):
        """Helper to clean up all chapter and board assignments for a member"""
        # Remove from all chapters
        chapter_members = frappe.get_all(
            "Chapter Member", filters={"member": member_name}, fields=["parent", "name"]
        )

        for cm in chapter_members:
            try:
                chapter_doc = frappe.get_doc("Chapter", cm.parent)
                chapter_doc.remove_member(member_name, leave_reason="Test cleanup")
            except Exception:
                pass

        # End all board memberships
        board_members = frappe.get_all(
            "Chapter Board Member", filters={"member": member_name, "status": "Active"}, fields=["name"]
        )

        for bm in board_members:
            try:
                board_doc = frappe.get_doc("Chapter Board Member", bm.name)
                board_doc.status = "Ended"
                board_doc.end_date = today()
                board_doc.end_reason = "Test cleanup"
                board_doc.save()
            except Exception:
                pass

    def _assign_member_to_chapter_direct(self, member, chapter):
        """Helper to directly assign member to chapter without cleanup"""
        chapter_doc = frappe.get_doc("Chapter", chapter)
        return chapter_doc.add_member(member)

    def _create_board_membership(self, member, chapter, role="Secretary"):
        """Helper to create a board membership"""
        try:
            # First ensure member is in the chapter
            self._assign_member_to_chapter_direct(member, chapter)

            board_member = frappe.get_doc(
                {
                    "doctype": "Chapter Board Member",
                    "member": member,
                    "chapter": chapter,
                    "role": role,
                    "start_date": today(),
                    "status": "Active"}
            )
            board_member.insert()
            return board_member.name
        except Exception as e:
            frappe.logger().error(f"Error creating board membership: {str(e)}")
            return None

    # ==================== BASIC FUNCTIONALITY TESTS ====================

    def test_01_basic_assignment_no_existing_memberships(self):
        """Test basic assignment when member has no existing memberships"""
        member = self.test_members[0]
        target_chapter = self.test_chapters[0]

        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="Basic assignment test"
        )

        self.assertTrue(result.get("success"), f"Assignment failed: {result.get('message')}")
        self.assertFalse(result.get("cleanup_performed"), "No cleanup should be needed")

        # Verify member is now in the chapter
        chapter_member = frappe.get_value(
            "Chapter Member", {"member": member, "parent": target_chapter, "enabled": 1}, "name"
        )
        self.assertIsNotNone(chapter_member, "Member should be in the target chapter")

    def test_02_assignment_with_existing_chapter_membership(self):
        """Test assignment when member already belongs to another chapter"""
        member = self.test_members[1]
        source_chapter = self.test_chapters[0]
        target_chapter = self.test_chapters[1]

        # First assign to source chapter
        self._assign_member_to_chapter_direct(member, source_chapter)

        # Verify initial assignment
        initial_membership = frappe.get_value(
            "Chapter Member", {"member": member, "parent": source_chapter, "enabled": 1}, "name"
        )
        self.assertIsNotNone(initial_membership, "Initial assignment should succeed")

        # Now reassign to target chapter
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="Reassignment test"
        )

        self.assertTrue(result.get("success"), f"Reassignment failed: {result.get('message')}")
        self.assertTrue(result.get("cleanup_performed"), "Cleanup should be performed")

        # Verify member is no longer in source chapter
        old_membership = frappe.get_value(
            "Chapter Member", {"member": member, "parent": source_chapter, "enabled": 1}, "name"
        )
        self.assertIsNone(old_membership, "Member should be removed from source chapter")

        # Verify member is now in target chapter
        new_membership = frappe.get_value(
            "Chapter Member", {"member": member, "parent": target_chapter, "enabled": 1}, "name"
        )
        self.assertIsNotNone(new_membership, "Member should be in target chapter")

    def test_03_assignment_with_board_membership_cleanup(self):
        """Test assignment when member has board memberships that need to be ended"""
        member = self.test_members[2]
        source_chapter = self.test_chapters[0]
        target_chapter = self.test_chapters[1]

        # Create board membership
        board_membership_id = self._create_board_membership(member, source_chapter, "Treasurer")
        self.assertIsNotNone(board_membership_id, "Board membership should be created")

        # Verify board membership is active
        board_status = frappe.get_value("Chapter Board Member", board_membership_id, "status")
        self.assertEqual(board_status, "Active", "Board membership should be active")

        # Reassign to different chapter
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="Board cleanup test"
        )

        self.assertTrue(
            result.get("success"), f"Assignment with board cleanup failed: {result.get('message')}"
        )
        self.assertTrue(result.get("cleanup_performed"), "Cleanup should be performed")

        # Verify board membership is ended
        board_doc = frappe.get_doc("Chapter Board Member", board_membership_id)
        self.assertEqual(board_doc.status, "Ended", "Board membership should be ended")
        self.assertIsNotNone(board_doc.end_date, "End date should be set")
        self.assertIn("reassigned", board_doc.end_reason.lower(), "End reason should mention reassignment")

        # Verify member is in new chapter
        new_membership = frappe.get_value(
            "Chapter Member", {"member": member, "parent": target_chapter, "enabled": 1}, "name"
        )
        self.assertIsNotNone(new_membership, "Member should be in target chapter")

    def test_04_assignment_to_same_chapter(self):
        """Test assignment when member is already in the target chapter"""
        member = self.test_members[3]
        chapter = self.test_chapters[0]

        # First assign to chapter
        self._assign_member_to_chapter_direct(member, chapter)

        # Try to assign to same chapter
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=chapter, note="Same chapter test"
        )

        # This should still succeed but indicate the member is already there
        self.assertTrue(
            result.get("success") or "already" in result.get("message", "").lower(),
            f"Same chapter assignment should handle gracefully: {result}",
        )

    # ==================== EDGE CASE TESTS ====================

    def test_05_multiple_chapter_memberships_cleanup(self):
        """Test cleanup when member belongs to multiple chapters (edge case)"""
        member = self.test_members[4]
        target_chapter = self.test_chapters[2]

        # Assign to multiple chapters (shouldn't normally happen, but test edge case)
        for chapter in self.test_chapters[:2]:
            self._assign_member_to_chapter_direct(member, chapter)

        # Verify multiple memberships exist
        existing_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent"]
        )
        self.assertGreaterEqual(len(existing_memberships), 2, "Multiple memberships should exist")

        # Reassign to target chapter
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="Multiple cleanup test"
        )

        self.assertTrue(result.get("success"), f"Multiple cleanup failed: {result.get('message')}")
        self.assertTrue(result.get("cleanup_performed"), "Cleanup should be performed")

        # Verify only target chapter membership exists
        final_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent"]
        )
        self.assertEqual(len(final_memberships), 1, "Only one membership should remain")
        self.assertEqual(final_memberships[0].parent, target_chapter, "Should be in target chapter")

    def test_06_nonexistent_member_error(self):
        """Test error handling for nonexistent member"""
        result = assign_member_to_chapter_with_cleanup(
            member="NONEXISTENT-MEMBER", chapter=self.test_chapters[0], note="Error test"
        )

        self.assertFalse(result.get("success"), "Should fail for nonexistent member")
        self.assertIn("does not exist", result.get("message", "").lower())

    def test_07_nonexistent_chapter_error(self):
        """Test error handling for nonexistent chapter"""
        result = assign_member_to_chapter_with_cleanup(
            member=self.test_members[0], chapter="NONEXISTENT-CHAPTER", note="Error test"
        )

        self.assertFalse(result.get("success"), "Should fail for nonexistent chapter")

    def test_08_missing_required_parameters(self):
        """Test error handling for missing parameters"""
        # Test missing member
        result = assign_member_to_chapter_with_cleanup(member=None, chapter=self.test_chapters[0])
        self.assertFalse(result.get("success"), "Should fail for missing member")

        # Test missing chapter
        result = assign_member_to_chapter_with_cleanup(member=self.test_members[0], chapter=None)
        self.assertFalse(result.get("success"), "Should fail for missing chapter")

    def test_09_complex_scenario_with_multiple_board_roles(self):
        """Test complex scenario with multiple board memberships across chapters"""
        member = self.test_members[0]

        # Create multiple board memberships in different chapters
        board_ids = []
        for i, chapter in enumerate(self.test_chapters[:2]):
            role = ["President", "Vice President"][i]
            board_id = self._create_board_membership(member, chapter, role)
            if board_id:
                board_ids.append(board_id)

        self.assertGreater(len(board_ids), 0, "At least one board membership should be created")

        # Reassign to third chapter
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=self.test_chapters[2], note="Complex scenario test"
        )

        self.assertTrue(result.get("success"), f"Complex scenario failed: {result.get('message')}")
        self.assertTrue(result.get("cleanup_performed"), "Cleanup should be performed")

        # Verify all board memberships are ended
        for board_id in board_ids:
            board_doc = frappe.get_doc("Chapter Board Member", board_id)
            self.assertEqual(board_doc.status, "Ended", f"Board membership {board_id} should be ended")

    # ==================== INTEGRATION TESTS ====================

    def test_10_history_tracking_integration(self):
        """Test that chapter membership history is properly tracked"""
        member = self.test_members[1]
        source_chapter = self.test_chapters[0]
        target_chapter = self.test_chapters[1]

        # Initial assignment
        self._assign_member_to_chapter_direct(member, source_chapter)

        # Get initial history count
        initial_history_count = frappe.db.count(
            "Member Chapter Membership History", filters={"member": member}
        )

        # Reassign
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="History tracking test"
        )

        self.assertTrue(result.get("success"), "Assignment should succeed")

        # Check that history was updated
        final_history_count = frappe.db.count("Member Chapter Membership History", filters={"member": member})

        # Should have at least one new history entry
        self.assertGreater(
            final_history_count, initial_history_count, "History should be updated with new assignment"
        )

    def test_11_concurrent_assignment_safety(self):
        """Test safety when multiple assignments might happen concurrently"""
        member = self.test_members[2]

        # Pre-assign to a chapter
        self._assign_member_to_chapter_direct(member, self.test_chapters[0])

        # Simulate rapid reassignments
        results = []
        for chapter in self.test_chapters[1:]:
            result = assign_member_to_chapter_with_cleanup(
                member=member, chapter=chapter, note=f"Concurrent test to {chapter}"
            )
            results.append(result)

        # At least the last assignment should succeed
        self.assertTrue(any(r.get("success") for r in results), "At least one assignment should succeed")

        # Verify member ends up in exactly one chapter
        final_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent"]
        )
        self.assertEqual(
            len(final_memberships), 1, "Member should be in exactly one chapter after concurrent operations"
        )

    # ==================== PERFORMANCE TESTS ====================

    def test_12_performance_with_large_membership_history(self):
        """Test performance when member has extensive membership history"""
        member = self.test_members[3]
        target_chapter = self.test_chapters[0]

        # Create multiple historical assignments by assigning and removing repeatedly
        for i in range(5):  # Create some history without overwhelming the test
            chapter = self.test_chapters[i % len(self.test_chapters)]
            self._assign_member_to_chapter_direct(member, chapter)
            if i < 4:  # Don't remove the last one
                chapter_doc = frappe.get_doc("Chapter", chapter)
                chapter_doc.remove_member(member, leave_reason=f"Historical test {i}")

        # Time the assignment
        import time

        start_time = time.time()

        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=target_chapter, note="Performance test"
        )

        end_time = time.time()
        execution_time = end_time - start_time

        self.assertTrue(result.get("success"), "Performance test assignment should succeed")
        self.assertLess(execution_time, 10.0, "Assignment should complete within 10 seconds")

    # ==================== CLEANUP AND VALIDATION TESTS ====================

    def test_13_data_integrity_after_assignment(self):
        """Test that data integrity is maintained after assignment operations"""
        member = self.test_members[4]

        # Create complex initial state
        self._assign_member_to_chapter_direct(member, self.test_chapters[0])
        self._create_board_membership(member, self.test_chapters[0], "Secretary")

        # Perform assignment with cleanup
        result = assign_member_to_chapter_with_cleanup(
            member=member, chapter=self.test_chapters[1], note="Data integrity test"
        )

        self.assertTrue(result.get("success"), "Assignment should succeed")

        # Verify data integrity
        # 1. No orphaned chapter memberships
        orphaned_memberships = frappe.db.sql(
            """
            SELECT cm.name
            FROM `tabChapter Member` cm
            LEFT JOIN `tabChapter` c ON c.name = cm.parent
            WHERE cm.member = %s AND cm.enabled = 1 AND c.name IS NULL
        """,
            member,
        )
        self.assertEqual(len(orphaned_memberships), 0, "No orphaned chapter memberships should exist")

        # 2. No active board memberships without chapter membership
        inconsistent_board = frappe.db.sql(
            """
            SELECT cbm.name
            FROM `tabChapter Board Member` cbm
            LEFT JOIN `tabChapter Member` cm ON cm.member = cbm.member
                AND cm.parent = cbm.chapter AND cm.enabled = 1
            WHERE cbm.member = %s AND cbm.status = 'Active' AND cm.name IS NULL
        """,
            member,
        )
        self.assertEqual(len(inconsistent_board), 0, "No active board memberships without chapter membership")

        # 3. Member should be in exactly one active chapter
        active_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent"]
        )
        self.assertEqual(len(active_memberships), 1, "Member should be in exactly one chapter")


def run_comprehensive_tests():
    """Run all comprehensive chapter assignment tests"""
    print("Starting comprehensive chapter assignment tests...")

    # Run the test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterAssignmentComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    tests_run = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)

    print(f"\n{'=' * 50}")
    print("COMPREHENSIVE TEST RESULTS")
    print(f"{'=' * 50}")
    print(f"Tests run: {tests_run}")
    print(f"Failures: {failures}")
    print(f"Errors: {errors}")
    print(f"Success rate: {((tests_run - failures - errors) / tests_run * 100):.1f}%")

    if failures > 0:
        print("\nFAILURES:")
        for test, error in result.failures:
            print(f"- {test}: {error}")

    if errors > 0:
        print("\nERRORS:")
        for test, error in result.errors:
            print(f"- {test}: {error}")

    return result.wasSuccessful()


if __name__ == "__main__":
    run_comprehensive_tests()
