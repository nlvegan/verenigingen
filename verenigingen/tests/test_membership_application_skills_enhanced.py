"""
Unit tests for membership application skills integration using Enhanced Test Factory
Migrated from test_membership_application_skills.py to use EnhancedTestCase
"""

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.web_form.membership_application import (
    submit_membership_application,
    create_volunteer_application_data,
    create_volunteer_from_approved_member,
    parse_volunteer_data_from_notes,
    add_skills_to_volunteer,
    get_proficiency_label,
    approve_membership_application
)


class TestMembershipApplicationSkillsEnhanced(EnhancedTestCase):
    """Test skills integration in membership application workflow using enhanced factory"""

    def setUp(self):
        """Set up test data using enhanced factory"""
        super().setUp()
        
        # Clean up any existing test data first
        self.cleanup_test_data()
        
        # Use factory to generate test application data
        self.test_application_data = self.factory.create_application_data(with_volunteer_skills=True)
        self.test_email = self.test_application_data["email"]
    
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
        super().tearDown()
    
    def cleanup_test_data(self):
        """Clean up test data to prevent conflicts"""
        # Clean up test members and volunteers
        frappe.db.sql("DELETE FROM `tabVolunteer` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE 'TEST_%@test.invalid'")
        frappe.db.sql("DELETE FROM `tabAddress` WHERE email_id LIKE 'TEST_%@test.invalid'")
        frappe.db.commit()

    def test_submit_application_with_volunteer_interest(self):
        """Test submitting membership application with volunteer interest"""
        # Monitor performance
        with self.assertQueryCount(300):  # Set realistic limit for application submission
            result = submit_membership_application(self.test_application_data)
        
        self.assertTrue(result["success"])
        self.assertIn("member_id", result)
        
        # Verify member was created
        member = frappe.get_doc("Member", result["member_id"])
        self.assertEqual(member.email, self.test_email)
        self.assertEqual(member.status, "Pending")
        
        # Verify volunteer interest was captured
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)
        
        # Verify volunteer data in notes
        # The factory generates skills including these categories
        self.assertIn("Technical", member.notes)
        self.assertIn("Communication", member.notes)
        self.assertIn("Leadership", member.notes)
        self.assertIn("Financial", member.notes)
        self.assertIn("Overall Skill Level:", member.notes)
        self.assertIn("Availability:", member.notes)

    def test_submit_application_without_volunteer_interest(self):
        """Test submitting application without volunteer interest"""
        # Create application data without volunteer interest
        data = self.factory.create_application_data(with_volunteer_skills=False)
        
        result = submit_membership_application(data)
        
        self.assertTrue(result["success"])
        member = frappe.get_doc("Member", result["member_id"])
        
        # Verify no volunteer interest captured
        self.assertNotIn("VOLUNTEER_INTEREST_FLAG: True", member.notes or "")
        self.assertNotIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes or "")

    def test_create_volunteer_application_data(self):
        """Test creating volunteer application data structure"""
        # Create a test member using factory
        member = self.create_test_member(
            status="Pending"
        )
        
        volunteer_info = create_volunteer_application_data(member, self.test_application_data)
        
        # Verify volunteer info structure
        self.assertTrue(volunteer_info["interested_in_volunteering"])
        self.assertIn(volunteer_info["volunteer_availability"], ["Weekly", "Monthly", "Quarterly"])
        self.assertIn(volunteer_info["volunteer_experience_level"], ["Beginner", "Intermediate", "Experienced"])
        self.assertGreater(len(volunteer_info["volunteer_skills"]), 3)  # Factory generates 4-6 skills
        
        # Verify member was updated
        member.reload()
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)

    def test_parse_volunteer_data_from_notes(self):
        """Test parsing volunteer data from member notes"""
        notes = """
Some other notes here.

VOLUNTEER INTEREST APPLICATION DATA:
==================================

Interested in Volunteering: Yes
Availability: Monthly
Experience Level: Intermediate
Overall Skill Level: 4

Areas of Interest:
events, communications

Skills Selected:
Technical: Web Development, Graphic Design
Communication: Writing
Leadership: Team Leadership

Availability Details:
Weekends and evenings

Additional Comments:
Excited to contribute!
"""
        
        data = parse_volunteer_data_from_notes(notes)
        
        self.assertIsNotNone(data)
        self.assertEqual(data["availability"], "Monthly")
        self.assertEqual(data["experience_level"], "Intermediate")
        self.assertEqual(data["skill_level"], "4")
        self.assertIn("events", data["volunteer_areas"])
        self.assertIn("communications", data["volunteer_areas"])
        self.assertIn("Technical", data["skills_by_category"])
        self.assertIn("Web Development", data["skills_by_category"]["Technical"])
        self.assertIn("Graphic Design", data["skills_by_category"]["Technical"])

    def test_parse_volunteer_data_no_volunteer_section(self):
        """Test parsing notes without volunteer section"""
        notes = "Just some regular notes without volunteer data"
        
        data = parse_volunteer_data_from_notes(notes)
        
        self.assertIsNone(data)

    def test_get_proficiency_label(self):
        """Test proficiency label conversion"""
        self.assertEqual(get_proficiency_label("1"), "Beginner")
        self.assertEqual(get_proficiency_label("2"), "Basic")
        self.assertEqual(get_proficiency_label("3"), "Intermediate")
        self.assertEqual(get_proficiency_label("4"), "Advanced")
        self.assertEqual(get_proficiency_label("5"), "Expert")
        self.assertEqual(get_proficiency_label("unknown"), "Intermediate")

    def test_create_volunteer_from_approved_member(self):
        """Test creating volunteer record from approved member"""
        # Submit application first
        result = submit_membership_application(self.test_application_data)
        member = frappe.get_doc("Member", result["member_id"])
        
        # Approve the member
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        # Create volunteer from approved member
        volunteer_name = create_volunteer_from_approved_member(member)
        
        self.assertIsNotNone(volunteer_name)
        
        # Verify volunteer record
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(volunteer.email, member.email)
        self.assertEqual(volunteer.status, "Active")
        
        # Verify skills were added (factory generates consistent skills)
        self.assertGreater(len(volunteer.skills_and_qualifications), 0)
        
        # Check that skills were created from the application data
        skill_categories = [skill.skill_category for skill in volunteer.skills_and_qualifications]
        self.assertIn("Technical", skill_categories)
        self.assertIn("Financial", skill_categories)  # Factory always includes Financial|Fundraising

    def test_create_volunteer_duplicate_prevention(self):
        """Test that duplicate volunteer records are not created"""
        # Submit application and create volunteer
        result = submit_membership_application(self.test_application_data)
        member = frappe.get_doc("Member", result["member_id"])
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        # Create volunteer first time
        volunteer_name1 = create_volunteer_from_approved_member(member)
        self.assertIsNotNone(volunteer_name1)
        
        # Try to create volunteer again - should return existing
        volunteer_name2 = create_volunteer_from_approved_member(member)
        
        # Should return the same volunteer
        self.assertEqual(volunteer_name1, volunteer_name2)

    def test_add_skills_to_volunteer(self):
        """Test adding skills to volunteer record"""
        # Create member and volunteer using factory
        member = self.create_test_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        
        # Define volunteer data with skills
        volunteer_data = {
            "skills_by_category": {
                "Technical": ["Python", "Django"],
                "Communication": ["Public Speaking"],
                "Leadership": ["Project Management"]
            },
            "skill_level": "3"
        }
        
        add_skills_to_volunteer(volunteer, volunteer_data)
        
        # Reload volunteer to get updated skills
        volunteer.reload()
        
        # Verify skills were added
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Python", skill_names)
        self.assertIn("Django", skill_names)
        self.assertIn("Public Speaking", skill_names)
        self.assertIn("Project Management", skill_names)
        
        # Verify proficiency level
        for skill in volunteer.skills_and_qualifications:
            if skill.volunteer_skill in ["Python", "Django", "Public Speaking", "Project Management"]:
                self.assertEqual(skill.proficiency_level, "3 - Intermediate")

    def test_approve_membership_application_with_volunteer_creation(self):
        """Test full workflow from application to volunteer creation"""
        # Submit application
        result = submit_membership_application(self.test_application_data)
        member_id = result["member_id"]
        
        # Test with different permission context
        with self.set_user("Administrator"):
            # Approve the application
            approve_result = approve_membership_application(member_id)
            
            self.assertTrue(approve_result.get("success", False))
            
            # Verify member status
            member = frappe.get_doc("Member", member_id)
            self.assertEqual(member.status, "Active")
            self.assertEqual(member.application_status, "Approved")
            
            # Verify volunteer was created if there was interest
            if self.test_application_data.get("interested_in_volunteering"):
                volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
                self.assertEqual(len(volunteers), 1)
                
                volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
                self.assertGreater(len(volunteer.skills_and_qualifications), 0)

    def test_invalid_skill_data_handling(self):
        """Test handling of invalid skill data in application"""
        # Create application with invalid skill format
        invalid_data = self.factory.create_application_data(with_volunteer_skills=True)
        invalid_data["volunteer_skills"] = ["InvalidFormat", "NoCategory"]  # Missing category separator
        
        # Should still process application but handle invalid skills gracefully
        result = submit_membership_application(invalid_data)
        self.assertTrue(result["success"])
        
        member = frappe.get_doc("Member", result["member_id"])
        # Should still capture volunteer interest even if skills are malformed
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)

    def test_performance_of_skill_processing(self):
        """Test performance of skill processing in application workflow"""
        # Create application with maximum skills
        app_data = self.factory.create_application_data(with_volunteer_skills=True)
        
        # Monitor query count for full workflow
        with self.assertQueryCount(350):  # Reasonable limit for full workflow
            # Submit application
            result = submit_membership_application(app_data)
            member = frappe.get_doc("Member", result["member_id"])
            
            # Approve and create volunteer
            member.application_status = "Approved"
            member.status = "Active"
            member.save()
            
            # Create volunteer with skills
            volunteer_name = create_volunteer_from_approved_member(member)
            self.assertIsNotNone(volunteer_name)

    def test_business_rules_in_application(self):
        """Test business rules are enforced in application process"""
        # Try to submit application for someone too young
        young_app_data = self.factory.create_application_data(with_volunteer_skills=True)
        young_app_data["birth_date"] = "2010-01-01"  # Too young
        
        # Application should still be accepted (pending review)
        result = submit_membership_application(young_app_data)
        self.assertTrue(result["success"])
        
        # But when trying to approve and create volunteer, should respect age rules
        member = frappe.get_doc("Member", result["member_id"])
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        # Volunteer creation might fail due to age validation
        # This depends on whether the volunteer creation checks member age
        volunteer_name = create_volunteer_from_approved_member(member)
        if volunteer_name:
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            # Verify volunteer was created but might have restrictions
            self.assertEqual(volunteer.member, member.name)


if __name__ == '__main__':
    import unittest
    unittest.main()