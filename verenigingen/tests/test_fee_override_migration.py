# -*- coding: utf-8 -*-
"""
Test suite for fee override migration and new dues schedule architecture
Tests the migration from legacy override fields to child DocType approach
"""

import frappe
from frappe.utils import today, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestFeeOverrideMigration(VereningingenTestCase):
    """Test the migration from fee overrides to dues schedules"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type()
        
    def test_fee_priority_system(self):
        """Test that fee calculation follows the correct priority order"""
        from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
        
        # Create membership
        membership = self.create_test_membership()
        
        # Test 1: No overrides - should use membership type amount
        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "membership_type")
        
        # Test 2: Add dues schedule - should have highest priority
        dues_schedule = self.create_test_dues_schedule(25.0)
        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "dues_schedule")
        self.assertEqual(fee_info["amount"], 25.0)
        
        # Test 3: Legacy override should be lower priority
        self.test_member.dues_rate = 30.0
        self.test_member.save()
        
        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "dues_schedule")  # Should still use dues schedule
        self.assertEqual(fee_info["amount"], 25.0)
        
        # Test 4: Remove dues schedule - should fall back to legacy override
        dues_schedule.status = "Inactive"
        dues_schedule.save()
        
        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "member_override")
        self.assertEqual(fee_info["amount"], 30.0)
        
    def test_create_new_dues_schedule(self):
        """Test creating new dues schedule from portal"""
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        # Create membership
        membership = self.create_test_membership()
        
        # Test creating new dues schedule
        schedule_name = create_new_dues_schedule(self.test_member, 35.0, "Testing new schedule")
        
        # Verify schedule was created
        self.assertIsNotNone(schedule_name)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        
        self.assertEqual(schedule.member, self.test_member.name)
        self.assertEqual(schedule.dues_rate, 35.0)
        self.assertEqual(schedule.contribution_mode, "Custom")
        self.assertEqual(schedule.status, "Active")
        self.assertTrue(schedule.uses_custom_amount)
        self.assertTrue(schedule.custom_amount_approved)
        self.assertIn("Testing new schedule", schedule.custom_amount_reason)
        
        # Verify legacy fields are also updated for backward compatibility
        self.test_member.reload()
        self.assertEqual(self.test_member.dues_rate, 35.0)
        
    def test_supersede_existing_schedule(self):
        """Test that creating new schedule supersedes existing one"""
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        # Create membership
        membership = self.create_test_membership()
        
        # Create first schedule
        first_schedule = self.create_test_dues_schedule(20.0)
        self.assertEqual(first_schedule.status, "Active")
        
        # Create second schedule - should supersede first
        second_schedule_name = create_new_dues_schedule(self.test_member, 25.0, "Updated amount")
        
        # Verify first schedule is superseded
        first_schedule.reload()
        self.assertEqual(first_schedule.status, "Superseded")
        
        # Verify second schedule is active
        second_schedule = frappe.get_doc("Membership Dues Schedule", second_schedule_name)
        self.assertEqual(second_schedule.status, "Active")
        self.assertEqual(second_schedule.dues_rate, 25.0)
        
    def test_fee_history_tracking(self):
        """Test that fee history is properly tracked"""
        from verenigingen.templates.pages.membership_fee_adjustment import get_member_fee_history
        
        # Create membership
        membership = self.create_test_membership()
        
        # Create multiple dues schedules
        schedule1 = self.create_test_dues_schedule(20.0)
        schedule1.custom_amount_reason = "First adjustment"
        schedule1.save()
        
        schedule2 = self.create_test_dues_schedule(25.0)
        schedule2.custom_amount_reason = "Second adjustment"
        schedule2.save()
        
        # Get fee history
        history = get_member_fee_history(self.test_member.name)
        
        # Verify history contains both schedules
        self.assertGreaterEqual(len(history), 2)
        
        # Check that amounts are tracked
        amounts = [h["amount"] for h in history]
        self.assertIn(20.0, amounts)
        self.assertIn(25.0, amounts)
        
        # Check that reasons are tracked
        reasons = [h["reason"] for h in history]
        self.assertTrue(any("First adjustment" in r for r in reasons))
        self.assertTrue(any("Second adjustment" in r for r in reasons))
        
    def test_migration_data_integrity(self):
        """Test that migration preserves data integrity"""
        # Create member with override
        self.test_member.dues_rate = 45.0
        self.test_member.fee_override_reason = "Special case"
        self.test_member.fee_override_date = today()
        self.test_member.save()
        
        # Simulate migration
        from scripts.migration.migrate_fee_overrides_to_dues_schedules import migrate_member_override
        
        membership = self.create_test_membership()
        
        member_data = {
            "name": self.test_member.name,
            "full_name": self.test_member.full_name,
            "dues_rate": 45.0,
            "fee_override_reason": "Special case",
            "fee_override_date": today()
        }
        
        migrate_member_override(member_data)
        
        # Verify dues schedule was created
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.test_member.name, "custom_amount_reason": ["like", "%Special case%"]},
            ["name", "dues_rate", "custom_amount_reason"],
            as_dict=True
        )
        
        self.assertIsNotNone(dues_schedule)
        self.assertEqual(dues_schedule.dues_rate, 45.0)
        self.assertIn("Special case", dues_schedule.custom_amount_reason)
        
    def test_enhanced_fee_calculation_api(self):
        """Test the enhanced fee calculation API"""
        from verenigingen.templates.pages.membership_fee_adjustment import get_fee_calculation_info
        
        # Create membership
        membership = self.create_test_membership()
        
        # Create dues schedule
        dues_schedule = self.create_test_dues_schedule(30.0)
        
        # Mock user session
        original_user = frappe.session.user
        frappe.session.user = self.test_member.email
        
        try:
            # Get fee calculation info
            fee_info = get_fee_calculation_info()
            
            # Verify enhanced information is returned
            self.assertIn("current_fee", fee_info)
            self.assertIn("current_source", fee_info)
            self.assertIn("current_reason", fee_info)
            self.assertIn("fee_history", fee_info)
            self.assertIn("active_dues_schedule", fee_info)
            
            # Verify current fee comes from dues schedule
            self.assertEqual(fee_info["current_fee"], 30.0)
            self.assertEqual(fee_info["current_source"], "dues_schedule")
            self.assertEqual(fee_info["active_dues_schedule"], dues_schedule.name)
            
        finally:
            frappe.session.user = original_user
            
    def test_backward_compatibility(self):
        """Test that system maintains backward compatibility"""
        from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
        
        # Create membership
        membership = self.create_test_membership()
        
        # Set only legacy override (no dues schedule)
        self.test_member.reload()  # Refresh to avoid timestamp mismatch
        self.test_member.dues_rate = 40.0
        self.test_member.save()
        
        # Should fall back to legacy override
        fee_info = get_effective_fee_for_member(self.test_member, membership)
        self.assertEqual(fee_info["source"], "member_override")
        self.assertEqual(fee_info["amount"], 40.0)
        self.assertIn("Legacy fee override", fee_info["reason"])
        
    def test_zero_amount_handling(self):
        """Test handling of zero amounts in new system"""
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        # Create membership
        membership = self.create_test_membership()
        
        # Test that zero amounts are handled appropriately
        with self.assertRaises(frappe.ValidationError):
            create_new_dues_schedule(self.test_member, 0.0, "Free membership")
            
    def test_currency_precision(self):
        """Test currency precision in new system"""
        from verenigingen.templates.pages.membership_fee_adjustment import create_new_dues_schedule
        
        # Create membership
        membership = self.create_test_membership()
        
        # Test with precise amount
        schedule_name = create_new_dues_schedule(self.test_member, 25.995, "Precise amount")
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        
        # Should be rounded to 2 decimal places
        self.assertEqual(schedule.dues_rate, 26.00)
        
    # Helper methods
    
    def create_test_membership(self):
        """Create a test membership for the test member"""
        # Check if membership already exists
        existing_membership = frappe.db.get_value(
            "Membership", 
            {"member": self.test_member.name, "status": "Active"}, 
            "name"
        )
        
        if existing_membership:
            return frappe.get_doc("Membership", existing_membership)
        
        membership = frappe.new_doc("Membership")
        membership.member = self.test_member.name
        membership.membership_type = self.test_membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        return membership
    
    def create_test_dues_schedule(self, amount):
        """Create a test dues schedule"""
        membership = self.create_test_membership()
        
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = self.test_membership_type.name
        dues_schedule.contribution_mode = "Custom"
        dues_schedule.dues_rate = amount
        dues_schedule.uses_custom_amount = 1
        dues_schedule.custom_amount_approved = 1
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 1
        dues_schedule.test_mode = 0
        dues_schedule.effective_date = today()
        dues_schedule.current_coverage_start = today()
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
    
    def create_test_membership_type(self):
        """Create a test membership type"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Test Migration Type {frappe.generate_hash(length=6)}"
        membership_type.amount = 20.0
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type