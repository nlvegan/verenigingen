"""
Real-integration tests for the *Member End Date Reconstruction* script report
(``verenigingen/verenigingen/report/member_end_date_reconstruction/``).

The report finds members with ``status = 'Quit'`` and no ``member_end_date``
and reconstructs a suggested end date through three ordered strategies:

1. Active SEPA mandate / Mollie subscription -> "Still Active" (no end date).
2. Last submitted Sales Invoice with a coverage end date -> that end date
   (confidence High when paid, Medium when outstanding).
3. Last submitted Payment Entry + the member's dues-schedule billing
   frequency -> the end of the corresponding billing period.

If none apply, the member is reported with "No Data".

These tests seed real Quit members with the various payment-history shapes
and assert on the reconstructed dates, confidences and data-source labels,
plus the pure ``get_member_billing_frequency`` helper and the column
structure. All data is auto-cleaned. The whitelisted ``apply_suggestion`` /
``apply_all_suggestions`` mutators are covered too.
"""

from datetime import date

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.member_end_date_reconstruction import (
    member_end_date_reconstruction as report,
)


class TestMemberEndDateReconstructionReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _quit_member(self, with_customer=True):
        """Create an Active member (so it inserts cleanly), then flip it to
        Quit with a NULL member_end_date directly in the DB so the report's
        ``status = 'Quit' AND member_end_date IS NULL`` query picks it up."""
        member = self.create_test_member(
            chapter=False,
            first_name="Quitter",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"quitter.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=with_customer,
        )
        member.reload()
        frappe.db.set_value(
            "Member",
            member.name,
            {"status": "Quit", "member_end_date": None},
            update_modified=False,
        )
        member.reload()
        return member

    def _member_row(self, member_name):
        """Re-read the member as the report's get_data SQL would expose it."""
        return frappe.db.get_value(
            "Member",
            member_name,
            ["name", "full_name", "member_end_date", "customer", "email"],
            as_dict=True,
        )

    def _row_for(self, data, member_name):
        return next((r for r in data if r["member"] == member_name), None)

    def _dues_schedule(self, member, billing_frequency):
        """Create a real (non-template) Membership Dues Schedule instance for the
        member with the requested billing frequency.

        The Dues Schedule validates that the member has a submitted, Active
        Membership. We create that Membership as a *draft* and promote it to
        ``docstatus = 1`` / ``status = 'Active'`` at the row level rather than
        calling ``membership.submit()``. The submit machinery fires hooks (the
        "Coverage Timeline Calculation" sweep + auto dues-schedule creation)
        that, against veg11's real member population, error-log across unrelated
        members and can roll back to a savepoint that deletes the just-created
        test member -> order-dependent flakes. The validation only inspects the
        Membership DB row, so a row-level promotion satisfies it cleanly, and the
        report reads only ``Membership Dues Schedule.billing_frequency`` by
        member, so a directly-saved schedule row exercises exactly what is under
        test."""
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        # Promote to a submitted, Active membership at the row level (see above).
        frappe.db.set_value(
            "Membership",
            membership.name,
            {"docstatus": 1, "status": "Active"},
            update_modified=False,
        )
        schedule = self.create_test_dues_schedule(
            member=member.name,
            membership_type=membership_type.name,
            billing_frequency=billing_frequency,
        )
        return schedule.name

    # ------------------------------------------------------------- columns / execute

    def test_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(len(columns), 10)
        self.assertIn("suggested_end_date", fieldnames)
        self.assertIn("confidence", fieldnames)
        self.assertIn("data_source", fieldnames)

    def test_execute_returns_columns_and_data(self):
        with self.assertNoErrorLog():
            columns, data = report.execute({})
        self.assertEqual(len(columns), 10)
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------- no-data path

    def test_quit_member_with_no_history_reports_no_data(self):
        member = self._quit_member(with_customer=True)
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row, "Quit member with NULL end date must appear")
        self.assertEqual(row["confidence"], "No Data")
        self.assertIsNone(row["suggested_end_date"])
        self.assertIn("No invoices or payments", row["data_source"])

    def test_quit_member_without_customer_reports_no_data(self):
        member = self._quit_member(with_customer=False)
        # Ensure no customer at all.
        frappe.db.set_value("Member", member.name, "customer", None, update_modified=False)
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], "No Data")

    def test_active_member_excluded(self):
        # A still-Active member must never appear.
        member = self.create_test_member(
            chapter=False,
            first_name="Stay",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"stay.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        with self.assertNoErrorLog():
            _, data = report.execute({})
        self.assertIsNone(self._row_for(data, member.name))

    def test_quit_member_with_end_date_excluded(self):
        member = self._quit_member(with_customer=True)
        frappe.db.set_value("Member", member.name, "member_end_date", today(), update_modified=False)
        with self.assertNoErrorLog():
            _, data = report.execute({})
        self.assertIsNone(
            self._row_for(data, member.name),
            "Quit members that already have an end date are excluded",
        )

    # ------------------------------------------------------------- SEPA / active path

    def test_active_sepa_mandate_marks_still_active(self):
        member = self._quit_member(with_customer=True)
        mandate = self.create_test_sepa_mandate(member=member.name, scenario="normal")
        self.assertEqual(mandate.status, "Active")

        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], "High")
        self.assertIn("Still Active", row["status_indicator"])
        self.assertIn("Active SEPA mandate", row["data_source"])
        self.assertIsNone(row["suggested_end_date"], "active members get no suggested end date")

    def test_mollie_subscription_marks_still_active(self):
        member = self._quit_member(with_customer=True)
        frappe.db.set_value(
            "Customer", member.customer, "custom_mollie_subscription_id", "sub_test123"
        )
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], "High")
        self.assertIn("Mollie subscription", row["data_source"])

    # ------------------------------------------------------------- invoice coverage path

    def test_invoice_coverage_paid_is_high_confidence(self):
        member = self._quit_member(with_customer=True)
        coverage_end = getdate("2024-09-30")
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_coverage_start_date=getdate("2024-09-01"),
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)

        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(getdate(row["suggested_end_date"]), coverage_end)
        self.assertEqual(row["confidence"], "High")
        self.assertIn("Invoice Coverage", row["status_indicator"])
        self.assertIn("Paid", row["details"])

    def test_invoice_coverage_unpaid_is_medium_confidence(self):
        member = self._quit_member(with_customer=True)
        coverage_end = getdate("2024-06-30")
        invoice = self.create_test_sales_invoice(
            member=member.name,
            custom_coverage_start_date=getdate("2024-06-01"),
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        # Leave an outstanding amount -> Medium confidence + "Unpaid" details.
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 25.0)

        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(getdate(row["suggested_end_date"]), coverage_end)
        self.assertEqual(row["confidence"], "Medium")
        self.assertIn("Unpaid", row["details"])

    # ------------------------------------------------------------- payment + frequency path

    def _quit_member_with_payment(self, billing_frequency, posting_date):
        member = self._quit_member(with_customer=True)
        if billing_frequency is not None:
            self._dues_schedule(member, billing_frequency)
        # The base create_test_payment_entry() auto-discovers a Cash account and,
        # when the company has none (true on veg11's real NVV CoA), falls back to
        # parenting a new account under a Receivable *ledger* -> ERPNext rejects
        # ("Parent account ... can not be a ledger"). Supply an explicit cash
        # account created via _ensure_account(), which always picks a real *group*
        # parent of the right root_type, so the draft saves on any CoA. The report
        # reads Payment Entry rows by raw SQL and never touches paid_to anyway.
        company = (
            frappe.defaults.get_user_default("Company")
            or frappe.get_all("Company", limit=1, pluck="name")[0]
        )
        cash_account = self._ensure_account("Test Cash Account", company, "Cash", is_group=0)
        payment = self.create_test_payment_entry(
            member=member.name,
            posting_date=posting_date,
            paid_amount=42.0,
            received_amount=42.0,
            paid_to=cash_account,
        )
        # The report reads Payment Entry rows via raw SQL filtered on
        # ``docstatus = 1`` and never touches the GL. Submitting a real
        # Payment Entry would require company/currency-consistent receivable
        # and cash accounts (the shared `_Test Company` is INR while the cash
        # account is EUR -> GL currency mismatch), which is orthogonal to the
        # report logic under test. Promote the saved draft to submitted at the
        # row level so the report's SELECT sees it without the GL machinery.
        frappe.db.set_value("Payment Entry", payment.name, "docstatus", 1, update_modified=False)
        return member, payment

    def test_payment_monthly_frequency_suggests_month_end(self):
        member, _ = self._quit_member_with_payment("Monthly", getdate("2024-03-10"))
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(getdate(row["suggested_end_date"]), date(2024, 3, 31))
        self.assertEqual(row["confidence"], "Medium")
        self.assertEqual(row["billing_frequency"], "Monthly")
        self.assertIn("Payment-Based", row["status_indicator"])

    def test_payment_quarterly_frequency_suggests_quarter_end(self):
        member, _ = self._quit_member_with_payment("Quarterly", getdate("2024-02-10"))
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(getdate(row["suggested_end_date"]), date(2024, 3, 31))
        self.assertEqual(row["billing_frequency"], "Quarterly")

    def test_payment_annual_frequency_suggests_year_end(self):
        member, _ = self._quit_member_with_payment("Annual", getdate("2024-05-10"))
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(getdate(row["suggested_end_date"]), date(2024, 12, 31))
        self.assertEqual(row["billing_frequency"], "Annual")

    def test_payment_without_billing_frequency_is_low_confidence(self):
        member, _ = self._quit_member_with_payment(None, getdate("2024-05-10"))
        with self.assertNoErrorLog():
            _, data = report.execute({})
        row = self._row_for(data, member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], "Low")
        self.assertIn("no billing frequency", row["details"])
        self.assertIsNone(row["suggested_end_date"])

    # ------------------------------------------------------------- billing frequency helper

    def test_get_member_billing_frequency_none_when_no_schedule(self):
        member = self._quit_member(with_customer=True)
        self.assertIsNone(report.get_member_billing_frequency(member.name))

    def test_get_member_billing_frequency_reads_latest_schedule(self):
        member = self._quit_member(with_customer=True)
        self._dues_schedule(member, "Quarterly")
        self.assertEqual(report.get_member_billing_frequency(member.name), "Quarterly")

    # ------------------------------------------------------------- analyze_member directly

    def test_analyze_member_no_history(self):
        member = self._quit_member(with_customer=False)
        frappe.db.set_value("Member", member.name, "customer", None, update_modified=False)
        result = report.analyze_member(self._member_row(member.name))
        self.assertEqual(result["confidence"], "No Data")
        self.assertEqual(result["member"], member.name)

    # ------------------------------------------------------------- apply_suggestion mutator

    def test_apply_suggestion_sets_end_date(self):
        member = self._quit_member(with_customer=True)
        suggested = "2024-12-31"
        result = report.apply_suggestion(member.name, suggested)
        self.assertTrue(result["success"])
        self.assertEqual(str(frappe.db.get_value("Member", member.name, "member_end_date")), suggested)

    def test_apply_suggestion_rejects_non_quit_member(self):
        member = self.create_test_member(
            chapter=False,
            first_name="Active",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"act.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        with self.assertRaises(frappe.ValidationError):
            report.apply_suggestion(member.name, "2024-12-31")

    def test_apply_suggestion_rejects_member_with_existing_end_date(self):
        member = self._quit_member(with_customer=True)
        frappe.db.set_value("Member", member.name, "member_end_date", "2024-01-01", update_modified=False)
        with self.assertRaises(frappe.ValidationError):
            report.apply_suggestion(member.name, "2024-12-31")

    def test_apply_all_suggestions_applies_high_confidence_only(self):
        # High-confidence member (paid invoice coverage) -> updated.
        high = self._quit_member(with_customer=True)
        coverage_end = getdate("2024-08-31")
        invoice = self.create_test_sales_invoice(
            member=high.name,
            custom_coverage_start_date=getdate("2024-08-01"),
            custom_coverage_end_date=coverage_end,
        )
        invoice.submit()
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)

        # No-data member -> skipped.
        skipped = self._quit_member(with_customer=False)
        frappe.db.set_value("Member", skipped.name, "customer", None, update_modified=False)

        result = report.apply_all_suggestions()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["updated"], 1)
        self.assertEqual(
            getdate(frappe.db.get_value("Member", high.name, "member_end_date")), coverage_end
        )
        self.assertIsNone(frappe.db.get_value("Member", skipped.name, "member_end_date"))
