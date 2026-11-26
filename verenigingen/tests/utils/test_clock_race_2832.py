"""The double-clock-read shapes from #2832 fail across midnight; assert_written_today does not.

Each test makes production write at 23:59:59 on day D (its own clock read) and
lets the assertion read the clock at 00:00:01 on D+1, which is what a test that
straddles midnight sees. The "old shape" tests pin that the pre-#2832 assertion
really fails there; the "new shape" tests pin that the helper accepts it.
"""

from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch

import frappe.utils

from verenigingen.tests.utils.clock_race import assert_written_today
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoTransaction

WRITE_DAY = date(2026, 3, 10)
AFTER_MIDNIGHT = datetime(2026, 3, 11, 0, 0, 1)
_CLOCK = "verenigingen.tests.utils.clock_race"


def _write_on_write_day():
    """Production side: a missing valueDate falls back to getdate() (read #1, still day D)."""
    with patch("verenigingen.verenigingen_payments.ponto.core.ponto_models.getdate", return_value=WRITE_DAY):
        return PontoTransaction._parse_date(None)


class TestMidnightStraddle2832(TestCase):
    def test_old_getdate_shape_fails_across_midnight(self):
        written = _write_on_write_day()
        with patch("frappe.utils.getdate", return_value=AFTER_MIDNIGHT.date()):
            with self.assertRaises(AssertionError):
                self.assertEqual(written, frappe.utils.getdate())

    def test_old_str_today_shape_fails_across_midnight(self):
        written = _write_on_write_day()
        with patch("frappe.utils.today", return_value=str(AFTER_MIDNIGHT.date())):
            with self.assertRaises(AssertionError):
                self.assertEqual(str(written), str(frappe.utils.today()))

    def test_helper_accepts_the_same_straddle(self):
        written = _write_on_write_day()
        with patch(f"{_CLOCK}.now_datetime", return_value=AFTER_MIDNIGHT):
            assert_written_today(self, written)
            assert_written_today(self, str(written))

    def test_helper_still_rejects_a_genuinely_stale_date(self):
        # Control: the helper is not simply always-true.
        with patch(f"{_CLOCK}.now_datetime", return_value=AFTER_MIDNIGHT):
            with self.assertRaises(AssertionError):
                assert_written_today(self, date(2026, 3, 8))
