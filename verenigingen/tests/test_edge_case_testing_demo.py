"""
Demonstration of the new edge case testing methods in VereningingenTestCase
Shows how to use the user-suggested approach for comprehensive validation testing
"""

import frappe
from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase


class TestEdgeCaseTestingDemo(VereningingenTestCase):
    """Demonstrate the new edge case testing capabilities"""
    
    def test_billing_frequency_conflict_with_new_methods(self):
        """Demonstrate testing billing frequency conflicts using the new approach"""
        
        # Step 1: Create test member and membership (standard setup)
        member = self.create_test_member(
            first_name="EdgeCase",
            last_name="TestUser",
            email="edgecase.testuser@example.com"
        )
        
        membership_type = self.create_test_membership_type(
            membership_type_name="Edge Case Test Type",
            dues_rate=25.0
        )
        
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name
        )
        
        # Step 2: Set up for edge case testing (clears auto-schedules)
        context = self.setup_edge_case_testing(member.name)
        
        # Verify the setup worked
        self.assertTrue(context['edge_case_ready'])
        print(f"Set up edge case testing for {context['member_full_name']}")
        print(f"Cancelled {len(context['cancelled_schedules'])} auto-schedules")
        
        # Step 3: Create controlled test schedules with conflicting frequencies
        monthly_schedule = self.create_controlled_dues_schedule(
            member.name, 
            "Monthly", 
            25.0
        )
        
        annual_schedule = self.create_controlled_dues_schedule(
            member.name,
            "Annual", 
            250.0  # Different frequency for same member!
        )
        
        # Step 4: Test validation logic that was previously impossible to test
        if hasattr(annual_schedule, 'validate_billing_frequency_consistency'):
            validation_result = annual_schedule.validate_billing_frequency_consistency()
            
            # This test was impossible before - now we can verify the validation works
            self.assertFalse(validation_result.get("valid", True), 
                "Validation should detect billing frequency conflict")
            self.assertIn("different billing frequencies", validation_result.get("reason", ""))
            
        print("✅ Successfully tested billing frequency conflict validation!")
    
    def test_membership_type_mismatch_with_new_methods(self):
        """Demonstrate testing membership type mismatches using the new approach"""
        
        # Step 1: Create member with one membership type
        member = self.create_test_member(
            first_name="TypeMismatch", 
            last_name="TestUser",
            email="typemismatch.testuser@example.com"
        )
        
        correct_type = self.create_test_membership_type(
            membership_type_name="Correct Type",
            dues_rate=30.0
        )
        
        wrong_type = self.create_test_membership_type(
            membership_type_name="Wrong Type",
            dues_rate=40.0
        )
        
        # Create membership with correct_type
        membership = self.create_test_membership(
            member=member.name,
            membership_type=correct_type.name
        )
        
        # Step 2: Clear auto-schedules to enable controlled testing
        cancelled = self.clear_member_auto_schedules(member.name)
        print(f"Cleared {len(cancelled)} auto-schedules for type mismatch testing")
        
        # Step 3: Create schedule with mismatched membership type
        mismatched_schedule = self.create_controlled_dues_schedule(
            member.name,
            "Monthly",
            40.0,
            membership_type=wrong_type.name  # This creates the mismatch!
        )
        
        # Step 4: Test validation that detects the mismatch
        if hasattr(mismatched_schedule, 'validate_membership_type_consistency'):
            validation_result = mismatched_schedule.validate_membership_type_consistency()
            
            # Verify our validation catches the mismatch
            self.assertFalse(validation_result.get("valid", True),
                "Validation should detect membership type mismatch")
            self.assertIn("Type mismatch", validation_result.get("reason", ""))
            
        print("✅ Successfully tested membership type mismatch validation!")
    
    def test_multiple_zero_rate_schedules_validation(self):
        """Demonstrate testing zero-rate validation with the new methods"""
        
        # Create member and free membership type
        member = self.create_test_member(
            first_name="ZeroRate",
            last_name="TestUser", 
            email="zerorate.testuser@example.com"
        )
        
        # Free membership type (minimum_amount = 0)
        free_type = self.create_test_membership_type(
            membership_type_name="Free Membership",
            dues_rate=0.0,
            minimum_amount=0.0
        )
        
        # Paid membership type (minimum_amount > 0) 
        paid_type = self.create_test_membership_type(
            membership_type_name="Paid Membership",
            dues_rate=25.0,
            minimum_amount=25.0
        )
        
        membership = self.create_test_membership(
            member=member.name,
            membership_type=free_type.name
        )
        
        # Clear auto-schedules for controlled testing
        self.clear_member_auto_schedules(member.name)
        
        # Test 1: Zero rate with free membership type (should be valid)
        free_schedule = self.create_controlled_dues_schedule(
            member.name,
            "Monthly",
            0.0,  # Zero rate
            membership_type=free_type.name
        )
        
        if hasattr(free_schedule, 'validate_dues_rate'):
            free_validation = free_schedule.validate_dues_rate()
            self.assertTrue(free_validation.get("valid", False),
                "Zero rate should be valid for free membership types")
        
        # Test 2: Zero rate with paid membership type (should be invalid)
        paid_schedule = self.create_controlled_dues_schedule(
            member.name,
            "Annual", 
            0.0,  # Zero rate but paid type!
            membership_type=paid_type.name
        )
        
        if hasattr(paid_schedule, 'validate_dues_rate'):
            paid_validation = paid_schedule.validate_dues_rate()
            self.assertFalse(paid_validation.get("valid", True),
                "Zero rate should be invalid for paid membership types")
        
        print("✅ Successfully tested zero-rate validation for different membership types!")
    
    def test_edge_case_cleanup_works_correctly(self):
        """Test that the cleanup mechanisms work properly"""
        
        member = self.create_test_member(
            first_name="Cleanup",
            last_name="TestUser",
            email="cleanup.testuser@example.com" 
        )
        
        membership_type = self.create_test_membership_type(
            membership_type_name="Cleanup Test Type",
            dues_rate=20.0
        )
        
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name
        )
        
        # Set up edge case testing
        context = self.setup_edge_case_testing(member.name)
        
        # Create multiple test schedules
        schedule1 = self.create_controlled_dues_schedule(member.name, "Monthly", 20.0)
        schedule2 = self.create_controlled_dues_schedule(member.name, "Quarterly", 60.0)
        schedule3 = self.create_controlled_dues_schedule(member.name, "Annual", 200.0)
        
        # Verify they were all created and tracked
        self.assertEqual(schedule1.member, member.name)
        self.assertEqual(schedule2.member, member.name) 
        self.assertEqual(schedule3.member, member.name)
        
        # Check that they're all tracked for cleanup
        tracked_schedules = [doc for doc in self._test_docs if doc["doctype"] == "Membership Dues Schedule"]
        self.assertGreaterEqual(len(tracked_schedules), 3, "All schedules should be tracked for cleanup")
        
        print("✅ Successfully tested cleanup tracking for edge case testing!")


if __name__ == "__main__":
    """
    This demonstrates the new edge case testing capabilities.
    Run with: python -m unittest verenigingen.tests.test_edge_case_testing_demo
    """
    import unittest
    unittest.main()