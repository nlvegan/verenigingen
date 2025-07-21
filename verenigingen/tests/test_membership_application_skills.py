"""
Unit tests for membership application skills integration
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


class TestMembershipApplicationSkills(unittest.TestCase):
    """Test skills integration in membership application workflow"""

    def setUp(self):
        """Set up test data"""
        # Create test data first
        self.test_email = "test_skills_member@example.com"
        
        # Clean up any existing test data
        self.cleanup_test_data()
        self.test_application_data = {
            "first_name": "Skills",
            "last_name": "Tester",
            "email": self.test_email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Test City", 
            "country": "Netherlands",
            "postal_code": "1234AB",
            "interested_in_volunteering": True,
            "volunteer_availability": "Monthly",
            "volunteer_experience_level": "Intermediate",
            "volunteer_areas": ["events", "communications"],
            "volunteer_skills": [
                "Technical|Web Development",
                "Technical|Graphic Design", 
                "Communication|Writing",
                "Leadership|Team Leadership",
                "Financial|Fundraising"
            ],
            "volunteer_skill_level": "4",
            "volunteer_availability_time": "Weekends and evenings",
            "volunteer_comments": "Excited to contribute to the organization!"
        }

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def cleanup_test_data(self):
        """Remove test data"""
        # Delete test members
        test_members = frappe.get_all("Member", filters={"email": self.test_email})
        for member in test_members:
            # Delete linked volunteers first
            volunteers = frappe.get_all("Volunteer", filters={"member": member.name})
            for volunteer in volunteers:
                frappe.delete_doc("Volunteer", volunteer.name, force=True)
            
            # Delete comments
            comments = frappe.get_all("Comment", filters={
                "reference_doctype": "Member",
                "reference_name": member.name
            })
            for comment in comments:
                frappe.delete_doc("Comment", comment.name, force=True)
            
            # Delete member
            frappe.delete_doc("Member", member.name, force=True)
        
        frappe.db.commit()

    def test_submit_application_with_volunteer_interest(self):
        """Test submitting membership application with volunteer interest"""
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
        self.assertIn("Technical: Web Development, Graphic Design", member.notes)
        self.assertIn("Communication: Writing", member.notes)
        self.assertIn("Leadership: Team Leadership", member.notes)
        self.assertIn("Financial: Fundraising", member.notes)
        self.assertIn("Overall Skill Level: 4", member.notes)
        self.assertIn("Availability: Monthly", member.notes)

    def test_submit_application_without_volunteer_interest(self):
        """Test submitting application without volunteer interest"""
        data = self.test_application_data.copy()
        data["interested_in_volunteering"] = False
        del data["volunteer_skills"]
        
        result = submit_membership_application(data)
        
        self.assertTrue(result["success"])
        member = frappe.get_doc("Member", result["member_id"])
        
        # Verify no volunteer interest captured
        self.assertNotIn("VOLUNTEER_INTEREST_FLAG: True", member.notes or "")
        self.assertNotIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes or "")

    def test_create_volunteer_application_data(self):
        """Test creating volunteer application data structure"""
        # Create a test member first
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "Member",
            "email": "test_vol_data@example.com",
            "birth_date": "1990-01-01",
            "status": "Pending"
        })
        member.insert()
        
        volunteer_info = create_volunteer_application_data(member, self.test_application_data)
        
        # Verify volunteer info structure
        self.assertTrue(volunteer_info["interested_in_volunteering"])
        self.assertEqual(volunteer_info["volunteer_availability"], "Monthly")
        self.assertEqual(volunteer_info["volunteer_experience_level"], "Intermediate")
        self.assertEqual(len(volunteer_info["volunteer_skills"]), 5)
        
        # Verify member was updated
        member.reload()
        self.assertIn("VOLUNTEER_INTEREST_FLAG: True", member.notes)
        self.assertIn("VOLUNTEER INTEREST APPLICATION DATA:", member.notes)
        
        # Clean up
        frappe.delete_doc("Member", member.name, force=True)

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
        
        # Verify skills were added
        self.assertGreater(len(volunteer.skills_and_qualifications), 0)
        
        # Check specific skills
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Web Development", skill_names)
        self.assertIn("Graphic Design", skill_names)
        self.assertIn("Writing", skill_names)
        self.assertIn("Team Leadership", skill_names)
        self.assertIn("Fundraising", skill_names)
        
        # Verify skill categories
        technical_skills = [s for s in volunteer.skills_and_qualifications if s.skill_category == "Technical"]
        self.assertEqual(len(technical_skills), 2)

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
        
        # Try to create again
        volunteer_name2 = create_volunteer_from_approved_member(member)
        
        # Should return existing volunteer name
        self.assertEqual(volunteer_name1, volunteer_name2)
        
        # Verify only one volunteer exists
        volunteers = frappe.get_all("Volunteer", filters={"member": member.name})
        self.assertEqual(len(volunteers), 1)

    def test_add_skills_to_volunteer(self):
        """Test adding skills to volunteer record"""
        # Create volunteer
        volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": "Test Volunteer",
            "email": "test_vol_skills@example.com",
            "status": "Active"
        })
        volunteer.insert()
        
        # Test data
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
        
        # Clean up
        frappe.delete_doc("Volunteer", volunteer.name, force=True)

    def test_full_application_to_volunteer_workflow(self):
        """Test complete workflow from application to active volunteer"""
        # 1. Submit application with volunteer interest
        result = submit_membership_application(self.test_application_data)
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
        self.assertEqual(volunteer.email, self.test_email)
        
        # 6. Verify skills were transferred
        self.assertGreater(len(volunteer.skills_and_qualifications), 0)
        skill_names = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        self.assertIn("Web Development", skill_names)
        self.assertIn("Writing", skill_names)
        self.assertIn("Team Leadership", skill_names)

    def test_application_validation_required_fields(self):
        """Test application validation for required fields"""
        # Test missing required fields
        invalid_data = {
            "email": self.test_email,
            "interested_in_volunteering": True
            # Missing first_name, last_name, birth_date
        }
        
        with self.assertRaises(Exception):
            submit_membership_application(invalid_data)

    def test_application_duplicate_email_prevention(self):
        """Test prevention of duplicate email applications"""
        # Submit first application
        result1 = submit_membership_application(self.test_application_data)
        self.assertTrue(result1["success"])
        
        # Try to submit second application with same email
        with self.assertRaises(Exception):
            submit_membership_application(self.test_application_data)

    def test_volunteer_skills_data_integrity(self):
        """Test that volunteer skills data maintains integrity"""
        # Submit application
        result = submit_membership_application(self.test_application_data)
        member = frappe.get_doc("Member", result["member_id"])
        
        # Approve and create volunteer
        member.application_status = "Approved"
        member.status = "Active"
        member.save()
        
        volunteer_name = create_volunteer_from_approved_member(member)
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        
        # Verify all skills have required fields
        for skill in volunteer.skills_and_qualifications:
            self.assertIsNotNone(skill.skill_category)
            self.assertIsNotNone(skill.volunteer_skill)
            self.assertIsNotNone(skill.proficiency_level)
            self.assertIn(skill.skill_category, ["Technical", "Communication", "Leadership", "Financial"])
            
        # Verify skills match application data
        expected_skills = ["Web Development", "Graphic Design", "Writing", "Team Leadership", "Fundraising"]
        actual_skills = [skill.volunteer_skill for skill in volunteer.skills_and_qualifications]
        
        for expected_skill in expected_skills:
            self.assertIn(expected_skill, actual_skills)


if __name__ == '__main__':
    unittest.main()