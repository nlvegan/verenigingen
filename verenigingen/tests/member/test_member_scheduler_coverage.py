"""
Additional real-DB coverage for the member scheduler
(``verenigingen/verenigingen/doctype/member/scheduler.py``).

The base suite (``test_member_scheduler.py``) covers the batch/specific/status/
duration helpers and the *skip* path of ``refresh_all_member_financial_histories``.
This file exercises:

- the *run* path of ``refresh_all_member_financial_histories`` (forced run when
  the last run was > 24h ago, which fires regardless of the hour-of-day window),
  including the last-run timestamp update.
- ``get_member_history_refresh_status`` / ``test_member_history_refresh`` /
  ``get_duration_update_stats`` returning structured results.

Members are created via the factory (with real Customer records) and run as
Administrator. No business logic is mocked.
"""

from datetime import datetime

import frappe
import pytz
from frappe.utils import add_to_date, get_datetime, get_system_timezone, now_datetime
from freezegun import freeze_time

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.member import scheduler


class TestMemberSchedulerCoverage(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="SchedCov",
            last_name="Member",
            email=f"schedcov.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertTrue(
            frappe.get_doc("Member", self.member.name).customer,
            "factory member should have a customer",
        )
        self._orig_last_run = frappe.db.get_single_value(
            "Verenigingen Settings", "last_member_history_refresh"
        )

    def tearDown(self):
        frappe.db.set_single_value(
            "Verenigingen Settings", "last_member_history_refresh", self._orig_last_run
        )
        super().tearDown()

    def test_refresh_all_forced_run_when_over_24h(self):
        # A last-run > 24h ago forces the run branch regardless of hour-of-day.
        # This exercises the synchronous processing path (<=100 members) and the
        # last-run timestamp update.
        #
        # The production code only *labels* this a "Forced run" when the current
        # hour falls OUTSIDE the scheduled windows (06-10 / 18-22); inside those
        # windows the same >24h-old run is labelled "Scheduled run" (see
        # scheduler.refresh_all_member_financial_histories). Freeze the clock to a
        # fixed off-window local hour so this test deterministically exercises the
        # forced-run branch instead of depending on the wall-clock hour at run time.
        tz = pytz.timezone(get_system_timezone())
        frozen = tz.localize(datetime(2026, 6, 15, 14, 30, 0))  # 14:30 local: off-window
        with freeze_time(frozen):
            frappe.db.set_single_value(
                "Verenigingen Settings",
                "last_member_history_refresh",
                add_to_date(now_datetime(), hours=-30),
            )
            before = now_datetime()
            result = scheduler.refresh_all_member_financial_histories()
            self.assertTrue(result["success"])
            self.assertNotIn("skipped", result)  # it ran, did not skip
            self.assertIn("run_reason", result)
            self.assertIn("Forced run", result["run_reason"])
            # The last-run timestamp was advanced to ~now.
            new_last_run = get_datetime(
                frappe.db.get_single_value("Verenigingen Settings", "last_member_history_refresh")
            )
            self.assertGreaterEqual(new_last_run, before.replace(microsecond=0))

    def test_refresh_all_runs_when_last_run_cleared(self):
        # Clearing the last-run value drives the run branch (either the "First run"
        # path when truly empty, or the forced-run path when an empty string parses
        # to a far-past datetime). Either way it must process, not skip.
        frappe.db.set_single_value("Verenigingen Settings", "last_member_history_refresh", None)
        result = scheduler.refresh_all_member_financial_histories()
        self.assertTrue(result["success"])
        self.assertNotIn("skipped", result)
        self.assertIn("run_reason", result)

    def test_status_and_stats_structured(self):
        status = scheduler.get_member_history_refresh_status()
        self.assertNotIn("error", status)
        self.assertGreaterEqual(status["total_members_with_customers"], 1)

        stats = scheduler.get_duration_update_stats()
        self.assertNotIn("error", stats)
        self.assertIn("coverage_percentage", stats)
