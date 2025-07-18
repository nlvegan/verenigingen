"""
Test enhanced contribution amendment system with dues schedule integration.

This test suite validates:
1. Enhanced auto-approval logic with configurable settings
2. Dues schedule integration for fee changes
3. Migration from subscription system to dues schedule system
4. New field tracking (new_dues_schedule, current_dues_schedule)
5. Integration with member portal fee adjustment

Updated to use the new dues schedule system.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestEnhancedContributionAmendmentSystem(VereningingenTestCase):
    """Test enhanced contribution amendment system with dues schedule integration"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test member
        self.test_member = self.create_test_member(
            first_name="Enhanced",
            last_name="Amendment",
            email="enhanced.amendment@example.com"
        )
        
        # Create test membership
        self.test_membership = self.create_test_membership(
            member=self.test_member.name,
            status="Active"
        )
        
        # Track for cleanup
        self.track_doc("Member", self.test_member.name)
        self.track_doc("Membership", self.test_membership.name)
        
    def test_enhanced_auto_approval_logic(self):
        """Test enhanced auto-approval with configurable settings"""
        
        # Test 1: Auto-approval for fee increase by member
        with patch('frappe.session.user', self.test_member.email):
            amendment = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.00,  # Increase from typical €15
                "reason": "I can afford to contribute more",
                "effective_date": add_days(today(), 30)
            })
            
            amendment.insert()
            self.track_doc("Contribution Amendment Request", amendment.name)
            
            # Should be auto-approved for fee increase by member
            self.assertEqual(amendment.status, "Approved")
            self.assertEqual(amendment.approved_by, self.test_member.email)
            self.assertIn("Auto-approved", amendment.internal_notes or "")
            
    def test_manual_approval_required_for_decreases(self):
        """Test that fee decreases require manual approval"""
        
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 10.00,  # Decrease from typical €15
            "reason": "Financial hardship",
            "effective_date": add_days(today(), 30)
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Should require manual approval for fee decrease
        self.assertEqual(amendment.status, "Pending Approval")
        self.assertIn("fee decrease", amendment.internal_notes or "")
        
    def test_dues_schedule_creation_on_application(self):
        """Test that applying amendments creates dues schedules"""
        
        # Create and approve amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 30.00,
            "reason": "Testing dues schedule creation",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve the amendment
        amendment.approve_amendment("Test approval")
        
        # Apply the amendment
        result = amendment.apply_amendment()
        
        # Check that application was successful
        self.assertEqual(result["status"], "success")
        self.assertEqual(amendment.status, "Applied")
        
        # Check that dues schedule was created
        self.assertIsNotNone(amendment.new_dues_schedule)
        
        # Verify the dues schedule
        dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        self.assertEqual(dues_schedule.amount, 30.00)
        self.assertEqual(dues_schedule.member, self.test_member.name)
        self.assertEqual(dues_schedule.status, "Active")
        self.assertEqual(dues_schedule.contribution_mode, "Custom")
        self.assertTrue(dues_schedule.uses_custom_amount)
        self.assertTrue(dues_schedule.custom_amount_approved)
        
    def test_current_dues_schedule_detection(self):
        """Test that amendments detect current dues schedules"""
        
        # Create an active dues schedule first
        dues_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=20.00,
            status="Active"
        )
        
        # Create amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 35.00,
            "reason": "Testing current dues schedule detection"
        })
        
        # Validate should set current details
        amendment.validate()
        
        # Should detect current dues schedule
        self.assertEqual(amendment.current_dues_schedule, dues_schedule.name)
        self.assertEqual(amendment.current_amount, 20.00)
        
    def test_existing_schedule_deactivation(self):
        """Test that new amendments deactivate existing schedules"""
        
        # Create initial dues schedule
        initial_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=20.00,
            status="Active"
        )
        
        # Create and apply amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 30.00,
            "reason": "Testing schedule deactivation",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve and apply
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()
        
        # Check that initial schedule was deactivated
        initial_schedule.reload()
        self.assertEqual(initial_schedule.status, "Cancelled")
        
        # Check that new schedule is active
        self.assertIsNotNone(amendment.new_dues_schedule)
        new_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", new_schedule.name)
        self.assertEqual(new_schedule.status, "Active")
        
    def test_legacy_override_field_maintenance(self):
        """Test that legacy override fields are maintained for backward compatibility"""
        
        # Create and apply amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 40.00,
            "reason": "Testing legacy field maintenance",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve and apply
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()
        
        # Check that legacy override fields are updated
        self.test_member.reload()
        self.assertEqual(self.test_member.membership_fee_override, 40.00)
        self.assertIn("Amendment:", self.test_member.fee_override_reason)
        self.assertEqual(self.test_member.fee_override_date, today())
        
    def test_zero_amount_handling(self):
        """Test handling of zero amount (free membership)"""
        
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 0.00,
            "reason": "Financial hardship - free membership",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve and apply
        amendment.approve_amendment("Approved for hardship")
        amendment.apply_amendment()
        
        # Check that dues schedule handles zero amount correctly
        dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        self.assertEqual(dues_schedule.amount, 0.00)
        self.assertIn("Free membership", dues_schedule.custom_amount_reason)
        
    def test_dues_schedule_system_integration(self):
        """Test integration with dues schedule system"""
        
        # Create a test dues schedule for the membership
        dues_schedule = frappe.get_doc({
            "doctype": "Subscription",
            "party_type": "Member",
            "party": self.test_member.name,
            "start_date": today(),
            "status": "Active"
        })
        subscription.insert()
        self.track_doc("Subscription", subscription.name)
        
        # Link subscription to membership
        self.test_membership.reload()
        self.test_membership.subscription = subscription.name
        self.test_membership.save()
        
        # Create and apply amendment
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 50.00,
            "reason": "Testing subscription integration",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve and apply
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()
        
        # Check that old subscription was handled
        self.assertTrue(amendment.old_subscription_cancelled)
        
        # Check subscription status
        subscription.reload()
        self.assertEqual(subscription.status, "Cancelled")
        
    def test_small_adjustment_auto_approval(self):
        """Test auto-approval for small adjustments (< 5% change)"""
        
        # Set up current amount of €20
        initial_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            amount=20.00,
            status="Active"
        )
        
        # Create amendment with small change (€0.50 = 2.5% of €20)
        with patch('frappe.session.user', self.test_member.email):
            amendment = frappe.get_doc({
                "doctype": "Contribution Amendment Request",
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 20.50,
                "reason": "Small adjustment",
                "effective_date": add_days(today(), 30)
            })
            
            amendment.insert()
            self.track_doc("Contribution Amendment Request", amendment.name)
            
            # Should be auto-approved for small adjustment
            self.assertEqual(amendment.status, "Approved")
            self.assertIn("Small adjustment", amendment.internal_notes or "")
            
    def test_amendment_metadata_tracking(self):
        """Test that amendment metadata is properly tracked"""
        
        amendment = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "membership": self.test_membership.name,
            "member": self.test_member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 25.00,
            "reason": "Testing metadata tracking",
            "effective_date": today()
        })
        
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        
        # Approve and apply
        amendment.approve_amendment("Test approval")
        amendment.apply_amendment()
        
        # Check that dues schedule has proper metadata
        dues_schedule = frappe.get_doc("Membership Dues Schedule", amendment.new_dues_schedule)
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        
        self.assertIn(amendment.name, dues_schedule.notes)
        self.assertIn("amendment request", dues_schedule.notes.lower())
        
        # Check that comments were added
        comments = frappe.get_all("Comment", 
            filters={"reference_doctype": "Membership Dues Schedule", 
                    "reference_name": dues_schedule.name},
            fields=["content"]
        )
        
        self.assertTrue(any("amendment request" in comment.content.lower() for comment in comments))
        
    def test_new_doctype_fields_exist(self):
        """Test that new DocType fields exist and are properly configured"""
        
        # Test field existence
        doctype = frappe.get_doc("DocType", "Contribution Amendment Request")
        field_names = [field.fieldname for field in doctype.fields]
        
        self.assertIn("new_dues_schedule", field_names)
        self.assertIn("current_dues_schedule", field_names)
        
        # Test field properties
        new_dues_field = None
        current_dues_field = None
        
        for field in doctype.fields:
            if field.fieldname == "new_dues_schedule":
                new_dues_field = field
            elif field.fieldname == "current_dues_schedule":
                current_dues_field = field
                
        self.assertIsNotNone(new_dues_field)
        self.assertIsNotNone(current_dues_field)
        
        # Check field types
        self.assertEqual(new_dues_field.fieldtype, "Link")
        self.assertEqual(new_dues_field.options, "Membership Dues Schedule")
        self.assertTrue(new_dues_field.read_only)
        
        self.assertEqual(current_dues_field.fieldtype, "Link")
        self.assertEqual(current_dues_field.options, "Membership Dues Schedule")
        self.assertTrue(current_dues_field.read_only)


def run_enhanced_amendment_tests():
    """Run the enhanced contribution amendment tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEnhancedContributionAmendmentSystem)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\\n=== ENHANCED CONTRIBUTION AMENDMENT TEST RESULTS ===")
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
    run_enhanced_amendment_tests()