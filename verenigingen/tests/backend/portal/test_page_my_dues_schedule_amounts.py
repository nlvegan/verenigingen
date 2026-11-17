"""
#2612 / #2611: my_dues_schedule page - the Monthly Amount card and the coverage
progress must follow the schedule's real billing_frequency.

Probe shortcut (declared): the member's Active schedule comes from the real
create_test_membership flow, but billing_frequency / dues_rate / custom interval are
then set with db.set_value to put it in each frequency. The page is driven through
its real get_context. Coverage (#2767) is driven through get_coverage_info with real paid invoices whose
coverage dates are then set directly (declared probe shortcut).
"""

import frappe

from verenigingen.tests.backend.portal.test_page_portal_cluster import PortalPageTestBase

RATE = 120.0

# Independent of the code under test: months of coverage one paid invoice buys.
# (billing_frequency, custom_number, custom_unit, monthly amount for RATE, months per invoice)
CASES = [
    ("Monthly", 0, "Days", RATE, 1),
    ("Quarterly", 0, "Days", RATE / 3, 3),
    ("Semi-Annual", 0, "Days", RATE / 6, 6),
    ("Annual", 0, "Days", RATE / 12, 12),
    ("Weekly", 0, "Days", RATE * 52 / 12, 12 / 52),
    ("Daily", 0, "Days", RATE * 365 / 12, 12 / 365),
    ("Custom", 2, "Months", RATE / 2, 2),
]


