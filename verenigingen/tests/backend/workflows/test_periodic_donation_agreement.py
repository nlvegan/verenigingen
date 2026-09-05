"""
Test Periodic Donation Agreement functionality
Tests the enhanced donation agreement system following testing standards
"""

import frappe
from frappe.utils import today, add_years, add_months, getdate
from datetime import datetime
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPeriodicDonationAgreement(EnhancedTestCase):
    """
    Integration tests for Periodic Donation Agreement following testing standards.

    Tests donation agreement lifecycle including recurring donations,
    SEPA integration, and payment processing workflows.

    External Services Mocked:
    - Email sending (frappe.sendmail)

    Real Integrations Tested:
    - Database operations and field validation
    - Business rule enforcement
    - SEPA mandate integration
    """

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()

        # Clean up any stale test data from previous runs
        self._cleanup_stale_pda_test_data()

        self.test_donor = self._get_or_create_pda_test_donor()
        self.test_sepa_mandate = self._get_or_create_pda_test_sepa_mandate()

    def _cleanup_stale_pda_test_data(self):
        """Clean up stale test data that may prevent test execution.

        Renamed from `_cleanup_stale_test_data` (#496): that name shadows
        `EnhancedTestCase._cleanup_stale_test_data`, which the harness's own
        `setUp()` calls unconditionally (gated only by a once-per-class flag).
        This override deletes exactly the two named PDA fixture donors and
        their agreements -- unrelated to the harness's site-wide, developer-mode
        + approved-site-gated cleanup, which this shadow replaced entirely for
        every test in this class.
        """
        # Clean up any existing test donors and their agreements
        for donor_name in ["TEST-PDA-Donor-001", "TEST-PDA-Other-Donor"]:
            existing = frappe.db.exists("Donor", {"donor_name": donor_name})
            if existing:
                # First delete any agreements for this donor
                agreements = frappe.get_all(
                    "Periodic Donation Agreement",
                    filters={"donor": existing}
                )
                for agreement in agreements:
                    try:
                        frappe.delete_doc("Periodic Donation Agreement", agreement.name, force=True)
                    except Exception:
                        pass
        frappe.db.commit()

    def _get_or_create_pda_test_donor(self):
        """Create a test donor with ANBI consent and required fields.

        Renamed from `create_test_donor` (#496): that name shadows
        `EnhancedTestCase.create_test_donor(**kwargs)`, which
        `create_test_donation()` calls internally for any caller that omits
        `donor=`. This override takes no arguments and always resolves to a
        fixed named donor (TEST-PDA-Donor-001), unlike the harness version's
        unique-per-call donor -- latent because this class never calls
        `create_test_donation()` today.
        """
        donor_name = "TEST-PDA-Donor-001"

        # Check if donor exists - if so, ensure it has required fields
        existing = frappe.db.exists("Donor", {"donor_name": donor_name})
        if existing:
            donor = frappe.get_doc("Donor", existing)
            # Update BSN if missing - use valid eleven-proof BSN
            needs_save = False
            if hasattr(donor, 'bsn_citizen_service_number') and not donor.bsn_citizen_service_number:
                donor.bsn_citizen_service_number = "111222333"  # Valid Dutch eleven-proof BSN
                needs_save = True
            if not donor.donor_type:
                donor.donor_type = "Individual"
                needs_save = True
            if needs_save:
                donor.save()
            return donor

        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_email = "pda-test@example.com"
        donor.donor_type = "Individual"  # Required field
        # BSN is required for individual donors in ANBI agreements
        if hasattr(donor, 'bsn_citizen_service_number'):
            donor.bsn_citizen_service_number = "111222333"  # Valid Dutch eleven-proof BSN
        if hasattr(donor, 'anbi_consent'):
            donor.anbi_consent = 1
            donor.anbi_consent_date = frappe.utils.now()
        if hasattr(donor, 'identification_verified'):
            donor.identification_verified = 1
            donor.identification_verification_date = today()
            donor.identification_verification_method = "Manual"
        donor.insert()
        return donor

    def _get_or_create_pda_test_sepa_mandate(self):
        """Create a test SEPA mandate.

        Renamed from `create_test_sepa_mandate` (#496): that name shadows
        `EnhancedTestCase.create_test_sepa_mandate(member_name=None, iban=None,
        **kwargs)`, which `create_test_mollie_subscription()` calls internally
        with `member_name=...`. This override takes no arguments and always
        resolves to a fixed named mandate (TEST-PDA-SEPA-001) linked to a
        donor, not a member -- latent because this class never calls
        `create_test_mollie_subscription()` today.
        """
        mandate_id = "TEST-PDA-SEPA-001"

        if not frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id}):
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.mandate_id = mandate_id
            mandate.donor = self.test_donor.name
            mandate.iban = "NL91ABNA0417164300"  # Valid test IBAN per testing standards
            mandate.bic = "ABNANL2A"
            mandate.mandate_type = "RCUR"
            mandate.status = "Active"
            mandate.valid_from = today()
            mandate.account_holder_name = "TEST-PDA-Donor-001"  # Required field
            mandate.sign_date = today()  # Required field
            mandate.insert()
            return mandate

        return frappe.get_doc("SEPA Mandate", {"mandate_id": mandate_id})

    def tearDown(self):
        """Clean up after each test"""
        # Clean up test agreements
        test_agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters={"donor": self.test_donor.name}
        )
        for agreement in test_agreements:
            try:
                doc = frappe.get_doc("Periodic Donation Agreement", agreement.name)
                if doc.docstatus == 0:
                    doc.delete()
            except Exception:
                pass

        frappe.db.commit()
        super().tearDown()

    def test_create_periodic_donation_agreement(self):
        """Test creating a periodic donation agreement with correct schema"""
        # Mock justified: External Service - email service, not business logic under test
        with patch('frappe.sendmail') as mock_email:
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor.name
            agreement.agreement_type = "Private Written"  # Valid option: Notarial or Private Written
            agreement.start_date = today()
            agreement.annual_amount = 1200  # Correct field name
            agreement.payment_frequency = "Monthly"  # Correct field name
            agreement.payment_method = "SEPA Direct Debit"
            agreement.sepa_mandate = self.test_sepa_mandate.name
            agreement.status = "Draft"
            agreement.agreement_duration_years = "5 Years (ANBI Minimum)"

            agreement.insert()

        # Verify real database changes
        self.assertEqual(agreement.donor, self.test_donor.name)
        self.assertEqual(agreement.agreement_type, "Private Written")
        self.assertEqual(agreement.annual_amount, 1200)
        self.assertEqual(agreement.payment_frequency, "Monthly")
        self.assertEqual(agreement.sepa_mandate, self.test_sepa_mandate.name)

        # Verify payment_amount is auto-calculated (1200 / 12 = 100)
        self.assertEqual(agreement.payment_amount, 100)

        # Verify field references are valid (per testing standards)
        agreement.reload()
        self.assertEqual(agreement.donor, self.test_donor.name)

    def test_payment_amount_calculations(self):
        """Test payment amount calculations for different frequencies"""
        test_cases = [
            ("Monthly", 1200, 100),      # 1200/12
            ("Quarterly", 1200, 300),    # 1200/4
            ("Annually", 1200, 1200),    # 1200/1
        ]

        for frequency, annual, expected in test_cases:
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor.name
            agreement.agreement_type = "Private Written"
            agreement.start_date = today()
            agreement.annual_amount = annual
            agreement.payment_frequency = frequency
            agreement.payment_method = "Bank Transfer"
            agreement.agreement_duration_years = "5 Years (ANBI Minimum)"

            agreement.calculate_payment_amount()

            self.assertEqual(
                agreement.payment_amount,
                expected,
                f"Payment amount calculation failed for {frequency}"
            )

    def test_minimum_duration_validation_for_anbi(self):
        """Test that ANBI agreements must be for minimum 5 years"""
        # Create an agreement with ANBI eligibility but less than 5 years
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        # Set a duration less than 5 years
        agreement.agreement_duration_years = "3 Years (Pledge - No ANBI benefits)"
        # But claim ANBI eligibility - this should cause validation to fail
        agreement.anbi_eligible = 1

        # Should throw error for claiming ANBI with less than 5 years
        with self.assertRaises(frappe.ValidationError):
            agreement.insert()

    def test_link_donation_to_agreement(self):
        """Test linking donations to agreements"""
        # Mock justified: External Service - email service, not business logic under test
        with patch('frappe.sendmail') as mock_email:
            # Create agreement
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor.name
            agreement.agreement_type = "Private Written"
            agreement.start_date = today()
            agreement.annual_amount = 1200
            agreement.payment_frequency = "Monthly"
            agreement.payment_method = "Bank Transfer"
            agreement.status = "Active"
            agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
            agreement.insert()

            # Get or create a mode of payment
            mode_of_payment = "Cash"  # Standard ERPNext mode of payment
            if not frappe.db.exists("Mode of Payment", mode_of_payment):
                mode_doc = frappe.new_doc("Mode of Payment")
                mode_doc.mode_of_payment = mode_of_payment
                mode_doc.enabled = 1
                mode_doc.type = "Cash"
                mode_doc.insert()

            # Create donation with agreement link
            donation = frappe.new_doc("Donation")
            donation.donor = self.test_donor.name
            donation.donation_date = today()
            donation.amount = 100
            donation.mode_of_payment = mode_of_payment
            donation.periodic_donation_agreement = agreement.name
            donation.paid = 1
            donation.insert()

        # Verify real database changes and field references
        self.assertEqual(donation.donor, self.test_donor.name)
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)
        self.assertEqual(donation.amount, 100)

        # Test field reference validation (per testing standards)
        donation.reload()
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)
        agreement.reload()
        self.assertEqual(agreement.donor, self.test_donor.name)

    def test_agreement_number_generation(self):
        """Test unique agreement number generation"""
        year = datetime.now().year

        # Create first agreement
        agreement1 = frappe.new_doc("Periodic Donation Agreement")
        agreement1.donor = self.test_donor.name
        agreement1.agreement_type = "Private Written"
        agreement1.start_date = today()
        agreement1.annual_amount = 1000
        agreement1.payment_frequency = "Annually"
        agreement1.payment_method = "Bank Transfer"
        agreement1.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement1.insert()

        # Create second agreement
        agreement2 = frappe.new_doc("Periodic Donation Agreement")
        agreement2.donor = self.test_donor.name
        agreement2.agreement_type = "Private Written"
        agreement2.start_date = today()
        agreement2.annual_amount = 2000
        agreement2.payment_frequency = "Annually"
        agreement2.payment_method = "Bank Transfer"
        agreement2.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement2.insert()

        # Verify unique sequential numbers
        self.assertTrue(agreement1.agreement_number.startswith(f"PDA-{year}-"))
        self.assertTrue(agreement2.agreement_number.startswith(f"PDA-{year}-"))
        self.assertNotEqual(agreement1.agreement_number, agreement2.agreement_number)

    def test_donor_mismatch_validation(self):
        """Test that donations from different donors cannot be linked"""
        # Create another donor
        other_donor = frappe.new_doc("Donor")
        other_donor.donor_name = "TEST-PDA-Other-Donor"
        other_donor.donor_email = "other-pda@example.com"
        other_donor.donor_type = "Individual"  # Required field
        other_donor.insert()

        try:
            # Create agreement for first donor
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor.name
            agreement.agreement_type = "Private Written"
            agreement.start_date = today()
            agreement.annual_amount = 1200
            agreement.payment_frequency = "Monthly"
            agreement.payment_method = "Bank Transfer"
            agreement.status = "Active"
            agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
            agreement.insert()

            # Get or create a mode of payment
            mode_of_payment = "Cash"
            if not frappe.db.exists("Mode of Payment", mode_of_payment):
                mode_doc = frappe.new_doc("Mode of Payment")
                mode_doc.mode_of_payment = mode_of_payment
                mode_doc.enabled = 1
                mode_doc.type = "Cash"
                mode_doc.insert()

            # Create donation from other donor
            donation = frappe.new_doc("Donation")
            donation.donor = other_donor.name
            donation.donation_date = today()
            donation.amount = 100
            donation.mode_of_payment = mode_of_payment
            donation.paid = 1
            donation.insert()

            # Try to link - should fail
            with self.assertRaises(frappe.ValidationError):
                agreement.link_donation(donation.name)
        finally:
            # Clean up
            try:
                frappe.delete_doc("Donor", other_donor.name, force=True)
            except Exception:
                pass

    def test_next_donation_date_calculation(self):
        """Test calculation of next expected donation date"""
        # Create agreement with monthly frequency
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.insert()

        # Without any donations, next date should be start date
        agreement.calculate_next_donation_date()
        self.assertEqual(getdate(agreement.next_expected_donation), getdate(agreement.start_date))

        # Add a donation (simulate last_donation_date being set)
        agreement.last_donation_date = today()
        agreement.calculate_next_donation_date()

        expected_next = add_months(getdate(today()), 1)
        self.assertEqual(getdate(agreement.next_expected_donation), expected_next)

    def test_cancel_agreement(self):
        """Test agreement cancellation"""
        # Create active agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.insert()

        # Cancel agreement
        agreement.cancel_agreement(reason="Donor requested cancellation")

        # Verify cancellation
        self.assertEqual(agreement.status, "Cancelled")
        self.assertEqual(getdate(agreement.cancellation_date), getdate(today()))
        self.assertEqual(agreement.cancellation_reason, "Donor requested cancellation")
        self.assertEqual(agreement.cancellation_processed_by, frappe.session.user)

    def test_agreement_with_sepa_mandate(self):
        """Test agreement with SEPA mandate"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor.name
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.sepa_mandate = self.test_sepa_mandate.name
        agreement.status = "Active"
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.insert()

        # Verify SEPA mandate is linked
        self.assertEqual(agreement.sepa_mandate, self.test_sepa_mandate.name)

        # Get or create a mode of payment for SEPA
        mode_of_payment = "Bank Transfer"
        if not frappe.db.exists("Mode of Payment", mode_of_payment):
            mode_doc = frappe.new_doc("Mode of Payment")
            mode_doc.mode_of_payment = mode_of_payment
            mode_doc.enabled = 1
            mode_doc.type = "Bank"
            mode_doc.insert()

        # Create donation with same SEPA mandate
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor.name
        donation.donation_date = today()
        donation.amount = 100
        donation.mode_of_payment = mode_of_payment
        donation.sepa_mandate = self.test_sepa_mandate.name
        donation.periodic_donation_agreement = agreement.name
        donation.paid = 1
        donation.insert()

        # Verify donation is properly linked
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)


def run_tests():
    """Run the test suite"""
    import unittest
    frappe.connect()
    unittest.main(module=__name__, exit=False, verbosity=2)
