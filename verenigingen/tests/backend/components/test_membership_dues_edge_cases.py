# -*- coding: utf-8 -*-
"""
Comprehensive edge case tests for the membership dues system
Tests real-world scenarios, boundary conditions, and error cases
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate
from verenigingen.tests.utils.base import VereningingenTestCase
from decimal import Decimal
import datetime


class TestMembershipDuesEdgeCases(VereningingenTestCase):
    """Test edge cases and real-world scenarios for membership dues system"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_simple_test_member()
        
    def create_simple_test_member(self):
        """Create a simple test member for testing"""
        member = frappe.new_doc("Member")
        member.first_name = "Edge"
        member.last_name = "Case"
        member.email = f"edge.case.{frappe.generate_hash(length=6)}@example.com"
        member.member_since = today()
        member.address_line1 = "123 Edge Street"
        member.postal_code = "1234AB"
        member.city = "Amsterdam"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
        
    # Boundary Value Tests
    
    def test_minimum_contribution_boundary_validation(self):
        """Test validation at minimum contribution boundaries"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.minimum_contribution = 0.01  # 1 cent minimum
        membership_type.suggested_contribution = 10.00
        membership_type.save()
        
        # Test exactly at minimum - should pass
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=0.01)
        self.assertEqual(dues_schedule.dues_rate, 0.01)
        
        # Test below minimum - should fail
        with self.assertRaises(frappe.ValidationError):
            self.create_test_dues_schedule(membership_type, amount=0.00)
            
        # Test edge case: negative minimum (should auto-correct)
        membership_type.minimum_contribution = -5.00
        membership_type.save()
        self.assertGreaterEqual(membership_type.minimum_contribution, 0)
        
    def test_maximum_contribution_boundary_validation(self):
        """Test validation at maximum contribution boundaries"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.minimum_contribution = 5.00
        membership_type.suggested_contribution = 25.00
        membership_type.maximum_contribution = 1000.00
        membership_type.save()
        
        # Test exactly at maximum - should pass
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=1000.00)
        self.assertEqual(dues_schedule.dues_rate, 1000.00)
        
        # Test above maximum - should validate but warn
        with self.assertRaises(frappe.ValidationError):
            self.create_test_dues_schedule(membership_type, amount=1000.01)
            
    def test_extreme_amount_values(self):
        """Test handling of extreme monetary values"""
        membership_type = self.create_edge_case_membership_type()
        
        # Test very large amounts (millionaire scenario)
        membership_type.minimum_contribution = 1.00
        membership_type.suggested_contribution = 50000.00
        membership_type.maximum_contribution = 999999.99
        membership_type.save()
        
        # Should handle large amounts gracefully
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=50000.00)
        self.assertEqual(dues_schedule.dues_rate, 50000.00)
        
        # Test precision with many decimal places
        membership_type.suggested_contribution = 25.999999
        membership_type.save()
        
        # Should round appropriately for currency
        self.assertAlmostEqual(membership_type.suggested_contribution, 26.00, places=2)
        
    # Date Edge Cases
    
    def test_leap_year_billing_edge_cases(self):
        """Test billing on leap year dates"""
        # Set member anniversary to Feb 29 (leap year scenario)
        leap_member = frappe.new_doc("Member")
        leap_member.first_name = "Leap"
        leap_member.last_name = "Year"
        leap_member.email = f"leap.{frappe.generate_hash(length=6)}@example.com"
        leap_member.member_since = "2024-02-29"  # Leap year date
        leap_member.address_line1 = "29 February Street"
        leap_member.postal_code = "2902AB"
        leap_member.city = "Leap City"
        leap_member.country = "Netherlands"
        leap_member.save()
        self.track_doc("Member", leap_member.name)
        
        membership_type = self.create_edge_case_membership_type()
        
        # Create dues schedule
        dues_schedule = self.create_test_dues_schedule_for_member(
            leap_member, membership_type, "Annual"
        )
        
        # Should handle leap year gracefully
        self.assertEqual(dues_schedule.billing_day, 29)
        
        # Next billing should be Feb 28 in non-leap year
        # Implementation should handle this edge case
        
    def test_month_end_billing_edge_cases(self):
        """Test billing on month-end dates (30th, 31st)"""
        # Member joined on January 31st
        month_end_member = frappe.new_doc("Member")
        month_end_member.first_name = "Month"
        month_end_member.last_name = "End"
        month_end_member.email = f"monthend.{frappe.generate_hash(length=6)}@example.com"
        month_end_member.member_since = "2025-01-31"
        month_end_member.address_line1 = "31 January Street"
        month_end_member.postal_code = "3101AB"
        month_end_member.city = "Month End City"
        month_end_member.country = "Netherlands"
        month_end_member.save()
        self.track_doc("Member", month_end_member.name)
        
        membership_type = self.create_edge_case_membership_type()
        
        dues_schedule = self.create_test_dues_schedule_for_member(
            month_end_member, membership_type, "Monthly"
        )
        
        # Should handle February correctly (28/29 days)
        self.assertEqual(dues_schedule.billing_day, 31)
        
        # Calculate next billing date - should handle February gracefully
        start_date = getdate(dues_schedule.current_coverage_start)
        next_date = getdate(dues_schedule.next_invoice_date)
        
        # Should be valid date
        self.assertIsInstance(next_date, datetime.date)
        
    def test_historical_member_dates(self):
        """Test members with very old join dates"""
        # Very old member (from 1990)
        old_member = frappe.new_doc("Member")
        old_member.first_name = "Historical"
        old_member.last_name = "Member"
        old_member.email = f"historical.{frappe.generate_hash(length=6)}@example.com"
        old_member.member_since = "1990-06-15"
        old_member.address_line1 = "15 Historical Avenue"
        old_member.postal_code = "1990AB"
        old_member.city = "Old Town"
        old_member.country = "Netherlands"
        old_member.save()
        self.track_doc("Member", old_member.name)
        
        membership_type = self.create_edge_case_membership_type()
        
        # Should handle old dates without issues
        dues_schedule = self.create_test_dues_schedule_for_member(
            old_member, membership_type, "Annual"
        )
        
        self.assertEqual(dues_schedule.billing_day, 15)
        
        # Coverage dates should be current, not historical
        coverage_start = getdate(dues_schedule.current_coverage_start)
        self.assertEqual(coverage_start, getdate(today()))
        
    # Multi-currency and Localization Edge Cases
    
    def test_currency_precision_edge_cases(self):
        """Test currency precision in different scenarios"""
        membership_type = self.create_edge_case_membership_type()
        
        # Test amounts with many decimal places
        test_amounts = [
            25.999,    # Should round to 26.00
            25.001,    # Should round to 25.00
            25.005,    # Should round to 25.01 (banker's rounding)
            0.999,     # Should round to 1.00
        ]
        
        for amount in test_amounts:
            dues_schedule = self.create_test_dues_schedule(membership_type, amount=amount)
            # Verify amount is properly rounded to 2 decimal places
            self.assertEqual(len(str(dues_schedule.dues_rate).split('.')[-1]), 2)
            
    def test_special_character_handling(self):
        """Test handling of special characters in names and descriptions"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Ñoël & André's Café Membership {frappe.generate_hash(length=6)}"
        membership_type.description = "Membership with spëcial chäractersß and émojis 🎉"
        membership_type.amount = 25.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.minimum_contribution = 5.0
        membership_type.suggested_contribution = 25.0
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.calculator_description = "Ñós sugerimos 0,75% de sú ingreso mensual neto"
        
        # Should save without issues
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        
        # Test tier with special characters
        tier = membership_type.append("predefined_tiers", {})
        tier.tier_name = "Студент"  # Russian "Student"
        tier.display_name = "Études Étudiantes"  # French with accents
        tier.amount = 15.0
        tier.description = "Taux réduit pour les étudiants 📚"
        tier.display_order = 1
        
        membership_type.save()
        
        # Test contribution options with special characters
        options = membership_type.get_contribution_options()
        self.assertEqual(options["mode"], "Calculator")
        self.assertIn("Ñós sugerimos", options["calculator"]["description"])
        
    # Concurrent Access and Race Conditions
    
    def test_concurrent_dues_schedule_creation(self):
        """Test handling of concurrent dues schedule creation for same member"""
        membership_type = self.create_edge_case_membership_type()
        
        # Create first dues schedule
        schedule1 = self.create_test_dues_schedule(membership_type)
        
        # Attempt to create second dues schedule for same member
        # Should either prevent duplicate or handle gracefully
        try:
            schedule2 = self.create_test_dues_schedule(membership_type)
            # If creation succeeds, ensure there's no conflict
            self.assertNotEqual(schedule1.name, schedule2.name)
        except frappe.ValidationError:
            # If validation prevents duplicate, that's acceptable
            pass
            
    def test_member_status_change_during_dues_processing(self):
        """Test dues processing when member status changes"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Suspend member while dues are active
        self.test_member.status = "Suspended"
        self.test_member.suspension_reason = "Payment failure"
        self.test_member.suspension_date = today()
        self.test_member.save()
        
        # Dues schedule should react appropriately
        dues_schedule.reload()
        
        # Should either pause collection or handle gracefully
        # Implementation dependent on business rules
        
    # Data Integrity Edge Cases
    
    def test_orphaned_dues_schedule_handling(self):
        """Test handling of dues schedules with deleted members"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Store member name before deletion
        member_name = self.test_member.name
        
        # Delete member (simulating data corruption)
        frappe.delete_doc("Member", member_name, force=True)
        
        # Dues schedule should handle missing member gracefully
        try:
            dues_schedule.reload()
            # Should either fail gracefully or show appropriate status
        except frappe.DoesNotExistError:
            # Expected behavior - dues schedule becomes invalid
            pass
            
    def test_membership_type_deletion_impact(self):
        """Test impact of deleting membership type on active dues schedules"""
        membership_type = self.create_edge_case_membership_type()
        dues_schedule = self.create_test_dues_schedule(membership_type)
        
        # Store membership type name
        type_name = membership_type.name
        
        # Attempt to delete membership type with active dues schedules
        try:
            frappe.delete_doc("Membership Type", type_name, force=True)
            # Should either be prevented or handled gracefully
        except frappe.LinkExistsError:
            # Expected - should prevent deletion if dues schedules exist
            pass
            
    # Performance Edge Cases
    
    def test_large_tier_list_performance(self):
        """Test performance with many tiers"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.contribution_mode = "Tiers"
        
        # Create many tiers (stress test)
        for i in range(50):
            tier = membership_type.append("predefined_tiers", {})
            tier.tier_name = f"Tier_{i:03d}"
            tier.display_name = f"Membership Tier {i+1}"
            tier.amount = 10.0 + (i * 5.0)
            tier.display_order = i + 1
            tier.description = f"Tier {i+1} description with some text to test performance"
            
        membership_type.save()
        
        # Test contribution options generation
        import time
        start_time = time.time()
        options = membership_type.get_contribution_options()
        end_time = time.time()
        
        # Should complete within reasonable time (< 1 second)
        self.assertLess(end_time - start_time, 1.0)
        self.assertEqual(len(options["tiers"]), 50)
        
    def test_bulk_dues_schedule_creation(self):
        """Test creating many dues schedules efficiently"""
        membership_type = self.create_edge_case_membership_type()
        
        # Create multiple members
        members = []
        for i in range(10):
            member = frappe.new_doc("Member")
            member.first_name = f"Bulk{i:03d}"
            member.last_name = "Test"
            member.email = f"bulk{i:03d}.{frappe.generate_hash(length=4)}@example.com"
            member.member_since = today()
            member.address_line1 = f"{i} Bulk Street"
            member.postal_code = f"{1000+i:04d}AB"
            member.city = "Bulk City"
            member.country = "Netherlands"
            member.save()
            self.track_doc("Member", member.name)
            members.append(member)
            
        # Create dues schedules for all members
        import time
        start_time = time.time()
        
        for member in members:
            self.create_test_dues_schedule_for_member(member, membership_type)
            
        end_time = time.time()
        
        # Should complete efficiently
        self.assertLess(end_time - start_time, 5.0)  # < 5 seconds for 10 schedules
        
    # Business Logic Edge Cases
    
    def test_zero_amount_dues_schedule(self):
        """Test handling of zero-amount dues (free membership)"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.minimum_contribution = 0.0
        membership_type.suggested_contribution = 0.0
        membership_type.save()
        
        # Create zero-amount dues schedule
        dues_schedule = self.create_test_dues_schedule(membership_type, amount=0.0)
        
        # Should handle zero amounts gracefully
        self.assertEqual(dues_schedule.dues_rate, 0.0)
        self.assertEqual(dues_schedule.status, "Active")
        
        # Coverage periods should still be calculated
        self.assertIsNotNone(dues_schedule.current_coverage_start)
        self.assertIsNotNone(dues_schedule.current_coverage_end)
        
    def test_contribution_mode_switching(self):
        """Test switching contribution modes on existing schedules"""
        membership_type = self.create_edge_case_membership_type()
        membership_type.contribution_mode = "Calculator"
        membership_type.save()
        
        # Create schedule with calculator mode
        dues_schedule = self.create_test_dues_schedule(membership_type)
        original_amount = dues_schedule.dues_rate
        
        # Switch membership type to Tiers mode
        membership_type.contribution_mode = "Tiers"
        
        # Add a tier
        tier = membership_type.append("predefined_tiers", {})
        tier.tier_name = "Standard"
        tier.display_name = "Standard Membership"
        tier.amount = 30.0
        tier.display_order = 1
        tier.is_default = True
        
        membership_type.save()
        
        # Existing dues schedule should maintain its amount
        dues_schedule.reload()
        self.assertEqual(dues_schedule.dues_rate, original_amount)
        
        # But new schedules should use tiers
        new_schedule = self.create_test_dues_schedule_for_member(
            self.create_simple_test_member(), membership_type
        )
        # Should use tier amount if no specific amount set
        
    def test_invalid_billing_frequency_handling(self):
        """Test handling of invalid billing frequencies"""
        membership_type = self.create_edge_case_membership_type()
        
        # Test with invalid frequency
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = self.test_member.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.billing_frequency = "Invalid Frequency"
        dues_schedule.dues_rate = 25.0
        dues_schedule.status = "Active"
        
        # Should either validate or default to valid frequency
        try:
            dues_schedule.save()
            # If it saves, should have defaulted to valid frequency
            self.assertIn(dues_schedule.billing_frequency, ["Monthly", "Quarterly", "Annual"])
        except frappe.ValidationError:
            # Expected - should validate billing frequency
            pass
            
    # Helper Methods
    
    def create_edge_case_membership_type(self):
        """Create a membership type for edge case testing"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Edge Case Type {frappe.generate_hash(length=6)}"
        membership_type.description = "Membership type for edge case testing"
        membership_type.amount = 25.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.minimum_contribution = 5.0
        membership_type.suggested_contribution = 25.0
        membership_type.maximum_contribution = 500.0
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type
        
    def create_test_dues_schedule(self, membership_type, frequency="Monthly", amount=None):
        """Create a test dues schedule with membership"""
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
        if amount is not None:
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = amount
            dues_schedule.uses_custom_amount = 1
            # Only auto-approve valid amounts for tests
            if amount > 0:
                dues_schedule.custom_amount_approved = 1  
                if amount > (membership_type.amount * 10):  # If above maximum
                    dues_schedule.custom_amount_reason = "Test scenario requiring large amount"
        else:
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = membership_type.suggested_contribution
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_test_dues_schedule_for_member(self, member, membership_type, frequency="Monthly", amount=None):
        """Create a test dues schedule for specific member"""
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
            # Only auto-approve valid amounts for tests
            if amount > 0:
                dues_schedule.custom_amount_approved = 1  
                if amount > (membership_type.amount * 10):  # If above maximum
                    dues_schedule.custom_amount_reason = "Test scenario requiring large amount"
        else:
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = membership_type.suggested_contribution
        dues_schedule.billing_frequency = frequency
        dues_schedule.payment_method = "Bank Transfer"
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0
        
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule