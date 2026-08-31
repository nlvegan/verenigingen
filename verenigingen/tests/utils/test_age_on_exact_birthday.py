"""#657 — an age gate must accept the applicant on their own Nth birthday.

`AgeValidator.calculate_age` used to return `days / 365.25`, a float. An N-year
span contains exactly `N // 4` leap days (over the ranges we care about), so
`N * 365.25` is a whole number of days **only when 4 divides N**. For every other
threshold the float sits ~0.002 *below* the integer on the person's own birthday,
and `if age_years < min_age` rejects them.

The thresholds below are split deliberately:

* `DIVISIBLE_BY_FOUR` are **controls**. They passed before the fix as well —
  16 and 12 are the configured membership/youth minimums on the live site, which
  is why nobody noticed. If these ever go red the test setup is broken, not the
  arithmetic.
* `NOT_DIVISIBLE_BY_FOUR` are the ones the bug ate: voting (18), student (14),
  senior (65), and 21 — a `minimum_volunteer_age` that `test_vip_import.py`
  already exercises as a supported configuration.

Each gate assertion is paired with a "one day short" assertion, so a fix that
merely made ages enormous could not turn the suite green.
"""

import frappe
from frappe.utils import add_days, add_years, getdate, today

from verenigingen.services.member.utils.member_age_service import calculate_member_age, get_age_group
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.verenigingen_settings import pinned_setting
from verenigingen.utils.validation_utilities import AgeValidator, ValidationError

DIVISIBLE_BY_FOUR = (12, 16, 20)
NOT_DIVISIBLE_BY_FOUR = (14, 17, 18, 21, 65)
ALL_THRESHOLDS = DIVISIBLE_BY_FOUR + NOT_DIVISIBLE_BY_FOUR


class TestAgeOnExactBirthday(EnhancedTestCase):
    """The arithmetic half of #657, at the AgeValidator layer."""

    def test_calculate_age_returns_the_integer_calendar_age_on_the_birthday(self):
        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n):
                self.assertEqual(
                    AgeValidator.calculate_age(add_years(ref, -n)),
                    n,
                    f"Someone born exactly {n} years ago today is {n}, not a float just under it",
                )

    def test_calculate_age_is_one_less_the_day_before_the_birthday(self):
        """Control: the fix must not simply round everything up."""
        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n):
                self.assertEqual(AgeValidator.calculate_age(add_days(add_years(ref, -n), 1)), n - 1)

    def test_calculate_age_still_honours_reference_date(self):
        """`reference_date` must survive the delegation to member_age_service."""
        self.assertEqual(AgeValidator.calculate_age("2000-03-01", "2018-02-28"), 17)
        self.assertEqual(AgeValidator.calculate_age("2000-03-01", "2018-03-01"), 18)
        self.assertEqual(AgeValidator.calculate_age("2000-03-01", "2018-03-02"), 18)

    def test_calculate_age_still_raises_on_a_future_birth_date(self):
        """`calculate_member_age` swallows and returns None; this must not (#597).

        Direct callers get the refusal. `validate_age` catches it and converts it
        to a soft result, so this is the layer where the raise has to be pinned.
        """
        with self.assertRaises(ValidationError):
            AgeValidator.calculate_age(add_years(getdate(today()), 1))

    def test_calculate_age_raises_for_a_birth_date_after_the_reference_date(self):
        with self.assertRaises(ValidationError):
            AgeValidator.calculate_age("2020-01-01", "2019-01-01")

    def test_minimum_age_gate_accepts_on_the_exact_birthday(self):
        """The decisive case: min_age N, born exactly N years ago today."""
        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n):
                result = AgeValidator.validate_age(
                    add_years(ref, -n), context="volunteer", custom_min_age=n, throw_on_error=False
                )
                self.assertTrue(
                    result.is_valid,
                    f"min_age={n}: an applicant turning {n} today must be accepted "
                    f"(got: {result.message})",
                )

    def test_minimum_age_gate_still_rejects_the_day_before_the_birthday(self):
        """Control: the gate must still discriminate."""
        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n):
                result = AgeValidator.validate_age(
                    add_days(add_years(ref, -n), 1),
                    context="volunteer",
                    custom_min_age=n,
                    throw_on_error=False,
                )
                self.assertFalse(
                    result.is_valid, f"min_age={n}: someone who turns {n} tomorrow must be rejected"
                )


class TestAgeArithmeticConvergence(EnhancedTestCase):
    """The three spellings that remain must agree with the canonical owner."""

    def test_age_validator_agrees_with_member_age_service(self):
        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n):
                birth = add_years(ref, -n)
                self.assertEqual(AgeValidator.calculate_age(birth), calculate_member_age(birth))

    def test_get_age_group_buckets_on_the_exact_eighteenth_birthday(self):
        ref = getdate(today())
        self.assertEqual(get_age_group(add_years(ref, -18)), "Young Adult")
        self.assertEqual(get_age_group(add_days(add_years(ref, -18), 1)), "Minor")
        self.assertEqual(get_age_group(add_years(ref, -65)), "Senior")
        self.assertEqual(get_age_group(add_days(add_years(ref, -65), 1)), "Middle-aged")

    def test_get_age_group_still_returns_none_for_a_future_birth_date(self):
        self.assertIsNone(get_age_group(add_years(getdate(today()), 1)))


class TestVipImportVolunteerAgeGate(EnhancedTestCase):
    """`vip_import._validate_volunteer_age` gates the same rule with its own formula."""

    def test_vip_import_accepts_a_member_on_their_exact_nth_birthday(self):
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _validate_volunteer_age

        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n), pinned_setting("minimum_volunteer_age", n):
                member = frappe.new_doc("Member")
                member.birth_date = add_years(ref, -n)
                self.assertIsNone(
                    _validate_volunteer_age(member),
                    f"minimum_volunteer_age={n}: a member turning {n} today qualifies",
                )

    def test_vip_import_still_rejects_the_day_before_the_birthday(self):
        from verenigingen.verenigingen.doctype.vip_import.vip_import import _validate_volunteer_age

        ref = getdate(today())
        for n in ALL_THRESHOLDS:
            with self.subTest(threshold=n), pinned_setting("minimum_volunteer_age", n):
                member = frappe.new_doc("Member")
                member.birth_date = add_days(add_years(ref, -n), 1)
                self.assertIsNotNone(_validate_volunteer_age(member))
