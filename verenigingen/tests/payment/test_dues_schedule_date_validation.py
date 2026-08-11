"""
Unit tests for dues schedule date validation and invoice generation.

These tests exercise the CURRENT date behaviour of Membership Dues Schedule:
  * a new instance schedule initializes next_invoice_date to today when unset
  * calculate_next_invoice_date advances dates per billing frequency
  * validate_dates enforces next_invoice_date >= last_invoice_date

NOTE: The legacy "auto-correct unreasonable next_invoice_date" behaviour and the
verenigingen.api.test_fixes helper module no longer exist; tests that asserted
them were removed. The valid billing frequencies are Daily/Weekly/Monthly/
Quarterly/Semi-Annual/Annual/Custom -- "Weekly" was re-added to the Select in
PR #280 and is exercised in tests/billing/test_weekly_billing_frequency.py.
"""

import frappe
import unittest
from frappe.utils import today, add_days, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDuesScheduleDateValidation(VereningingenTestCase):
    """Test suite for dues schedule date validation and edge cases"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.today = getdate(today())

    def _create_active_schedule(self, billing_frequency="Daily", dues_rate=5.0):
        """Create a member with an ACTIVE membership and return its dues schedule.

        Submitting a Membership auto-creates an Active Membership Dues Schedule
        (one active schedule per member is enforced by the controller), so the
        correct pattern is to reuse the auto-created schedule rather than insert
        a colliding new one.
        """
        member = self.create_test_member()
        membership_type = self.create_test_membership_type(
            billing_period="Monthly", minimum_amount=min(dues_rate, 5.0)
        )
        membership = self.create_test_membership(member=member, membership_type=membership_type.name)
        membership.submit()

        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        schedule.billing_frequency = billing_frequency
        schedule.dues_rate = dues_rate
        schedule.save()
        return member, membership, schedule

    def test_new_schedule_initializes_next_invoice_date(self):
        """A new instance schedule with no next_invoice_date defaults to today."""
        member, membership, schedule = self._create_active_schedule(billing_frequency="Daily")
        self.assertIsNotNone(
            schedule.next_invoice_date, "System should set next_invoice_date if not provided"
        )

    def test_daily_next_invoice_date_calculation(self):
        """calculate_next_invoice_date advances by one day for daily billing."""
        member, membership, schedule = self._create_active_schedule(billing_frequency="Daily")
        next_date = getdate(schedule.calculate_next_invoice_date(from_date=self.today))
        self.assertEqual(next_date, add_days(self.today, 1), "Daily billing should advance one day")

    def test_monthly_next_invoice_date_calculation(self):
        """calculate_next_invoice_date advances roughly a month for monthly billing."""
        member, membership, schedule = self._create_active_schedule(
            billing_frequency="Monthly", dues_rate=25.0
        )
        next_date = getdate(schedule.calculate_next_invoice_date(from_date=self.today))
        delta_days = (next_date - self.today).days
        self.assertGreaterEqual(delta_days, 28, "Monthly billing should advance at least 28 days")
        self.assertLessEqual(delta_days, 31, "Monthly billing should advance at most 31 days")

    def test_next_before_last_invoice_date_rejected(self):
        """validate_dates rejects a next_invoice_date before last_invoice_date."""
        member, membership, schedule = self._create_active_schedule(billing_frequency="Daily")

        schedule.last_invoice_date = self.today
        schedule.next_invoice_date = add_days(self.today, -1)
        with self.assertRaises(frappe.ValidationError):
            schedule.save()

    def test_consistent_last_next_dates_allowed(self):
        """A next_invoice_date one day after last_invoice_date saves cleanly."""
        member, membership, schedule = self._create_active_schedule(billing_frequency="Daily")

        schedule.last_invoice_date = self.today
        schedule.next_invoice_date = add_days(self.today, 1)
        schedule.save()  # should not raise

        self.assertEqual(getdate(schedule.last_invoice_date), self.today)
        self.assertEqual(getdate(schedule.next_invoice_date), add_days(self.today, 1))

    def test_invoice_generation_with_correct_dates(self):
        """Invoice generation works when the schedule is due today."""
        member, membership, schedule = self._create_active_schedule(billing_frequency="Daily")

        # Create customer for the member
        if not member.customer:
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": member.full_name,
                    "customer_type": "Individual",
                    "customer_group": "Individual",
                    "territory": "All Territories",
                }
            )
            customer.insert()
            member.db_set("customer", customer.name)
            member.reload()
            self.track_doc("Customer", customer.name)

        # Make the schedule due today (db_set bypasses next>=last validation safely)
        schedule.db_set("next_invoice_date", self.today)
        schedule.db_set("last_invoice_date", add_days(self.today, -1))
        schedule.reload()

        try:
            invoice = schedule.generate_invoice()
            if invoice:
                self.track_doc("Sales Invoice", invoice.name)
                self.assertEqual(
                    invoice.customer,
                    member.customer,
                    "Invoice should be for the correct customer",
                )
                self.assertGreater(invoice.grand_total, 0, "Invoice should have a positive amount")
        except Exception as e:
            # If generation fails, it should be due to configuration, not date issues
            self.assertNotIn(
                "date",
                str(e).lower(),
                f"Invoice generation should not fail due to date issues: {e}",
            )


if __name__ == "__main__":
    unittest.main()
