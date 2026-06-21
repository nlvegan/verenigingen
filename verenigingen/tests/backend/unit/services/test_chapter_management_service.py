# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for ChapterManagementService

Tests chapter affiliation queries and management functionality.
Uses EnhancedTestCase for proper test data management.
"""

import frappe

from verenigingen.services.member.chapter import ChapterManagementService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterManagementService(EnhancedTestCase):
    """Unit tests for ChapterManagementService"""

    def setUp(self):
        super().setUp()
        self.service = ChapterManagementService()
        # Ensure chapter management is enabled for tests that depend on it
        self._original_chapter_mgmt = frappe.db.get_single_value(
            "Verenigingen Settings", "enable_chapter_management"
        )
        if not self._original_chapter_mgmt:
            frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
            frappe.db.commit()

    def tearDown(self):
        # Always restore original setting (could be 0 or None)
        frappe.db.set_single_value(
            "Verenigingen Settings", "enable_chapter_management", self._original_chapter_mgmt or 0
        )
        frappe.db.commit()
        super().tearDown()

    def test_is_chapter_management_enabled_true(self):
        """Test that chapter management check returns True when enabled"""
        result = self.service.is_chapter_management_enabled()
        self.assertTrue(result)

    def test_get_member_chapters_with_no_chapters(self):
        """Test getting chapters for member with no chapter affiliations"""
        member = self.create_test_member()

        chapters = self.service.get_member_chapters(member.name)

        self.assertIsInstance(chapters, list)
        self.assertEqual(len(chapters), 0)

    def test_get_member_chapters_empty_member_name(self):
        """Test that empty member name returns empty list"""
        chapters = self.service.get_member_chapters("")
        self.assertEqual(chapters, [])

        chapters = self.service.get_member_chapters(None)
        self.assertEqual(chapters, [])

    def test_get_member_chapters_invalid_member_raises_validation_error(self):
        """Test that invalid member name raises ValidationError"""
        with self.assertRaises(frappe.ValidationError):
            self.service.get_member_chapters("INVALID-MEMBER-NAME")

    def test_get_board_memberships_with_no_volunteer(self):
        """Test board memberships for member without volunteer record"""
        member = self.create_test_member(birth_date="2000-01-01")

        board_memberships = self.service.get_board_memberships(member.name)

        self.assertIsInstance(board_memberships, list)
        self.assertEqual(len(board_memberships), 0)

    def test_get_board_memberships_with_volunteer_no_board_role(self):
        """Test board memberships for volunteer without board roles"""
        member = self.create_test_member(birth_date="2000-01-01")
        volunteer = self.create_test_volunteer(member.name)

        board_memberships = self.service.get_board_memberships(member.name)

        self.assertEqual(len(board_memberships), 0)

    def test_get_board_memberships_empty_member_name(self):
        """Test that empty member name returns empty list"""
        result = self.service.get_board_memberships("")
        self.assertEqual(result, [])

        result = self.service.get_board_memberships(None)
        self.assertEqual(result, [])

    def test_get_board_memberships_invalid_member_throws(self):
        """Test that invalid member name throws ValidationError"""
        with self.assertRaises(frappe.ValidationError):
            self.service.get_board_memberships("INVALID-MEMBER-NAME")

    def test_get_chapter_names_empty_list(self):
        """Test getting chapter names for member with no chapters"""
        member = self.create_test_member()

        names = self.service.get_chapter_names(member.name)

        self.assertIsInstance(names, list)
        self.assertEqual(len(names), 0)

    def test_get_chapter_names_empty_member_name(self):
        """Test that empty member name returns empty list"""
        names = self.service.get_chapter_names("")
        self.assertEqual(names, [])

        names = self.service.get_chapter_names(None)
        self.assertEqual(names, [])

    def test_get_chapter_display_html_basic(self):
        """Test HTML display generation for member with no chapters"""
        member = self.create_test_member()

        html = self.service.get_chapter_display_html(member.name)

        self.assertIsInstance(html, str)

    def test_get_chapter_display_html_invalid_member_returns_error_html(self):
        """Test that invalid member name returns error HTML (doesn't throw)"""
        html = self.service.get_chapter_display_html("INVALID-MEMBER")

        # Should return error HTML, not throw exception (good UI design)
        self.assertIsInstance(html, str)
        self.assertIn("Error", html)

    def test_chapter_management_disabled_returns_empty_list(self):
        """Test that disabled chapter management returns empty lists for board memberships"""
        # Temporarily disable chapter management using db_set to avoid validation
        # (validation requires dues_income_account which may not be set in tests)
        original_value = frappe.db.get_single_value(
            "Verenigingen Settings", "enable_chapter_management"
        )

        try:
            frappe.db.set_single_value(
                "Verenigingen Settings", "enable_chapter_management", 0
            )
            frappe.db.commit()

            member = self.create_test_member()

            # Board memberships should return empty when disabled
            board_memberships = self.service.get_board_memberships(member.name)
            self.assertEqual(len(board_memberships), 0)

        finally:
            # Restore original setting
            frappe.db.set_single_value(
                "Verenigingen Settings", "enable_chapter_management", original_value
            )
            frappe.db.commit()

    def test_service_respects_permissions(self):
        """Test that service methods respect Frappe permissions"""
        member = self.create_test_member()

        # These calls should succeed with proper permissions in test context
        chapters = self.service.get_member_chapters(member.name)
        self.assertIsInstance(chapters, list)

        board_memberships = self.service.get_board_memberships(member.name)
        self.assertIsInstance(board_memberships, list)

        names = self.service.get_chapter_names(member.name)
        self.assertIsInstance(names, list)

        html = self.service.get_chapter_display_html(member.name)
        self.assertIsInstance(html, str)

    # ------------------------------------------------------------------
    # Fixture helpers for "member actually affiliated with a chapter"
    # ------------------------------------------------------------------

    def _member_in_chapter(self, **member_kwargs):
        """Create a chapter and a member assigned to it.

        Returns (member, chapter). Uses the chapter= kwarg path which routes
        through ChapterMembershipManager (or the child-table fallback) to make
        a real, enabled Chapter Member row keyed on the member.
        """
        chapter = self.create_test_chapter()
        member = self.create_test_member(chapter=chapter.name, **member_kwargs)
        return member, chapter

    def _make_board_member(self, member, chapter, role_name=None, is_active=1):
        """Give a member an (active) board position in a chapter.

        Creates a volunteer for the member, a chapter role, and appends a
        Chapter Board Member row to the chapter. Returns the volunteer.
        """
        volunteer = self.create_test_volunteer(member.name)
        role = self.factory.ensure_chapter_role(role_name or f"Test Board Role {chapter.name[:20]}")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": is_active,
            },
        )
        chapter_doc.save()
        return volunteer

    # ------------------------------------------------------------------
    # get_member_chapters (fallback, 2-query path) with real affiliations
    # ------------------------------------------------------------------

    def test_get_member_chapters_returns_affiliation(self):
        """A member with a chapter affiliation is returned with is_primary set."""
        member, chapter = self._member_in_chapter()

        chapters = self.service.get_member_chapters(member.name)

        self.assertEqual(len(chapters), 1)
        row = chapters[0]
        self.assertEqual(row["chapter"], chapter.name)
        self.assertTrue(row["is_primary"])  # first/only chapter is primary
        self.assertFalse(row["is_board"])  # no board position created
        self.assertIn("status", row)

    def test_get_member_chapters_marks_board_membership(self):
        """The fallback path flags is_board=True when the member holds a board seat."""
        member, chapter = self._member_in_chapter()
        self._make_board_member(member, chapter)

        chapters = self.service.get_member_chapters(member.name)

        self.assertEqual(len(chapters), 1)
        self.assertTrue(chapters[0]["is_board"])

    # ------------------------------------------------------------------
    # get_member_chapters_optimized (single-query path)
    # ------------------------------------------------------------------

    def test_get_member_chapters_optimized_returns_affiliation(self):
        """Optimized query returns chapter with region, is_primary and is_board=False."""
        member, chapter = self._member_in_chapter()

        chapters = self.service.get_member_chapters_optimized(member.name)

        self.assertEqual(len(chapters), 1)
        row = chapters[0]
        self.assertEqual(row["chapter"], chapter.name)
        self.assertTrue(row["is_primary"])
        self.assertFalse(row["is_board"])
        # region is populated from the joined Chapter row
        expected_region = frappe.db.get_value("Chapter", chapter.name, "region")
        self.assertEqual(row["region"], expected_region)

    def test_get_member_chapters_optimized_flags_board(self):
        """Optimized query flags is_board=True for an active board volunteer."""
        member, chapter = self._member_in_chapter()
        self._make_board_member(member, chapter)

        chapters = self.service.get_member_chapters_optimized(member.name)

        self.assertEqual(len(chapters), 1)
        self.assertTrue(chapters[0]["is_board"])

    def test_get_member_chapters_optimized_empty_member_name(self):
        """Empty member name short-circuits to an empty list."""
        self.assertEqual(self.service.get_member_chapters_optimized(""), [])

    def test_get_member_chapters_optimized_invalid_member_raises(self):
        """Unknown member raises a ValidationError before querying."""
        with self.assertRaises(frappe.ValidationError):
            self.service.get_member_chapters_optimized("INVALID-MEMBER-NAME")

    # ------------------------------------------------------------------
    # get_board_memberships with a real active board seat
    # ------------------------------------------------------------------

    def test_get_board_memberships_returns_active_position(self):
        """An active board seat surfaces with chapter, role and volunteer name."""
        member, chapter = self._member_in_chapter()
        volunteer = self._make_board_member(member, chapter)

        memberships = self.service.get_board_memberships(member.name)

        self.assertEqual(len(memberships), 1)
        row = memberships[0]
        self.assertEqual(row["chapter"], chapter.name)
        self.assertEqual(row["volunteer_name"], volunteer.name)
        self.assertEqual(row["member_check"], member.name)
        self.assertIsNotNone(row["start_date"])

    def test_get_board_memberships_excludes_inactive(self):
        """An inactive (is_active=0) board seat is filtered out."""
        member, chapter = self._member_in_chapter()
        self._make_board_member(member, chapter, is_active=0)

        memberships = self.service.get_board_memberships(member.name)

        self.assertEqual(len(memberships), 0)

    # ------------------------------------------------------------------
    # check_board_membership public API
    # ------------------------------------------------------------------

    def test_check_board_membership_true(self):
        """Returns True for a member holding an active board seat in the chapter."""
        member, chapter = self._member_in_chapter()
        self._make_board_member(member, chapter)

        self.assertTrue(self.service.check_board_membership(member.name, chapter.name))

    def test_check_board_membership_false(self):
        """Returns False for a member with no board seat in the chapter."""
        member, chapter = self._member_in_chapter()

        self.assertFalse(self.service.check_board_membership(member.name, chapter.name))

    def test_check_board_membership_empty_args(self):
        """Missing member or chapter name returns False without querying."""
        self.assertFalse(self.service.check_board_membership("", "Chapter-X"))
        self.assertFalse(self.service.check_board_membership("Member-X", ""))

    def test_check_board_membership_invalid_chapter_raises(self):
        """A valid member but unknown chapter raises ValidationError."""
        member = self.create_test_member()
        with self.assertRaises(frappe.ValidationError):
            self.service.check_board_membership(member.name, "NONEXISTENT-CHAPTER")

    # ------------------------------------------------------------------
    # get_chapter_names with real affiliations
    # ------------------------------------------------------------------

    def test_get_chapter_names_returns_names(self):
        """Returns the affiliated chapter's name as a plain string list."""
        member, chapter = self._member_in_chapter()

        names = self.service.get_chapter_names(member.name)

        self.assertEqual(names, [chapter.name])

    # ------------------------------------------------------------------
    # get_chapter_display_html with real affiliations (badge rendering)
    # ------------------------------------------------------------------

    def test_get_chapter_display_html_renders_badge(self):
        """HTML output contains a status badge and the chapter name for an affiliation."""
        member, chapter = self._member_in_chapter()

        html = self.service.get_chapter_display_html(member.name)

        self.assertIn("chapter-list", html)
        self.assertIn(chapter.name, html)
        # Active status maps to the 'success' badge class via STATUS_CLASS_MAP
        self.assertIn("badge-success", html)

    def test_get_chapter_display_html_no_chapters_message(self):
        """A member with no chapters yields the 'No active chapters' message."""
        member = self.create_test_member()

        html = self.service.get_chapter_display_html(member.name)

        self.assertIn("No active chapters", html)

    def test_get_chapter_display_html_empty_member_name(self):
        """Empty member name yields the 'No member specified' message."""
        html = self.service.get_chapter_display_html("")
        self.assertIn("No member specified", html)

    # ------------------------------------------------------------------
    # disabled chapter management short-circuits the *board* query path
    # ------------------------------------------------------------------

    def test_get_board_memberships_disabled_returns_empty_even_with_seat(self):
        """When disabled, get_board_memberships returns [] even if a seat exists."""
        member, chapter = self._member_in_chapter()
        self._make_board_member(member, chapter)

        # Disable via set_single_value WITHOUT commit: production gates on
        # frappe.db.get_single_value (chapter_management_service.py:72) which sees the
        # change in the same transaction, and FrappeTestCase rolls it back at test end.
        # So enable_chapter_management=0 is never committed to the shared Single,
        # avoiding a parallel-shard race window.
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 0)
        self.assertEqual(self.service.get_board_memberships(member.name), [])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterManagementService)
    unittest.TextTestRunner(verbosity=2).run(suite)
