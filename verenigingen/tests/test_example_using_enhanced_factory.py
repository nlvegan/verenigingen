#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example: Using Enhanced Test Factory in Real Tests
This demonstrates how to use the enhanced factory for actual testing scenarios
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerSkillsWithEnhancedFactory(EnhancedTestCase):
    """Example test using the enhanced factory for volunteer skills testing"""
    
    def tearDown(self):
        """Clean up test data after each test"""
        super().tearDown()
        # Clean up any test volunteers to prevent email conflicts
        frappe.db.sql("DELETE FROM `tabVolunteer` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.commit()
    
    def test_volunteer_skill_creation(self):
        """Test creating volunteer with skills using enhanced factory"""
        # Create member and volunteer using factory
        member = self.create_test_member(
            first_name="Jane",
            last_name="Doe",
            birth_date="1990-05-15"
        )
        
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name="Jane Doe - Volunteer"
        )
        
        # Add skills to volunteer
        skill_data = {
            "skill_category": "Technical",
            "volunteer_skill": "Web Development",
            "proficiency_level": "4 - Advanced",
            "experience_years": 5
        }
        
        skill = self.factory.create_volunteer_skill(
            volunteer.name,
            skill_data
        )
        
        # Verify skill was created correctly
        self.assertEqual(skill.skill_category, "Technical")
        self.assertEqual(skill.volunteer_skill, "Web Development")
        self.assertEqual(skill.proficiency_level, "4 - Advanced")
        
    def test_query_count_optimization(self):
        """Demonstrate query count monitoring"""
        # Monitor that our operations are efficient
        with self.assertQueryCount(300):  # Set realistic limit
            # Create test data
            member = self.create_test_member()
            volunteer = self.create_test_volunteer(member.name)
            
            # Add multiple skills
            skills = [
                {"skill_category": "Technical", "volunteer_skill": "Python"},
                {"skill_category": "Communication", "volunteer_skill": "Writing"},
                {"skill_category": "Leadership", "volunteer_skill": "Team Management"}
            ]
            
            for skill_data in skills:
                self.factory.create_volunteer_skill(volunteer.name, skill_data)
                
    def test_permission_switching(self):
        """Test operations with different user permissions"""
        # Create data as Administrator
        member = self.create_test_member()
        
        # Switch to a different user context
        with self.set_user("test@example.com"):
            # This would test permission-restricted operations
            # For example, trying to access the member record
            try:
                member_doc = frappe.get_doc("Member", member.name)
                # Test what the user can see/do
            except frappe.PermissionError:
                # Expected if user doesn't have permissions
                pass
                
    def test_business_rules_in_context(self):
        """Test business rules work correctly in real scenarios"""
        # Try to create a young member - should fail
        with self.assertRaises(Exception) as cm:
            young_member = self.create_test_member(
                first_name="Young",
                last_name="Person",
                birth_date="2010-01-01"  # 15 years old
            )
        self.assertIn("Members must be 16+ years old", str(cm.exception))
        
        # Create an adult member
        adult_member = self.create_test_member(
            first_name="Adult",
            last_name="Person", 
            birth_date="1990-01-01"  # 35 years old
        )
        
        # Should succeed
        volunteer = self.factory.create_volunteer(
            member_name=adult_member.name
        )
        self.assertIsNotNone(volunteer)


class TestApplicationDataGeneration(EnhancedTestCase):
    """Example of using factory for application testing"""
    
    def tearDown(self):
        """Clean up test data after each test"""
        super().tearDown()
        # Clean up any test data
        frappe.db.sql("DELETE FROM `tabVolunteer` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.commit()
    
    def test_membership_application_flow(self):
        """Test full membership application flow with test data"""
        # Generate realistic application data
        app_data = self.create_test_application_data(with_skills=True)
        
        # Verify generated data
        self.assertIn("first_name", app_data)
        self.assertIn("email", app_data)
        self.assertIn("volunteer_skills", app_data)
        
        # Email should be test email
        self.assertTrue(app_data["email"].startswith("TEST_"))
        self.assertTrue(app_data["email"].endswith("@test.invalid"))
        
        # Should have realistic skills
        self.assertGreater(len(app_data["volunteer_skills"]), 3)
        self.assertIn("Financial|Fundraising", app_data["volunteer_skills"])
        
    def test_deterministic_application_data(self):
        """Test that application data is deterministic with same seed"""
        # Create two factories with same seed
        factory1 = self.factory.__class__(seed=99999)
        factory2 = self.factory.__class__(seed=99999)
        
        # Generate application data
        app1 = factory1.create_application_data()
        app2 = factory2.create_application_data()
        
        # Should be identical (except for test_run_id)
        self.assertEqual(app1["first_name"], app2["first_name"])
        self.assertEqual(app1["volunteer_availability"], app2["volunteer_availability"])


if __name__ == "__main__":
    import unittest
    unittest.main()