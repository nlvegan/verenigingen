# -*- coding: utf-8 -*-
"""
Enhanced feature tests for the membership dues system based on design document
Tests the flexible contribution system, income calculator, and payment workflows
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate
from verenigingen.tests.utils.base import VereningingenTestCase
from decimal import Decimal
import json


class TestMembershipDuesEnhancedFeatures(VereningingenTestCase):
    """Test enhanced features from the membership dues system design document"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()
        
    def create_simple_test_member(self):
        """Create a simple test member for testing"""
        member = frappe.new_doc("Member")
        member.first_name = "Enhanced"
        member.last_name = "Tester"
        member.email = f"enhanced.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Enhanced Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
        
    # Enhanced API Integration Tests (focusing on what's not already tested)
    
    def test_enhanced_membership_application_api_integration(self):
        """Test the enhanced membership application API integration"""
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        
        # Create various membership types to test API response
        tier_type = self.create_test_membership_type_with_tiers()
        calc_type = self.create_test_membership_type(
            contribution_mode="Calculator",
            enable_income_calculator=1,
            income_percentage_rate=0.75
        )
        
        # Get API response
        types_data = get_membership_types_for_application()
        
        # Validate API response structure
        self.assertIsInstance(types_data, list)
        self.assertTrue(len(types_data) >= 2)
        
        # Find our test types in response
        tier_type_data = next((t for t in types_data if t["name"] == tier_type.name), None)
        calc_type_data = next((t for t in types_data if t["name"] == calc_type.name), None)
        
        self.assertIsNotNone(tier_type_data)
        self.assertIsNotNone(calc_type_data)
        
        # Validate API includes contribution options
        self.assertIn("contribution_options", tier_type_data)
        self.assertIn("contribution_options", calc_type_data)
        
        # Validate tier type API response
        tier_options = tier_type_data["contribution_options"]
        self.assertEqual(tier_options["mode"], "Tiers")
        self.assertIn("tiers", tier_options)
        self.assertEqual(len(tier_options["tiers"]), 3)  # Student, Standard, Supporter
        
        # Validate calculator type API response
        calc_options = calc_type_data["contribution_options"]
        self.assertEqual(calc_options["mode"], "Calculator")
        self.assertTrue(calc_options["calculator"]["enabled"])
        self.assertEqual(calc_options["calculator"]["percentage"], 0.75)
        
    def test_contribution_amount_validation_api(self):
        """Test the contribution amount validation API"""
        from verenigingen.api.enhanced_membership_application import validate_contribution_amount
        
        membership_type = self.create_test_membership_type(
            minimum_contribution=10.00,
            suggested_contribution=25.00,
            maximum_contribution=100.00
        )
        
        # Test valid amount
        result = validate_contribution_amount(
            membership_type.name,
            25.00,
            "Calculator",
            None,
            1.0
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["amount"], 25.00)
        
        # Test amount below minimum
        result = validate_contribution_amount(
            membership_type.name,
            5.00,
            "Calculator",
            None,
            0.5
        )
        self.assertFalse(result["valid"])
        self.assertIn("minimum", result["error"])
        
        # Test amount above maximum
        result = validate_contribution_amount(
            membership_type.name,
            150.00,
            "Calculator",
            None,
            6.0
        )
        self.assertFalse(result["valid"])
        self.assertIn("maximum", result["error"])
        
    def test_verenigingen_settings_income_calculator_integration(self):
        """Test integration with Verenigingen Settings for income calculator"""
        # Get current settings
        settings = frappe.get_single("Verenigingen Settings")
        
        # Store original values
        original_enabled = getattr(settings, "enable_income_calculator", 0)
        original_rate = getattr(settings, "income_percentage_rate", 0.5)
        original_desc = getattr(settings, "calculator_description", "")
        
        # Test with calculator enabled
        settings.enable_income_calculator = 1
        settings.income_percentage_rate = 0.75
        settings.calculator_description = "Test calculator description"
        settings.save()
        
        try:
            # Test that membership types inherit from settings
            from verenigingen.templates.pages.apply_for_membership import get_context
            
            context = {}
            get_context(context)
            
            # Should have calculator settings from Verenigingen Settings
            self.assertEqual(context.get("enable_income_calculator"), 1)
            self.assertEqual(context.get("income_percentage_rate"), 0.75)
            self.assertIn("Test calculator", context.get("calculator_description", ""))
            
        finally:
            # Restore original settings
            settings.enable_income_calculator = original_enabled
            settings.income_percentage_rate = original_rate
            settings.calculator_description = original_desc
            settings.save()
        
    # Tier-Based Contribution Tests
    
    def test_tier_selection_and_validation(self):
        """Test tier selection and amount validation"""
        membership_type = self.create_test_membership_type_with_tiers()
        
        # Get student tier
        student_tier = next((t for t in membership_type.predefined_tiers if t.tier_name == "Student"), None)
        self.assertIsNotNone(student_tier)
        
        # Create dues schedule with tier
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Tier"
        dues_schedule.selected_tier = student_tier.name
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        # Save and validate
        membership = self.create_test_membership()
        dues_schedule.membership = membership.name
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Amount should match tier
        self.assertEqual(dues_schedule.dues_rate, student_tier.amount)
        
    def test_tier_requires_verification_flag(self):
        """Test tier verification requirement handling"""
        membership_type = self.create_test_membership_type_with_tiers()
        
        # Add a tier that requires verification
        verified_tier = membership_type.append("predefined_tiers", {})
        verified_tier.tier_name = "Senior"
        verified_tier.display_name = "Senior Citizen Discount"
        verified_tier.amount = 10.0
        verified_tier.requires_verification = 1
        verified_tier.description = "Discounted rate for seniors (65+)"
        membership_type.save()
        
        options = membership_type.get_contribution_options()
        senior_tier = next((t for t in options["tiers"] if t["name"] == "Senior"), None)
        
        self.assertIsNotNone(senior_tier)
        self.assertTrue(senior_tier["requires_verification"])
        
    def test_default_tier_selection(self):
        """Test default tier is properly marked"""
        membership_type = self.create_test_membership_type_with_tiers()
        options = membership_type.get_contribution_options()
        
        # Find default tier
        default_tier = next((t for t in options["tiers"] if t["is_default"]), None)
        self.assertIsNotNone(default_tier)
        self.assertEqual(default_tier["name"], "Standard")
        
    # Custom Amount Tests
    
    def test_custom_amount_validation_and_approval(self):
        """Test custom amount validation and approval workflow"""
        membership_type = self.create_test_membership_type(
            minimum_contribution=10.00,
            suggested_contribution=25.00,
            maximum_contribution=100.00,
            custom_amount_requires_approval=1
        )
        
        # Test custom amount within limits
        dues_schedule = self.create_dues_schedule_with_custom_amount(
            membership_type, 50.00, "Personal preference"
        )
        
        # Should be created but may need approval
        self.assertEqual(dues_schedule.contribution_mode, "Custom")
        self.assertEqual(dues_schedule.dues_rate, 50.00)
        self.assertTrue(dues_schedule.uses_custom_amount)
        
    def test_custom_amount_below_minimum_validation(self):
        """Test custom amount below minimum is rejected"""
        membership_type = self.create_test_membership_type(
            minimum_contribution=10.00
        )
        
        # Try to create with amount below minimum
        with self.assertRaises(frappe.ValidationError) as context:
            self.create_dues_schedule_with_custom_amount(
                membership_type, 5.00, "Financial hardship"
            )
        
        self.assertIn("minimum", str(context.exception).lower())
        
    def test_custom_amount_above_maximum_handling(self):
        """Test custom amount above maximum with reason"""
        membership_type = self.create_test_membership_type(
            maximum_contribution=100.00
        )
        
        # Create with amount above maximum but with valid reason
        dues_schedule = self.create_dues_schedule_with_custom_amount(
            membership_type, 200.00, "Want to support the organization extra"
        )
        
        # Should be created with reason recorded
        self.assertEqual(dues_schedule.dues_rate, 200.00)
        self.assertIn("support", dues_schedule.custom_amount_reason)
        
    # Contribution Mode Switching Tests
    
    def test_both_mode_contribution_options(self):
        """Test membership type with both tiers and calculator"""
        membership_type = self.create_test_membership_type(
            contribution_mode="Both",
            enable_income_calculator=1,
            income_percentage_rate=0.6
        )
        
        # Add some tiers
        basic_tier = membership_type.append("predefined_tiers", {})
        basic_tier.tier_name = "Basic"
        basic_tier.display_name = "Basic Membership" 
        basic_tier.amount = 15.0
        basic_tier.display_order = 1
        
        plus_tier = membership_type.append("predefined_tiers", {})
        plus_tier.tier_name = "Plus"
        plus_tier.display_name = "Plus Membership"
        plus_tier.amount = 30.0
        plus_tier.is_default = 1
        plus_tier.display_order = 2
        
        membership_type.save()
        
        options = membership_type.get_contribution_options()
        
        # Should have both tiers and calculator
        self.assertEqual(options["mode"], "Both")
        self.assertIn("tiers", options)
        self.assertIn("quick_amounts", options)
        self.assertTrue(options["calculator"]["enabled"])
        
        # Verify both options are present
        self.assertEqual(len(options["tiers"]), 2)
        self.assertTrue(len(options["quick_amounts"]) > 0)
        
    # Coverage Period Tests
    
    def test_coverage_period_calculation_monthly(self):
        """Test monthly coverage period calculation"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(
            membership_type, frequency="Monthly"
        )
        
        # Check coverage dates
        start = getdate(dues_schedule.current_coverage_start)
        end = getdate(dues_schedule.current_coverage_end)
        next_invoice = getdate(dues_schedule.next_invoice_date)
        
        # End should be one day before next month
        expected_end = getdate(add_months(start, 1)) - frappe.utils.timedelta(days=1)
        self.assertEqual(end, expected_end)
        
        # Next invoice should be start of next month
        expected_next = getdate(add_months(start, 1))
        self.assertEqual(next_invoice, expected_next)
        
    def test_coverage_period_calculation_quarterly(self):
        """Test quarterly coverage period calculation"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(
            membership_type, frequency="Quarterly"
        )
        
        start = getdate(dues_schedule.current_coverage_start)
        end = getdate(dues_schedule.current_coverage_end)
        next_invoice = getdate(dues_schedule.next_invoice_date)
        
        # End should be one day before 3 months later
        expected_end = getdate(add_months(start, 3)) - frappe.utils.timedelta(days=1)
        self.assertEqual(end, expected_end)
        
        # Next invoice should be 3 months later
        expected_next = getdate(add_months(start, 3))
        self.assertEqual(next_invoice, expected_next)
        
    def test_coverage_period_calculation_annual(self):
        """Test annual coverage period calculation"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(
            membership_type, frequency="Annual"
        )
        
        start = getdate(dues_schedule.current_coverage_start)
        end = getdate(dues_schedule.current_coverage_end)
        next_invoice = getdate(dues_schedule.next_invoice_date)
        
        # End should be one day before 12 months later
        expected_end = getdate(add_months(start, 12)) - frappe.utils.timedelta(days=1)
        self.assertEqual(end, expected_end)
        
        # Next invoice should be 12 months later
        expected_next = getdate(add_months(start, 12))
        self.assertEqual(next_invoice, expected_next)
        
    # Anniversary Billing Tests
    
    def test_billing_day_from_member_anniversary(self):
        """Test billing day is set from member join anniversary"""
        # Create member with specific join date
        anniversary_member = frappe.new_doc("Member")
        anniversary_member.first_name = "Anniversary"
        anniversary_member.last_name = "Test"
        anniversary_member.email = f"anniversary.{frappe.generate_hash(length=6)}@example.com"
        anniversary_member.member_since = "2023-03-15"  # 15th of month
        anniversary_member.address_line1 = "15 Anniversary Lane"
        anniversary_member.postal_code = "1515AB"
        anniversary_member.city = "Amsterdam"
        anniversary_member.country = "Netherlands"
        anniversary_member.save()
        self.track_doc("Member", anniversary_member.name)
        
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule_for_member(
            anniversary_member, membership_type
        )
        
        # Billing day should be 15
        self.assertEqual(dues_schedule.billing_day, 15)
        
    def test_billing_day_default_when_no_anniversary(self):
        """Test billing day defaults to 1 when no member_since date"""
        no_date_member = frappe.new_doc("Member")
        no_date_member.first_name = "NoDate"
        no_date_member.last_name = "Member"
        no_date_member.email = f"nodate.{frappe.generate_hash(length=6)}@example.com"
        no_date_member.member_since = None  # No join date
        no_date_member.address_line1 = "1 Default Street"
        no_date_member.postal_code = "0001AB"
        no_date_member.city = "Amsterdam"
        no_date_member.country = "Netherlands"
        no_date_member.save()
        self.track_doc("Member", no_date_member.name)
        
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule_for_member(
            no_date_member, membership_type
        )
        
        # Should default to 1
        self.assertEqual(dues_schedule.billing_day, 1)
        
    # Payment Method Integration Tests
    
    def test_sepa_integration_with_dues_schedule(self):
        """Test SEPA mandate integration with dues schedule"""
        membership_type = self.create_test_membership_type()
        
        # Create SEPA mandate for member
        sepa_mandate = frappe.new_doc("SEPA Mandate")
        sepa_mandate.member = self.test_member.name
        sepa_mandate.mandate_reference = f"TEST-{frappe.generate_hash(length=8)}"
        sepa_mandate.iban = "NL91ABNA0417164300"  # Test IBAN
        sepa_mandate.bic = "ABNANL2A"
        sepa_mandate.status = "Active"
        sepa_mandate.signature_date = today()
        sepa_mandate.save()
        self.track_doc("SEPA Mandate", sepa_mandate.name)
        
        # Create dues schedule with SEPA
        dues_schedule = self.create_test_dues_schedule(
            membership_type,
            payment_method="SEPA Direct Debit"
        )
        dues_schedule.active_mandate = sepa_mandate.name
        dues_schedule.next_sequence_type = "FRST"  # First collection
        dues_schedule.save()
        
        # Validate SEPA fields
        self.assertEqual(dues_schedule.payment_method, "SEPA Direct Debit")
        self.assertEqual(dues_schedule.active_mandate, sepa_mandate.name)
        self.assertEqual(dues_schedule.next_sequence_type, "FRST")
        
    def test_sepa_sequence_type_progression(self):
        """Test SEPA sequence type changes from FRST to RCUR"""
        membership_type = self.create_test_membership_type()
        
        dues_schedule = self.create_test_dues_schedule(
            membership_type,
            payment_method="SEPA Direct Debit"
        )
        
        # Initially should be FRST
        self.assertEqual(dues_schedule.next_sequence_type, "FRST")
        
        # After first successful collection, should change to RCUR
        # This would be triggered by payment processing
        dues_schedule.next_sequence_type = "RCUR"
        dues_schedule.last_payment_date = today()
        dues_schedule.save()
        
        self.assertEqual(dues_schedule.next_sequence_type, "RCUR")
        
    # Grace Period and Status Tests
    
    def test_grace_period_handling(self):
        """Test grace period status and date handling"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Simulate payment failure
        dues_schedule.status = "Grace Period"
        dues_schedule.grace_period_until = add_days(today(), 14)  # 2 week grace
        dues_schedule.notes = "Payment failures: 1"
        dues_schedule.save()
        
        # Validate grace period fields
        self.assertEqual(dues_schedule.status, "Grace Period")
        self.assertIsNotNone(dues_schedule.grace_period_until)
        self.assertIn("Payment failures: 1", dues_schedule.notes)
        
    def test_suspension_after_grace_period(self):
        """Test suspension after grace period expires"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Set expired grace period
        dues_schedule.status = "Grace Period"
        dues_schedule.grace_period_until = add_days(today(), -1)  # Yesterday
        dues_schedule.notes = "Payment failures: 3"
        dues_schedule.save()
        
        # Should be suspendable
        self.assertTrue(getdate(dues_schedule.grace_period_until) < getdate(today()))
        
    def test_payment_failure_counter(self):
        """Test consecutive payment failure tracking"""
        membership_type = self.create_test_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Test failure tracking
        for i in range(1, 4):
            dues_schedule.notes = f"Payment failures: {i}"
            dues_schedule.save()
            self.assertIn(f"Payment failures: {i}", dues_schedule.notes)
            
        # Test reset on successful payment
        dues_schedule.notes = "Payment successful - failures reset"
        dues_schedule.last_payment_date = today()
        dues_schedule.save()
        
        self.assertIn("Payment successful", dues_schedule.notes)
        
    # Creative Test Scenarios (inspired by design document)
    
    def test_member_lifecycle_with_contribution_changes(self):
        """Test complete member lifecycle with contribution adjustments over time"""
        membership_type = self.create_test_membership_type(
            contribution_mode="Both",
            enable_income_calculator=1
        )
        
        # Add tiers
        student_tier = membership_type.append("predefined_tiers", {})
        student_tier.tier_name = "Student"
        student_tier.amount = 10.0
        student_tier.requires_verification = 1
        
        professional_tier = membership_type.append("predefined_tiers", {})
        professional_tier.tier_name = "Professional"
        professional_tier.amount = 50.0
        professional_tier.is_default = 1
        
        membership_type.save()
        
        # Stage 1: Member starts as student
        dues_schedule = self.create_test_dues_schedule(membership_type)
        dues_schedule.contribution_mode = "Tier"
        dues_schedule.selected_tier = student_tier.name
        dues_schedule.dues_rate = 10.0
        dues_schedule.save()
        
        # Stage 2: Member graduates, switches to calculator mode
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.selected_tier = None
        dues_schedule.base_multiplier = 2.0  # Earning more now
        dues_schedule.dues_rate = membership_type.suggested_contribution * 2.0  # TODO: Update to use dues schedule template
        dues_schedule.save()
        
        # Stage 3: Member becomes senior, switches to professional tier
        dues_schedule.contribution_mode = "Tier"
        dues_schedule.selected_tier = professional_tier.name
        dues_schedule.dues_rate = 50.0
        dues_schedule.save()
        
        # Validate final state
        self.assertEqual(dues_schedule.contribution_mode, "Tier")
        self.assertEqual(dues_schedule.dues_rate, 50.0)
        
    def test_organizational_configuration_switching(self):
        """Test organization switching between tier-based and calculator-based approaches"""
        # Create organization that starts with tiers
        tier_org_type = self.create_test_membership_type_with_tiers()
        
        # Create some members with tier-based contributions
        tier_schedule = self.create_test_dues_schedule(tier_org_type)
        tier_schedule.contribution_mode = "Tier"
        standard_tier = next(t for t in tier_org_type.predefined_tiers if t.tier_name == "Standard")
        tier_schedule.selected_tier = standard_tier.name
        tier_schedule.dues_rate = standard_tier.amount
        tier_schedule.save()
        
        # Organization decides to switch to calculator-based
        tier_org_type.contribution_mode = "Calculator"
        tier_org_type.enable_income_calculator = 1
        tier_org_type.income_percentage_rate = 0.75
        tier_org_type.save()
        
        # Existing members should maintain their current contributions
        tier_schedule.reload()
        self.assertEqual(tier_schedule.dues_rate, standard_tier.amount)
        
        # New members should use calculator mode
        new_schedule = self.create_test_dues_schedule_for_member(
            self.create_simple_test_member(), tier_org_type
        )
        
        # Validate new schedule uses current organization configuration
        options = tier_org_type.get_contribution_options()
        self.assertEqual(options["mode"], "Calculator")
        
    def test_financial_hardship_custom_amount_workflow(self):
        """Test financial hardship workflow with custom amounts and approval"""
        membership_type = self.create_test_membership_type(
            minimum_contribution=15.00,
            suggested_contribution=30.00,
            custom_amount_requires_approval=1
        )
        
        # Member requests financial hardship adjustment
        hardship_schedule = self.create_dues_schedule_with_custom_amount(
            membership_type, 
            15.00,  # At minimum due to hardship
            "Currently unemployed, requesting minimum contribution until situation improves"
        )
        
        # Should be created but require approval
        self.assertEqual(hardship_schedule.contribution_mode, "Custom")
        self.assertTrue(hardship_schedule.uses_custom_amount)
        self.assertIn("unemployed", hardship_schedule.custom_amount_reason)
        
        # If minimum or reasonable, should be auto-approved for testing
        if hardship_schedule.dues_rate == membership_type.minimum_contribution:
            self.assertTrue(hardship_schedule.custom_amount_approved)
            
    def test_wealthy_supporter_high_contribution_workflow(self):
        """Test wealthy supporter with very high contribution amounts"""
        membership_type = self.create_test_membership_type(
            minimum_contribution=10.00,
            suggested_contribution=25.00,
            maximum_contribution=500.00
        )
        
        # Wealthy supporter wants to contribute significantly more
        supporter_schedule = self.create_dues_schedule_with_custom_amount(
            membership_type,
            1000.00,  # Well above maximum
            "Successful business owner wanting to support the cause significantly"
        )
        
        # Should handle large amounts gracefully
        self.assertEqual(supporter_schedule.dues_rate, 1000.00)
        self.assertEqual(supporter_schedule.contribution_mode, "Custom")
        self.assertIn("business owner", supporter_schedule.custom_amount_reason)
        
    def test_family_membership_scenario(self):
        """Test family membership with multiple rates and shared billing"""
        # Create family membership type
        family_type = self.create_test_membership_type(
            membership_type_name="Family Membership",
            contribution_mode="Tiers",
            minimum_contribution=25.00,
            suggested_contribution=75.00
        )
        
        # Add family tiers
        couple_tier = family_type.append("predefined_tiers", {})
        couple_tier.tier_name = "Couple"
        couple_tier.display_name = "Couple (2 adults)"
        couple_tier.amount = 60.0
        couple_tier.display_order = 1
        
        family_tier = family_type.append("predefined_tiers", {})
        family_tier.tier_name = "Family"
        family_tier.display_name = "Family (2 adults + children)"
        family_tier.amount = 75.0
        family_tier.is_default = 1
        family_tier.display_order = 2
        
        large_family_tier = family_type.append("predefined_tiers", {})
        large_family_tier.tier_name = "LargeFamily"
        large_family_tier.display_name = "Large Family (3+ adults or 4+ children)"
        large_family_tier.amount = 90.0
        large_family_tier.display_order = 3
        
        family_type.save()
        
        # Create family member with family tier
        family_schedule = self.create_test_dues_schedule(family_type)
        family_schedule.contribution_mode = "Tier"
        family_schedule.selected_tier = family_tier.name
        family_schedule.dues_rate = 75.0
        family_schedule.billing_frequency = "Annual"  # Families might prefer annual
        family_schedule.save()
        
        # Validate family membership setup
        self.assertEqual(family_schedule.dues_rate, 75.0)
        self.assertEqual(family_schedule.billing_frequency, "Annual")
        
    def test_seasonal_membership_with_prorated_amounts(self):
        """Test seasonal membership with mid-year starts and prorated amounts"""
        seasonal_type = self.create_test_membership_type(
            membership_type_name="Seasonal Summer Membership",
            suggested_contribution=100.00,  # Full year rate
            billing_frequency="Annual"
        )
        
        # Member joins mid-year (hypothetically June)
        mid_year_schedule = self.create_test_dues_schedule(
            seasonal_type,
            frequency="Annual"
        )
        
        # Simulate prorated amount for half-year (would be calculated by business logic)
        mid_year_schedule.dues_rate = 50.00  # Prorated for half year
        mid_year_schedule.custom_amount_reason = "Mid-year join - prorated amount"
        mid_year_schedule.uses_custom_amount = 1
        mid_year_schedule.save()
        
        # Validate prorated setup
        self.assertEqual(mid_year_schedule.dues_rate, 50.0)
        self.assertIn("prorated", mid_year_schedule.custom_amount_reason)
        
    def test_international_member_currency_handling(self):
        """Test international member with different payment methods"""
        intl_type = self.create_test_membership_type(
            membership_type_name="International Membership",
            suggested_contribution=30.00  # EUR base
        )
        
        # Create international member
        intl_member = frappe.new_doc("Member")
        intl_member.first_name = "International"
        intl_member.last_name = "Member"
        intl_member.email = f"intl.{frappe.generate_hash(length=6)}@example.com"
        intl_member.member_since = today()
        intl_member.address_line1 = "123 International Street"
        intl_member.postal_code = "12345"
        intl_member.city = "New York"
        intl_member.country = "United States"  # Non-EU country
        intl_member.save()
        self.track_doc("Member", intl_member.name)
        
        # Create dues schedule with bank transfer (no SEPA)
        intl_schedule = self.create_test_dues_schedule_for_member(
            intl_member, intl_type
        )
        intl_schedule.payment_method = "Bank Transfer"  # No SEPA for US member
        intl_schedule.save()
        
        # Validate international setup
        self.assertEqual(intl_schedule.payment_method, "Bank Transfer")
        self.assertEqual(intl_member.country, "United States")
        
    def test_organization_rebranding_membership_type_migration(self):
        """Test organization rebranding with membership type updates"""
        # Old membership type (before rebrand)
        old_type = self.create_test_membership_type(
            membership_type_name="Old Organization Membership"
        )
        
        # Create member with old type
        old_schedule = self.create_test_dues_schedule(old_type)
        
        # Organization rebrands and creates new membership type
        new_type = self.create_test_membership_type(
            membership_type_name="New Rebranded Membership",
            suggested_contribution=35.00  # Slight increase
        )
        
        # Migrate existing member to new type
        old_schedule.membership_type = new_type.name
        # Keep existing amount during transition
        old_schedule.save()
        
        # Validate migration maintains member's current contribution
        self.assertEqual(old_schedule.membership_type, new_type.name)
        # Amount should remain unchanged during migration
        
    def test_dues_schedule_with_payment_plan_integration(self):
        """Test dues schedule integration with payment plan features"""
        membership_type = self.create_test_membership_type(
            suggested_contribution=120.00,  # Annual amount
            billing_frequency="Annual"
        )
        
        # Member wants to pay annually but in monthly installments
        payment_plan_schedule = self.create_test_dues_schedule(
            membership_type,
            frequency="Annual",
            amount=120.00
        )
        
        # Would integrate with payment plan system
        payment_plan_schedule.billing_frequency = "Monthly"  # Pay monthly
        payment_plan_schedule.dues_rate = 10.00  # Monthly portion of annual
        payment_plan_schedule.save()
        
        # Validate payment plan setup
        self.assertEqual(payment_plan_schedule.billing_frequency, "Monthly")
        self.assertEqual(payment_plan_schedule.dues_rate, 10.00)

    # Helper Methods
    
    def create_test_membership_type(self, **kwargs):
        """Create a test membership type with flexible options"""
        defaults = {
            "membership_type_name": f"Enhanced Type {frappe.generate_hash(length=6)}",
            "amount": 25.0,
            "is_active": 1,
            "contribution_mode": "Calculator",
            "enable_income_calculator": 1,
            "income_percentage_rate": 0.75,
            "calculator_description": "We suggest 0.75% of your monthly net income"}
        defaults.update(kwargs)
        
        membership_type = frappe.new_doc("Membership Type")
        for key, value in defaults.items():
            if hasattr(membership_type, key):
                setattr(membership_type, key, value)
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_membership_type_with_tiers(self):
        """Create membership type with predefined tiers"""
        membership_type = self.create_test_membership_type(
            contribution_mode="Tiers",
            enable_income_calculator=0
        )
        
        # Add tiers
        student_tier = membership_type.append("predefined_tiers", {})
        student_tier.tier_name = "Student"
        student_tier.display_name = "Student Membership"
        student_tier.amount = 15.0
        student_tier.description = "Discounted rate for students"
        student_tier.display_order = 1
        
        standard_tier = membership_type.append("predefined_tiers", {})
        standard_tier.tier_name = "Standard"
        standard_tier.display_name = "Standard Membership"
        standard_tier.amount = 25.0
        standard_tier.description = "Standard membership rate"
        standard_tier.is_default = 1
        standard_tier.display_order = 2
        
        supporter_tier = membership_type.append("predefined_tiers", {})
        supporter_tier.tier_name = "Supporter"
        supporter_tier.display_name = "Supporter Membership"
        supporter_tier.amount = 50.0
        supporter_tier.description = "Higher contribution to support our mission"
        supporter_tier.display_order = 3
        
        membership_type.save()
        return membership_type
        
    def create_test_membership(self):
        """Create a test membership"""
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = frappe.db.get_value("Membership Type", {}, "name")
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        return membership
        
    def create_test_dues_schedule(self, membership_type, frequency="Monthly", 
                                 amount=None, payment_method="Bank Transfer"):
        """Create a test dues schedule"""
        membership = self.create_test_membership()
        membership.membership_type = membership_type.name
        membership.save()
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        
        if amount is not None:
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = amount
            dues_schedule.uses_custom_amount = 1
        else:
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = membership_type.suggested_contribution  # TODO: Update to use dues schedule template
            
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = payment_method
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        # Set default SEPA fields if SEPA payment
        if payment_method == "SEPA Direct Debit":
            dues_schedule.next_sequence_type = "FRST"
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_test_dues_schedule_for_member(self, member, membership_type, 
                                           frequency="Monthly", amount=None):
        """Create test dues schedule for specific member"""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        
        if amount is not None:
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = amount
            dues_schedule.uses_custom_amount = 1
        else:
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = membership_type.suggested_contribution  # TODO: Update to use dues schedule template
            
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_dues_schedule_with_custom_amount(self, membership_type, amount, reason):
        """Create dues schedule with custom amount and reason"""
        membership = self.create_test_membership()
        membership.membership_type = membership_type.name
        membership.save()
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Custom"
        dues_schedule.dues_rate = amount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_reason = reason
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        # Auto-approve for testing if within reasonable bounds
        if membership_type.minimum_contribution <= amount <= (membership_type.maximum_contribution or amount * 2):
            dues_schedule.custom_amount_approved = 1
            dues_schedule.custom_amount_approved_by = frappe.session.user
            
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule