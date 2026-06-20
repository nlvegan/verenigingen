"""
Real-DB tests for the chapter ``VolunteerIntegrationManager``
(``verenigingen/verenigingen/doctype/chapter/managers/volunteer_integration_manager.py``).

The manager mediates between chapter board members and the volunteer assignment
history (add / complete assignment records, sync, statistics, consistency,
migration). It is reached in production via ``chapter.volunteer_integration_manager``;
tests resolve it the same way. Real Volunteer / Member / Chapter Role / board-member
rows are created via the factory and assignment history is read back from the
volunteer document, so the delegation to AssignmentHistoryManager is exercised for
real (no business-logic mocking).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerIntegrationManager(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"VIM Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    @property
    def manager(self):
        return self.chapter.volunteer_integration_manager

    def _reload(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_role(self, is_chair=0):
        role_name = f"VIMRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_chair": is_chair,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first="VIM"):
        member = self.create_test_member(
            first_name=first,
            last_name="Integration",
            email=f"vim.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        vol = self.create_test_volunteer(member=member.name)
        return member, vol

    def _seat(self, role_name=None, is_active=1, from_date=None, to_date=None, first="VIM"):
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

    # ----------------------------------------- add_volunteer_assignment_history

    def test_add_assignment_history_persists_active_record(self):
        _m, vol = self._make_volunteer(first="Adder")
        role = self._make_role()
        with self.assertNoErrorLog():
            ok = self.manager.add_volunteer_assignment_history(vol.name, role, today())
        self.assertTrue(ok)

        history = self.manager.get_volunteer_assignment_history(vol.name)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], role)
        self.assertEqual(history[0]["status"], "Active")
        self.assertEqual(history[0]["end_date"], None)

    def test_update_assignment_history_completes_record(self):
        _m, vol = self._make_volunteer(first="Completer")
        role = self._make_role()
        start = add_days(today(), -30)
        self.manager.add_volunteer_assignment_history(vol.name, role, start)
        # Clear cache so the read reflects DB after completion
        self.manager._clear_volunteer_cache(vol.name)

        with self.assertNoErrorLog():
            ok = self.manager.update_volunteer_assignment_history(vol.name, role, start, today())
        self.assertTrue(ok)

        self.manager._clear_volunteer_cache(vol.name)
        history = self.manager.get_volunteer_assignment_history(vol.name)
        completed = [h for h in history if h["status"] == "Completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(str(completed[0]["end_date"]), today())

    def test_get_history_only_returns_this_chapters_assignments(self):
        _m, vol = self._make_volunteer(first="Scoped")
        role = self._make_role()
        self.manager.add_volunteer_assignment_history(vol.name, role, today())

        # Add an assignment referencing a DIFFERENT chapter
        other = self.create_test_chapter(
            chapter_name=f"VIM Other {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
        )
        other.volunteer_integration_manager.add_volunteer_assignment_history(vol.name, role, today())

        self.manager._clear_volunteer_cache(vol.name)
        history = self.manager.get_volunteer_assignment_history(vol.name)
        self.assertEqual(len(history), 1, "manager must only see its own chapter's assignments")

    def test_get_history_nonexistent_volunteer_returns_empty(self):
        # Exception path -> returns [] (logs an error, which is expected here).
        # log_action with level "error" goes through frappe.logger(), not Error Log,
        # but mark the pattern as expected to be safe.
        self.expectErrorLog("Error getting volunteer assignment history")
        history = self.manager.get_volunteer_assignment_history("NO-SUCH-VOLUNTEER")
        self.assertEqual(history, [])

    # ----------------------------------------- sync_board_members_with_volunteer_system

    def test_sync_processes_active_board_member(self):
        # Seating already creates the active assignment via the board hook;
        # sync re-affirms it and reports success per processed volunteer.
        _m, vol, role = self._seat(first="SyncA")

        result = self.chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()
        self.assertTrue(result["success"])
        stats = result["stats"]
        self.assertEqual(stats["volunteers_processed"], 1)
        self.assertGreaterEqual(stats["assignments_added"], 1)
        self.assertEqual(stats["errors"], [])

    def test_sync_completes_inactive_member_with_end_date(self):
        # An inactive board member with a to_date should be marked completed.
        start = add_days(today(), -30)
        _m, vol, role = self._seat(
            first="SyncInactive", is_active=0, from_date=start, to_date=today()
        )
        result = self.chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["stats"]["assignments_updated"], 1)

    # ----------------------------------------- get_chapter_volunteer_statistics

    def test_statistics_count_active_and_roles(self):
        _m, _vol, role = self._seat(first="StatA")
        self._seat(role_name=role, first="StatB")  # same role, second active member

        stats = self.chapter.volunteer_integration_manager.get_chapter_volunteer_statistics()
        self.assertEqual(stats["total_volunteers"], 2)
        self.assertEqual(stats["active_volunteers"], 2)
        self.assertEqual(stats["role_distribution"].get(role), 2)
        self.assertEqual(stats["volunteers_with_members"], 2)
        # tenure computed from from_date..today (seated today -> 0 days avg)
        self.assertIn("average_tenure_days", stats)

    def test_statistics_empty_board(self):
        stats = self.manager.get_chapter_volunteer_statistics()
        self.assertEqual(stats["total_volunteers"], 0)
        self.assertEqual(stats["active_volunteers"], 0)

    # ----------------------------------------- validate_volunteer_board_consistency

    def test_consistency_seated_active_member_is_consistent(self):
        # Seating creates the active assignment record, so the active board
        # member is consistent with no issues and no missing-record warnings.
        _m, _vol, _role = self._seat(first="Consistent")
        result = self.chapter.volunteer_integration_manager.validate_volunteer_board_consistency()
        self.assertTrue(result["is_consistent"])
        self.assertEqual(result["issues"], [])
        self.assertFalse(any("no active assignment record" in w for w in result["warnings"]))
        self.assertEqual(result["total_board_members"], 1)

    def test_consistency_empty_board(self):
        result = self.manager.validate_volunteer_board_consistency()
        self.assertTrue(result["is_consistent"])
        self.assertEqual(result["total_board_members"], 0)

    # ----------------------------------------- migrate_volunteer_assignments

    def test_migration_idempotent_when_active_record_exists(self):
        # Seating already created the active assignment, so migration is a no-op:
        # it processes the board member but creates nothing (record exists).
        _m, vol, _role = self._seat(first="Migrate")
        result = self.chapter.volunteer_integration_manager.migrate_volunteer_assignments()
        self.assertTrue(result["success"])
        self.assertEqual(result["stats"]["board_members_processed"], 1)
        self.assertEqual(result["stats"]["assignments_created"], 0)
        self.assertEqual(result["stats"]["errors"], [])

    # ----------------------------------------- get_summary

    def test_get_summary_shape(self):
        self._seat(first="Summary")
        summary = self.chapter.volunteer_integration_manager.get_summary()
        self.assertIn("volunteer_statistics", summary)
        self.assertIn("consistency_check", summary)
        self.assertIn(summary["integration_health"], ("Good", "Issues Found"))

    # ----------------------------------------- pure helper

    def test_calculate_assignment_duration(self):
        self.assertEqual(self.manager._calculate_assignment_duration("2024-01-01", "2024-01-11"), 10)
        # invalid date -> 0
        self.assertEqual(self.manager._calculate_assignment_duration("garbage", "alsobad"), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
