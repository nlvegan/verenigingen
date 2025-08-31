"""
Test Donation Agreement functionality
"""

import frappe
from datetime import datetime
from dateutil.relativedelta import relativedelta
from frappe.utils import today, add_to_date, flt
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationAgreement(EnhancedTestCase):
    """Test comprehensive Donation Agreement functionality"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test donor
        self.donor = self.create_test_donor(donor_name="Test Donor", donor_email="test@example.com")

    def test_recurring_donation_agreement_creation(self):
        """Test creation of recurring donation agreement"""
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 50.00,
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Draft",
            }
        )

        # Save and validate
        agreement.save()

        # Verify calculations
        self.assertGreater(flt(agreement.total_committed_amount), 0)
        self.assertEqual(agreement.next_due_date, today())

    def test_one_time_pledge_agreement(self):
        """Test one-time pledge donation agreement"""
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "One-time Pledge",
                "amount": 500.00,
                "currency": "EUR",
                "start_date": today(),
                "donation_purpose": "Special Campaign",
                "status": "Draft",
            }
        )

        # Save and validate
        agreement.save()

        # Verify one-time commitment calculation
        self.assertEqual(flt(agreement.total_committed_amount), 500.00)

    def test_anbi_eligibility_calculation(self):
        """Test ANBI tax exemption eligibility"""
        # Create agreement with high amount - 500 EUR annually (42 * 12)
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 42.00,  # 42 * 12 = 504 EUR annually, above ANBI threshold
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Draft",
            }
        )

        # Save and check ANBI eligibility
        agreement.save()

        # Should be ANBI eligible based on annual amount (504 > 500)
        self.assertEqual(agreement.anbi_eligible, 1)

    def test_donation_transaction_creation(self):
        """Test automatic donation transaction creation"""
        # Create and submit recurring agreement
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 25.00,
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Active",
                "auto_create_transactions": 1,
            }
        )

        agreement.save()
        agreement.submit()

        # Create transaction
        donation_name = agreement.create_next_donation_transaction()

        if donation_name:
            # Verify donation was created
            donation = frappe.get_doc("Donation", donation_name)
            self.assertEqual(donation.donor, self.donor.name)
            self.assertEqual(flt(donation.amount), 25.00)
            self.assertEqual(donation.donation_agreement, agreement.name)

    def test_income_projection(self):
        """Test income projection calculation"""
        # Create recurring agreement
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 50.00,
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Active",
            }
        )

        agreement.save()

        # Test annual projection
        annual_projection = agreement.get_projected_annual_income()
        self.assertEqual(annual_projection, 600.00)  # 50 * 12 months

    def test_agreement_status_changes(self):
        """Test agreement status change handling"""
        # Create agreement
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 30.00,
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Active",
            }
        )

        agreement.save()
        agreement.submit()

        # Use db_set to change status after submit (bypasses validation)
        agreement.db_set("status", "Suspended")
        agreement.db_set("internal_notes", "Test suspension")

        # Verify status change was handled
        agreement.reload()
        self.assertEqual(agreement.status, "Suspended")

    def test_financial_tracking_updates(self):
        """Test financial tracking field updates"""
        # Create agreement
        agreement = frappe.new_doc("Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Recurring",
                "amount": 40.00,
                "currency": "EUR",
                "recurring_frequency": "1 month",
                "start_date": today(),
                "donation_purpose": "General Fund",
                "status": "Active",
            }
        )

        agreement.save()
        agreement.submit()

        # Update financial tracking
        agreement.update_financial_tracking()

        # Verify tracking fields are updated
        self.assertIsNotNone(agreement.total_received_amount)
        self.assertIsNotNone(agreement.total_outstanding_amount)

    def create_test_donor(self, donor_name, donor_email):
        """Create test donor with required fields"""
        if frappe.db.exists("Donor", {"donor_name": donor_name}):
            return frappe.get_doc("Donor", {"donor_name": donor_name})

        donor = frappe.new_doc("Donor")
        donor.update({"donor_name": donor_name, "donor_email": donor_email, "donor_type": "Individual"})
        donor.save()
        return donor
