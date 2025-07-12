#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test the Enhanced Test Factory Implementation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase, 
    EnhancedTestDataFactory,
    BusinessRuleError,
    with_enhanced_test_data
)


class TestEnhancedFactory(EnhancedTestCase):
    """Test suite for the enhanced test factory"""
    
    def tearDown(self):
        """Clean up test data after each test"""
        super().tearDown()
        # Clean up any test volunteers to prevent email conflicts
        frappe.db.sql("DELETE FROM `tabVolunteer` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.commit()
    
    def test_business_rule_validation(self):
        """Test that business rules are enforced"""
        # Test age validation - member too young
        self.assertBusinessRuleViolation(
            self.factory.create_member,
            birth_date="2020-01-01"  # Too young
        )
        
        # Test age validation - birth date in future
        self.assertBusinessRuleViolation(
            self.factory.create_member,
            birth_date="2030-01-01"  # Future date
        )
        
    def test_field_validation(self):
        """Test that field validation works"""
        # Test creating member with invalid field
        with self.assertRaises(Exception) as cm:
            self.factory.create_member(
                nonexistent_field="value"
            )
        self.assertIn("Field 'nonexistent_field' does not exist", str(cm.exception))
        
    def test_deterministic_data_generation(self):
        """Test that data generation is deterministic with same seed"""
        # Create two factories with same seed
        factory1 = EnhancedTestDataFactory(seed=99999)
        factory2 = EnhancedTestDataFactory(seed=99999)
        
        # Generate test data
        email1 = factory1.generate_test_email("test")
        email2 = factory2.generate_test_email("test")
        
        # Should be identical
        self.assertEqual(email1, email2)
        
        # Test phone numbers
        phone1 = factory1.generate_test_phone()
        phone2 = factory2.generate_test_phone()
        self.assertEqual(phone1, phone2)
        
    def test_member_creation_with_validation(self):
        """Test member creation with all validations"""
        member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            birth_date="1990-01-01"
        )
        
        self.assertEqual(member.first_name, "Valid")
        self.assertEqual(member.last_name, "Member")
        self.assertTrue(member.email.startswith("TEST_member"))
        self.assertTrue(member.email.endswith("@test.invalid"))
        
    def test_volunteer_creation_with_member(self):
        """Test volunteer creation linked to member"""
        # Create member first
        member = self.create_test_member()
        
        # Create volunteer
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Test Volunteer"
        )
        
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(volunteer.volunteer_name, "Test Volunteer")
        self.assertEqual(volunteer.status, "Active")
        
    def test_application_data_generation(self):
        """Test membership application data generation"""
        # Test with skills
        app_data = self.create_test_application_data(with_skills=True)
        
        self.assertIn("first_name", app_data)
        self.assertIn("email", app_data)
        self.assertIn("volunteer_skills", app_data)
        self.assertTrue(app_data["interested_in_volunteering"])
        
        # Verify skill selection includes required skills
        skills = app_data["volunteer_skills"]
        skill_text = " ".join(skills)
        self.assertIn("Financial", skill_text)  # Should include fundraising
        
        # Test without skills
        app_data_no_skills = self.create_test_application_data(with_skills=False)
        self.assertNotIn("volunteer_skills", app_data_no_skills)
        
    @with_enhanced_test_data(seed=54321)
    def test_decorator_functionality(self):
        """Test the decorator for enhanced test data"""
        # Factory should be available
        self.assertIsNotNone(self.factory)
        
        # Should use the seed from decorator
        email = self.factory.generate_test_email()
        self.assertIn("TEST_", email)
        
    def test_query_monitoring(self):
        """Test query count monitoring from FrappeTestCase"""
        # Member creation involves many queries due to customer creation, contact creation, etc.
        # Let's be realistic about the query count
        with self.assertQueryCount(250):  # Realistic for member + volunteer creation
            member = self.create_test_member()
            volunteer = self.create_test_volunteer(member.name)
            
    def test_permission_context(self):
        """Test permission context switching from FrappeTestCase"""
        original_user = frappe.session.user
        
        with self.set_user("Administrator"):
            self.assertEqual(frappe.session.user, "Administrator")
            member = self.create_test_member()
            
        # Should restore original user
        self.assertEqual(frappe.session.user, original_user)
        
    def test_realistic_test_data(self):
        """Test that Faker generates realistic looking data"""
        member = self.create_test_member()
        
        # When using Faker, the name parts come from Faker data
        # The full_name should contain realistic looking parts
        self.assertTrue(len(member.first_name) > 0)
        self.assertTrue(len(member.last_name) > 0)
        
        # Email should be clearly test email
        self.assertTrue(member.email.startswith("TEST_"))
        self.assertTrue(member.email.endswith("@test.invalid"))
        
        # Phone should use test range (90000000+ range)
        self.assertIn("+31 6 9", member.contact_number)


class TestBusinessRules(EnhancedTestCase):
    """Specific tests for business rule validation"""
    
    def test_volunteer_start_date_rules(self):
        """Test volunteer start date business rules"""
        # Create member with known birth date
        member = self.create_test_member(
            birth_date="2000-01-01"
        )
        
        # Try to create volunteer with start date before member was 16
        self.assertBusinessRuleViolation(
            self.factory.create_volunteer,
            member_name=member.name,
            start_date="2015-01-01"  # Member would be 15, too young
        )
        
    def test_membership_date_rules(self):
        """Test membership date validation rules"""
        # This test would validate membership rules if we had a create_membership method
        # For now, we'll test the validation logic directly
        member = self.create_test_member(
            birth_date="1990-01-01"
        )
        
        # Test the membership validation logic
        test_data = {
            "member": member.name,
            "start_date": "1989-01-01"  # Before birth
        }
        
        # Should fail validation
        with self.assertRaises(BusinessRuleError):
            self.factory.validate_membership_business_rules(test_data)


if __name__ == "__main__":
    import unittest
    unittest.main()