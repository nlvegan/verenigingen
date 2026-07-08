"""
Real-integration tests for the *Overdue Member Payments* script report
(``verenigingen/verenigingen/report/overdue_member_payments/``).

This report was at 79% coverage. The report is LIVE: it is registered as a
standard Script Report with ref_doctype Member.

These tests seed real Members (with Customers), Memberships and overdue Sales
Invoices via the factory and call ``execute(filters)`` directly. They cover:
  * the column structure and the empty-result branch;
  * the customer-aggregation logic (multiple overdue invoices per member);
  * the status-indicator branches (Due / Overdue / Urgent / Critical and the
    grace-period variants);
  * the ``from_date`` / ``to_date`` / ``days_overdue`` / ``critical_only`` /
    ``urgent_only`` / ``membership_type`` / ``chapter`` filter branches;
  * the summary statistics, the chapter chart, and the batch loaders for
    chapters and last-payment dates.

No business logic is mocked. Tests run as Administrator.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.overdue_member_payments import (
    overdue_member_payments as report,
)


class TestOverdueMemberPaymentsReport(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.suffix = frappe.generate_hash(length=6)

    # ------------------------------------------------------------- helpers

    def _member_with_customer(self, status="Active", **kwargs):
        member = self.create_test_member(
            first_name="Overdue",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"overdue.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
            auto_create_customer=True,
            **kwargs,
        )
        member.reload()
        self.assertTrue(member.customer, "member must have a customer for the report to include it")
        return member

    def _active_membership(self, member, **kwargs):
        membership_type = self.create_test_membership_type(**kwargs)
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        membership.submit()
        return membership, membership_type

    def _overdue_invoice(self, member, due_date, posting_date=None):
        """Create a submitted, overdue Sales Invoice for ``member``.

        The report filters on ``status in (Overdue, Unpaid)`` and
        ``due_date < today`` with ``docstatus = 1``. A submitted invoice with a
        non-zero outstanding amount and a past due_date is "Overdue".

        The factory always appends a single line item at rate 25.0, so each
        invoice's outstanding amount is 25.0.
        """
        posting_date = posting_date or due_date
        invoice = self.create_test_sales_invoice(
            member=member.name,
            posting_date=posting_date,
            due_date=due_date,
        )
        invoice.submit()
        invoice.reload()
        return invoice

    def _add_member_to_chapter(self, member, chapter):
        chapter.append(
            "members",
            {"member": member.name, "status": "Active", "enabled": 1},
        )
        chapter.save()

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertIn("member_name", fieldnames)
        self.assertIn("total_overdue", fieldnames)
        self.assertIn("days_overdue", fieldnames)
        self.assertIn("status_indicator", fieldnames)
        self.assertIn("grace_period_status", fieldnames)

    def test_validate_doctype_fields_known_good(self):
        self.assertTrue(report.validate_doctype_fields("Member", ["name", "full_name", "email"]))

    def test_validate_doctype_fields_missing_returns_false(self):
        self.assertFalse(report.validate_doctype_fields("Member", ["definitely_not_a_real_field_xyz"]))

    # --------------------------------------------------------- empty branch

    def test_execute_empty_filters_returns_five_tuple(self):
        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        self.assertTrue(len(columns) > 0)
        self.assertIsInstance(data, list)

    def test_execute_none_filters(self):
        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute(None)
        self.assertIsInstance(data, list)

    def test_summary_and_chart_empty_when_no_data(self):
        self.assertEqual(report.get_summary([]), [])
        self.assertIsNone(report.get_chart_data([]))

    # ---------------------------------------------------- overdue detection

    def test_member_with_overdue_invoice_appears(self):
        member = self._member_with_customer()
        self._active_membership(member)
        # Due 20 days ago -> overdue, 14 < days <= 30 -> "Overdue" indicator.
        self._overdue_invoice(member, due_date=add_days(today(), -20))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})

        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row, "member with an overdue invoice must appear")
        self.assertEqual(row["overdue_count"], 1)
        self.assertGreater(row["total_overdue"], 0)
        self.assertGreaterEqual(row["days_overdue"], 19)
        self.assertIn("Overdue", row["status_indicator"])

    def test_multiple_overdue_invoices_are_aggregated(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -10))
        self._overdue_invoice(member, due_date=add_days(today(), -40))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})

        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["overdue_count"], 2)
        # Each factory invoice is 25.0 -> two invoices aggregate to 50.0.
        self.assertEqual(row["total_overdue"], 50.0)
        # days_overdue is computed from the oldest (min) due date -> ~40 days.
        self.assertGreaterEqual(row["days_overdue"], 39)
        # oldest invoice date should be the earlier posting date.
        self.assertEqual(str(row["oldest_invoice_date"]), str(add_days(today(), -40)))

    def test_paid_invoice_is_not_overdue(self):
        member = self._member_with_customer()
        self._active_membership(member)
        invoice = self._overdue_invoice(member, due_date=add_days(today(), -20))
        # Fully pay it -> status becomes Paid -> excluded from the report.
        frappe.db.set_value("Sales Invoice", invoice.name, "outstanding_amount", 0)
        frappe.db.set_value("Sales Invoice", invoice.name, "status", "Paid")

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        self.assertFalse(
            any(r["member_name"] == member.name for r in data),
            "paid invoices must not be reported as overdue",
        )

    # ---------------------------------------------- status indicator tiers

    def test_status_indicator_critical_over_60_days(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -70))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Critical", row["status_indicator"])

    def test_status_indicator_urgent_between_30_and_60(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -45))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Urgent", row["status_indicator"])

    def test_status_indicator_due_under_14_days(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -3))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Due", row["status_indicator"])

    # --------------------------------------------------- grace period logic

    def test_grace_period_active_indicator(self):
        member = self._member_with_customer()
        membership, _ = self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -70))
        # Set the active membership into a grace period expiring far in the future.
        frappe.db.set_value("Membership", membership.name, "grace_period_status", "Grace Period")
        frappe.db.set_value("Membership", membership.name, "grace_period_expiry_date", add_days(today(), 30))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["grace_period_status"], "Grace Period")
        self.assertIn("Grace Period", row["status_indicator"])
        self.assertNotIn("Expiring", row["status_indicator"])
        self.assertNotIn("Expired", row["status_indicator"])

    def test_grace_period_expiring_soon_indicator(self):
        member = self._member_with_customer()
        membership, _ = self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -70))
        frappe.db.set_value("Membership", membership.name, "grace_period_status", "Grace Period")
        frappe.db.set_value("Membership", membership.name, "grace_period_expiry_date", add_days(today(), 3))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Grace Period Expiring", row["status_indicator"])

    def test_grace_period_expired_indicator(self):
        member = self._member_with_customer()
        membership, _ = self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -70))
        frappe.db.set_value("Membership", membership.name, "grace_period_status", "Grace Period")
        frappe.db.set_value("Membership", membership.name, "grace_period_expiry_date", add_days(today(), -1))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        self.assertIn("Grace Period Expired", row["status_indicator"])

    # ------------------------------------------------------------- filters

    def test_days_overdue_filter_excludes_recent(self):
        recent = self._member_with_customer()
        self._active_membership(recent)
        self._overdue_invoice(recent, due_date=add_days(today(), -10))

        old = self._member_with_customer()
        self._active_membership(old)
        self._overdue_invoice(old, due_date=add_days(today(), -50))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"days_overdue": 30})
        names = {r["member_name"] for r in data}
        self.assertIn(old.name, names)
        self.assertNotIn(recent.name, names, "invoices < 30 days overdue must be excluded")

    def test_critical_only_filter(self):
        moderate = self._member_with_customer()
        self._active_membership(moderate)
        self._overdue_invoice(moderate, due_date=add_days(today(), -40))

        critical = self._member_with_customer()
        self._active_membership(critical)
        self._overdue_invoice(critical, due_date=add_days(today(), -80))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"critical_only": 1})
        names = {r["member_name"] for r in data}
        self.assertIn(critical.name, names)
        self.assertNotIn(moderate.name, names, "only > 60 days overdue are critical")

    def test_urgent_only_filter(self):
        minor = self._member_with_customer()
        self._active_membership(minor)
        self._overdue_invoice(minor, due_date=add_days(today(), -20))

        urgent = self._member_with_customer()
        self._active_membership(urgent)
        self._overdue_invoice(urgent, due_date=add_days(today(), -50))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"urgent_only": 1})
        names = {r["member_name"] for r in data}
        self.assertIn(urgent.name, names)
        self.assertNotIn(minor.name, names, "only > 30 days overdue are urgent")

    def test_from_date_and_to_date_filter(self):
        in_range = self._member_with_customer()
        self._active_membership(in_range)
        self._overdue_invoice(in_range, due_date=add_days(today(), -20), posting_date=add_days(today(), -20))

        out_of_range = self._member_with_customer()
        self._active_membership(out_of_range)
        self._overdue_invoice(
            out_of_range, due_date=add_days(today(), -200), posting_date=add_days(today(), -200)
        )

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute(
                {"from_date": add_days(today(), -40), "to_date": add_days(today(), -5)}
            )
        names = {r["member_name"] for r in data}
        self.assertIn(in_range.name, names)
        self.assertNotIn(out_of_range.name, names, "invoices posted outside the date window must be excluded")

    def test_from_date_only_filter(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -20), posting_date=add_days(today(), -20))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"from_date": add_days(today(), -40)})
        names = {r["member_name"] for r in data}
        self.assertIn(member.name, names)

    def test_membership_type_filter(self):
        member_a = self._member_with_customer()
        _, type_a = self._active_membership(member_a)
        self._overdue_invoice(member_a, due_date=add_days(today(), -20))

        member_b = self._member_with_customer()
        _, type_b = self._active_membership(member_b)
        self._overdue_invoice(member_b, due_date=add_days(today(), -20))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"membership_type": type_a.name})
        names = {r["member_name"] for r in data}
        self.assertIn(member_a.name, names)
        self.assertNotIn(member_b.name, names, "different membership type must be excluded")

    def test_chapter_filter_excludes_members_not_in_chapter(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -20))

        # Member is in no chapter -> filtering on a real chapter must exclude it.
        chapter = self.create_test_chapter()
        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"chapter": chapter.name})
        names = {r["member_name"] for r in data}
        self.assertNotIn(member.name, names)

    def test_chapter_filter_includes_member_in_chapter(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -20))

        chapter = self.create_test_chapter()
        self._add_member_to_chapter(member, chapter)

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({"chapter": chapter.name})
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row, "member belonging to the filtered chapter must appear")

    # ----------------------------------------------------- summary / chart

    def test_summary_statistics(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -70))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        labels = {s["label"]: s["value"] for s in summary}
        self.assertIn("Members with Overdue Payments", labels)
        self.assertIn("Total Overdue Invoices", labels)
        self.assertIn("Critical (>60 days)", labels)
        self.assertGreaterEqual(labels["Members with Overdue Payments"], 1)
        self.assertGreaterEqual(labels["Critical (>60 days)"], 1)

    def test_chart_groups_by_chapter(self):
        member = self._member_with_customer()
        self._active_membership(member)
        self._overdue_invoice(member, due_date=add_days(today(), -20))

        with self.assertNoErrorLog():
            columns, data, _none, chart, summary = report.execute({})
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")
        # Chart groups overdue amounts by chapter; the seeded member's row chapter
        # must appear as a chart label.
        row = next((r for r in data if r["member_name"] == member.name), None)
        self.assertIsNotNone(row)
        expected_label = row["chapter"] or "Unassigned"
        self.assertIn(expected_label, chart["data"]["labels"])

    # ------------------------------------------------------- batch loaders

    def test_batch_get_member_chapters_empty_input(self):
        self.assertEqual(report.batch_get_member_chapters([]), {})

    def test_batch_get_last_payment_dates_empty_input(self):
        self.assertEqual(report.batch_get_last_payment_dates([]), {})

    def test_get_members_for_customers_maps_customer_to_member(self):
        member = self._member_with_customer()
        mapping = report.get_members_for_customers([member.customer])
        self.assertEqual(mapping.get(member.customer), member.name)

    def test_batch_get_member_info_resolves_membership_fields(self):
        member = self._member_with_customer()
        membership, mtype = self._active_membership(member)
        frappe.db.set_value("Membership", membership.name, "grace_period_status", "Grace Period")

        info = report.batch_get_member_info_by_customers([member.customer])
        self.assertIn(member.customer, info)
        self.assertEqual(info[member.customer]["membership_type"], mtype.name)
        self.assertEqual(info[member.customer]["grace_period_status"], "Grace Period")

    def test_get_member_info_by_customer_single(self):
        member = self._member_with_customer()
        self._active_membership(member)
        info = report.get_member_info_by_customer(member.customer)
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], member.name)

    # ---------------------------------------------------- invalid filter (unhappy)

    def test_execute_raises_on_non_numeric_days_overdue_filter(self):
        """A non-numeric days_overdue filter must raise, not be silently swallowed.

        get_data() does ``int(filters.get("days_overdue"))`` with no guard, and
        execute()'s outer except re-raises after logging. This is a genuine
        invalid-parameter rejection path that was previously untested (only
        the happy numeric-filter case was covered by
        test_days_overdue_filter_excludes_recent).
        """
        with self.assertRaises(ValueError):
            report.execute({"days_overdue": "not-a-number"})
