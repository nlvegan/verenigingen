"""
Test Campaign-Donation Integration functionality

This test suite validates that donations are properly linked to campaigns
and that campaign budget totals are calculated correctly.
"""

import frappe
from frappe.utils import flt, getdate, today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCampaignDonationIntegration(EnhancedTestCase):
    """Test comprehensive Campaign-Donation integration functionality"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test donor
        self.donor = self.create_test_donor(
            donor_name="Test Campaign Donor", 
            donor_email="campaign.test@example.com"
        )

        # Create test campaign
        self.campaign = frappe.new_doc("Donation Campaign")
        self.campaign.update({
            "campaign_name": "Test Integration Campaign",
            "campaign_type": "Annual Giving",  # Use valid campaign type
            "description": "Test campaign for integration testing",
            "status": "Active",
            "start_date": today(),
            "monetary_goal": 1000.00,
            "donor_goal": 10,
            "is_public": 1
        })
        self.campaign.save()

    def test_donation_campaign_linking(self):
        """Test that donations are properly linked to campaigns"""
        # Create donation with campaign link
        donation = frappe.new_doc("Donation")
        donation.update({
            "donor": self.donor.name,
            "donation_date": today(),
            "amount": 150.00,
            "donation_type": "General",
            "mode_of_payment": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign": self.campaign.name,
            "paid": 1  # Mark as paid to include in campaign totals
        })
        
        # Save and submit donation
        donation.save()
        donation.submit()

        # Refresh campaign to get updated totals
        self.campaign.reload()
        self.campaign.update_progress()

        # Verify campaign totals are updated
        self.assertEqual(self.campaign.total_donations, 1)
        self.assertEqual(flt(self.campaign.total_raised), 150.00)
        self.assertEqual(self.campaign.total_donors, 1)
        self.assertEqual(flt(self.campaign.average_donation_amount), 150.00)

        # Verify progress calculations
        expected_monetary_progress = (150.00 / 1000.00) * 100  # 15%
        expected_donor_progress = (1 / 10) * 100  # 10%
        
        self.assertEqual(flt(self.campaign.monetary_progress), 15.0)
        self.assertEqual(flt(self.campaign.donor_progress), 10.0)

    def test_multiple_donations_to_campaign(self):
        """Test multiple donations accumulating to campaign totals"""
        # Create second donor
        donor2 = self.create_test_donor(
            donor_name="Second Test Donor",
            donor_email="donor2.test@example.com"
        )

        # Create first donation
        donation1 = frappe.new_doc("Donation")
        donation1.update({
            "donor": self.donor.name,
            "donation_date": today(),
            "amount": 200.00,
            "donation_type": "General",
            "mode_of_payment": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign": self.campaign.name,
            "paid": 1
        })
        donation1.save()
        donation1.submit()

        # Create second donation from different donor
        donation2 = frappe.new_doc("Donation")
        donation2.update({
            "donor": donor2.name,
            "donation_date": today(),
            "amount": 300.00,
            "donation_type": "General",
            "mode_of_payment": "Cash",
            "donation_purpose_type": "Campaign",
            "campaign": self.campaign.name,
            "paid": 1
        })
        donation2.save()
        donation2.submit()

        # Update campaign progress
        self.campaign.reload()
        self.campaign.update_progress()

        # Verify accumulated totals
        self.assertEqual(self.campaign.total_donations, 2)
        self.assertEqual(flt(self.campaign.total_raised), 500.00)
        self.assertEqual(self.campaign.total_donors, 2)  # Two unique donors
        self.assertEqual(flt(self.campaign.average_donation_amount), 250.00)

        # Verify progress calculations
        self.assertEqual(flt(self.campaign.monetary_progress), 50.0)  # 500/1000 = 50%
        self.assertEqual(flt(self.campaign.donor_progress), 20.0)    # 2/10 = 20%

    def test_unpaid_donations_excluded_from_totals(self):
        """Test that unpaid donations are not included in campaign totals"""
        # Create paid donation
        paid_donation = frappe.new_doc("Donation")
        paid_donation.update({
            "donor": self.donor.name,
            "donation_date": today(),
            "amount": 100.00,
            "donation_type": "General",
            "mode_of_payment": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign": self.campaign.name,
            "paid": 1  # Paid
        })
        paid_donation.save()
        paid_donation.submit()

        # Create unpaid donation
        unpaid_donation = frappe.new_doc("Donation")
        unpaid_donation.update({
            "donor": self.donor.name,
            "donation_date": today(),
            "amount": 200.00,
            "donation_type": "General",
            "mode_of_payment": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign": self.campaign.name,
            "paid": 0  # Not paid
        })
        unpaid_donation.save()
        unpaid_donation.submit()

        # Update campaign progress
        self.campaign.reload()
        self.campaign.update_progress()

        # Verify only paid donation is counted
        self.assertEqual(self.campaign.total_donations, 1)
        self.assertEqual(flt(self.campaign.total_raised), 100.00)
        self.assertEqual(self.campaign.total_donors, 1)

    def test_campaign_without_donations(self):
        """Test campaign progress calculation with no donations"""
        # Update campaign progress (should be zero for new campaign)
        self.campaign.update_progress()

        # Verify zero totals
        self.assertEqual(self.campaign.total_donations, 0)
        self.assertEqual(flt(self.campaign.total_raised), 0.00)
        self.assertEqual(self.campaign.total_donors, 0)
        self.assertEqual(flt(self.campaign.average_donation_amount), 0.00)
        self.assertEqual(flt(self.campaign.monetary_progress), 0.00)
        self.assertEqual(flt(self.campaign.donor_progress), 0.00)

    def test_campaign_donation_form_flow(self):
        """Test the complete donation form submission flow with campaign"""
        from verenigingen.templates.pages.donate import submit_donation
        
        # Simulate form submission data
        form_data = {
            "donor_name": "Form Test Donor",
            "donor_email": "form.test@example.com",
            "amount": "75.50",
            "donation_type": "General",
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign_reference": self.campaign.name,  # Existing campaign
            "donation_notes": "Test donation from form"
        }

        # Submit donation through the form handler
        result = submit_donation(**form_data)

        # Verify submission success
        self.assertTrue(result.get("success"))
        donation_id = result.get("donation_id")
        self.assertIsNotNone(donation_id)

        # Get the created donation
        donation = frappe.get_doc("Donation", donation_id)

        # Verify campaign linking
        self.assertEqual(donation.campaign, self.campaign.name)
        self.assertEqual(donation.donation_purpose_type, "Campaign")

        # Mark as paid and update campaign progress
        donation.paid = 1
        donation.save()
        
        self.campaign.reload()
        self.campaign.update_progress()

        # Verify campaign totals updated
        self.assertEqual(self.campaign.total_donations, 1)
        self.assertEqual(flt(self.campaign.total_raised), 75.50)

    def test_campaign_fallback_to_notes(self):
        """Test campaign reference fallback to notes for non-existent campaigns"""
        from verenigingen.templates.pages.donate import submit_donation
        
        # Simulate form submission with non-existent campaign
        form_data = {
            "donor_name": "Fallback Test Donor",
            "donor_email": "fallback.test@example.com",
            "amount": "50.00",
            "donation_type": "General", 
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "Campaign",
            "campaign_reference": "Non-existent Campaign",  # This doesn't exist
            "donation_notes": "Additional user notes"
        }

        # Submit donation
        result = submit_donation(**form_data)
        self.assertTrue(result.get("success"))

        # Get created donation
        donation = frappe.get_doc("Donation", result.get("donation_id"))

        # Verify campaign field is empty (since campaign doesn't exist)
        self.assertFalse(donation.campaign)

        # Verify campaign reference is stored in notes
        self.assertIn("Campaign: Non-existent Campaign", donation.donation_notes)
        self.assertIn("Additional user notes", donation.donation_notes)

        # Verify purpose type is still set
        self.assertEqual(donation.donation_purpose_type, "Campaign")

    def tearDown(self):
        """Clean up test data"""
        # Campaign cleanup is handled by EnhancedTestCase
        super().tearDown()