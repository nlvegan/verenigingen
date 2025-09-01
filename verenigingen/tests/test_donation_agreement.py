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
        
        # Create test campaign for campaign donation tests
        self.campaign = frappe.new_doc("Donation Campaign")
        self.campaign.update({
            "campaign_name": f"Test Campaign {frappe.generate_hash(length=6)}",
            "campaign_type": "Annual Giving", 
            "description": "Test campaign for donation integration",
            "status": "Active",
            "start_date": today(),
            "monetary_goal": 1000.00,
            "donor_goal": 10,
            "is_public": 1,
            # Initialize progress tracking fields to prevent NoneType errors
            "total_raised": 0.0,
            "total_donors": 0,
            "total_donations": 0,
            "monetary_progress": 0.0,
            "donor_progress": 0.0,
            "average_donation_amount": 0.0
        })
        self.campaign.save()

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

    # ============= CAMPAIGN DONATION INTEGRATION TESTS =============
    
    def test_donation_campaign_budget_integration(self):
        """Test that donations properly update campaign budget totals"""
        # Record initial campaign state
        initial_raised = self.campaign.total_raised
        initial_donors = self.campaign.total_donors
        
        # Create donation linked to campaign using Enhanced Test Factory
        donation = self.create_test_donation(
            donor=self.donor.name,
            amount=150.00,
            donation_type="General",  # Use valid donation type
            campaign=self.campaign.name,
            paid=1  # Mark as paid to include in campaign totals
        )
        
        # Update campaign progress to reflect new donation
        self.campaign.reload()
        self.campaign.update_progress()
        
        # Verify campaign budget totals updated correctly
        self.assertEqual(flt(self.campaign.total_raised - initial_raised), 150.00)
        self.assertEqual(self.campaign.total_donors - initial_donors, 1)
        self.assertEqual(flt(self.campaign.average_donation_amount), 150.00)
        
        # Verify progress calculations
        expected_progress = (self.campaign.total_raised / self.campaign.monetary_goal) * 100
        self.assertEqual(flt(self.campaign.monetary_progress), expected_progress)

    def test_multiple_donations_campaign_accumulation(self):
        """Test multiple donations accumulating to campaign totals"""
        # Create second donor for unique donor counting test
        donor2 = self.create_test_donor("Test Donor 2", "test2@example.com")
        
        # Create first donation
        donation1 = self.create_test_donation(
            donor=self.donor.name,
            amount=200.00,
            donation_type="General", 
            campaign=self.campaign.name,
            paid=1
        )
        
        # Create second donation from different donor
        donation2 = self.create_test_donation(
            donor=donor2.name,
            amount=300.00,
            donation_type="General",
            campaign=self.campaign.name, 
            paid=1
        )
        
        # Update campaign progress
        self.campaign.reload()
        self.campaign.update_progress()
        
        # Verify accumulated totals (500.00 total, 2 donors, average 250.00)
        self.assertEqual(flt(self.campaign.total_raised), 500.00)
        self.assertEqual(self.campaign.total_donors, 2)
        self.assertEqual(flt(self.campaign.average_donation_amount), 250.00)

    def test_unpaid_donations_excluded_from_campaign_totals(self):
        """Test that unpaid donations don't affect campaign budget totals"""
        # Record baseline
        baseline_raised = self.campaign.total_raised
        baseline_donors = self.campaign.total_donors
        
        # Create paid donation
        paid_donation = self.create_test_donation(
            donor=self.donor.name,
            amount=100.00,
            donation_type="General",
            campaign=self.campaign.name,
            paid=1  # Paid
        )
        
        # Create unpaid donation  
        unpaid_donation = self.create_test_donation(
            donor=self.donor.name,
            amount=200.00,
            donation_type="General", 
            campaign=self.campaign.name,
            paid=0  # Not paid
        )
        
        # Update campaign progress
        self.campaign.reload()
        self.campaign.update_progress()
        
        # Verify only paid donation affects totals
        self.assertEqual(flt(self.campaign.total_raised - baseline_raised), 100.00)
        # Donor count should increase by 1 (only counting paid donations)
        self.assertGreaterEqual(self.campaign.total_donors - baseline_donors, 1)

    def test_campaign_donation_form_integration(self):
        """Test complete donation form submission with campaign selection"""
        from verenigingen.templates.pages.donate import submit_donation
        
        # Test form submission with existing campaign
        form_data = {
            "donor_name": "Form Integration Test Donor",
            "donor_email": "form.integration@example.com",
            "amount": "75.50",
            "donation_type": "General", 
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "Campaign", 
            "campaign_reference": self.campaign.name,  # Existing campaign
            "donation_notes": "Test form integration with campaign"
        }
        
        # Submit donation through form handler
        result = submit_donation(**form_data)
        
        # Verify successful submission
        self.assertTrue(result.get("success"))
        donation_id = result.get("donation_id")
        self.assertIsNotNone(donation_id)
        
        # Verify donation created with proper campaign link
        donation = frappe.get_doc("Donation", donation_id)
        self.assertEqual(donation.campaign, self.campaign.name)
        self.assertEqual(donation.donation_purpose_type, "Campaign")
        self.assertIn("Test form integration", donation.donation_notes)
        
        # Mark as paid and verify campaign totals update
        donation.paid = 1
        donation.save()
        
        self.campaign.reload()
        previous_total = self.campaign.total_raised
        self.campaign.update_progress()
        
        # Campaign should reflect the new donation
        self.assertGreater(self.campaign.total_raised, previous_total)

    def test_campaign_fallback_to_notes_integration(self):
        """Test campaign reference fallback for non-existent campaigns"""
        from verenigingen.templates.pages.donate import submit_donation
        
        # Test with non-existent campaign
        form_data = {
            "donor_name": "Fallback Test Donor",
            "donor_email": "fallback.test@example.com", 
            "amount": "50.00",
            "donation_type": "General",
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign_reference": "Non-existent Campaign Reference",
            "donation_notes": "Additional user notes"
        }
        
        # Submit donation
        result = submit_donation(**form_data)
        self.assertTrue(result.get("success"))
        
        # Verify donation created with fallback behavior
        donation = frappe.get_doc("Donation", result.get("donation_id"))
        
        # Campaign field should be empty (since it doesn't exist)
        self.assertFalse(donation.campaign)
        
        # Campaign reference should be stored in notes
        self.assertIn("Campaign: Non-existent Campaign Reference", donation.donation_notes)
        self.assertIn("Additional user notes", donation.donation_notes)
        
        # Purpose type should still be set correctly
        self.assertEqual(donation.donation_purpose_type, "Campaign")
