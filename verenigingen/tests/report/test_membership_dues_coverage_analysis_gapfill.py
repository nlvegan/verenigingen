"""
Gap-fill real-integration tests for the *Membership Dues Coverage Analysis*
script report
(``verenigingen/verenigingen/report/membership_dues_coverage_analysis/``).

The base coverage is provided by ``test_membership_dues_coverage_analysis.py``
(columns, execute, validate_filters, gap classification, book-year splitting,
billing-period calculation, display formatting, the pure helpers). This file
adds tests for the branches that file does NOT cover:

  * ``should_include_row`` gap-severity and show-only-catchup-required filters;
  * ``get_member_invoices_with_coverage`` Overdue / Outstanding payment-status
    branches and the unpaid/outstanding stat accumulation;
  * ``get_expected_billing_frequency`` (real membership type lookup);
  * ``identify_billing_pattern_issues`` (Daily-billing adjustment detection);
  * ``calculate_catchup_requirements`` (no-schedule and with-gaps paths);
  * ``calculate_billing_periods_for_gap`` Daily / Custom single-period paths;
  * the ``get_book_year_*`` helpers including the non-calendar end-year branch;
  * ``get_gap_reason`` quarterly / annual / final-gap / custom branches;
  * ``build_member_row`` and the ``get_coverage_timeline_data`` whitelisted
    visualization endpoint.

No business logic is mocked. Tests run as Administrator.
"""

import datetime

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)


