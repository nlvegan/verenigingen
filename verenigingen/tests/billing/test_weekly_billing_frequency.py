# -*- coding: utf-8 -*-
"""
End-to-end proof that the "Weekly" billing frequency actually bills.

WHY THIS FILE EXISTS
--------------------
PR #280 added ``Weekly`` to the ``billing_frequency`` Select on both Membership
Dues Schedule and Member Fee Change History. Until then the option did not
exist, so ``_validate_selects()`` rejected every production write of it — no
deployment has ever run a Weekly schedule. The claim attached to that change
("the calculator, batch processor and reports have always handled Weekly; only
the schema was missing it") was never verified against the running code.

These tests verify it by driving the real path and asserting the concrete dates
and amounts, never merely that a row was persisted:

  * the schema accepts and PERSISTS "Weekly" (read back from the database, not
    from the in-memory doc — a dropped Select silently becomes NULL/first option)
  * period arithmetic through the controller: +7 days, Monday..Sunday weeks
  * the coverage sequence: a first period of exactly 7 days anchored on the
    join date, and a second period that starts the day after the first ended
  * a real Sales Invoice: 7-day coverage, one line, qty 1, full (unprorated)
    dues_rate, and next_invoice_date advanced by exactly 7 days
  * the batch processor's cutoff rule, which caps generation one BILLING PERIOD
    ahead of today — a week for Weekly. If Weekly fell through to the Monthly
    default the cap would sit ~30 days out and the batch would keep re-billing.

Deliberately on VereningingenTestCase: EnhancedTestCase is the harness whose
``in_import`` flag suppressed ``_validate_selects()`` and made this whole class
of defect invisible.
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.billing.bulk_invoice_generation_service import (
    BulkInvoiceGenerationService,
)
from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.tests.utils.base import VereningingenTestCase

DUES_RATE = 7.0
MINIMUM_AMOUNT = 5.0

# A fixed Wednesday, so the Monday..Sunday assertions do not depend on the day
# the suite happens to run.
FIXED_WEDNESDAY = getdate("2025-03-12")
FIXED_WEEK_MONDAY = getdate("2025-03-10")
FIXED_WEEK_SUNDAY = getdate("2025-03-16")


class TestWeeklyBillingFrequency(VereningingenTestCase):
    """Drive a Weekly dues schedule through calculation, invoicing and the batch."""

    def setUp(self):
        super().setUp()

        # Pin the settings the billing path reads, so the assertions below describe
        # the code and not whatever the test site happens to be configured with.
        self._settings_backup = {}
        self._pin_setting("enable_sequential_coverage", 1)
        self._pin_setting("auto_submit_membership_invoices", 1)
        self._pin_setting("billing_cutoff_frequency", "Monthly")

        self.today = getdate(today())

        self.member = self.create_test_member(auto_create_customer=True, status="Active")
        self.assertTrue(self.member.customer, "invoice generation needs a Customer on the member")

        self.membership_type = self.create_test_membership_type(minimum_amount=MINIMUM_AMOUNT)

        # The factory inserts a Draft membership; submitting it makes the member
        # billable and auto-creates the (Annual) dues schedule we switch to Weekly.
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
            start_date=self.today,
        )
        self.membership.submit()

        self.schedule = self._make_weekly_schedule()

    def tearDown(self):
        for fieldname, value in self._settings_backup.items():
            frappe.db.set_single_value("Verenigingen Settings", fieldname, value)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def _pin_setting(self, fieldname, value):
        self._settings_backup[fieldname] = frappe.db.get_single_value("Verenigingen Settings", fieldname)
        frappe.db.set_single_value("Verenigingen Settings", fieldname, value)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

    def _make_weekly_schedule(self):
        """Switch the member's auto-created schedule to Weekly and return it."""
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertTrue(name, "submitting a Membership should auto-create an Active dues schedule")

        schedule = frappe.get_doc("Membership Dues Schedule", name)
        schedule.billing_frequency = "Weekly"
        schedule.dues_rate = DUES_RATE
        schedule.save()
        return schedule

    def _generate_invoice(self):
        """Generate one invoice through the real controller path, failing loudly."""
        can_generate, reason = self.schedule.can_generate_invoice()
        self.assertTrue(can_generate, f"Weekly schedule should be invoiceable, got: {reason}")

        invoice = self.schedule.generate_invoice()
        self.assertIsNotNone(invoice, "generate_invoice() returned None for a Weekly schedule")
        self.track_doc("Sales Invoice", invoice.name)
        self.schedule.reload()
        return invoice

    # ------------------------------------------------------------------- schema

    def test_weekly_is_a_valid_option_on_both_selects(self):
        """The two Selects PR #280 fixed must both offer Weekly.

        Before #280 they did not, so `_validate_selects()` rejected every Weekly
        write in production while the test harness let it through.
        """
        for doctype, fieldname in (
            ("Membership Dues Schedule", "billing_frequency"),
            ("Member Fee Change History", "billing_frequency"),
        ):
            options = frappe.get_meta(doctype).get_field(fieldname).options.split("\n")
            self.assertIn("Weekly", options, f"{doctype}.{fieldname} must offer Weekly")

    def test_weekly_persists_to_the_database(self):
        """A saved Weekly schedule reads back as Weekly, not NULL or a fallback."""
        stored = frappe.db.get_value("Membership Dues Schedule", self.schedule.name, "billing_frequency")
        self.assertEqual(stored, "Weekly")

    def test_weekly_persists_in_the_fee_change_history(self):
        """The canonical history writer stores Weekly instead of dropping the row."""
        from verenigingen.services.member.history.member_fee_change_history_service import (
            get_member_fee_change_history_service,
        )

        member_doc = frappe.get_doc("Member", self.member.name)
        get_member_fee_change_history_service().add_fee_change_to_history(
            member_doc,
            {
                "schedule_name": self.schedule.name,
                "dues_rate": DUES_RATE,
                "old_dues_rate": 0,
                "billing_frequency": "Weekly",
                "change_type": "Schedule Created",
            },
        )
        member_doc.save()

        # Re-read from the database, not from the in-memory doc: a rejected Select
        # value is what this test is looking for, and it only shows up on read-back.
        reloaded = frappe.get_doc("Member", self.member.name)
        rows = [r for r in reloaded.fee_change_history if r.dues_schedule == self.schedule.name]
        self.assertTrue(rows, "the fee change entry for the Weekly schedule was not written")
        self.assertEqual(rows[0].billing_frequency, "Weekly")

    # --------------------------------------------------------------- arithmetic

    def test_next_invoice_date_advances_exactly_seven_days(self):
        """Not ~a month: a Weekly schedule must advance by 7 days precisely."""
        next_date = getdate(self.schedule.calculate_next_invoice_date(from_date=FIXED_WEDNESDAY))
        self.assertEqual(next_date, add_days(FIXED_WEDNESDAY, 7))

    def test_billing_period_is_the_calendar_week_monday_to_sunday(self):
        """calculate_billing_period() returns the ISO week containing the date."""
        period_start, period_end = self.schedule.calculate_billing_period(FIXED_WEDNESDAY)
        self.assertEqual(getdate(period_start), FIXED_WEEK_MONDAY)
        self.assertEqual(getdate(period_end), FIXED_WEEK_SUNDAY)
        self.assertEqual((getdate(period_end) - getdate(period_start)).days, 6)

    def test_first_coverage_period_is_seven_days_from_the_join_date(self):
        """The first period runs a full week from the member's membership start.

        The member joined today, so coverage starts today rather than at the
        Monday of the surrounding week, and ends six days later — a full week,
        because nothing prorates a short period (the generator always charges
        the whole dues_rate).
        """
        calculator = CoverageCalculator(self.schedule)
        result = calculator.calculate_next_coverage_period(
            member_doc=frappe.get_doc("Member", self.member.name)
        )
        self.assertTrue(result.success, result.error_message)

        period = result.data
        self.assertEqual(period.calculation_method, "first_invoice")
        self.assertEqual(getdate(period.start_date), self.today)
        self.assertEqual(getdate(period.end_date), add_days(self.today, 6))

    # ------------------------------------------------------- invoice generation

    def test_generated_invoice_covers_one_week_at_the_full_rate(self):
        invoice = self._generate_invoice()

        coverage_start = getdate(invoice.custom_coverage_start_date)
        coverage_end = getdate(invoice.custom_coverage_end_date)
        self.assertEqual(coverage_start, self.today)
        self.assertEqual(coverage_end, add_days(self.today, 6))
        self.assertEqual((coverage_end - coverage_start).days, 6, "coverage must span exactly one week")

        # One line, quantity one, the full weekly rate. A frequency-dependent
        # multiplier or a prorating bug would show up here as a different amount.
        self.assertEqual(len(invoice.items), 1)
        self.assertEqual(flt(invoice.items[0].qty), 1.0)
        self.assertEqual(flt(invoice.items[0].rate, 2), flt(DUES_RATE, 2))
        self.assertEqual(flt(invoice.net_total, 2), flt(DUES_RATE, 2))
        self.assertEqual(invoice.items[0].item_code, "Membership Dues - Weekly")

    def test_schedule_dates_advance_by_a_week_after_invoicing(self):
        invoice = self._generate_invoice()

        self.assertEqual(getdate(self.schedule.last_invoice_coverage_start), self.today)
        self.assertEqual(getdate(self.schedule.last_invoice_coverage_end), add_days(self.today, 6))
        self.assertEqual(getdate(self.schedule.last_invoice_date), getdate(invoice.posting_date))
        self.assertEqual(
            getdate(self.schedule.next_invoice_date),
            add_days(getdate(invoice.posting_date), 7),
            "next_invoice_date must advance one week, not one month",
        )
        # The member-facing mirror of the same date.
        self.assertEqual(
            getdate(frappe.db.get_value("Member", self.member.name, "next_invoice_date")),
            add_days(getdate(invoice.posting_date), 7),
        )

    def test_second_invoice_continues_the_week_without_a_gap(self):
        """Sequential coverage: week two starts the day week one ended + 1."""
        first = self._generate_invoice()
        second = self._generate_invoice()

        self.assertNotEqual(first.name, second.name)

        first_end = getdate(first.custom_coverage_end_date)
        second_start = getdate(second.custom_coverage_start_date)
        second_end = getdate(second.custom_coverage_end_date)

        self.assertEqual(second_start, add_days(first_end, 1), "weekly coverage must be gap-free")
        self.assertEqual(second_end, add_days(second_start, 6))
        self.assertEqual(flt(second.net_total, 2), flt(DUES_RATE, 2))

    # ------------------------------------------------------- batch / cutoff rule

    def test_batch_generates_once_then_stops_a_week_ahead(self):
        """The cutoff cap is one BILLING period ahead of today — a week, not a month.

        should_generate_for_cutoff_period() compares the latest coverage end
        against min(cutoff_date, one period ahead of today). With Weekly handled
        the cap is today+6, which the first invoice reaches exactly, so no second
        invoice is due. Were Weekly falling through to the Monthly default the
        cap would sit ~30 days out and the batch would keep re-billing the member
        every run until coverage caught up.
        """
        cutoff = BulkInvoiceGenerationService().calculate_cutoff_date()

        self.assertTrue(
            self.schedule.should_generate_for_cutoff_period(cutoff),
            "an uncovered Weekly schedule must be picked up by the batch",
        )

        self._generate_invoice()

        self.assertFalse(
            self.schedule.should_generate_for_cutoff_period(cutoff),
            "a Weekly schedule covered through today+6 is a full period ahead; "
            "generating again would over-bill",
        )

    def test_batch_eligibility_scan_sees_the_weekly_schedule(self):
        """The real batch entry point selects the Weekly schedule, then drops it."""
        service = BulkInvoiceGenerationService()
        cutoff = service.calculate_cutoff_date()

        before = service.get_eligible_schedules(cutoff_date=cutoff, test_mode=False)
        self.assertIn(
            self.schedule.name,
            before.eligible_schedules,
            "the bulk generator must consider an uninvoiced Weekly schedule eligible",
        )

        self._generate_invoice()

        after = service.get_eligible_schedules(cutoff_date=cutoff, test_mode=False)
        self.assertNotIn(
            self.schedule.name,
            after.eligible_schedules,
            "after one week of coverage the Weekly schedule must drop out of the batch",
        )
        already_covered = [row["schedule"] for row in after.filtered_members["already_covered"]]
        self.assertIn(self.schedule.name, already_covered)

    # ------------------------------------------- schedule creation / recovery paths

    def test_auto_creator_sets_a_weekly_next_invoice_date(self):
        """dues_schedule_auto_creator keeps its own frequency ladder; Weekly must be in it."""
        from verenigingen.services.billing import dues_schedule_auto_creator as auto_creator

        self.assertEqual(
            getdate(auto_creator._calculate_next_invoice_date("Weekly")),
            add_days(self.today, 7),
            "a Weekly schedule auto-created for a member must next invoice in a week",
        )
