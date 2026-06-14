"""
Tests for the SEPA Direct Debit Batch Scheduler date/eligibility/config logic.

verenigingen/verenigingen_payments/api/dd_batch_scheduler.py is almost entirely
pure scheduling logic: which day of the month is a batch-creation day, whether to
skip weekends/holidays, the next business day, validation of the configured-days
string, and the schedule/config builders. None of that touches Mollie or the
network, so it is tested directly with real Verenigingen Payments Settings.

The whitelisted entrypoints get_batch_creation_schedule / validate_batch_creation_days
/ toggle_auto_batch_creation are exercised as a real privileged user so their
permission decorators run exactly as in production.
"""

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import dd_batch_scheduler as sched


class TestDDBatchSchedulerLogic(EnhancedTestCase):
    """Pure date / eligibility / validation logic - no privileged context needed."""

    # --- is_bank_holiday -----------------------------------------------------

    def test_is_bank_holiday_recognises_fixed_dutch_holidays(self):
        # New Year, King's Day, Christmas, Boxing Day are fixed in the impl.
        self.assertTrue(sched.is_bank_holiday(getdate("2026-01-01")))
        self.assertTrue(sched.is_bank_holiday(getdate("2026-04-27")))
        self.assertTrue(sched.is_bank_holiday(getdate("2026-12-25")))
        self.assertTrue(sched.is_bank_holiday(getdate("2026-12-26")))

    def test_is_bank_holiday_false_for_ordinary_day(self):
        # 2026-03-10 is a Tuesday and not in the holiday list.
        self.assertFalse(sched.is_bank_holiday(getdate("2026-03-10")))

    def test_is_bank_holiday_is_year_relative(self):
        # The impl builds the holiday strings from date.year, so any year's
        # Jan 1 must be a holiday.
        self.assertTrue(sched.is_bank_holiday(getdate("2030-01-01")))
        self.assertTrue(sched.is_bank_holiday(getdate("2024-12-25")))

    # --- should_skip_batch_creation -----------------------------------------

    def test_weekday_number_normalizes_string_names(self):
        # Regression for the str-vs-int crash: get_weekday() returns names here,
        # so _weekday_number must map them to 0..6 (weekend = 5/6).
        self.assertEqual(sched._weekday_number(getdate("2026-03-07")), 5)  # Saturday
        self.assertEqual(sched._weekday_number(getdate("2026-03-08")), 6)  # Sunday
        self.assertEqual(sched._weekday_number(getdate("2026-03-09")), 0)  # Monday

    def test_should_skip_returns_bool(self):
        # Smoke the real entrypoint against today() - must always return a bool.
        self.assertIsInstance(sched.should_skip_batch_creation(), bool)

    # --- get_next_business_day ----------------------------------------------

    def test_get_next_business_day_never_weekend(self):
        result = sched.get_next_business_day()
        self.assertLess(sched._weekday_number(result), 5, "next business day must be a weekday")
        self.assertGreater(getdate(result), getdate(), "must be in the future")

    # --- get_next_batch_creation_date ---------------------------------------

    def test_next_creation_date_is_weekday_and_not_holiday(self):
        # Configured for several days so a valid one is almost always findable
        # this month or next.
        next_date = sched.get_next_batch_creation_date([1, 5, 10, 15, 20, 25])
        next_date = getdate(next_date)
        # The function only returns weekday non-holiday dates (its fallback to
        # the 1st of next month is the only exception, and only when nothing
        # else qualifies). With 6 spread-out days at least one qualifies.
        self.assertLess(sched._weekday_number(next_date), 5)
        self.assertFalse(sched.is_bank_holiday(next_date))

    def test_next_creation_date_rolls_into_next_month_when_no_days_left(self):
        # Configure only day 1; unless today IS before day 1 (impossible), the
        # result must be in a later month (current day is always >= 1).
        next_date = getdate(sched.get_next_batch_creation_date([1]))
        today = getdate()
        self.assertGreater(next_date, today)

    # --- validate_batch_creation_days ---------------------------------------

    def test_validate_days_accepts_single_day(self):
        result = sched.validate_batch_creation_days("15")
        self.assertTrue(result["valid"])
        self.assertEqual(result["parsed_days"], [15])

    def test_validate_days_sorts_and_dedupes(self):
        result = sched.validate_batch_creation_days("20,1,1,10")
        self.assertTrue(result["valid"])
        self.assertEqual(result["parsed_days"], [1, 10, 20])

    def test_validate_days_rejects_out_of_range(self):
        result = sched.validate_batch_creation_days("1,32")
        self.assertFalse(result["valid"])
        self.assertIn("32", result["error"])

    def test_validate_days_rejects_non_numeric(self):
        result = sched.validate_batch_creation_days("abc,1")
        self.assertFalse(result["valid"])

    def test_validate_days_rejects_empty(self):
        result = sched.validate_batch_creation_days("")
        self.assertFalse(result["valid"])
        self.assertEqual(result["parsed_days"], [])

    def test_validate_days_warns_on_end_of_month_days(self):
        result = sched.validate_batch_creation_days("29,30,31")
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["warnings"]), 3)

    # --- get_scheduler_config -----------------------------------------------

    def test_scheduler_config_applies_conservative_caps(self):
        config = sched.get_scheduler_config()
        # The scheduler clamps these regardless of stored config.
        self.assertLessEqual(config["max_amount_per_batch"], 3000)
        self.assertLessEqual(config["max_invoices_per_batch"], 15)
        self.assertEqual(config["preferred_batch_size"], 10)


