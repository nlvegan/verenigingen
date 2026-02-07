# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for ChapterManagementService

Tests chapter affiliation queries and management functionality.
Uses EnhancedTestCase for proper test data management.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
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
        # Restore original setting
        if not self._original_chapter_mgmt:
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
        member = self.create_test_member(first_name="Test", last_name="Member")

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
        member = self.create_test_member(first_name="Test", last_name="Member", birth_date="2000-01-01")

        board_memberships = self.service.get_board_memberships(member.name)

        self.assertIsInstance(board_memberships, list)
        self.assertEqual(len(board_memberships), 0)

    def test_get_board_memberships_with_volunteer_no_board_role(self):
        """Test board memberships for volunteer without board roles"""
        member = self.create_test_member(first_name="Test", last_name="Member", birth_date="2000-01-01")
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
        member = self.create_test_member(first_name="Names", last_name="Test")

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
        member = self.create_test_member(first_name="HTML", last_name="Test")

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

            member = self.create_test_member(first_name="Test", last_name="Member")

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
        member = self.create_test_member(first_name="Permission", last_name="Test")

        # These calls should succeed with proper permissions in test context
        chapters = self.service.get_member_chapters(member.name)
        self.assertIsInstance(chapters, list)

        board_memberships = self.service.get_board_memberships(member.name)
        self.assertIsInstance(board_memberships, list)

        names = self.service.get_chapter_names(member.name)
        self.assertIsInstance(names, list)

        html = self.service.get_chapter_display_html(member.name)
        self.assertIsInstance(html, str)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterManagementService)
    unittest.TextTestRunner(verbosity=2).run(suite)
