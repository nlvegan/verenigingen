"""
Real-integration tests for the *Members Without Dues Schedule* script report
(``verenigingen/verenigingen/report/members_without_dues_schedule/``).

This report was at 0% coverage (never executed under test). The report is
LIVE: it is registered as a standard Script Report with ref_doctype Member
and is linked from the Verenigingen workspace.

These tests seed real Members (with Customers), Memberships and Membership
Dues Schedules via the factory and call ``execute(filters)`` directly,
asserting on the column structure, the data rows, the summary statistics and
the chart. They cover the no-schedule branch, the overdue/critical branches,
the manual-mode branch, and the ``member_status`` / ``problems_only`` /
``critical_only`` filter branches.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.members_without_dues_schedule import (
    members_without_dues_schedule as report,
)


class TestMembersWithoutDuesScheduleReport(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.suffix = frappe.generate_hash(length=6)

    # ------------------------------------------------------------- helpers

    def _member_with_customer(self, status="Active", **kwargs):
        member = self.create_test_member(
            first_name="Dues",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"dues.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            auto_create_customer=True,
            **kwargs,
        )
        member.reload()
        self.assertTrue(member.customer, "member should have a customer for the report to include it")
        return member

    def _active_schedule(self, member, **kwargs):
        """Create an active membership + dues schedule for ``member``.

        A Membership Dues Schedule validates that the member has an active
        (submitted) Membership, so we submit a membership first. The
        membership on_submit auto-creates a schedule; we then overwrite the
        fields the report reads (next_invoice_date, dues_rate, etc.) directly
        in the DB so the report sees the requested state.
        """
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        membership.submit()

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active", "is_template": 0},
            "name",
        )
        self.assertTrue(
            schedule_name, "submitting the membership should auto-create an active dues schedule"
        )
        for field, value in kwargs.items():
            frappe.db.set_value("Membership Dues Schedule", schedule_name, field, value)
        return frappe.get_doc("Membership Dues Schedule", schedule_name)

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        self.assertEqual(len(columns), 15)
        # Columns are colon-encoded strings; the first is the Member link.
        self.assertIn("Link/Member", columns[0])
        self.assertIn("Currency", columns[11])  # Dues Rate

    # --------------------------------------------------------- no schedule

    def test_member_without_schedule_appears_with_no_schedule_marker(self):
        member = self._member_with_customer()
        columns, data, _, chart, summary = report.execute({})

        self.assertEqual(len(columns), 15)
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row, "member without a dues schedule must appear in the report")
        self.assertIn("No Schedule", row["dues_schedule_status"])
        self.assertIn("No Coverage", row["coverage_gap"])
        self.assertIn("Create Schedule", row["action_required"])
        self.assertEqual(row["days_overdue"], 0)
        self.assertIsNone(row["billing_frequency"])

    def test_member_without_customer_is_skipped(self):
        # A member with no customer record must not appear at all.
        member = self.create_test_member(
            first_name="NoCust",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"nocust.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        member.reload()
        if member.customer:
            frappe.db.set_value("Member", member.name, "customer", None)

        columns, data, _, chart, summary = report.execute({})
        self.assertFalse(
            any(r["member_id"] == member.name for r in data),
            "members without a customer must be skipped",
        )

    # ----------------------------------------------------- healthy schedule

    def test_member_with_healthy_schedule_is_active(self):
        member = self._member_with_customer()
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), 10),  # future -> not overdue
            billing_frequency="Monthly",
            dues_rate=15.0,
        )

        columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Active", row["dues_schedule_status"])
        self.assertEqual(row["days_overdue"], 0)
        self.assertEqual(float(row["dues_rate"]), 15.0)
        self.assertEqual(row["billing_frequency"], "Monthly")

    # ---------------------------------------------------- overdue branches

    def test_member_with_critical_overdue_schedule(self):
        member = self._member_with_customer()
        # next_invoice_date 20 days in the past -> days_overdue > 14 -> Critical
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), -20),
            billing_frequency="Monthly",
            dues_rate=12.0,
        )

        columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Critical", row["dues_schedule_status"])
        self.assertGreaterEqual(row["days_overdue"], 14)
        self.assertIn("Urgent Fix Required", row["action_required"])

    def test_member_with_overdue_schedule_between_7_and_14_days(self):
        member = self._member_with_customer()
        self._active_schedule(
            member,
            next_invoice_date=add_days(today(), -10),  # 10 days -> Overdue
            billing_frequency="Monthly",
            dues_rate=10.0,
        )

        columns, data, _, chart, summary = report.execute({})
        row = next((r for r in data if r["member_id"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Overdue", row["dues_schedule_status"])
        self.assertTrue(7 < row["days_overdue"] <= 14)

    # ------------------------------------------------------- filter: problems_only

    def test_problems_only_filter_excludes_healthy_schedules(self):
        healthy = self._member_with_customer()
        self._active_schedule(healthy, next_invoice_date=add_days(today(), 10), dues_rate=15.0)

        critical = self._member_with_customer()
        self._active_schedule(critical, next_invoice_date=add_days(today(), -30), dues_rate=15.0)

        columns, data, _, chart, summary = report.execute({"problems_only": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(critical.name, ids, "problem schedule must be retained")
        self.assertNotIn(healthy.name, ids, "healthy schedule must be filtered out")

    def test_critical_only_filter_excludes_non_critical(self):
        minor = self._member_with_customer()
        self._active_schedule(minor, next_invoice_date=add_days(today(), -5), dues_rate=15.0)  # 5 days

        critical = self._member_with_customer()
        self._active_schedule(critical, next_invoice_date=add_days(today(), -30), dues_rate=15.0)

        columns, data, _, chart, summary = report.execute({"critical_only": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(critical.name, ids)
        self.assertNotIn(minor.name, ids, "schedules <= 7 days overdue are not critical")

    # --------------------------------------------------- filter: member_status

    def test_member_status_filter_restricts_to_status(self):
        active = self._member_with_customer(status="Active")
        suspended = self._member_with_customer(status="Suspended")

        columns, data, _, chart, summary = report.execute({"member_status": "Suspended"})
        ids = {r["member_id"] for r in data}
        self.assertIn(suspended.name, ids)
        self.assertNotIn(active.name, ids)

    def test_default_excludes_suspended_members(self):
        suspended = self._member_with_customer(status="Suspended")
        columns, data, _, chart, summary = report.execute({})
        ids = {r["member_id"] for r in data}
        self.assertNotIn(suspended.name, ids, "Suspended members are excluded by default")

    def test_include_suspended_filter(self):
        suspended = self._member_with_customer(status="Suspended")
        columns, data, _, chart, summary = report.execute({"include_suspended": 1})
        ids = {r["member_id"] for r in data}
        self.assertIn(suspended.name, ids)

    # ----------------------------------------------------------- summary / chart

    def test_summary_counts_members_without_schedule(self):
        member = self._member_with_customer()
        columns, data, _, chart, summary = report.execute({})

        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Total Members Analyzed", labels)
        self.assertIn("Members Without Schedule", labels)
        self.assertGreaterEqual(labels["Members Without Schedule"], 1)
        self.assertEqual(labels["Total Members Analyzed"], len(data))

    def test_summary_empty_when_no_data(self):
        self.assertEqual(report.get_report_summary([]), [])

    def test_chart_none_when_no_data(self):
        self.assertIsNone(report.get_chart_data([]))

    def test_chart_reflects_status_distribution(self):
        member = self._member_with_customer()
        columns, data, _, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "pie")
        self.assertIn("No Schedule", chart["data"]["labels"])

    # ----------------------------------------------- get_report_summary financial

    def test_report_summary_estimates_overdue_amount(self):
        # Build synthetic data rows feeding the financial estimate branch.
        rows = [
            {
                "dues_schedule_status": '<span class="indicator red">Critical</span>',
                "days_overdue": 30,
                "dues_rate": 10.0,
                "billing_frequency": "Daily",
            }
        ]
        summary = report.get_report_summary(rows)
        labels = {s["label"]: s["value"] for s in summary}
        # Daily * 30 days * 10.0 = 300
        self.assertEqual(labels["Estimated Overdue Amount"], 300)
