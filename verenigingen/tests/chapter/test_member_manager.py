"""
Real-integration tests for the chapter ``MemberManager``
``verenigingen/verenigingen/doctype/chapter/managers/member_manager.py``.

The manager owns chapter membership operations (add / join-request / approve /
reject / remove / update / list / search / export / stats). It is reached in
production via ``chapter_doc.member_manager`` (a lazily-built
``MemberManager(self)``), so every test resolves the manager that way to mirror
the real call path rather than instantiating the class directly.

Tests create real Members and Chapters via the test factory (no business-logic
mocking) and run as Administrator. Notification helpers send through the unified
EmailService and are wrapped in try/except in production, so they are exercised
indirectly via approve/reject/join and asserted only on their observable side
effects (status, history, comments) -- the email send itself is a no-op in the
test environment.
"""

import json

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberManager(VereningingenTestCase):
    """Exercise the chapter MemberManager end to end via chapter.member_manager."""

    def setUp(self):
        super().setUp()
        # Membership-history side effects are partly event-driven; run subscribers
        # inline so history rows are created deterministically within the test.
        self._prev_run_events_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True

        self.chapter = self.create_test_chapter(
            chapter_name=f"MemberMgr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="MemberMgr",
            last_name="Primary",
            email=f"membermgr.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_run_events_sync
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    @property
    def manager(self):
        """Resolve the manager the same way production does."""
        return self.chapter.member_manager

    def _reload_chapter(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_member(self, status="Active", first="Extra"):
        return self.create_test_member(
            first_name=first,
            last_name="MemberMgr",
            email=f"membermgr.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
        )

    # ------------------------------------------------------------------ add_member

    def test_add_member_happy_path(self):
        result = self.manager.add_member(self.member.name, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "added")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "Active")
        self.assertTrue(row.enabled)
        self.assertEqual(str(row.chapter_join_date), today())

    def test_add_member_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_member("", notify=False)

    def test_add_member_nonexistent_member_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_member("NONEXISTENT-MEMBER-XYZ", notify=False)

    def test_add_member_already_in_chapter_is_rejected(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.add_member(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_exists")

    def test_add_member_inactive_member_is_disabled_in_chapter(self):
        # Members who are not Active should be force-disabled / Inactive in the
        # chapter regardless of the requested enabled flag.
        suspended = self._make_member(status="Suspended", first="Suspended")
        result = self.manager.add_member(suspended.name, enabled=True, notify=False)
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

    def test_add_member_honours_explicit_join_date(self):
        result = self.manager.add_member(self.member.name, join_date="2024-01-15", notify=False)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(str(row.chapter_join_date), "2024-01-15")

    def test_add_member_reenables_disabled_member(self):
        # First add then disable (non-permanent) so a disabled row exists.
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        self.manager.remove_member(self.member.name, leave_reason="testing", notify=False)
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertFalse(row.enabled)

        result = self.manager.add_member(self.member.name, enabled=True, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "re-enabled")
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        self.assertIsNone(row.leave_reason)

    # ------------------------------------------------------------------ request_to_join

    def test_request_to_join_creates_pending(self):
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "requested")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "Pending")

        # Directly guard the add_membership_history(status="Pending") call: the
        # Chapter Member row above is written before it, so without this assertion
        # the kwarg-drift bug would pass undetected.
        history = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Pending",
            },
        )
        self.assertGreater(len(history), 0, "join request should append a Pending history row")

    def test_request_to_join_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.request_to_join("", notify=False)

    def test_request_to_join_notifies_active_board_without_error(self):
        # With an active board member present, the old _notify_board_of_join_request
        # read board_member.member (a nonexistent field) -> AttributeError, swallowed
        # and logged. Assert the join request notification path no longer errors.
        board_member = self.create_test_member(
            first_name="Board",
            last_name="Notify",
            email=f"board.notify.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member_name=board_member.name)
        role_name = f"BoardNotify{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "permissions_level": "Basic"}
        ).insert()
        self.add_board_member_to_chapter(
            self.chapter, volunteer, role_name, email=board_member.email
        )
        self._reload_chapter()

        self.manager.request_to_join(self.member.name, notify=True)

        errored = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%Error sending join request notification%"]},
        )
        self.assertEqual(len(errored), 0, "board notification must not error on a populated board")

    def test_request_to_join_nonexistent_member_returns_failure(self):
        # request_to_join wraps its body in try/except and returns a failure dict
        # rather than raising (the throw is caught and reported).
        result = self.manager.request_to_join("NONEXISTENT-MEMBER-XYZ", notify=False)
        self.assertFalse(result["success"])

    def test_request_to_join_already_pending(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_pending")

    def test_request_to_join_already_active_member(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_member")

    # ------------------------------------------------------------------ approve_member_request

    def test_approve_member_request_happy_path(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name, approved_by="Administrator")
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(row.status, "Active")
        self.assertEqual(str(row.chapter_join_date), today())

    def test_approve_member_request_no_request(self):
        result = self.manager.approve_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("No membership request", result["message"])

    def test_approve_member_request_not_pending(self):
        # An already-active member is not pending and cannot be approved.
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("not pending", result["message"])

    def test_approve_member_request_promotes_row_to_active(self):
        # The join request already wrote a Pending history row;
        # ChapterMembershipHistoryManager deliberately refuses to add an "Active"
        # row while a "Pending" one exists (it warns to use update_membership_status
        # instead). So the observable, durable effect of approval is that the
        # Chapter Member row flips to Active -- assert that rather than a new row.
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name)
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(row.status, "Active")

        # The originating Pending history row is still present (not lost on approve).
        pending = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Pending",
            },
        )
        self.assertGreater(len(pending), 0)

    # ------------------------------------------------------------------ reject_member_request

    def test_reject_member_request_happy_path(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.reject_member_request(
            self.member.name, reason="not eligible", rejected_by="Administrator"
        )
        self.assertTrue(result["success"])

        # The pending row is removed entirely on rejection.
        self._reload_chapter()
        self.assertIsNone(self.manager._find_chapter_member(self.member.name))

    def test_reject_member_request_no_request(self):
        result = self.manager.reject_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("No membership request", result["message"])

    def test_reject_member_request_not_pending(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.reject_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("not pending", result["message"])

    def test_reject_member_request_records_rejected_history(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        self.manager.reject_member_request(self.member.name, reason="dupe")
        # "Rejected" is not a valid Chapter Membership History status; the manager
        # records a declined request as Inactive (see member_manager fix comment).
        history = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Inactive",
            },
        )
        self.assertGreater(len(history), 0, "rejection should append an Inactive history row")

    # ------------------------------------------------------------------ remove_member

    def test_remove_member_disable(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.remove_member(self.member.name, leave_reason="moved away", notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "disabled")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)  # still present, just disabled
        self.assertFalse(row.enabled)
        self.assertEqual(row.leave_reason, "moved away")

    def test_remove_member_permanent(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.remove_member(self.member.name, permanent=True, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "removed")

        self._reload_chapter()
        self.assertIsNone(self.manager._find_chapter_member(self.member.name))

    def test_remove_member_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.remove_member("", notify=False)

    def test_remove_member_not_in_chapter(self):
        result = self.manager.remove_member(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "not_found")

    # ------------------------------------------------------------------ update_member_info

    def test_update_member_info_disable_then_reenable(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()

        # Disable via update -> leave_reason auto-populated.
        result = self.manager.update_member_info(self.member.name, enabled=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "updated")
        self.assertIn("enabled status", result["changes"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertFalse(row.enabled)
        self.assertTrue(row.leave_reason)

        # Re-enable via update -> leave_reason cleared.
        result = self.manager.update_member_info(self.member.name, enabled=True)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        self.assertIsNone(row.leave_reason)

    def test_update_member_info_no_changes(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        # Member is already enabled; setting enabled=True is a no-op.
        result = self.manager.update_member_info(self.member.name, enabled=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_changes")

    def test_update_member_info_not_in_chapter_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.update_member_info(self.member.name, enabled=False)

    # ------------------------------------------------------------------ get_members

    def test_get_members_excludes_disabled_by_default(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="Disabled")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        members = self.manager.get_members()
        ids = {m["member_id"] for m in members}
        self.assertIn(self.member.name, ids)
        self.assertNotIn(disabled.name, ids)

    def test_get_members_include_disabled(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="Disabled2")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        members = self.manager.get_members(include_disabled=True)
        ids = {m["member_id"] for m in members}
        self.assertIn(disabled.name, ids)

    def test_get_members_with_details(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        members = self.manager.get_members(with_details=True)
        row = next(m for m in members if m["member_id"] == self.member.name)
        self.assertEqual(row["email"], self.member.email)
        self.assertIn("status", row)
        self.assertEqual(row["member_name"], self.member.full_name)

    # ------------------------------------------------------------------ search_members

    def test_search_members_by_name(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        results = self.manager.search_members("MemberMgr")
        ids = {m["member_id"] for m in results}
        self.assertIn(self.member.name, ids)

    def test_search_members_no_match(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        results = self.manager.search_members("ZZZ-no-such-name-ZZZ")
        self.assertEqual(results, [])

    def test_search_members_empty_query_returns_all(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        # Empty query short-circuits to get_members().
        results = self.manager.search_members("")
        ids = {m["member_id"] for m in results}
        self.assertIn(self.member.name, ids)

    # ------------------------------------------------------------------ export_members

    def test_export_members_json(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        out = self.manager.export_members(format="json")
        data = json.loads(out)
        self.assertTrue(any(m["member_id"] == self.member.name for m in data))

    def test_export_members_csv_has_header_and_row(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        out = self.manager.export_members(format="csv")
        lines = out.splitlines()
        self.assertIn("Member ID", lines[0])
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn(self.member.name, out)

    def test_export_members_csv_empty(self):
        out = self.manager.export_members(format="csv")
        self.assertEqual(out, "No members to export")

    def test_export_members_unsupported_format_throws(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        with self.assertRaises(frappe.ValidationError):
            self.manager.export_members(format="xml")

    # ------------------------------------------------------------------ get_member_statistics

    def test_get_member_statistics_counts(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="StatDisabled")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        stats = self.manager.get_member_statistics()
        self.assertEqual(stats["total_members"], 2)
        self.assertEqual(stats["enabled_members"], 1)
        self.assertEqual(stats["disabled_members"], 1)
        # primary_members is derived from a cross-chapter "most recent enabled
        # chapter" DB query, so its exact value depends on global Chapter Member
        # state we don't own here. Assert the partition is internally consistent
        # rather than a specific count.
        self.assertEqual(
            stats["primary_members"] + stats["secondary_members"], stats["enabled_members"]
        )
        self.assertIsInstance(stats["primary_members"], int)

    # ------------------------------------------------------------------ get_summary

    def test_get_summary_includes_stats_and_recent(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        summary = self.manager.get_summary()
        self.assertIn("total_members", summary)
        self.assertIn("recent_additions", summary)
        self.assertIn("recent_removals", summary)
        self.assertIn("last_updated", summary)
