from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from verenigingen.tests.utils.clock_race import assert_written_today

_CLOCK = "verenigingen.tests.utils.clock_race"


class TestAssertWrittenToday(TestCase):
    def _at(self, moment):
        return (
            patch(f"{_CLOCK}.now_datetime", return_value=moment),
            patch(f"{_CLOCK}.today", return_value=str(moment.date())),
        )

    def _run(self, moment, value):
        a, b = self._at(moment)
        with a, b:
            assert_written_today(self, value)

    def test_same_day_passes_for_string_and_date_types(self):
        moment = datetime(2026, 3, 10, 12, 0, 0)
        self._run(moment, "2026-03-10")
        self._run(moment, moment.date())
        self._run(moment, moment)

    def test_yesterday_passes_only_just_after_midnight(self):
        self._run(datetime(2026, 3, 1, 0, 0, 5), "2026-02-28")

    def test_yesterday_fails_when_not_near_midnight(self):
        with self.assertRaises(AssertionError):
            self._run(datetime(2026, 3, 1, 0, 5, 0), "2026-02-28")

    def test_a_different_day_fails_even_just_after_midnight(self):
        with self.assertRaises(AssertionError):
            self._run(datetime(2026, 3, 1, 0, 0, 5), "2026-02-20")

    def test_none_fails(self):
        with self.assertRaises(AssertionError):
            self._run(datetime(2026, 3, 10, 12, 0, 0), None)
