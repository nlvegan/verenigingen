"""
Additional real-DB coverage for the chapter ``VolunteerIntegrationManager``
(``verenigingen/verenigingen/doctype/chapter/managers/volunteer_integration_manager.py``).

The base suite (``test_volunteer_integration_manager.py``) covers the happy
paths of add/complete/sync/statistics/consistency. This file fills the remaining
uncovered branches:

- ``cleanup_orphaned_assignments`` (an entire method): completes Active chapter
  assignments belonging to volunteers no longer on the board, and leaves
  on-board volunteers' assignments untouched.
- ``migrate_volunteer_assignments`` create + complete branches (a board member
  whose assignment record is missing).
- ``_get_volunteer_details`` cache (hit + miss + unknown-volunteer fallback).
- ``_clear_volunteer_cache`` full clear.
- error branches that return the documented failure shapes.

Everything is exercised through ``chapter.volunteer_integration_manager`` (the
production access path), using real Volunteer/Member/Chapter Role/board rows
created via the factory. No business logic is mocked.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerIntegrationManagerCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"VIMCov Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    @property
    def manager(self):
        return self.chapter.volunteer_integration_manager

    def _reload(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_role(self):
        role_name = f"VIMCovRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first="VIMCov"):
        member = self.create_test_member(
            first_name=first,
            last_name="Cleanup",
            email=f"vimcov.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        vol = self.create_test_volunteer(member=member.name)
        return member, vol

    def _seat(self, role_name=None, is_active=1, from_date=None, to_date=None, first="VIMCov"):
        member, vol = self._make_volunteer(first=first)
        if role_name is None:
            role_name = self._make_role()
        self.chapter.append(
            "board_members",
            {
                "volunteer": vol.name,
                "volunteer_name": vol.volunteer_name,
                "chapter_role": role_name,
                "from_date": from_date or today(),
                "to_date": to_date,
                "is_active": is_active,
            },
        )
        self.chapter.save()
        self._reload()
        return member, vol, role_name

    # ------------------------------------------------- cleanup_orphaned_assignments

    def test_cleanup_completes_assignments_for_off_board_volunteer(self):
        # Give a volunteer an Active chapter assignment, but do NOT seat them on
        # the board. cleanup must find that orphaned Active assignment and mark
        # it Completed with today's end_date.
        _m, vol = self._make_volunteer(first="OffBoard")
        role = self._make_role()
        self.manager.add_volunteer_assignment_history(vol.name, role, add_days(today(), -10))

        result = self.chapter.volunteer_integration_manager.cleanup_orphaned_assignments()
        self.assertTrue(result["success"])
        stats = result["stats"]
        self.assertGreaterEqual(stats["volunteers_checked"], 1)
        self.assertGreaterEqual(stats["orphaned_assignments"], 1)
        self.assertGreaterEqual(stats["assignments_cleaned"], 1)

        # The assignment is now Completed and dated today.
        mgr = self.chapter.volunteer_integration_manager
        mgr._clear_volunteer_cache(vol.name)
        history = mgr.get_volunteer_assignment_history(vol.name)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "Completed")
        self.assertEqual(str(history[0]["end_date"]), today())

    def test_cleanup_leaves_on_board_volunteer_untouched(self):
        # A volunteer currently seated (active) on the board should NOT have their
        # active assignment cleaned up — they are still a current_volunteer.
        _m, vol, _role = self._seat(first="OnBoard")

        result = self.chapter.volunteer_integration_manager.cleanup_orphaned_assignments()
        self.assertTrue(result["success"])
        # The seated volunteer's row is in current_volunteers, so it is skipped:
        # no orphaned/cleaned assignments attributable to them.
        self.assertEqual(result["stats"]["assignments_cleaned"], 0)

        mgr = self.chapter.volunteer_integration_manager
        mgr._clear_volunteer_cache(vol.name)
        history = mgr.get_volunteer_assignment_history(vol.name)
        active = [h for h in history if h["status"] == "Active"]
        self.assertEqual(len(active), 1, "seated volunteer keeps their active assignment")

    def test_cleanup_empty_chapter_no_assignments(self):
        result = self.manager.cleanup_orphaned_assignments()
        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["volunteers_checked"], 0)
        self.assertEqual(result["stats"]["assignments_cleaned"], 0)

    # ------------------------------------------------- migrate_volunteer_assignments

    def test_migration_creates_missing_active_assignment(self):
        # Seat a board member, then delete the assignment row that seating created
        # so migration has to recreate it.
        _m, vol, _role = self._seat(first="MigrateCreate")
        # Remove the assignment history rows for a clean "missing" state.
        volunteer_doc = frappe.get_doc("Volunteer", vol.name)
        volunteer_doc.set("assignment_history", [])
        volunteer_doc.save()
        self.chapter.volunteer_integration_manager._clear_volunteer_cache(vol.name)

        result = self.chapter.volunteer_integration_manager.migrate_volunteer_assignments()
        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["board_members_processed"], 1)
        self.assertEqual(result["stats"]["assignments_created"], 1)

    def test_migration_completes_missing_completed_assignment(self):
        # An inactive board member with a to_date but no completed assignment record
        # should get one created by migration.
        start = add_days(today(), -60)
        _m, vol, _role = self._seat(first="MigrateComplete", is_active=0, from_date=start, to_date=today())
        volunteer_doc = frappe.get_doc("Volunteer", vol.name)
        volunteer_doc.set("assignment_history", [])
        volunteer_doc.save()
        self.chapter.volunteer_integration_manager._clear_volunteer_cache(vol.name)

        result = self.chapter.volunteer_integration_manager.migrate_volunteer_assignments()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["stats"]["assignments_fixed"], 1)

    # ------------------------------------------------- _get_volunteer_details

    def test_get_volunteer_details_caches_real_volunteer(self):
        _m, vol = self._make_volunteer(first="Details")
        mgr = self.manager
        details = mgr._get_volunteer_details(vol.name)
        self.assertEqual(details["name"], vol.volunteer_name)
        self.assertEqual(details["member"], vol.member)
        self.assertIn(vol.name, mgr.volunteer_cache)
        # Second call hits the cache and returns the same dict.
        self.assertIs(mgr._get_volunteer_details(vol.name), details)

    def test_get_volunteer_details_unknown_volunteer_fallback(self):
        mgr = self.manager
        details = mgr._get_volunteer_details("NO-SUCH-VOLUNTEER-XYZ")
        self.assertEqual(details["name"], "NO-SUCH-VOLUNTEER-XYZ")
        self.assertEqual(details["status"], "Unknown")
        self.assertIsNone(details["member"])

    # ------------------------------------------------- _clear_volunteer_cache (full)

    def test_clear_volunteer_cache_full(self):
        _m, vol = self._make_volunteer(first="CacheClear")
        mgr = self.manager
        mgr._get_volunteer_details(vol.name)
        self.manager.get_volunteer_assignment_history(vol.name)
        self.assertTrue(mgr.volunteer_cache)
        # No argument -> clears everything.
        mgr._clear_volunteer_cache()
        self.assertEqual(mgr.volunteer_cache, {})
        self.assertEqual(mgr.assignment_cache, {})

    # ------------------------------------------------- error branches

    def test_add_assignment_history_nonexistent_volunteer_returns_false(self):
        # AssignmentHistoryManager raises for a missing volunteer; the manager
        # catches it, logs an error, and returns False.
        self.expectErrorLog("Error adding volunteer assignment history")
        ok = self.manager.add_volunteer_assignment_history("NO-SUCH-VOL", self._make_role(), today())
        self.assertFalse(ok)

    def test_update_assignment_history_nonexistent_volunteer_returns_false(self):
        self.expectErrorLog("Error updating volunteer assignment history")
        ok = self.manager.update_volunteer_assignment_history(
            "NO-SUCH-VOL", self._make_role(), add_days(today(), -5), today()
        )
        self.assertFalse(ok)
