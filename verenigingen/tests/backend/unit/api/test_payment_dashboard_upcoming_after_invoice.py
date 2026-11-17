"""#2613: the payment dashboard's upcoming dates for a member who has already been invoiced.

The real invoice writer (``BillingDateService.update_schedule_dates``) sets
``last_invoice_date`` to the posting date and ``next_invoice_date`` one running period
later, so ``next > last`` holds after every invoice. The portal's ``get_upcoming_dates``
and ``get_payment_schedule`` both used to stop at the first date later than
``last_invoice_date`` and therefore listed nothing for any invoiced member.

Schedules are advanced through that real writer, not by hand-setting the two dates (the
earlier test did, to ``last = next + 15``, a state the invoice flow never produces).
Expected dates are derived from the schedule's own frequency and its real last invoice
date through the running-period chain (``calculate_next_invoice_date``), never hardcoded.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.api.payment_dashboard import get_payment_schedule
from verenigingen.services.billing import billing_period_calculator as bpc
from verenigingen.services.billing.billing_date_service import get_billing_date_service
from verenigingen.templates.pages import payment_dashboard
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestUpcomingDatesAfterInvoice(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Upcoming", last_name="Invoiced", status="Active")
        self.create_test_membership(member_name=self.member.name)
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertIsNotNone(name, "Expected the membership to create an active dues schedule")
        self.schedule = frappe.get_doc("Membership Dues Schedule", name)

    def _posting_date(self):
        """A recent posting date (so every projected date is still in the future) that is
        NOT the 1st: a calendar-anchored implementation would land on the wrong day."""
        posting = getdate(add_days(today(), -10))
        if posting.day == 1:
            posting = add_days(posting, -1)
        return posting

    def _leave_schedule_invoiced(self, frequency):
        """Leave the schedule exactly as the real invoice flow does after one invoice."""
        posting = self._posting_date()
        self.schedule.billing_frequency = frequency
        self.schedule.next_invoice_date = posting
        self.schedule.last_invoice_date = None
        self.schedule.save()
        get_billing_date_service().update_schedule_dates(self.schedule, actual_invoice_date=str(posting))
        self.schedule.reload()
        # premise, derived from the writer's own output
        self.assertEqual(getdate(self.schedule.last_invoice_date), posting)
        self.assertGreater(getdate(self.schedule.next_invoice_date), getdate(self.schedule.last_invoice_date))
        return posting

    def _chain(self, frequency, start, count):
        dates, current = [start], start
        while len(dates) < count:
            current = bpc.calculate_next_invoice_date(frequency, current)
            dates.append(current)
        return dates

    def test_portal_lists_upcoming_dates_after_an_invoice(self):
        for frequency in ("Monthly", "Quarterly", "Annual"):
            posting = self._leave_schedule_invoiced(frequency)
            shown = payment_dashboard.get_current_dues_schedule(self.member.name)
            dates = payment_dashboard.get_upcoming_dates(shown)
            first = bpc.calculate_next_invoice_date(frequency, posting)
            self.assertEqual(dates, self._chain(frequency, first, 4), frequency)
            # running period from the member's own anchor, not a calendar boundary
            self.assertEqual(dates[0].day, posting.day, frequency)

    def test_api_schedule_lists_future_dates_after_an_invoice(self):
        for frequency in ("Monthly", "Quarterly", "Annual"):
            posting = self._leave_schedule_invoiced(frequency)
            first = bpc.calculate_next_invoice_date(frequency, posting)
            horizon = add_months(first, 12)
            expected = [first]
            while True:
                nxt = bpc.calculate_next_invoice_date(frequency, expected[-1])
                if nxt >= horizon:
                    break
                expected.append(nxt)
            result = get_payment_schedule(self.member.name)
            self.assertTrue(result["success"], msg=result)
            self.assertEqual([getdate(e["date"]) for e in result["data"]], expected, frequency)
            self.assertGreaterEqual(len(expected), 1, frequency)

    def test_member_with_no_invoice_yet_is_unchanged(self):
        """Control: with no invoice the list starts at next_invoice_date, as before."""
        self.schedule.billing_frequency = "Monthly"
        self.schedule.next_invoice_date = add_days(today(), 5)
        self.schedule.last_invoice_date = None
        self.schedule.save()
        self.schedule.reload()
        shown = payment_dashboard.get_current_dues_schedule(self.member.name)
        dates = payment_dashboard.get_upcoming_dates(shown)
        self.assertEqual(dates, self._chain("Monthly", getdate(self.schedule.next_invoice_date), 4))
        api_dates = [getdate(e["date"]) for e in get_payment_schedule(self.member.name)["data"]]
        self.assertEqual(api_dates[0], getdate(self.schedule.next_invoice_date))