class TestMembershipDuesCoverageAnalysisGapFill(VereningingenTestCase):
    """Force a calendar book year (Jan 1 - Dec 31) for the duration of each test.

    ``split_gap_by_book_year`` rejects non-~12-month book-year configurations,
    so the catch-up / billing-period helpers require a calendar book year.
    """

    BOOK_YEAR_FIELDS = (
        ("book_year_start_month", 1),
        ("book_year_start_day", 1),
        ("book_year_end_month", 12),
        ("book_year_end_day", 31),
    )

    def setUp(self):
        super().setUp()
        self._orig_book_year = {
            field: frappe.db.get_single_value("Verenigingen Settings", field)
            for field, _ in self.BOOK_YEAR_FIELDS
        }
        for field, value in self.BOOK_YEAR_FIELDS:
            frappe.db.set_single_value("Verenigingen Settings", field, value)

    def tearDown(self):
        for field, orig in self._orig_book_year.items():
            frappe.db.set_single_value("Verenigingen Settings", field, orig)
        super().tearDown()

    # ------------------------------------------------------------- helpers

    def _active_member_with_membership(self, start_date=None, billing_period="Monthly"):
        member = self.create_test_member(
            first_name="CovGap",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"covgap.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        # FrappeTestCase rolls back at the DB level but the auto-incrementing
        # member naming-series counter can reuse a name from a previous test in
        # the same module run. A reused Member can therefore carry a stale
        # `Member Fee Change History` row whose `dues_schedule` link points at a
        # schedule that was cleaned up. Submitting the new membership triggers
        # `member.save()` -> `_validate_links()`, which then fails with a
        # LinkValidationError on that orphaned link. Drop any such orphaned rows
        # before they can poison the save. (Test-isolation only; the production
        # save path is unaffected because production never rolls schedules back.)
        self._purge_orphaned_fee_change_history(member)
        membership_type = self.create_test_membership_type(billing_period=billing_period)
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        if start_date:
            membership.start_date = start_date
        membership.submit()
        return member, membership, membership_type

    def _purge_orphaned_fee_change_history(self, member):
        """Delete fee-change-history rows whose dues_schedule link is dangling.

        Keeps the member savable when a reused name carries stale child rows
        from a previously rolled-back test (see caller for the full rationale).
        Rows are deleted directly so we do not re-run the very ``member.save()``
        link validation we are trying to keep clean, and the member is reloaded
        so the in-memory child table no longer carries the orphaned rows.
        """
        purged = False
        for row in member.get("fee_change_history") or []:
            schedule = getattr(row, "dues_schedule", None)
            if schedule and not frappe.db.exists("Membership Dues Schedule", schedule):
                frappe.db.delete("Member Fee Change History", {"name": row.name})
                purged = True
        if purged:
            member.reload()

    def _coverage_invoice(self, member, coverage_start, coverage_end, paid=True, mark_overdue=False):
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_coverage_start_date=coverage_start,
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        if paid:
            frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)
        elif mark_overdue:
            frappe.db.set_value("Sales Invoice", invoice.name, "status", "Overdue")
        return invoice

    # --------------------------------------------- should_include_row filters

    def test_gap_severity_filter_excludes_non_matching(self):
        # Seed a member with a large (Critical/Significant) gap.
        start = add_days(today(), -120)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        self._coverage_invoice(member, start, add_days(start, 10), paid=True)

        with self.assertNoErrorLog():
            columns, data = report.execute(
                {
                    "from_date": add_days(today(), -150),
                    "to_date": today(),
                    "gap_severity": "Minor",
                }
            )
        # Every returned row's gaps text must reference the requested severity.
        for row in data:
            self.assertIn("Minor", row["current_gaps"])

    def test_show_only_catchup_required_filter(self):
        start = add_days(today(), -90)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        # A gap with an active dues schedule -> catch-up required.
        self._coverage_invoice(member, start, add_days(start, 10), paid=True)

        with self.assertNoErrorLog():
            columns, data = report.execute(
                {
                    "from_date": add_days(today(), -120),
                    "to_date": today(),
                    "show_only_catchup_required": 1,
                }
            )
        # Every returned row must require catch-up.
        self.assertTrue(all(r["catchup_required"] for r in data))

    def test_should_include_row_unit_gap_severity(self):
        row_no_gap = {"current_gaps": "No gaps", "gap_days": 0, "catchup_required": 0}
        self.assertFalse(report.should_include_row(row_no_gap, {"gap_severity": "Critical"}))

        row_minor = {
            "current_gaps": "2025-01-01 to 2025-01-05 (5 days, Minor)",
            "gap_days": 5,
            "catchup_required": 0,
        }
        self.assertFalse(report.should_include_row(row_minor, {"gap_severity": "Critical"}))
        self.assertTrue(report.should_include_row(row_minor, {"gap_severity": "Minor"}))

    def test_should_include_row_unit_catchup_and_gaps(self):
        row = {"current_gaps": "No gaps", "gap_days": 0, "catchup_required": 0}
        self.assertFalse(report.should_include_row(row, {"show_only_gaps": 1}))
        self.assertFalse(report.should_include_row(row, {"show_only_catchup_required": 1}))
        self.assertTrue(report.should_include_row(row, {}))

    # --------------------------------------- payment-status / outstanding stats

    def test_unpaid_invoice_records_outstanding_amount(self):
        start = add_days(today(), -40)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        # Unpaid (outstanding > 0) invoice covering the whole window.
        self._coverage_invoice(member, start, today(), paid=False)

        analysis = report.calculate_coverage_timeline(member.name, add_days(today(), -60), today())
        self.assertGreater(analysis["stats"]["unpaid_coverage_days"], 0)
        self.assertGreater(analysis["stats"]["outstanding_amount"], 0)

    def test_overdue_invoice_payment_status(self):
        start = add_days(today(), -40)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        self._coverage_invoice(member, start, today(), paid=False, mark_overdue=True)

        invoices = report.get_member_invoices_with_coverage(
            frappe.db.get_value("Member", member.name, "customer")
        )
        statuses = {inv["payment_status"] for inv in invoices}
        # The CASE expression maps an Overdue, non-zero-outstanding invoice to
        # 'Overdue'.
        self.assertTrue(statuses & {"Overdue", "Outstanding"})

    # ------------------------------------- get_expected_billing_frequency

    def test_get_expected_billing_frequency_returns_membership_type_period(self):
        start = add_days(today(), -60)
        member, _membership, mtype = self._active_member_with_membership(
            start_date=start, billing_period="Monthly"
        )
        freq = report.get_expected_billing_frequency(member.name, start, today())
        self.assertEqual(freq, "Monthly")

    def test_get_expected_billing_frequency_none_for_no_membership(self):
        member = self.create_test_member(
            first_name="NoMb",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"nomb.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        freq = report.get_expected_billing_frequency(member.name, add_days(today(), -30), today())
        self.assertIsNone(freq)

    # -------------------------------- identify_billing_pattern_issues (Daily)

    def test_identify_billing_pattern_issues_daily_adjustment(self):
        # A single low-amount invoice covering > 7 days while expected billing
        # is Daily, with no per-day invoices -> flagged as a billing pattern
        # mismatch. The period dates must fall inside the membership window so
        # that get_expected_billing_frequency resolves to "Daily".
        start = add_days(today(), -60)
        member, _membership, _ = self._active_member_with_membership(
            start_date=start, billing_period="Daily"
        )
        period_start = getdate(start)
        cov_end = add_days(period_start, 19)  # 20-day adjustment invoice
        period_end = add_days(period_start, 30)
        coverage_map = [
            {
                "invoice": "INV-ADJUST",
                "coverage_start": period_start,
                "coverage_end": getdate(cov_end),
                "payment_status": "Paid",
                "amount": 5.0,  # Low amount -> looks like an adjustment.
                "outstanding_amount": 0,
                "posting_date": period_start,
            }
        ]
        issues = report.identify_billing_pattern_issues(
            coverage_map, period_start, getdate(period_end), member.name
        )
        self.assertTrue(issues, "a long low-amount invoice under Daily billing must be flagged")
        self.assertEqual(issues[0]["issue_type"], "billing_pattern_mismatch")

    def test_identify_billing_pattern_issues_returns_empty_for_non_daily(self):
        member, _membership, _ = self._active_member_with_membership(
            start_date=add_days(today(), -60), billing_period="Monthly"
        )
        issues = report.identify_billing_pattern_issues(
            [], getdate("2025-01-01"), getdate("2025-01-31"), member.name
        )
        self.assertEqual(issues, [])

    # ----------------------------------- calculate_catchup_requirements

    def test_calculate_catchup_requirements_no_gaps(self):
        result = report.calculate_catchup_requirements("ANY-MEMBER", [])
        self.assertFalse(result["required"])
        self.assertEqual(result["summary"], "No catch-up required")

    def test_calculate_catchup_requirements_with_active_schedule(self):
        start = add_days(today(), -90)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        # Gap that the active dues schedule should generate catch-up periods for.
        gaps = [
            {
                "gap_start": getdate("2025-01-01"),
                "gap_end": getdate("2025-03-31"),
                "gap_days": 90,
                "gap_type": "Significant",
            }
        ]
        result = report.calculate_catchup_requirements(member.name, gaps)
        self.assertTrue(result["required"])
        self.assertGreater(len(result["periods"]), 0)
        self.assertGreater(result["total_amount"], 0)

    # ------------------------------ calculate_billing_periods_for_gap branches

    def test_calculate_billing_periods_daily_single_period(self):
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-01-01"), getdate("2025-01-15"), "Daily", 1.0
        )
        # Daily -> one period per book-year segment (treated as a single span).
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["billing_frequency"], "Daily")

    def test_calculate_billing_periods_custom_single_period(self):
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-01-01"), getdate("2025-02-15"), "Custom", 50.0
        )
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["amount"], 50.0)

    def test_calculate_billing_periods_quarterly_q4(self):
        # A gap landing in Q4 exercises the quarter==4 year-rollover branch.
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-10-01"), getdate("2025-12-31"), "Quarterly", 45.0
        )
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["billing_frequency"], "Quarterly")

    # ----------------------------------------------- book-year helpers

    def test_get_book_year_boundaries_returns_calendar(self):
        boundaries = report.get_book_year_boundaries()
        self.assertEqual(boundaries, (1, 1, 12, 31))

    def test_get_book_year_end_date_non_calendar(self):
        # April-start book year ending in March -> end is in the NEXT calendar
        # year. We must temporarily configure an April-start book year.
        frappe.db.set_single_value("Verenigingen Settings", "book_year_start_month", 4)
        frappe.db.set_single_value("Verenigingen Settings", "book_year_start_day", 1)
        frappe.db.set_single_value("Verenigingen Settings", "book_year_end_month", 3)
        frappe.db.set_single_value("Verenigingen Settings", "book_year_end_day", 31)
        try:
            end = report.get_book_year_end_date(2024, 3, 31)
            # Book year 2024 (Apr 2024 - Mar 2025) ends 2025-03-31.
            self.assertEqual(end, datetime.date(2025, 3, 31))
        finally:
            # tearDown restores the originals, but reset start month so the
            # boundary lookup inside get_book_year_end_date is consistent.
            frappe.db.set_single_value("Verenigingen Settings", "book_year_start_month", 1)
            frappe.db.set_single_value("Verenigingen Settings", "book_year_end_month", 12)

    def test_get_book_year_end_date_day_overflow_clamped(self):
        # Feb 31 requested -> clamped to the last valid day of February.
        end = report.get_book_year_end_date(2025, 2, 31)
        self.assertEqual(end, datetime.date(2025, 2, 28))

    # ------------------------------------------------- get_gap_reason branches

    def test_get_gap_reason_final_gap_offset(self):
        # is_final_gap=True uses a 0-day offset in the internal day count.
        reason = report.get_gap_reason(
            getdate("2025-01-01"), getdate("2025-01-10"), "Daily", is_final_gap=True
        )
        self.assertIn("daily", reason)

    def test_get_gap_reason_quarterly_partial_and_long(self):
        partial = report.get_gap_reason(today(), add_days(today(), 30), "Quarterly")
        self.assertIn("Partial quarter", partial)
        long_gap = report.get_gap_reason(today(), add_days(today(), 200), "Quarterly")
        self.assertIn("quarter(s)", long_gap)

    def test_get_gap_reason_annual_partial_and_long(self):
        partial = report.get_gap_reason(today(), add_days(today(), 100), "Annual")
        self.assertIn("Partial year", partial)
        long_gap = report.get_gap_reason(today(), add_days(today(), 800), "Annual")
        self.assertIn("year(s)", long_gap)

    def test_get_gap_reason_custom_frequency(self):
        reason = report.get_gap_reason(today(), add_days(today(), 5), "Custom")
        self.assertIn("custom", reason.lower())

    # --------------------------------------------------------- build_member_row

    def test_build_member_row_shape(self):
        member_data = {
            "member": "M-1",
            "member_name": "Test Member",
            "membership_start": getdate("2025-01-01"),
            "membership_status": "Active",
            "billing_frequency": "Monthly",
            "dues_rate": 15.0,
            "last_invoice_date": getdate("2025-01-01"),
            "next_invoice_due": getdate("2025-02-01"),
        }
        analysis = report.get_empty_coverage_analysis()
        row = report.build_member_row(member_data, analysis)
        self.assertEqual(row["member"], "M-1")
        self.assertEqual(row["current_gaps"], "No gaps")
        self.assertEqual(row["catchup_periods"], "None required")
        self.assertEqual(row["catchup_required"], 0)
        self.assertEqual(row["billing_frequency"], "Monthly")

    # ----------------------------------------- whitelisted visualization API

    def test_get_coverage_timeline_data_for_seeded_member(self):
        start = add_days(today(), -60)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        self._coverage_invoice(member, start, add_days(start, 20), paid=True)

        result = report.get_coverage_timeline_data(member.name, add_days(today(), -90), today())
        self.assertIn("timeline_events", result)
        self.assertIn("stats", result)
        self.assertIn("catchup", result)
        # Events are sorted by start date.
        starts = [e["start"] for e in result["timeline_events"]]
        self.assertEqual(starts, sorted(starts))

    # ----------------------------------------------- chapter filter / conditions

    def test_build_conditions_with_chapter_and_billing_frequency(self):
        conditions, params = report.build_conditions(
            {"chapter": "CH-1", "billing_frequency": "Monthly", "member": "M-1"}
        )
        self.assertIn("cm.parent = %s", conditions)
        self.assertIn("mds.billing_frequency = %s", conditions)
        self.assertIn("m.name = %s", conditions)
        self.assertEqual(params, ["M-1", "CH-1", "Monthly"])

    def test_get_membership_periods_clips_to_date_range(self):
        start = add_days(today(), -100)
        member, _membership, _ = self._active_member_with_membership(start_date=start)
        # Restrict the window; the period must be clipped to from_date/to_date.
        periods = report.get_membership_periods(
            member.name, add_days(today(), -30), today()
        )
        self.assertTrue(periods)
        for seg_start, seg_end in periods:
            self.assertGreaterEqual(seg_start, getdate(add_days(today(), -30)))
            self.assertLessEqual(seg_end, getdate(today()))
