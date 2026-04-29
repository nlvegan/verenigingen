# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for ChapterBoardMember controller (verenigingen/doctype/chapter_board_member).

Covers two bug classes that lived in remove_board_member_role:
  1. `["is", "null"]` — invalid Frappe filter; valid form is `["is", "not set"]`.
  2. DocType passed as `"Verenigingen Chapter Board Member"` — that string is
     the role name; the DocType is just `"Chapter Board Member"`.

Together they made remove_board_member_role unreachable in production. Any
volunteer being removed from a chapter board hit the first error, and even
after fixing it the second would have raised "table doesn't exist".

The tests below split into two layers:
  - Live-DB regression tests for the actual SQL filter shapes the controller
    runs (catches both bugs directly without any mocks).
  - Behavioral tests using mocks for the assign/remove decision logic, since
    the downstream role-profile sync system rewrites Has Role rows independently
    of what assign_board_member_role does, making end-to-end assertions flaky.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
    ChapterBoardMember,
)


BOARD_MEMBER_ROLE = "Verenigingen Chapter Board Member"


class TestChapterBoardMemberCountQueries(EnhancedTestCase):
    """Regression: the SQL filter shapes used by remove_board_member_role
    must execute against the live DB without raising.

    These two queries catch both bugs in one shot — if the DocType is wrong
    we get "table doesn't exist", if the operator is wrong we get
    "'is' operator only supports 'set' and 'not set' as value".
    """

    def test_open_ended_active_count_runs(self):
        """`to_date is not set` filter is accepted and returns an integer."""
        n = frappe.db.count(
            "Chapter Board Member",
            {
                "volunteer": "non-existent-volunteer-name",
                "is_active": 1,
                "to_date": ["is", "not set"],
            },
        )
        self.assertIsInstance(n, int)
        self.assertEqual(n, 0)

    def test_future_dated_active_count_runs(self):
        """`to_date >= today` filter is accepted and returns an integer."""
        n = frappe.db.count(
            "Chapter Board Member",
            {
                "volunteer": "non-existent-volunteer-name",
                "is_active": 1,
                "to_date": [">=", today()],
            },
        )
        self.assertIsInstance(n, int)
        self.assertEqual(n, 0)

    def test_invalid_is_null_operator_still_rejected_by_frappe(self):
        """Sanity guard: if Frappe ever stops rejecting `['is', 'null']` we
        want this test to fail so we can revisit whether our fix is still
        needed."""
        with self.assertRaises(Exception) as ctx:
            frappe.db.count(
                "Chapter Board Member",
                {"to_date": ["is", "null"]},
            )
        self.assertIn(
            "is",
            str(ctx.exception).lower(),
            "Expected Frappe to reject `['is', 'null']`; if this changes the "
            "controller could revert to the old form, but the comment in "
            "remove_board_member_role should be revisited first.",
        )


def _make_board_member_stub(volunteer="VOL-1", name="cbm-1"):
    """Build a ChapterBoardMember instance bypassing Frappe's normal init.

    We need a real instance to call the bound methods, but inserting child
    rows pulls in the whole chapter+role-profile pipeline. Constructing a
    bare object lets us exercise the decision logic in isolation.
    """
    doc = ChapterBoardMember.__new__(ChapterBoardMember)
    doc.volunteer = volunteer
    doc.name = name
    return doc


