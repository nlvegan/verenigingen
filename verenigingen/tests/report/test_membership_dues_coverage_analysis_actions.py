"""Real-integration tests for the whitelisted ACTIONS of the *Membership Dues
Coverage Analysis* report
(``verenigingen/verenigingen/report/membership_dues_coverage_analysis/``).

The report's pure helpers and ``execute`` path are covered by
``test_membership_dues_coverage_analysis.py`` and ``..._gapfill.py``. This file
covers the whitelisted actions ``generate_catchup_invoices`` (the report's
"generate the invoices needed to fill a member's coverage gaps" button) and
``export_gap_analysis`` (the xlsx export) -- which those files never exercise.

Scope notes (verified against the production code, 2026-07-16):
  * ``generate_catchup_invoices`` is ``@high_security_api(FINANCIAL)``; called
    in-process as Administrator it runs the wrapped body and returns its raw
    ``{"message", "generated_invoices", "errors"}`` dict (no envelope wrapping).
  * Its inline ``has_permission("Sales Invoice", "create")`` throw is shadowed
    by the decorator (a non-privileged caller is denied earlier), so that branch
    is NOT mutation-isolable and is out of scope.
  * Its ``"No active dues schedule"`` error branch is UNREACHABLE: with no active
    schedule ``calculate_catchup_requirements`` returns ``required=False``, so the
    loop ``continue``s before the schedule check. Logged in backlog-dead-code.md.
  * ``export_gap_analysis`` builds an xlsx from list-of-lists rows and persists it
    as a private File, returning ``{"file_url", "message"}``. (It previously called
    ``make_xlsx(..., file_name=...)`` -- an invalid kwarg -- and always raised
    TypeError; fixed 2026-07-16.)
  * ``debug_coverage_fields`` is a dev-only diagnostic, left uncovered (low value).
"""

import io
import zipfile

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)


class TestMembershipDuesCoverageReportActions(VereningingenTestCase):
    # A ~12-month book year is required by the catch-up / book-year split math
    # (test_site_1 ships a ~90-day config that split_gap_by_book_year rejects).
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

    # --------------------------------------------------------------- input guards

    def test_invalid_json_string_raises(self):
        # A malformed JSON string hits the json.loads except-branch -> throw.
        with self.assertRaises(frappe.ValidationError):
            report.generate_catchup_invoices("{not valid json")

    def test_valid_json_but_not_a_list_raises(self):
        # Parses to a dict, not a list -> the isinstance(list) guard throws.
        with self.assertRaises(frappe.ValidationError):
            report.generate_catchup_invoices('{"member": "X"}')

    def test_empty_list_generates_nothing(self):
        result = report.generate_catchup_invoices([])
        self.assertEqual(result["message"], "Generated 0 catch-up invoices")
        self.assertEqual(result["generated_invoices"], [])
        self.assertEqual(result["errors"], [])

    # ------------------------------------------------------------ business branches

    def test_member_with_full_coverage_is_skipped(self):
        # No gap -> catchup not required -> the loop `continue`s, nothing created.
        member = self._gap_member(covered_days=None)  # fully covered
        result = report.generate_catchup_invoices([{"member": member.name}], add_days(today(), -120), today())
        self.assertEqual(result["message"], "Generated 0 catch-up invoices")
        self.assertEqual(result["generated_invoices"], [])
        self.assertEqual(result["errors"], [])

    def test_member_with_gap_generates_catchup_invoice(self):
        member = self._gap_member(covered_days=30)  # 30d covered, rest is gap
        before = self._member_invoice_count(member)

        result = report.generate_catchup_invoices([{"member": member.name}], add_days(today(), -120), today())

        self.assertGreaterEqual(
            len(result["generated_invoices"]),
            1,
            f"expected >=1 catch-up invoice, got {result}",
        )
        self.assertIn("Generated", result["message"])
        # Each reported invoice is a real, persisted Sales Invoice for this member.
        for gen in result["generated_invoices"]:
            self.assertEqual(gen["member"], member.name)
            self.assertTrue(frappe.db.exists("Sales Invoice", gen["invoice"]))
        self.assertGreater(
            self._member_invoice_count(member),
            before,
            "a new Sales Invoice should have been persisted",
        )

    def test_second_run_is_idempotent_for_same_period(self):
        # Generating again for the same window must skip the already-created
        # coverage invoices (the existing-invoice guard), producing 0 new ones.
        member = self._gap_member(covered_days=30)
        first = report.generate_catchup_invoices([{"member": member.name}], add_days(today(), -120), today())
        self.assertGreaterEqual(len(first["generated_invoices"]), 1)

        second = report.generate_catchup_invoices([{"member": member.name}], add_days(today(), -120), today())
        self.assertEqual(
            second["generated_invoices"],
            [],
            "the second run must skip existing coverage invoices",
        )

    # ------------------------------------------------------------ export_gap_analysis

    def test_export_produces_private_xlsx_including_gap_member(self):
        member = self._gap_member(covered_days=30)  # has a gap -> appears in export

        result = report.export_gap_analysis({"from_date": add_days(today(), -120), "to_date": today()})

        self.assertTrue(result["file_url"].endswith(".xlsx"))
        self.assertIn("exported", result["message"])

        file_doc = frappe.get_doc("File", {"file_url": result["file_url"]})
        self.track_doc("File", file_doc.name)
        self.assertEqual(file_doc.is_private, 1, "financial export must be private")

        content = file_doc.get_content()
        self.assertEqual(content[:2], b"PK", "must be a real (zip-based) xlsx")
        # The member's name must appear in the worksheet XML -- proves the gap
        # member's row was actually written (not just an empty file). make_xlsx
        # runs xlsxwriter in constant_memory mode, which writes strings inline in
        # the sheet rather than a shared-strings table.
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn(member.name, sheet_xml)

    def test_export_with_no_matching_gaps_still_returns_valid_file(self):
        # Restrict the report to a fully-covered member -> no gap rows are written,
        # but the export must still produce a valid (header-only) xlsx, not crash.
        member = self._gap_member(covered_days=None)  # fully covered

        result = report.export_gap_analysis(
            {"member": member.name, "from_date": add_days(today(), -120), "to_date": today()}
        )

        self.assertTrue(result["file_url"].endswith(".xlsx"))
        file_doc = frappe.get_doc("File", {"file_url": result["file_url"]})
        self.track_doc("File", file_doc.name)
        self.assertEqual(file_doc.get_content()[:2], b"PK")

    # --------------------------------------------------------------------- helpers

    def _gap_member(self, covered_days):
        """A member with a submitted active membership + auto dues schedule.

        ``covered_days=None`` covers the whole window (no gap). An integer covers
        only the first N days of a 90-day membership, leaving the remainder as a
        coverage gap that catch-up must fill.
        """
        member = self.create_test_member(
            first_name="Catchup",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"catchup.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        membership_type = self.create_test_membership_type()
        start = add_days(today(), -90)
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.start_date = start
        membership.submit()  # on_submit auto-creates the Active dues schedule

        if covered_days is None:
            self._coverage_invoice(member, start, today())
        else:
            self._coverage_invoice(member, start, add_days(start, covered_days - 1))
        return member

    def _coverage_invoice(self, member, coverage_start, coverage_end):
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_coverage_start_date=coverage_start,
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        return invoice

    @staticmethod
    def _member_invoice_count(member):
        return frappe.db.count("Sales Invoice", {"customer": member.customer, "docstatus": 1})
