"""
Real-integration coverage for
``verenigingen/services/volunteer/volunteer_statistics.py``.

Two public functions:
  * ``get_volunteer_expense_statistics(volunteer_name, months_back=12)`` --
    aggregates native Expense Claims via the volunteer's linked Employee.
  * ``get_volunteer_expense_summary(volunteer_name)`` -- wraps the above and
    adds a ``recent_count`` (last month).

Both wrap their bodies in ``try/except`` -> ``frappe.log_error`` -> return the
empty/zero shape, so a "did not raise" smoke test cannot fail. Hardening
(mirroring tests/events/test_team_events_coverage.py):

1. ``self.assertNoErrorLog()`` around every happy/no-op path so a swallowed
   exception (which would silently return zeros) becomes a real failure.
2. Real arithmetic assertions against a KNOWN fixture of Expense Claims: a
   submitted+Paid claim, a draft claim, and a date-window-excluded claim --
   asserting the exact aggregate totals/counts, not merely "returned a dict".
3. The error branch is exercised honestly via a non-existent volunteer
   (``frappe.get_doc`` raises DoesNotExistError inside the try) and asserted to
   return the empty shape AND to log the documented error title.

No business logic is mocked.
"""

import frappe
from frappe.utils import add_months, today

from verenigingen.services.volunteer.volunteer_statistics import (
    _get_empty_statistics,
    get_volunteer_expense_statistics,
    get_volunteer_expense_summary,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

EMPTY_KEYS = {
    "total_submitted",
    "total_approved",
    "pending_amount",
    "pending_count",
    "approved_count",
    "total_count",
}


class TestVolunteerStatisticsCoverage(EnhancedTestCase):
    """Real integration coverage for volunteer expense statistics."""

    # ------------------------------------------------------------------ helpers
    def _company(self):
        return (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )

    def _accounts(self, company):
        expense_acct = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        return expense_acct, payable

    def _make_volunteer_with_employee(self, prefix="stats"):
        """Member + Volunteer linked to a real Employee."""
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        member = self.create_test_member(
            first_name="Stat", last_name=prefix.title(), birth_date="1990-01-01"
        )
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Stat{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        # ISOLATION: Employee uses a sequential autoname (HR-EMP-#####). On this
        # bench the next-assigned name can collide with STALE/orphaned Expense
        # Claims left by prior data whose employee was deleted -- they'd leak
        # into this volunteer's aggregates. The employee was just inserted, so
        # any Expense Claim already referencing its name is a pre-existing orphan
        # and is safe to purge for a clean per-test baseline.
        self._purge_orphan_claims(emp.name)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        volunteer.reload()
        return volunteer, emp, company

    def _purge_orphan_claims(self, employee_name):
        """Delete any Expense Claims already attached to a freshly-created
        Employee name (stale rows from sequential-autoname reuse)."""
        orphans = frappe.get_all("Expense Claim", filters={"employee": employee_name}, pluck="name")
        for ec_name in orphans:
            # Force docstatus to 0 so a (stale) submitted row can be deleted.
            frappe.db.set_value("Expense Claim", ec_name, "docstatus", 0, update_modified=False)
            frappe.delete_doc("Expense Claim", ec_name, force=True, ignore_permissions=True)

    def _make_claim(
        self, emp, company, *, claimed, sanctioned, status, docstatus=0, posting_date=None
    ):
        """Insert an Expense Claim with explicit totals/status/docstatus.

        docstatus + status are set directly (set_value) because the statistics
        SQL reads those COLUMN values; this avoids the approver submission
        workflow while still exercising the real aggregation code path.
        """
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        posting_date = posting_date or today()
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": emp.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": posting_date,
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": claimed,
                        "sanctioned_amount": sanctioned,
                        "expense_date": posting_date,
                        "default_account": expense_acct,
                    }
                ],
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Expense Claim", ec.name, priority=1)
        # Pin the totals + status/docstatus columns to exact values.
        frappe.db.set_value(
            "Expense Claim",
            ec.name,
            {
                "total_claimed_amount": claimed,
                "total_sanctioned_amount": sanctioned,
                "status": status,
                "docstatus": docstatus,
            },
            update_modified=False,
        )
        return ec

    # ============================================================ _get_empty_statistics
    def test_empty_statistics_shape(self):
        stats = _get_empty_statistics()
        self.assertEqual(set(stats.keys()), EMPTY_KEYS)
        self.assertTrue(all(v == 0 for v in stats.values()))

    # ============================================================ no employee linked
    def test_statistics_no_employee_returns_empty(self):
        """A volunteer with no employee_id short-circuits to the empty shape."""
        member = self.create_test_member(first_name="NoEmp", last_name="Vol", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        self.assertFalse(volunteer.employee_id)

        with self.assertNoErrorLog():
            stats = get_volunteer_expense_statistics(volunteer.name)
        self.assertEqual(stats, _get_empty_statistics())

    def test_statistics_employee_no_claims_returns_zeros(self):
        """Linked employee with zero claims -> all aggregates zero, total_count 0."""
        volunteer, _emp, _company = self._make_volunteer_with_employee("noclaims")
        with self.assertNoErrorLog():
            stats = get_volunteer_expense_statistics(volunteer.name)
        self.assertEqual(stats["total_count"], 0)
        self.assertEqual(stats["total_submitted"], 0)
        self.assertEqual(stats["total_approved"], 0)
        self.assertEqual(stats["pending_count"], 0)
        self.assertEqual(stats["approved_count"], 0)

    # ============================================================ real aggregation
    def test_statistics_aggregates_known_fixture(self):
        """Exact aggregation over a KNOWN mix of claims.

        Fixture (all within the 12-month window unless noted):
          A: submitted (docstatus 1) + Paid,  claimed 100, sanctioned 90 -> APPROVED
          B: draft     (docstatus 0) + Draft, claimed  40, sanctioned  0 -> PENDING
          C: submitted (docstatus 1) + Approved, claimed 30, sanctioned 30 -> APPROVED
          D: dated 18 months ago -> EXCLUDED by the from_date filter entirely
        Expected: total_count=3, total_submitted=170, total_approved=120,
                  approved_count=2, pending_count=1, pending_amount=50.
        """
        volunteer, emp, company = self._make_volunteer_with_employee("agg")

        self._make_claim(emp, company, claimed=100, sanctioned=90, status="Paid", docstatus=1)
        self._make_claim(emp, company, claimed=40, sanctioned=0, status="Draft", docstatus=0)
        self._make_claim(emp, company, claimed=30, sanctioned=30, status="Approved", docstatus=1)
        # Out-of-window claim must NOT be counted.
        self._make_claim(
            emp,
            company,
            claimed=999,
            sanctioned=999,
            status="Paid",
            docstatus=1,
            posting_date=add_months(today(), -18),
        )

        with self.assertNoErrorLog():
            stats = get_volunteer_expense_statistics(volunteer.name)

        self.assertEqual(stats["total_count"], 3, "out-of-window claim must be excluded")
        self.assertEqual(stats["total_submitted"], 170.0)
        self.assertEqual(stats["total_approved"], 120.0)
        self.assertEqual(stats["approved_count"], 2)
        self.assertEqual(stats["pending_count"], 1)
        self.assertEqual(stats["pending_amount"], 50.0)

    def test_statistics_months_back_window(self):
        """months_back narrows the window: a 6-month-old claim is excluded when
        months_back=3 but included at the default 12."""
        volunteer, emp, company = self._make_volunteer_with_employee("window")
        self._make_claim(
            emp,
            company,
            claimed=50,
            sanctioned=50,
            status="Paid",
            docstatus=1,
            posting_date=add_months(today(), -6),
        )

        with self.assertNoErrorLog():
            narrow = get_volunteer_expense_statistics(volunteer.name, months_back=3)
            wide = get_volunteer_expense_statistics(volunteer.name, months_back=12)
        self.assertEqual(narrow["total_count"], 0, "6-month-old claim excluded by months_back=3")
        self.assertEqual(wide["total_count"], 1, "6-month-old claim included by months_back=12")

    # ============================================================ error branch
    def test_statistics_nonexistent_volunteer_logs_and_returns_empty(self):
        """A non-existent volunteer makes frappe.get_doc raise inside the try;
        the function logs the documented title and returns the empty shape."""
        self.expectErrorLog("Volunteer Expense Statistics Error")
        before = frappe.db.count("Error Log")
        stats = get_volunteer_expense_statistics("NONEXISTENT-VOL-STATS-999")
        self.assertEqual(stats, _get_empty_statistics())
        self.assertGreater(
            frappe.db.count("Error Log"), before, "the swallowed lookup failure must be logged"
        )

    # ============================================================ summary wrapper
    def test_summary_adds_recent_count_zero_without_claims(self):
        """Summary mirrors statistics and adds recent_count=0 with no claims."""
        volunteer, _emp, _company = self._make_volunteer_with_employee("sum0")
        with self.assertNoErrorLog():
            summary = get_volunteer_expense_summary(volunteer.name)
        self.assertIn("recent_count", summary)
        self.assertEqual(summary["recent_count"], 0)
        # And it still carries the standard statistics keys.
        self.assertTrue(EMPTY_KEYS.issubset(summary.keys()))

    def test_summary_recent_count_counts_last_month_only(self):
        """recent_count counts claims within the last month; an older (but still
        within the 12-month stats window) claim is NOT recent."""
        volunteer, emp, company = self._make_volunteer_with_employee("sumrecent")
        # Recent claim (today) -> counted in recent_count.
        self._make_claim(emp, company, claimed=20, sanctioned=20, status="Paid", docstatus=1)
        # Two-months-old claim -> in the 12-month stats window but NOT recent.
        self._make_claim(
            emp,
            company,
            claimed=15,
            sanctioned=15,
            status="Paid",
            docstatus=1,
            posting_date=add_months(today(), -2),
        )

        with self.assertNoErrorLog():
            summary = get_volunteer_expense_summary(volunteer.name)

        self.assertEqual(summary["total_count"], 2, "both claims are within the 12-month stats window")
        self.assertEqual(summary["recent_count"], 1, "only the last-month claim is recent")

    def test_summary_no_employee_recent_count_zero(self):
        """No employee_id -> stats empty AND recent_count short-circuits to 0."""
        member = self.create_test_member(first_name="SumNoEmp", last_name="Vol", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        with self.assertNoErrorLog():
            summary = get_volunteer_expense_summary(volunteer.name)
        self.assertEqual(summary["recent_count"], 0)
        self.assertEqual(summary["total_count"], 0)

    def test_summary_nonexistent_volunteer_logs_and_returns_zeros(self):
        """Non-existent volunteer: statistics logs its error, then the summary's
        own get_doc raises -> recent-count error logged too; result is all zeros
        with recent_count=0."""
        self.expectErrorLog("Volunteer Expense Statistics Error")
        self.expectErrorLog("Recent Expense Count Error")
        summary = get_volunteer_expense_summary("NONEXISTENT-VOL-SUMMARY-999")
        self.assertEqual(summary["recent_count"], 0)
        self.assertEqual(summary["total_count"], 0)
