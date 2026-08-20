# Copyright (c) 2026, Foppe de Haan and Contributors
# See license.txt

"""
Regression tests for issue #350: the docstatus predicate on Donation queries.

``Donation`` has no ``is_submittable`` in its DocType JSON, so a donation created
by any normal code path stays at ``docstatus = 0`` forever. A whole family of
consumers nevertheless filtered on ``docstatus = 1``, so they aggregated nothing:
ANBI statistics, the Donation Summary report, the donation dashboard, the donor
summary and the campaign totals all reported zero on every deployment.

The correct predicate is ``docstatus < 2``, **not** removal. Frappe's
``Document._submit()`` / ``._cancel()`` carry no ``is_submittable`` guard, so
both docstatus 1 and docstatus 2 rows exist in the wild — the live site has one
of each family — and a cancelled donation must never land in a Belastingdienst
figure or a GL reconciliation.

Every behavioural test therefore builds **two** donations, one live and one
cancelled, and asserts the consumer counts exactly the live one. That makes each
test fail under both mutations: reinstating ``= 1`` drops the live donation, and
deleting the predicate admits the cancelled one.

Donations are created the way production creates them — insert, never submit.
The tests deliberately avoid ``EnhancedTestCase.create_test_donation``, which
force-sets ``docstatus = 1`` via ``frappe.db.set_value``; that fixture
manufactures a state production cannot reach and is why this bug class stayed
invisible to the suite.

``TestDonationQueriesUseTheCorrectDocstatusPredicate`` is the structural gate,
covering the call sites that have no behavioural test of their own.
"""

import ast
import re
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_years, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase

# --------------------------------------------------------------------------- #
# Scanner (shared by the structural gate and its planted-shape control)
# --------------------------------------------------------------------------- #

DONATION_DOCTYPES = {"Donation", "Periodic Donation Agreement"}
DONATION_TABLES = ("tabDonation", "tabPeriodic Donation Agreement")
ORM_QUERY_FUNCS = {"get_all", "get_list", "count", "exists", "get_value", "get_values", "delete"}

# A predicate that excludes docstatus 0. "< 2", "!= 2", "<= 1" and "in (0, 1)"
# all admit drafts and are correct; only equality with 1 is the #350 bug.
_SQL_BAD_PREDICATE = re.compile(r"docstatus\s*(?:=|==)\s*1\b", re.IGNORECASE)


