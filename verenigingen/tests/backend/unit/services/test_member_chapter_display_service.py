# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberChapterDisplayService

Tests the member chapter display service to ensure:
- Force update sets flags and saves properly
- Chapter display is updated correctly
- Optimized query with fallback works
- Change detection works for display updates
- Error handling works correctly

Tests cover methods added during member.py extraction.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMemberChapterDisplayServiceForceUpdate(unittest.TestCase):
    """Test force_update_chapter_display() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )
        self.service = get_member_chapter_display_service()

    def test_force_update_sets_flag_and_saves(self):
        """Test that force update sets flag, updates display, and saves"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.current_chapter_display = "Test Display"

        with patch.object(self.service, "update_current_chapter_display"):
            result = self.service.force_update_chapter_display(mock_member)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Chapter display updated")
        mock_member.save.assert_called_once()

    def test_force_update_clears_flag_on_success(self):
        """Test that the assignment flag is cleared after success"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._chapter_assignment_in_progress = True

        with patch.object(self.service, "update_current_chapter_display"):
            self.service.force_update_chapter_display(mock_member)

        # Flag should be cleared in finally block
        self.assertFalse(
            hasattr(mock_member, "_chapter_assignment_in_progress")
            and mock_member._chapter_assignment_in_progress
        )

    def test_force_update_handles_save_error(self):
        """Test error handling when save fails"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.save.side_effect = Exception("Save failed")

        with patch.object(self.service, "update_current_chapter_display"):
            result = self.service.force_update_chapter_display(mock_member)

        self.assertFalse(result["success"])
        self.assertIn("error", result)


class TestMemberChapterDisplayServiceOptimized(unittest.TestCase):
    """Test get_current_chapters_optimized() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )
        self.service = get_member_chapter_display_service()

    def test_returns_empty_for_no_name(self):
        """Test that empty list is returned when member has no name"""
        mock_member = MagicMock()
        mock_member.name = None

        result = self.service.get_current_chapters_optimized(mock_member)

        self.assertEqual(result, [])

    def test_delegates_to_internal_method(self):
        """Test that optimized method delegates correctly"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        with patch.object(self.service, "_get_current_chapters_optimized", return_value=[{"chapter": "Amsterdam"}]):
            result = self.service.get_current_chapters_optimized(mock_member)

        self.assertEqual(result, [{"chapter": "Amsterdam"}])

    @patch("verenigingen.services.member.chapter.chapter_management_service.get_chapter_management_service")
    def test_fallback_on_error(self, mock_get_service):
        """Test fallback to standard method on error"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_service = MagicMock()
        mock_service.get_member_chapters.return_value = [{"chapter": "Fallback"}]
        mock_get_service.return_value = mock_service

        with patch.object(self.service, "_get_current_chapters_optimized", side_effect=Exception("Query failed")):
            result = self.service.get_current_chapters_optimized(mock_member)

        self.assertEqual(result, [{"chapter": "Fallback"}])
        mock_service.get_member_chapters.assert_called_once_with("MEM-001")


class TestMemberChapterDisplayServiceShouldUpdate(unittest.TestCase):
    """Test should_update_chapter_display() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )
        self.service = get_member_chapter_display_service()

    def test_returns_false_for_new_records(self):
        """Test that new records don't trigger update"""
        mock_member = MagicMock()
        mock_member.is_new.return_value = True

        result = self.service.should_update_chapter_display(mock_member)

        self.assertFalse(result)

    def test_returns_true_when_pincode_changed(self):
        """Test that pincode change triggers update"""
        mock_member = MagicMock()
        mock_member.is_new.return_value = False
        mock_member.has_value_changed.side_effect = lambda f: f == "pincode"

        result = self.service.should_update_chapter_display(mock_member)

        self.assertTrue(result)

    def test_returns_true_when_city_changed(self):
        """Test that city change triggers update"""
        mock_member = MagicMock()
        mock_member.is_new.return_value = False
        mock_member.has_value_changed.side_effect = lambda f: f == "city"

        result = self.service.should_update_chapter_display(mock_member)

        self.assertTrue(result)

    def test_returns_true_when_assignment_in_progress(self):
        """Test that explicit assignment flag triggers update"""
        mock_member = MagicMock()
        mock_member.is_new.return_value = False
        mock_member.has_value_changed.return_value = False
        mock_member._chapter_assignment_in_progress = True

        result = self.service.should_update_chapter_display(mock_member)

        self.assertTrue(result)

    def test_returns_false_when_no_changes(self):
        """Test that no changes means no update needed"""
        mock_member = MagicMock()
        mock_member.is_new.return_value = False
        mock_member.has_value_changed.return_value = False
        # No _chapter_assignment_in_progress attribute
        del mock_member._chapter_assignment_in_progress

        result = self.service.should_update_chapter_display(mock_member)

        self.assertFalse(result)


class TestMemberChapterDisplayServiceUpdateDisplay(unittest.TestCase):
    """Test update_current_chapter_display() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )
        self.service = get_member_chapter_display_service()

    def test_sets_no_chapter_message_when_empty(self):
        """Test empty chapter list shows appropriate message"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        # No current_chapter_display_temp attribute
        del mock_member.current_chapter_display_temp

        with patch.object(self.service, "_get_current_chapters_optimized", return_value=[]):
            self.service.update_current_chapter_display(mock_member)

        self.assertIn("No chapter assignment", mock_member.current_chapter_display)

    def test_generates_html_for_chapters(self):
        """Test HTML generation for chapter list"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        del mock_member.current_chapter_display_temp

        chapters = [
            {"chapter": "Amsterdam", "region": "Noord-Holland", "is_primary": True, "is_board": False, "chapter_join_date": "2024-01-15"}
        ]

        with patch.object(self.service, "_get_current_chapters_optimized", return_value=chapters):
            self.service.update_current_chapter_display(mock_member)

        self.assertIn("Amsterdam", mock_member.current_chapter_display)
        self.assertIn("Noord-Holland", mock_member.current_chapter_display)
        self.assertIn("Primary", mock_member.current_chapter_display)
        self.assertIn("2024-01-15", mock_member.current_chapter_display)

    def test_handles_exception_gracefully(self):
        """Test error handling sets error message"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        with patch.object(self.service, "_get_current_chapters_optimized", side_effect=Exception("DB Error")):
            self.service.update_current_chapter_display(mock_member)

        self.assertIn("Error loading chapter", mock_member.current_chapter_display)


if __name__ == "__main__":
    unittest.main()
