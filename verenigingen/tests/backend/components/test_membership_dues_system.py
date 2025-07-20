# -*- coding: utf-8 -*-
"""
Comprehensive unit tests for the enhanced membership dues system
Tests the flexible contribution system with tiers, calculator, and custom amounts
"""

import frappe
from frappe.utils import today, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.fixtures.test_data_factory import TestDataFactory


class TestMembershipDuesSystem(VereningingenTestCase):
    """Test the enhanced membership dues system functionality"""

    def setUp(self):
        super().setUp()
        self.factory = TestDataFactory(cleanup_on_exit=False)
        self.test_member = self.create_simple_test_member()
        
    def test_tier_based_membership_type(self):
        """Test membership type with predefined tiers"""
        membership_type = self.create_test_membership_type_with_tiers()
        
        # Validate configuration
        self.assertEqual(membership_type.contribution_mode, "Tiers")
        self.assertEqual(len(membership_type.predefined_tiers), 3)
        self.assertFalse(membership_type.enable_income_calculator)
        
        # Test contribution options
        options = membership_type.get_contribution_options()
        self.assertEqual(options["mode"], "Tiers")
        self.assertTrue("tiers" in options)
        self.assertEqual(len(options["tiers"]), 3)
        
        # Verify tier ordering
        tiers = sorted(options["tiers"], key=lambda x: x["display_order"])
        self.assertEqual(tiers[0]["name"], "Student")
        self.assertEqual(tiers[1]["name"], "Standard") 
        self.assertEqual(tiers[2]["name"], "Supporter")
        
    def test_calculator_based_membership_type(self):
        """Test membership type with income calculator"""
        membership_type = self.create_test_membership_type_with_calculator()
        
        # Validate configuration
        self.assertEqual(membership_type.contribution_mode, "Calculator")
        self.assertTrue(membership_type.enable_income_calculator)
        self.assertEqual(membership_type.income_percentage_rate, 0.75)
        
        # Test contribution options
        options = membership_type.get_contribution_options()
        self.assertEqual(options["mode"], "Calculator")
        self.assertTrue(options["calculator"]["enabled"])
        self.assertEqual(options["calculator"]["percentage"], 0.75)
        self.assertTrue("quick_amounts" in options)
        
    def test_flexible_membership_type(self):
        """Test membership type with both tiers and calculator"""
        membership_type = self.create_test_membership_type_flexible()
        
        # Validate configuration
        self.assertEqual(membership_type.contribution_mode, "Both")
        self.assertTrue(membership_type.enable_income_calculator)
        self.assertTrue(len(membership_type.predefined_tiers) > 0)
        
        # Test contribution options
        options = membership_type.get_contribution_options()
        self.assertEqual(options["mode"], "Both")
        self.assertTrue("tiers" in options)
        self.assertTrue("quick_amounts" in options)
        self.assertTrue(options["calculator"]["enabled"])
        
    def test_membership_dues_schedule_creation(self):
        """Test creating membership dues schedule with different contribution modes"""
        membership_type = self.create_test_membership_type_with_tiers()
        
        # Create a test membership first
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        # Create tier-based schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Tier"
        dues_schedule.selected_tier = membership_type.predefined_tiers[0].name  # Student tier
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = "SEPA Direct Debit"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0  # Test mode
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Validate amount was set from tier
        student_tier_amount = membership_type.predefined_tiers[0].amount
        self.assertEqual(dues_schedule.dues_rate, student_tier_amount)
        
        # Validate dates were calculated
        self.assertIsNotNone(dues_schedule.current_coverage_start)
        self.assertIsNotNone(dues_schedule.current_coverage_end)
        self.assertIsNotNone(dues_schedule.next_invoice_date)
        
    def test_membership_dues_schedule_calculator_mode(self):
        """Test dues schedule with calculator mode"""
        membership_type = self.create_test_membership_type_with_calculator()
        
        # Create a test membership first
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.base_multiplier = 1.5  # 150% of suggested amount
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Validate amount calculation
        expected_amount = membership_type.suggested_contribution * 1.5
        self.assertEqual(dues_schedule.dues_rate, expected_amount)
        
    def test_membership_dues_schedule_custom_mode(self):
        """Test dues schedule with custom amount"""
        membership_type = self.create_test_membership_type_flexible()
        custom_amount = 42.50
        
        # Create a test membership first
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Custom"
        dues_schedule.dues_rate = custom_amount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_reason = "Financial hardship adjustment"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        # Validate custom configuration
        self.assertEqual(dues_schedule.dues_rate, custom_amount)
        self.assertTrue(dues_schedule.uses_custom_amount)
        self.assertEqual(dues_schedule.custom_amount_reason, "Financial hardship adjustment")
        
    def test_amount_validation(self):
        """Test amount validation against membership type constraints"""
        membership_type = self.create_test_membership_type_with_calculator()
        
        # Test amount below minimum
        with self.assertRaises(frappe.ValidationError):
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = self.test_member.name
            dues_schedule.membership_type = membership_type.name
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = membership_type.minimum_contribution - 1  # Below minimum
            dues_schedule.uses_custom_amount = 1
            dues_schedule.save()
            
    def test_coverage_date_calculation(self):
        """Test coverage date calculation for different billing frequencies"""
        membership_type = self.create_test_membership_type_with_calculator()
        
        # Test monthly billing
        monthly_schedule = self.create_test_dues_schedule(
            membership_type, "Monthly", amount=15.0
        )
        
        start_date = monthly_schedule.current_coverage_start
        end_date = monthly_schedule.current_coverage_end
        next_date = monthly_schedule.next_invoice_date
        
        # Validate monthly calculation
        from frappe.utils import getdate
        expected_end = getdate(add_months(start_date, 1))
        self.assertEqual(getdate(next_date), expected_end)
        
        # Test quarterly billing
        quarterly_schedule = self.create_test_dues_schedule(
            membership_type, "Quarterly", amount=45.0
        )
        
        start_date = quarterly_schedule.current_coverage_start
        next_date = quarterly_schedule.next_invoice_date
        
        # Validate quarterly calculation
        expected_next = getdate(add_months(start_date, 3))
        self.assertEqual(getdate(next_date), expected_next)
        
    def test_billing_day_calculation(self):
        """Test billing day is set based on member anniversary"""
        # Set member anniversary
        self.test_member.member_since = "2023-03-15"
        self.test_member.save()
        
        membership_type = self.create_test_membership_type_with_calculator()
        dues_schedule = self.create_test_dues_schedule(membership_type, "Monthly")
        
        # Billing day should match member anniversary day
        self.assertEqual(dues_schedule.billing_day, 15)
        
    def test_enhanced_application_api(self):
        """Test the enhanced membership application API"""
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        
        # Create test membership types
        tier_type = self.create_test_membership_type_with_tiers()
        calc_type = self.create_test_membership_type_with_calculator()
        
        # Get types for application
        types = get_membership_types_for_application()
        
        # Validate response structure
        self.assertIsInstance(types, list)
        self.assertTrue(len(types) >= 2)
        
        # Find our test types
        tier_type_data = next((t for t in types if t["name"] == tier_type.name), None)
        calc_type_data = next((t for t in types if t["name"] == calc_type.name), None)
        
        self.assertIsNotNone(tier_type_data)
        self.assertIsNotNone(calc_type_data)
        
        # Validate contribution options are included
        self.assertTrue("contribution_options" in tier_type_data)
        self.assertTrue("contribution_options" in calc_type_data)
        
        # Validate tier type has tiers
        tier_options = tier_type_data["contribution_options"]
        self.assertEqual(tier_options["mode"], "Tiers")
        self.assertTrue("tiers" in tier_options)
        
        # Validate calculator type has calculator
        calc_options = calc_type_data["contribution_options"]
        self.assertEqual(calc_options["mode"], "Calculator")
        self.assertTrue(calc_options["calculator"]["enabled"])
        
    def test_contribution_validation_api(self):
        """Test contribution amount validation API"""
        from verenigingen.api.enhanced_membership_application import validate_contribution_amount
        
        membership_type = self.create_test_membership_type_with_calculator()
        
        # Test valid amount
        result = validate_contribution_amount(
            membership_type.name, 
            membership_type.suggested_contribution,
            "Calculator", 
            None, 
            1.0
        )
        self.assertTrue(result["valid"])
        
        # Test amount below minimum
        result = validate_contribution_amount(
            membership_type.name,
            membership_type.minimum_contribution - 1,
            "Calculator",
            None,
            0.5
        )
        self.assertFalse(result["valid"])
        self.assertTrue("minimum" in result["error"])
        
        # Test amount above maximum (if set)
        if membership_type.maximum_contribution:
            result = validate_contribution_amount(
                membership_type.name,
                membership_type.maximum_contribution + 100,
                "Calculator", 
                None,
                10.0
            )
            self.assertFalse(result["valid"])
            self.assertTrue("maximum" in result["error"])
    
    # Helper methods for creating test data
    
    def create_simple_test_member(self):
        """Create a simple test member for testing"""
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Member"
        member.email = f"test.member.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Test Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
    
    def create_test_membership_type_with_tiers(self):
        """Create a test membership type with predefined tiers"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Tier Membership {frappe.generate_hash(length=6)}"
        membership_type.description = "Test membership type with predefined tiers"
        membership_type.amount = 25.0
        membership_type.billing_frequency = "Annual"
        membership_type.is_active = 1
        
        # Contribution system
        membership_type.contribution_mode = "Tiers"
        membership_type.minimum_contribution = 10.0
        membership_type.suggested_contribution = 25.0
        membership_type.maximum_contribution = 100.0
        membership_type.allow_custom_amounts = 1
        membership_type.enable_income_calculator = 0
        
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
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_membership_type_with_calculator(self):
        """Create a test membership type with income calculator"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Calculator Membership {frappe.generate_hash(length=6)}"
        membership_type.description = "Test membership type with income calculator"
        membership_type.amount = 15.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        
        # Contribution system
        membership_type.contribution_mode = "Calculator"
        membership_type.minimum_contribution = 5.0
        membership_type.suggested_contribution = 15.0
        membership_type.maximum_contribution = 150.0
        membership_type.fee_slider_max_multiplier = 10.0
        membership_type.allow_custom_amounts = 1
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.calculator_description = "We suggest 0.75% of your monthly net income"
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_membership_type_flexible(self):
        """Create a test membership type with both tiers and calculator"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Flexible Membership {frappe.generate_hash(length=6)}"
        membership_type.description = "Test membership type with both options"
        membership_type.amount = 20.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        
        # Contribution system
        membership_type.contribution_mode = "Both"
        membership_type.minimum_contribution = 8.0
        membership_type.suggested_contribution = 20.0
        membership_type.maximum_contribution = 200.0
        membership_type.fee_slider_max_multiplier = 10.0
        membership_type.allow_custom_amounts = 1
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.6
        membership_type.calculator_description = "Calculate 0.6% of monthly income or choose from tiers"
        
        # Add basic tiers
        basic_tier = membership_type.append("predefined_tiers", {})
        basic_tier.tier_name = "Basic"
        basic_tier.display_name = "Basic Membership"
        basic_tier.amount = 15.0
        basic_tier.display_order = 1
        
        plus_tier = membership_type.append("predefined_tiers", {})
        plus_tier.tier_name = "Plus"
        plus_tier.display_name = "Plus Membership"
        plus_tier.amount = 20.0
        plus_tier.is_default = 1
        plus_tier.display_order = 2
        
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_dues_schedule(self, membership_type, frequency="Monthly", amount=None):
        """Create a test dues schedule"""
        # Create a test membership first
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.dues_rate = amount or membership_type.suggested_contribution
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0  # Test mode
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule