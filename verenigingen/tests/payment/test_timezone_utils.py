"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/timezone_utils.py
(previously ~35% covered).

These are pure datetime/timezone conversion helpers used by the Mollie
integration to normalise Mollie API timestamps and compute settlement /
reporting period date ranges. They have no DocType side effects, so the tests
exercise the real functions directly against real datetime inputs and assert
the real returned values / branches. Nothing is mocked: ``get_system_timezone``
and ``pytz`` are exercised as-is.

Base class: VereningingenTestCase (FrappeTestCase-derived, auto-rollback,
runs as Administrator). No data is created.
"""

import unittest
from datetime import datetime, timedelta, timezone

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils import timezone_utils as tz


class TestEnsureTimezoneAware(VereningingenTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(tz.ensure_timezone_aware(None))

    def test_naive_gets_utc(self):
        naive = datetime(2025, 1, 15, 10, 30, 0)
        out = tz.ensure_timezone_aware(naive)
        self.assertIsNotNone(out.tzinfo)
        self.assertEqual(out.utcoffset(), timedelta(0))
        # Wall-clock fields are unchanged; only tzinfo is attached.
        self.assertEqual(out.replace(tzinfo=None), naive)

    def test_aware_is_passed_through_unchanged(self):
        aware = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone(timedelta(hours=2)))
        out = tz.ensure_timezone_aware(aware)
        self.assertIs(out, aware)


class TestEnsureTimezoneNaive(VereningingenTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(tz.ensure_timezone_naive(None))

    def test_naive_passed_through(self):
        naive = datetime(2025, 1, 15, 10, 30, 0)
        out = tz.ensure_timezone_naive(naive)
        self.assertIsNone(out.tzinfo)
        self.assertEqual(out, naive)

    def test_aware_converted_to_utc_then_stripped(self):
        # 12:30 at +02:00 == 10:30 UTC; result must be naive 10:30.
        aware = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone(timedelta(hours=2)))
        out = tz.ensure_timezone_naive(aware)
        self.assertIsNone(out.tzinfo)
        self.assertEqual(out, datetime(2025, 1, 15, 10, 30, 0))


class TestParseMollieDatetime(VereningingenTestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(tz.parse_mollie_datetime(""))
        self.assertIsNone(tz.parse_mollie_datetime(None))

    def test_z_suffix_parsed_as_utc(self):
        out = tz.parse_mollie_datetime("2025-01-15T10:30:00Z")
        self.assertEqual(out, datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc))
        self.assertEqual(out.utcoffset(), timedelta(0))

    def test_offset_suffix_parsed(self):
        out = tz.parse_mollie_datetime("2025-01-15T10:30:00+02:00")
        self.assertEqual(out.utcoffset(), timedelta(hours=2))

    def test_invalid_string_returns_none(self):
        # Mock justified: parse failure path emits a frappe.logger().warning; we
        # assert the production return contract (None), not the log transport.
        self.assertIsNone(tz.parse_mollie_datetime("not-a-date"))


class TestMollieDatetimeForDisplay(VereningingenTestCase):
    def test_empty_returns_empty_string(self):
        self.assertEqual(tz.mollie_datetime_for_display(None), "")

    def test_naive_formatted_without_tz(self):
        naive = datetime(2025, 1, 15, 10, 30, 45)
        self.assertEqual(tz.mollie_datetime_for_display(naive), "2025-01-15 10:30:45")

    def test_aware_formatted_with_tz_token(self):
        aware = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        out = tz.mollie_datetime_for_display(aware)
        # Aware path converts to system tz and appends a %Z token; it is a real
        # formatted string carrying the date.
        self.assertIn("2025-06-15", out)
        self.assertRegex(out, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class TestSafeDatetimeToIsoformat(VereningingenTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(tz.safe_datetime_to_isoformat(None))

    def test_string_passed_through(self):
        self.assertEqual(
            tz.safe_datetime_to_isoformat("2025-01-15T10:30:00+00:00"),
            "2025-01-15T10:30:00+00:00",
        )

    def test_naive_datetime_isoformat(self):
        out = tz.safe_datetime_to_isoformat(datetime(2025, 1, 15, 10, 30, 0))
        self.assertEqual(out, "2025-01-15T10:30:00")

    def test_aware_datetime_normalised_to_naive_utc(self):
        # +02:00 12:30 -> naive UTC 10:30 -> iso without offset.
        aware = datetime(2025, 1, 15, 12, 30, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(tz.safe_datetime_to_isoformat(aware), "2025-01-15T10:30:00")

    def test_other_type_stringified(self):
        self.assertEqual(tz.safe_datetime_to_isoformat(12345), "12345")


class TestGetPeriodDateRange(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        # Fixed reference: Wed 2025-05-14 13:45:12 UTC (week starts Mon 2025-05-12).
        self.ref = datetime(2025, 5, 14, 13, 45, 12, tzinfo=timezone.utc)

    def test_day(self):
        start, end = tz.get_period_date_range("day", self.ref)
        self.assertEqual(start, datetime(2025, 5, 14, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, self.ref)

    def test_week_starts_monday(self):
        start, end = tz.get_period_date_range("week", self.ref)
        self.assertEqual(start, datetime(2025, 5, 12, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, self.ref)

    def test_month(self):
        start, _ = tz.get_period_date_range("month", self.ref)
        self.assertEqual(start, datetime(2025, 5, 1, 0, 0, 0, tzinfo=timezone.utc))

    def test_quarter_q2(self):
        # May is in Q2 -> quarter starts April 1.
        start, _ = tz.get_period_date_range("quarter", self.ref)
        self.assertEqual(start, datetime(2025, 4, 1, 0, 0, 0, tzinfo=timezone.utc))

    def test_quarter_q1_boundary(self):
        jan = datetime(2025, 1, 20, 9, 0, 0, tzinfo=timezone.utc)
        start, _ = tz.get_period_date_range("quarter", jan)
        self.assertEqual(start, datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc))

    def test_year(self):
        start, _ = tz.get_period_date_range("year", self.ref)
        self.assertEqual(start, datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc))

    def test_naive_reference_made_aware(self):
        naive_ref = datetime(2025, 5, 14, 13, 45, 12)
        start, end = tz.get_period_date_range("day", naive_ref)
        self.assertEqual(start.utcoffset(), timedelta(0))
        self.assertEqual(end.utcoffset(), timedelta(0))

    def test_default_reference_is_now_utc(self):
        before = datetime.now(timezone.utc)
        start, end = tz.get_period_date_range("day")
        after = datetime.now(timezone.utc)
        # end == "now" reference; start == midnight UTC of today.
        self.assertTrue(before <= end <= after)
        self.assertEqual(start, end.replace(hour=0, minute=0, second=0, microsecond=0))

    def test_unknown_period_raises(self):
        with self.assertRaises(ValueError):
            tz.get_period_date_range("fortnight", self.ref)


class TestFilterItemsByDateRange(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.start = datetime(2025, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
        self.end = datetime(2025, 1, 20, 0, 0, 0, tzinfo=timezone.utc)

    def test_filters_inside_and_outside(self):
        items = [
            {"id": "in1", "createdAt": "2025-01-12T08:00:00Z"},
            {"id": "out_before", "createdAt": "2025-01-01T08:00:00Z"},
            {"id": "out_after", "createdAt": "2025-01-25T08:00:00Z"},
            {"id": "edge_start", "createdAt": "2025-01-10T00:00:00Z"},
        ]
        out = tz.filter_items_by_date_range(items, self.start, self.end)
        ids = {i["id"] for i in out}
        self.assertEqual(ids, {"in1", "edge_start"})

    def test_missing_and_unparseable_dates_skipped(self):
        items = [
            {"id": "nodate"},
            {"id": "baddate", "createdAt": "garbage"},
            {"id": "good", "createdAt": "2025-01-15T08:00:00Z"},
        ]
        out = tz.filter_items_by_date_range(items, self.start, self.end)
        self.assertEqual([i["id"] for i in out], ["good"])

    def test_custom_date_field(self):
        items = [{"id": "x", "settledAt": "2025-01-15T08:00:00Z", "createdAt": "2099-01-01T00:00:00Z"}]
        out = tz.filter_items_by_date_range(items, self.start, self.end, date_field="settledAt")
        self.assertEqual(len(out), 1)

    def test_naive_bounds_treated_as_utc(self):
        # Naive start/end must be coerced to UTC inside the function (real branch).
        naive_start = datetime(2025, 1, 10, 0, 0, 0)
        naive_end = datetime(2025, 1, 20, 0, 0, 0)
        items = [{"id": "in", "createdAt": "2025-01-15T08:00:00Z"}]
        out = tz.filter_items_by_date_range(items, naive_start, naive_end)
        self.assertEqual(len(out), 1)


class TestParsePeriodKeyToDateRange(VereningingenTestCase):
    def test_regular_month(self):
        start, end = tz.parse_period_key_to_date_range("2025-03")
        self.assertEqual(start, datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc))
        # End is last second of March.
        self.assertEqual(end, datetime(2025, 3, 31, 23, 59, 59, tzinfo=timezone.utc))

    def test_december_rolls_to_next_year(self):
        start, end = tz.parse_period_key_to_date_range("2025-12")
        self.assertEqual(start, datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc))

    def test_february_non_leap(self):
        _, end = tz.parse_period_key_to_date_range("2025-02")
        self.assertEqual(end, datetime(2025, 2, 28, 23, 59, 59, tzinfo=timezone.utc))

    def test_invalid_format_raises_valueerror(self):
        with self.assertRaises(ValueError):
            tz.parse_period_key_to_date_range("2025/03")

    def test_non_numeric_raises_valueerror(self):
        with self.assertRaises(ValueError):
            tz.parse_period_key_to_date_range("abcd-ef")


if __name__ == "__main__":
    unittest.main()
