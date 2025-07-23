"""
Integration tests for complete skills workflow from application to active volunteer
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


class TestSkillsIntegrationWorkflow(unittest.TestCase):
    """Test complete integration workflow for skills system"""

    def setUp(self):
        """Set up test data"""
        self.cleanup_test_data()
        
        # Test application data with comprehensive skills
        self.application_data = {
            "first_name": "Integration",
            "last_name": "Tester",
            "email": "integration_test@example.com",
            "birth_date": "1985-06-15",
            "address_line1": "456 Integration Ave",
            "city": "Test City",
            "country": "Netherlands", 
            "postal_code": "5678CD",
            "interested_in_volunteering": True,
            "volunteer_availability": "Weekly",
            "volunteer_experience_level": "Experienced",
            "volunteer_areas": ["events", "communications", "fundraising"],
            "volunteer_skills": [
                "Technical|Python Programming",
                "Technical|Database Design",
                "Communication|Technical Writing",
                "Communication|Presentation Skills",
                "Leadership|Project Management",
                "Leadership|Team Coordination",
                "Financial|Budget Planning",
                "Organizational|Event Coordination",
                "Other|Custom Skill Example"
            ],
            "volunteer_skill_level": "4",
            "volunteer_availability_time": "Monday evenings, weekend mornings",
            "volunteer_comments": "Passionate about using technology for social good. Previous experience with nonprofit organizations."
        }

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove all test data"""
        # Delete test members and related data
        test_emails = ["integration_test@example.com", "workflow_test@example.com", "edge_case@example.com"]
        
        for email in test_emails:
            members = frappe.get_all("Member", filters={"email": email})
            for member in members:
                try:
                    # Delete volunteers first
                    volunteers = frappe.get_all("Volunteer", filters={"member": member.name})
                    for volunteer in volunteers:
                        frappe.delete_doc("Volunteer", volunteer.name, force=True, ignore_permissions=True)
                    
                    # Delete memberships
                    memberships = frappe.get_all("Membership", filters={"member": member.name})
                    for membership in memberships:
                        frappe.delete_doc("Membership", membership.name, force=True, ignore_permissions=True)
                    
                    # Delete comments
                    comments = frappe.get_all("Comment", filters={
                        "reference_doctype": "Member",
                        "reference_name": member.name
                    })
                    for comment in comments:
                        frappe.delete_doc("Comment", comment.name, force=True, ignore_permissions=True)
                    
                    # Delete member
                    frappe.delete_doc("Member", member.name, force=True, ignore_permissions=True)
                except Exception as e:
                    # Ignore cleanup errors
                    pass
        
        # Clean up any test volunteers not linked to members
        try:
            test_volunteers = frappe.get_all("Volunteer", 
                filters={"volunteer_name": ["like", "%Integration%"]})
            for volunteer in test_volunteers:
                frappe.delete_doc("Volunteer", volunteer.name, force=True, ignore_permissions=True)
        except Exception:
            pass
        
        frappe.db.commit()

    def test_complete_workflow_application_to_skills_search(self):
        """Test complete workflow from application submission to skills search"""
        
        # PHASE 1: Submit membership application with volunteer interest
        print("Phase 1: Submitting membership application...")
        result = submit_membership_application(self.application_data)
        
        self.assertTrue(result["success"])
        member_id = result["member_id"]
        
        # Verify member record created with volunteer interest
        member = frappe.get_doc("Member", member_id)
        self.assertEqual(member.status, "Pending")
        # Check for volunteer interest indicators (be flexible about exact format)
        notes = member.notes or ""
        has_volunteer_flag = ("VOLUNTEER_INTEREST_FLAG: True" in notes or 
                             "interested_in_volunteering" in notes or
                             member.interested_in_volunteering == 1)
        self.assertTrue(has_volunteer_flag, f"Expected volunteer interest flag in member notes or field. Notes: '{notes}', interested_in_volunteering: {member.interested_in_volunteering}")
        
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
        self.assertEqual(volunteer.email, self.application_data["email"])
        self.assertEqual(volunteer.volunteer_name, f"{self.application_data['first_name']} {self.application_data['last_name']}")
        
        # PHASE 4: Verify skills were transferred correctly
        print("Phase 4: Verifying skills transfer...")
        self.assertGreater(len(volunteer.skills_and_qualifications), 0, "Volunteer should have skills")
        
        # Check specific skills
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        expected_skills = [
            "Python Programming", "Database Design", "Technical Writing",
            "Presentation Skills", "Project Management", "Team Coordination",
            "Budget Planning", "Event Coordination", "Custom Skill Example"
        ]
        
        for expected_skill in expected_skills:
            self.assertIn(expected_skill, skill_names, f"Skill '{expected_skill}' should be present")
        
        # Verify skill categories
        categories = {skill.skill_category for skill in volunteer.skills_and_qualifications}
        expected_categories = {"Technical", "Communication", "Leadership", "Financial", "Organizational", "Other"}
        self.assertTrue(expected_categories.issubset(categories), "All skill categories should be present")
        
        # Verify proficiency levels
        for skill in volunteer.skills_and_qualifications:
            self.assertIn("4 - Advanced", skill.proficiency_level, "All skills should have correct proficiency level")
        
        # PHASE 5: Test skills search functionality
        print("Phase 5: Testing skills search functionality...")
        
        # Search by specific skill
        python_results = search_volunteers_by_skill("Python Programming")
        self.assertGreater(len(python_results), 0, "Should find volunteer with Python Programming skill")
        
        found_volunteer = None
        for result in python_results:
            if result.volunteer_name == volunteer.volunteer_name:
                found_volunteer = result
                break
        
        self.assertIsNotNone(found_volunteer, "Our test volunteer should be found in Python Programming search")
        self.assertEqual(found_volunteer.matched_skill, "Python Programming")
        self.assertEqual(found_volunteer.skill_category, "Technical")
        
        # Search by category
        technical_results = search_volunteers_by_skill("", category="Technical")
        technical_volunteers = [r.volunteer_name for r in technical_results]
        self.assertIn(volunteer.volunteer_name, technical_volunteers, "Volunteer should be found in Technical category search")
        
        # Search by proficiency level
        advanced_results = search_volunteers_by_skill("Python Programming", min_level=4)
        advanced_volunteers = [r.volunteer_name for r in advanced_results]
        self.assertIn(volunteer.volunteer_name, advanced_volunteers, "Volunteer should be found in advanced level search")
        
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

    def test_multiple_volunteers_skills_interaction(self):
        """Test skills system with multiple volunteers"""
        
        # Create first volunteer through application process
        result1 = submit_membership_application(self.application_data)
        member1_id = result1["member_id"]
        approve_membership_application(member1_id, create_invoice=False)
        
        # Create second volunteer with different skills
        app_data_2 = self.application_data.copy()
        app_data_2["email"] = "workflow_test@example.com"
        app_data_2["first_name"] = "Workflow"
        app_data_2["last_name"] = "Test2"
        app_data_2["volunteer_skills"] = [
            "Technical|Python Programming",  # Overlapping skill
            "Technical|Java Development",    # Different skill
            "Communication|Social Media Management",
            "Leadership|Strategic Planning",
            "Event Planning|Conference Organization"
        ]
        app_data_2["volunteer_skill_level"] = "5"  # Different level
        
        result2 = submit_membership_application(app_data_2)
        member2_id = result2["member_id"]
        approve_membership_application(member2_id, create_invoice=False)
        
        # Test overlapping skills search
        python_volunteers = search_volunteers_by_skill("Python Programming")
        self.assertGreaterEqual(len(python_volunteers), 2, "Should find both volunteers with Python Programming")
        
        # Verify different proficiency levels
        proficiency_levels = {r.proficiency_level for r in python_volunteers}
        self.assertIn("4 - Advanced", proficiency_levels)
        self.assertIn("5 - Expert", proficiency_levels)
        
        # Test unique skills
        java_volunteers = search_volunteers_by_skill("Java Development")
        self.assertEqual(len(java_volunteers), 1, "Should find only one volunteer with Java Development")
        
        # Test skills overview with multiple volunteers
        overview = get_skills_overview()
        self.assertTrue(overview["success"])
        
        # Python should appear with count >= 2
        python_skill = next((s for s in overview["top_skills"] if s["volunteer_skill"] == "Python Programming"), None)
        if python_skill:
            self.assertGreaterEqual(python_skill["volunteer_count"], 2)

    def test_workflow_error_handling(self):
        """Test workflow error handling and edge cases"""
        
        # Test application without volunteer interest
        no_volunteer_data = self.application_data.copy()
        no_volunteer_data["email"] = "no_volunteer@example.com"
        no_volunteer_data["interested_in_volunteering"] = False
        del no_volunteer_data["volunteer_skills"]
        
        result = submit_membership_application(no_volunteer_data)
        member_id = result["member_id"]
        
        # Approve member
        approve_membership_application(member_id, create_invoice=False)
        
        # Should not create volunteer record
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 0, "No volunteer record should be created for non-volunteer member")
        
        # Clean up
        frappe.delete_doc("Member", member_id, force=True)

    def test_skills_data_validation(self):
        """Test validation of skills data throughout workflow"""
        
        # Submit application with edge case skills data
        edge_case_data = self.application_data.copy()
        edge_case_data["email"] = "edge_case@example.com"
        edge_case_data["volunteer_skills"] = [
            "Technical|Skill with Special Characters !@#",
            "Communication|Very Long Skill Name That Exceeds Normal Length Expectations",
            "Other|Single",
            "Leadership|",  # Empty skill name
            "Technical|Skill-With-Hyphens-And_Underscores"
        ]
        
        result = submit_membership_application(edge_case_data)
        member_id = result["member_id"]
        approve_membership_application(member_id, create_invoice=False)
        
        # Verify volunteer was created despite edge cases
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 1)
        
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Verify skills were processed correctly
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        
        # Should include valid skills
        self.assertIn("Skill with Special Characters !@#", skill_names)
        self.assertIn("Very Long Skill Name That Exceeds Normal Length Expectations", skill_names)
        self.assertIn("Single", skill_names)
        self.assertIn("Skill-With-Hyphens-And_Underscores", skill_names)
        
        # Empty skill name should be filtered out or handled gracefully
        # (Implementation dependent - just verify no crashes)
        
        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)
        frappe.delete_doc("Member", member_id, force=True)

    def test_performance_with_realistic_data_volume(self):
        """Test workflow performance with realistic data volumes"""
        
        # Create application and process normally
        result = submit_membership_application(self.application_data)
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
        self.assertGreater(len(volunteer.skills_and_qualifications), 5, "All skills should be transferred")

    def test_end_to_end_skills_management(self):
        """Test end-to-end skills management after volunteer creation"""
        
        # Create volunteer through application process
        result = submit_membership_application(self.application_data)
        member_id = result["member_id"]
        approve_membership_application(member_id, create_invoice=False)
        
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Test adding additional skills after creation
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
        
        # Test updating skill proficiency
        for skill in volunteer.skills_and_qualifications:
            if skill.volunteer_skill == "Python Programming":
                skill.proficiency_level = "5 - Expert"
                break
        
        volunteer.save()
        
        # Verify updated proficiency appears in search
        expert_python = search_volunteers_by_skill("Python Programming", min_level=5)
        expert_found = any(r.volunteer_name == volunteer.volunteer_name for r in expert_python)
        self.assertTrue(expert_found, "Volunteer should be found in expert-level Python search after update")

    def test_skills_browse_page_integration(self):
        """Test integration with skills browse page functionality"""
        
        # Create volunteer through application
        result = submit_membership_application(self.application_data)
        member_id = result["member_id"]
        approve_membership_application(member_id, create_invoice=False)
        
        # Test skills browse page backend function
        from verenigingen.templates.pages.volunteer.skills import (
            get_skills_grouped_by_category,
            get_skills_statistics
        )
        
        # Test skills grouping
        skills_by_category = get_skills_grouped_by_category()
        self.assertGreater(len(skills_by_category), 0, "Should have skills grouped by category")
        
        # Verify our skills appear
        all_skills = []
        for category, skills in skills_by_category.items():
            all_skills.extend([skill['skill_name'] for skill in skills])
        
        self.assertIn("Python Programming", all_skills, "Our volunteer's skills should appear in browse page")
        
        # Test statistics
        stats = get_skills_statistics()
        self.assertGreater(stats["total_unique_skills"], 0, "Should have unique skills count")
        self.assertGreater(stats["volunteers_with_skills"], 0, "Should have volunteers with skills count")

    def test_data_consistency_across_workflow(self):
        """Test data consistency throughout the entire workflow"""
        
        # Submit application
        result = submit_membership_application(self.application_data)
        member_id = result["member_id"]
        
        # Get initial data
        member = frappe.get_doc("Member", member_id)
        initial_skills_data = member.notes
        
        # Approve application
        approve_membership_application(member_id, create_invoice=False)
        
        # Get volunteer
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        
        # Verify data consistency
        original_skills = self.application_data["volunteer_skills"]
        volunteer_skills = [(s.skill_category, s.volunteer_skill) for s in volunteer.skills_and_qualifications]
        
        for skill_value in original_skills:
            if '|' in skill_value:
                category, skill_name = skill_value.split('|', 1)
                self.assertIn((category, skill_name), volunteer_skills, 
                             f"Skill {skill_name} in category {category} should be preserved")
        
        # Verify proficiency level consistency
        expected_level = self.application_data["volunteer_skill_level"]
        for skill in volunteer.skills_and_qualifications:
            self.assertIn(expected_level, skill.proficiency_level, 
                         "Proficiency level should be preserved from application")


if __name__ == '__main__':
    unittest.main()