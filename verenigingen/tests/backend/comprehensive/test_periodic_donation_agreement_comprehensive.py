"""
Comprehensive Unit Tests for Periodic Donation Agreement
Including edge cases and error scenarios
"""

import frappe
from frappe.utils import today, add_years, add_months, getdate, flt
from datetime import datetime
from decimal import Decimal
from verenigingen.tests.utils.base import VereningingenTestCase


class TestPeriodicDonationAgreementComprehensive(VereningingenTestCase):
    
    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.test_company = frappe.db.get_single_value("Verenigingen Settings", "donation_company") or "Test Company"
        self.test_donor = self.create_test_donor()
    
    # Cleanup is now handled automatically by VereningingenTestCase
    
    def create_test_donor(self, suffix=""):
        """Create a test donor using factory method"""
        donor = super().create_test_donor(
            donor_name=f"TEST-PDA-Donor-{frappe.utils.random_string(5)}{suffix}",
            donor_email=f"test-pda-{frappe.utils.random_string(5)}@example.com",
            donor_type="Individual"
        )
        return donor.name
    
    # Basic Functionality Tests
    
    def test_create_agreement_with_defaults(self):
        """Test creating agreement with default values"""
        agreement = self.create_test_periodic_donation_agreement(
            donor=self.test_donor,
            start_date=today(),
            annual_amount=1200,
            payment_frequency="Monthly",
            payment_method="Bank Transfer"
        )
        
        # Verify defaults
        self.assertEqual(agreement.status, "Draft")
        self.assertEqual(agreement.agreement_duration_years, "5 Years (ANBI Minimum)")
        self.assertEqual(agreement.anbi_eligible, 1)
        self.assertIsNotNone(agreement.agreement_number)
        
        # Verify calculations
        expected_end = add_years(getdate(agreement.start_date), 5)
        self.assertEqual(getdate(agreement.end_date), expected_end)
        self.assertEqual(agreement.payment_amount, 100)  # 1200/12
    
    def test_duration_variations(self):
        """Test different agreement durations"""
        test_cases = [
            ("1 Year (Pledge - No ANBI benefits)", 1, False),  # Non-ANBI
            ("3 Years (Pledge - No ANBI benefits)", 3, False),  # Non-ANBI
            ("5 Years (ANBI Minimum)", 5, True),  # ANBI minimum
            ("7 Years (ANBI)", 7, True),  # ANBI eligible
            ("10 Years (ANBI)", 10, True),  # Maximum duration
        ]
        
        for duration_str, expected_years, is_anbi in test_cases:
            agreement = self.create_test_periodic_donation_agreement(
                donor=self.test_donor,
                start_date=today(),
                agreement_duration_years=duration_str,
                anbi_eligible=1 if is_anbi else 0,
                annual_amount=1000,
                payment_frequency="Annually",
                payment_method="Bank Transfer"
            )
            
            # Verify duration calculation
            expected_end = add_years(getdate(agreement.start_date), expected_years)
            self.assertEqual(
                getdate(agreement.end_date), 
                expected_end,
                f"Failed for duration: {duration_str}"
            )
    
    # Payment Calculation Tests
    
    def test_payment_calculations_edge_cases(self):
        """Test payment calculations with edge cases"""
        test_cases = [
            # (annual_amount, frequency, expected_payment)
            (1200, "Monthly", 100),
            (1200, "Quarterly", 300),
            (1200, "Annually", 1200),
            (1000, "Monthly", 83.33),  # Rounding test
            (999, "Monthly", 83.25),  # Rounding test
            (1, "Monthly", 0.08),  # Minimum amount
            (1000000, "Monthly", 83333.33),  # Large amount
            (365, "Monthly", 30.42),  # Daily equivalent
        ]
        
        for annual, frequency, expected in test_cases:
            agreement = self.create_test_periodic_donation_agreement(
                donor=self.test_donor,
                start_date=today(),
                annual_amount=annual,
                payment_frequency=frequency,
                payment_method="Bank Transfer"
            )
            
            agreement.calculate_payment_amount()
            
            self.assertAlmostEqual(
                float(agreement.payment_amount),
                expected,
                places=2,
                msg=f"Failed for {annual} {frequency}"
            )
    
    # Validation Tests
    
    def test_anbi_duration_validation(self):
        """Test ANBI eligibility duration validation"""
        # Non-ANBI agreement can be < 5 years
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.end_date = add_years(today(), 2)  # 2 years
        agreement.anbi_eligible = 0
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        
        # Should not throw error
        agreement.insert()
        
        # ANBI agreement must be >= 5 years - should throw error
        with self.assertRaises(frappe.ValidationError):
            agreement2 = self.create_test_periodic_donation_agreement(
                donor=self.test_donor,
                start_date=today(),
                end_date=add_years(today(), 4),  # 4 years
                anbi_eligible=1,
                annual_amount=1000,
                payment_frequency="Annually",
                payment_method="Bank Transfer"
            )
    
    def test_date_validation_edge_cases(self):
        """Test date validation edge cases"""
        # End date before start date - should throw error
        with self.assertRaises(frappe.ValidationError):
            agreement = self.create_test_periodic_donation_agreement(
                donor=self.test_donor,
                start_date=today(),
                end_date=add_months(today(), -1),
                annual_amount=1000,
                payment_frequency="Monthly",
                payment_method="Bank Transfer"
            )
        
        # Same start and end date - should throw error
        with self.assertRaises(frappe.ValidationError):
            agreement2 = self.create_test_periodic_donation_agreement(
                donor=self.test_donor,
                start_date=today(),
                end_date=today(),
                annual_amount=1000,
                payment_frequency="Monthly",
                payment_method="Bank Transfer"
            )
    
    # Donation Linking Tests
    
    def test_donation_linking_edge_cases(self):
        """Test edge cases in donation linking"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Test 1: Link valid donation
        donation1 = self.create_test_donation(self.test_donor, 100)
        agreement.link_donation(donation1.name)
        self.assertEqual(len(agreement.donations), 1)
        
        # Test 2: Try to link same donation again
        with self.assertRaises(frappe.ValidationError):
            agreement.link_donation(donation1.name)
        
        # Test 3: Try to link donation from different donor
        other_donor = self.create_test_donor("-other")
        donation2 = self.create_test_donation(other_donor, 100)
        
        with self.assertRaises(frappe.ValidationError):
            agreement.link_donation(donation2.name)
        
        # Test 4: Link multiple donations
        donation3 = self.create_test_donation(self.test_donor, 100)
        donation4 = self.create_test_donation(self.test_donor, 100)
        
        agreement.link_donation(donation3.name)
        agreement.link_donation(donation4.name)
        
        self.assertEqual(len(agreement.donations), 3)
        self.assertEqual(agreement.total_donated, 300)
        self.assertEqual(agreement.donations_count, 3)
    
    def create_test_donation(self, donor, amount, paid=True):
        """Helper to create test donation"""
        donation = frappe.new_doc("Donation")
        donation.donor = donor
        donation.date = today()
        donation.amount = amount
        donation.payment_method = "Bank Transfer"
        donation.donation_type = "General"
        donation.company = self.test_company
        donation.paid = 1 if paid else 0
        donation.insert()
        donation.submit()
        return donation
    
    # Agreement Number Generation Tests
    
    def test_agreement_number_uniqueness(self):
        """Test agreement number generation uniqueness"""
        numbers = set()
        
        # Create multiple agreements
        for i in range(10):
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor
            agreement.start_date = today()
            agreement.annual_amount = 1000 + i
            agreement.payment_frequency = "Monthly"
            agreement.payment_method = "Bank Transfer"
            agreement.insert()
            
            # Check uniqueness
            self.assertNotIn(agreement.agreement_number, numbers)
            numbers.add(agreement.agreement_number)
            
            # Check format
            self.assertTrue(agreement.agreement_number.startswith("PDA-"))
            self.assertIn(str(datetime.now().year), agreement.agreement_number)
    
    # Next Donation Date Calculation Tests
    
    def test_next_donation_date_calculations(self):
        """Test next expected donation date calculations"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Test 1: No donations yet
        agreement.calculate_next_donation_date()
        self.assertEqual(agreement.next_expected_donation, agreement.start_date)
        
        # Test 2: After first donation
        agreement.last_donation_date = today()
        agreement.calculate_next_donation_date()
        expected_next = add_months(getdate(today()), 1)
        self.assertEqual(getdate(agreement.next_expected_donation), expected_next)
        
        # Test 3: Quarterly frequency
        agreement.payment_frequency = "Quarterly"
        agreement.calculate_next_donation_date()
        expected_next = add_months(getdate(today()), 3)
        self.assertEqual(getdate(agreement.next_expected_donation), expected_next)
        
        # Test 4: Near end of agreement
        agreement.last_donation_date = add_months(agreement.end_date, -1)
        agreement.calculate_next_donation_date()
        self.assertIsNone(agreement.next_expected_donation)  # Beyond end date
    
    # Cancellation Tests
    
    def test_agreement_cancellation_scenarios(self):
        """Test various cancellation scenarios"""
        # Create active agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Test 1: Cancel without reason
        original_status = agreement.status
        agreement.cancel_agreement()  # Should use default reason
        
        self.assertEqual(agreement.status, "Cancelled")
        self.assertEqual(agreement.cancellation_date, today())
        self.assertEqual(agreement.cancellation_reason, "Cancelled by donor request")
        self.assertEqual(agreement.cancellation_processed_by, frappe.session.user)
        
        # Test 2: Already cancelled
        with self.assertRaises(frappe.ValidationError):
            agreement.cancel_agreement("Another reason")
    
    # SEPA Integration Tests
    
    def test_sepa_mandate_integration(self):
        """Test SEPA mandate integration"""
        # Create SEPA mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.donor = self.test_donor
        mandate.mandate_id = f"TEST-SEPA-{frappe.utils.random_string(8)}"
        mandate.iban = "NL91ABNA0417164300"
        mandate.bic = "ABNANL2A"
        mandate.mandate_type = "RCUR"
        mandate.status = "Active"
        mandate.valid_from = today()
        mandate.insert()
        
        # Create agreement with SEPA
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.sepa_mandate = mandate.name
        agreement.status = "Active"
        agreement.insert()
        
        # Create donation with SEPA
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor
        donation.date = today()
        donation.amount = 100
        donation.payment_method = "SEPA Direct Debit"
        donation.sepa_mandate = mandate.name
        donation.periodic_donation_agreement = agreement.name
        donation.donation_type = "General"
        donation.company = self.test_company
        donation.insert()
        donation.submit()
        
        # Verify linkage
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)
        self.assertEqual(donation.sepa_mandate, mandate.name)
    
    # Email Notification Tests
    
    def test_email_notification_scenarios(self):
        """Test email notification scenarios"""
        # Create donor with email
        donor = frappe.new_doc("Donor")
        donor.donor_name = "TEST-PDA-Email-Donor"
        donor.donor_email = "test@example.com"
        donor.donor_type = "Individual"
        donor.insert()
        
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor.name
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Draft"
        agreement.insert()
        
        # Test activation email
        agreement.status = "Active"
        agreement.save()
        
        # Note: Actual email sending is mocked in tests
        # We're just testing that methods don't throw errors
        
        # Test expiry notification
        agreement.end_date = add_months(today(), 3)  # 90 days
        agreement.check_expiry_notification()
    
    # Error Handling Tests
    
    def test_error_scenarios(self):
        """Test various error scenarios"""
        # Test 1: Invalid annual amount
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = -100  # Negative amount
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        
        with self.assertRaises(frappe.ValidationError):
            agreement.insert()
        
        # Test 2: Zero annual amount
        agreement2 = frappe.new_doc("Periodic Donation Agreement")
        agreement2.donor = self.test_donor
        agreement2.start_date = today()
        agreement2.annual_amount = 0
        agreement2.payment_frequency = "Monthly"
        agreement2.payment_method = "Bank Transfer"
        
        with self.assertRaises(frappe.ValidationError):
            agreement2.insert()
        
        # Test 3: Missing required fields
        agreement3 = frappe.new_doc("Periodic Donation Agreement")
        agreement3.donor = self.test_donor
        # Missing start_date
        agreement3.annual_amount = 1000
        agreement3.payment_frequency = "Monthly"
        agreement3.payment_method = "Bank Transfer"
        
        with self.assertRaises(frappe.ValidationError):
            agreement3.insert()
    
    # Performance Tests
    
    def test_large_donation_tracking(self):
        """Test performance with many linked donations"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = add_years(today(), -2)  # 2 years ago
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Create 24 monthly donations (2 years)
        import time
        start_time = time.time()
        
        for month in range(24):
            donation_date = add_months(agreement.start_date, month)
            donation = frappe.new_doc("Donation")
            donation.donor = self.test_donor
            donation.date = donation_date
            donation.amount = 100
            donation.payment_method = "Bank Transfer"
            donation.donation_type = "General"
            donation.company = self.test_company
            donation.periodic_donation_agreement = agreement.name
            donation.paid = 1
            donation.insert()
            donation.submit()
            
            agreement.link_donation(donation.name)
        
        elapsed_time = time.time() - start_time
        
        # Verify calculations
        self.assertEqual(agreement.donations_count, 24)
        self.assertEqual(agreement.total_donated, 2400)
        
        # Performance check (should complete in reasonable time)
        self.assertLess(elapsed_time, 30, "Donation linking took too long")
    
    # ANBI Clarity Tests
    
    def test_commitment_type_setting(self):
        """Test commitment type is set correctly based on duration"""
        # Test ANBI agreement (5+ years)
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement.anbi_eligible = 1
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        
        self.assertEqual(agreement.commitment_type, "ANBI Periodic Donation Agreement")
        
        # Test pledge (< 5 years)
        agreement2 = frappe.new_doc("Periodic Donation Agreement")
        agreement2.donor = self.test_donor
        agreement2.start_date = today()
        agreement2.agreement_duration_years = "2 Years (Pledge - No ANBI benefits)"
        agreement2.anbi_eligible = 0
        agreement2.annual_amount = 1200
        agreement2.payment_frequency = "Monthly"
        agreement2.payment_method = "Bank Transfer"
        agreement2.insert()
        
        self.assertEqual(agreement2.commitment_type, "Donation Pledge (No ANBI Tax Benefits)")
    
    def test_anbi_eligibility_auto_setting(self):
        """Test ANBI eligibility is automatically set based on duration"""
        # Test 1: 1-year pledge should not be ANBI eligible
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.agreement_duration_years = "1 Year (Pledge - No ANBI benefits)"
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        agreement.insert()
        
        self.assertEqual(agreement.anbi_eligible, 0)
        self.assertEqual(agreement.commitment_type, "Donation Pledge (No ANBI Tax Benefits)")
        
        # Test 2: 5-year agreement should be ANBI eligible
        agreement2 = frappe.new_doc("Periodic Donation Agreement")
        agreement2.donor = self.test_donor
        agreement2.start_date = today()
        agreement2.agreement_duration_years = "5 Years (ANBI Minimum)"
        agreement2.annual_amount = 1000
        agreement2.payment_frequency = "Annually"
        agreement2.payment_method = "Bank Transfer"
        agreement2.insert()
        
        self.assertEqual(agreement2.anbi_eligible, 1)
        self.assertEqual(agreement2.commitment_type, "ANBI Periodic Donation Agreement")
    
    def test_duration_parsing_with_labels(self):
        """Test duration parsing handles new labeled format"""
        test_cases = [
            ("1 Year (Pledge - No ANBI benefits)", 1),
            ("2 Years (Pledge - No ANBI benefits)", 2),
            ("5 Years (ANBI Minimum)", 5),
            ("10 Years (ANBI)", 10),
        ]
        
        for duration_str, expected_years in test_cases:
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor
            agreement.start_date = today()
            agreement.agreement_duration_years = duration_str
            agreement.annual_amount = 1000
            agreement.payment_frequency = "Annually"
            agreement.payment_method = "Bank Transfer"
            
            # Test get_agreement_duration method
            parsed_duration = agreement.get_agreement_duration()
            self.assertEqual(
                parsed_duration, 
                expected_years,
                f"Failed to parse duration from: {duration_str}"
            )
    
    def test_anbi_validation_messages(self):
        """Test validation messages are clear about ANBI requirements"""
        # Try to create ANBI agreement with < 5 years
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.end_date = add_years(today(), 3)  # Only 3 years
        agreement.anbi_eligible = 1  # Trying to claim ANBI benefits
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        
        with self.assertRaises(frappe.ValidationError) as cm:
            agreement.insert()
        
        # Check that error message mentions ANBI requirements
        error_message = str(cm.exception)
        self.assertIn("ANBI", error_message)
        self.assertIn("5 years", error_message)
    
    # Integration Tests
    
    def test_donation_validation_with_agreement(self):
        """Test donation validation when linked to agreement"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Test 1: Valid donation
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor
        donation.date = today()
        donation.amount = 100
        donation.payment_method = "Bank Transfer"
        donation.periodic_donation_agreement = agreement.name
        donation.donation_type = "General"
        donation.company = self.test_company
        donation.insert()
        
        # Should auto-populate ANBI fields
        self.assertEqual(donation.anbi_agreement_number, agreement.agreement_number)
        self.assertEqual(donation.anbi_agreement_date, agreement.agreement_date)
        self.assertEqual(donation.belastingdienst_reportable, 1)
        self.assertEqual(donation.status, "Recurring")
        
        # Test 2: Wrong donor
        donation2 = frappe.new_doc("Donation")
        donation2.donor = self.create_test_donor("-wrong")
        donation2.date = today()
        donation2.amount = 100
        donation2.payment_method = "Bank Transfer"
        donation2.periodic_donation_agreement = agreement.name
        donation2.donation_type = "General"
        donation2.company = self.test_company
        
        with self.assertRaises(frappe.ValidationError):
            donation2.insert()
        
        # Test 3: Cancelled agreement
        agreement.status = "Cancelled"
        agreement.save()
        
        donation3 = frappe.new_doc("Donation")
        donation3.donor = self.test_donor
        donation3.date = today()
        donation3.amount = 100
        donation3.payment_method = "Bank Transfer"
        donation3.periodic_donation_agreement = agreement.name
        donation3.donation_type = "General"
        donation3.company = self.test_company
        
        with self.assertRaises(frappe.ValidationError):
            donation3.insert()


def run_tests():
    """Run the test suite"""
    frappe.connect()
    unittest.main(module=__name__, exit=False, verbosity=2)