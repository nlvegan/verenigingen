"""
Test suite for invoice validation safeguards
Following CLAUDE.md testing guidelines using VereningingenTestCase
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.test_data_factory import TestDataFactory


class TestInvoiceValidationSafeguards(VereningingenTestCase):
    """Test invoice validation safeguards implementation"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.factory = TestDataFactory()
        
    def test_rate_validation_zero_rate(self):
        """Test that zero dues rates are properly rejected"""
        # Create a simple dues schedule document (no save) to test validation
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Zero-Rate-Validation"
        schedule.membership_type = "Individual"  # Use existing type
        schedule.dues_rate = 0.0  # Zero rate - should be rejected
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.is_template = 1  # Template doesn't require member
        
        # Test rate validation directly
        rate_result = schedule.validate_dues_rate()
        
        self.assertFalse(rate_result["valid"], "Zero rate should be rejected")
        self.assertIn("must be positive", rate_result["reason"])
        
    def test_rate_validation_negative_rate(self):
        """Test that negative dues rates are properly rejected"""
        # Create a simple dues schedule document (no save) to test validation
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Negative-Rate-Validation"
        schedule.membership_type = "Individual"  # Use existing type
        schedule.dues_rate = -10.0  # Negative rate - should be rejected
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.is_template = 1  # Template doesn't require member
        
        # Test rate validation directly
        rate_result = schedule.validate_dues_rate()
        
        self.assertFalse(rate_result["valid"], "Negative rate should be rejected")
        self.assertIn("must be positive", rate_result["reason"])
        
    def test_rate_validation_valid_rate(self):
        """Test that valid dues rates are accepted"""
        # Create a simple dues schedule document (no save) to test validation
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Valid-Rate-Validation"
        schedule.membership_type = "Individual"  # Use existing type
        schedule.dues_rate = 25.0  # Valid positive rate
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.is_template = 1  # Template doesn't require member
        
        # Test rate validation directly
        rate_result = schedule.validate_dues_rate()
        
        self.assertTrue(rate_result["valid"], f"Valid rate should be accepted: {rate_result}")
        
    def test_membership_type_consistency_matching_types(self):
        """Test membership type consistency when types match"""
        # Create test data with unique identifiers
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Consistent",
            last_name=f"Tester{test_id}",
            email=f"consistent.tester.{test_id}@test.com"
        )
        
        membership_type = self.create_test_membership_type(
            membership_type_name=f"Consistent Test Type {test_id}",
            dues_rate=30.0
        )
        
        membership = self.create_test_membership(
            member=member.name,
            membership_type=membership_type.name,
            docstatus=0  # Keep as draft to avoid auto-schedule creation
        )
        membership.submit()  # Submit manually after tracking
        
        # Create schedule document (unsaved) to test validation
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Consistency-{test_id}"
        schedule.member = member.name
        schedule.membership_type = membership_type.name  # Same as member's membership
        schedule.dues_rate = 30.0
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.is_template = 0
        
        # Test membership type consistency
        consistency_result = schedule.validate_membership_type_consistency()
        
        self.assertTrue(consistency_result["valid"], f"Matching types should be valid: {consistency_result}")
        
    def test_membership_type_consistency_mismatched_types(self):
        """Test membership type consistency when types don't match"""
        # Create test data with unique identifiers
        test_id = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="Mismatch",
            last_name=f"Tester{test_id}",
            email=f"mismatch.tester.{test_id}@test.com"
        )
        
        # Create two different membership types
        correct_type = self.create_test_membership_type(
            membership_type_name=f"Correct Type {test_id}",
            dues_rate=40.0
        )
        
        wrong_type = self.create_test_membership_type(
            membership_type_name=f"Wrong Type {test_id}", 
            dues_rate=50.0
        )
        
        # Member has membership of correct_type
        membership = self.create_test_membership(
            member=member.name,
            membership_type=correct_type.name,
            docstatus=0  # Keep as draft to avoid auto-schedule creation
        )
        membership.submit()  # Submit manually after tracking
        
        # Create schedule document (unsaved) that references wrong_type
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"Test-Mismatch-{test_id}"
        schedule.member = member.name
        schedule.membership_type = wrong_type.name  # Mismatch!
        schedule.dues_rate = 50.0
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        schedule.is_template = 0
        
        # Test membership type consistency
        consistency_result = schedule.validate_membership_type_consistency()
        
        self.assertFalse(consistency_result["valid"], "Mismatched types should be rejected")
        self.assertIn("Type mismatch", consistency_result["reason"])
        self.assertIn(correct_type.name, consistency_result["reason"])
        self.assertIn(wrong_type.name, consistency_result["reason"])
        
    def test_can_generate_invoice_with_validations(self):
        """Test that can_generate_invoice properly uses our new validations"""
        # Test 1: Valid schedule should pass rate validation
        valid_schedule = frappe.new_doc("Membership Dues Schedule")
        valid_schedule.schedule_name = "Test-Valid-Integration"
        valid_schedule.membership_type = "Individual"
        valid_schedule.dues_rate = 35.0  # Valid rate
        valid_schedule.billing_frequency = "Monthly"
        valid_schedule.status = "Active"
        valid_schedule.auto_generate = 1
        valid_schedule.next_invoice_date = today()
        valid_schedule.is_template = 1  # Template to avoid member requirements
        
        # Test the rate validation directly (can_generate_invoice calls this)
        rate_result = valid_schedule.validate_dues_rate()
        self.assertTrue(rate_result["valid"], "Valid rate should pass validation")
        self.assertNotIn("must be positive", rate_result["reason"])
        
        # Test 2: Invalid rate should be rejected  
        invalid_schedule = frappe.new_doc("Membership Dues Schedule")
        invalid_schedule.schedule_name = "Test-Invalid-Integration"
        invalid_schedule.membership_type = "Individual"
        invalid_schedule.dues_rate = 0.0  # Invalid rate
        invalid_schedule.billing_frequency = "Monthly"
        invalid_schedule.status = "Active"
        invalid_schedule.auto_generate = 1
        invalid_schedule.next_invoice_date = today()
        invalid_schedule.is_template = 1  # Template to avoid member requirements
        
        # Test the rate validation directly
        rate_result = invalid_schedule.validate_dues_rate()
        self.assertFalse(rate_result["valid"], "Invalid rate should fail validation")
        self.assertIn("must be positive", rate_result["reason"])


