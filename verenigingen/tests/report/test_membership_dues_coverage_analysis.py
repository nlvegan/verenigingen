"""
Real-integration tests for the *Membership Dues Coverage Analysis* script
report (``verenigingen/verenigingen/report/membership_dues_coverage_analysis/``).

This report was at 0% coverage (never executed under test). The report is
LIVE: it is registered as a standard Script Report with ref_doctype Member
and is linked from the Verenigingen workspace.

These tests:
  * call ``execute(filters)`` with seeded Members, Memberships, Dues
    Schedules and coverage-bearing Sales Invoices;
  * exercise filter validation (date range, member/chapter existence,
    billing frequency, gap severity);
  * exercise the pure helper functions (gap classification, book-year
    splitting, billing-period calculation, display formatting) directly.

No business logic is mocked. Tests run as Administrator.
"""

import datetime

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)


class TestMembershipDuesCoverageAnalysisReport(VereningingenTestCase):
    """The catch-up / book-year calculations require a ~12-month book year.

    ``split_gap_by_book_year`` rejects book-year configurations whose period is
    not roughly a year (test_site_1 ships a Jan 1 - Mar 31 / ~90-day config,
    which is intentionally rejected). We force a calendar book year for the
    duration of each test and restore the original afterwards.
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

    # ----------------------------------------------------------- execute / columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertIn("member", fieldnames)
        self.assertIn("coverage_percentage", fieldnames)
        self.assertIn("catchup_required", fieldnames)
        self.assertEqual(len(columns), 18)

    def test_execute_empty_filters_returns_columns_and_data(self):
        columns, data = report.execute({})
        self.assertEqual(len(columns), 18)
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        columns, data = report.execute(None)
        self.assertEqual(len(columns), 18)

    # ----------------------------------------------------------- seeded member

    def _active_member_with_membership(self, start_date=None):
        member = self.create_test_member(
            first_name="Coverage",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"coverage.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        if start_date:
            membership.start_date = start_date
        membership.submit()
        return member, membership, membership_type

    def _coverage_invoice(self, member, coverage_start, coverage_end, paid=True):
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_coverage_start_date=coverage_start,
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        if paid:
            # Mark fully paid so payment_status resolves to "Paid"
            frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)
        return invoice

    def test_execute_includes_active_member_with_full_coverage(self):
        start = add_days(today(), -60)
        member, membership, _ = self._active_member_with_membership(start_date=start)
        # One invoice covering the whole membership window -> no gaps.
        self._coverage_invoice(member, start, today(), paid=True)

        columns, data = report.execute({"from_date": add_days(today(), -90), "to_date": today()})
        row = next((r for r in data if r["member"] == member.name), None)
        self.assertIsNotNone(row, "active member with a membership must appear")
        self.assertGreater(row["total_active_days"], 0)
        self.assertGreater(row["covered_days"], 0)
        self.assertGreaterEqual(row["coverage_percentage"], 90)
        self.assertEqual(row["current_gaps"], "No gaps")

    def test_execute_member_with_coverage_gap(self):
        start = add_days(today(), -90)
        member, membership, _ = self._active_member_with_membership(start_date=start)
        # Invoice covers only the first 30 days -> the rest is a gap.
        self._coverage_invoice(member, start, add_days(start, 29), paid=True)

        columns, data = report.execute({"from_date": add_days(today(), -120), "to_date": today()})
        row = next((r for r in data if r["member"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertGreater(row["gap_days"], 0)
        self.assertNotEqual(row["current_gaps"], "No gaps")

    def test_member_filter_restricts_to_member(self):
        member, membership, _ = self._active_member_with_membership(start_date=add_days(today(), -30))
        columns, data = report.execute({"member": member.name})
        self.assertTrue(all(r["member"] == member.name for r in data))

    def test_show_only_gaps_filter(self):
        start = add_days(today(), -90)
        member, membership, _ = self._active_member_with_membership(start_date=start)
        self._coverage_invoice(member, start, add_days(start, 20), paid=True)

        columns, data = report.execute(
            {"from_date": add_days(today(), -120), "to_date": today(), "show_only_gaps": 1}
        )
        # Every returned row must have a gap.
        self.assertTrue(all(r["gap_days"] > 0 for r in data))
        self.assertTrue(any(r["member"] == member.name for r in data))

    # ----------------------------------------------------------- validate_filters

    def test_validate_filters_rejects_reversed_dates(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({"from_date": today(), "to_date": add_days(today(), -10)})

    def test_validate_filters_rejects_nonexistent_member(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({"member": "NONEXISTENT-MEMBER-ZZZ"})

    def test_validate_filters_rejects_nonexistent_chapter(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({"chapter": "NONEXISTENT-CHAPTER-ZZZ"})

    def test_validate_filters_rejects_bad_billing_frequency(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({"billing_frequency": "Hourly"})

    def test_validate_filters_rejects_bad_gap_severity(self):
        with self.assertRaises(frappe.ValidationError):
            report.execute({"gap_severity": "Catastrophic"})

    # ----------------------------------------------------------- get_filters

    def test_get_filters_definition(self):
        filters = report.get_filters()
        fieldnames = [f["fieldname"] for f in filters]
        self.assertIn("chapter", fieldnames)
        self.assertIn("from_date", fieldnames)
        self.assertIn("show_only_gaps", fieldnames)

    # ----------------------------------------------------------- pure helpers

    def test_classify_gap_type_thresholds(self):
        self.assertEqual(report.classify_gap_type(5), "Minor")
        self.assertEqual(report.classify_gap_type(20), "Moderate")
        self.assertEqual(report.classify_gap_type(60), "Significant")
        self.assertEqual(report.classify_gap_type(200), "Critical")

    def test_classify_gap_with_billing_context_daily(self):
        self.assertEqual(report.classify_gap_with_billing_context(20, "Daily", "Minor"), "Critical")
        self.assertEqual(report.classify_gap_with_billing_context(8, "Daily", "Minor"), "Significant")
        self.assertEqual(report.classify_gap_with_billing_context(4, "Daily", "Minor"), "Moderate")
        self.assertEqual(report.classify_gap_with_billing_context(1, "Daily", "Minor"), "Minor")

    def test_classify_gap_with_billing_context_monthly(self):
        self.assertEqual(report.classify_gap_with_billing_context(70, "Monthly", "Minor"), "Critical")
        self.assertEqual(report.classify_gap_with_billing_context(40, "Monthly", "Minor"), "Significant")
        self.assertEqual(report.classify_gap_with_billing_context(20, "Monthly", "Minor"), "Moderate")

    def test_classify_gap_with_billing_context_no_frequency_returns_base(self):
        self.assertEqual(report.classify_gap_with_billing_context(50, None, "Moderate"), "Moderate")

    def test_get_gap_reason_variants(self):
        self.assertIn("unknown", report.get_gap_reason(today(), today(), None))
        self.assertIn("daily", report.get_gap_reason(today(), add_days(today(), 5), "Daily"))
        self.assertIn("monthly", report.get_gap_reason(today(), add_days(today(), 40), "Monthly"))
        self.assertIn("quarterly", report.get_gap_reason(today(), add_days(today(), 100), "Quarterly"))
        self.assertIn("annual", report.get_gap_reason(today(), add_days(today(), 400), "Annual"))

    def test_format_gaps_for_display(self):
        self.assertEqual(report.format_gaps_for_display([]), "No gaps")
        gaps = [
            {
                "gap_start": getdate("2025-01-01"),
                "gap_end": getdate("2025-01-31"),
                "gap_days": 31,
                "gap_type": "Moderate",
                "gap_reason": "Partial month gap in monthly billing",
            }
        ]
        text = report.format_gaps_for_display(gaps)
        self.assertIn("2025-01-01", text)
        self.assertIn("Moderate", text)

    def test_format_catchup_periods_for_display(self):
        self.assertEqual(report.format_catchup_periods_for_display([]), "None required")
        periods = [{"start": getdate("2025-02-01"), "end": getdate("2025-02-28"), "amount": 15.0}]
        text = report.format_catchup_periods_for_display(periods)
        self.assertIn("2025-02-01", text)
        self.assertIn("15.0", text)

    def test_get_empty_coverage_analysis_shape(self):
        empty = report.get_empty_coverage_analysis()
        self.assertEqual(empty["stats"]["total_active_days"], 0)
        self.assertFalse(empty["catchup"]["required"])

    def test_build_period_coverage_map_clips_and_dedupes(self):
        invoices = [
            {
                "invoice": "INV-A",
                "coverage_start": getdate("2025-01-01"),
                "coverage_end": getdate("2025-01-31"),
                "payment_status": "Paid",
                "grand_total": 15.0,
                "outstanding_amount": 0,
                "posting_date": getdate("2025-01-01"),
            },
            # Overlapping invoice -> should be removed by dedup
            {
                "invoice": "INV-B",
                "coverage_start": getdate("2025-01-15"),
                "coverage_end": getdate("2025-02-15"),
                "payment_status": "Paid",
                "grand_total": 15.0,
                "outstanding_amount": 0,
                "posting_date": getdate("2025-01-15"),
            },
        ]
        coverage = report.build_period_coverage_map(
            invoices, getdate("2025-01-01"), getdate("2025-03-01")
        )
        # First invoice kept; second overlaps so it is dropped.
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0]["invoice"], "INV-A")

    def test_identify_coverage_gaps_full_gap_when_no_coverage(self):
        gaps = report.identify_coverage_gaps([], getdate("2025-01-01"), getdate("2025-01-31"))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gap_days"], 31)

    # ----------------------------------------------------------- book-year helpers

    def test_get_book_year_for_date_calendar(self):
        # Calendar book year (Jan 1 start) -> book year == calendar year.
        self.assertEqual(report.get_book_year_for_date(getdate("2025-06-15"), 1, 1), 2025)

    def test_get_book_year_for_date_non_calendar(self):
        # April-start book year: a date in Feb belongs to the previous book year.
        self.assertEqual(report.get_book_year_for_date(getdate("2025-02-15"), 4, 1), 2024)
        self.assertEqual(report.get_book_year_for_date(getdate("2025-05-15"), 4, 1), 2025)

    def test_get_book_year_end_date_calendar(self):
        end = report.get_book_year_end_date(2025, 12, 31)
        self.assertEqual(end, datetime.date(2025, 12, 31))

    def test_split_gap_by_book_year_single_year(self):
        segments = report.split_gap_by_book_year(getdate("2025-03-01"), getdate("2025-09-01"))
        self.assertEqual(len(segments), 1)
        seg_start, seg_end, book_year = segments[0]
        self.assertEqual(seg_start, getdate("2025-03-01"))
        self.assertEqual(seg_end, getdate("2025-09-01"))
        self.assertEqual(book_year, 2025)

    def test_split_gap_by_book_year_crosses_boundary(self):
        # Gap spanning Dec 2024 -> Feb 2025 splits at the calendar book-year boundary.
        segments = report.split_gap_by_book_year(getdate("2024-12-01"), getdate("2025-02-01"))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0][2], 2024)
        self.assertEqual(segments[1][2], 2025)

    def test_calculate_billing_periods_monthly(self):
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-01-01"), getdate("2025-03-15"), "Monthly", 15.0
        )
        # Jan, Feb, partial Mar -> 3 periods, all within calendar book year 2025.
        self.assertEqual(len(periods), 3)
        for p in periods:
            self.assertEqual(p["amount"], 15.0)
            self.assertEqual(p["billing_frequency"], "Monthly")

    def test_calculate_billing_periods_annual(self):
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-01-01"), getdate("2025-12-31"), "Annual", 100.0
        )
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["amount"], 100.0)

    def test_calculate_billing_periods_quarterly(self):
        periods = report.calculate_billing_periods_for_gap(
            getdate("2025-01-01"), getdate("2025-06-30"), "Quarterly", 45.0
        )
        # Q1 + Q2 within the calendar book year.
        self.assertEqual(len(periods), 2)

    # ----------------------------------------------------------- calculate_coverage_timeline

    def test_calculate_coverage_timeline_nonexistent_member_returns_empty(self):
        analysis = report.calculate_coverage_timeline("NONEXISTENT-MEMBER-ZZZ")
        self.assertEqual(analysis["stats"]["total_active_days"], 0)

    def test_calculate_coverage_timeline_for_seeded_member(self):
        start = add_days(today(), -45)
        member, membership, _ = self._active_member_with_membership(start_date=start)
        self._coverage_invoice(member, start, today(), paid=True)

        analysis = report.calculate_coverage_timeline(
            member.name, add_days(today(), -60), today()
        )
        self.assertGreater(analysis["stats"]["total_active_days"], 0)
        self.assertIn("catchup", analysis)
