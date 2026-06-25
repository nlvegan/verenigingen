# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for membership_duration_service.

Covers the pure formatting / years helpers with exact boundary values plus the
DB-backed total-days calculation against real submitted Membership records.
"""

import unittest

import frappe
from frappe.utils import add_days, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.utils.membership_duration_service import (
    calculate_duration_in_years,
    calculate_total_membership_days,
    format_duration_human_readable,
    get_membership_duration_summary,
    update_member_duration_fields,
)


class TestMembershipDurationFormatting(EnhancedTestCase):
    """Pure formatting / conversion tests - exact value assertions."""

    def test_format_zero_or_negative(self):
        self.assertEqual(format_duration_human_readable(0), "Less than 1 month")
        self.assertEqual(format_duration_human_readable(-5), "Less than 1 month")

    def test_format_rounds_to_nearest_month(self):
        # 14 days -> rounds down to 0 months -> "Less than 1 month"
        self.assertEqual(format_duration_human_readable(14), "Less than 1 month")
        # 15 days -> round(15/30)=0 (banker's? no, round(0.5)=0) ; 16 days -> round(0.53)=1
        self.assertEqual(format_duration_human_readable(16), "1 month")
        # 30 days -> 1 month
        self.assertEqual(format_duration_human_readable(30), "1 month")
        # 60 days -> 2 months
        self.assertEqual(format_duration_human_readable(60), "2 months")

    def test_format_years_and_months(self):
        # 365 days -> round(365/30)=12 months -> 1 year
        self.assertEqual(format_duration_human_readable(365), "1 year")
        # 13 months worth: 390 days -> round(13.0)=13 -> 1 year, 1 month
        self.assertEqual(format_duration_human_readable(390), "1 year, 1 month")
        # 25 months: 750 days -> round(25.0)=25 -> 2 years, 1 month
        self.assertEqual(format_duration_human_readable(750), "2 years, 1 month")

    def test_format_pluralization(self):
        # 720 days -> 24 months -> exactly 2 years (no months) and plural "years"
        self.assertEqual(format_duration_human_readable(720), "2 years")

    def test_calculate_duration_in_years(self):
        self.assertEqual(calculate_duration_in_years(0), 0)
        self.assertEqual(calculate_duration_in_years(-1), 0)
        # 365.25 days = exactly 1 year
        self.assertAlmostEqual(calculate_duration_in_years(365.25), 1.0, places=4)
        self.assertAlmostEqual(calculate_duration_in_years(730.5), 2.0, places=4)


class TestMembershipDurationCalculation(EnhancedTestCase):
    """DB-backed total-days calculation with real Membership records."""

    def _membership_type(self):
        return self.create_test_membership_type().name

    def test_no_member_returns_zero(self):
        self.assertEqual(calculate_total_membership_days("NONEXISTENT-MEMBER"), 0)

    def test_member_with_no_memberships(self):
        member = self.create_test_member(
            first_name="Dur",
            last_name="NoMemb",
            email="dur.nomemb@example.com",
        )
        self.assertEqual(calculate_total_membership_days(member.name), 0)

    def test_active_membership_counts_to_today(self):
        """Active membership without renewal date counts start..today inclusive."""
        member = self.create_test_member(
            first_name="Dur",
            last_name="Active",
            email="dur.active@example.com",
        )
        start = add_days(today(), -100)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._membership_type(),
            start_date=start,
            status="Active",
        )
        # Clear renewal_date so the active branch uses today
        if membership.get("renewal_date"):
            frappe.db.set_value("Membership", membership.name, "renewal_date", None)
        days = calculate_total_membership_days(member.name)
        # start..today inclusive = 100 + 1
        self.assertEqual(days, 101)

    def test_active_membership_capped_at_renewal_date(self):
        """Active membership counts only up to renewal_date when it is in the past."""
        member = self.create_test_member(
            first_name="Dur",
            last_name="Capped",
            email="dur.capped@example.com",
        )
        start = add_days(today(), -100)
        renewal = add_days(today(), -40)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._membership_type(),
            start_date=start,
            status="Active",
        )
        frappe.db.set_value("Membership", membership.name, "renewal_date", renewal)
        days = calculate_total_membership_days(member.name)
        # min(today, renewal) = renewal; start..renewal inclusive = 60 + 1
        self.assertEqual(days, 61)

    def test_update_member_duration_fields_writes_field(self):
        """update_member_duration_fields populates cumulative_membership_duration."""
        member = self.create_test_member(
            first_name="Dur",
            last_name="Update",
            email="dur.update@example.com",
        )
        start = add_days(today(), -400)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._membership_type(),
            start_date=start,
            status="Active",
        )
        frappe.db.set_value("Membership", membership.name, "renewal_date", None)
        member.reload()
        result = update_member_duration_fields(member)
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_days"], 401)
        # 401 days -> round(401/30)=13 months -> "1 year, 1 month"
        self.assertEqual(member.cumulative_membership_duration, "1 year, 1 month")
        self.assertEqual(result.data["duration"], "1 year, 1 month")

    def test_duration_summary_structure_and_values(self):
        member = self.create_test_member(
            first_name="Dur",
            last_name="Summary",
            email="dur.summary@example.com",
        )
        start = add_days(today(), -730)
        membership = self.create_test_membership(
            member_name=member.name,
            membership_type_name=self._membership_type(),
            start_date=start,
            status="Active",
        )
        frappe.db.set_value("Membership", membership.name, "renewal_date", None)
        summary = get_membership_duration_summary(member.name)
        self.assertEqual(summary["member_name"], member.name)
        self.assertEqual(summary["total_days"], 731)
        self.assertGreater(summary["duration_years"], 1.9)
        self.assertLess(summary["duration_years"], 2.1)
        self.assertIn("year", summary["duration_formatted"])


if __name__ == "__main__":
    unittest.main()
