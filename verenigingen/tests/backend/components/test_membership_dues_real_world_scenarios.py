# -*- coding: utf-8 -*-
"""
Real-world scenario tests for the membership dues system
Tests common organizational workflows and member lifecycle scenarios
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
import time


class TestMembershipDuesRealWorldScenarios(VereningingenTestCase):
    """Test real-world scenarios for membership dues system"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()
        
    def create_simple_test_member(self):
        """Create a simple test member for testing using factory method"""
        return self.create_test_member(
            first_name="Real",
            last_name="World",
            email=f"real.world.{frappe.generate_hash(length=6)}@example.com",
            address_line1="123 Real Street",
            postal_code="1234AB",
            city="Amsterdam"
        )
        
    # Organization Migration Scenarios
    
    def test_organization_switching_from_fixed_to_flexible_dues(self):
        """Test organization switching from fixed amounts to flexible contribution system"""
        # Stage 1: Traditional fixed-amount organization
        traditional_type = self.create_test_membership_type(
            membership_type_name=f"Traditional Fixed {frappe.generate_hash(length=6)}",
            amount=50.0,  # Fixed amount
            billing_frequency="Annual",
            is_active=1
            # Old system - no contribution mode fields
        )
        
        # Create existing members with fixed amounts using factory method
        existing_members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Existing{i}",
                last_name="Member",
                email=f"existing{i}.{frappe.generate_hash(length=4)}@example.com",
                member_since=add_days(today(), -365),  # 1 year ago
                address_line1=f"{i} Existing Street",
                postal_code=f"{2000+i:04d}AB",
                city="Existing City"
            )
            existing_members.append(member)
            
        # Stage 2: Organization decides to switch to flexible contribution system
        # Update membership type to support flexible contributions
        traditional_type.contribution_mode = "Both"  # Support both tiers and calculator
        traditional_type.minimum_contribution = 25.0
        traditional_type.suggested_contribution = 50.0
        traditional_type.maximum_contribution = 500.0
        traditional_type.enable_income_calculator = 1
        traditional_type.income_percentage_rate = 1.0
        traditional_type.calculator_description = "We suggest 1% of your monthly net income"
        
        # Add tiers for different member types
        student_tier = traditional_type.append("predefined_tiers", {})
        student_tier.tier_name = "Student"
        student_tier.display_name = "Student Membership"
        student_tier.amount = 25.0
        student_tier.description = "Reduced rate for students"
        student_tier.display_order = 1
        
        standard_tier = traditional_type.append("predefined_tiers", {})
        standard_tier.tier_name = "Standard"
        standard_tier.display_name = "Standard Membership"
        standard_tier.amount = 50.0
        standard_tier.description = "Standard membership rate"
        standard_tier.is_default = 1
        standard_tier.display_order = 2
        
        supporter_tier = traditional_type.append("predefined_tiers", {})
        supporter_tier.tier_name = "Supporter"
        supporter_tier.display_name = "Supporter Membership"
        supporter_tier.amount = 100.0
        supporter_tier.description = "Higher contribution to support our mission"
        supporter_tier.display_order = 3
        
        traditional_type.save()
        
        # Test that existing members can continue with old amounts
        # while new members get flexible options
        options = traditional_type.get_contribution_options()
        self.assertEqual(options["mode"], "Both")
        self.assertEqual(len(options["tiers"]), 3)
        self.assertTrue(options["calculator"]["enabled"])
        
        # Existing members should be able to upgrade to flexible system voluntarily
        for member in existing_members[:2]:  # First 2 members upgrade
            membership = frappe.new_doc("Membership")
            membership.member = member.name
            membership.membership_type = traditional_type.name
            membership.start_date = today()
            membership.status = "Active"
            membership.save()
            self.track_doc("Membership", membership.name)
            
            # They choose supporter tier
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = member.name
            dues_schedule.membership = membership.name
            dues_schedule.membership_type = traditional_type.name
            dues_schedule.contribution_mode = "Tier"
            dues_schedule.selected_tier = supporter_tier.name
            dues_schedule.dues_rate = 100.0
            dues_schedule.billing_frequency = "Annual"
            dues_schedule.status = "Active"
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            
        # Remaining members stay on old fixed amount (grandfathered)
        # This demonstrates backward compatibility
        
    def test_student_to_professional_lifecycle(self):
        """Test member transitioning from student to professional rates"""
        # Create membership type that supports both scenarios
        lifecycle_type = frappe.new_doc("Membership Type")
        lifecycle_type.membership_type_name = f"Lifecycle Type {frappe.generate_hash(length=6)}"
        lifecycle_type.amount = 50.0
        lifecycle_type.billing_frequency = "Annual"
        lifecycle_type.is_active = 1
        lifecycle_type.contribution_mode = "Tiers"
        lifecycle_type.minimum_contribution = 15.0
        lifecycle_type.suggested_contribution = 50.0
        lifecycle_type.maximum_contribution = 200.0
        
        # Student tier
        student_tier = lifecycle_type.append("predefined_tiers", {})
        student_tier.tier_name = "Student"
        student_tier.display_name = "Student Membership"
        student_tier.amount = 15.0
        student_tier.description = "Reduced rate for full-time students"
        student_tier.requires_verification = 1
        student_tier.display_order = 1
        
        # Professional tier
        professional_tier = lifecycle_type.append("predefined_tiers", {})
        professional_tier.tier_name = "Professional"
        professional_tier.display_name = "Professional Membership"
        professional_tier.amount = 75.0
        professional_tier.description = "Standard rate for working professionals"
        professional_tier.is_default = 1
        professional_tier.display_order = 2
        
        lifecycle_type.save()
        self.track_doc("Membership Type", lifecycle_type.name)
        
        # Student member starts with student rate using factory method
        student_member = self.create_test_member(
            first_name="Student",
            last_name="Member",
            email=f"student.{frappe.generate_hash(length=6)}@university.edu",
            member_since=add_days(today(), -180),  # 6 months ago
            address_line1="University Campus",
            postal_code="1234ST",
            city="University City"
        )
        
        # Initial membership with student rate using factory method
        student_membership = self.create_test_membership(
            member=student_member.name,
            membership_type=lifecycle_type.name,
            start_date=add_days(today(), -180),
            status="Active"
        )
        
        student_dues = self.create_test_dues_schedule(
            member=student_member.name,
            membership_type=lifecycle_type.name,
            contribution_mode="Tier",
            amount=15.0,
            billing_frequency="Annual",
            status="Active"
        )
        
        # Student graduates and gets job - transitions to professional rate
        # Simulate 6 months later
        time.sleep(0.1)  # Small delay to ensure different timestamps
        
        # Update member information
        student_member.email = student_member.email.replace("@university.edu", "@company.com")
        student_member.save()
        
        # Create new dues schedule for professional rate
        professional_dues = frappe.new_doc("Membership Dues Schedule")
        professional_dues.member = student_member.name
        professional_dues.membership = student_membership.name
        professional_dues.membership_type = lifecycle_type.name
        professional_dues.contribution_mode = "Tier"
        professional_dues.selected_tier = professional_tier.name
        professional_dues.amount = 75.0
        professional_dues.billing_frequency = "Annual"
        professional_dues.status = "Active"
        professional_dues.save()
        self.track_doc("Membership Dues Schedule", professional_dues.name)
        
        # Deactivate old student schedule
        student_dues.status = "Inactive"
        student_dues.add_comment(text="Upgraded to professional rate after graduation")
        student_dues.save()
        
        # Verify transition worked correctly
        self.assertEqual(professional_dues.amount, 75.0)
        self.assertEqual(student_dues.status, "Inactive")
        self.assertEqual(professional_dues.status, "Active")
        
    def test_economic_hardship_assistance_workflow(self):
        """Test member requesting reduced rates due to economic hardship"""
        # Create membership type with support for hardship rates
        hardship_type = frappe.new_doc("Membership Type")
        hardship_type.membership_type_name = f"Hardship Support Type {frappe.generate_hash(length=6)}"
        hardship_type.amount = 60.0
        hardship_type.billing_frequency = "Monthly"
        hardship_type.is_active = 1
        hardship_type.contribution_mode = "Calculator"
        hardship_type.minimum_contribution = 5.0  # Very low minimum for hardship cases
        hardship_type.suggested_contribution = 60.0
        hardship_type.maximum_contribution = 600.0
        hardship_type.enable_income_calculator = 1
        hardship_type.income_percentage_rate = 0.5
        hardship_type.allow_custom_amounts = 1
        hardship_type.save()
        self.track_doc("Membership Type", hardship_type.name)
        
        # Member initially paying standard rate
        hardship_member = frappe.new_doc("Member")
        hardship_member.first_name = "Economic"
        hardship_member.last_name = "Hardship"
        hardship_member.email = f"hardship.{frappe.generate_hash(length=6)}@example.com"
        hardship_member.member_since = add_days(today(), -90)
        hardship_member.address_line1 = "456 Hardship Street"
        hardship_member.postal_code = "4567AB"
        hardship_member.city = "Hardship City"
        hardship_member.country = "Netherlands"
        hardship_member.save()
        self.track_doc("Member", hardship_member.name)
        
        hardship_membership = frappe.new_doc("Membership")
        hardship_membership.member = hardship_member.name
        hardship_membership.membership_type = hardship_type.name
        hardship_membership.start_date = add_days(today(), -90)
        hardship_membership.status = "Active"
        hardship_membership.save()
        self.track_doc("Membership", hardship_membership.name)
        
        # Original dues at standard rate
        original_dues = frappe.new_doc("Membership Dues Schedule")
        original_dues.member = hardship_member.name
        original_dues.membership = hardship_membership.name
        original_dues.membership_type = hardship_type.name
        original_dues.contribution_mode = "Calculator"
        original_dues.base_multiplier = 1.0
        original_dues.amount = 60.0
        original_dues.billing_frequency = "Monthly"
        original_dues.status = "Active"
        original_dues.save()
        self.track_doc("Membership Dues Schedule", original_dues.name)
        
        # Member experiences job loss and requests hardship assistance
        # Create hardship dues schedule with custom amount
        hardship_dues = frappe.new_doc("Membership Dues Schedule")
        hardship_dues.member = hardship_member.name
        hardship_dues.membership = hardship_membership.name
        hardship_dues.membership_type = hardship_type.name
        hardship_dues.contribution_mode = "Custom"
        hardship_dues.amount = 10.0  # Reduced amount
        hardship_dues.uses_custom_amount = 1
        hardship_dues.custom_amount_reason = "Temporary economic hardship - job loss"
        hardship_dues.billing_frequency = "Monthly"
        hardship_dues.status = "Draft"  # Pending approval
        hardship_dues.save()
        self.track_doc("Membership Dues Schedule", hardship_dues.name)
        
        # Simulate administrative approval
        hardship_dues.status = "Active"
        hardship_dues.custom_amount_approved = 1
        hardship_dues.custom_amount_approved_by = frappe.session.user
        hardship_dues.custom_amount_approved_date = now_datetime()
        hardship_dues.save()
        
        # Deactivate original schedule
        original_dues.status = "Suspended"
        original_dues.add_comment(text="Suspended due to approved hardship request")
        original_dues.save()
        
        # Verify hardship workflow
        self.assertEqual(hardship_dues.amount, 10.0)
        self.assertTrue(hardship_dues.uses_custom_amount)
        self.assertTrue(hardship_dues.custom_amount_approved)
        self.assertEqual(original_dues.status, "Suspended")
        
        # Test recovery scenario - member finds new job after 6 months
        # Create recovery dues schedule
        recovery_dues = frappe.new_doc("Membership Dues Schedule")
        recovery_dues.member = hardship_member.name
        recovery_dues.membership = hardship_membership.name
        recovery_dues.membership_type = hardship_type.name
        recovery_dues.contribution_mode = "Calculator"
        recovery_dues.base_multiplier = 0.8  # 80% of suggested amount
        recovery_dues.amount = 48.0
        recovery_dues.billing_frequency = "Monthly"
        recovery_dues.status = "Active"
        recovery_dues.save()
        self.track_doc("Membership Dues Schedule", recovery_dues.name)
        
        # Deactivate hardship schedule
        hardship_dues.status = "Completed"
        hardship_dues.add_comment(text="Hardship period ended - member recovered financially")
        hardship_dues.save()
        
        # Verify recovery
        self.assertEqual(recovery_dues.amount, 48.0)
        self.assertEqual(hardship_dues.status, "Completed")
        
    def test_family_membership_scenario(self):
        """Test family membership with shared billing"""
        # Create family membership type
        family_type = frappe.new_doc("Membership Type")
        family_type.membership_type_name = f"Family Membership {frappe.generate_hash(length=6)}"
        family_type.amount = 120.0  # Higher base for family
        family_type.billing_frequency = "Annual"
        family_type.is_active = 1
        family_type.contribution_mode = "Both"
        family_type.minimum_contribution = 80.0
        family_type.suggested_contribution = 120.0
        family_type.maximum_contribution = 500.0
        family_type.enable_income_calculator = 1
        family_type.income_percentage_rate = 1.5
        family_type.calculator_description = "Family rate: 1.5% of household income"
        
        # Family tiers
        small_family_tier = family_type.append("predefined_tiers", {})
        small_family_tier.tier_name = "Small_Family"
        small_family_tier.display_name = "Small Family (2 members)"
        small_family_tier.amount = 100.0
        small_family_tier.description = "For families with 2 members"
        small_family_tier.display_order = 1
        
        large_family_tier = family_type.append("predefined_tiers", {})
        large_family_tier.tier_name = "Large_Family"
        large_family_tier.display_name = "Large Family (3+ members)"
        large_family_tier.amount = 150.0
        large_family_tier.description = "For families with 3 or more members"
        large_family_tier.display_order = 2
        
        family_type.save()
        self.track_doc("Membership Type", family_type.name)
        
        # Create family members
        family_members = []
        
        # Primary member (bill payer)
        primary_member = frappe.new_doc("Member")
        primary_member.first_name = "Primary"
        primary_member.last_name = "Family"
        primary_member.email = f"primary.family.{frappe.generate_hash(length=6)}@example.com"
        primary_member.member_since = today()
        primary_member.address_line1 = "789 Family Avenue"
        primary_member.postal_code = "7890AB"
        primary_member.city = "Family City"
        primary_member.country = "Netherlands"
        primary_member.save()
        self.track_doc("Member", primary_member.name)
        family_members.append(primary_member)
        
        # Spouse
        spouse_member = frappe.new_doc("Member")
        spouse_member.first_name = "Spouse"
        spouse_member.last_name = "Family"
        spouse_member.email = f"spouse.family.{frappe.generate_hash(length=6)}@example.com"
        spouse_member.member_since = today()
        spouse_member.address_line1 = "789 Family Avenue"  # Same address
        spouse_member.postal_code = "7890AB"
        spouse_member.city = "Family City"
        spouse_member.country = "Netherlands"
        spouse_member.save()
        self.track_doc("Member", spouse_member.name)
        family_members.append(spouse_member)
        
        # Child (over 16, eligible for membership)
        child_member = frappe.new_doc("Member")
        child_member.first_name = "Child"
        child_member.last_name = "Family"
        child_member.email = f"child.family.{frappe.generate_hash(length=6)}@example.com"
        child_member.member_since = today()
        child_member.address_line1 = "789 Family Avenue"  # Same address
        child_member.postal_code = "7890AB"
        child_member.city = "Family City"
        child_member.country = "Netherlands"
        child_member.birth_date = add_days(today(), -6570)  # 18 years old
        child_member.save()
        self.track_doc("Member", child_member.name)
        family_members.append(child_member)
        
        # Create family membership - only primary member has dues schedule
        # Others are linked but don't pay separately
        family_membership = frappe.new_doc("Membership")
        family_membership.member = primary_member.name
        family_membership.membership_type = family_type.name
        family_membership.start_date = today()
        family_membership.status = "Active"
        family_membership.save()
        self.track_doc("Membership", family_membership.name)
        
        # Primary member pays for entire family using large family tier
        family_dues = frappe.new_doc("Membership Dues Schedule")
        family_dues.member = primary_member.name
        family_dues.membership = family_membership.name
        family_dues.membership_type = family_type.name
        family_dues.contribution_mode = "Tier"
        family_dues.selected_tier = large_family_tier.name
        family_dues.amount = 150.0
        family_dues.billing_frequency = "Annual"
        family_dues.status = "Active"
        family_dues.notes = f"Family membership covering {len(family_members)} members"
        family_dues.save()
        self.track_doc("Membership Dues Schedule", family_dues.name)
        
        # Create individual memberships for other family members but no separate dues
        for member in family_members[1:]:  # Skip primary member
            individual_membership = frappe.new_doc("Membership")
            individual_membership.member = member.name
            individual_membership.membership_type = family_type.name
            individual_membership.start_date = today()
            individual_membership.status = "Active"
            individual_membership.save()
            self.track_doc("Membership", individual_membership.name)
            
        # Verify family setup
        self.assertEqual(family_dues.amount, 150.0)
        self.assertEqual(len(family_members), 3)
        
        # Test family member leaving (child goes to university)
        # Child's membership becomes inactive, but family dues remain
        child_membership = frappe.get_doc("Membership", {"member": child_member.name})
        child_membership.status = "Inactive"
        child_membership.add_comment(text="Child moved away for university")
        child_membership.save()
        
        # Family could switch to small family tier
        family_dues.selected_tier = small_family_tier.name
        family_dues.amount = 100.0
        family_dues.add_comment(text="Reduced to small family tier - child away at university")
        family_dues.save()
        
        self.assertEqual(family_dues.amount, 100.0)
        
    def test_volunteer_to_board_member_workflow(self):
        """Test member transitioning from volunteer to board member with different rates"""
        # Create membership type with board member tier
        board_type = frappe.new_doc("Membership Type")
        board_type.membership_type_name = f"Board Member Type {frappe.generate_hash(length=6)}"
        board_type.amount = 100.0
        board_type.billing_frequency = "Annual"
        board_type.is_active = 1
        board_type.contribution_mode = "Tiers"
        board_type.minimum_contribution = 25.0
        board_type.suggested_contribution = 100.0
        board_type.maximum_contribution = 1000.0
        
        # Volunteer tier
        volunteer_tier = board_type.append("predefined_tiers", {})
        volunteer_tier.tier_name = "Verenigingen Volunteer"
        volunteer_tier.display_name = "Active Volunteer"
        volunteer_tier.amount = 50.0
        volunteer_tier.description = "Reduced rate for active volunteers"
        volunteer_tier.display_order = 1
        
        # Regular member tier
        regular_tier = board_type.append("predefined_tiers", {})
        regular_tier.tier_name = "Regular"
        regular_tier.display_name = "Regular Member"
        regular_tier.amount = 100.0
        regular_tier.description = "Standard membership rate"
        regular_tier.is_default = 1
        regular_tier.display_order = 2
        
        # Board member tier (higher contribution expected)
        board_tier = board_type.append("predefined_tiers", {})
        board_tier.tier_name = "Board"
        board_tier.display_name = "Board Member"
        board_tier.amount = 200.0
        board_tier.description = "Board members leading by example"
        board_tier.display_order = 3
        
        board_type.save()
        self.track_doc("Membership Type", board_type.name)
        
        # Member starts as regular volunteer
        volunteer_member = frappe.new_doc("Member")
        volunteer_member.first_name = "Future"
        volunteer_member.last_name = "Board"
        volunteer_member.email = f"future.board.{frappe.generate_hash(length=6)}@example.com"
        volunteer_member.member_since = add_days(today(), -730)  # 2 years ago
        volunteer_member.address_line1 = "321 Leadership Lane"
        volunteer_member.postal_code = "3210AB"
        volunteer_member.city = "Leadership City"
        volunteer_member.country = "Netherlands"
        volunteer_member.save()
        self.track_doc("Member", volunteer_member.name)
        
        # Create volunteer record
        volunteer_record = frappe.new_doc("Volunteer")
        volunteer_record.volunteer_name = f"{volunteer_member.first_name} {volunteer_member.last_name}"
        volunteer_record.email = volunteer_member.email
        volunteer_record.member = volunteer_member.name
        volunteer_record.status = "Active"
        volunteer_record.start_date = add_days(today(), -730)
        volunteer_record.skills = "Leadership, Communication, Event Organization"
        volunteer_record.save()
        self.track_doc("Volunteer", volunteer_record.name)
        
        # Initial membership with volunteer rate
        volunteer_membership = frappe.new_doc("Membership")
        volunteer_membership.member = volunteer_member.name
        volunteer_membership.membership_type = board_type.name
        volunteer_membership.start_date = add_days(today(), -730)
        volunteer_membership.status = "Active"
        volunteer_membership.save()
        self.track_doc("Membership", volunteer_membership.name)
        
        volunteer_dues = frappe.new_doc("Membership Dues Schedule")
        volunteer_dues.member = volunteer_member.name
        volunteer_dues.membership = volunteer_membership.name
        volunteer_dues.membership_type = board_type.name
        volunteer_dues.contribution_mode = "Tier"
        volunteer_dues.selected_tier = volunteer_tier.name
        volunteer_dues.amount = 50.0
        volunteer_dues.billing_frequency = "Annual"
        volunteer_dues.status = "Active"
        volunteer_dues.save()
        self.track_doc("Membership Dues Schedule", volunteer_dues.name)
        
        # After 1 year of active volunteering, member is elected to board
        # Create new dues schedule for board member rate
        board_dues = frappe.new_doc("Membership Dues Schedule")
        board_dues.member = volunteer_member.name
        board_dues.membership = volunteer_membership.name
        board_dues.membership_type = board_type.name
        board_dues.contribution_mode = "Tier"
        board_dues.selected_tier = board_tier.name
        board_dues.amount = 200.0
        board_dues.billing_frequency = "Annual"
        board_dues.status = "Active"
        board_dues.save()
        self.track_doc("Membership Dues Schedule", board_dues.name)
        
        # Deactivate volunteer dues
        volunteer_dues.status = "Completed"
        volunteer_dues.add_comment(text="Transitioned to board member rate")
        volunteer_dues.save()
        
        # Update volunteer record to reflect board position
        volunteer_record.status = "Board Member"
        volunteer_record.add_comment(text="Elected to board of directors")
        volunteer_record.save()
        
        # Verify transition
        self.assertEqual(board_dues.amount, 200.0)
        self.assertEqual(volunteer_dues.status, "Completed")
        self.assertEqual(volunteer_record.status, "Board Member")
        
        # Test end of board term - member returns to volunteer rate
        # After 2 years, board term ends
        post_board_dues = frappe.new_doc("Membership Dues Schedule")
        post_board_dues.member = volunteer_member.name
        post_board_dues.membership = volunteer_membership.name
        post_board_dues.membership_type = board_type.name
        post_board_dues.contribution_mode = "Tier"
        post_board_dues.selected_tier = volunteer_tier.name  # Back to volunteer rate
        post_board_dues.amount = 50.0
        post_board_dues.billing_frequency = "Annual"
        post_board_dues.status = "Active"
        post_board_dues.save()
        self.track_doc("Membership Dues Schedule", post_board_dues.name)
        
        # Complete board dues
        board_dues.status = "Completed"
        board_dues.add_comment(text="Board term ended - returning to volunteer rate")
        board_dues.save()
        
        # Update volunteer status
        volunteer_record.status = "Active"
        volunteer_record.add_comment(text="Board term completed - continuing as volunteer")
        volunteer_record.save()
        
        # Verify return to volunteer status
        self.assertEqual(post_board_dues.amount, 50.0)
        self.assertEqual(board_dues.status, "Completed")
        self.assertEqual(volunteer_record.status, "Active")
        
    def test_seasonal_membership_adjustments(self):
        """Test seasonal membership rate adjustments"""
        # Create membership type supporting seasonal adjustments
        seasonal_type = frappe.new_doc("Membership Type")
        seasonal_type.membership_type_name = f"Seasonal Type {frappe.generate_hash(length=6)}"
        seasonal_type.amount = 40.0
        seasonal_type.subscription_period = "Monthly"
        seasonal_type.is_active = 1
        seasonal_type.contribution_mode = "Calculator"
        seasonal_type.minimum_contribution = 10.0
        seasonal_type.suggested_contribution = 40.0
        seasonal_type.maximum_contribution = 200.0
        seasonal_type.enable_income_calculator = 1
        seasonal_type.income_percentage_rate = 0.8
        seasonal_type.allow_custom_amounts = 1
        seasonal_type.save()
        self.track_doc("Membership Type", seasonal_type.name)
        
        # Seasonal worker member (tourism industry)
        seasonal_member = frappe.new_doc("Member")
        seasonal_member.first_name = "Seasonal"
        seasonal_member.last_name = "Worker"
        seasonal_member.email = f"seasonal.{frappe.generate_hash(length=6)}@tourism.com"
        seasonal_member.member_since = today()
        seasonal_member.address_line1 = "555 Tourism Boulevard"
        seasonal_member.postal_code = "5555AB"
        seasonal_member.city = "Resort Town"
        seasonal_member.country = "Netherlands"
        seasonal_member.save()
        self.track_doc("Member", seasonal_member.name)
        
        seasonal_membership = frappe.new_doc("Membership")
        seasonal_membership.member = seasonal_member.name
        seasonal_membership.membership_type = seasonal_type.name
        seasonal_membership.start_date = today()
        seasonal_membership.status = "Active"
        seasonal_membership.save()
        self.track_doc("Membership", seasonal_membership.name)
        
        # Summer season - full income, full rate
        summer_dues = frappe.new_doc("Membership Dues Schedule")
        summer_dues.member = seasonal_member.name
        summer_dues.membership = seasonal_membership.name
        summer_dues.membership_type = seasonal_type.name
        summer_dues.contribution_mode = "Calculator"
        summer_dues.base_multiplier = 1.0
        summer_dues.amount = 40.0
        summer_dues.billing_frequency = "Monthly"
        summer_dues.status = "Active"
        summer_dues.notes = "Summer season - full employment"
        summer_dues.save()
        self.track_doc("Membership Dues Schedule", summer_dues.name)
        
        # Winter season - reduced income, request reduced rate
        winter_dues = frappe.new_doc("Membership Dues Schedule")
        winter_dues.member = seasonal_member.name
        winter_dues.membership = seasonal_membership.name
        winter_dues.membership_type = seasonal_type.name
        winter_dues.contribution_mode = "Custom"
        winter_dues.amount = 15.0  # Reduced winter rate
        winter_dues.uses_custom_amount = 1
        winter_dues.custom_amount_reason = "Seasonal employment - reduced winter income"
        winter_dues.billing_frequency = "Monthly"
        winter_dues.status = "Active"
        winter_dues.custom_amount_approved = 1
        winter_dues.custom_amount_approved_by = frappe.session.user
        winter_dues.custom_amount_approved_date = now_datetime()
        winter_dues.save()
        self.track_doc("Membership Dues Schedule", winter_dues.name)
        
        # Suspend summer schedule during winter
        summer_dues.status = "Suspended"
        summer_dues.add_comment(text="Suspended for winter season")
        summer_dues.save()
        
        # Next summer - return to full rate
        next_summer_dues = frappe.new_doc("Membership Dues Schedule")
        next_summer_dues.member = seasonal_member.name
        next_summer_dues.membership = seasonal_membership.name
        next_summer_dues.membership_type = seasonal_type.name
        next_summer_dues.contribution_mode = "Calculator"
        next_summer_dues.base_multiplier = 1.2  # Slight increase
        next_summer_dues.amount = 48.0
        next_summer_dues.billing_frequency = "Monthly"
        next_summer_dues.status = "Active"
        next_summer_dues.notes = "Next summer season - income increased"
        next_summer_dues.save()
        self.track_doc("Membership Dues Schedule", next_summer_dues.name)
        
        # Complete winter schedule
        winter_dues.status = "Completed"
        winter_dues.add_comment(text="Winter season ended")
        winter_dues.save()
        
        # Verify seasonal adjustments
        self.assertEqual(summer_dues.amount, 40.0)
        self.assertEqual(winter_dues.amount, 15.0)
        self.assertEqual(next_summer_dues.amount, 48.0)
        self.assertEqual(winter_dues.status, "Completed")
        self.assertEqual(next_summer_dues.status, "Active")
        
    # Helper Methods for Real World Tests
    
    def create_test_membership_type(self, name_suffix="", **kwargs):
        """Create a test membership type with default values"""
        defaults = {
            "membership_type_name": f"Test Membership {name_suffix} {frappe.generate_hash(length=6)}",
            "amount": 50.0,
            "subscription_period": "Monthly",
            "is_active": 1,
            "contribution_mode": "Calculator",
            "enable_income_calculator": 1,
            "income_percentage_rate": 0.75
        }
        defaults.update(kwargs)
        
        membership_type = frappe.new_doc("Membership Type")
        for key, value in defaults.items():
            setattr(membership_type, key, value)
            
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type