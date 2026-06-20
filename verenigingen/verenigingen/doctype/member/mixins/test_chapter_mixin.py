"""
Tests for verenigingen/verenigingen/doctype/member/mixins/chapter_mixin.py

ChapterMixin is mixed into the Member controller. The interesting,
independently-testable logic is update_chapter_tracking_fields() (pure
in-memory field mutation that drives the audit trail when a member's chapter
changes). The service-delegating read methods (get_chapters / is_board_member /
get_board_roles) are exercised against the REAL ChapterManagementService with a
member that holds no board positions, pinning their empty/false defaults and
their list/dict shapes.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterMixin(EnhancedTestCase):
    # ------------------------------------------------------------------
    # update_chapter_tracking_fields  (pure in-memory logic)
    # ------------------------------------------------------------------
    def test_tracking_initial_assignment_sets_default_reason(self):
        """First-time assignment (no old chapter) sets an 'Initial assignment' reason."""
        member = self.create_test_member(first_name="Track", last_name="Init")
        member.chapter_change_reason = None
        member.previous_chapter = None

        member.update_chapter_tracking_fields(old_chapter=None, new_chapter="Amsterdam")

        self.assertEqual(member.chapter_assigned_by, frappe.session.user)
        self.assertEqual(member.chapter_change_reason, "Initial assignment to Amsterdam")
        # No previous chapter recorded on a first assignment.
        self.assertFalse(member.previous_chapter)

    def test_tracking_change_records_previous_and_default_reason(self):
        """Changing chapters records previous_chapter and a 'Changed from X to Y' reason."""
        member = self.create_test_member(first_name="Track", last_name="Change")
        member.chapter_change_reason = None

        member.update_chapter_tracking_fields(old_chapter="Rotterdam", new_chapter="Utrecht")

        self.assertEqual(member.previous_chapter, "Rotterdam")
        self.assertEqual(member.chapter_assigned_by, frappe.session.user)
        self.assertEqual(member.chapter_change_reason, "Changed from Rotterdam to Utrecht")

    def test_tracking_preserves_explicit_reason(self):
        """A caller-supplied chapter_change_reason is NOT overwritten by the default."""
        member = self.create_test_member(first_name="Track", last_name="Reason")
        member.chapter_change_reason = "Member relocated"

        member.update_chapter_tracking_fields(old_chapter="Den Haag", new_chapter="Eindhoven")

        self.assertEqual(member.chapter_change_reason, "Member relocated")
        self.assertEqual(member.previous_chapter, "Den Haag")

    def test_tracking_no_new_chapter_only_sets_previous(self):
        """Clearing a chapter (new_chapter falsy) records previous but no assigned_by/reason."""
        member = self.create_test_member(first_name="Track", last_name="Clear")
        member.chapter_assigned_by = None
        member.chapter_change_reason = None

        member.update_chapter_tracking_fields(old_chapter="Groningen", new_chapter=None)

        self.assertEqual(member.previous_chapter, "Groningen")
        # new_chapter falsy -> assigned_by / reason branch is skipped.
        self.assertFalse(member.chapter_assigned_by)
        self.assertFalse(member.chapter_change_reason)

    # ------------------------------------------------------------------
    # Service-delegating reads (real ChapterManagementService)
    # ------------------------------------------------------------------
    def test_get_chapters_empty_for_unaffiliated_member(self):
        """A member belonging to no chapter gets an empty list (not an error).
        assertNoErrorLog catches a service that throws-and-swallows to [] instead."""
        member = self.create_test_member(first_name="Solo", last_name="Member")
        with self.assertNoErrorLog():
            chapters = member.get_chapters()
        self.assertIsInstance(chapters, list)
        self.assertEqual(chapters, [])

    def test_is_board_member_false_for_non_board_member(self):
        """A member with no board positions is not a board member of anything."""
        member = self.create_test_member(first_name="NotBoard", last_name="Member")
        with self.assertNoErrorLog():
            self.assertFalse(member.is_board_member())

    def test_get_board_roles_empty_for_non_board_member(self):
        """get_board_roles returns an empty list (correct shape) for a non-board member."""
        member = self.create_test_member(first_name="NoRoles", last_name="Member")
        with self.assertNoErrorLog():
            roles = member.get_board_roles()
        self.assertIsInstance(roles, list)
        self.assertEqual(roles, [])

    def test_is_chapter_management_enabled_reflects_setting(self):
        """_is_chapter_management_enabled returns the chapter service's actual flag
        (not merely 'a bool')."""
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        member = self.create_test_member(first_name="Mgmt", last_name="Flag")
        expected = get_chapter_management_service().is_chapter_management_enabled()
        self.assertEqual(member._is_chapter_management_enabled(), expected)
