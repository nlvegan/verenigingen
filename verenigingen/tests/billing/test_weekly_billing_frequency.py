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

These tests verify it by driving the real path and asserting concrete dates and
amounts, never merely that a row was persisted:

  * "Weekly" survives a save and reads back from the DATABASE. An invalid Select
    makes ``_validate_selects()`` throw on save, so a round trip is the proof
    that the option is really accepted end to end.
  * period arithmetic through the controller: +7 days, Monday..Sunday weeks
  * the coverage sequence: a first period of exactly 7 days anchored on the join
    date, and a second period that starts the day after the first ended
  * a real Sales Invoice: 7-day coverage, one line, qty 1, full (unprorated)
    dues_rate, and next_invoice_date advanced by exactly 7 days
  * the batch processor's per-schedule gate, whose cap is one BILLING PERIOD
    ahead of today — a week for Weekly, which is what stops a coarser global
    billing_cutoff_frequency (Monthly) from over-billing a Weekly member.

Deliberately on VereningingenTestCase: EnhancedTestCase is the harness whose
``in_import`` flag suppressed ``_validate_selects()`` and made this whole class
of defect invisible.
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.tests.support.verenigingen_settings import pin_setting
from verenigingen.tests.utils.base import VereningingenTestCase

DUES_RATE = 7.0
MINIMUM_AMOUNT = 5.0

# A fixed Wednesday, so the Monday..Sunday assertions do not depend on the day
# the suite happens to run.
FIXED_WEDNESDAY = getdate("2025-03-12")
FIXED_WEEK_MONDAY = getdate("2025-03-10")
FIXED_WEEK_SUNDAY = getdate("2025-03-16")


class TestWeeklyFrequencyIsDeclared(VereningingenTestCase):
    """Cheap declaration checks — no member/membership fixtures needed."""

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

    def test_auto_creator_sets_a_weekly_next_invoice_date(self):
        """dues_schedule_auto_creator keeps its own frequency ladder; Weekly must be in it.

        Without a Weekly branch the ladder falls through to its monthly default,
        so a Weekly schedule auto-created for a member was told to next invoice
        in a month.
        """
        from verenigingen.services.billing import dues_schedule_auto_creator as auto_creator

        self.assertEqual(
            getdate(auto_creator._calculate_next_invoice_date("Weekly")),
            add_days(getdate(today()), 7),
        )


class TestWeeklyBillingFrequency(VereningingenTestCase):
    """Drive a Weekly dues schedule through calculation, invoicing and the batch gate."""

    def setUp(self):
        super().setUp()

        # Pin the settings the billing path reads, so the assertions below describe
        # the code and not whatever the test site happens to be configured with.
        # Restores go through addCleanup (not tearDown): they must run AFTER the
        # base tearDown, which rolls back before each tracked-doc delete and would
        # otherwise discard them, and they must survive a setUp that raises later.
        self._pin_setting("enable_sequential_coverage", 1)
        self._pin_setting("auto_submit_membership_invoices", 1)
        self._pin_setting("billing_cutoff_frequency", "Monthly")

        self.today = getdate(today())

        self.member = self.create_test_member(auto_create_customer=True)
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

    # ------------------------------------------------------------------ helpers

    def _pin_setting(self, fieldname, value):
        # Delegates to tests/support/verenigingen_settings, which owns this. This
        # used to be three private helpers here; #659 needed the same thing and the
        # duplicate-helper census flagged the collision.
        #
        # Behaviour change worth knowing: the shared helper commits the PIN as well
        # as the restore (the local copy committed only the restore). Safe here
        # because these pins run before any fixture is created in setUp -- keep them
        # first if this setUp grows.
        pin_setting(self, fieldname, value)

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

    # ---------------------------------------------------------------- persistence

    def test_weekly_persists_to_the_database(self):
        """A saved Weekly schedule reads back as Weekly.

        This cannot fail on its own — an invalid Select throws inside
        `_make_weekly_schedule`'s save() and errors the whole class — but it
        names the property the rest of the file depends on.
        """
        stored = frappe.db.get_value("Membership Dues Schedule", self.schedule.name, "billing_frequency")
        self.assertEqual(stored, "Weekly")

    def test_weekly_persists_in_the_fee_change_history(self):
        """The canonical history writer stores Weekly instead of coercing it.

        `MemberFeeChangeHistoryService` keeps its own frequency allowlist and
        silently rewrites anything unlisted to "Custom", so a missing entry
        there would not raise — it would quietly mislabel the row.
        """
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

        # Re-read from the database, and pin the row to the one written above via
        # its change_type: the schedule's own hooks write other rows for this
        # schedule, and asserting on whichever lands first would be accidental.
        reloaded = frappe.get_doc("Member", self.member.name)
        rows = [
            r
            for r in reloaded.fee_change_history
            if r.dues_schedule == self.schedule.name and r.change_type == "Schedule Created"
        ]
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

    # -------------------------------------------------------- batch gate / cutoff

    def test_generation_cap_is_one_week_ahead_of_today(self):
        """The cap the batch applies to a Weekly schedule is today+6, not a month.

        billing_cutoff_frequency is a single global setting and is usually
        coarser than an individual member's frequency. should_generate_for_cutoff
        _period() therefore caps the cutoff at one BILLING period ahead of today
        (coverage_calculator.py:254). Pinned explicitly here because that value
        is the only frequency-sensitive input to the batch's per-schedule gate —
        a Monthly fall-through would put it ~30 days out.
        """
        calculator = CoverageCalculator(self.schedule)
        self.assertEqual(getdate(calculator._one_period_ahead_of_today()), add_days(self.today, 6))

    def test_batch_gate_generates_once_then_stops_a_week_ahead(self):
        """One invoice satisfies a far-future cutoff, because the cap is a week.

        The cutoff is passed explicitly rather than read from settings: the
        Monthly setting collapses below today+6 in the last days of a month,
        which would make this assertion vacuous on those dates. With a cutoff
        60 days out the min() is decided by the frequency cap alone.

        Honest scope: this asserts the gate opens once and then closes, i.e.
        that the cap and the coverage sequence agree. It does NOT by itself
        discriminate Weekly from another frequency — both sides of the
        comparison are computed by the same period arithmetic, deliberately
        (coverage_calculator.py:264-266). The frequency itself is pinned by
        test_generation_cap_is_one_week_ahead_of_today and by the coverage-date
        assertions above.
        """
        far_cutoff = add_days(self.today, 60)

        self.assertTrue(
            self.schedule.should_generate_for_cutoff_period(far_cutoff),
            "an uncovered Weekly schedule must be picked up by the batch",
        )

        self._generate_invoice()

        self.assertFalse(
            self.schedule.should_generate_for_cutoff_period(far_cutoff),
            "coverage through today+6 is a full week ahead; generating again would over-bill",
        )
