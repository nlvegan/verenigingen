"""
Real-integration tests for the *Chapter Dues Split* script report
(``verenigingen/verenigingen/report/chapter_dues_split/``).

This report was at 0% coverage. It is a LIVE standard Script Report
(ref_doctype Sales Invoice, linked from the Verenigingen workspace) used for
financial planning: it groups submitted membership Sales Invoices by
``custom_member_chapter``, sums paid/unpaid amounts and computes the
chapter/national allocation split via ``DuesAllocationService``.

Tests seed real Chapters and submitted Sales Invoices (tagged with a chapter)
and exercise the column structure, aggregation, paid/unpaid split, the
allocation columns, the custom-split flag and the date/chapter/company
filters. All seeded data is auto-cleaned.
"""

import frappe
from frappe.utils import add_days, flt, get_first_day, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.chapter_dues_split import chapter_dues_split as report


class TestChapterDuesSplitReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _make_chapter(self, *, split_percentage=None):
        chapter = self.create_test_chapter()
        if split_percentage is not None:
            frappe.db.set_value("Chapter", chapter.name, "chapter_split_percentage", split_percentage)
        return chapter

    # The shared factory creates each test invoice with a single line of
    # qty=1 @ rate=25.0, so every seeded invoice has a grand_total of 25.0.
    INVOICE_AMOUNT = 25.0

    def _chapter_invoice(self, chapter_name, *, paid=True, posting_date=None):
        """Create a submitted Sales Invoice (grand_total 25.0) tagged with a chapter."""
        member = self.create_test_member(
            first_name="Dues",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"dues.{frappe.generate_hash(length=6)}@test.invalid",
            auto_create_customer=True,
        )
        member.reload()
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_member_chapter=chapter_name,
            posting_date=posting_date or today(),
        )
        invoice.submit()
        if not paid:
            # Leave outstanding so it counts as unpaid.
            frappe.db.set_value(
                "Sales Invoice", invoice.name, "outstanding_amount", self.INVOICE_AMOUNT
            )
        else:
            frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)
        return invoice

    def _rows_for(self, data, chapter_name):
        return next((r for r in data if r["chapter"] == chapter_name), None)

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns({})
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 12)
        for expected in (
            "chapter",
            "total_invoices",
            "total_amount",
            "paid_count",
            "paid_amount",
            "unpaid_count",
            "unpaid_amount",
            "chapter_percentage",
            "chapter_amount",
            "national_percentage",
            "national_amount",
            "uses_custom_split",
        ):
            self.assertIn(expected, fieldnames)

    # ------------------------------------------------------------- aggregation

    def test_paid_invoice_aggregated_for_chapter(self):
        chapter = self._make_chapter()
        self._chapter_invoice(chapter.name, paid=True)

        with self.assertNoErrorLog():
            columns, data = report.execute({"chapter": chapter.name})

        self.assertEqual(len(columns), 12)
        row = self._rows_for(data, chapter.name)
        self.assertIsNotNone(row, "chapter with a tagged invoice must appear")
        self.assertEqual(row["total_invoices"], 1)
        self.assertEqual(row["paid_count"], 1)
        self.assertEqual(row["unpaid_count"], 0)
        self.assertEqual(flt(row["paid_amount"]), self.INVOICE_AMOUNT)
        # chapter + national amounts reconcile to the total.
        self.assertAlmostEqual(
            flt(row["chapter_amount"]) + flt(row["national_amount"]),
            flt(row["total_amount"]),
            places=2,
        )

    def test_unpaid_invoice_split(self):
        chapter = self._make_chapter()
        self._chapter_invoice(chapter.name, paid=False)

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter.name})
        row = self._rows_for(data, chapter.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["unpaid_count"], 1)
        self.assertEqual(row["paid_count"], 0)
        self.assertEqual(flt(row["unpaid_amount"]), 25.0)

    def test_mixed_paid_and_unpaid(self):
        chapter = self._make_chapter()
        self._chapter_invoice(chapter.name, paid=True)
        self._chapter_invoice(chapter.name, paid=False)

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter.name})
        row = self._rows_for(data, chapter.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["total_invoices"], 2)
        self.assertEqual(row["paid_count"], 1)
        self.assertEqual(row["unpaid_count"], 1)
        self.assertEqual(flt(row["paid_amount"]), self.INVOICE_AMOUNT)
        self.assertEqual(flt(row["unpaid_amount"]), self.INVOICE_AMOUNT)
        self.assertEqual(flt(row["total_amount"]), 2 * self.INVOICE_AMOUNT)

    # ------------------------------------------------------------- custom split

    def test_custom_split_flag_true(self):
        chapter = self._make_chapter(split_percentage=75.0)
        self._chapter_invoice(chapter.name, paid=True)

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter.name})
        row = self._rows_for(data, chapter.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["uses_custom_split"], 1)
        # 75% of the 25.0 invoice goes to the chapter, 25% to national.
        self.assertAlmostEqual(flt(row["chapter_amount"]), 0.75 * self.INVOICE_AMOUNT, places=2)
        self.assertAlmostEqual(flt(row["national_amount"]), 0.25 * self.INVOICE_AMOUNT, places=2)
        self.assertAlmostEqual(flt(row["chapter_percentage"]), 75.0, places=2)

    def test_custom_split_flag_false_when_zero(self):
        chapter = self._make_chapter(split_percentage=0)
        self._chapter_invoice(chapter.name, paid=True)

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter.name})
        row = self._rows_for(data, chapter.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["uses_custom_split"], 0, "a 0% split is not a custom split")

    # ------------------------------------------------------------- filters

    def test_chapter_filter_restricts(self):
        chapter_a = self._make_chapter()
        chapter_b = self._make_chapter()
        self._chapter_invoice(chapter_a.name)
        self._chapter_invoice(chapter_b.name)

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter_a.name})
        chapters = {r["chapter"] for r in data}
        self.assertIn(chapter_a.name, chapters)
        self.assertNotIn(chapter_b.name, chapters)

    def test_date_filter_excludes_out_of_range(self):
        chapter = self._make_chapter()
        # Invoice well in the past.
        self._chapter_invoice(chapter.name, posting_date=add_days(today(), -400))

        with self.assertNoErrorLog():
            _columns, data = report.execute(
                {
                    "chapter": chapter.name,
                    "from_date": add_days(today(), -10),
                    "to_date": today(),
                }
            )
        self.assertIsNone(
            self._rows_for(data, chapter.name),
            "an invoice outside the date window must not be aggregated",
        )

    def test_default_date_range_is_current_month(self):
        """When no dates are supplied the report defaults to the current month.

        Observable effect: an invoice posted this month is included while one
        posted in a prior month is excluded (the default window is the first..
        last day of the current month).
        """
        # Skip near month boundaries where get_first_day(today()) could fall in
        # the same window as an "older" invoice we post.
        if getdate(today()).day <= 2:
            self.skipTest("skipping default-month assertion at the month boundary")

        chapter = self._make_chapter()
        self._chapter_invoice(chapter.name, posting_date=today())
        older_chapter = self._make_chapter()
        self._chapter_invoice(
            older_chapter.name, posting_date=add_days(get_first_day(today()), -10)
        )

        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        chapters = {r["chapter"] for r in data}
        self.assertIn(chapter.name, chapters, "current-month invoice must be included")
        self.assertNotIn(
            older_chapter.name,
            chapters,
            "an invoice from a prior month is outside the default current-month window",
        )

    def test_company_filter(self):
        chapter = self._make_chapter()
        invoice = self._chapter_invoice(chapter.name)
        company = frappe.db.get_value("Sales Invoice", invoice.name, "company")

        with self.assertNoErrorLog():
            _columns, data = report.execute({"chapter": chapter.name, "company": company})
        self.assertIsNotNone(self._rows_for(data, chapter.name))

        with self.assertNoErrorLog():
            _columns, data2 = report.execute(
                {"chapter": chapter.name, "company": "Nonexistent Company ZZZ"}
            )
        self.assertIsNone(self._rows_for(data2, chapter.name))

    # ------------------------------------------------------------- empty branch

    def test_untagged_invoice_not_included(self):
        """An invoice with no chapter tag must never appear."""
        member = self.create_test_member(
            first_name="NoChap",
            last_name=f"M{frappe.generate_hash(length=4)}",
            email=f"nochap.{frappe.generate_hash(length=6)}@test.invalid",
            auto_create_customer=True,
        )
        member.reload()
        invoice = self.create_test_sales_invoice(member=member.name, rate=30.0, qty=1)
        invoice.submit()

        with self.assertNoErrorLog():
            _columns, data = report.execute({})
        # No row should reference this invoice's (absent) chapter.
        self.assertTrue(all(r["chapter"] for r in data))
