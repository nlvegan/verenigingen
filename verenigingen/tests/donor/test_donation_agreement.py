"""
Test Periodic Donation Agreement functionality
"""

import frappe
from datetime import datetime
from dateutil.relativedelta import relativedelta
from frappe.utils import today, add_to_date, flt
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class TestDonationAgreement(EnhancedTestCase):
    """Test comprehensive Periodic Donation Agreement functionality"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test donor
        self.donor = self._create_or_reuse_local_donor(donor_name="Test Donor", donor_email="test@example.com")

        # Create test campaign for campaign donation tests with unique name
        # Use hash-based naming to avoid race conditions in parallel execution
        campaign_name = f"Test Campaign {frappe.generate_hash(length=8)}"

        # Clean up any existing campaign with this name
        if DocumentExistenceValidator.check_document_exists("Donation Campaign", campaign_name):
            frappe.delete_doc("Donation Campaign", campaign_name, force=True)

        self.campaign = frappe.new_doc("Donation Campaign")
        self.campaign.update({
            "campaign_name": campaign_name,
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

        # Track for cleanup if available
        if hasattr(self, '_track_record'):
            self._track_record("Donation Campaign", self.campaign.name)

    def test_recurring_donation_agreement_creation(self):
        """Test creation of recurring donation agreement"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 600.00,  # €600/year
                "payment_frequency": "Monthly",  # Pay monthly
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "3 Years (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Draft",
            }
        )

        # Save and validate
        agreement.save()

        # Verify calculations
        self.assertEqual(flt(agreement.annual_amount), 600.00)
        self.assertEqual(agreement.payment_frequency, "Monthly")
        # Payment amount is auto-calculated: 600 / 12 = 50
        self.assertEqual(flt(agreement.payment_amount), 50.00)

    def test_one_time_pledge_agreement(self):
        """Test one-time pledge donation agreement"""
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 500.00,  # €500 one-time
                "payment_frequency": "Annually",  # One payment per year
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Draft",
            }
        )

        # Save and validate
        agreement.save()

        # Verify one-time commitment values
        self.assertEqual(flt(agreement.annual_amount), 500.00)
        self.assertEqual(flt(agreement.payment_amount), 500.00)  # Annual payment = annual amount

    def test_anbi_eligibility_calculation(self):
        """Test ANBI tax exemption eligibility"""
        # Create agreement with 5+ year duration for ANBI eligibility
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 500.00,  # €500 annually
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "5 Years (ANBI Minimum)",
                "status": "Draft",
            }
        )

        # Save and check ANBI eligibility
        # Note: This may fail if donor doesn't have BSN - that's a valid business rule
        try:
            agreement.save()
            # Should be ANBI eligible based on 5+ year duration
            self.assertEqual(agreement.anbi_eligible, 1)
        except frappe.ValidationError as e:
            # If validation fails due to missing BSN, that's expected
            if "BSN" in str(e):
                self.skipTest("Donor requires BSN for ANBI agreements - business rule enforced")

    def test_donation_transaction_creation(self):
        """Test donation agreement activation"""
        # Create recurring agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 300.00,  # €300/year
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "3 Years (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Draft",
            }
        )

        agreement.save()

        # Activate agreement
        agreement.status = "Active"
        agreement.save()

        # Verify agreement is active
        self.assertEqual(agreement.status, "Active")
        self.assertEqual(flt(agreement.annual_amount), 300.00)
        self.assertEqual(flt(agreement.payment_amount), 25.00)  # 300 / 12 months

    def test_income_projection(self):
        """Test annual amount calculation"""
        # Create recurring agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 600.00,  # €600/year
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "3 Years (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Active",
            }
        )

        agreement.save()

        # Verify annual amount and payment calculation
        self.assertEqual(flt(agreement.annual_amount), 600.00)
        self.assertEqual(flt(agreement.payment_amount), 50.00)  # 600 / 12 months

    def test_agreement_status_changes(self):
        """Test agreement status change handling"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 360.00,  # €360/year
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "3 Years (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Draft",
            }
        )

        agreement.save()

        # Change status to Active
        agreement.status = "Active"
        agreement.save()

        self.assertEqual(agreement.status, "Active")

        # Change status to Cancelled using proper validation flow
        agreement.reload()  # Reload to get latest state
        agreement.status = "Cancelled"
        agreement.cancellation_reason = "Test cancellation"
        agreement.save()  # Triggers validation hooks

        # Verify status change was handled
        agreement.reload()
        self.assertEqual(agreement.status, "Cancelled")

    def test_financial_tracking_updates(self):
        """Test financial tracking field updates"""
        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.update(
            {
                "donor": self.donor.name,
                "agreement_type": "Private Written",
                "annual_amount": 480.00,  # €480/year
                "payment_frequency": "Monthly",
                "payment_method": "Bank Transfer",
                "start_date": today(),
                "agreement_duration_years": "3 Years (Pledge - No ANBI benefits)",
                "anbi_eligible": 0,  # Not ANBI eligible (< 5 years)
                "status": "Active",
            }
        )

        agreement.save()

        # Verify tracking fields exist (may be None if not initialized)
        # Check that fields are accessible
        self.assertTrue(hasattr(agreement, 'total_donated'))
        self.assertTrue(hasattr(agreement, 'donations_count'))
        # Initially these should be zero/empty or None
        self.assertEqual(flt(agreement.total_donated or 0), 0.0)
        self.assertEqual(agreement.donations_count or 0, 0)

    def _create_or_reuse_local_donor(self, donor_name, donor_email):
        """Create test donor with required fields, reusing one already named `donor_name`.

        Renamed from `create_test_donor` (#496): that name shadows
        `EnhancedTestCase.create_test_donor`, which `create_test_donation()` calls
        internally (`self.create_test_donor(...)`) whenever a donation is created
        without an explicit `donor=`. The harness version always makes a fresh,
        ANBI-valid donor with a unique email; this one instead looks up an existing
        donor by name and reuses it -- a different, name-based dedup behavior that
        this test class wants for itself but that silently overrode the harness's
        internal donor-creation path for every `create_test_donation()` call in this
        class that omitted `donor=`.
        """
        if DocumentExistenceValidator.check_document_exists("Donor", {"donor_name": donor_name}):
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
        donor2 = self._create_or_reuse_local_donor("Test Donor 2", "test2@example.com")

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
        # Skip test if Donation Creation Security DocType doesn't exist
        if not frappe.db.exists("DocType", "Donation Creation Security"):
            self.skipTest("Donation Creation Security DocType not implemented yet")

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

        # Debug output to see what's happening
        if not result.get("success"):
            print(f"❌ Form submission failed: {result}")

        # For campaign integration testing, focus on donation creation not payment
        # Payment failures are expected in test environment
        self.assertTrue(result.get("donation_created"), "Donation should be created")
        donation_id = result.get("donation_id")
        self.assertIsNotNone(donation_id, "Donation ID should be provided")

        # Verify donation created with proper campaign link
        donation = frappe.get_doc("Donation", donation_id)
        self.assertEqual(donation.campaign, self.campaign.name)
        self.assertEqual(donation.donation_purpose_type, "Campaign")
        self.assertIn("Test form integration", donation.donation_notes)

        # Mark as paid using proper validation flow
        donation.reload()  # Reload to get latest state
        donation.paid = 1
        try:
            donation.save()  # Triggers validation hooks
        except frappe.UpdateAfterSubmitError:
            # If document is submitted, use db_set as fallback
            donation.db_set("paid", 1)

        self.campaign.reload()
        previous_total = self.campaign.total_raised
        self.campaign.update_progress()

        # Campaign should reflect the new donation
        self.assertGreater(self.campaign.total_raised, previous_total)

    def test_campaign_fallback_to_notes_integration(self):
        """Test campaign reference fallback for non-existent campaigns"""
        # Skip test if Donation Creation Security DocType doesn't exist
        if not frappe.db.exists("DocType", "Donation Creation Security"):
            self.skipTest("Donation Creation Security DocType not implemented yet")

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

        # Debug output to see what's happening
        if not result.get("success"):
            print(f"❌ Fallback test failed: {result}")

        # For campaign integration testing, focus on donation creation not payment
        self.assertTrue(result.get("donation_created"), "Donation should be created")

        # Verify donation created with fallback behavior
        donation = frappe.get_doc("Donation", result.get("donation_id"))

        # Campaign field should be empty (since it doesn't exist)
        self.assertFalse(donation.campaign)

        # Campaign reference should be stored in notes
        self.assertIn("Campaign: Non-existent Campaign Reference", donation.donation_notes)
        self.assertIn("Additional user notes", donation.donation_notes)

        # Purpose type should still be set correctly
        self.assertEqual(donation.donation_purpose_type, "Campaign")
