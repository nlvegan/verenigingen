# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for team role profile sync.

Covers:
- on_team_lead_change() — role profile + Team Lead role sync when team_lead changes
- on_team_members_change() — role profile sync when team members gain/lose active status
- _sync_team_lead_role() — assign/remove "Team Lead" Has Role
- bulk_apply_team_role_profiles() — the admin button path
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# Patch @validate_api_input decorator before team_management module loads.
# It's used without parentheses on sync_team_with_volunteers (pre-existing bug)
# which causes a TypeError at import time.
import verenigingen.utils.validation.api_validators as _validators

_orig_validate = _validators.validate_api_input


def _patched_validate_api_input(*args, **kwargs):
    if args and callable(args[0]) and not kwargs:
        return args[0]
    return _orig_validate(*args, **kwargs)


_validators.validate_api_input = _patched_validate_api_input
if "verenigingen.api.team_management" in sys.modules:
    importlib.reload(sys.modules["verenigingen.api.team_management"])


class TestSyncTeamLeadRole(EnhancedTestCase):
    """Tests for _sync_team_lead_role() helper."""

    def _call_sync(self, user):
        from verenigingen.utils.team_role_profile_hooks import _sync_team_lead_role

        _sync_team_lead_role(user)

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    def test_assigns_role_when_leading_team_without_role(self, mock_frappe):
        """Assigns 'Team Lead' Has Role when user leads a team but doesn't have the role."""
        mock_frappe.db.exists.side_effect = lambda dt, filters=None: (
            "TEAM-001" if dt == "Team" else None
        )
        mock_user_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_user_doc

        self._call_sync("leader@example.com")

        mock_user_doc.append.assert_called_once_with("roles", {"role": "Team Lead"})
        mock_user_doc.save.assert_called_once_with(ignore_permissions=True)

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    def test_removes_role_when_no_longer_leading(self, mock_frappe):
        """Removes 'Team Lead' Has Role when user no longer leads any team."""
        mock_frappe.db.exists.side_effect = lambda dt, filters=None: (
            None if dt == "Team" else "HAS-ROLE-001"
        )

        self._call_sync("ex-leader@example.com")

        mock_frappe.delete_doc.assert_called_once_with(
            "Has Role", "HAS-ROLE-001", ignore_permissions=True
        )

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    def test_no_op_when_leading_and_has_role(self, mock_frappe):
        """Does nothing when user leads a team and already has the role."""
        mock_frappe.db.exists.side_effect = lambda dt, filters=None: (
            "TEAM-001" if dt == "Team" else "HAS-ROLE-001"
        )

        self._call_sync("leader@example.com")

        mock_frappe.get_doc.assert_not_called()
        mock_frappe.delete_doc.assert_not_called()

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    def test_no_op_when_not_leading_and_no_role(self, mock_frappe):
        """Does nothing when user doesn't lead any team and doesn't have the role."""
        mock_frappe.db.exists.return_value = None

        self._call_sync("nobody@example.com")

        mock_frappe.get_doc.assert_not_called()
        mock_frappe.delete_doc.assert_not_called()

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    def test_exception_logged_not_raised(self, mock_frappe):
        """Exceptions are logged, not propagated."""
        mock_frappe.db.exists.side_effect = Exception("DB gone")

        # Should not raise
        self._call_sync("user@example.com")

        mock_frappe.log_error.assert_called_once()


class TestOnTeamLeadChange(EnhancedTestCase):
    """Tests for on_team_lead_change() hook."""

    def _make_doc(self, old_lead=None, new_lead=None, changed=True):
        """Create a mock Team document with _doc_before_save."""
        doc = MagicMock()
        doc.team_lead = new_lead
        doc.has_value_changed.return_value = changed
        if old_lead is not None:
            doc._doc_before_save = MagicMock()
            doc._doc_before_save.team_lead = old_lead
        else:
            doc._doc_before_save = None
        return doc

    @patch("verenigingen.utils.team_role_profile_hooks._sync_team_lead_role")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_syncs_old_and_new_lead(self, mock_auto_sync, mock_role_sync):
        """Calls auto_sync and _sync_team_lead_role for both old and new lead."""
        from verenigingen.utils.team_role_profile_hooks import on_team_lead_change

        doc = self._make_doc(old_lead="old@example.com", new_lead="new@example.com")
        on_team_lead_change(doc, "on_update")

        mock_auto_sync.assert_any_call("old@example.com")
        mock_auto_sync.assert_any_call("new@example.com")
        mock_role_sync.assert_any_call("old@example.com")
        mock_role_sync.assert_any_call("new@example.com")

    @patch("verenigingen.utils.team_role_profile_hooks._sync_team_lead_role")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_no_op_when_unchanged(self, mock_auto_sync, mock_role_sync):
        """Does nothing when team_lead hasn't changed."""
        from verenigingen.utils.team_role_profile_hooks import on_team_lead_change

        doc = self._make_doc(changed=False)
        on_team_lead_change(doc, "on_update")

        mock_auto_sync.assert_not_called()
        mock_role_sync.assert_not_called()

    @patch("verenigingen.utils.team_role_profile_hooks._sync_team_lead_role")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_handles_no_doc_before_save(self, mock_auto_sync, mock_role_sync):
        """Handles case where _doc_before_save is None (new team)."""
        from verenigingen.utils.team_role_profile_hooks import on_team_lead_change

        doc = self._make_doc(old_lead=None, new_lead="new@example.com")
        on_team_lead_change(doc, "on_update")

        # Only new lead should be synced
        self.assertEqual(mock_auto_sync.call_count, 1)
        mock_auto_sync.assert_called_once_with("new@example.com")


