"""#946: get_join_year_segmentation computed avg_tenure_days from the DATABASE clock
(pypika ``DateDiff(CurDate(), ...)``). Every other window in this class was moved to
the SITE clock by #908; this one was invisible to its line-regex validator.

Fault injection (declared): the site clock is replaced by patching the module's
``today`` to a date far from the database's real CURDATE(), so the two clocks
disagree by construction. Members come from the real create_test_member flow;
``member_since`` is then set with db.set_value (probe shortcut) to put two members
in a join year no other fixture uses. The expected figure is computed here with
frappe.utils.date_diff from each member's persisted member_since.
"""

from unittest import mock

import frappe
from frappe.utils import add_days, date_diff, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.page.membership_analytics import membership_analytics

JOIN_YEAR = 1951
SINCE_DATES = ("1951-03-01", "1951-09-15")


class TestJoinYearSegmentationSiteClock946(EnhancedTestCase):
    def _members_since_1951(self):
        names = []
        for since in SINCE_DATES:
            member = self.create_test_member(
                first_name="Tenure", last_name=f"T{frappe.generate_hash(length=6)}", birth_date="1930-01-01"
            )
            frappe.db.set_value("Member", member.name, "member_since", since, update_modified=False)
            names.append(member.name)
        return names

    def _row(self, site_today):
        with mock.patch.object(membership_analytics, "today", return_value=site_today):
            rows = membership_analytics.get_join_year_segmentation(JOIN_YEAR, "")
        return next(r for r in rows if int(r["name"]) == JOIN_YEAR)

    def test_avg_tenure_days_is_measured_to_the_site_clock(self):
        self._members_since_1951()
        site_today = add_days(today(), 4000)  # the DB clock cannot be 4000 days ahead
        expected = sum(date_diff(site_today, s) for s in SINCE_DATES) / len(SINCE_DATES)
        row = self._row(site_today)
        self.assertEqual(row["total_members"], len(SINCE_DATES), "no other fixture may share the join year")
        self.assertAlmostEqual(float(row["avg_tenure_days"]), expected, delta=0.5)

    def test_control_the_result_follows_the_clock_it_is_given(self):
        """A different site date gives a different answer, so the test above cannot pass
        on a constant."""
        self._members_since_1951()
        early = float(self._row(add_days(today(), 4000))["avg_tenure_days"])
        late = float(self._row(add_days(today(), 4100))["avg_tenure_days"])
        self.assertAlmostEqual(late - early, 100, delta=0.5)
