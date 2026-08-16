# Copyright (c) 2026, Foppe de Haan and Contributors
# See license.txt

"""
Regression tests for issue #350.

``Donation`` has no ``is_submittable`` in its DocType JSON, so a Donation created
by any normal code path stays at ``docstatus = 0`` forever. A whole family of
consumers nevertheless filtered on ``docstatus = 1``, so they aggregated nothing:
ANBI statistics, the Donation Summary report, the donation dashboard, the donor
summary and the campaign totals all reported zero on every deployment.

Every test below creates a Donation exactly the way production does — insert, no
submit — and asserts the consumer actually sees it. Before the fix each of these
is red, because the consumer's ``docstatus = 1`` predicate excludes the row.

``TestDonationQueriesDoNotFilterOnDocstatus`` is the structural gate: it scans
production sources for any Donation query that reintroduces a ``docstatus``
predicate. ``docstatus`` carries no meaning on a non-submittable doctype, so any
such predicate is a bug regardless of which comparison it uses.
"""

import ast
import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase


class DonationDocstatusFilterTestCase(VereningingenTestCase):
    """Shared fixture: one paid, unsubmitted ANBI donation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.mode_of_payment = self._ensure_mode_of_payment()

    def _ensure_mode_of_payment(self, name="Bank Transfer"):
        if not frappe.db.exists("Mode of Payment", name):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = name
            mode.insert()
            self.track_doc("Mode of Payment", mode.name)
        return name

    def _make_donor(self, **kwargs):
        return self.create_test_donor(**kwargs)

    def _make_donation(self, donor, amount, **kwargs):
        """Insert a Donation the way production does: saved, never submitted."""
        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.amount = amount
        donation.donation_date = kwargs.pop("donation_date", today())
        donation.mode_of_payment = self.mode_of_payment
        donation.paid = kwargs.pop("paid", 1)
        for key, value in kwargs.items():
            setattr(donation, key, value)
        # Inserting a Donation enqueues a confirmation email; keep the test off SMTP.
        with patch("frappe.sendmail"):
            donation.insert()
        self.track_doc("Donation", donation.name)
        # The whole point of this suite: nothing submits a Donation.
        self.assertEqual(
            donation.docstatus,
            0,
            "Donation is not submittable — a fixture that submits it cannot prove anything here",
        )
        return donation


class TestANBIOperationsCountUnsubmittedDonations(DonationDocstatusFilterTestCase):
    """verenigingen/api/anbi_operations.py"""

    def test_get_anbi_statistics_counts_an_unsubmitted_donation(self):
        """get_anbi_statistics must include a donation that was never submitted."""
        from verenigingen.api.anbi_operations import get_anbi_statistics

        before = get_anbi_statistics(from_date=today(), to_date=today())
        self.assertTrue(before["success"], f"unexpected failure: {before.get('error')}")
        base_count = before["data"]["statistics"]["total_anbi_donations"]
        base_amount = float(before["data"]["statistics"]["total_anbi_amount"] or 0)

        donor = self._make_donor(donor_name="ANBI Stats Donor")
        self._make_donation(
            donor,
            750.0,
            anbi_agreement_number=f"ANBI-{frappe.generate_hash(length=8)}",
            anbi_agreement_date=today(),
        )

        after = get_anbi_statistics(from_date=today(), to_date=today())
        self.assertTrue(after["success"], f"unexpected failure: {after.get('error')}")
        stats = after["data"]["statistics"]

        self.assertEqual(
            stats["total_anbi_donations"] - base_count,
            1,
            "the unsubmitted ANBI donation was not counted",
        )
        self.assertAlmostEqual(
            float(stats["total_anbi_amount"] or 0) - base_amount,
            750.0,
            places=2,
            msg="the unsubmitted ANBI donation's amount was not summed",
        )

    def test_generate_anbi_report_includes_an_unsubmitted_donation(self):
        """generate_anbi_report must list a donation that was never submitted."""
        from verenigingen.api.anbi_operations import generate_anbi_report

        donor = self._make_donor(donor_name="ANBI Report Donor")
        donation = self._make_donation(
            donor,
            600.0,
            anbi_agreement_number=f"ANBI-{frappe.generate_hash(length=8)}",
            anbi_agreement_date=today(),
        )

        result = generate_anbi_report(from_date=today(), to_date=today())
        self.assertTrue(result["success"], f"unexpected failure: {result.get('error')}")

        reported_ids = [row["donation_id"] for row in result["data"]["donations"]]
        self.assertIn(donation.name, reported_ids, "the unsubmitted ANBI donation is missing from the report")


class TestDonationSummaryReportIncludesUnsubmittedDonations(DonationDocstatusFilterTestCase):
    """verenigingen/verenigingen/report/donation_summary/donation_summary.py"""

    def test_report_aggregates_an_unsubmitted_donation(self):
        from verenigingen.verenigingen.report.donation_summary.donation_summary import get_data

        donor = self._make_donor(donor_name="Summary Report Donor")
        self._make_donation(donor, 400.0)
        self._make_donation(donor, 350.0)

        rows = get_data({"from_date": today(), "to_date": today(), "donor": donor.name})

        self.assertEqual(len(rows), 1, "the donor's unsubmitted donations produced no report row")
        self.assertEqual(rows[0]["donor"], donor.name)
        self.assertEqual(rows[0]["donation_count"], 2)
        self.assertAlmostEqual(float(rows[0]["total_donations"]), 750.0, places=2)


class TestDonationServicesCountUnsubmittedDonations(DonationDocstatusFilterTestCase):
    """verenigingen/services/donation/*.py"""

    def test_donor_summary_counts_an_unsubmitted_donation(self):
        """donor_service.get_donor_donation_summary — line 354."""
        from verenigingen.services.donation.donor_service import get_donation_donor_service

        donor = self._make_donor(donor_name="Donor Summary Donor")
        self._make_donation(donor, 125.0)

        # The service takes a Donation as its constructor arg but reads only the
        # donor_name argument here; an in-memory doc is enough.
        service = get_donation_donor_service(frappe.new_doc("Donation"))
        summary = service.get_donor_donation_summary(donor.name)

        self.assertEqual(summary["total_donations"], 1, "the unsubmitted donation was not counted")
        self.assertEqual(summary["paid_donations"], 1)
        self.assertAlmostEqual(float(summary["total_amount"]), 125.0, places=2)

    def test_summary_by_purpose_counts_an_unsubmitted_donation(self):
        """reporting_service.get_donation_summary_by_purpose — line 199."""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        service = DonationReportingService()
        before = service.get_donation_summary_by_purpose(from_date=today(), to_date=today())
        base_count = before["General"]["count"]
        base_total = float(before["General"]["total"])

        donor = self._make_donor(donor_name="Purpose Summary Donor")
        self._make_donation(donor, 275.0, donation_purpose_type="General")

        after = service.get_donation_summary_by_purpose(from_date=today(), to_date=today())

        self.assertEqual(
            after["General"]["count"] - base_count, 1, "the unsubmitted donation was not counted"
        )
        self.assertAlmostEqual(float(after["General"]["total"]) - base_total, 275.0, places=2)

    def test_allocation_report_includes_an_unsubmitted_donation(self):
        """reporting_service.create_donation_allocation_report — lines 328/354."""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        donor = self._make_donor(donor_name="Allocation Report Donor")
        donation = self._make_donation(donor, 90.0)

        report = DonationReportingService().create_donation_allocation_report(
            from_date=today(), to_date=today()
        )

        names = [row["name"] for row in report["donations"]]
        self.assertIn(donation.name, names, "the unsubmitted donation is missing from the allocation report")

    def test_reconciliation_counts_an_unsubmitted_donation(self):
        """financial_service.reconcile_donation_accounts — line 171."""
        from verenigingen.services.donation.financial_service import DonationFinancialService

        service = DonationFinancialService()
        base_total = float(service.reconcile_donation_accounts()["total_donations"])

        donor = self._make_donor(donor_name="Reconcile Donor")
        self._make_donation(donor, 310.0)

        after_total = float(service.reconcile_donation_accounts()["total_donations"])

        self.assertAlmostEqual(
            after_total - base_total,
            310.0,
            places=2,
            msg="the unsubmitted donation was not reconciled",
        )


class TestDonationDashboardCountsUnsubmittedDonations(DonationDocstatusFilterTestCase):
    """verenigingen/services/donation/dashboard_service.py"""

    def _year_bounds(self):
        year = getdate(today()).year
        return f"{year}-01-01", f"{year}-12-31"

    def test_year_to_date_stats_count_an_unsubmitted_donation(self):
        from verenigingen.services.donation.dashboard_service import DonationDashboardService

        service = DonationDashboardService()
        year_start, year_end = self._year_bounds()
        before = service._get_year_to_date_stats(year_start, year_end)

        donor = self._make_donor(donor_name="Dashboard YTD Donor")
        self._make_donation(donor, 220.0)

        after = service._get_year_to_date_stats(year_start, year_end)

        self.assertEqual(
            after["total_donations_count"] - before["total_donations_count"],
            1,
            "the unsubmitted donation is missing from the year-to-date dashboard stats",
        )
        self.assertAlmostEqual(
            after["total_donations_amount"] - before["total_donations_amount"], 220.0, places=2
        )

    def test_recent_donations_include_an_unsubmitted_donation(self):
        from verenigingen.services.donation.dashboard_service import DonationDashboardService

        donor = self._make_donor(donor_name="Dashboard Recent Donor")
        donation = self._make_donation(donor, 180.0)

        recent = DonationDashboardService()._get_recent_donations()

        self.assertIn(
            donation.name,
            [row["name"] for row in recent],
            "the unsubmitted donation is missing from the dashboard's recent donations",
        )


class TestDonationQueriesDoNotFilterOnDocstatus(VereningingenTestCase):
    """Structural gate for issue #350.

    ``Donation`` is not submittable, so ``docstatus`` is always 0 and carries no
    information. Any query predicate on it silently discards real donations. This
    scans production sources (tests and one-off debug scripts excluded) for both
    shapes the codebase uses: a raw-SQL ``tabDonation`` statement mentioning
    ``docstatus``, and an ORM call on "Donation" whose ``filters`` carry a
    ``docstatus`` key.
    """

    ORM_QUERY_FUNCS = {"get_all", "get_list", "count", "exists", "get_value", "get_values", "delete"}

    @classmethod
    def _app_root(cls):
        import verenigingen

        return Path(verenigingen.__file__).parent

    @classmethod
    def _production_sources(cls):
        root = cls._app_root()
        skipped_dirs = {"tests", "node_modules", "__pycache__"}
        for path in root.rglob("*.py"):
            parts = set(path.relative_to(root).parts)
            if parts & skipped_dirs:
                continue
            if path.name.startswith("test_") or path.name.startswith("debug_"):
                continue
            yield path

    def _sql_offenders(self, tree, path):
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            sql = node.value
            if "tabDonation`" not in sql:
                continue
            if re.search(r"\bdocstatus\b", sql):
                offenders.append(f"{path}:{node.lineno} raw SQL on `tabDonation` filters on docstatus")
        return offenders

    def _orm_offenders(self, tree, path):
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in self.ORM_QUERY_FUNCS:
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "Donation"):
                continue
            filters = [a for a in node.args[1:]] + [kw.value for kw in node.keywords if kw.arg == "filters"]
            for candidate in filters:
                if isinstance(candidate, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "docstatus" for k in candidate.keys
                ):
                    offenders.append(
                        f"{path}:{node.lineno} frappe.{node.func.attr}('Donation', ...) filters on docstatus"
                    )
        return offenders

    def test_no_production_donation_query_filters_on_docstatus(self):
        offenders = []
        scanned = 0
        for path in self._production_sources():
            source = path.read_text(encoding="utf-8")
            if "Donation" not in source:
                continue
            scanned += 1
            tree = ast.parse(source, filename=str(path))
            offenders.extend(self._sql_offenders(tree, path))
            offenders.extend(self._orm_offenders(tree, path))

        # Control: the scanner must actually be looking at files, otherwise an
        # empty offender list would prove nothing.
        self.assertGreater(scanned, 20, "the scan found almost no Donation sources — it is not running")
        self.assertEqual(
            offenders,
            [],
            "Donation is not submittable; these docstatus predicates are dead:\n"
            + "\n".join(offenders),
        )

    def test_the_scanner_detects_a_reintroduced_docstatus_filter(self):
        """Control for the gate above: a planted offender must be reported.

        Without this, a scanner that matched nothing at all would look identical
        to a clean codebase.
        """
        planted = ast.parse(
            'frappe.get_all("Donation", filters={"docstatus": 1})\n'
            'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus = 1")\n'
        )
        offenders = self._orm_offenders(planted, "planted.py") + self._sql_offenders(planted, "planted.py")
        self.assertEqual(len(offenders), 2, f"the scanner missed a planted offender: {offenders}")
