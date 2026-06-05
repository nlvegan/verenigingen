"""Unit tests for verenigingen.utils.folder_category_detector."""

import unittest

from verenigingen.utils.folder_category_detector import detect_category_from_folder_path


class TestDetectCategoryFromFolderPath(unittest.TestCase):
    """Tests for folder-path-based category detection."""

    # --- Explicit category preserved ---

    def test_explicit_category_not_overridden(self):
        result = detect_category_from_folder_path(
            "Landelijk / bestuursvergadering", "Financial Report"
        )
        assert result == "Financial Report"

    def test_empty_string_category_treated_as_other(self):
        # Empty string is falsy, so it should act like "Other"
        result = detect_category_from_folder_path(
            "Landelijk / bestuursvergadering", ""
        )
        # Empty string is falsy → triggers keyword matching
        assert result == "Meeting Minutes"

    # --- Meeting Minutes keywords ---

    def test_bestuursvergadering(self):
        result = detect_category_from_folder_path(
            "Landelijk / bestuursvergadering / 2024", "Other"
        )
        assert result == "Meeting Minutes"

    def test_ledenvergadering(self):
        result = detect_category_from_folder_path(
            "Afdelingen / Amsterdam / ledenvergadering", "Other"
        )
        assert result == "Meeting Minutes"

    def test_conferentie(self):
        result = detect_category_from_folder_path("Conferenties / 2025", "Other")
        assert result == "Meeting Minutes"

    def test_congres(self):
        result = detect_category_from_folder_path("Congressen / 2024", "Other")
        assert result == "Meeting Minutes"

    def test_kaderdag(self):
        result = detect_category_from_folder_path("Kaderdagen / 2025", "Other")
        assert result == "Meeting Minutes"

    def test_notulen(self):
        result = detect_category_from_folder_path("Notulen bestuur", "Other")
        assert result == "Meeting Minutes"

    # --- Intern Bulletin ---

    def test_intern_bulletin(self):
        result = detect_category_from_folder_path(
            "Landelijk / Intern Bulletin / 2025", "Other"
        )
        assert result == "Intern Bulletin"

    def test_intern_bulletin_lowercase(self):
        result = detect_category_from_folder_path(
            "intern bulletin", "Other"
        )
        assert result == "Intern Bulletin"

    # --- Policy ---

    def test_programmacommissie(self):
        result = detect_category_from_folder_path(
            "Programmacommissie / vergaderingen", "Other"
        )
        assert result == "Policy"

    def test_minimumprogramma(self):
        result = detect_category_from_folder_path(
            "Minimumprogramma / 2025", "Other"
        )
        assert result == "Policy"

    # --- No match ---

    def test_no_keywords(self):
        # Use a path with no recognizable keyword in any category.
        result = detect_category_from_folder_path("Random Stuff / 2024", "Other")
        assert result == "Other"

    def test_empty_path(self):
        result = detect_category_from_folder_path("", "Other")
        assert result == "Other"

    def test_none_category_no_match(self):
        # None current_category is falsy → triggers keyword matching
        result = detect_category_from_folder_path("Random Stuff / 2024", None)
        assert result is None  # no keyword match, returns current_category

    # --- Case insensitivity ---

    def test_case_insensitive_match(self):
        result = detect_category_from_folder_path(
            "BESTUURSVERGADERING / 2024", "Other"
        )
        assert result == "Meeting Minutes"


if __name__ == "__main__":
    unittest.main()