class TestOnTeamMembersChange(EnhancedTestCase):
    """Tests for on_team_members_change() hook."""

    def _make_member(self, volunteer, status="Active"):
        m = MagicMock()
        m.volunteer = volunteer
        m.status = status
        return m

    def _make_doc(self, old_members=None, new_members=None, changed=True):
        doc = MagicMock()
        doc.has_value_changed.return_value = changed
        doc.team_members = new_members or []
        if old_members is not None:
            doc._doc_before_save = MagicMock()
            doc._doc_before_save.team_members = old_members
        else:
            doc._doc_before_save = None
        return doc

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_syncs_added_member(self, mock_sync, mock_frappe):
        """Syncs role profile when a new active member is added."""
        from verenigingen.utils.team_role_profile_hooks import on_team_members_change

        mock_frappe.db.get_value.side_effect = lambda dt, name, field: (
            "MEM-001" if dt == "Volunteer" else "user@example.com"
        )

        doc = self._make_doc(
            old_members=[],
            new_members=[self._make_member("VOL-001")],
        )
        on_team_members_change(doc, "on_update")

        mock_sync.assert_called_once_with("user@example.com")

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_syncs_removed_member(self, mock_sync, mock_frappe):
        """Syncs role profile when an active member is removed."""
        from verenigingen.utils.team_role_profile_hooks import on_team_members_change

        mock_frappe.db.get_value.side_effect = lambda dt, name, field: (
            "MEM-001" if dt == "Volunteer" else "user@example.com"
        )

        doc = self._make_doc(
            old_members=[self._make_member("VOL-001")],
            new_members=[],
        )
        on_team_members_change(doc, "on_update")

        mock_sync.assert_called_once_with("user@example.com")

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_no_op_when_unchanged(self, mock_sync, mock_frappe):
        """Does nothing when team_members hasn't changed."""
        from verenigingen.utils.team_role_profile_hooks import on_team_members_change

        doc = self._make_doc(changed=False)
        on_team_members_change(doc, "on_update")

        mock_sync.assert_not_called()

    @patch("verenigingen.utils.team_role_profile_hooks.frappe")
    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_skips_member_without_user(self, mock_sync, mock_frappe):
        """Skips sync when volunteer has no linked user."""
        from verenigingen.utils.team_role_profile_hooks import on_team_members_change

        mock_frappe.db.get_value.side_effect = lambda dt, name, field: (
            "MEM-001" if dt == "Volunteer" else None
        )

        doc = self._make_doc(
            old_members=[],
            new_members=[self._make_member("VOL-001")],
        )
        on_team_members_change(doc, "on_update")

        mock_sync.assert_not_called()


class TestBulkApplyTeamRoleProfiles(EnhancedTestCase):
    """Tests for bulk_apply_team_role_profiles() admin button.

    The team_management module has a pre-existing decorator bug (@validate_api_input
    used without arguments on sync_team_with_volunteers). We patch it to allow import.
    """

    def _get_inner_fn(self):
        """Get the unwrapped function, bypassing decorators."""
        from verenigingen.api.team_management import bulk_apply_team_role_profiles

        fn = bulk_apply_team_role_profiles
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn

    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_nonexistent_team_returns_failure(self, mock_sync):
        """Returns failure dict for nonexistent team."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=False), patch(
            "verenigingen.api.team_management.frappe.has_permission", return_value=True
        ):
            result = fn("No-Such-Team")

        self.assertFalse(result["success"])
        self.assertEqual(result["applied_count"], 0)
        mock_sync.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_empty_team_returns_success(self, mock_sync):
        """Empty team (no active members with users) returns success with 0 updated."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=True), patch.object(
            frappe.db, "sql", return_value=[]
        ), patch(
            "verenigingen.api.team_management.frappe.has_permission", return_value=True
        ):
            result = fn("Empty-Team")

        self.assertTrue(result["success"])
        self.assertEqual(result["applied_count"], 0)
        mock_sync.assert_not_called()

    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
    def test_syncs_each_team_member_user(self, mock_sync):
        """Calls auto_sync_on_role_change for each team member's user."""
        fn = self._get_inner_fn()

        with patch.object(frappe.db, "exists", return_value=True), patch.object(
            frappe.db,
            "sql",
            return_value=[{"user": "alice@example.com"}, {"user": "bob@example.com"}],
        ), patch(
            "verenigingen.api.team_management.frappe.has_permission", return_value=True
        ):
            result = fn("Test-Team")

        self.assertTrue(result["success"])
        self.assertEqual(result["applied_count"], 2)
        mock_sync.assert_any_call("alice@example.com")
        mock_sync.assert_any_call("bob@example.com")

    @patch("verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change")
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
        ), patch.object(frappe, "log_error"), patch(
            "verenigingen.api.team_management.frappe.has_permission", return_value=True
        ):
            result = fn("Test-Team")

        self.assertTrue(result["success"])
        self.assertEqual(result["applied_count"], 2)
