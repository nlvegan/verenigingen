# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for member_age_service.

These tests exercise the pure age-calculation utilities with exact boundary
values (birthday today, day-before/after birthday, leap-year Feb 29) plus the
document-mutating helpers (update_member_age_field / validate_member_age_requirements)
against real Member documents created via the factory.
"""

import unittest
from datetime import date, timedelta

from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.utils.member_age_service import (
    calculate_age_from_string,
    calculate_member_age,
    get_age_group,
    is_eligible_for_volunteering,
    is_minor,
    update_member_age_field,
    validate_member_age_requirements,
)


def _birth_date_for_age(years: int, *, offset_days: int = 0) -> date:
    """Return a birth date that yields the given age today (+/- offset days).

    Anchored to frappe's site-tz getdate(), the same clock calculate_member_age()
    uses. Python's date.today() is the server/process tz and names a different
    calendar day in the late-UTC window, which slid every boundary case by one
    day (#628).
    """
    today = getdate()
    try:
        bd = today.replace(year=today.year - years)
    except ValueError:
        # today is Feb 29 -> fall back to Feb 28
        bd = today.replace(year=today.year - years, day=28)
    return bd + timedelta(days=offset_days)


class TestMemberAgeServiceCalculations(EnhancedTestCase):
    """Pure calculation tests - no DB needed, exact value assertions."""

    def test_calculate_age_birthday_today(self):
        """Age increments exactly on the birthday."""
        bd = _birth_date_for_age(30)
        self.assertEqual(calculate_member_age(bd), 30)

    def test_calculate_age_day_before_birthday(self):
        """One day before the birthday the person is still a year younger."""
        # Birth date is tomorrow's date 30 years ago -> birthday is tomorrow -> age 29
        bd = _birth_date_for_age(30, offset_days=1)
        self.assertEqual(calculate_member_age(bd), 29)

    def test_calculate_age_day_after_birthday(self):
        """One day after the birthday the age has already incremented."""
        bd = _birth_date_for_age(30, offset_days=-1)
        self.assertEqual(calculate_member_age(bd), 30)

    def test_calculate_age_accepts_string(self):
        """String birth dates in YYYY-MM-DD are parsed correctly."""
        self.assertEqual(
            calculate_member_age("2000-01-01"),
            getdate().year - 2000 - ((getdate().month, getdate().day) < (1, 1)),
        )

    def test_calculate_age_leap_year_birth(self):
        """A Feb-29 birth date computes a sensible age (no exception)."""
        age = calculate_member_age("2000-02-29")
        # 2000 was a leap year; age must be this-year - 2000 (minus 1 before Feb 29)
        today = getdate()
        expected = today.year - 2000 - ((today.month, today.day) < (2, 29))
        self.assertEqual(age, expected)

    def test_calculate_age_none_returns_none(self):
        """Falsy birth date returns None, not 0."""
        self.assertIsNone(calculate_member_age(None))
        self.assertIsNone(calculate_member_age(""))

    def test_calculate_age_invalid_string_returns_none(self):
        """Unparseable birth date string returns None via error handling."""
        self.assertIsNone(calculate_member_age("not-a-date"))

    def test_calculate_age_from_string_valid(self):
        bd = _birth_date_for_age(45).strftime("%Y-%m-%d")
        self.assertEqual(calculate_age_from_string(bd), 45)

    def test_calculate_age_from_string_invalid(self):
        self.assertIsNone(calculate_age_from_string("13/01/1990"))
        self.assertIsNone(calculate_age_from_string(None))

    def test_get_age_group_boundaries(self):
        """Age groups bucket exactly at 18/30/50/65 boundaries."""
        self.assertEqual(get_age_group(_birth_date_for_age(17)), "Minor")
        self.assertEqual(get_age_group(_birth_date_for_age(18)), "Young Adult")
        self.assertEqual(get_age_group(_birth_date_for_age(29)), "Young Adult")
        self.assertEqual(get_age_group(_birth_date_for_age(30)), "Adult")
        self.assertEqual(get_age_group(_birth_date_for_age(49)), "Adult")
        self.assertEqual(get_age_group(_birth_date_for_age(50)), "Middle-aged")
        self.assertEqual(get_age_group(_birth_date_for_age(64)), "Middle-aged")
        self.assertEqual(get_age_group(_birth_date_for_age(65)), "Senior")

    def test_get_age_group_none(self):
        self.assertIsNone(get_age_group(None))

    def test_is_minor_boundary(self):
        """is_minor is True under 18, False at/after 18."""
        self.assertTrue(is_minor(_birth_date_for_age(17)))
        self.assertFalse(is_minor(_birth_date_for_age(18)))
        self.assertIsNone(is_minor(None))

    def test_is_eligible_for_volunteering_boundary(self):
        """Volunteering eligible at 16+, not below."""
        self.assertFalse(is_eligible_for_volunteering(_birth_date_for_age(15)))
        self.assertTrue(is_eligible_for_volunteering(_birth_date_for_age(16)))
        self.assertIsNone(is_eligible_for_volunteering(None))


class TestMemberAgeServiceDocument(EnhancedTestCase):
    """Tests that mutate / validate real Member documents."""

    def test_update_member_age_field_sets_age(self):
        """update_member_age_field writes the computed age onto the doc."""
        member = self.create_test_member(
            first_name="Age",
            last_name="Field",
            email="age.field@example.com",
            birth_date=_birth_date_for_age(40).strftime("%Y-%m-%d"),
        )
        member.age = None
        update_member_age_field(member)
        self.assertEqual(member.age, 40)

    def test_update_member_age_field_no_birth_date_clears(self):
        """With no birth date, the age field is set to None."""
        member = self.create_test_member(
            first_name="Age",
            last_name="NoBirth",
            email="age.nobirth@example.com",
        )
        member.birth_date = None
        member.age = 99
        update_member_age_field(member)
        self.assertIsNone(member.age)

    def test_validate_age_requirements_skips_without_birth_date(self):
        """No birth date -> validation is a no-op (returns None, no throw)."""
        member = self.create_test_member(
            first_name="Age",
            last_name="Skip",
            email="age.skip@example.com",
        )
        member.birth_date = None
        # Should not raise
        self.assertIsNone(validate_member_age_requirements(member))

    def test_validate_age_requirements_adult_passes(self):
        """An adult passes age validation without raising."""
        member = self.create_test_member(
            first_name="Age",
            last_name="Adult",
            email="age.adult@example.com",
            birth_date=_birth_date_for_age(35).strftime("%Y-%m-%d"),
        )
        # Direct (non-application) member, adult -> no exception
        self.assertIsNone(validate_member_age_requirements(member, allow_parental_consent=False))


if __name__ == "__main__":
    unittest.main()
