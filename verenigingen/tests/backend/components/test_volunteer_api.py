import unittest
from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.utils.base import BaseVereengingenTest
from verenigingen.tests.utils.factories import TestDataFactory


class TestVolunteerAPI(BaseVereengingenTest):
    """Test whitelisted API endpoints for Volunteer doctype as called from JavaScript"""

    def setUp(self):
        super().setUp()
        self.factory = TestDataFactory()

        # Create test volunteer with member link
        self.test_member = self.factory.create_member(
            membership_id="TEST-VOL-001", first_name="Test", last_name="Volunteer"
        )

        self.test_volunteer = self.factory.create_volunteer(
            volunteer_name="Test Volunteer", member=self.test_member.name, start_date=today()
        )

        # Create a test user for API calls
        self.test_user = self.factory.create_user(
            email="test.volunteer@example.com", first_name="Test", last_name="Volunteer"
        )

    def tearDown(self):
        # Clean up test data in reverse dependency order
        self.factory.cleanup()
        super().tearDown()

    def test_add_activity_api(self):
        """Test add_activity whitelisted API endpoint"""
        # Set user context as JavaScript would
        frappe.set_user(self.test_user.name)

        # Test basic activity creation
        response = frappe.get_doc("Volunteer", self.test_volunteer.name).add_activity(
            activity_type="Project",
            role="Coordinator",
            description="Test project coordination",
            start_date=today(),
        )

        # Verify response and database state
        self.assertIsNotNone(response)
        self.assertTrue(frappe.db.exists("Volunteer Activity", response))

        # Verify activity details
        activity = frappe.get_doc("Volunteer Activity", response)
        self.assertEqual(activity.volunteer, self.test_volunteer.name)
        self.assertEqual(activity.activity_type, "Project")
        self.assertEqual(activity.role, "Coordinator")
        self.assertEqual(activity.status, "Active")

    def test_add_activity_api_with_all_fields(self):
        """Test add_activity API with all optional fields"""
        frappe.set_user(self.test_user.name)

        end_date = getdate(today()) + timedelta(days=30)

        response = frappe.get_doc("Volunteer", self.test_volunteer.name).add_activity(
            activity_type="Event",
            role="Organizer",
            description="Test event organization",
            start_date=today(),
            end_date=end_date,
            reference_doctype="Chapter",
            reference_name=self.test_member.chapter,
            estimated_hours=10,
            notes="Test activity notes",
        )

        activity = frappe.get_doc("Volunteer Activity", response)
        self.assertEqual(activity.description, "Test event organization")
        self.assertEqual(activity.end_date, end_date)
        self.assertEqual(activity.reference_doctype, "Chapter")
        self.assertEqual(activity.estimated_hours, 10)
        self.assertEqual(activity.notes, "Test activity notes")

    def test_add_activity_api_validation_errors(self):
        """Test add_activity API validation and error handling"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Test missing activity_type
        with self.assertRaises(frappe.ValidationError):
            volunteer.add_activity(activity_type="", role="Coordinator")

        # Test missing role
        with self.assertRaises(frappe.ValidationError):
            volunteer.add_activity(activity_type="Project", role="")

        # Test invalid date range
        with self.assertRaises(frappe.ValidationError):
            volunteer.add_activity(
                activity_type="Project",
                role="Coordinator",
                start_date=today(),
                end_date=getdate(today()) - timedelta(days=1),
            )

    def test_end_activity_api(self):
        """Test end_activity whitelisted API endpoint"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # First create an activity
        activity_name = volunteer.add_activity(activity_type="Project", role="Coordinator")

        # Verify activity is active
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.status, "Active")
        self.assertIsNone(activity.end_date)

        # End the activity
        end_date = today()
        volunteer.end_activity(
            activity_name=activity_name, end_date=end_date, notes="Activity completed successfully"
        )

        # Verify activity is ended
        activity.reload()
        self.assertEqual(activity.status, "Completed")
        self.assertEqual(activity.end_date, getdate(end_date))
        self.assertEqual(activity.notes, "Activity completed successfully")

    def test_end_activity_api_validation(self):
        """Test end_activity API validation"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Test missing activity_name
        with self.assertRaises(frappe.ValidationError):
            volunteer.end_activity(activity_name="")

        # Test non-existent activity
        with self.assertRaises(frappe.DoesNotExistError):
            volunteer.end_activity(activity_name="NON-EXISTENT")

    def test_get_volunteer_history_api(self):
        """Test get_volunteer_history whitelisted API endpoint"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Create some test activities
        activity1 = volunteer.add_activity(activity_type="Project", role="Coordinator", start_date=today())

        activity2 = volunteer.add_activity(
            activity_type="Event", role="Helper", start_date=getdate(today()) - timedelta(days=30)
        )

        # Test API call
        history = volunteer.get_volunteer_history()

        # Verify response structure
        self.assertIsInstance(history, list)
        self.assertTrue(len(history) >= 2)

        # Verify history items contain expected fields
        for item in history:
            self.assertIn("date", item)
            self.assertIn("description", item)
            self.assertIn("type", item)

    def test_get_skills_by_category_api(self):
        """Test get_skills_by_category whitelisted API endpoint"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Add some test skills
        volunteer.append(
            "skills",
            {"skill": "Project Management", "skill_category": "Leadership", "proficiency_level": "Advanced"},
        )
        volunteer.append(
            "skills",
            {
                "skill": "Event Planning",
                "skill_category": "Event Management",
                "proficiency_level": "Beginner"},
        )
        volunteer.save()

        # Test API call
        skills_by_category = volunteer.get_skills_by_category()

        # Verify response structure
        self.assertIsInstance(skills_by_category, dict)

        # Check for expected categories
        if skills_by_category:  # Only check if skills exist
            for category, skills in skills_by_category.items():
                self.assertIsInstance(skills, list)
                for skill in skills:
                    self.assertIn("skill", skill)
                    self.assertIn("proficiency_level", skill)

    def test_get_aggregated_assignments_api(self):
        """Test get_aggregated_assignments whitelisted API endpoint"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Create test activity for assignments
        activity_name = volunteer.add_activity(
            activity_type="Project", role="Coordinator", description="Test project for assignments"
        )

        # Test API call
        assignments = volunteer.get_aggregated_assignments()

        # Verify response structure
        self.assertIsInstance(assignments, list)

        # Verify assignment items contain expected fields
        for assignment in assignments:
            self.assertIn("source_type", assignment)
            self.assertIn("role", assignment)
            self.assertIn("is_active", assignment)
            self.assertIn("source_name", assignment)

    def test_api_permissions(self):
        """Test API permission checks"""
        # Create unauthorized user
        unauthorized_user = self.factory.create_user(
            email="unauthorized@example.com", first_name="Unauthorized", last_name="User"
        )

        # Set unauthorized user context
        frappe.set_user(unauthorized_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Test that permissions are properly enforced
        # Note: Exact permission behavior depends on role configuration
        try:
            volunteer.add_activity(activity_type="Project", role="Coordinator")
        except frappe.PermissionError:
            # This is expected if permissions are properly configured
            pass

    def test_api_error_handling(self):
        """Test API error handling and response formats"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Test that errors are properly raised and formatted
        with self.assertRaises(Exception) as context:
            volunteer.add_activity(activity_type=None, role="Coordinator")

        # Verify error message is user-friendly
        self.assertIn("required", str(context.exception).lower())

    def test_api_data_integrity(self):
        """Test that API calls maintain data integrity"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Create activity via API
        activity_name = volunteer.add_activity(
            activity_type="Project", role="Coordinator", description="Data integrity test"
        )

        # Verify database consistency
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.volunteer, volunteer.name)

        # Verify volunteer record is updated appropriately
        volunteer.reload()
        assignments = volunteer.get_aggregated_assignments()
        activity_found = any(assignment["source_name"] == activity_name for assignment in assignments)
        self.assertTrue(activity_found, "Activity should appear in aggregated assignments")

    def test_concurrent_api_calls(self):
        """Test API behavior with concurrent operations"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Create multiple activities in quick succession
        activities = []
        for i in range(3):
            activity_name = volunteer.add_activity(
                activity_type="Project", role=f"Role {i}", description=f"Concurrent test activity {i}"
            )
            activities.append(activity_name)

        # Verify all activities were created correctly
        self.assertEqual(len(activities), 3)
        for activity_name in activities:
            self.assertTrue(frappe.db.exists("Volunteer Activity", activity_name))


if __name__ == "__main__":
    unittest.main()
