"""
Integration tests for DonationReportingService.

These tests create real Donor/Donation fixtures and assert on the actual
aggregation logic (per-chapter / per-campaign sub-totals, GL-entry joins,
ANBI report-data generation, allocation-report SQL) rather than only checking
that the endpoints return a dict. This exercises the branches missed by the
existing empty-data API tests.

Author: Verenigingen Development Team
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.donation.reporting_service import DonationReportingService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationReportingService(EnhancedTestCase):
    """Test suite for DonationReportingService data aggregation."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.service = DonationReportingService()
        self.donor = self.create_test_donor(donor_name="Reporting Donor")
        self.chapter = self._get_chapter()

    # ========== get_anbi_donations_for_reporting ==========

    def test_anbi_reporting_returns_only_anbi_donations(self):
        """Only donations with an ANBI agreement number are reported."""
        anbi_number = f"ANBI-TEST-{frappe.generate_hash(length=6)}"
        self.create_test_donation(
            donor=self.donor.name,
            amount=200.0,
            donation_date=today(),
            anbi_agreement_number=anbi_number,
        )
        # Non-ANBI donation should be excluded
        self.create_test_donation(donor=self.donor.name, amount=50.0, donation_date=today())

        report = self.service.get_anbi_donations_for_reporting(
            str(add_days(getdate(), -1)), str(add_days(getdate(), 1))
        )

        matching = [r for r in report if r["anbi_agreement_number"] == anbi_number]
        self.assertEqual(len(matching), 1)
        entry = matching[0]
        self.assertEqual(entry["amount"], 200.0)
        self.assertEqual(entry["donor_name"], self.donor.donor_name)
        self.assertIn("donor_email", entry)

    def test_anbi_reporting_respects_date_range(self):
        """ANBI donations outside the date window are excluded."""
        anbi_number = f"ANBI-OLD-{frappe.generate_hash(length=6)}"
        self.create_test_donation(
            donor=self.donor.name,
            amount=10.0,
            donation_date=add_days(today(), -400),
            anbi_agreement_number=anbi_number,
        )
        report = self.service.get_anbi_donations_for_reporting(str(add_days(getdate(), -10)), str(today()))
        self.assertFalse(any(r["anbi_agreement_number"] == anbi_number for r in report))

    def test_generate_anbi_report_data_from_dict_skips_without_number(self):
        """The per-row generator returns None when there's no agreement number."""
        result = self.service._generate_anbi_report_data_from_dict(
            {"name": "X", "donor": self.donor.name, "anbi_agreement_number": None}
        )
        self.assertIsNone(result)

    # ========== get_donations_by_chapter ==========

    def test_get_donations_by_chapter_totals(self):
        """Chapter report aggregates total/paid/outstanding correctly."""
        self._chapter_donation(amount=100.0, paid=1)
        self._chapter_donation(amount=40.0, paid=0)

        result = self.service.get_donations_by_chapter(self.chapter)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total_amount"], 140.0)
        self.assertEqual(result["paid_amount"], 100.0)
        self.assertEqual(result["outstanding_amount"], 40.0)

    def test_get_donations_by_chapter_invalid_chapter_throws(self):
        """Unknown chapter raises a ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            self.service.get_donations_by_chapter("NONEXISTENT-CHAPTER-ZZZ")

    def test_get_donations_by_chapter_date_filter(self):
        """Date filter excludes out-of-range chapter donations."""
        self._chapter_donation(amount=100.0, paid=1, donation_date=add_days(today(), -400))
        result = self.service.get_donations_by_chapter(
            self.chapter, from_date=str(add_days(getdate(), -10)), to_date=str(today())
        )
        self.assertEqual(result["count"], 0)

    # ========== get_donations_by_campaign ==========

    def test_get_donations_by_campaign_totals(self):
        """Campaign report aggregates totals."""
        campaign = self._campaign_value()
        self._campaign_donation(campaign, amount=300.0, paid=1)
        self._campaign_donation(campaign, amount=200.0, paid=0)

        result = self.service.get_donations_by_campaign(campaign)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total_amount"], 500.0)
        self.assertEqual(result["paid_amount"], 300.0)
        self.assertEqual(result["outstanding_amount"], 200.0)

    # ========== get_donation_summary_by_purpose ==========

    def test_summary_by_purpose_buckets_chapter_and_general(self):
        """Summary groups amounts under the right purpose buckets."""
        self.create_test_donation(donor=self.donor.name, amount=70.0, paid=1, donation_purpose_type="General")
        self._chapter_donation(amount=130.0, paid=1)

        summary = self.service.get_donation_summary_by_purpose()

        self.assertGreaterEqual(summary["General"]["total"], 70.0)
        self.assertGreaterEqual(summary["General"]["count"], 1)
        self.assertGreaterEqual(summary["Chapter"]["total"], 130.0)
        # Per-chapter breakdown present
        self.assertIn(self.chapter, summary["Chapter"]["chapters"])
        self.assertEqual(summary["Chapter"]["chapters"][self.chapter]["total"], 130.0)
        self.assertEqual(summary["Chapter"]["chapters"][self.chapter]["paid"], 130.0)

    def test_summary_by_purpose_campaign_breakdown(self):
        """Campaign donations populate the per-campaign sub-dict."""
        campaign = self._campaign_value()
        self._campaign_donation(campaign, amount=80.0, paid=1)

        summary = self.service.get_donation_summary_by_purpose()
        self.assertIn(campaign, summary["Campaign"]["campaigns"])
        self.assertEqual(summary["Campaign"]["campaigns"][campaign]["total"], 80.0)
        self.assertEqual(summary["Campaign"]["campaigns"][campaign]["paid"], 80.0)

    # ========== get_donation_accounting_summary ==========

    def test_accounting_summary_totals_paid_donations(self):
        """Accounting summary totals only paid+submitted donations by purpose."""
        self._chapter_donation(amount=55.0, paid=1)
        # unpaid donation should be excluded (filter paid=1)
        self.create_test_donation(
            donor=self.donor.name, amount=999.0, paid=0, donation_purpose_type="General"
        )

        summary = self.service.get_donation_accounting_summary()
        self.assertGreaterEqual(summary["total_donations"], 55.0)
        self.assertIn("Chapter", summary["by_purpose"])
        self.assertIsInstance(summary["gl_entries"], list)
        # Unpaid 999 donation must not be counted
        self.assertNotIn(999.0, summary["by_purpose"].values())

    # ========== create_donation_allocation_report ==========

    def test_allocation_report_overall(self):
        """Allocation report joins donor data and totals across all donations."""
        self.create_test_donation(donor=self.donor.name, amount=120.0, paid=1)

        report = self.service.create_donation_allocation_report()
        self.assertGreaterEqual(report["summary"]["count"], 1)
        self.assertGreaterEqual(report["summary"]["total_amount"], 120.0)
        # donor_name joined from Donor table
        names = {d.get("donor_name") for d in report["donations"]}
        self.assertIn(self.donor.donor_name, names)

    def test_allocation_report_chapter_filter(self):
        """Allocation report restricted to a chapter only returns that chapter."""
        self._chapter_donation(amount=45.0, paid=1)
        report = self.service.create_donation_allocation_report(chapter=self.chapter)
        self.assertGreaterEqual(report["summary"]["count"], 1)
        for d in report["donations"]:
            self.assertEqual(d["chapter_reference"], self.chapter)
        self.assertEqual(report["filters_applied"]["chapter"], self.chapter)

    def test_allocation_report_paid_vs_outstanding(self):
        """Allocation report splits paid vs outstanding amounts."""
        self.create_test_donation(donor=self.donor.name, amount=60.0, paid=1)
        self.create_test_donation(donor=self.donor.name, amount=40.0, paid=0)
        report = self.service.create_donation_allocation_report()
        self.assertGreaterEqual(report["summary"]["paid_amount"], 60.0)
        self.assertGreaterEqual(report["summary"]["outstanding_amount"], 40.0)

    # ========== Helpers ==========

    def _get_chapter(self):
        chapter = frappe.get_all("Chapter", limit=1, pluck="name")
        if not chapter:
            self.skipTest("No Chapter available on test site")
        return chapter[0]

    def _chapter_donation(self, amount, paid, donation_date=None):
        # The shared factory does not pass through ``chapter_reference`` and the
        # Donation controller requires it for Chapter purpose, so build/submit
        # the doc directly.
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_date": donation_date or today(),
                "amount": amount,
                "mode_of_payment": "Bank Transfer",
                "paid": paid,
                "donation_purpose_type": "Chapter",
                "chapter_reference": self.chapter,
            }
        )
        donation.insert()
        frappe.db.set_value("Donation", donation.name, "docstatus", 1)
        donation.reload()
        return donation

    def _campaign_value(self):
        """Create a Donation Campaign and return its name (campaign is a Link)."""
        existing = frappe.get_all("Donation Campaign", limit=1, pluck="name")
        if existing:
            return existing[0]
        campaign = frappe.get_doc(
            {
                "doctype": "Donation Campaign",
                "campaign_name": f"Test Campaign {frappe.generate_hash(length=6)}",
                "campaign_type": "Other",
                "status": "Active",
                "start_date": today(),
            }
        )
        # setUp runs as Administrator, so no permission bypass is needed.
        campaign.insert()
        return campaign.name

    def _campaign_donation(self, campaign, amount, paid):
        return self.create_test_donation(
            donor=self.donor.name,
            amount=amount,
            paid=paid,
            donation_date=today(),
            donation_purpose_type="Campaign",
            campaign=campaign,
        )