class TestRemoveBoardMemberRoleLogic(EnhancedTestCase):
    """Behavioral tests for remove_board_member_role decision logic.

    Mocks the DB and secure_document_operation so we can verify that the
    method correctly decides whether to remove the role based on how many
    other active board positions the volunteer holds.
    """

    def _patch_db(self, mock_frappe, *, member, user, role_assignment, count_results):
        """Wire up the mocked frappe.db calls the method makes in order:
          1. frappe.get_doc('Volunteer', ...)  -> volunteer_doc.member
          2. frappe.db.get_value('Member', ...) -> user
          3. frappe.db.count(...) twice (open-ended, future)
          4. frappe.db.exists('Has Role', ...) -> role_assignment
        """
        volunteer_doc = MagicMock()
        volunteer_doc.member = member
        mock_frappe.get_doc.return_value = volunteer_doc
        mock_frappe.db.get_value.return_value = user
        mock_frappe.db.count.side_effect = list(count_results)
        mock_frappe.db.exists.return_value = role_assignment

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_role_removed_when_no_other_active_boards(self, mock_frappe, mock_secure):
        """No other active boards → secure_document_operation('delete') runs."""
        self._patch_db(
            mock_frappe,
            member="MEM-1",
            user="user@example.test",
            role_assignment="HasRole-1",
            count_results=[0, 0],
        )
        mock_secure.return_value = MagicMock(success=True)

        doc = _make_board_member_stub()
        # Provide a real-ish doc for the get_doc("Has Role", ...) lookup
        mock_frappe.get_doc.side_effect = [
            mock_frappe.get_doc.return_value,  # Volunteer lookup
            MagicMock(),  # Has Role lookup
        ]

        doc.remove_board_member_role()

        self.assertEqual(mock_secure.call_count, 1)
        self.assertEqual(mock_secure.call_args.kwargs["operation"], "delete")

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_role_kept_when_other_open_ended_active_board_exists(self, mock_frappe, mock_secure):
        """An open-ended (to_date NULL) active position keeps the role.

        Original bug path: this branch executes the `["is", "not set"]`
        filter; when the filter was `["is", "null"]` it crashed before we
        could even count.
        """
        self._patch_db(
            mock_frappe,
            member="MEM-1",
            user="user@example.test",
            role_assignment="HasRole-1",
            count_results=[1, 0],  # one open-ended, no future-ending
        )

        _make_board_member_stub().remove_board_member_role()

        mock_secure.assert_not_called()

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_role_kept_when_future_dated_active_board_exists(self, mock_frappe, mock_secure):
        """A position with a future to_date is still active → role preserved."""
        self._patch_db(
            mock_frappe,
            member="MEM-1",
            user="user@example.test",
            role_assignment="HasRole-1",
            count_results=[0, 1],
        )

        _make_board_member_stub().remove_board_member_role()

        mock_secure.assert_not_called()

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_skips_when_volunteer_missing(self, mock_frappe, mock_secure):
        """Without a volunteer, the method short-circuits without DB lookups."""
        doc = _make_board_member_stub(volunteer=None)

        doc.remove_board_member_role()

        mock_frappe.get_doc.assert_not_called()
        mock_secure.assert_not_called()

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_skips_when_member_has_no_user(self, mock_frappe, mock_secure):
        """If the member has no linked user, no role row to remove."""
        volunteer_doc = MagicMock()
        volunteer_doc.member = "MEM-1"
        mock_frappe.get_doc.return_value = volunteer_doc
        mock_frappe.db.get_value.return_value = None  # no user

        _make_board_member_stub().remove_board_member_role()

        mock_frappe.db.count.assert_not_called()
        mock_secure.assert_not_called()

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_count_filters_use_correct_doctype_and_operator(self, mock_frappe, _mock_secure):
        """Regression: assert the exact filter shapes the method passes to count.

        This is the most direct test of both bugs at once:
          - DocType must be 'Chapter Board Member' (not the role name).
          - to_date filter must use 'not set' (not 'null').
        """
        self._patch_db(
            mock_frappe,
            member="MEM-1",
            user="user@example.test",
            role_assignment=None,
            count_results=[0, 0],
        )

        doc = _make_board_member_stub(volunteer="VOL-X", name="cbm-X")
        doc.remove_board_member_role()

        self.assertEqual(mock_frappe.db.count.call_count, 2)

        first_call = mock_frappe.db.count.call_args_list[0]
        second_call = mock_frappe.db.count.call_args_list[1]

        # First query: open-ended active positions
        self.assertEqual(first_call.args[0], "Chapter Board Member")
        self.assertEqual(first_call.args[1]["to_date"], ["is", "not set"])
        self.assertEqual(first_call.args[1]["volunteer"], "VOL-X")
        self.assertEqual(first_call.args[1]["name"], ["!=", "cbm-X"])
        self.assertEqual(first_call.args[1]["is_active"], 1)

        # Second query: future-ending active positions
        self.assertEqual(second_call.args[0], "Chapter Board Member")
        self.assertEqual(second_call.args[1]["to_date"][0], ">=")


class TestAssignBoardMemberRoleLogic(EnhancedTestCase):
    """Behavioral tests for assign_board_member_role decision logic."""

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_role_assigned_when_user_lacks_it(self, mock_frappe, mock_secure):
        """When the user doesn't already have the role, save the User with the role appended."""
        volunteer_doc = MagicMock()
        volunteer_doc.member = "MEM-1"
        user_doc = MagicMock()
        mock_frappe.get_doc.side_effect = [volunteer_doc, user_doc]
        mock_frappe.db.get_value.return_value = "user@example.test"
        mock_frappe.db.exists.return_value = None  # no existing role row
        mock_secure.return_value = MagicMock(success=True)

        _make_board_member_stub().assign_board_member_role()

        user_doc.append.assert_called_once_with(
            "roles",
            {"role": BOARD_MEMBER_ROLE},
        )
        self.assertEqual(mock_secure.call_count, 1)
        self.assertEqual(mock_secure.call_args.kwargs["operation"], "save")

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_assign_idempotent_when_role_exists(self, mock_frappe, mock_secure):
        """If the user already has the role, no User save is performed."""
        volunteer_doc = MagicMock()
        volunteer_doc.member = "MEM-1"
        mock_frappe.get_doc.return_value = volunteer_doc
        mock_frappe.db.get_value.return_value = "user@example.test"
        mock_frappe.db.exists.return_value = "HasRole-1"  # already there

        _make_board_member_stub().assign_board_member_role()

        mock_secure.assert_not_called()

    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.secure_document_operation")
    @patch("verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member.frappe")
    def test_assign_skips_when_volunteer_has_no_member(self, mock_frappe, mock_secure):
        """No member on the volunteer → bail out before touching the DB further."""
        volunteer_doc = MagicMock()
        volunteer_doc.member = None
        mock_frappe.get_doc.return_value = volunteer_doc

        _make_board_member_stub().assign_board_member_role()

        mock_frappe.db.get_value.assert_not_called()
        mock_secure.assert_not_called()
