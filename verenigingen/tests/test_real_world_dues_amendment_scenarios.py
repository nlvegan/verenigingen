"""
Real-world test scenarios for the enhanced dues amendment system.

This test suite validates realistic scenarios that would occur in actual usage:
1. Member requests fee increase due to improved financial situation
2. Member requests fee decrease due to financial hardship
3. Student member graduates and requests adult membership fee
4. Long-term member with legacy override migrates to new system
5. Member portal fee adjustment integration
6. Bulk amendment processing scenarios
"""

import unittest
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, today, flt

from verenigingen.tests.utils.base import VereningingenTestCase


class TestRealWorldDuesAmendmentScenarios(VereningingenTestCase):
    """Test real-world scenarios for dues amendment system"""

    def setUp(self):
        """Set up test data for realistic scenarios"""
        super().setUp()
        
        # Create various member types for realistic testing
        self.create_test_members()
        self.create_test_memberships()
        self.create_test_dues_schedules()
        
    def create_test_members(self):
        """Create different types of members for realistic testing"""
        
        # Young professional member
        self.young_professional = self.create_test_member(
            first_name="Sarah",
            last_name="Professional",
            email="sarah.professional@example.com",
            birth_date="1995-03-15",
            student_status=False
        )
        
        # Student member
        self.student_member = self.create_test_member(
            first_name="Tom",
            last_name="Student",
            email="tom.student@example.com",
            birth_date="2000-08-20",
            student_status=True
        )
        
        # Long-term member with legacy data
        self.legacy_member = self.create_test_member(
            first_name="Margaret",
            last_name="Legacy",
            email="margaret.legacy@example.com",
            birth_date="1970-05-10",
            student_status=False
        )
        
        # Member facing financial hardship
        self.hardship_member = self.create_test_member(
            first_name="David",
            last_name="Hardship",
            email="david.hardship@example.com",
            birth_date="1985-12-03",
            student_status=False
        )
        
    def create_test_memberships(self):
        """Create memberships for test members"""
        
        # Get regular membership type
        regular_type = frappe.db.get_value("Membership Type", {"name": ["like", "%Regular%"]}, "name")
        if not regular_type:
            regular_type = frappe.db.get_value("Membership Type", {}, "name")
        
        # Create memberships
        self.young_professional_membership = self.create_test_membership(
            member=self.young_professional.name,
            membership_type=regular_type,
            status="Active"
        )
        
        self.student_membership = self.create_test_membership(
            member=self.student_member.name,
            membership_type=regular_type,
            status="Active"
        )
        
        self.legacy_membership = self.create_test_membership(
            member=self.legacy_member.name,
            membership_type=regular_type,
            status="Active"
        )
        
        self.hardship_membership = self.create_test_membership(
            member=self.hardship_member.name,
            membership_type=regular_type,
            status="Active"
        )
        
    def create_test_dues_schedules(self):
        """Create initial dues schedules for test members"""
        
        # Young professional - standard amount
        self.young_professional_schedule = self.create_test_dues_schedule(
            member=self.young_professional.name,
            membership=self.young_professional_membership.name,
            amount=15.00,
            contribution_mode="Tiers",
            status="Active"
        )
        
        # Student - reduced amount
        self.student_schedule = self.create_test_dues_schedule(
            member=self.student_member.name,
            membership=self.student_membership.name,
            amount=10.00,
            contribution_mode="Tiers",
            status="Active"
        )
        
        # Legacy member - has override fields instead of dues schedule
        self.legacy_member.reload()
        self.legacy_member.dues_rate = 20.00
        self.legacy_member.fee_override_reason = "Long-term member discount"
        self.legacy_member.fee_override_date = add_days(today(), -365)
        self.legacy_member.save()
        
        # Hardship member - current standard amount
        self.hardship_schedule = self.create_test_dues_schedule(
            member=self.hardship_member.name,
            membership=self.hardship_membership.name,
            amount=15.00,
            contribution_mode="Tiers",
            status="Active"
        )
        
    def test_young_professional_fee_increase_scenario(self):
        """
        Real-world scenario: Young professional gets a promotion and wants to increase contribution
        """
        print("\\n=== Testing: Young Professional Fee Increase ===")
        
        # Member requests fee increase from €15 to €25
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.young_professional_membership.name,
            "member": self.young_professional.name,
            "amendment_type": "Fee Change",
            "requested_amount": 25.00,
            "reason": "Got a promotion and want to support the organization more",
            "effective_date": add_days(today(), 30)
        })
        
        # Should be auto-approved since it's an increase
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Verify auto-approval
        self.assertEqual(amendment.status, "Approved")
        self.assertIn("Auto-approved", amendment.internal_notes or "")
        
        # Apply the amendment
        result = amendment.apply_amendment()
        self.assertEqual(result["status"], "success")
        
        # Verify dues schedule was created
        self.assertIsNotNone(amendment.new_dues_schedule)
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        self.assertEqual(new_schedule.dues_rate, 25.00)
        self.assertEqual(new_schedule.contribution_mode, "Custom")
        self.assertTrue(new_schedule.uses_custom_amount)
        self.assertEqual(new_schedule.status, "Active")
        
        # Verify old schedule was deactivated
        self.young_professional_schedule.reload()
        self.assertEqual(self.young_professional_schedule.status, "Cancelled")
        
        # Verify legacy fields are maintained
        self.young_professional.reload()
        self.assertEqual(self.young_professional.dues_rate, 25.00)
        self.assertIn("Amendment:", self.young_professional.fee_override_reason)
        
    def test_student_graduation_scenario(self):
        """
        Real-world scenario: Student member graduates and requests adult membership rate
        """
        print("\\n=== Testing: Student Graduation Scenario ===")
        
        # Student graduates and requests adult rate (€10 -> €15)
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.student_membership.name,
            "member": self.student_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 15.00,
            "reason": "Graduated from university, moving to adult membership rate",
            "effective_date": add_days(today(), 14)  # Effective in 2 weeks
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Should be auto-approved since it's an increase
        self.assertEqual(amendment.status, "Approved")
        
        # Apply the amendment
        amendment.apply_amendment()
        
        # Verify the change
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        self.assertEqual(new_schedule.dues_rate, 15.00)
        self.assertIn("graduated", new_schedule.custom_amount_reason.lower())
        
        # Update member's student status
        self.student_member.reload()
        self.student_member.student_status = False
        self.student_member.save()
        
    def test_financial_hardship_scenario(self):
        """
        Real-world scenario: Member faces financial hardship and requests fee reduction
        """
        print("\\n=== Testing: Financial Hardship Scenario ===")
        
        # Member requests fee reduction from €15 to €8
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.hardship_membership.name,
            "member": self.hardship_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 8.00,
            "reason": "Temporary financial hardship due to job loss",
            "effective_date": add_days(today(), 7)
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Should require manual approval since it's a decrease
        self.assertEqual(amendment.status, "Pending Approval")
        self.assertIn("fee decrease", amendment.internal_notes or "")
        
        # Administrator approves the hardship request
        amendment.approve_amendment("Approved due to documented financial hardship")
        
        # Verify approval
        self.assertEqual(amendment.status, "Approved")
        self.assertIn("financial hardship", amendment.internal_notes or "")
        
        # Apply the amendment
        amendment.apply_amendment()
        
        # Verify the change
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        self.assertEqual(new_schedule.dues_rate, 8.00)
        self.assertIn("hardship", new_schedule.custom_amount_reason.lower())
        
    def test_legacy_member_migration_scenario(self):
        """
        Real-world scenario: Legacy member with override fields gets new dues schedule
        """
        print("\\n=== Testing: Legacy Member Migration Scenario ===")
        
        # Legacy member has override fields but no dues schedule
        self.assertIsNotNone(self.legacy_member.dues_rate)
        
        # Member requests small adjustment to trigger migration
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.legacy_membership.name,
            "member": self.legacy_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 22.00,  # Small increase from €20
            "reason": "Small adjustment to support increased costs",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Should detect legacy override as current amount
        self.assertEqual(amendment.current_amount, 20.00)
        
        # Apply the amendment
        amendment.approve_amendment("Approved")
        amendment.apply_amendment()
        
        # Verify migration to dues schedule
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        self.assertEqual(new_schedule.dues_rate, 22.00)
        self.assertEqual(new_schedule.contribution_mode, "Custom")
        self.assertTrue(new_schedule.uses_custom_amount)
        
    def test_zero_amount_free_membership_scenario(self):
        """
        Real-world scenario: Member in extreme financial hardship requests free membership
        """
        print("\\n=== Testing: Free Membership Scenario ===")
        
        # Member requests free membership
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.hardship_membership.name,
            "member": self.hardship_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 0.00,
            "reason": "Extreme financial hardship - requesting temporary free membership",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Should require manual approval
        self.assertEqual(amendment.status, "Pending Approval")
        
        # Administrator approves with special consideration
        amendment.approve_amendment("Approved for documented extreme hardship - 6 month review")
        amendment.apply_amendment()
        
        # Verify zero amount handling
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        
        self.assertEqual(new_schedule.dues_rate, 0.00)
        self.assertIn("Free membership", new_schedule.custom_amount_reason)
        
    def test_bulk_amendment_processing_scenario(self):
        """
        Real-world scenario: Processing multiple amendments in batch
        """
        print("\\n=== Testing: Bulk Amendment Processing ===")
        
        # Create multiple amendments for different members
        amendments = []
        
        # Create amendments for each member
        for i, (member, membership) in enumerate([
            (self.young_professional, self.young_professional_membership),
            (self.student_member, self.student_membership),
            (self.legacy_member, self.legacy_membership)
        ]):
            amendment = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 20.00 + (i * 5),  # Different amounts
                "reason": f"Bulk processing test amendment {i+1}",
                "effective_date": today()
            })
            
            amendment.insert()
            amendments.append(amendment)
            self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Process all amendments
        processed_count = 0
        for amendment in amendments:
            if amendment.status == "Pending Approval":
                amendment.approve_amendment("Bulk approval")
            
            result = amendment.apply_amendment()
            if result["status"] == "success":
                processed_count += 1
                
                # Track created dues schedules
                if amendment.new_dues_schedule:
                    self.track_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        
        # Verify all were processed
        self.assertEqual(processed_count, len(amendments))
        
    def test_member_portal_integration_scenario(self):
        """
        Real-world scenario: Member uses portal to adjust fee
        """
        print("\\n=== Testing: Member Portal Integration ===")
        
        # Simulate member portal fee adjustment
        from verenigingen.templates.pages.membership_fee_adjustment import submit_fee_adjustment_request
        
        # Mock session user
        original_user = frappe.session.user
        try:
            frappe.session.user = self.young_professional.email
            
            # Submit fee adjustment through portal
            result = submit_fee_adjustment_request(
                new_amount=30.00,
                reason="Using member portal to increase contribution"
            )
            
            # Verify result
            self.assertTrue(result["success"])
            self.assertIn("amendment_id", result)
            
            # Get the created amendment
            amendment = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])
            self.track_doc("Contribution Amendment Request", amendment.name)
            
            # Verify it was created correctly
            self.assertEqual(amendment.requested_amount, 30.00)
            self.assertEqual(amendment.member, self.young_professional.name)
            self.assertTrue(amendment.requested_by_member)
            
            # Should be auto-approved for increase
            if result.get("needs_approval"):
                self.assertEqual(amendment.status, "Approved")
            else:
                self.assertEqual(amendment.status, "Applied")
                
        finally:
            frappe.session.user = original_user
            
    def test_amendment_conflict_resolution_scenario(self):
        """
        Real-world scenario: Multiple amendments for same member with conflict resolution
        """
        print("\\n=== Testing: Amendment Conflict Resolution ===")
        
        # Create first amendment
        amendment1 = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.young_professional_membership.name,
            "member": self.young_professional.name,
            "amendment_type": "Fee Change",
            "requested_amount": 28.00,
            "reason": "First amendment request",
            "effective_date": add_days(today(), 30)
        })
        
        amendment1.insert()
        self.track_doc("Contribution Amendment Request", amendment1.name)
        
        # Create second amendment (should be prevented by validation)
        with self.assertRaises(frappe.ValidationError):
            amendment2 = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "membership": self.young_professional_membership.name,
                "member": self.young_professional.name,
                "amendment_type": "Fee Change",
                "requested_amount": 32.00,
                "reason": "Second amendment request",
                "effective_date": add_days(today(), 30)
            })
            amendment2.insert()
            
    def test_realistic_fee_calculation_scenario(self):
        """
        Real-world scenario: Test realistic fee calculation priorities
        """
        print("\\n=== Testing: Realistic Fee Calculation ===")
        
        # Test priority system: Dues Schedule > Legacy Override > Standard
        
        # Member with both dues schedule and legacy override
        member_with_both = self.create_test_member(
            first_name="Mixed",
            last_name="System",
            email="mixed.system@example.com"
        )
        
        # Set legacy override
        member_with_both.dues_rate = 18.00
        member_with_both.fee_override_reason = "Legacy override"
        member_with_both.save()
        
        # Create dues schedule (should take priority)
        dues_schedule = self.create_test_dues_schedule(
            member=member_with_both.name,
            amount=22.00,
            contribution_mode="Custom",
            status="Active"
        )
        
        # Test fee calculation
        from verenigingen.templates.pages.membership_fee_adjustment import get_effective_fee_for_member
        
        membership = self.create_test_membership(
            member=member_with_both.name,
            status="Active"
        )
        
        effective_fee = get_effective_fee_for_member(member_with_both, membership)
        
        # Should prioritize dues schedule over legacy override
        self.assertEqual(effective_fee["amount"], 22.00)
        self.assertEqual(effective_fee["source"], "dues_schedule")
        
        print(f"✓ Fee calculation priority working: {effective_fee}")
        

def run_real_world_tests():
    """Run the real-world dues amendment tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestRealWorldDuesAmendmentScenarios)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\\n=== REAL-WORLD DUES AMENDMENT TEST RESULTS ===")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    run_real_world_tests()