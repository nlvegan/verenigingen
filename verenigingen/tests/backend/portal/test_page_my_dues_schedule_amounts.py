"""
#2612 / #2611: my_dues_schedule page - the Monthly Amount card and the coverage
progress must follow the schedule's real billing_frequency.

Probe shortcut (declared): the member's Active schedule comes from the real
create_test_membership flow, but billing_frequency / dues_rate / custom interval are
then set with db.set_value to put it in each frequency. The page is driven through
its real get_context. The coverage arithmetic is driven through coverage_from_paid_count with a
chosen paid-invoice count, so no real invoices are needed.
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

    def test_coverage_months_per_invoice_follows_billing_frequency(self):
        from verenigingen.templates.pages.my_dues_schedule import coverage_from_paid_count

        for frequency, number, unit, _amount, months in CASES:
            with self.subTest(frequency=frequency):
                _member, user = self._member_with_schedule(frequency, number, unit)
                schedule = self._context(user).current_schedule
                info = coverage_from_paid_count(schedule, 1)
                self.assertEqual(info["covered_months"], min(round(months), 12))
                self.assertEqual(info["percentage"], round(info["covered_months"] / 12 * 100))

    def test_coverage_is_capped_at_twelve_months(self):
        from verenigingen.templates.pages.my_dues_schedule import coverage_from_paid_count

        _member, user = self._member_with_schedule("Annual", 0, "Days")
        schedule = self._context(user).current_schedule
        info = coverage_from_paid_count(schedule, 5)
        self.assertEqual(info["covered_months"], 12)
        self.assertEqual(info["percentage"], 100)

    def test_coverage_unknown_for_custom_without_interval(self):
        from verenigingen.templates.pages.my_dues_schedule import coverage_from_paid_count

        _member, user = self._member_with_schedule("Custom", 0, "Days")
        schedule = self._context(user).current_schedule
        info = coverage_from_paid_count(schedule, 3)
        self.assertIsNone(info["percentage"])
        self.assertIsNone(info["covered_months"])

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

    def test_get_coverage_info_counts_a_real_paid_invoice(self):
        """SQL path: one real submitted, fully paid invoice covers one billing period."""
        from verenigingen.templates.pages.my_dues_schedule import get_coverage_info

        for frequency, months in (("Annual", 12), ("Monthly", 1)):
            with self.subTest(frequency=frequency):
                member, user = self._member_with_schedule(frequency, 0, "Days")
                self._pay_one_invoice(member)
                schedule = self._context(user).current_schedule
                info = get_coverage_info(member.name, schedule)
                self.assertEqual(info["covered_months"], months)
