# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for MemberChapterDisplayService - Focus on XSS protection

Tests verify that all database-sourced content is properly HTML-escaped
to prevent XSS attacks via malicious chapter names, regions, or dates.
"""

import unittest
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.display.member_chapter_display_service import (
    MemberChapterDisplayService,
    get_member_chapter_display_service,
)


class MockMemberDoc:
    """Simple mock object that properly stores attributes"""
    def __init__(self, name):
        self.name = name
        self.current_chapter_display = None
        # Don't include current_chapter_display_temp so service uses main field


class TestMemberChapterDisplayService(FrappeTestCase):
    """Test suite for MemberChapterDisplayService with focus on security"""

    def test_xss_protection_in_chapter_name(self):
        """Test that malicious chapter names are HTML-escaped"""
        # Create mock member document that properly stores attributes
        member_doc = MockMemberDoc("Test-Member-001")

        # Mock chapter data with XSS payloads
        malicious_chapters = [
            {
                "chapter": "<script>alert('XSS')</script>",
                "region": "Safe Region",
                "is_primary": 1,
                "is_board": 0,
                "chapter_join_date": "2024-01-15",
            }
        ]

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            return_value=malicious_chapters,
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        # Verify the output is escaped
        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)

        # XSS payload should be escaped
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("alert(&#x27;XSS&#x27;)", output)
        self.assertNotIn("<script>", output)
        self.assertNotIn("alert('XSS')", output)

    def test_xss_protection_in_region(self):
        """Test that malicious region names are HTML-escaped"""
        member_doc = MockMemberDoc("Test-Member-002")

        malicious_chapters = [
            {
                "chapter": "Amsterdam",
                "region": "<img src=x onerror=alert(document.cookie)>",
                "is_primary": 0,
                "is_board": 1,
                "chapter_join_date": "2024-02-20",
            }
        ]

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            return_value=malicious_chapters,
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)

        # XSS payload should be escaped
        self.assertIn("&lt;img", output)
        self.assertIn("onerror=", output)  # Escaped form
        self.assertNotIn("<img src=x onerror=", output)

    def test_xss_protection_in_join_date(self):
        """Test that malicious date values are HTML-escaped"""
        member_doc = MockMemberDoc("Test-Member-003")

        malicious_chapters = [
            {
                "chapter": "Rotterdam",
                "region": "Zuid-Holland",
                "is_primary": 1,
                "is_board": 0,
                "chapter_join_date": "2024<script>alert(1)</script>-03-15",
            }
        ]

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            return_value=malicious_chapters,
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)

        # XSS payload in date should be escaped
        self.assertIn("&lt;script&gt;", output)
        self.assertNotIn("<script>alert(1)</script>", output)

    def test_safe_content_rendered_correctly(self):
        """Test that safe, normal content renders correctly"""
        member_doc = MockMemberDoc("Test-Member-004")

        safe_chapters = [
            {
                "chapter": "Amsterdam",
                "region": "Noord-Holland",
                "is_primary": 1,
                "is_board": 1,
                "chapter_join_date": "2024-01-15",
            }
        ]

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            return_value=safe_chapters,
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)

        # Safe content should be present
        self.assertIn("Amsterdam", output)
        self.assertIn("Noord-Holland", output)
        self.assertIn("2024-01-15", output)
        self.assertIn("Primary", output)
        self.assertIn("Board Member", output)

    def test_no_chapters_display(self):
        """Test empty state when member has no chapters"""
        member_doc = MockMemberDoc("Test-Member-005")

        with patch.object(
            MemberChapterDisplayService, "_get_current_chapters_optimized", return_value=[]
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)
        self.assertIn("No chapter assignment", output)

    def test_multiple_chapters_with_mixed_content(self):
        """Test multiple chapters with some malicious content"""
        member_doc = MockMemberDoc("Test-Member-006")

        mixed_chapters = [
            {
                "chapter": "Safe Chapter",
                "region": "Safe Region",
                "is_primary": 1,
                "is_board": 0,
                "chapter_join_date": "2024-01-01",
            },
            {
                "chapter": "<b>Bold Attack</b>",
                "region": "Normal Region",
                "is_primary": 0,
                "is_board": 1,
                "chapter_join_date": "2024-02-01",
            },
        ]

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            return_value=mixed_chapters,
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)

        # Safe chapter rendered normally
        self.assertIn("Safe Chapter", output)

        # Malicious chapter escaped
        self.assertIn("&lt;b&gt;Bold Attack&lt;/b&gt;", output)
        self.assertNotIn("<b>Bold Attack</b>", output)

    def test_error_handling(self):
        """Test that errors are handled gracefully"""
        member_doc = MockMemberDoc("Test-Member-007")

        with patch.object(
            MemberChapterDisplayService,
            "_get_current_chapters_optimized",
            side_effect=Exception("Database error"),
        ):
            get_member_chapter_display_service().update_current_chapter_display(member_doc)

        output = member_doc.current_chapter_display
        self.assertIsNotNone(output)
        self.assertIn("Error loading chapter information", output)


def run_tests():
    """Run test suite"""
    unittest.main()


if __name__ == "__main__":
    run_tests()