class TestMyDuesScheduleAmounts(PortalPageTestBase):
    def _member_with_schedule(self, frequency, number, unit):
        member, user = self._make_member_with_user()
        self.create_test_membership(member_name=member.name)
        schedule = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, pluck="name"
        )[0]
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule,
            {
                "billing_frequency": frequency,
                "custom_frequency_number": number,
                "custom_frequency_unit": unit,
                "dues_rate": RATE,
            },
        )
        return member, user

    def _context(self, user):
        from verenigingen.templates.pages import my_dues_schedule

        with self.as_user(user):
            ctx = frappe._dict()
            my_dues_schedule.get_context(ctx)
        return ctx

    def test_monthly_amount_follows_billing_frequency(self):
        for frequency, number, unit, expected, _months in CASES:
            with self.subTest(frequency=frequency):
                _member, user = self._member_with_schedule(frequency, number, unit)
                ctx = self._context(user)
                self.assertAlmostEqual(ctx.current_schedule.monthly_amount, round(expected, 2), places=2)

    def test_custom_without_interval_has_no_monthly_amount(self):
        _member, user = self._member_with_schedule("Custom", 0, "Days")
        ctx = self._context(user)
        self.assertIsNotNone(ctx.current_schedule)
        self.assertIsNone(ctx.current_schedule.monthly_amount)

    def _render(self, user):
        from frappe.website.serve import get_response_content

        with self.as_user(user):
            return get_response_content("my_dues_schedule")

    def _monthly_card(self, html):
        """The text of the Monthly Amount card, so asserts cannot match elsewhere."""
        start = html.index("Monthly Amount")
        return html[start : html.index("</p>", html.index("</p>", start) + 1)]

    def _coverage_card(self, html):
        start = html.index(">Coverage<")
        return html[start : html.index("</p>", html.index("</p>", start) + 1)]

    def test_rendered_page_shows_monthly_amount(self):
        # Annual at RATE: one invoice a year, so RATE / 12 per month.
        _member, user = self._member_with_schedule("Annual", 0, "Days")
        card = self._monthly_card(self._render(user))
        self.assertIn(frappe.format_value(RATE / 12, {"fieldtype": "Currency"}), card)
        self.assertNotIn("--", card)

    def test_rendered_page_shows_nothing_for_custom_without_interval(self):
        _member, user = self._member_with_schedule("Custom", 0, "Days")
        html = self._render(user)
        self.assertIn("--", self._monthly_card(html))
        coverage = self._coverage_card(html)
        self.assertIn("--", coverage)
        self.assertNotIn("%", coverage)

    def _pay_one_invoice(self, member):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        invoice = self.create_test_sales_invoice(member.name)
        if invoice.docstatus == 0:
            invoice.submit()
        entry = get_payment_entry(invoice.doctype, invoice.name)
        entry.reference_no = f"TEST-{invoice.name}"
        entry.reference_date = frappe.utils.today()
        entry.insert()
        entry.submit()
        # Priority 6 releases the Payment Entry before its party (Member 5, Customer 3). At the
        # default tier it is cancelled after the Customer is gone and leaks with "Could not find
        # Party" (the CI leak ratchet caught exactly that on the merge-queue run of #2690).
        self.factory.track_document("Payment Entry", entry.name, priority=6)
        invoice.reload()
        self.assertEqual(invoice.outstanding_amount, 0)

    def _paid_invoice_covering(self, member, start, end, posting_date=None):
        """A real paid invoice, then its coverage ledger set directly (probe shortcut:
        the fields are real, but set with db.set_value instead of by invoice generation)."""
        self._pay_one_invoice(member)
        invoice = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer, "docstatus": 1, "custom_coverage_start_date": ["is", "not set"]},
            pluck="name",
        )[0]
        values = {"custom_coverage_start_date": start, "custom_coverage_end_date": end}
        if posting_date:
            values["posting_date"] = posting_date
        frappe.db.set_value("Sales Invoice", invoice, values)

    @staticmethod
    def _expected_covered_days(periods, as_of):
        """Independent of the code under test: days of the trailing 12 months any period covers."""
        window_start = frappe.utils.add_days(frappe.utils.add_months(as_of, -12), 1)
        days = set()
        for start, end in periods:
            day = max(start, window_start)
            while day <= min(end, as_of):
                days.add(day)
                day = frappe.utils.add_days(day, 1)
        return len(days), (as_of - window_start).days + 1

    def test_running_annual_period_straddling_new_year_shows_its_coverage(self):
        """#2767: a running Annual period that began last year still covers today."""
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        as_of = frappe.utils.getdate(frappe.utils.today())
        start = frappe.utils.getdate(f"{as_of.year - 1}-12-31")
        end = frappe.utils.getdate(f"{as_of.year}-12-30")
        member, user = self._member_with_schedule("Annual", 0, "Days")
        self._paid_invoice_covering(member, start, end, posting_date=start)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        covered, window = self._expected_covered_days([(start, end)], as_of)
        self.assertEqual(info["percentage"], round(covered * 100 / window))
        self.assertGreater(info["percentage"], 0)
        self.assertEqual(info["total_months"], 12)

    def test_invoice_posted_today_for_a_long_past_period_covers_nothing_now(self):
        """Control: the posting date is this year (the old window counted it), the period is not."""
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        as_of = frappe.utils.getdate(frappe.utils.today())
        start = frappe.utils.add_months(as_of, -36)
        end = frappe.utils.add_days(frappe.utils.add_months(start, 12), -1)
        member, user = self._member_with_schedule("Annual", 0, "Days")
        self._paid_invoice_covering(member, start, end)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        self.assertEqual(info["percentage"], 0)
        self.assertEqual(info["covered_months"], 0)

    def test_back_to_back_monthly_periods_are_summed_without_double_counting(self):
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        as_of = frappe.utils.getdate(frappe.utils.today())
        first_start = frappe.utils.add_days(as_of, -45)
        first_end = frappe.utils.add_days(first_start, 29)
        second_start = frappe.utils.add_days(first_end, 1)
        second_end = frappe.utils.add_days(second_start, 29)
        member, user = self._member_with_schedule("Monthly", 0, "Days")
        self._paid_invoice_covering(member, first_start, first_end)
        # Overlaps the first by 5 days: those days must count once.
        self._paid_invoice_covering(member, frappe.utils.add_days(second_start, -5), second_end)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        covered, window = self._expected_covered_days(
            [(first_start, first_end), (frappe.utils.add_days(second_start, -5), second_end)], as_of
        )
        self.assertEqual(info["percentage"], round(covered * 100 / window))
        self.assertEqual(info["covered_months"], round(covered * 12 / window))

    def _submitted_unpaid_invoice_covering(self, member, start, end):
        """A real submitted, UNPAID invoice with its coverage ledger set directly (probe shortcut)."""
        invoice = self.create_test_sales_invoice(member.name)
        if invoice.docstatus == 0:
            invoice.submit()
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {"custom_coverage_start_date": start, "custom_coverage_end_date": end},
        )
        return invoice

    def _current_running_period(self):
        as_of = frappe.utils.getdate(frappe.utils.today())
        start = frappe.utils.add_days(as_of, -30)
        return start, frappe.utils.add_days(frappe.utils.add_months(start, 12), -1)

    def test_an_unpaid_invoice_with_coverage_dates_covers_nothing(self):
        """Control (#2767 review F2): the period is current and the invoice is real, only unpaid."""
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        start, end = self._current_running_period()
        member, user = self._member_with_schedule("Annual", 0, "Days")
        invoice = self._submitted_unpaid_invoice_covering(member, start, end)
        self.assertGreater(invoice.outstanding_amount, 0)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        self.assertEqual(info["percentage"], 0)
        self.assertEqual(info["covered_months"], 0)

    def test_a_credit_noted_unpaid_invoice_covers_nothing(self):
        """Control (#2767 review F2/F1): make_sales_return with update_outstanding_for_self=0
        takes the ORIGINAL to outstanding 0 / "Credit Note Issued" though nobody paid, and the
        return invoice copies the coverage dates. Neither may count."""
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        start, end = self._current_running_period()
        member, user = self._member_with_schedule("Annual", 0, "Days")
        invoice = self._submitted_unpaid_invoice_covering(member, start, end)
        credit_note = make_sales_return(invoice.name)
        credit_note.update_outstanding_for_self = 0
        credit_note.insert()
        credit_note.submit()
        self.factory.track_document("Sales Invoice", credit_note.name, priority=6)
        invoice.reload()
        credit_note.reload()
        self.assertEqual(invoice.outstanding_amount, 0)
        self.assertEqual(invoice.status, "Credit Note Issued")
        self.assertEqual(credit_note.custom_coverage_start_date, start)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        self.assertEqual(info["percentage"], 0)
        self.assertEqual(info["covered_months"], 0)

    def test_custom_schedule_without_interval_returns_none_coverage(self):
        """Direct (#2767 review F3): the unknown-period branch, with a paid current-period invoice
        that WOULD otherwise give a percentage."""
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        start, end = self._current_running_period()
        member, user = self._member_with_schedule("Custom", 0, "Days")
        self._paid_invoice_covering(member, start, end)
        info = get_coverage_info(member.name, self._context(user).current_schedule)
        self.assertIsNone(info["percentage"])
        self.assertIsNone(info["covered_months"])
        self.assertEqual(info["total_months"], 12)