class DonationQueryScanner:
    """Find Donation/PDA queries whose docstatus predicate excludes docstatus 0.

    Deliberately conservative about *attribution*: a site is only reported when
    the doctype can be tied to the query (the SQL names the table, the ORM call's
    first argument resolves to the doctype, or a query-builder alias resolves to
    it). Shapes it cannot attribute are listed in the gate's docstring rather
    than guessed at, because a gate that guesses fails the build on innocent code.
    """

    def __init__(self, tree, path):
        self.path = path
        self.tree = tree
        self.offenders = []
        # name -> value node, for simple `x = <literal>` in module or function scope
        self.bindings = {}
        self.qb_aliases = set()

    # -- resolution helpers -------------------------------------------------
    def _collect_bindings(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            self.bindings.setdefault(target.id, node.value)
            # frappe.qb aliases: Donation = DocType("Donation") / frappe.qb.DocType(...)
            doctype_name = self._doctype_of_call(node.value)
            if doctype_name in DONATION_DOCTYPES:
                self.qb_aliases.add(target.id)

    @staticmethod
    def _doctype_of_call(node):
        if not isinstance(node, ast.Call):
            return None
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != "DocType" or not node.args:
            return None
        first = node.args[0]
        return first.value if isinstance(first, ast.Constant) else None

    def _resolve(self, node, seen=None):
        """Follow a Name back to the literal it was last assigned, once."""
        seen = seen or set()
        if isinstance(node, ast.Name) and node.id in self.bindings and node.id not in seen:
            seen.add(node.id)
            return self._resolve(self.bindings[node.id], seen)
        return node

    def _text_of(self, node, seen=None):
        """Flatten a string expression: constants, f-strings, `+` concatenation."""
        node = self._resolve(node, seen)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            # FormattedValue placeholders become a neutral token so that a
            # predicate split across an interpolation still reads as one string.
            return "".join(
                part.value if isinstance(part, ast.Constant) else " ? " for part in node.values
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._text_of(node.left, seen) + self._text_of(node.right, seen)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # "...".format(...) — the template is what carries the predicate.
            if node.func.attr == "format":
                return self._text_of(node.func.value, seen)
        return ""

    # -- predicate classification -------------------------------------------
    @staticmethod
    def _value_excludes_drafts(value):
        """True when an ORM filter value on docstatus excludes docstatus 0."""
        if isinstance(value, ast.Constant) and value.value == 1:
            return True
        if isinstance(value, (ast.List, ast.Tuple)) and len(value.elts) == 2:
            op, operand = value.elts
            op_is_eq = isinstance(op, ast.Constant) and op.value in ("=", "==")
            operand_is_one = isinstance(operand, ast.Constant) and operand.value == 1
            return op_is_eq and operand_is_one
        return False

    def _filters_offend(self, node):
        node = self._resolve(node)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "docstatus":
                    if self._value_excludes_drafts(self._resolve(value)):
                        return True
        if isinstance(node, (ast.List, ast.Tuple)):
            for element in node.elts:
                element = self._resolve(element)
                if not isinstance(element, (ast.List, ast.Tuple)):
                    continue
                parts = [e.value if isinstance(e, ast.Constant) else None for e in element.elts]
                # ["docstatus", "=", 1] or ["Donation", "docstatus", "=", 1]
                if "docstatus" in parts:
                    tail = parts[parts.index("docstatus") + 1 :]
                    if len(tail) >= 2 and tail[0] in ("=", "==") and tail[1] == 1:
                        return True
        return False

    # -- the three attributable shapes --------------------------------------
    def _scan_sql(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                continue
            if isinstance(node, ast.Constant) and not isinstance(node.value, str):
                continue
            text = self._text_of(node)
            if not any(table in text for table in DONATION_TABLES):
                continue
            if _SQL_BAD_PREDICATE.search(text):
                self._report(node, "raw SQL selects a Donation table with docstatus = 1")

    def _scan_orm(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ORM_QUERY_FUNCS or not node.args:
                continue
            first = self._resolve(node.args[0])
            if not (isinstance(first, ast.Constant) and first.value in DONATION_DOCTYPES):
                continue
            candidates = list(node.args[1:]) + [kw.value for kw in node.keywords if kw.arg == "filters"]
            if any(self._filters_offend(candidate) for candidate in candidates):
                self._report(node, f"frappe.{node.func.attr}('{first.value}', ...) filters docstatus = 1")

    def _scan_query_builder(self):
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                continue
            if not isinstance(node.ops[0], ast.Eq):
                continue
            left = node.left
            if not (isinstance(left, ast.Attribute) and left.attr == "docstatus"):
                continue
            if not (isinstance(left.value, ast.Name) and left.value.id in self.qb_aliases):
                continue
            right = node.comparators[0]
            if isinstance(right, ast.Constant) and right.value == 1:
                self._report(node, "frappe.qb query on a Donation doctype compares docstatus == 1")

    def _report(self, node, why):
        self.offenders.append(f"{self.path}:{node.lineno} {why}")

    def run(self):
        self._collect_bindings()
        self._scan_sql()
        self._scan_orm()
        self._scan_query_builder()
        return self.offenders


def scan_source(source, path="<planted>"):
    return DonationQueryScanner(ast.parse(source), path).run()


# --------------------------------------------------------------------------- #
# Behavioural tests
# --------------------------------------------------------------------------- #


class DonationDocstatusFilterTestCase(VereningingenTestCase):
    """Builds one live and one cancelled donation per scenario."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.mode_of_payment = self._existing_mode_of_payment()

    @staticmethod
    def _existing_mode_of_payment():
        """Reuse a Mode of Payment; never create one.

        Mode of Payment is shared master data — creating it from inside a test
        would hand it to the cleanup drain and break every later class in the
        shard (see the shared-fixture note in CLAUDE.md).
        """
        if frappe.db.exists("Mode of Payment", "Bank Transfer"):
            return "Bank Transfer"
        existing = frappe.db.get_value("Mode of Payment", {}, "name")
        if not existing:
            raise AssertionError("no Mode of Payment on this site; cannot build a Donation fixture")
        return existing

    def _make_donor(self, **kwargs):
        return self.create_test_donor(**kwargs)

    def _make_donation(self, donor, amount, cancelled=False, **kwargs):
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
        self.assertEqual(
            donation.docstatus, 0, "Donation is not submittable — the fixture must not submit it"
        )
        if cancelled:
            # Donation is not submittable, so .cancel() is not a supported route;
            # this is exactly how a docstatus-2 Donation comes into existence.
            frappe.db.set_value("Donation", donation.name, "docstatus", 2, update_modified=False)
            donation.reload()
            self.assertEqual(donation.docstatus, 2)
        return donation

    def _live_and_cancelled(self, donor, live_amount, cancelled_amount, **kwargs):
        live = self._make_donation(donor, live_amount, **kwargs)
        cancelled = self._make_donation(donor, cancelled_amount, cancelled=True, **kwargs)
        return live, cancelled


class TestANBIOperationsDocstatusPredicate(DonationDocstatusFilterTestCase):
    """verenigingen/api/anbi_operations.py"""

    def _anbi_kwargs(self):
        return {
            "anbi_agreement_number": f"ANBI-{frappe.generate_hash(length=8)}",
            "anbi_agreement_date": today(),
        }

    def test_statistics_count_the_live_donation_and_omit_the_cancelled_one(self):
        from verenigingen.api.anbi_operations import get_anbi_statistics

        before = get_anbi_statistics(from_date=today(), to_date=today())
        self.assertTrue(before["success"], f"unexpected failure: {before.get('error')}")
        base_count = before["data"]["statistics"]["total_anbi_donations"]
        base_amount = float(before["data"]["statistics"]["total_anbi_amount"] or 0)

        donor = self._make_donor(donor_name="ANBI Stats Donor")
        self._make_donation(donor, 750.0, **self._anbi_kwargs())
        self._make_donation(donor, 250.0, cancelled=True, **self._anbi_kwargs())

        after = get_anbi_statistics(from_date=today(), to_date=today())
        stats = after["data"]["statistics"]

        self.assertEqual(
            stats["total_anbi_donations"] - base_count,
            1,
            "expected exactly the live donation: the unsubmitted one must count, "
            "the cancelled one must not",
        )
        self.assertAlmostEqual(
            float(stats["total_anbi_amount"] or 0) - base_amount,
            750.0,
            places=2,
            msg="a cancelled donation must never reach this Belastingdienst amount",
        )

    def test_report_lists_the_live_donation_and_omits_the_cancelled_one(self):
        from verenigingen.api.anbi_operations import generate_anbi_report

        donor = self._make_donor(donor_name="ANBI Report Donor")
        live, cancelled = (
            self._make_donation(donor, 600.0, **self._anbi_kwargs()),
            self._make_donation(donor, 300.0, cancelled=True, **self._anbi_kwargs()),
        )

        result = generate_anbi_report(from_date=today(), to_date=today())
        self.assertTrue(result["success"], f"unexpected failure: {result.get('error')}")
        reported = [row["donation_id"] for row in result["data"]["donations"]]

        self.assertIn(live.name, reported, "the unsubmitted ANBI donation is missing from the report")
        self.assertNotIn(
            cancelled.name, reported, "a cancelled donation must not be reported to the tax office"
        )


class TestConsentRequestDocstatusPredicate(DonationDocstatusFilterTestCase):
    """anbi_operations.send_consent_requests — the highest-blast-radius call site.

    Its donor query was dead, so the endpoint sent zero emails; with the
    predicate fixed it sends real ones, capped at LIMIT 100, and its only
    re-send guard is ``donor.anbi_consent = 0``. A donor whose only donation was
    cancelled must not be mailed.

    The email transport is stubbed — that is infrastructure, not business logic;
    the donor-selection query under test runs for real.
    """

    class _Recorder:
        def __init__(self):
            self.recipients = []

        def send_templated_email(self, **kwargs):
            self.recipients.extend(kwargs.get("recipients") or [])
            return frappe._dict(success=True, errors=[])

    def test_only_donors_with_a_live_donation_are_emailed(self):
        from verenigingen.api.anbi_operations import send_consent_requests

        live_donor = self._make_donor(donor_name="Consent Live Donor")
        self._make_donation(live_donor, 100.0)
        cancelled_donor = self._make_donor(donor_name="Consent Cancelled Donor")
        self._make_donation(cancelled_donor, 100.0, cancelled=True)

        recorder = self._Recorder()
        with patch(
            "verenigingen.services.communication.email_service.get_email_service",
            return_value=recorder,
        ):
            result = send_consent_requests()

        self.assertTrue(result["success"], f"unexpected failure: {result.get('error')}")
        self.assertIn(
            live_donor.donor_email,
            recorder.recipients,
            "a donor with an unsubmitted paid donation was never asked for ANBI consent",
        )
        self.assertNotIn(
            cancelled_donor.donor_email,
            recorder.recipients,
            "a donor whose only donation is cancelled was emailed a consent request",
        )


class TestDonationSummaryReportDocstatusPredicate(DonationDocstatusFilterTestCase):
    """verenigingen/verenigingen/report/donation_summary/donation_summary.py"""

    def test_report_aggregates_only_the_live_donations(self):
        from verenigingen.verenigingen.report.donation_summary.donation_summary import get_data

        donor = self._make_donor(donor_name="Summary Report Donor")
        self._make_donation(donor, 400.0)
        self._make_donation(donor, 350.0)
        self._make_donation(donor, 250.0, cancelled=True)

        rows = get_data({"from_date": today(), "to_date": today(), "donor": donor.name})

        self.assertEqual(len(rows), 1, "the donor's unsubmitted donations produced no report row")
        self.assertEqual(rows[0]["donation_count"], 2, "the cancelled donation was counted")
        self.assertAlmostEqual(
            float(rows[0]["total_donations"]), 750.0, places=2, msg="cancelled amount leaked into the total"
        )


class TestDonationServicesDocstatusPredicate(DonationDocstatusFilterTestCase):
    """verenigingen/services/donation/*.py"""

    def test_donor_summary_counts_only_the_live_donation(self):
        """donor_service.get_donor_donation_summary"""
        from verenigingen.services.donation.donor_service import get_donation_donor_service

        donor = self._make_donor(donor_name="Donor Summary Donor")
        self._live_and_cancelled(donor, 125.0, 90.0)

        service = get_donation_donor_service(frappe.new_doc("Donation"))
        summary = service.get_donor_donation_summary(donor.name)

        self.assertEqual(summary["total_donations"], 1, "expected only the live donation")
        self.assertAlmostEqual(float(summary["total_amount"]), 125.0, places=2)

    def test_anbi_reporting_lists_only_the_live_donation(self):
        """reporting_service.get_anbi_donations_for_reporting.

        A second, parallel ANBI implementation alongside
        anbi_operations.generate_anbi_report — both feed Belastingdienst
        reporting and both have to exclude cancelled donations.
        """
        from verenigingen.services.donation.reporting_service import DonationReportingService

        donor = self._make_donor(donor_name="ANBI Service Report Donor")
        anbi = {"anbi_agreement_date": today()}
        live = self._make_donation(
            donor, 500.0, anbi_agreement_number=f"ANBI-{frappe.generate_hash(length=8)}", **anbi
        )
        cancelled = self._make_donation(
            donor,
            200.0,
            cancelled=True,
            anbi_agreement_number=f"ANBI-{frappe.generate_hash(length=8)}",
            **anbi,
        )

        rows = DonationReportingService().get_anbi_donations_for_reporting(today(), today())
        names = [row.get("donation_id") or row.get("name") for row in rows]

        self.assertIn(live.name, names, "the unsubmitted ANBI donation is missing from the report")
        self.assertNotIn(cancelled.name, names, "a cancelled donation reached the ANBI report")

    def test_summary_by_purpose_counts_only_the_live_donation(self):
        """reporting_service.get_donation_summary_by_purpose"""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        service = DonationReportingService()
        before = service.get_donation_summary_by_purpose(from_date=today(), to_date=today())
        base_count = before["General"]["count"]
        base_total = float(before["General"]["total"])

        donor = self._make_donor(donor_name="Purpose Summary Donor")
        self._live_and_cancelled(donor, 275.0, 125.0, donation_purpose_type="General")

        after = service.get_donation_summary_by_purpose(from_date=today(), to_date=today())

        self.assertEqual(after["General"]["count"] - base_count, 1, "expected only the live donation")
        self.assertAlmostEqual(float(after["General"]["total"]) - base_total, 275.0, places=2)

    def test_accounting_summary_counts_only_the_live_donation(self):
        """reporting_service.get_donation_accounting_summary"""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        service = DonationReportingService()
        base = float(
            service.get_donation_accounting_summary(from_date=today(), to_date=today())["total_donations"]
        )

        donor = self._make_donor(donor_name="Accounting Summary Donor")
        self._live_and_cancelled(donor, 310.0, 210.0)

        after = float(
            service.get_donation_accounting_summary(from_date=today(), to_date=today())["total_donations"]
        )

        self.assertAlmostEqual(
            after - base, 310.0, places=2, msg="expected only the live donation in the accounting summary"
        )

    def test_donations_by_chapter_list_only_the_live_donation(self):
        """reporting_service.get_donations_by_chapter"""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        chapter = self.create_test_chapter()
        donor = self._make_donor(donor_name="Chapter Donations Donor")
        live, cancelled = self._live_and_cancelled(
            donor, 145.0, 65.0, donation_purpose_type="Chapter", chapter_reference=chapter.name
        )

        result = DonationReportingService().get_donations_by_chapter(chapter.name)
        names = [row["name"] for row in result["donations"]]

        self.assertIn(live.name, names, "the unsubmitted chapter donation is missing")
        self.assertNotIn(cancelled.name, names, "a cancelled chapter donation was listed")
        self.assertAlmostEqual(float(result["total_amount"]), 145.0, places=2)

    def test_donations_by_campaign_list_only_the_live_donation(self):
        """reporting_service.get_donations_by_campaign"""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        campaign = self._make_campaign()
        donor = self._make_donor(donor_name="Campaign Donations Donor")
        live, cancelled = self._live_and_cancelled(
            donor, 155.0, 55.0, donation_purpose_type="Campaign", campaign=campaign.name
        )

        result = DonationReportingService().get_donations_by_campaign(campaign.name)
        names = [row["name"] for row in result["donations"]]

        self.assertIn(live.name, names, "the unsubmitted campaign donation is missing")
        self.assertNotIn(cancelled.name, names, "a cancelled campaign donation was listed")
        self.assertAlmostEqual(float(result["total_amount"]), 155.0, places=2)

    def test_allocation_report_lists_only_the_live_donation(self):
        """reporting_service.create_donation_allocation_report"""
        from verenigingen.services.donation.reporting_service import DonationReportingService

        donor = self._make_donor(donor_name="Allocation Report Donor")
        live, cancelled = self._live_and_cancelled(donor, 90.0, 40.0)

        report = DonationReportingService().create_donation_allocation_report(
            from_date=today(), to_date=today()
        )
        names = [row["name"] for row in report["donations"]]

        self.assertIn(live.name, names, "the unsubmitted donation is missing from the allocation report")
        self.assertNotIn(cancelled.name, names, "a cancelled donation was allocated")

    def test_reconciliation_counts_only_the_live_donation(self):
        """financial_service.reconcile_donation_accounts"""
        from verenigingen.services.donation.financial_service import DonationFinancialService

        service = DonationFinancialService()
        base_total = float(service.reconcile_donation_accounts()["total_donations"])

        donor = self._make_donor(donor_name="Reconcile Donor")
        self._live_and_cancelled(donor, 310.0, 120.0)

        after_total = float(service.reconcile_donation_accounts()["total_donations"])

        self.assertAlmostEqual(
            after_total - base_total,
            310.0,
            places=2,
            msg="expected only the live donation to be reconciled against the GL",
        )

    def _make_campaign(self):
        campaign = frappe.new_doc("Donation Campaign")
        campaign.campaign_name = f"DocstatusCamp {frappe.generate_hash(length=8)}"
        campaign.campaign_type = "Project Funding"
        campaign.status = "Active"
        campaign.start_date = today()
        campaign.insert()
        self.track_doc("Donation Campaign", campaign.name)
        return campaign


class TestDonationDashboardDocstatusPredicate(DonationDocstatusFilterTestCase):
    """verenigingen/services/donation/dashboard_service.py (Donation queries)"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.donation.dashboard_service import DonationDashboardService

        self.service = DonationDashboardService()
        year = getdate(today()).year
        self.year_start, self.year_end = f"{year}-01-01", f"{year}-12-31"

    def test_year_to_date_stats_count_only_the_live_donation(self):
        before = self.service._get_year_to_date_stats(self.year_start, self.year_end)

        donor = self._make_donor(donor_name="Dashboard YTD Donor")
        self._live_and_cancelled(donor, 220.0, 80.0)

        after = self.service._get_year_to_date_stats(self.year_start, self.year_end)

        self.assertEqual(
            after["total_donations_count"] - before["total_donations_count"],
            1,
            "expected exactly the live donation in the year-to-date stats",
        )
        self.assertAlmostEqual(
            after["total_donations_amount"] - before["total_donations_amount"], 220.0, places=2
        )

    def test_reportable_donations_count_only_the_live_donation(self):
        before = self.service._get_reportable_donations(self.year_start, self.year_end, 500)

        donor = self._make_donor(donor_name="Dashboard Reportable Donor")
        self._live_and_cancelled(donor, 900.0, 800.0)

        after = self.service._get_reportable_donations(self.year_start, self.year_end, 500)

        self.assertEqual(
            after["reportable_donations_count"] - before["reportable_donations_count"], 1
        )
        self.assertAlmostEqual(
            after["reportable_donations_amount"] - before["reportable_donations_amount"], 900.0, places=2
        )

    def test_monthly_trend_counts_only_the_live_donation(self):
        year = getdate(today()).year
        month_index = getdate(today()).month - 1
        before = self.service._get_monthly_trend_chart(year)["datasets"][0]["values"][month_index]

        donor = self._make_donor(donor_name="Dashboard Trend Donor")
        self._live_and_cancelled(donor, 130.0, 70.0)

        after = self.service._get_monthly_trend_chart(year)["datasets"][0]["values"][month_index]

        self.assertAlmostEqual(after - before, 130.0, places=2)

    def test_donor_stats_count_only_donors_with_a_live_donation(self):
        before = self.service._get_donor_stats()["unique_donors"]

        live_donor = self._make_donor(donor_name="Dashboard Live Donor")
        self._make_donation(live_donor, 60.0)
        cancelled_only_donor = self._make_donor(donor_name="Dashboard Cancelled Donor")
        self._make_donation(cancelled_only_donor, 60.0, cancelled=True)

        after = self.service._get_donor_stats()["unique_donors"]

        self.assertEqual(
            after - before,
            1,
            "a donor whose only donation is cancelled must not count as a donor",
        )

    def test_recent_donations_list_the_live_donation_and_omit_the_cancelled_one(self):
        # _get_recent_donations orders by donation_date DESC with LIMIT 10 and no
        # donor scoping, so the fixtures are dated far in the future to make the
        # assertion independent of whatever else the site holds.
        far_future = add_days(today(), 3650)
        donor = self._make_donor(donor_name="Dashboard Recent Donor")
        live, cancelled = self._live_and_cancelled(donor, 180.0, 90.0, donation_date=far_future)

        names = [row["name"] for row in self.service._get_recent_donations()]

        self.assertIn(live.name, names, "the unsubmitted donation is missing from recent donations")
        self.assertNotIn(cancelled.name, names, "a cancelled donation was listed as a recent donation")


class TestPeriodicAgreementDashboardDocstatusPredicate(VereningingenTestCase):
    """dashboard_service's Periodic Donation Agreement queries.

    PDA is not submittable either, so the same ``docstatus = 1`` predicate made
    all three of these return zero.
    """

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        from verenigingen.services.donation.dashboard_service import DonationDashboardService

        self.service = DonationDashboardService()

    def _make_agreement(self, cancelled=False, **kwargs):
        # An ANBI-eligible agreement is rejected unless the individual donor has
        # consented and carries an eleven-proof-valid BSN.
        from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn

        kwargs.setdefault(
            "donor",
            self.create_test_donor(
                donor_type="Individual",
                anbi_consent=1,
                anbi_consent_date=today(),
                bsn_citizen_service_number=generate_valid_bsn(),
            ).name,
        )
        agreement = self.create_test_periodic_donation_agreement(status="Active", **kwargs)
        self.assertEqual(agreement.docstatus, 0, "PDA is not submittable")
        if cancelled:
            frappe.db.set_value(
                "Periodic Donation Agreement", agreement.name, "docstatus", 2, update_modified=False
            )
            agreement.reload()
        return agreement

    def test_agreement_stats_count_only_the_live_agreement(self):
        before = self.service._get_periodic_agreement_stats()["active_anbi_agreements"]

        self._make_agreement(anbi_eligible=1)
        self._make_agreement(anbi_eligible=1, cancelled=True)

        after = self.service._get_periodic_agreement_stats()["active_anbi_agreements"]

        self.assertEqual(after - before, 1, "expected exactly the live ANBI agreement")

    def test_agreement_distribution_counts_only_the_live_agreement(self):
        def anbi_count():
            rows = self.service._get_agreement_distribution()["labels"]
            values = self.service._get_agreement_distribution()["datasets"][0]["values"]
            return values[rows.index("ANBI Agreements")] if "ANBI Agreements" in rows else 0

        before = anbi_count()
        self._make_agreement(anbi_eligible=1)
        self._make_agreement(anbi_eligible=1, cancelled=True)

        self.assertEqual(anbi_count() - before, 1, "expected exactly the live ANBI agreement")

    def test_expiring_agreements_list_only_the_live_agreement(self):
        # end_date is derived from start_date + duration, so start 5 years back to
        # land inside the 90-day expiry window the dashboard queries.
        five_years_ago = add_years(getdate(today()), -5).strftime("%Y-%m-%d")
        live = self._make_agreement(start_date=five_years_ago)
        cancelled = self._make_agreement(start_date=five_years_ago, cancelled=True)

        names = [row["name"] for row in self.service._get_expiring_agreements()]

        self.assertIn(live.name, names, "the expiring agreement is missing from the dashboard")
        self.assertNotIn(cancelled.name, names, "a cancelled agreement was listed as expiring")


# --------------------------------------------------------------------------- #
# Structural gate
# --------------------------------------------------------------------------- #


class TestDonationQueriesUseTheCorrectDocstatusPredicate(VereningingenTestCase):
    """Gate for issue #350 over every call site, including the untested ones.

    Flags only predicates that EXCLUDE docstatus 0 (``= 1`` / ``== 1``). The
    correct forms — ``< 2``, ``!= 2``, ``<= 1``, ``in (0, 1)`` — are permitted,
    which matters: an earlier revision of this gate matched ``docstatus``
    regardless of comparison and drove a correct ``docstatus < 2`` call site in
    api/donor_customer_management.py to be "fixed" into a bug.

    Covers, for both Donation and Periodic Donation Agreement: raw SQL naming the
    table (constant, f-string, ``+`` concatenation, ``.format()`` template), ORM
    calls whose doctype is a literal or a variable bound to one, filters given
    inline / via a variable / as list-of-lists, and ``frappe.qb`` comparisons
    through a ``DocType(...)`` alias. Each of those is planted and asserted
    individually by ``test_the_scanner_catches_every_query_shape_in_this_repo``.

    Out of reach, and deliberately not guessed at: predicates assembled at
    runtime from non-literal values, doctype names built by concatenation, and
    filters passed through a helper in another module. Those rely on the
    behavioural tests above. Client-side filters are out of scope entirely — this
    reads Python only, so a ``docstatus: 1`` in a ``.js`` controller is not
    covered here.

    Known over-approximation: a SQL statement that joins a Donation table to
    another submittable doctype and filters *that* one on ``docstatus = 1`` would
    be reported. No such statement exists in the repo today, and a false positive
    on this gate costs a human read rather than silently shipping a dead query.
    """

    @classmethod
    def _production_sources(cls):
        import verenigingen

        root = Path(verenigingen.__file__).parent
        skipped_dirs = {"tests", "node_modules", "__pycache__"}
        for path in root.rglob("*.py"):
            if set(path.relative_to(root).parts) & skipped_dirs:
                continue
            if path.name.startswith("test_") or path.name.startswith("debug_"):
                continue
            yield path

    def test_no_production_donation_query_excludes_draft_donations(self):
        offenders = []
        scanned = 0
        for path in self._production_sources():
            source = path.read_text(encoding="utf-8")
            if not any(name in source for name in DONATION_DOCTYPES):
                continue
            scanned += 1
            offenders.extend(DonationQueryScanner(ast.parse(source, filename=str(path)), path).run())

        # Control: an empty offender list from a scanner that read nothing would
        # be indistinguishable from a clean codebase.
        self.assertGreater(scanned, 20, "the scan found almost no Donation sources — it is not running")
        self.assertEqual(
            offenders,
            [],
            "Donation/PDA are not submittable, so 'docstatus = 1' silently discards every real row. "
            "Use 'docstatus < 2':\n" + "\n".join(offenders),
        )

    def test_the_scanner_catches_every_query_shape_in_this_repo(self):
        """Control: each shape the gate claims to cover must be caught on its own."""
        shapes = {
            "inline dict filters": 'frappe.get_all("Donation", filters={"docstatus": 1})',
            "variable dict filters": (
                'def f():\n'
                '    filters = {"paid": 1, "docstatus": 1}\n'
                '    return frappe.get_all("Donation", filters=filters)\n'
            ),
            "operator-pair filters": 'frappe.get_all("Donation", filters={"docstatus": ["=", 1]})',
            "list-of-list filters": 'frappe.get_all("Donation", filters=[["docstatus", "=", 1]])',
            "variable doctype name": (
                'def f():\n'
                '    dt = "Donation"\n'
                '    return frappe.db.count(dt, {"docstatus": 1})\n'
            ),
            "positional filters": 'frappe.db.count("Donation", {"docstatus": 1})',
            "plain SQL": 'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus = 1")',
            "f-string SQL": 'frappe.db.sql(f"SELECT name FROM `tabDonation` WHERE docstatus = 1 {tail}")',
            "SQL split across an interpolation": (
                'frappe.db.sql(f"SELECT name FROM `tabDonation` WHERE docstatus {op} 1 AND docstatus = 1")'
            ),
            "concatenated SQL": (
                'frappe.db.sql("SELECT name FROM `tabDonation` " + "WHERE docstatus = 1")'
            ),
            "format-template SQL": (
                'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus = 1 {cond}".format(cond=c))'
            ),
            "frappe.qb": (
                'def f():\n'
                '    Donation = DocType("Donation")\n'
                '    return frappe.qb.from_(Donation).where(Donation.docstatus == 1)\n'
            ),
            "periodic donation agreement SQL": (
                'frappe.db.sql("SELECT name FROM `tabPeriodic Donation Agreement` WHERE docstatus = 1")'
            ),
            "periodic donation agreement ORM": (
                'frappe.get_all("Periodic Donation Agreement", filters={"docstatus": 1})'
            ),
        }
        missed = [label for label, source in shapes.items() if not scan_source(source)]
        self.assertEqual(missed, [], f"the gate does not actually catch these shapes: {missed}")

    def test_the_scanner_permits_the_correct_predicates(self):
        """Control: the gate must not flag a predicate that admits drafts.

        This is the assertion whose absence turned a correct ``docstatus < 2``
        call site into a bug in an earlier revision of this branch.
        """
        permitted = {
            "orm less-than-two": 'frappe.get_all("Donation", filters={"docstatus": ["<", 2]})',
            "orm not-equal-two": 'frappe.get_all("Donation", filters={"docstatus": ["!=", 2]})',
            "orm list-of-list": 'frappe.get_all("Donation", filters=[["docstatus", "<", 2]])',
            "sql less-than-two": 'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus < 2")',
            "sql not-equal-two": 'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus != 2")',
            "sql less-or-equal-one": 'frappe.db.sql("SELECT name FROM `tabDonation` WHERE docstatus <= 1")',
            "no predicate at all": 'frappe.get_all("Donation", filters={"paid": 1})',
            "another doctype entirely": 'frappe.get_all("Sales Invoice", filters={"docstatus": 1})',
        }
        wrongly_flagged = {
            label: scan_source(source) for label, source in permitted.items() if scan_source(source)
        }
        self.assertEqual(wrongly_flagged, {}, f"the gate flags correct code: {wrongly_flagged}")
