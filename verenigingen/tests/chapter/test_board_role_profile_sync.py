# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for board member role profile sync.

Covers:
- BoardManager._sync_role_profile_for_volunteer() — the direct sync path
- bulk_assign_chapter_board_role_profiles() — the admin button path
- Both paths use auto_sync_on_role_change() under the hood
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSyncRoleProfileForVolunteer(EnhancedTestCase):
    """Tests for BoardManager._sync_role_profile_for_volunteer()."""

    def _make_board_manager(self):
        """Create a BoardManager with a mock chapter doc."""
        from verenigingen.verenigingen.doctype.chapter.managers.board_manager import BoardManager

        chapter_doc = MagicMock()
        chapter_doc.name = "Test-Chapter"
        return BoardManager(chapter_doc)

    @patch("verenigingen.verenigingen.doctype.chapter.managers.board_manager.frappe")
    def test_no_member_linked_to_volunteer(self, mock_frappe):
        """Skips sync when volunteer has no linked member."""
        mock_frappe.db.get_value.return_value = None

        mgr = self._make_board_manager()
        mgr._sync_role_profile_for_volunteer("VOL-001")

        mock_frappe.db.get_value.assert_called_once_with("Volunteer", "VOL-001", "member")

    @patch("verenigingen.verenigingen.doctype.chapter.managers.board_manager.frappe")
    def test_no_user_linked_to_member(self, mock_frappe):
        """Skips sync when member has no user account."""
        mock_frappe.db.get_value.side_effect = lambda dt, name, field: (
            "MEM-001" if dt == "Volunteer" else None
        )

        mgr = self._make_board_manager()
        mgr._sync_role_profile_for_volunteer("VOL-001")

        self.assertEqual(mock_frappe.db.get_value.call_count, 2)

    @patch(
        "verenigingen.verenigingen.doctype.chapter.managers.board_manager.frappe"
    )
    def test_calls_auto_sync_when_user_found(self, mock_frappe):
        """Calls auto_sync_on_role_change when volunteer->member->user resolves."""
        mock_frappe.db.get_value.side_effect = lambda dt, name, field: (
            "MEM-001" if dt == "Volunteer" else "user@example.com"
        )

        with patch(
            "verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change"
        ) as mock_sync:
            mgr = self._make_board_manager()
            mgr._sync_role_profile_for_volunteer("VOL-001")

            mock_sync.assert_called_once_with("user@example.com")

    @patch(
        "verenigingen.verenigingen.doctype.chapter.managers.board_manager.frappe"
    )
    def test_exception_logged_not_raised(self, mock_frappe):
        """Exceptions are logged, not propagated."""
        mock_frappe.db.get_value.side_effect = Exception("DB gone")

        mgr = self._make_board_manager()
        # Should not raise
        mgr._sync_role_profile_for_volunteer("VOL-001")


