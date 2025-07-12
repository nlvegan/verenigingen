"""
Integration tests for complete skills workflow using SecureTestDataFactory
Demonstrates comprehensive testing with deterministic, schema-validated data
"""

import unittest
import frappe
from frappe.utils import today, now_datetime

from verenigingen.verenigingen.web_form.membership_application import (
    submit_membership_application,
    approve_membership_application
)
from verenigingen.verenigingen.doctype.volunteer.volunteer import (
    search_volunteers_by_skill,
    get_all_skills_list
)
from verenigingen.api.volunteer_skills import get_skills_overview

from verenigingen.tests.fixtures.secure_test_data_factory import (
    SecureTestContext,
    with_secure_test_data
)
from verenigingen.tests.fixtures.field_validator import validate_field


class TestSkillsIntegrationWorkflowSecure(unittest.TestCase):
    """Test complete integration workflow for skills system using secure factory"""

    @with_secure_test_data(seed=54321)
    def test_complete_workflow_application_to_skills_search(self, factory):
        """Test complete workflow from application submission to skills search"""
        
        # PHASE 1: Submit membership application with volunteer interest
        print("Phase 1: Submitting membership application...")
        application_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(application_data)
        
        self.assertTrue(result["success"])
        member_id = result["member_id"]
        
        # Verify member record created with volunteer interest
        member = frappe.get_doc("Member", member_id)
        self.assertEqual(member.status, "Pending")
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)
        
        # PHASE 2: Approve membership application
        print("Phase 2: Approving membership application...")
        approval_result = approve_membership_application(member_id, create_invoice=False)
        
        self.assertTrue(approval_result["success"])
        
        # Verify member is approved
        member.reload()
        self.assertEqual(member.status, "Active")
        self.assertEqual(member.application_status, "Approved")
        
        # PHASE 3: Verify volunteer record was automatically created
        print("Phase 3: Verifying volunteer record creation...")
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 1, "Exactly one volunteer record should be created")
        
        volunteer_name = volunteers[0].name
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        
        # Verify volunteer basic info
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.email, application_data["email"])
        self.assertEqual(volunteer.volunteer_name, f"{application_data['first_name']} {application_data['last_name']}")
        
        # PHASE 4: Verify skills were transferred correctly
        print("Phase 4: Verifying skills transfer...")
        self.assertGreater(len(volunteer.skills_and_qualifications), 0, "Volunteer should have skills")
        
        # With seed 54321, we get deterministic skills
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        expected_skills = ["Web Development", "Graphic Design", "Writing"]  # First 3 from deterministic list
        
        for expected_skill in expected_skills:
            self.assertIn(expected_skill, skill_names, f"Skill '{expected_skill}' should be present")
        
        # Verify skill categories
        categories = {skill.skill_category for skill in volunteer.skills_and_qualifications}
        expected_categories = {"Technical", "Communication"}  # Based on deterministic data
        self.assertTrue(expected_categories.issubset(categories), "Expected categories should be present")
        
        # Verify proficiency levels (deterministic from seed)
        for skill in volunteer.skills_and_qualifications:
            self.assertIn("1 - Beginner", skill.proficiency_level, "Skills should have correct proficiency level")
        
        # PHASE 5: Test skills search functionality
        print("Phase 5: Testing skills search functionality...")
        
        # Search by specific skill
        web_dev_results = search_volunteers_by_skill("Web Development")
        self.assertGreater(len(web_dev_results), 0, "Should find volunteer with Web Development skill")
        
        found_volunteer = None
        for result in web_dev_results:
            if result.volunteer_name == volunteer.volunteer_name:
                found_volunteer = result
                break
        
        self.assertIsNotNone(found_volunteer, "Our test volunteer should be found in Web Development search")
        self.assertEqual(found_volunteer.matched_skill, "Web Development")
        self.assertEqual(found_volunteer.skill_category, "Technical")
        
        # Search by category
        technical_results = search_volunteers_by_skill("", category="Technical")
        technical_volunteers = [r.volunteer_name for r in technical_results]
        self.assertIn(volunteer.volunteer_name, technical_volunteers, "Volunteer should be found in Technical category search")
        
        # PHASE 6: Test skills overview integration
        print("Phase 6: Testing skills overview integration...")
        overview = get_skills_overview()
        
        self.assertTrue(overview["success"])
        
        # Verify our skills appear in overview
        all_skills = overview["top_skills"]
        overview_skill_names = [skill["volunteer_skill"] for skill in all_skills]
        
        # At least some of our skills should appear
        skills_found = sum(1 for skill in expected_skills if skill in overview_skill_names)
        self.assertGreater(skills_found, 0, "Some of our volunteer's skills should appear in overview")
        
        # PHASE 7: Test skills list functionality
        print("Phase 7: Testing skills list functionality...")
        all_skills_list = get_all_skills_list()
        
        self.assertGreater(len(all_skills_list), 0, "Skills list should not be empty")
        
        list_skill_names = [skill.volunteer_skill for skill in all_skills_list]
        skills_in_list = sum(1 for skill in expected_skills if skill in list_skill_names)
        self.assertGreater(skills_in_list, 0, "Some of our volunteer's skills should appear in skills list")
        
        print("✅ Complete workflow test passed!")

    @with_secure_test_data(seed=54322)
    def test_multiple_volunteers_skills_interaction(self, factory):
        """Test skills system with multiple volunteers"""
        
        # Create first volunteer through application process
        app_data_1 = factory.create_application_data(with_volunteer_skills=True)
        result1 = submit_membership_application(app_data_1)
        member1_id = result1["member_id"]
        approve_membership_application(member1_id, create_invoice=False)
        
        # Create second volunteer with different skills using different sequence
        factory.get_next_sequence("application")  # Advance sequence for different skills
        app_data_2 = factory.create_application_data(with_volunteer_skills=True)
        result2 = submit_membership_application(app_data_2)
        member2_id = result2["member_id"]
        approve_membership_application(member2_id, create_invoice=False)
        
        # Both should have Web Development skill (deterministic first skill)
        web_dev_volunteers = search_volunteers_by_skill("Web Development")
        self.assertGreaterEqual(len(web_dev_volunteers), 2, "Should find both volunteers with Web Development")
        
        # Test skills overview with multiple volunteers
        overview = get_skills_overview()
        self.assertTrue(overview["success"])
        
        # Web Development should appear with count >= 2
        web_dev_skill = next((s for s in overview["top_skills"] if s["volunteer_skill"] == "Web Development"), None)
        if web_dev_skill:
            self.assertGreaterEqual(web_dev_skill["volunteer_count"], 2)

    @with_secure_test_data(seed=54323)
    def test_workflow_error_handling(self, factory):
        """Test workflow error handling and edge cases"""
        
        # Test application without volunteer interest
        no_volunteer_data = factory.create_application_data(with_volunteer_skills=False)
        
        result = submit_membership_application(no_volunteer_data)
        member_id = result["member_id"]
        
        # Approve member
        approve_membership_application(member_id, create_invoice=False)
        
        # Should not create volunteer record
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 0, "No volunteer record should be created for non-volunteer member")

    @with_secure_test_data(seed=54324)
    def test_skills_data_validation(self, factory):
        """Test validation of skills data throughout workflow"""
        
        # Submit application with standard skills data
        app_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(app_data)
        member_id = result["member_id"]
        approve_membership_application(member_id, create_invoice=False)
        
        # Verify volunteer was created despite edge cases
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 1)
        
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Verify skills were processed correctly
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        
        # Should include deterministic skills
        self.assertIn("Web Development", skill_names)
        self.assertIn("Graphic Design", skill_names)
        self.assertIn("Writing", skill_names)

    @with_secure_test_data(seed=54325)
    def test_performance_with_realistic_data_volume(self, factory):
        """Test workflow performance with realistic data volumes"""
        
        # Create application and process normally
        app_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(app_data)
        member_id = result["member_id"]
        
        # Measure approval process time
        import time
        start_time = time.time()
        
        approve_membership_application(member_id, create_invoice=False)
        
        approval_time = time.time() - start_time
        
        # Should complete in reasonable time (< 5 seconds for test environment)
        self.assertLess(approval_time, 5.0, "Approval process should complete quickly")
        
        # Verify volunteer was created correctly despite performance test
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 1)
        
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        self.assertGreater(len(volunteer.skills_and_qualifications), 0, "Skills should be transferred")

    @with_secure_test_data(seed=54326)
    def test_end_to_end_skills_management(self, factory):
        """Test end-to-end skills management after volunteer creation"""
        
        # Create volunteer through application process
        app_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(app_data)
        member_id = result["member_id"]
        approve_membership_application(member_id, create_invoice=False)
        
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Test adding additional skills after creation
        # Validate the field exists first
        validate_field("Volunteer Skill", "skill_category")
        validate_field("Volunteer Skill", "volunteer_skill")
        validate_field("Volunteer Skill", "proficiency_level")
        validate_field("Volunteer Skill", "experience_years")
        
        new_skill = volunteer.append('skills_and_qualifications', {})
        new_skill.skill_category = "Technical"
        new_skill.volunteer_skill = "Machine Learning"
        new_skill.proficiency_level = "3 - Intermediate"
        new_skill.experience_years = 1
        
        volunteer.save()
        
        # Verify new skill appears in search
        ml_results = search_volunteers_by_skill("Machine Learning")
        self.assertGreater(len(ml_results), 0, "Should find volunteer with newly added Machine Learning skill")
        
        found = any(r.volunteer_name == volunteer.volunteer_name for r in ml_results)
        self.assertTrue(found, "Our volunteer should be found in Machine Learning search")

    @with_secure_test_data(seed=54327)
    def test_data_consistency_across_workflow(self, factory):
        """Test data consistency throughout the entire workflow"""
        
        # Submit application
        app_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(app_data)
        member_id = result["member_id"]
        
        # Get initial data
        member = frappe.get_doc("Member", member_id)
        initial_skills_data = member.notes
        
        # Approve application
        approve_membership_application(member_id, create_invoice=False)
        
        # Get volunteer
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Verify data consistency - deterministic skills from seed
        original_skills = app_data["volunteer_skills"]  # ["Technical|Web Development", "Technical|Graphic Design", "Communication|Writing"]
        volunteer_skills = [(s.skill_category, s.volunteer_skill) for s in volunteer.skills_and_qualifications]
        
        for skill_value in original_skills:
            if '|' in skill_value:
                category, skill_name = skill_value.split('|', 1)
                self.assertIn((category, skill_name), volunteer_skills, 
                             f"Skill {skill_name} in category {category} should be preserved")
        
        # Verify proficiency level consistency
        expected_level = app_data["volunteer_skill_level"]  # "1" from deterministic data
        for skill in volunteer.skills_and_qualifications:
            self.assertIn(expected_level, skill.proficiency_level, 
                         "Proficiency level should be preserved from application")

    @with_secure_test_data(seed=54328)
    def test_field_validation_security(self, factory):
        """Test that field validation prevents schema bugs"""
        
        # Test that trying to access non-existent fields raises errors
        from verenigingen.tests.fixtures.field_validator import FieldValidationError
        
        with self.assertRaises(FieldValidationError):
            validate_field("Member", "nonexistent_field")
            
        with self.assertRaises(FieldValidationError):
            validate_field("Volunteer", "fake_field")
            
        # Test that valid fields pass
        validate_field("Member", "first_name")
        validate_field("Member", "email")
        validate_field("Volunteer", "volunteer_name")
        validate_field("Volunteer", "member")
        
        print("✅ Field validation security test passed")


if __name__ == '__main__':
    unittest.main()