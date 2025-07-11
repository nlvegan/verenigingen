"""
Test Periodic Donation Agreement functionality
Tests the ANBI Phase 2 implementation for 5-year donation agreements
"""

import frappe
import unittest
from frappe.utils import today, add_years, add_months, getdate
from datetime import datetime


class TestPeriodicDonationAgreement(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        cls.test_donor = cls.create_test_donor()
        cls.test_sepa_mandate = cls.create_test_sepa_mandate()
    
    @classmethod
    def create_test_donor(cls):
        """Create a test donor with ANBI consent"""
        donor_name = "TEST-PDA-Donor-001"
        
        if not frappe.db.exists("Donor", {"donor_name": donor_name}):
            donor = frappe.new_doc("Donor")
            donor.donor_name = donor_name
            donor.donor_email = "pda-test@example.com"
            donor.donor_type = "Individual"
            donor.anbi_consent = 1
            donor.anbi_consent_date = frappe.utils.now()
            donor.identification_verified = 1
            donor.identification_verification_date = today()
            donor.identification_verification_method = "Manual"
            donor.insert()
            return donor.name
        
        return frappe.db.get_value("Donor", {"donor_name": donor_name}, "name")
    
    @classmethod
    def create_test_sepa_mandate(cls):
        """Create a test SEPA mandate"""
        mandate_id = "TEST-PDA-SEPA-001"
        
        if not frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id}):
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.mandate_id = mandate_id
            mandate.donor = cls.test_donor
            mandate.iban = "NL91ABNA0417164300"
            mandate.bic = "ABNANL2A"
            mandate.mandate_type = "RCUR"
            mandate.status = "Active"
            mandate.valid_from = today()
            mandate.insert()
            return mandate.name
        
        return frappe.db.get_value("SEPA Mandate", {"mandate_id": mandate_id}, "name")
    
    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")
    
    def tearDown(self):
        """Clean up after each test"""
        # Clean up test agreements
        test_agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters={"donor": self.test_donor}
        )
        for agreement in test_agreements:
            doc = frappe.get_doc("Periodic Donation Agreement", agreement.name)
            if doc.docstatus == 0:
                doc.delete()
        
        frappe.db.commit()
    
    def test_create_periodic_agreement(self):
        """Test creating a periodic donation agreement"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.agreement_type = "Private Written"
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.sepa_mandate = self.test_sepa_mandate
        agreement.status = "Draft"
        
        agreement.insert()
        
        # Verify auto-calculations
        self.assertIsNotNone(agreement.agreement_number)
        self.assertTrue(agreement.agreement_number.startswith("PDA-"))
        
        # End date should be 5 years from start
        expected_end = add_years(getdate(agreement.start_date), 5)
        self.assertEqual(getdate(agreement.end_date), expected_end)
        
        # Payment amount should be annual/12 for monthly
        self.assertEqual(agreement.payment_amount, 100)  # 1200/12
    
    def test_payment_amount_calculations(self):
        """Test payment amount calculations for different frequencies"""
        test_cases = [
            ("Monthly", 1200, 100),      # 1200/12
            ("Quarterly", 1200, 300),    # 1200/4
            ("Annually", 1200, 1200),    # 1200/1
        ]
        
        for frequency, annual, expected in test_cases:
            agreement = frappe.new_doc("Periodic Donation Agreement")
            agreement.donor = self.test_donor
            agreement.start_date = today()
            agreement.annual_amount = annual
            agreement.payment_frequency = frequency
            agreement.payment_method = "Bank Transfer"
            
            agreement.calculate_payment_amount()
            
            self.assertEqual(
                agreement.payment_amount, 
                expected,
                f"Payment amount calculation failed for {frequency}"
            )
    
    def test_minimum_period_validation(self):
        """Test that agreements must be for minimum 5 years"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.end_date = add_years(today(), 3)  # Only 3 years
        agreement.annual_amount = 1000
        agreement.payment_frequency = "Annually"
        agreement.payment_method = "Bank Transfer"
        
        # Should throw error for less than 5 years
        with self.assertRaises(frappe.ValidationError):
            agreement.insert()
    
    def test_link_donation_to_agreement(self):
        """Test linking donations to agreements"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Create donation
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor
        donation.date = today()
        donation.amount = 100
        donation.payment_method = "Bank Transfer"
        donation.donation_type = "General"
        donation.paid = 1
        donation.insert()
        donation.submit()
        
        # Link donation
        agreement.link_donation(donation.name)
        
        # Verify linking
        self.assertEqual(len(agreement.donations), 1)
        self.assertEqual(agreement.donations[0].donation, donation.name)
        self.assertEqual(agreement.donations[0].amount, 100)
        self.assertEqual(agreement.donations[0].status, "Paid")
        
        # Verify donation tracking update
        self.assertEqual(agreement.total_donated, 100)
        self.assertEqual(agreement.donations_count, 1)
        self.assertEqual(agreement.last_donation_date, today())
    
    def test_agreement_number_generation(self):
        """Test unique agreement number generation"""
        year = datetime.now().year
        
        # Create first agreement
        agreement1 = frappe.new_doc("Periodic Donation Agreement")
        agreement1.donor = self.test_donor
        agreement1.start_date = today()
        agreement1.annual_amount = 1000
        agreement1.payment_frequency = "Annually"
        agreement1.payment_method = "Bank Transfer"
        agreement1.insert()
        
        # Create second agreement
        agreement2 = frappe.new_doc("Periodic Donation Agreement")
        agreement2.donor = self.test_donor
        agreement2.start_date = today()
        agreement2.annual_amount = 2000
        agreement2.payment_frequency = "Annually"
        agreement2.payment_method = "Bank Transfer"
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
        other_donor.donor_email = "other@example.com"
        other_donor.insert()
        
        # Create agreement for first donor
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Create donation from other donor
        donation = frappe.new_doc("Donation")
        donation.donor = other_donor.name
        donation.date = today()
        donation.amount = 100
        donation.payment_method = "Bank Transfer"
        donation.donation_type = "General"
        donation.insert()
        donation.submit()
        
        # Try to link - should fail
        with self.assertRaises(frappe.ValidationError):
            agreement.link_donation(donation.name)
        
        # Clean up
        other_donor.delete()
    
    def test_next_donation_date_calculation(self):
        """Test calculation of next expected donation date"""
        # Create agreement with monthly frequency
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Without any donations, next date should be start date
        agreement.calculate_next_donation_date()
        self.assertEqual(agreement.next_expected_donation, agreement.start_date)
        
        # Add a donation
        agreement.last_donation_date = today()
        agreement.calculate_next_donation_date()
        
        expected_next = add_months(getdate(today()), 1)
        self.assertEqual(getdate(agreement.next_expected_donation), expected_next)
    
    def test_cancel_agreement(self):
        """Test agreement cancellation"""
        # Create active agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "Bank Transfer"
        agreement.status = "Active"
        agreement.insert()
        
        # Cancel agreement
        agreement.cancel_agreement("Donor requested cancellation")
        
        # Verify cancellation
        self.assertEqual(agreement.status, "Cancelled")
        self.assertEqual(agreement.cancellation_date, today())
        self.assertEqual(agreement.cancellation_reason, "Donor requested cancellation")
        self.assertEqual(agreement.cancellation_processed_by, frappe.session.user)
    
    def test_agreement_with_sepa_mandate(self):
        """Test agreement with SEPA mandate"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = self.test_donor
        agreement.start_date = today()
        agreement.annual_amount = 1200
        agreement.payment_frequency = "Monthly"
        agreement.payment_method = "SEPA Direct Debit"
        agreement.sepa_mandate = self.test_sepa_mandate
        agreement.status = "Active"
        agreement.insert()
        
        # Verify SEPA mandate is linked
        self.assertEqual(agreement.sepa_mandate, self.test_sepa_mandate)
        
        # Create donation with same SEPA mandate
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor
        donation.date = today()
        donation.amount = 100
        donation.payment_method = "SEPA Direct Debit"
        donation.sepa_mandate = self.test_sepa_mandate
        donation.donation_type = "General"
        donation.periodic_donation_agreement = agreement.name
        donation.insert()
        donation.submit()
        
        # Verify donation is properly linked
        self.assertEqual(donation.periodic_donation_agreement, agreement.name)


def run_tests():
    """Run the test suite"""
    frappe.connect()
    unittest.main(module=__name__, exit=False, verbosity=2)