class TestBulkAssignChapterBoardRoleProfiles(EnhancedTestCase):
    """Tests for the rewritten bulk_assign_chapter_board_role_profiles().

    These tests call the function directly (bypassing security decorators)
    by extracting the inner function via __wrapped__.
    """

    def _get_inner_fn(self):
        """Get the unwrapped function, bypassing @critical_api and @frappe.whitelist."""
        from verenigingen.utils.chapter_role_profile_manager import (
            bulk_assign_chapter_board_role_profiles,
        )

        fn = bulk_assign_chapter_board_role_profiles
        # Unwrap decorator layers until we reach the original
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn

    @patch("verenigingen.services.member.account.user_role_profile_calculator.auto_sync_on_role_change")
    def test_nonexistent_chapter_returns_failure(self, mock_sync):
        """Returns failure dict for nonexistent chapter."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=False):
            result = fn("No-Such-Chapter")

        self.assertFalse(result["success"])
        self.assertEqual(result["members_updated"], 0)
        mock_sync.assert_not_called()

    @patch("verenigingen.services.member.account.user_role_profile_calculator.auto_sync_on_role_change")
    def test_empty_board_returns_success(self, mock_sync):
        """Empty board (no active members with users) returns success with 0 updated."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=True), patch.object(
            frappe.db, "sql", return_value=[]
        ):
            result = fn("Empty-Chapter")

        self.assertTrue(result["success"])
        self.assertEqual(result["members_updated"], 0)
        mock_sync.assert_not_called()

    @patch("verenigingen.services.member.account.user_role_profile_calculator.auto_sync_on_role_change")
    def test_syncs_each_board_member_user(self, mock_sync):
        """Calls auto_sync_on_role_change for each board member's user."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=True), patch.object(
            frappe.db,
            "sql",
            return_value=[{"user": "alice@example.com"}, {"user": "bob@example.com"}],
        ):
            result = fn("Test-Chapter")

        self.assertTrue(result["success"])
        self.assertEqual(result["members_updated"], 2)
        mock_sync.assert_any_call("alice@example.com")
        mock_sync.assert_any_call("bob@example.com")

    @patch("verenigingen.services.member.account.user_role_profile_calculator.auto_sync_on_role_change")
    def test_partial_failure_still_counts_successes(self, mock_sync):
        """If one user fails, others still get synced."""
        fn = self._get_inner_fn()
        mock_sync.side_effect = [None, Exception("fail"), None]

        with patch.object(frappe.db, "exists", return_value=True), patch.object(
            frappe.db,
            "sql",
            return_value=[
                {"user": "alice@example.com"},
                {"user": "bob@example.com"},
                {"user": "charlie@example.com"},
            ],
        ), patch.object(frappe, "log_error"):
            result = fn("Test-Chapter")

        self.assertTrue(result["success"])
        self.assertEqual(result["members_updated"], 2)


class TestDisabledUserIsNotResurrected(EnhancedTestCase):
    """A disabled account must not be re-enabled by role-profile sync.

    sync_user_role_profile() calls _ensure_employee_for_profile(), which creates an
    Employee with status "Active". ERPNext's Employee.validate_for_enabled_user_id()
    keeps Employee status and User.enabled in lockstep, so an Active Employee
    pointing at a disabled User force-enables that User:

        if self.status != "Active" and enabled or self.status == "Active" and enabled == 0:
            frappe.db.set_value("User", self.user_id, "enabled", not enabled)

    Chapter.on_update drains the deferred board-profile syncs, so seating a board
    member reaches that path. Without the guard, seating someone — or any later
    chapter save touching an already-seated member — silently resurrects a
    deliberately disabled account.
    """

    def _make_disabled_member_user(self):
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        frappe.db.set_value("User", user.email, "enabled", 0)
        member = self.factory.create_member(email=user.email)
        member.user = user.email
        member.save()
        volunteer = self.factory.create_volunteer(
            member_name=member.name, email=user.email, _exact_email=True
        )
        return user.email, volunteer

    def test_sync_skips_disabled_user(self):
        """sync_user_role_profile() reports a skip and leaves the account disabled."""
        from verenigingen.services.member.account.user_role_profile_calculator import (
            sync_user_role_profile,
        )

        email, _volunteer = self._make_disabled_member_user()

        result = sync_user_role_profile(email)

        self.assertEqual(result.get("skipped"), "user_disabled")
        self.assertFalse(result.get("changed"))
        self.assertEqual(frappe.db.get_value("User", email, "enabled"), 0)

    def test_seating_a_board_member_does_not_re_enable_the_user(self):
        """The reachable path: a chapter save must not resurrect a disabled account."""
        email, volunteer = self._make_disabled_member_user()

        if not frappe.db.exists("Chapter Role", "Treasurer"):
            role = frappe.new_doc("Chapter Role")
            role.role_name = "Treasurer"
            role.permissions_level = "Financial"
            role.is_active = 1
            role.insert()

        chapter = self.factory.create_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": "Treasurer",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()

        self.assertEqual(
            frappe.db.get_value("User", email, "enabled"),
            0,
            "seating a board member re-enabled a disabled user account",
        )