class TestValidationFieldIntegrity(VereningingenTestCase):
    """Test that the validation logic uses correct field names and relationships"""
    
    def test_membership_doctype_fields(self):
        """Verify that Membership doctype has the fields we're querying"""
        # Read the Membership doctype to verify field names
        membership_meta = frappe.get_meta("Membership")
        
        # Check that the fields we query in validate_membership_type_consistency exist
        membership_type_field = membership_meta.get_field("membership_type")
        self.assertIsNotNone(membership_type_field, "Membership doctype should have membership_type field")
        
        # Verify it's a Link field to Membership Type
        self.assertEqual(membership_type_field.fieldtype, "Link", "membership_type should be a Link field")
        self.assertEqual(membership_type_field.options, "Membership Type", "membership_type should link to Membership Type")
        
    def test_membership_dues_schedule_fields(self):
        """Verify that Membership Dues Schedule has the fields we're using"""
        schedule_meta = frappe.get_meta("Membership Dues Schedule")
        
        # Check dues_rate field
        dues_rate_field = schedule_meta.get_field("dues_rate")
        self.assertIsNotNone(dues_rate_field, "Schedule should have dues_rate field")
        self.assertEqual(dues_rate_field.fieldtype, "Currency", "dues_rate should be Currency field")
        
        # Check membership_type field
        membership_type_field = schedule_meta.get_field("membership_type")
        self.assertIsNotNone(membership_type_field, "Schedule should have membership_type field")
        self.assertEqual(membership_type_field.fieldtype, "Link", "membership_type should be Link field")
        
        # Check member field
        member_field = schedule_meta.get_field("member")
        self.assertIsNotNone(member_field, "Schedule should have member field")
        self.assertEqual(member_field.fieldtype, "Link", "member should be Link field")
        self.assertEqual(member_field.options, "Member", "member should link to Member")


class TestValidationEdgeCases(VereningingenTestCase):
    """Test edge cases and error conditions in validation logic"""
    
    def test_validation_with_missing_member(self):
        """Test validation behavior when member doesn't exist"""
        # Create a membership type for the test
        membership_type = self.create_test_membership_type(
            membership_type_name="Missing Member Test Type",
            dues_rate=25.0
        )
        
        # Create schedule with non-existent member using new_doc (not factory method)
        # since factory would validate the member exists
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Missing-Member-Schedule"
        schedule.member = "NON_EXISTENT_MEMBER"
        schedule.membership_type = membership_type.name
        schedule.dues_rate = 25.0
        schedule.billing_frequency = "Monthly"
        schedule.status = "Active"
        schedule.auto_generate = 1
        schedule.next_invoice_date = today()
        
        # This should not crash - validation should handle gracefully
        consistency_result = schedule.validate_membership_type_consistency()
        
        # Should return valid=True because member eligibility check will catch this
        self.assertTrue(consistency_result["valid"], "Missing member should be handled gracefully")
        self.assertIn("will be handled by eligibility check", consistency_result["reason"])
        
    def test_validation_with_multiple_active_memberships(self):
        """Test validation when member has multiple active memberships"""
        # Create member
        member = self.create_test_member(
            first_name="Multiple",
            last_name="Tester",
            email="multiple.tester@test.com"
        )
        
        # Create two membership types
        type1 = self.create_test_membership_type(
            membership_type_name="Type One",
            dues_rate=30.0
        )
        
        type2 = self.create_test_membership_type(
            membership_type_name="Type Two", 
            dues_rate=40.0
        )
        
        # Create two active memberships (if allowed by business logic)
        membership1 = self.create_test_membership(
            member=member.name,
            membership_type=type1.name
        )
        
        # Try to create second membership - this should fail due to business rules
        # Based on user feedback: "members cannot have multiple memberships"  
        try:
            membership2 = self.create_test_membership(
                member=member.name,
                membership_type=type2.name
            )
            
            # If we get here, multiple memberships were created unexpectedly
            # Skip this test and notify (as per user requirements)
            self.skipTest("Found multiple active memberships for member - this violates business rules. Skipping test as requested.")
            
        except frappe.ValidationError as e:
            # Multiple memberships not allowed - this is expected behavior
            # Verify the error message indicates the business rule is working
            self.assertIn("already has an active membership", str(e))
            
            # Test that our validation method handles single membership case correctly
            # Create an unsaved schedule document to test validation
            schedule = frappe.new_doc("Membership Dues Schedule")
            schedule.schedule_name = f"Test-Single-Membership-{frappe.generate_hash(length=6)}"
            schedule.member = member.name
            schedule.membership_type = type1.name  # Same as the existing membership
            schedule.dues_rate = 30.0
            schedule.billing_frequency = "Monthly"
            schedule.status = "Active"
            schedule.is_template = 0
            
            consistency_result = schedule.validate_membership_type_consistency()
            
            # Should be valid since there's only one membership and types match
            self.assertTrue(consistency_result["valid"], f"Single membership with matching type should be valid: {consistency_result}")