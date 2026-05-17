# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonation(EnhancedTestCase):
    """
    Integration tests for Donation DocType following testing standards.

    Tests donation creation and basic workflow with proper field validation
    and real database operations.

    External Services Mocked:
    - Email sending (frappe.sendmail)

    Real Integrations Tested:
    - Database operations and field references
    - Business rule validation
    - Donor linking and type fetching
    """

    def setUp(self):
        """Set up test data using Enhanced Test Factory properly"""
        super().setUp()

        # Get any existing company or use default
        companies = frappe.get_all("Company", limit=1)
        if companies:
            self.test_company = companies[0].name
        else:
            # Fallback to a simple company name that tests can use
            self.test_company = "_Test Company"

        # Create test donor using proper schema understanding
        self.test_donor = self.create_test_donor()

        # Set up basic donation settings
        self.setup_donation_settings()

    def create_test_donor(self):
        """Create test donor using actual schema fields"""
        # Use the factory to create donor with correct field types
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Test Donation Donor {self.test_run_id}"
        donor.donor_type = "Individual"  # Select field with valid option
        donor.donor_email = f"test-donor-{self.test_run_id}@example.com"
        donor.insert()
        return donor

    def test_basic_donation_creation(self):
        """Test basic donation creation with proper field validation"""
        # Mock only external services
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            # Create donation with proper field references
            donation = frappe.new_doc("Donation")
            donation.donor = self.test_donor.name
            donation.amount = 100
            donation.donation_date = frappe.utils.today()
            donation.company = self.test_company

            # The mode_of_payment field is required per new schema
            if not frappe.db.exists("Mode of Payment", "Test Payment"):
                mode = frappe.new_doc("Mode of Payment")
                mode.mode_of_payment = "Test Payment"
                mode.insert()
            donation.mode_of_payment = "Test Payment"

            donation.insert()

        # Verify real database changes
        self.assertTrue(donation.name)
        self.assertEqual(donation.donor, self.test_donor.name)

        # Verify donor_type is automatically fetched (read-only field)
        donation.reload()
        self.assertEqual(donation.donor_type, "Individual")  # Fetched from donor

        # Test field reference is valid per testing standards
        self.assertEqual(donation.amount, 100)

    def test_donation_agreement_linking(self):
        """Test donation agreement linking with new schema"""
        # Mock only external services
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            # Create donation agreement first
            agreement = frappe.new_doc("Donation Agreement")
            agreement.donor = self.test_donor.name
            agreement.agreement_type = "Recurring"
            agreement.status = "Active"
            agreement.start_date = frappe.utils.today()
            agreement.amount = 100
            agreement.currency = "EUR"
            agreement.recurring_frequency = "1 month"
            agreement.donation_purpose = "General Fund"
            agreement.insert()

            # Create donation with agreement link
            donation = frappe.new_doc("Donation")
            donation.donor = self.test_donor.name
            donation.amount = 100
            donation.donation_date = frappe.utils.today()
            donation.company = self.test_company
            donation.mode_of_payment = "Test Payment"
            donation.donation_agreement = agreement.name  # New linking field
            donation.insert()

        # Verify real database changes and relationships
        self.assertEqual(donation.donation_agreement, agreement.name)
        self.assertEqual(donation.donor, self.test_donor.name)

        # Verify field references are valid (per testing standards)
        donation.reload()
        agreement.reload()
        self.assertEqual(donation.donation_agreement, agreement.name)
        self.assertEqual(agreement.donor, self.test_donor.name)

    def _create_periodic_agreement_donation(self):
        """Create a draft Donation linked to a 5-year ANBI periodic agreement.

        Returns the unsubmitted Donation document. Callers should run this
        inside a `patch("frappe.sendmail")` block (the inserts send email).
        """
        # Donor with BSN — required for ANBI periodic agreement validation
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"PDA Donor {self.test_run_id}"
        donor.donor_type = "Individual"
        donor.donor_email = f"pda-donor-{self.test_run_id}@example.com"
        donor.anbi_consent = 1
        donor.anbi_consent_date = frappe.utils.today()
        donor.identification_verified = 1
        donor.identification_verification_date = frappe.utils.today()
        donor.identification_verification_method = "DigiD"
        donor.bsn_citizen_service_number = "123456782"
        donor.insert()

        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.start_date = frappe.utils.today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        agreement.status = "Active"
        agreement.donor_signature_received = 1
        agreement.signed_date = frappe.utils.today()
        agreement.save()

        if not frappe.db.exists("Mode of Payment", "Test Payment"):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = "Test Payment"
            mode.insert()

        donation = frappe.new_doc("Donation")
        donation.donor = donor.name
        donation.amount = 100
        donation.donation_date = frappe.utils.today()
        donation.company = self.test_company
        donation.mode_of_payment = "Test Payment"
        donation.periodic_donation_agreement = agreement.name
        donation.insert()
        return donation

    def test_periodic_agreement_donation_is_belastingdienst_reportable(self):
        """A donation linked to a periodic donation agreement is auto-marked
        belastingdienst_reportable.

        Regression (audit T1.2, 2026-05-17): the belastingdienst_reportable
        field did not exist on the Donation DocType, so the donation dashboard
        crashed and the field could not be populated.
        """
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            donation = self._create_periodic_agreement_donation()

        donation.reload()
        self.assertEqual(donation.belastingdienst_reportable, 1)

    def test_belastingdienst_reportable_cleared_when_agreement_unlinked(self):
        """Removing the periodic agreement link clears the auto-set
        belastingdienst_reportable flag (review H1, PR #37) — the flag must
        not stay 1 once the donation is no longer under an agreement.
        """
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            donation = self._create_periodic_agreement_donation()
            self.assertEqual(donation.belastingdienst_reportable, 1)

            donation.periodic_donation_agreement = None
            donation.save()

        donation.reload()
        self.assertEqual(donation.belastingdienst_reportable, 0)

    def setup_donation_settings(self):
        """Set up basic donation settings"""
        try:
            settings = frappe.get_doc("Verenigingen Settings")
            if settings:
                settings.company = self.test_company
                settings.save()
        except frappe.DoesNotExistError:
            # Settings don't exist, that's fine for basic tests
            pass
