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

    # test_donation_agreement_linking removed: it exercised the "Donation
    # Agreement" DocType and the Donation.donation_agreement field, both of
    # which were deleted. The replacement — Periodic Donation Agreement linked
    # via Donation.periodic_donation_agreement — is exercised implicitly by the
    # periodic-agreement tests below (see _create_periodic_agreement_donation):
    # their belastingdienst_reportable assertions depend on that link being set.

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

    # ------------------------------------------------------------------
    # Helpers (privileged data creation lives here, not in test bodies)
    # ------------------------------------------------------------------
    def _ensure_mode_of_payment(self, name="Test Payment"):
        """Ensure a Mode of Payment exists for use in donations."""
        if not frappe.db.exists("Mode of Payment", name):
            mode = frappe.new_doc("Mode of Payment")
            mode.mode_of_payment = name
            mode.insert()
        return name

    def _make_donation(self, **overrides):
        """Build (not insert) a Donation with sane defaults for the test donor."""
        donation = frappe.new_doc("Donation")
        donation.donor = overrides.pop("donor", self.test_donor.name)
        donation.amount = overrides.pop("amount", 100)
        donation.donation_date = overrides.pop("donation_date", frappe.utils.today())
        donation.company = overrides.pop("company", self.test_company)
        donation.mode_of_payment = overrides.pop("mode_of_payment", self._ensure_mode_of_payment())
        for key, value in overrides.items():
            setattr(donation, key, value)
        return donation

    def _insert_donation(self, **overrides):
        """Build and insert a Donation (inserts trigger email enqueue -> patch sendmail)."""
        donation = self._make_donation(**overrides)
        with patch("frappe.sendmail"):
            donation.insert()
        return donation

    def _make_donor(self, **overrides):
        """Create and insert a Donor with a unique name/email."""
        donor = frappe.new_doc("Donor")
        donor.donor_name = overrides.pop(
            "donor_name", f"Helper Donor {self.test_run_id} {frappe.generate_hash()[:6]}"
        )
        donor.donor_type = overrides.pop("donor_type", "Individual")
        donor.donor_email = overrides.pop(
            "donor_email", f"helper-{self.test_run_id}-{frappe.generate_hash()[:6]}@example.com"
        )
        for key, value in overrides.items():
            setattr(donor, key, value)
        donor.insert()
        return donor

    # ------------------------------------------------------------------
    # validate() — donor requirement
    # ------------------------------------------------------------------
    def test_missing_donor_throws_for_non_website_user(self):
        """A non-website user must explicitly select a Donor (validate throws)."""
        donation = self._make_donation()
        donation.donor = None
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    # ------------------------------------------------------------------
    # validate_anbi_agreement()
    # ------------------------------------------------------------------
    def test_anbi_number_without_date_throws(self):
        """ANBI Agreement Number without a date is rejected."""
        donation = self._make_donation()
        donation.anbi_agreement_number = "ANBI-2024-001"
        donation.anbi_agreement_date = None
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_anbi_date_without_number_throws(self):
        """ANBI Agreement Date without a number is rejected."""
        donation = self._make_donation()
        donation.anbi_agreement_number = None
        donation.anbi_agreement_date = frappe.utils.today()
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_anbi_number_and_date_together_is_valid(self):
        """Providing both ANBI number and date passes validation and persists."""
        donation = self._insert_donation(
            anbi_agreement_number="ANBI-2024-099",
            anbi_agreement_date=frappe.utils.today(),
        )
        donation.reload()
        self.assertEqual(donation.anbi_agreement_number, "ANBI-2024-099")

    # ------------------------------------------------------------------
    # validate_donation_purpose()
    # ------------------------------------------------------------------
    def test_campaign_purpose_requires_reference(self):
        """Campaign purpose type without a campaign reference is rejected."""
        donation = self._make_donation(donation_purpose_type="Campaign")
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_campaign_purpose_accepts_notes_fallback(self):
        """Campaign purpose is allowed when a 'Campaign:' marker is in notes
        (fallback for campaigns that do not yet exist as Donation Campaign docs)."""
        donation = self._insert_donation(
            donation_purpose_type="Campaign",
            donation_notes="Campaign: Spring Fundraiser 2024",
        )
        donation.reload()
        self.assertEqual(donation.donation_purpose_type, "Campaign")

    def test_chapter_purpose_requires_chapter(self):
        """Chapter purpose type without a chapter reference is rejected."""
        donation = self._make_donation(donation_purpose_type="Chapter")
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_invalid_chapter_reference_throws(self):
        """A non-existent chapter reference is rejected."""
        donation = self._make_donation(
            donation_purpose_type="Chapter",
            chapter_reference=f"Nonexistent Chapter {frappe.generate_hash()[:8]}",
        )
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_valid_chapter_purpose(self):
        """A donation earmarked for an existing chapter validates and persists."""
        # Create our own Chapter — a fresh CI shard has none (querying for an
        # arbitrary existing Chapter is order-dependent and fails in isolation).
        chapter_name = self.create_test_chapter().name
        donation = self._insert_donation(
            donation_purpose_type="Chapter",
            chapter_reference=chapter_name,
        )
        donation.reload()
        self.assertEqual(donation.chapter_reference, chapter_name)

    def test_specific_goal_requires_description_for_privileged_user(self):
        """Specific Goal without a description throws for a user who can write."""
        donation = self._make_donation(donation_purpose_type="Specific Goal")
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_specific_goal_with_description_is_valid(self):
        """Specific Goal with a description validates and persists."""
        donation = self._insert_donation(
            donation_purpose_type="Specific Goal",
            specific_goal_description="Build a new shelter for rescued animals",
        )
        donation.reload()
        self.assertEqual(donation.donation_purpose_type, "Specific Goal")

    # ------------------------------------------------------------------
    # get_earmarking_summary()
    # ------------------------------------------------------------------
    def test_earmarking_summary_general(self):
        """General donations summarize to the General Fund."""
        donation = self._insert_donation(donation_purpose_type="General")
        self.assertEqual(donation.get_earmarking_summary(), "General Fund")

    def test_earmarking_summary_chapter(self):
        """Chapter donations summarize with the chapter name."""
        # Create our own Chapter (a fresh CI shard has none — see above).
        chapter_name = self.create_test_chapter().name
        donation = self._insert_donation(donation_purpose_type="Chapter", chapter_reference=chapter_name)
        self.assertEqual(donation.get_earmarking_summary(), f"Chapter: {chapter_name}")

    def test_earmarking_summary_specific_goal_short(self):
        """Short specific-goal descriptions are returned in full."""
        donation = self._insert_donation(
            donation_purpose_type="Specific Goal",
            specific_goal_description="Short goal",
        )
        self.assertEqual(donation.get_earmarking_summary(), "Specific Goal: Short goal")

    def test_earmarking_summary_specific_goal_long_truncates(self):
        """Long specific-goal descriptions are truncated to 50 chars with an ellipsis."""
        long_desc = "x" * 80
        donation = self._insert_donation(
            donation_purpose_type="Specific Goal",
            specific_goal_description=long_desc,
        )
        summary = donation.get_earmarking_summary()
        self.assertTrue(summary.startswith("Specific Goal: " + "x" * 50))
        self.assertTrue(summary.endswith("..."))

    # ------------------------------------------------------------------
    # generate_anbi_report_data()
    # ------------------------------------------------------------------
    def test_generate_anbi_report_data_none_without_agreement_number(self):
        """No ANBI agreement number -> no report data."""
        donation = self._insert_donation()
        self.assertIsNone(donation.generate_anbi_report_data())

    def test_generate_anbi_report_data_with_agreement_number(self):
        """With an ANBI agreement number, report data reflects the donation/donor."""
        donation = self._insert_donation(
            anbi_agreement_number="ANBI-2024-555",
            anbi_agreement_date=frappe.utils.today(),
            amount=250,
        )
        data = donation.generate_anbi_report_data()
        self.assertIsNotNone(data)
        self.assertEqual(data["anbi_agreement_number"], "ANBI-2024-555")
        self.assertEqual(data["amount"], 250)
        self.assertEqual(data["donor_name"], self.test_donor.donor_name)
        self.assertEqual(data["donation_id"], donation.name)
        # Regression: generate_anbi_report_data() used to crash with
        # AttributeError on self.donation_type (no such field on Donation).
        # It now tolerates the missing field and returns None for it.
        self.assertIsNone(data["donation_type"])

    # ------------------------------------------------------------------
    # on_payment_authorized()  (legacy hook)
    # ------------------------------------------------------------------
    def test_on_payment_authorized_sets_paid(self):
        """The legacy on_payment_authorized hook marks the donation as paid."""
        donation = self._insert_donation(paid=0)
        self.assertEqual(donation.paid, 0)
        with patch("frappe.sendmail"):
            donation.on_payment_authorized()
        donation.reload()
        self.assertEqual(donation.paid, 1)

    # ------------------------------------------------------------------
    # validate_periodic_donation_agreement() — error branches
    # ------------------------------------------------------------------
    def test_periodic_agreement_donor_mismatch_throws(self):
        """A donation whose donor does not match the agreement donor is rejected."""
        with patch("frappe.sendmail"):
            linked = self._create_periodic_agreement_donation()
        agreement_name = linked.periodic_donation_agreement

        other_donor = self._make_donor()
        donation = self._make_donation(
            donor=other_donor.name,
            periodic_donation_agreement=agreement_name,
        )
        with self.assertRaises(frappe.ValidationError):
            with patch("frappe.sendmail"):
                donation.insert()

    def test_periodic_agreement_autopopulates_anbi_fields(self):
        """Linking a periodic agreement copies its ANBI number/date onto the donation
        and forces status to Recurring + belastingdienst_reportable."""
        with patch("frappe.sendmail"):
            donation = self._create_periodic_agreement_donation()
        donation.reload()
        agreement = frappe.get_doc("Periodic Donation Agreement", donation.periodic_donation_agreement)
        if agreement.agreement_number:
            self.assertEqual(donation.anbi_agreement_number, agreement.agreement_number)
        self.assertEqual(donation.status, "Recurring")
        self.assertEqual(donation.belastingdienst_reportable, 1)

    # ------------------------------------------------------------------
    # Whitelisted: create_donor_from_donation
    # ------------------------------------------------------------------
    def test_create_donor_from_donation_explicit_type(self):
        """create_donor_from_donation creates a Donor with the given fields."""
        from verenigingen.verenigingen.doctype.donation.donation import create_donor_from_donation

        email = f"new-donor-{self.test_run_id}-{frappe.generate_hash()[:6]}@example.com"
        donor = create_donor_from_donation(
            donor_name="API Created Donor", email=email, phone="+31612345678", donor_type="Individual"
        )
        self.assertTrue(frappe.db.exists("Donor", donor.name))
        self.assertEqual(donor.donor_email, email)
        self.assertEqual(donor.donor_type, "Individual")
        self.assertEqual(donor.phone, "+31612345678")

    def test_create_donor_from_donation_defaults_type_from_settings(self):
        """When donor_type is omitted it falls back to the Verenigingen Settings default."""
        from verenigingen.verenigingen.doctype.donation.donation import create_donor_from_donation

        default_type = frappe.db.get_single_value("Verenigingen Settings", "default_donor_type")
        email = f"defaulted-donor-{self.test_run_id}-{frappe.generate_hash()[:6]}@example.com"
        donor = create_donor_from_donation(donor_name="Defaulted Donor", email=email)
        self.assertTrue(frappe.db.exists("Donor", donor.name))
        if default_type:
            self.assertEqual(donor.donor_type, default_type)

    # ------------------------------------------------------------------
    # Whitelisted: generate_anbi_agreement_number
    # ------------------------------------------------------------------
    def test_generate_anbi_agreement_number_format(self):
        """The generated ANBI agreement number follows ANBI-<year>-<NNN>."""
        from verenigingen.verenigingen.doctype.donation.donation import generate_anbi_agreement_number

        number = generate_anbi_agreement_number()
        parts = number.split("-")
        self.assertEqual(parts[0], "ANBI")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[2]), 3)
        self.assertTrue(parts[2].isdigit())

    def test_generate_anbi_agreement_number_increments(self):
        """The generated number increments off the most recent stored ANBI number."""
        from verenigingen.verenigingen.doctype.donation.donation import generate_anbi_agreement_number

        # Persist a donation with a known ANBI number so it is the latest by creation
        self._insert_donation(
            anbi_agreement_number="ANBI-2099-042",
            anbi_agreement_date=frappe.utils.today(),
        )
        number = generate_anbi_agreement_number()
        self.assertEqual(number, "ANBI-2099-043")

    # ------------------------------------------------------------------
    # get_company_for_donations
    # ------------------------------------------------------------------
    def test_get_company_for_donations_returns_company(self):
        """get_company_for_donations returns a real, existing company."""
        from verenigingen.verenigingen.doctype.donation.donation import get_company_for_donations

        company = get_company_for_donations()
        self.assertTrue(company)
        self.assertTrue(frappe.db.exists("Company", company))

    # ------------------------------------------------------------------
    # on_update() — paid transition enqueues payment confirmation
    # ------------------------------------------------------------------
    def test_marking_paid_enqueues_payment_confirmation(self):
        """Marking a donation paid for the first time enqueues the payment email."""
        donation = self._insert_donation(paid=0)
        with (
            patch("verenigingen.verenigingen.doctype.donation.donation.frappe.enqueue") as mock_enqueue,
            patch("frappe.sendmail"),
        ):
            donation.paid = 1
            donation.save()
        enqueued = [c for c in mock_enqueue.call_args_list if "send_payment_confirmation_email" in str(c)]
        self.assertTrue(enqueued, "Expected payment confirmation email to be enqueued on paid transition")