class TestDDBatchSchedulerCreationDay(EnhancedTestCase):
    """is_batch_creation_day reads the live Payments Settings - drive it via the doc."""

    def _set_creation_days(self, value):
        settings = frappe.get_single("Verenigingen Payments Settings")
        settings.batch_creation_days = value
        settings.flags.ignore_validate = True
        settings.save()
        frappe.db.commit()
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def test_is_batch_creation_day_matches_today(self):
        today_day = getdate().day
        self._set_creation_days(str(today_day))
        self.assertTrue(sched.is_batch_creation_day())

    def test_is_batch_creation_day_false_for_other_day(self):
        today_day = getdate().day
        other_day = today_day + 1 if today_day < 28 else 1
        # Ensure other_day != today_day
        if other_day == today_day:
            other_day = 2
        self._set_creation_days(str(other_day))
        self.assertFalse(sched.is_batch_creation_day())

    def test_is_batch_creation_day_with_multiple_days(self):
        today_day = getdate().day
        self._set_creation_days(f"{today_day},28")
        self.assertTrue(sched.is_batch_creation_day())


class TestDDBatchSchedulerEndpoints(EnhancedTestCase):
    """Whitelisted entrypoints, run as a privileged user so the decorators pass."""

    def setUp(self):
        super().setUp()
        # The endpoints require SEPA admin / system manager roles via
        # @require_sepa_permission and @critical/@standard_api. Administrator
        # carries System Manager in the test bootstrap.
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_get_batch_creation_schedule_shape(self):
        result = sched.get_batch_creation_schedule()
        # Real return shape consumed by the admin page.
        for key in ("enabled", "schedule", "configured_days", "next_run", "config", "last_run"):
            self.assertIn(key, result)
        self.assertIsInstance(result["configured_days"], list)
        self.assertTrue(result["configured_days"])  # always at least [1]

    def test_validate_batch_creation_days_endpoint(self):
        # Same logic as the unit tests but exercised through the decorated entry.
        result = sched.validate_batch_creation_days("1,15")
        self.assertTrue(result["valid"])
        self.assertEqual(result["parsed_days"], [1, 15])

    def test_toggle_auto_batch_creation_persists(self):
        # Capture original so we leave settings as we found them.
        original = bool(
            getattr(
                frappe.get_single("Verenigingen Payments Settings"),
                "enable_auto_batch_creation",
                False,
            )
        )
        try:
            on = sched.toggle_auto_batch_creation(True)
            self.assertTrue(on["success"])
            self.assertTrue(on["enabled"])
            frappe.clear_document_cache(
                "Verenigingen Payments Settings", "Verenigingen Payments Settings"
            )
            self.assertTrue(
                bool(frappe.db.get_single_value("Verenigingen Payments Settings", "enable_auto_batch_creation"))
            )

            off = sched.toggle_auto_batch_creation(False)
            self.assertTrue(off["success"])
            self.assertFalse(off["enabled"])
        finally:
            settings = frappe.get_single("Verenigingen Payments Settings")
            settings.enable_auto_batch_creation = original
            settings.flags.ignore_validate = True
            settings.save()
            frappe.db.commit()

    def test_toggle_auto_batch_creation_coerces_unknown_string_to_false(self):
        # cbool() coerces an unrecognized string to 0 (False) rather than raising,
        # so the endpoint disables auto-creation. Restore afterwards.
        original = bool(
            getattr(
                frappe.get_single("Verenigingen Payments Settings"),
                "enable_auto_batch_creation",
                False,
            )
        )
        try:
            result = sched.toggle_auto_batch_creation("not-a-boolean")
            self.assertTrue(result["success"])
            self.assertFalse(result["enabled"])
        finally:
            settings = frappe.get_single("Verenigingen Payments Settings")
            settings.enable_auto_batch_creation = original
            settings.flags.ignore_validate = True
            settings.save()
            frappe.db.commit()

    def test_test_batch_scheduler_config_runs_self_tests(self):
        # This endpoint runs validate_batch_creation_days across a built-in
        # matrix and reports pass/fail - all built-in cases must pass.
        result = sched.test_batch_scheduler_config()
        self.assertTrue(result["success"])
        self.assertTrue(result["validation_tests"])
        for case in result["validation_tests"]:
            self.assertTrue(case["passed"], f"built-in case failed: {case}")
        self.assertIn("schedule_info", result)
        self.assertIn("today_check", result)
