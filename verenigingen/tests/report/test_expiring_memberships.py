"""
Real-integration tests for the *Expiring Memberships* script report
(``verenigingen/verenigingen/report/expiring_memberships/``).

The report was at 0% coverage. It lists active/pending memberships whose
"expiry date" (the most recent dues-schedule ``next_invoice_date`` falling
back to the membership ``renewal_date``) falls in a given month/year.

These tests seed real Members + Memberships, set ``renewal_date`` /
dues-schedule ``next_invoice_date`` to known months, and assert on the
column structure and the month/year filtering branches (including the
fiscal-year string parsing and the empty-result branch).
"""

import frappe
from frappe.utils import getdate

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.expiring_memberships import expiring_memberships as report

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class TestExpiringMembershipsReport(VereningingenTestCase):
    # ------------------------------------------------------------- helpers

    def _member_with_membership(self, renewal_date=None, status="Active"):
        member = self.create_test_member(
            first_name="Expiry",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"expiry.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
        )
        membership.submit()
        # Force the membership status + renewal_date directly (the report reads
        # these via the COALESCE expiry calculation).
        frappe.db.set_value(
            "Membership",
            membership.name,
            {"status": status, "renewal_date": renewal_date},
            update_modified=False,
        )
        # The expiry COALESCE prefers the most recent dues schedule's
        # next_invoice_date over renewal_date. Submitting the membership
        # auto-creates a schedule, so align that schedule's next_invoice_date
        # with the renewal_date we want the report to key on (clear it when we
        # are deliberately testing the renewal_date fallback).
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0},
            "name",
            order_by="creation desc",
        )
        if schedule_name:
            frappe.db.set_value(
                "Membership Dues Schedule",
                schedule_name,
                "next_invoice_date",
                renewal_date,
                update_modified=False,
            )
        return member, membership

    # ------------------------------------------------------------- columns

    def test_get_columns_structure(self):
        columns = report.get_columns({})
        self.assertEqual(len(columns), 8)
        self.assertIn("Link/Membership Type", columns[0])
        self.assertIn("Link/Member", columns[2])
        self.assertIn("Date", columns[5])  # Expiring On

    def test_execute_returns_columns_and_data(self):
        with self.assertNoErrorLog():
            columns, data = report.execute({"month": "Jan", "fiscal_year": "2025"})
        self.assertEqual(len(columns), 8)
        self.assertIsInstance(data, list)

    # ------------------------------------------------------------- filtering

    def test_membership_appears_in_its_renewal_month(self):
        # Renewal date in a known, fixed month so the test is deterministic.
        renewal = getdate("2030-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal)

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jun", "fiscal_year": "2030"})
        ids = {r["name"] for r in data}  # member id is the 3rd column
        self.assertIn(member.name, ids, "membership must appear in June 2030")

    def test_membership_absent_in_other_month(self):
        renewal = getdate("2030-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal)

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jul", "fiscal_year": "2030"})
        ids = {r["name"] for r in data}
        self.assertNotIn(member.name, ids, "membership must not appear in a different month")

    def test_membership_absent_in_other_year(self):
        renewal = getdate("2030-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal)

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jun", "fiscal_year": "2029"})
        ids = {r["name"] for r in data}
        self.assertNotIn(member.name, ids)

    def test_fiscal_year_range_string_is_parsed(self):
        # "2030-2031" -> first segment (2030) is used as the year.
        renewal = getdate("2030-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal)

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jun", "fiscal_year": "2030-2031"})
        ids = {r["name"] for r in data}
        self.assertIn(member.name, ids)

    def test_invalid_fiscal_year_falls_back_to_current_year(self):
        # Non-numeric fiscal_year -> falls back to getdate().year. Seed a
        # renewal in the current year so the row is found.
        current_year = getdate().year
        renewal = getdate(f"{current_year}-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal)

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jun", "fiscal_year": "not-a-year"})
        ids = {r["name"] for r in data}
        self.assertIn(member.name, ids)

    def test_cancelled_membership_excluded(self):
        # Report only considers status in ('Active', 'Pending').
        renewal = getdate("2030-06-15")
        member, membership = self._member_with_membership(renewal_date=renewal, status="Cancelled")

        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jun", "fiscal_year": "2030"})
        ids = {r["name"] for r in data}
        self.assertNotIn(member.name, ids, "non-active/pending memberships are excluded")

    def test_empty_result_for_far_future_month(self):
        with self.assertNoErrorLog():
            _, data = report.execute({"month": "Jan", "fiscal_year": "1990"})
        self.assertEqual(data, [])
