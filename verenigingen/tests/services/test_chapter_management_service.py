# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for chapter_management_service.

Covers chapter affiliation queries (optimized + fallback), board-membership
detection, chapter-name listing, HTML rendering (XSS-safe), and input/validation
guards against real Chapter / Chapter Member / Chapter Board Member / Volunteer
records.
"""

import unittest

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.chapter.chapter_management_service import (
    ChapterManagementService,
    get_chapter_management_service,
)


class ChapterServiceTestBase(EnhancedTestCase):
    """Shared setup helpers for chapter service tests."""

    def setUp(self):
        super().setUp()
        self.service = ChapterManagementService()

    def _ensure_chapter_role(self):
        """Get-or-create a 'Test Board Role' Chapter Role (self-seed for CI)."""
        name = "Test Board Role"
        if not frappe.db.exists("Chapter Role", name):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": name,
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            )
            role.insert(ignore_permissions=True)
            self._track_test_document("Chapter Role", role.name)
            return role.name
        return name

    def _build_member_in_chapter(self, *, email, board=False):
        """Create a member and add them to a fresh chapter (optionally as board)."""
        member = self.create_test_member(
            first_name="Chap",
            last_name="Member",
            email=email,
        )
        chapter = self.create_test_chapter()
        chapter.append(
            "members",
            {"member": member.name, "chapter_join_date": today(), "status": "Active", "enabled": 1},
        )
        if board:
            volunteer = self.create_test_volunteer(member_name=member.name)
            role = self._ensure_chapter_role()
            chapter.append(
                "board_members",
                {
                    "volunteer": volunteer.name,
                    "chapter_role": role,
                    "from_date": today(),
                    "is_active": 1,
                },
            )
        chapter.save()
        return member, chapter


class TestChapterManagementEnabled(ChapterServiceTestBase):
    def test_enabled_flag_reflects_setting(self):
        """is_chapter_management_enabled mirrors the Verenigingen Settings flag."""
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)
        self.assertTrue(self.service.is_chapter_management_enabled())
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 0)
        self.assertFalse(self.service.is_chapter_management_enabled())
        # restore
        frappe.db.set_single_value("Verenigingen Settings", "enable_chapter_management", 1)


class TestGetMemberChapters(ChapterServiceTestBase):
    def test_empty_member_name_returns_empty(self):
        self.assertEqual(self.service.get_member_chapters_optimized(""), [])
        self.assertEqual(self.service.get_member_chapters(""), [])

    def test_nonexistent_member_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self.service.get_member_chapters_optimized("NONEXISTENT-MEMBER-XYZ")

    def test_optimized_returns_chapter_with_primary_flag(self):
        member, chapter = self._build_member_in_chapter(email="chap.opt@example.com")
        chapters = self.service.get_member_chapters_optimized(member.name)
        self.assertEqual(len(chapters), 1)
        row = chapters[0]
        self.assertEqual(row["chapter"], chapter.name)
        self.assertEqual(row["status"], "Active")
        self.assertTrue(row["is_primary"])
        self.assertFalse(row["is_board"])

    def test_optimized_flags_board_member(self):
        member, chapter = self._build_member_in_chapter(email="chap.board@example.com", board=True)
        chapters = self.service.get_member_chapters_optimized(member.name)
        self.assertEqual(len(chapters), 1)
        self.assertTrue(chapters[0]["is_board"])

    def test_fallback_matches_optimized_structure(self):
        member, chapter = self._build_member_in_chapter(email="chap.fallback@example.com", board=True)
        chapters = self.service.get_member_chapters(member.name)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["chapter"], chapter.name)
        self.assertTrue(chapters[0]["is_primary"])
        self.assertTrue(chapters[0]["is_board"])


class TestBoardMemberships(ChapterServiceTestBase):
    def test_get_board_memberships_returns_position(self):
        member, chapter = self._build_member_in_chapter(email="board.list@example.com", board=True)
        positions = self.service.get_board_memberships(member.name)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["chapter"], chapter.name)
        self.assertEqual(positions[0]["role"], "Test Board Role")

    def test_get_board_memberships_empty_for_non_board(self):
        member, _ = self._build_member_in_chapter(email="board.none@example.com")
        self.assertEqual(self.service.get_board_memberships(member.name), [])

    def test_check_board_membership_true(self):
        member, chapter = self._build_member_in_chapter(email="board.check@example.com", board=True)
        self.assertTrue(self.service.check_board_membership(member.name, chapter.name))

    def test_check_board_membership_false_for_plain_member(self):
        member, chapter = self._build_member_in_chapter(email="board.plain@example.com")
        self.assertFalse(self.service.check_board_membership(member.name, chapter.name))

    def test_check_board_membership_nonexistent_chapter_raises(self):
        member, _ = self._build_member_in_chapter(email="board.badchap@example.com")
        with self.assertRaises(frappe.ValidationError):
            self.service.check_board_membership(member.name, "NONEXISTENT-CHAPTER")

    def test_check_board_membership_empty_args_false(self):
        self.assertFalse(self.service.check_board_membership("", "x"))
        self.assertFalse(self.service.check_board_membership("x", ""))


class TestChapterNamesAndHtml(ChapterServiceTestBase):
    def test_get_chapter_names(self):
        member, chapter = self._build_member_in_chapter(email="names.test@example.com")
        names = self.service.get_chapter_names(member.name)
        self.assertEqual(names, [chapter.name])

    def test_get_chapter_names_empty(self):
        self.assertEqual(self.service.get_chapter_names(""), [])

    def test_display_html_no_member(self):
        html = self.service.get_chapter_display_html("")
        self.assertIn("No member specified", html)

    def test_display_html_no_chapters(self):
        member = self.create_test_member(
            first_name="Html",
            last_name="NoChap",
            email="html.nochap@example.com",
        )
        html = self.service.get_chapter_display_html(member.name)
        self.assertIn("No active chapters", html)

    def test_display_html_renders_badge_with_chapter_name(self):
        member, chapter = self._build_member_in_chapter(email="html.badge@example.com")
        html = self.service.get_chapter_display_html(member.name)
        self.assertIn("chapter-list", html)
        self.assertIn(frappe.utils.escape_html(chapter.name), html)
        # Active status maps to the success CSS class
        self.assertIn("badge-success", html)


class TestSingletonAccessor(ChapterServiceTestBase):
    def test_accessor_returns_service(self):
        svc = get_chapter_management_service()
        self.assertIsInstance(svc, ChapterManagementService)


if __name__ == "__main__":
    unittest.main()
