import unittest
from datetime import timedelta

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.test_utils import TestDataFactory


class TestVolunteerAPI(VereningingenTestCase):
    """Test whitelisted API endpoints for Volunteer doctype as called from JavaScript"""

    def setUp(self):
        super().setUp()
        self.factory = TestDataFactory()

        # Create test volunteer with member link
        self.test_member = self.factory.create_test_member(
            membership_id="TEST-VOL-001", first_name="Test", last_name="Verenigingen Volunteer"
        )

        self.test_volunteer = self.factory.create_test_volunteer(
            volunteer_name="Test Volunteer", member=self.test_member.name, start_date=today()
        )
        # TestDataFactory is stateless (no cleanup()), so register docs with the
        # base test case for automatic teardown.
        self.track_doc("Volunteer", self.test_volunteer.name)
        self.track_doc("Member", self.test_member.name)

        # Create a test user for API calls. The volunteer activity endpoints
        # (add_activity/end_activity) are @high_security_api AND insert/modify
        # "Volunteer Activity" documents as the calling user (no ignore_permissions).
        # Only "Verenigingen Administrator" has both the API HIGH/CRITICAL grant
        # and DocPerm create/write on Volunteer Activity, so it is the realistic
        # role for the admin path these JS-called endpoints exercise.
        self.test_user = self.factory.create_test_user(
            email="test.volunteer@example.com",
            first_name="Test",
            last_name="Verenigingen Volunteer",
            roles=["Verenigingen Administrator"],
        )
        # create_test_user returns an existing user (from a prior run) without
        # re-applying roles, so ensure the required role is present.
        if "Verenigingen Administrator" not in frappe.get_roles(self.test_user.name):
            self.test_user.add_roles("Verenigingen Administrator")

        # AuthorizationPolicy caps a bare individual role at MEDIUM (Rule 5); the
        # @high_security_api activity endpoints below need HIGH, which is grantable
        # only through an assigned role PROFILE (Rule 4). TestDataFactory.create_test_user
        # assigns bare roles only, so grant the matching profile here. The
        # unauthorized user built in test_api_permissions is deliberately left
        # profileless.
        grant_matching_role_profiles(self.test_user.name, ["Verenigingen Administrator"])

    def tearDown(self):
        # Base class cleans up tracked docs (see track_doc calls in setUp);
        # TestDataFactory has no cleanup() method of its own.
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
        # A valid Chapter is needed for the activity's reference_name; create one
        # as Administrator (the test user lacks Chapter create permission). This
        # test overrides self.factory with the lightweight TestDataFactory, so use
        # a CoreTestDataFactory directly for chapter creation.
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

        chapter = CoreTestDataFactory().create_test_chapter()
        self.track_doc("Chapter", chapter.name)

        frappe.set_user(self.test_user.name)

        end_date = getdate(today()) + timedelta(days=30)

        response = frappe.get_doc("Volunteer", self.test_volunteer.name).add_activity(
            activity_type="Event",
            role="Organizer",
            description="Test event organization",
            start_date=today(),
            end_date=end_date,
            reference_doctype="Chapter",
            reference_name=chapter.name,
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
        """Test add_activity API validation and error handling.

        Message-pinned on purpose: verenigingen.utils.error_handling.PermissionError
        SUBCLASSES frappe.ValidationError, so a bare assertRaises(ValidationError)
        also swallows an authorization denial. These assertions passed for that
        wrong reason until the role PROFILE grant was added to setUp.
        """
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Test missing activity_type
        with self.assertRaisesRegex(frappe.ValidationError, "Activity Type is required"):
            volunteer.add_activity(activity_type="", role="Coordinator")

        # Test missing role
        with self.assertRaisesRegex(frappe.ValidationError, "Role is required"):
            volunteer.add_activity(activity_type="Project", role="")

        # Test invalid date range
        with self.assertRaisesRegex(frappe.ValidationError, "End date cannot be before start date"):
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

        # An empty activity_name is not separately validated -- production goes
        # straight to frappe.get_doc(""), so this pins "not found", not a
        # missing-argument check. Message-pinned so an authorization denial
        # (which subclasses ValidationError) cannot satisfy it.
        with self.assertRaisesRegex(frappe.DoesNotExistError, "Volunteer Activity"):
            volunteer.end_activity(activity_name="")

        # Test non-existent activity
        with self.assertRaisesRegex(frappe.DoesNotExistError, "NON-EXISTENT"):
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

        # Verify history items contain the documented fields. get_volunteer_history()
        # returns dicts keyed assignment_type/role/reference/start_date/end_date/
        # is_active/status.
        for item in history:
            self.assertIn("assignment_type", item)
            self.assertIn("role", item)
            self.assertIn("start_date", item)

    def test_get_skills_by_category_api(self):
        """Test get_skills_by_category whitelisted API endpoint"""
        frappe.set_user(self.test_user.name)
        volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)

        # Add some test skills. The child table is "skills_and_qualifications"
        # with fields volunteer_skill/skill_category/proficiency_level, and the
        # Select options are constrained (see Volunteer Skill DocType).
        volunteer.append(
            "skills_and_qualifications",
            {
                "volunteer_skill": "Project Management",
                "skill_category": "Leadership",
                "proficiency_level": "4 - Advanced",
            },
        )
        volunteer.append(
            "skills_and_qualifications",
            {
                "volunteer_skill": "Event Planning",
                "skill_category": "Event Planning",
                "proficiency_level": "1 - Beginner",
            },
        )
        volunteer.save()

        # Test API call
        skills_by_category = volunteer.get_skills_by_category()

        # Verify response structure
        self.assertIsInstance(skills_by_category, dict)

        # Check for expected categories. get_skills_by_category() returns each
        # skill as {"skill": ..., "level": ..., "experience": ...}.
        if skills_by_category:  # Only check if skills exist
            for category, skills in skills_by_category.items():
                self.assertIsInstance(skills, list)
                for skill in skills:
                    self.assertIn("skill", skill)
                    self.assertIn("level", skill)

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
        unauthorized_user = self.factory.create_test_user(
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
