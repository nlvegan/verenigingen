"""
Integration tests for DonationFinancialService.

Covers the live, whitelisted donation-creation paths and the reconciliation
report using real Donor/Donation/Chapter fixtures on the test database.

These tests intentionally exercise production call patterns (the same ones the
whitelisted controller wrappers in donation.py invoke) so they would catch
regressions like:
- create_chapter_donation never setting the mandatory mode_of_payment field
- reconcile_donation_accounts selecting a non-existent ``company`` column

Author: Verenigingen Development Team
"""

import frappe
from frappe.utils import today

from verenigingen.services.donation.financial_service import DonationFinancialService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationFinancialService(EnhancedTestCase):
    """Test suite for DonationFinancialService live paths."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.service = DonationFinancialService()
        self.donor = self.create_test_donor(donor_name="Financial Service Donor")

    # ========== create_donation_from_bank_transfer ==========

    def test_create_donation_from_bank_transfer_creates_paid_submitted_donation(self):
        """Bank-transfer donations are created paid and submitted."""
        with self.assertNoErrorLog():
            donation = self.service.create_donation_from_bank_transfer(
                donor=self.donor.name,
                amount=125.0,
                date=today(),
                bank_reference="BANK-REF-FS-1",
                donation_type="General",
            )

        self.assertTrue(frappe.db.exists("Donation", donation.name))
        self.assertEqual(donation.docstatus, 1)
        self.assertEqual(donation.paid, 1)
        self.assertEqual(donation.amount, 125.0)
        self.assertEqual(donation.mode_of_payment, "Bank Transfer")
        self.assertEqual(donation.bank_reference, "BANK-REF-FS-1")

    def test_create_donation_from_bank_transfer_missing_donation_type_setting_raises(self):
        """
        Documents the phantom 'default_donation_type' setting:
        when no donation_type is supplied the service falls back to
        get_single_value('Verenigingen Settings', 'default_donation_type'),
        which does not exist on the DocType and raises ValidationError.

        See FLAG in handoff: default_donation_type / default_donation_item are
        phantom Verenigingen Settings fields.
        """
        with self.assertRaises(frappe.ValidationError):
            self.service.create_donation_from_bank_transfer(
                donor=self.donor.name,
                amount=10.0,
                date=today(),
                bank_reference="BANK-REF-FS-2",
                # no donation_type -> triggers phantom-setting lookup
            )

    # ========== create_sepa_donation ==========

    def test_create_sepa_donation_promised_when_not_recurring(self):
        """A one-off SEPA donation gets status 'Promised' and is not paid yet."""
        mandate = self._create_sepa_mandate(self.donor)
        with self.assertNoErrorLog():
            donation = self.service.create_sepa_donation(
                donor=self.donor.name,
                amount=60.0,
                date=today(),
                sepa_mandate=mandate.name,
                donation_type="General",
            )

        self.assertTrue(frappe.db.exists("Donation", donation.name))
        # Not submitted - SEPA batch processes it later
        self.assertEqual(donation.docstatus, 0)
        self.assertEqual(donation.status, "Promised")
        self.assertEqual(donation.paid, 0)
        self.assertEqual(donation.mode_of_payment, "SEPA Direct Debit")
        self.assertEqual(donation.sepa_mandate, mandate.name)

    def test_create_sepa_donation_recurring_sets_recurring_status(self):
        """A recurring SEPA donation gets status 'Recurring' and stores frequency."""
        mandate = self._create_sepa_mandate(self.donor)
        with self.assertNoErrorLog():
            donation = self.service.create_sepa_donation(
                donor=self.donor.name,
                amount=20.0,
                date=today(),
                sepa_mandate=mandate.name,
                donation_type="General",
                recurring_frequency="Monthly",
            )

        self.assertEqual(donation.status, "Recurring")
        self.assertEqual(donation.recurring_frequency, "Monthly")

    # ========== create_chapter_donation ==========

    def test_create_chapter_donation_sets_chapter_purpose_and_mode_of_payment(self):
        """
        Chapter donations are earmarked correctly AND set the mandatory
        mode_of_payment field (regression: previously raised MandatoryError).
        """
        chapter = frappe.get_all("Chapter", limit=1, pluck="name")
        if not chapter:
            self.skipTest("No Chapter available on test site")
        chapter_name = chapter[0]

        with self.assertNoErrorLog():
            donation = self.service.create_chapter_donation(
                donor=self.donor.name,
                amount=40.0,
                chapter=chapter_name,
                donation_type="General",
                notes="For the local chapter",
            )

        self.assertTrue(frappe.db.exists("Donation", donation.name))
        self.assertEqual(donation.donation_purpose_type, "Chapter")
        self.assertEqual(donation.chapter_reference, chapter_name)
        self.assertEqual(donation.donation_notes, "For the local chapter")
        # The fix: mandatory mode_of_payment is now populated
        self.assertEqual(donation.mode_of_payment, "Bank Transfer")

    def test_create_chapter_donation_default_notes(self):
        """When no notes supplied, a default earmark note is generated."""
        chapter = frappe.get_all("Chapter", limit=1, pluck="name")
        if not chapter:
            self.skipTest("No Chapter available on test site")
        chapter_name = chapter[0]

        donation = self.service.create_chapter_donation(
            donor=self.donor.name,
            amount=15.0,
            chapter=chapter_name,
            donation_type="General",
        )
        self.assertIn(chapter_name, donation.donation_notes)

    def test_create_chapter_donation_invalid_chapter_throws(self):
        """Non-existent chapter is rejected with a clear error."""
        with self.assertRaises(frappe.ValidationError):
            self.service.create_chapter_donation(
                donor=self.donor.name,
                amount=15.0,
                chapter="NONEXISTENT-CHAPTER-ZZZ",
                donation_type="General",
            )

    # ========== reconcile_donation_accounts ==========

    def test_reconcile_donation_accounts_clean_when_no_gl_entries_match(self):
        """
        Reconciliation runs without crashing (regression: previously selected
        a non-existent ``company`` column -> OperationalError) and reports the
        expected report structure.
        """
        # Create a paid, submitted donation so the report has at least one row
        self.service.create_donation_from_bank_transfer(
            donor=self.donor.name,
            amount=99.0,
            date=today(),
            bank_reference="RECON-REF-1",
            donation_type="General",
        )

        report = self.service.reconcile_donation_accounts()

        self.assertIn("total_donations", report)
        self.assertIn("total_gl_credits", report)
        self.assertIn("discrepancies", report)
        self.assertIn("summary", report)
        self.assertIn("reconciliation_status", report["summary"])
        # Our donation has no Donation-type GL entries, so it shows as a discrepancy
        self.assertGreaterEqual(report["summary"]["discrepancy_count"], 1)
        self.assertEqual(report["summary"]["reconciliation_status"], "Needs Review")

    # ========== earmarking / accounts helpers (no settings configured) ==========

    def test_get_earmarking_accounts_returns_none_when_unconfigured(self):
        """
        Earmarking accounts are sourced from (phantom) Verenigingen Settings
        fields via .get() (safe -> None), so unconfigured systems return None
        rather than crashing. Documents the dead earmarking path.
        """
        donation = self._chapter_donation_doc()
        svc = DonationFinancialService(donation)
        # source/destination accounts not configured -> None
        self.assertIsNone(svc._get_earmarking_accounts())

    def test_requires_earmarking_true_for_chapter_purpose(self):
        """_requires_earmarking is True for Chapter/Campaign purpose donations."""
        donation = self._chapter_donation_doc()
        svc = DonationFinancialService(donation)
        self.assertTrue(svc._requires_earmarking())

    def test_requires_earmarking_false_for_general(self):
        """General donations do not require earmarking."""
        donation = self.create_test_donation(
            donor=self.donor.name,
            donation_purpose_type="General",
        )
        svc = DonationFinancialService(donation)
        self.assertFalse(svc._requires_earmarking())

    def test_get_earmarking_summary_chapter(self):
        """Earmarking summary reports Chapter destination."""
        donation = self._chapter_donation_doc()
        svc = DonationFinancialService(donation)
        summary = svc.get_earmarking_summary()
        self.assertTrue(summary["requires_earmarking"])
        self.assertEqual(summary["earmarking_type"], "Chapter")
        self.assertIn(donation.chapter_reference, summary["destination_fund"])

    def test_get_customer_name_none_without_customer(self):
        """_get_customer_name returns None for a donor with no linked customer."""
        donation = self.create_test_donation(donor=self.donor.name)
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc._get_customer_name())

    def test_get_company_for_donations_returns_company(self):
        """The company resolver returns the configured Verenigingen Settings company."""
        svc = DonationFinancialService()
        company = svc._get_company_for_donations()
        self.assertTrue(company)
        self.assertTrue(frappe.db.exists("Company", company))

    # ========== Helpers ==========

    def _chapter_donation_doc(self):
        """Insert a valid Chapter-purpose donation (chapter_reference required)."""
        chapter = frappe.get_all("Chapter", limit=1, pluck="name")
        if not chapter:
            self.skipTest("No Chapter available on test site")
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_date": today(),
                "amount": 100.0,
                "mode_of_payment": "Bank Transfer",
                "donation_purpose_type": "Chapter",
                "chapter_reference": chapter[0],
                "paid": 0,
            }
        )
        donation.insert()
        return donation

    def _create_sepa_mandate(self, donor):
        """Create a minimal active SEPA mandate linked to a member for the donor.

        SEPA Mandate.member is mandatory, so create a member to anchor it.
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        member = self.create_test_member(
            first_name="Sepa",
            last_name="Donor",
            email=f"sepa.donor.{frappe.generate_hash(length=8)}@example.com",
            birth_date="1985-01-01",
        )
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member.name,
                "mandate_id": f"FS-MND-{frappe.generate_hash(length=8)}",
                "iban": "NL91ABNA0417164300",
                "bic": "ABNANL2A",
                "account_holder_name": "Sepa Donor",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "used_for_donations": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        result = secure_document_operation(
            operation="insert",
            doc=mandate,
            justification="Test SEPA mandate for donation",
            required_permissions=["SEPA Mandate:create"],
        )
        if not result.success:
            raise frappe.ValidationError("; ".join(result.errors))
        return mandate
