"""
Unit tests for membership application skills integration using SecureTestDataFactory
Demonstrates proper use of schema-validated, deterministic test data
"""

import unittest
import frappe
from frappe.utils import today, now_datetime

from verenigingen.verenigingen.web_form.membership_application import (
    submit_membership_application,
    create_volunteer_application_data,
    create_volunteer_from_approved_member,
    parse_volunteer_data_from_notes,
    add_skills_to_volunteer,
    get_proficiency_label,
    approve_membership_application
)

from verenigingen.tests.fixtures.secure_test_data_factory import (
    SecureTestContext,
    with_secure_test_data
)
from verenigingen.tests.fixtures.field_validator import validate_field


class TestMembershipApplicationSkillsSecure(unittest.TestCase):
    """Test skills integration in membership application workflow using secure factory"""

    @with_secure_test_data(seed=12345)
    def test_submit_application_with_volunteer_interest(self, factory):
        """Test submitting membership application with volunteer interest"""
        # Create deterministic test data
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        
        result = submit_membership_application(test_application_data)
        
        self.assertTrue(result["success"])
        self.assertIn("member_id", result)
        
        # Verify member was created
        member = frappe.get_doc("Member", result["member_id"])
        self.assertEqual(member.email, test_application_data["email"])
        self.assertEqual(member.status, "Pending")
        
        # Verify volunteer interest was captured
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)
        
        # Verify volunteer data in notes
        self.assertIn("Technical: Web Development, Graphic Design", member.notes)
        self.assertIn("Communication: Writing", member.notes)
        self.assertIn("Leadership: Team Leadership", member.notes)
        self.assertIn("Financial: Fundraising", member.notes)

    @with_secure_test_data(seed=12346)
    def test_submit_application_without_volunteer_interest(self, factory):
        """Test submitting application without volunteer interest"""
        # Create application data without volunteer skills with unique email
        data = factory.create_application_data(with_volunteer_skills=False)
        # Make email unique to avoid application_id collision
        data["email"] = f"unique_{factory.get_next_sequence('unique_email')}@test.example"
        
        result = submit_membership_application(data)
        
        self.assertTrue(result["success"])
        member = frappe.get_doc("Member", result["member_id"])
        
        # Verify no volunteer interest captured
        self.assertNotIn("VOLUNTEER_INTEREST_FLAG: True", member.notes or "")
        self.assertNotIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes or "")

    @with_secure_test_data(seed=12347)
    def test_create_volunteer_application_data(self, factory):
        """Test creating volunteer application data structure"""
        # Create test member using secure factory
        member = factory.create_member(
            first_name="Test", 
            last_name="Verenigingen Volunteer",
            email="test_vol_data@secure.test"
        )
        
        # Create application data
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        
        volunteer_info = create_volunteer_application_data(member, test_application_data)
        
        # Verify volunteer info structure
        self.assertTrue(volunteer_info["interested_in_volunteering"])
        self.assertEqual(volunteer_info["volunteer_availability"], "Monthly")  # Deterministic (seq=1, 1%3=1, index 1="Monthly")
        self.assertEqual(volunteer_info["volunteer_experience_level"], "Intermediate")  # Deterministic (seq=1, 1%3=1, index 1="Intermediate")
        self.assertEqual(len(volunteer_info["volunteer_skills"]), 5)  # Deterministic count (seq=1, (1%3)+4=5)
        
        # Verify member was updated
        member.reload()
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)

    @with_secure_test_data(seed=12348)
    def test_parse_volunteer_data_from_notes(self, factory):
        """Test parsing volunteer data from member notes"""
        # Create test notes with known structure
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

    @with_secure_test_data(seed=12349)
    def test_create_volunteer_from_approved_member(self, factory):
        """Test creating volunteer record from approved member"""
        # Submit application first using secure factory
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(test_application_data)
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
        
        # Verify skills were added (deterministic count - 5 skills from application)
        self.assertEqual(len(volunteer.skills_and_qualifications), 5)
        
        # Check specific skills (deterministic from seed)
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Web Development", skill_names)
        self.assertIn("Graphic Design", skill_names)
        self.assertIn("Writing", skill_names)

    @with_secure_test_data(seed=12350)
    def test_create_volunteer_duplicate_prevention(self, factory):
        """Test that duplicate volunteer records are not created"""
        # Submit application and create volunteer
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(test_application_data)
        member = frappe.get_doc("Member", result["member_id"])
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        # Create volunteer first time
        volunteer_name1 = create_volunteer_from_approved_member(member)
        
        # Try to create again
        volunteer_name2 = create_volunteer_from_approved_member(member)
        
        # Should return existing volunteer name
        self.assertEqual(volunteer_name1, volunteer_name2)
        
        # Verify only one volunteer exists
        volunteers = frappe.get_all("Volunteer", filters={"member": member.name})
        self.assertEqual(len(volunteers), 1)

    @with_secure_test_data(seed=12351)
    def test_add_skills_to_volunteer(self, factory):
        """Test adding skills to volunteer record"""
        # Create volunteer using secure factory
        member = factory.create_member()
        volunteer = factory.create_volunteer(member.name)
        
        # Test data with validated fields
        volunteer_data = {
            "skills_by_category": {
                "Technical": ["Python", "JavaScript"],
                "Communication": ["Writing", "Public Speaking"]
            },
            "skill_level": "4"
        }
        
        # Add skills
        add_skills_to_volunteer(volunteer, volunteer_data)
        
        # Verify skills were added
        volunteer.reload()
        self.assertEqual(len(volunteer.skills_and_qualifications), 4)
        
        # Check specific skills
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Python", skill_names)
        self.assertIn("JavaScript", skill_names)
        self.assertIn("Writing", skill_names)
        self.assertIn("Public Speaking", skill_names)
        
        # Check proficiency levels
        for skill in volunteer.skills_and_qualifications:
            self.assertIn("4 - Advanced", skill.proficiency_level)

    @with_secure_test_data(seed=12352)
    def test_full_application_to_volunteer_workflow(self, factory):
        """Test complete workflow from application to active volunteer"""
        # 1. Submit application with volunteer interest
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        result = submit_membership_application(test_application_data)
        self.assertTrue(result["success"])
        
        member_id = result["member_id"]
        member = frappe.get_doc("Member", member_id)
        
        # 2. Verify application data captured
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)
        
        # 3. Approve membership application
        approve_result = approve_membership_application(member_id, create_invoice=False)
        self.assertTrue(approve_result["success"])
        
        # 4. Verify member is approved
        member.reload()
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")
        
        # 5. Verify volunteer record was created automatically
        volunteers = frappe.get_all("Volunteer", filters={"member": member_id})
        self.assertEqual(len(volunteers), 1)
        
        volunteer = frappe.get_doc("Volunteer", volunteers[0].name)
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.email, test_application_data["email"])
        
        # 6. Verify skills were transferred (deterministic count)
        self.assertEqual(len(volunteer.skills_and_qualifications), 4)  # First application gets 4 skills ((1%3)+4=4)
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Web Development", skill_names)
        self.assertIn("Graphic Design", skill_names)
        self.assertIn("Writing", skill_names)
        self.assertIn("Team Leadership", skill_names)

    @with_secure_test_data(seed=12353)
    def test_application_validation_required_fields(self, factory):
        """Test application validation for required fields"""
        # Test missing required fields - validate fields exist first
        validate_field("Member", "first_name")
        validate_field("Member", "last_name") 
        validate_field("Member", "email")
        validate_field("Member", "birth_date")
        
        invalid_data = {
            "email": "test@secure.test",
            "interested_in_volunteering": True
            # Missing required fields
        }
        
        with self.assertRaises(Exception):
            submit_membership_application(invalid_data)

    @with_secure_test_data(seed=12354)
    def test_application_duplicate_email_prevention(self, factory):
        """Test prevention of duplicate email applications"""
        # Submit first application
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        result1 = submit_membership_application(test_application_data)
        self.assertTrue(result1["success"])
        
        # Try to submit second application with same email
        with self.assertRaises(Exception):
            submit_membership_application(test_application_data)

    @with_secure_test_data(seed=12355)
    def test_volunteer_skills_data_integrity(self, factory):
        """Test that volunteer skills data maintains integrity"""
        # Submit application with unique email
        test_application_data = factory.create_application_data(with_volunteer_skills=True)
        test_application_data["email"] = f"integrity_{factory.get_next_sequence('integrity_email')}@test.example"
        result = submit_membership_application(test_application_data)
        member = frappe.get_doc("Member", result["member_id"])
        
        # Approve and create volunteer
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        volunteer_name = create_volunteer_from_approved_member(member)
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        
        # Verify all skills have required fields
        for skill in volunteer.skills_and_qualifications:
            # Validate these fields exist in schema
            validate_field("Volunteer Skill", "skill_category")
            validate_field("Volunteer Skill", "volunteer_skill")
            validate_field("Volunteer Skill", "proficiency_level")
            
            self.assertIsNotNone(skill.skill_category)
            self.assertIsNotNone(skill.volunteer_skill)
            self.assertIsNotNone(skill.proficiency_level)
            self.assertIn(skill.skill_category, ["Technical", "Communication", "Leadership"])
            
        # Verify skills match application data (deterministic)
        expected_skills = ["Web Development", "Graphic Design", "Writing", "Team Leadership"]
        actual_skills = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        
        for expected_skill in expected_skills:
            self.assertIn(expected_skill, actual_skills)

    def test_get_proficiency_label(self):
        """Test proficiency label conversion"""
        self.assertEqual(get_proficiency_label("1"), "Beginner")
        self.assertEqual(get_proficiency_label("2"), "Basic")
        self.assertEqual(get_proficiency_label("3"), "Intermediate")
        self.assertEqual(get_proficiency_label("4"), "Advanced")
        self.assertEqual(get_proficiency_label("5"), "Expert")
        self.assertEqual(get_proficiency_label("unknown"), "Intermediate")

    def test_parse_volunteer_data_no_volunteer_section(self):
        """Test parsing notes without volunteer section"""
        notes = "Just some regular notes without volunteer data"
        
        data = parse_volunteer_data_from_notes(notes)
        
        self.assertIsNone(data)


if __name__ == '__main__':
    unittest.main()