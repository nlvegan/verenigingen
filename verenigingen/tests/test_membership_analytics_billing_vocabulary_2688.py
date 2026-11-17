"""
#2688: the ungenerated-dues estimate in membership_analytics must price EVERY real
Membership Dues Schedule billing_frequency option and EVERY custom_frequency_unit.

It tested 'Yearly' (not an option) and singular units ('Month'), so Annual,
Semi-Annual, Weekly, Daily and every Custom row priced to 0.

Probe shortcut (declared): members and schedules come from the real
create_test_member / create_test_membership flow, then billing_frequency, the custom
interval and the member's dues_rate are set with db.set_value to put each schedule in
each frequency. The query itself is the real one, run through get_current_year_revenue.
The expected figure is computed here from each member's own persisted member_since and
an independent periods-per-year table, not from the code under test; the option list is
read from the DocType so a new option cannot be forgotten silently.
"""

import frappe
from frappe.utils import date_diff, getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.page.membership_analytics.membership_analytics import (
    get_current_year_revenue,
)

RATE = 120.0
CUSTOM_NUMBER = 2

# Independent of the code under test: invoices per year for one period of each option.
PERIODS_PER_YEAR = {
    "Annual": 1,
    "Semi-Annual": 2,
    "Quarterly": 4,
    "Monthly": 12,
    "Weekly": 52,
    "Daily": 365,
}
UNITS_PER_YEAR = {"Days": 365, "Weeks": 52, "Months": 12, "Years": 1}


def _doctype_options(fieldname):
    meta = frappe.get_meta("Membership Dues Schedule")
    return [o for o in meta.get_field(fieldname).options.split("\n") if o]


def _cases():
    cases = [(f, None, PERIODS_PER_YEAR[f]) for f in _doctype_options("billing_frequency") if f != "Custom"]
    cases += [("Custom", u, UNITS_PER_YEAR[u] / CUSTOM_NUMBER) for u in _doctype_options("custom_frequency_unit")]
    return cases


class TestMembershipAnalyticsBillingVocabulary2688(EnhancedTestCase):
    def _ungenerated(self, year):
        return get_current_year_revenue(year)["breakdown"]["ungenerated_dues"]

    def _member_in(self, frequency, unit):
        member = self.create_test_member(
            first_name="Vocab",
            last_name=f"T{frappe.generate_hash(length=6)}",
            birth_date="1990-01-01",
        )
        self.create_test_membership(member_name=member.name)
        schedule = frappe.get_all(
            "Membership Dues Schedule", filters={"member": member.name, "status": "Active"}, pluck="name"
        )[0]
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule,
            {
                "billing_frequency": frequency,
                "custom_frequency_number": CUSTOM_NUMBER if frequency == "Custom" else 0,
                "custom_frequency_unit": unit or "Days",
            },
        )
        frappe.db.set_value("Member", member.name, "dues_rate", RATE)
        return member.name

    def _expected(self, member_name, per_year, year):
        member_since = getdate(frappe.db.get_value("Member", member_name, "member_since"))
        start = max(member_since, getdate(f"{year}-01-01"))
        days_left = date_diff(f"{year}-12-31", start)
        days_in_year = date_diff(f"{year}-12-31", f"{year}-01-01") + 1
        return RATE * per_year * days_left / days_in_year

    def test_every_billing_frequency_and_custom_unit_is_priced(self):
        year = now_datetime().year
        cases = _cases()
        # control: the option lists really contain what this test claims to cover
        self.assertGreaterEqual(len(cases), 10)
        baseline = self._ungenerated(year)
        for frequency, unit, per_year in cases:
            with self.subTest(frequency=frequency, unit=unit):
                member_name = self._member_in(frequency, unit)
                self.assertFalse(
                    frappe.db.exists(
                        "Sales Invoice", {"member": member_name, "docstatus": 1}
                    ),
                    "fixture must have no invoices, so no coverage gap is subtracted",
                )
                expected = self._expected(member_name, per_year, year)
                self.assertGreater(expected, 0, "member_since must leave days to estimate")
                after = self._ungenerated(year)
                self.assertAlmostEqual(after - baseline, expected, delta=0.05)
                baseline = after
