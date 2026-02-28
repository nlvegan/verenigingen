"""Unit tests for verenigingen.utils.date_extraction."""

import unittest
from datetime import date

from verenigingen.utils.date_extraction import extract_date_from_text, extract_year_from_text


class TestExtractDateFromText(unittest.TestCase):
    """Tests for extract_date_from_text() covering all pattern types."""

    # --- Pattern 1: YYYYMMDD prefix ---

    def test_yyyymmdd_prefix_with_space(self):
        assert extract_date_from_text("20251221 Intern Bulletin 54.pdf") == date(2025, 12, 21)

    def test_yyyymmdd_prefix_with_dash(self):
        assert extract_date_from_text("20251108-Intern-Bulletin-51.pdf") == date(2025, 11, 8)

    def test_yyyymmdd_prefix_end_of_string(self):
        assert extract_date_from_text("20250130") == date(2025, 1, 30)

    def test_yyyymmdd_invalid_month_skipped(self):
        # Month 13 is invalid; should not match as YYYYMMDD
        assert extract_date_from_text("20251321 document.pdf") is None

    def test_yyyymmdd_invalid_day_skipped(self):
        # Day 32 is invalid
        assert extract_date_from_text("20250132 document.pdf") is None

    # --- Pattern 2: YYYY-MM-DD (ISO) ---

    def test_iso_date_inline(self):
        assert extract_date_from_text("Notulen 2025-12-10.docx") == date(2025, 12, 10)

    def test_iso_date_at_start(self):
        assert extract_date_from_text("2025-01-15 meeting notes.pdf") == date(2025, 1, 15)

    def test_iso_date_invalid_feb_30(self):
        # Feb 30 doesn't exist
        assert extract_date_from_text("report 2025-02-30.pdf") is None

    # --- Pattern 3: DD-MM-YYYY (European) ---

    def test_european_date_at_start(self):
        assert extract_date_from_text("18-01-2026 - Intern Bulletin 56.pdf") == date(2026, 1, 18)

    def test_european_date_inline(self):
        result = extract_date_from_text("Notulen uitgebreide bestuursvergadering 28-09-2025.pdf")
        assert result == date(2025, 9, 28)

    def test_european_date_with_slashes(self):
        assert extract_date_from_text("report 15/03/2025.pdf") == date(2025, 3, 15)

    def test_european_date_with_dots(self):
        assert extract_date_from_text("verslag 01.06.2024.docx") == date(2024, 6, 1)

    # --- Pattern 4: YYYY MM DD (space-separated) ---

    def test_space_separated_date(self):
        assert extract_date_from_text("2025 08 30 notulen kaderdag.pdf") == date(2025, 8, 30)

    # --- Pattern 5: Dutch month names ---

    def test_dutch_month_dd_month_yyyy(self):
        assert extract_date_from_text("31 mei 2025 Notulen congres .pdf") == date(2025, 5, 31)

    def test_dutch_month_januari(self):
        assert extract_date_from_text("15 januari 2024 verslag.pdf") == date(2024, 1, 15)

    def test_dutch_month_case_insensitive(self):
        assert extract_date_from_text("3 OKTOBER 2025 rapport.pdf") == date(2025, 10, 3)

    def test_dutch_month_invalid_day(self):
        # 31 februari doesn't exist
        assert extract_date_from_text("31 februari 2025 verslag.pdf") is None

    # --- No date ---

    def test_no_date_at_all(self):
        assert extract_date_from_text("Grondvesten Paraat.docx") is None

    def test_no_date_logo(self):
        assert extract_date_from_text("RSP_logo_rood.png") is None

    def test_empty_string(self):
        assert extract_date_from_text("") is None

    def test_none_input(self):
        assert extract_date_from_text(None) is None

    # --- Priority: YYYYMMDD prefix wins over ISO ---

    def test_yyyymmdd_wins_over_iso_in_same_string(self):
        # YYYYMMDD at start should be tried first
        result = extract_date_from_text("20250115-report-2025-02-20.pdf")
        assert result == date(2025, 1, 15)


class TestExtractYearFromText(unittest.TestCase):
    """Tests for extract_year_from_text()."""

    def test_year_from_full_date(self):
        assert extract_year_from_text("Notulen 2025-12-10.docx") == "2025"

    def test_year_from_standalone_pattern(self):
        assert extract_year_from_text("Jaarverslag 2024.pdf") == "2024"

    def test_year_from_european_date(self):
        assert extract_year_from_text("18-01-2026 bulletin.pdf") == "2026"

    def test_no_year_returns_default(self):
        assert extract_year_from_text("logo.png") == "Other"

    def test_custom_default(self):
        assert extract_year_from_text("logo.png", default="Unknown") == "Unknown"

    def test_empty_string(self):
        assert extract_year_from_text("") == "Other"

    def test_none_input(self):
        assert extract_year_from_text(None) == "Other"

    def test_standalone_year_not_date(self):
        # "Report 2023" has a year but not a full date
        assert extract_year_from_text("Report 2023") == "2023"

    def test_yyyymmdd_prefix_extracts_year(self):
        assert extract_year_from_text("20231015 Budget.pdf") == "2023"


class TestEdgeCases(unittest.TestCase):
    """Edge case tests for ambiguous or tricky inputs."""

    def test_year_only_folder_name(self):
        # A folder named "2024" — standalone year, no full date
        assert extract_year_from_text("2024") == "2024"

    def test_multiple_years_first_wins(self):
        # ISO pattern matches first occurrence
        assert extract_year_from_text("meeting 2024-01-15 report 2025-06-01.pdf") == "2024"

    def test_path_with_separators(self):
        # Folder path style
        assert extract_year_from_text("Landelijk / bestuursvergadering / 2024") == "2024"

    def test_filename_with_version_number(self):
        # "v2" shouldn't be mistaken for a year
        assert extract_year_from_text("report_v2_final.pdf") == "Other"

    def test_four_digit_non_year(self):
        # 1999 doesn't match our 20xx pattern
        assert extract_year_from_text("archive_1999.pdf") == "Other"


if __name__ == "__main__":
    unittest.main()
