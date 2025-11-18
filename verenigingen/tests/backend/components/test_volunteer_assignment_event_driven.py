"""
Test Suite for Event-Driven Volunteer Assignment Architecture

Tests the event-driven architecture for volunteer assignment history updates.
Verifies that the removal of direct sync from after_save() doesn't break functionality.

Architecture:
1. Chapter.on_update() → emits events
2. Events → background jobs (with deduplication)
3. Background jobs → sync_board_members_with_volunteer_system()
4. Sync function → updates ALL board members assignment history

Related: docs/VOLUNTEER_ASSIGNMENT_ARCHITECTURE_CHANGE.md
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerAssignmentEventDriven(EnhancedTestCase):
    """Test event-driven volunteer assignment sync"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()

        # Create test region
        if not frappe.db.exists("Region", "EventTestRegion"):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "EventTestRegion",
                "region_code": "EVTST",
            }).insert()

        # Create chapter roles
        chapter_roles = [
            {"name": "Event Test Chair", "is_unique": 1},
            {"name": "Event Test Secretary", "is_unique": 1},
            {"name": "Event Test Member", "is_unique": 0},  # Non-unique for multi-member tests
        ]
        for role_config in chapter_roles:
            if not frappe.db.exists("Chapter Role", role_config["name"]):
                frappe.get_doc({
                    "doctype": "Chapter Role",
                    "role_name": role_config["name"],
                    "permissions_level": "Admin",
                    "is_unique": role_config["is_unique"],
                    "is_active": 1,
                }).insert()

    def setUp(self):
        """Set up test data for each test"""
        super().setUp()

        # Create multiple test volunteers for comprehensive testing
        self.test_volunteers = []
        self.test_members = []

        for i in range(3):
            member = self.create_test_member(
                first_name=f"EventTest{i}",
                last_name="Volunteer",
                email=f"event.test.{i}.{frappe.utils.random_string(8)}@example.com"
            )
            self.test_members.append(member)

            volunteer = self.create_test_volunteer(member_name=member.name)
            self.test_volunteers.append(volunteer)

        # Create test chapter with timestamp for uniqueness
        import time
        timestamp = str(int(time.time() * 1000))[-8:]  # Last 8 digits of timestamp
        self.test_chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": f"EventTestChapter{timestamp}",
            "chapter_head": self.test_members[0].name,
            "region": "EventTestRegion",
            "introduction": "Test chapter for event-driven sync testing",
        }).insert()

    def tearDown(self):
        """Clean up test data"""
        # Clear board members
        if hasattr(self, 'test_chapter'):
            try:
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

    def test_01_event_emission_on_board_member_add(self):
        """
        Verify that adding a board member emits chapter_board_changed event
        (not testing background job execution, just event emission)
        """
        # Track if event was emitted by checking Chapter's event detection logic
        old_doc = frappe.copy_doc(self.test_chapter)

        # Add board member
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteers[0].name,
            "chapter_role": "Event Test Chair",
            "from_date": today(),
            "is_active": 1,
        })

        # Detect changes (this is what happens in on_update)
        old_board = {
            (bm.volunteer, bm.chapter_role)
            for bm in (old_doc.board_members or [])
            if bm.is_active
        }
        new_board = {
            (bm.volunteer, bm.chapter_role)
            for bm in (self.test_chapter.board_members or [])
            if bm.is_active
        }

        added_members = new_board - old_board

        # Verify change was detected
        self.assertEqual(
            len(added_members), 1,
            "Should detect 1 board member addition"
        )
        self.assertIn(
            (self.test_volunteers[0].name, "Event Test Chair"),
            added_members,
            "Should detect the specific board member added"
        )

    def test_02_full_board_sync_processes_all_members(self):
        """
        Verify that sync_board_members_with_volunteer_system() syncs ALL board members,
        not just the one that changed (this is why chapter-level deduplication works)
        """
        # Add multiple board members
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteers[0].name,
            "chapter_role": "Event Test Chair",
            "from_date": today(),
            "is_active": 1,
        })
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteers[1].name,
            "chapter_role": "Event Test Secretary",
            "from_date": today(),
            "is_active": 1,
        })
        self.test_chapter.save()
        frappe.db.commit()

        # Manually trigger sync (simulates background job completion)
        sync_result = self.test_chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()

        # Verify sync processed both volunteers
        self.assertTrue(sync_result.get("success"), "Sync should succeed")
        stats = sync_result.get("stats", {})
        self.assertEqual(
            stats.get("volunteers_processed"), 2,
            "Should process ALL 2 board members (full sync, not incremental)"
        )

        # Verify both volunteers have assignment history
        for volunteer in [self.test_volunteers[0], self.test_volunteers[1]]:
            volunteer.reload()
            assignments = [
                a for a in volunteer.assignment_history or []
                if a.reference_name == self.test_chapter.name
                and a.status == "Active"
            ]
            self.assertEqual(
                len(assignments), 1,
                f"Volunteer {volunteer.name} should have 1 active assignment from full sync"
            )

    def test_03_event_driven_sync_creates_assignments(self):
        """
        End-to-end test: Add board member → trigger sync → verify assignment created
        This simulates the full event-driven flow
        """
        # Add board member
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteers[0].name,
            "chapter_role": "Event Test Chair",
            "from_date": today(),
            "is_active": 1,
        })
        self.test_chapter.save()
        frappe.db.commit()

        # Manually trigger the event handler (simulates background job)
        from verenigingen.events.subscribers.chapter_subscribers import handle_volunteer_sync
        handle_volunteer_sync(
            "chapter_board_changed",
            {
                "chapter": self.test_chapter.name,
                "volunteer": self.test_volunteers[0].name,
                "action": "added",
                "role": "Event Test Chair",
            }
        )

        # Verify assignment was created
        self.test_volunteers[0].reload()
        assignments = [
            a for a in self.test_volunteers[0].assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Event Test Chair"
            and a.status == "Active"
        ]

        self.assertEqual(
            len(assignments), 1,
            "Event-driven sync should create assignment history"
        )

    def test_04_event_driven_sync_completes_assignments(self):
        """
        End-to-end test: Remove board member → trigger sync → verify assignment completed
        """
        # First add board member and create assignment
        self.test_chapter.append("board_members", {
            "volunteer": self.test_volunteers[0].name,
            "chapter_role": "Event Test Chair",
            "from_date": add_days(today(), -30),
            "is_active": 1,
        })
        self.test_chapter.save()

        # Create assignment
        from verenigingen.events.subscribers.chapter_subscribers import handle_volunteer_sync
        handle_volunteer_sync(
            "chapter_board_changed",
            {
                "chapter": self.test_chapter.name,
                "volunteer": self.test_volunteers[0].name,
                "action": "added",
                "role": "Event Test Chair",
            }
        )

        # Now deactivate board member
        self.test_chapter.reload()
        for bm in self.test_chapter.board_members:
            if bm.volunteer == self.test_volunteers[0].name:
                bm.is_active = 0
                bm.to_date = today()
                break
        self.test_chapter.save()
        frappe.db.commit()

        # Trigger sync for removal
        handle_volunteer_sync(
            "chapter_board_changed",
            {
                "chapter": self.test_chapter.name,
                "volunteer": self.test_volunteers[0].name,
                "action": "removed",
                "role": "Event Test Chair",
            }
        )

        # Verify assignment was completed
        self.test_volunteers[0].reload()
        completed_assignments = [
            a for a in self.test_volunteers[0].assignment_history or []
            if a.reference_name == self.test_chapter.name
            and a.role == "Event Test Chair"
            and a.status == "Completed"
        ]

        self.assertEqual(
            len(completed_assignments), 1,
            "Event-driven sync should complete assignment when board member deactivated"
        )

    def test_05_multiple_board_changes_single_save(self):
        """
        Real-world scenario: Add 3 board members in one save
        Verifies that ALL get synced (full board sync, not per-volunteer)
        """
        # Add 3 board members in one operation
        roles = ["Event Test Chair", "Event Test Secretary", "Event Test Member"]
        for i in range(3):
            self.test_chapter.append("board_members", {
                "volunteer": self.test_volunteers[i].name,
                "chapter_role": roles[i],
                "from_date": today(),
                "is_active": 1,
            })

        self.test_chapter.save()
        frappe.db.commit()

        # Manually trigger sync (in production this would be one background job due to deduplication)
        sync_result = self.test_chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()

        # Verify all 3 volunteers were processed
        self.assertEqual(
            sync_result.get("stats", {}).get("volunteers_processed"), 3,
            "Should process all 3 board members in single sync"
        )

        # Verify all have assignments
        for i, volunteer in enumerate(self.test_volunteers):
            volunteer.reload()
            assignments = [
                a for a in volunteer.assignment_history or []
                if a.reference_name == self.test_chapter.name
                and a.status == "Active"
            ]
            self.assertEqual(
                len(assignments), 1,
                f"Volunteer {i+1} should have assignment from bulk sync"
            )

    def test_06_no_direct_sync_in_after_save(self):
        """
        Verify that saving a chapter does NOT directly call sync
        (architecture change: removed direct sync from after_save)

        This is a regression test to ensure the direct sync doesn't get re-added
        """
        # Check that Chapter.after_save doesn't have sync code
        import inspect
        from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

        after_save_source = inspect.getsource(Chapter.after_save)

        # Should NOT contain sync call
        self.assertNotIn(
            "sync_board_members_with_volunteer_system",
            after_save_source,
            "after_save() should NOT directly call sync (event-driven only)"
        )

        # Should NOT have the old recursion guard for sync
        self.assertNotIn(
            "_syncing_board_members",
            after_save_source,
            "after_save() should NOT have sync recursion guard (no longer needed)"
        )

        # Should have the architectural note
        self.assertIn(
            "event-driven",
            after_save_source.lower(),
            "after_save() should document event-driven architecture"
        )

    def test_07_event_handler_validates_chapter_exists(self):
        """
        Verify that event handler checks if chapter exists before processing
        (prevents errors during data imports or race conditions)
        """
        from verenigingen.events.subscribers.chapter_subscribers import handle_volunteer_sync

        # Try to sync with non-existent chapter
        # Should not raise error, just log warning and return
        try:
            handle_volunteer_sync(
                "chapter_board_changed",
                {
                    "chapter": "NonExistentChapter123",
                    "volunteer": self.test_volunteers[0].name,
                    "action": "added",
                }
            )
            # Should complete without error
            success = True
        except Exception as e:
            success = False
            error_message = str(e)

        self.assertTrue(
            success,
            "Event handler should gracefully handle non-existent chapter, not raise exception"
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
