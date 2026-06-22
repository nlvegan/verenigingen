"""
Additional real-DB coverage for the chapter ``MemberManager``
(``verenigingen/verenigingen/doctype/chapter/managers/member_manager.py``).

The base suite covers add/join/approve/reject/remove/update/list/search/export/
stats. This file fills:

- ``bulk_add_members`` (string-JSON parse, empty, mixed success/error, summary)
- ``_validate_url`` / ``_validate_member_data`` validators
- ``request_to_join`` reactivation branch (disabled+enabled member re-requests)
- ``_remove_stale_member_links`` (a members row pointing at a deleted Member)
- ``handle_member_additions`` new-chapter (old_doc=None) branch
- ``_get_recent_member_changes`` empty result

Everything is exercised through ``chapter.member_manager`` (production path) with
real Member/Chapter rows from the factory. No business logic is mocked.
"""

import json

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberManagerCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._prev_run_events_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True
        self.chapter = self.create_test_chapter(
            chapter_name=f"MMCov Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="MMCov",
            last_name="Primary",
            email=f"mmcov.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_run_events_sync
        super().tearDown()

    @property
    def manager(self):
        return self.chapter.member_manager

    def _reload(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_member(self, first="Extra", status="Active"):
        return self.create_test_member(
            first_name=first,
            last_name="MMCov",
            email=f"mmcov.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
        )

    # ------------------------------------------------------------ bulk_add_members

    def test_bulk_add_members_empty_list(self):
        result = self.manager.bulk_add_members([])
        self.assertFalse(result["success"])
        self.assertIn("No members", result["error"])

    def test_bulk_add_members_accepts_json_string(self):
        m2 = self._make_member(first="BulkJSON")
        payload = json.dumps([{"member_id": self.member.name}, {"member_id": m2.name}])
        result = self.manager.bulk_add_members(payload)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 2)
        self.assertIn(self.member.name, result["added_members"])

    def test_bulk_add_members_mixed_success_and_errors(self):
        m2 = self._make_member(first="BulkOK")
        data = [
            {"member_id": self.member.name},
            {"introduction": "no id here"},  # missing member_id -> error
            {"member_id": "NONEXISTENT-MEMBER-XYZ"},  # does not exist -> error
            {"member_id": m2.name},
        ]
        # add_member() logs an Error Log when it throws for the nonexistent member;
        # bulk_add_members catches it and records the failure line. The logging is
        # expected here (expectErrorLog marks the pattern ignorable in tearDown).
        self.expectErrorLog("Failed to add member")
        result = self.manager.bulk_add_members(data)
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 2)
        self.assertGreaterEqual(len(result["errors"]), 2)

    def test_bulk_add_members_skips_already_present(self):
        # Pre-add the member, then bulk-add it again: counted as an error line,
        # not a processed add.
        self.manager.add_member(self.member.name, notify=False)
        self._reload()
        result = self.chapter.member_manager.bulk_add_members([{"member_id": self.member.name}])
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertTrue(any("Failed to add" in e for e in result["errors"]))

    # ------------------------------------------------------------ _validate_url

    def test_validate_url_accepts_valid(self):
        self.assertTrue(self.manager._validate_url("https://example.org/path"))
        self.assertTrue(self.manager._validate_url("http://localhost:8000"))

    def test_validate_url_rejects_invalid(self):
        self.assertFalse(self.manager._validate_url("not-a-url"))
        self.assertFalse(self.manager._validate_url("ftp://example.org"))

    # ------------------------------------------------------------ _validate_member_data

    def test_validate_member_data_rejects_overlong_introduction(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertRaises(frappe.ValidationError):
            self.manager._validate_member_data(member_doc, introduction="x" * 501)

    def test_validate_member_data_rejects_bad_url(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        with self.assertRaises(frappe.ValidationError):
            self.manager._validate_member_data(member_doc, website_url="nope")

    def test_validate_member_data_warns_for_inactive_member(self):
        # A non-Active member triggers an msgprint warning (no raise).
        inactive = self._make_member(first="InactiveWarn", status="Suspended")
        member_doc = frappe.get_doc("Member", inactive.name)
        # Should not raise; the warning path executes.
        self.manager._validate_member_data(member_doc)

    # ------------------------------------------------------------ request_to_join reactivation

    def test_request_to_join_reactivates_inactive_enabled_member(self):
        # Add member, then update to Inactive status while keeping enabled, so the
        # reactivation branch (status == Inactive and enabled) fires on re-request.
        self.manager.add_member(self.member.name, notify=False)
        self._reload()
        row = self.manager._find_chapter_member(self.member.name)
        row.status = "Inactive"
        row.enabled = 1
        self.chapter.save()
        self._reload()

        result = self.chapter.member_manager.request_to_join(self.member.name, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "rejoin_requested")
        self._reload()
        row = self.chapter.member_manager._find_chapter_member(self.member.name)
        self.assertEqual(row.status, "Pending")

    # ------------------------------------------------------------ _remove_stale_member_links

    def test_remove_stale_member_links_drops_deleted_member_row(self):
        # Create a member, add it, then hard-delete the Member so the chapter row
        # references a non-existent member. _remove_stale_member_links must drop it.
        ghost = self._make_member(first="Ghost")
        ghost_name = ghost.name
        self.manager.add_member(ghost_name, notify=False)
        self._reload()
        # Remove from our tracked docs so teardown doesn't choke, then delete.
        frappe.delete_doc("Member", ghost_name, force=True, ignore_permissions=True)

        mgr = self.chapter.member_manager
        self.assertIsNotNone(mgr._find_chapter_member(ghost_name))
        mgr._remove_stale_member_links()
        self.assertIsNone(
            mgr._find_chapter_member(ghost_name), "stale row for a deleted member must be removed"
        )

    # ------------------------------------------------------------ handle_member_additions (new chapter)

    def test_handle_member_additions_new_chapter_records_all_enabled(self):
        # old_doc=None path: every enabled member in the chapter is walked and a
        # history row recorded. We append the members row directly (without going
        # through add_member, which already records history) so the new-chapter
        # branch is the FIRST writer of this member's history row.
        self.chapter.append(
            "members",
            {
                "member": self.member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        self.chapter.save()
        self._reload()

        self.chapter.member_manager.handle_member_additions(old_doc=None)
        history = frappe.get_all(
            "Chapter Membership History",
            filters={"parent": self.member.name, "chapter_name": self.chapter.name},
        )
        self.assertGreater(len(history), 0, "new-chapter path must record enabled members")

    # ------------------------------------------------------------ _get_recent_member_changes

    def test_get_recent_member_changes_empty(self):
        # A fresh chapter with no matching comments returns an empty list.
        changes = self.manager._get_recent_member_changes("removed")
        self.assertEqual(changes, [])

    # ------------------------------------------------------------ get_members with_details deleted member

    def test_get_members_with_details_tolerates_deleted_member(self):
        ghost = self._make_member(first="DetailGhost")
        ghost_name = ghost.name
        self.manager.add_member(ghost_name, notify=False)
        self._reload()
        frappe.delete_doc("Member", ghost_name, force=True, ignore_permissions=True)
        # with_details swallows the lookup failure for the deleted member.
        members = self.chapter.member_manager.get_members(with_details=True)
        ghost_rows = [m for m in members if m["member_id"] == ghost_name]
        # The row is still listed (enabled), just without detail fields.
        self.assertEqual(len(ghost_rows), 1)
        self.assertNotIn("email", ghost_rows[0])
