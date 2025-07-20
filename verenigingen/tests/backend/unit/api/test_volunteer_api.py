# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Volunteer whitelisted API methods
Tests the API endpoints that JavaScript calls
"""


import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestVolunteerWhitelistMethods(VereningingenUnitTestCase):
    """Test Volunteer whitelisted API methods as called from JavaScript"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        try:
            cls.test_env = TestEnvironmentSetup.create_standard_test_environment()
        except Exception:
            cls.test_env = {"chapters": [], "teams": []}

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        try:
            self.builder.cleanup()
        except Exception as e:
            frappe.logger().error(f"Cleanup error in test: {str(e)}")
        super().tearDown()

    def _create_test_volunteer(self):
        """Helper to create a test volunteer"""
        test_data = self.builder.with_member(first_name="Test", last_name="Volunteer").build()

        member = test_data["member"]

        # Create volunteer from member
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "member": member.name,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "email": member.email,
                "volunteer_status": "Active"}
        )
        volunteer.insert(ignore_permissions=True)
        self.track_doc("Volunteer", volunteer.name)

        return volunteer

    def test_add_activity_whitelist(self):
        """Test add_activity method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # Test via API call (simulating JavaScript)
        result = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
            doc=volunteer.as_dict(),
            activity_type="Training",
            description="Test training session",
            date=today(),
            hours=2.5,
        )

        # Verify activity was added
        volunteer.reload()
        self.assertEqual(len(volunteer.activities), 1)
        activity = volunteer.activities[0]
        self.assertEqual(activity.activity_type, "Training")
        self.assertEqual(activity.description, "Test training session")
        self.assertEqual(activity.hours, 2.5)
        self.assertEqual(activity.status, "In Progress")

    def test_add_activity_validation(self):
        """Test add_activity validation"""
        volunteer = self._create_test_volunteer()

        # Test invalid hours
        with self.assertRaises(frappe.ValidationError):
            frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
                doc=volunteer.as_dict(),
                activity_type="Training",
                description="Invalid hours",
                date=today(),
                hours=-1,  # Invalid negative hours
            )

        # Test missing required fields
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
                doc=volunteer.as_dict(),
                activity_type="",  # Missing activity type
                description="Missing type",
                date=today(),
                hours=1,
            )

    def test_end_activity_whitelist(self):
        """Test end_activity method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # First add an activity
        frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
            doc=volunteer.as_dict(),
            activity_type="Event Support",
            description="Test event",
            date=today(),
            hours=3,
        )

        volunteer.reload()
        activity_name = volunteer.activities[0].name

        # End the activity
        result = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.end_activity",
            doc=volunteer.as_dict(),
            activity_name=activity_name,
            end_time=now_datetime(),
        )

        # Verify activity was ended
        volunteer.reload()
        activity = volunteer.activities[0]
        self.assertEqual(activity.status, "Completed")
        self.assertIsNotNone(activity.end_time)

    def test_get_volunteer_history_whitelist(self):
        """Test get_volunteer_history method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # Add multiple activities
        for i in range(3):
            frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
                doc=volunteer.as_dict(),
                activity_type="Training",
                description=f"Activity {i + 1}",
                date=add_days(today(), -i * 30),
                hours=2,
            )

        volunteer.reload()

        # Get history
        history = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.get_volunteer_history",
            doc=volunteer.as_dict(),
        )

        # Verify history
        self.assertEqual(len(history), 3)
        self.assertEqual(history["total_hours"], 6.0)
        self.assertEqual(len(history["activities"]), 3)

    def test_get_skills_by_category_whitelist(self):
        """Test get_skills_by_category method"""
        volunteer = self._create_test_volunteer()

        # Add skills
        volunteer.append(
            "skills",
            {
                "skill_name": "Python Programming",
                "skill_category": "Technical",
                "proficiency_level": "Expert"},
        )
        volunteer.append(
            "skills",
            {
                "skill_name": "Event Planning",
                "skill_category": "Administrative",
                "proficiency_level": "Intermediate"},
        )
        volunteer.save(ignore_permissions=True)

        # Get skills by category
        skills = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.get_skills_by_category",
            doc=volunteer.as_dict(),
        )

        # Verify categorization
        self.assertIn("Technical", skills)
        self.assertIn("Administrative", skills)
        self.assertEqual(len(skills["Technical"]), 1)
        self.assertEqual(skills["Technical"][0]["skill_name"], "Python Programming")

    def test_calculate_total_hours_whitelist(self):
        """Test calculate_total_hours method"""
        volunteer = self._create_test_volunteer()

        # Add activities with different statuses
        activities = [
            ("Completed", 5.0),
            ("Completed", 3.5),
            ("In Progress", 2.0),  # Should not be counted
            ("Cancelled", 1.0),  # Should not be counted
        ]

        for status, hours in activities:
            activity = {
                "activity_type": "Training",
                "description": f"Activity {status}",
                "date": today(),
                "hours": hours,
                "status": status}
            volunteer.append("activities", activity)

        volunteer.save(ignore_permissions=True)

        # Calculate total hours
        total_hours = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.calculate_total_hours",
            doc=volunteer.as_dict(),
        )

        # Should only count completed activities
        self.assertEqual(total_hours, 8.5)

    def test_create_minimal_employee_whitelist(self):
        """Test create_minimal_employee method"""
        volunteer = self._create_test_volunteer()

        # Create minimal employee
        employee_name = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.create_minimal_employee",
            doc=volunteer.as_dict(),
        )

        # Verify employee was created
        self.assertTrue(employee_name)
        employee = frappe.get_doc("Employee", employee_name)
        self.assertEqual(employee.first_name, volunteer.first_name)
        self.assertEqual(employee.last_name, volunteer.last_name)
        self.assertEqual(employee.personal_email, volunteer.email)

        # Test idempotency - calling again should return same employee
        employee_name_2 = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.create_minimal_employee",
            doc=volunteer.as_dict(),
        )
        self.assertEqual(employee_name, employee_name_2)

    def test_create_volunteer_from_member_whitelist(self):
        """Test create_volunteer_from_member module function"""
        # Create member
        test_data = self.builder.with_member(first_name="New", last_name="Volunteer").build()

        member = test_data["member"]

        # Create volunteer from member via API
        volunteer_name = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member",
            member_name=member.name,
        )

        # Verify volunteer was created
        self.assertTrue(volunteer_name)
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(volunteer.first_name, member.first_name)
        self.assertEqual(volunteer.last_name, member.last_name)
        self.assertEqual(volunteer.email, member.email)

        # Verify member was updated
        member.reload()
        self.assertEqual(member.volunteer, volunteer_name)

    def test_sync_chapter_board_members_whitelist(self):
        """Test sync_chapter_board_members function"""
        # Create chapter with board members
        chapter = frappe.get_doc(
            {"doctype": "Chapter", "chapter_name": "Test Sync Chapter", "chapter_code": "TSC"}
        )

        # Add board members
        for i in range(2):
            member_data = self.builder.with_member(first_name=f"Board{i}", last_name="Member").build()

            chapter.append(
                "board_members",
                {
                    "member": member_data["member"].name,
                    "role": "Board Member",
                    "start_date": today(),
                    "status": "Active"},
            )

        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)

        # Sync board members
        result = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.sync_chapter_board_members",
            chapter_name=chapter.name,
        )

        # Verify volunteers were created
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["updated"], 0)

        # Verify volunteers exist
        for board_member in chapter.board_members:
            member = frappe.get_doc("Member", board_member.member)
            self.assertTrue(member.volunteer)
            volunteer = frappe.get_doc("Volunteer", member.volunteer)
            self.assertEqual(volunteer.volunteer_status, "Active")

    def test_get_aggregated_assignments_whitelist(self):
        """Test get_aggregated_assignments method"""
        volunteer = self._create_test_volunteer()

        # Add team assignments
        volunteer.append(
            "team_assignments",
            {
                "team": "IT Support",
                "role": "Developer",
                "start_date": add_days(today(), -180),
                "status": "Active"},
        )
        volunteer.append(
            "team_assignments",
            {
                "team": "Events",
                "role": "Coordinator",
                "start_date": add_days(today(), -90),
                "end_date": add_days(today(), -30),
                "status": "Completed"},
        )
        volunteer.save(ignore_permissions=True)

        # Get aggregated assignments
        assignments = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.get_aggregated_assignments",
            doc=volunteer.as_dict(),
        )

        # Verify aggregation
        self.assertIn("active_teams", assignments)
        self.assertIn("past_teams", assignments)
        self.assertEqual(len(assignments["active_teams"]), 1)
        self.assertEqual(len(assignments["past_teams"]), 1)
        self.assertEqual(assignments["active_teams"][0]["team"], "IT Support")

    def test_permission_checks(self):
        """Test permission checks on whitelisted methods"""
        volunteer = self._create_test_volunteer()

        # Create a non-admin user
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": "test.volunteer@example.com",
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}]}
        )
        test_user.insert(ignore_permissions=True)
        self.track_doc("User", test_user.name)

        # Test as non-admin user
        with self.as_user("test.volunteer@example.com"):
            # Should not be able to add activity without proper permissions
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
                    doc=volunteer.as_dict(),
                    activity_type="Training",
                    description="Unauthorized",
                    date=today(),
                    hours=1,
                )

    def test_error_handling(self):
        """Test error handling in whitelisted methods"""
        volunteer = self._create_test_volunteer()

        # Test ending non-existent activity
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.end_activity",
                doc=volunteer.as_dict(),
                activity_name="non-existent-activity",
                end_time=now_datetime(),
            )

        # Test creating volunteer from non-existent member
        with self.assertRaises(Exception):
            frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.create_volunteer_from_member",
                member_name="non-existent-member",
            )

    def test_data_integrity(self):
        """Test data integrity in volunteer operations"""
        volunteer = self._create_test_volunteer()

        # Add multiple activities concurrently
        for i in range(5):
            result = frappe.call(
                "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.add_activity",
                doc=volunteer.as_dict(),
                activity_type="Training",
                description=f"Concurrent activity {i}",
                date=today(),
                hours=1,
            )

        # Verify all activities were added
        volunteer.reload()
        self.assertEqual(len(volunteer.activities), 5)

        # Verify total hours calculation is correct
        total_hours = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.calculate_total_hours",
            doc=volunteer.as_dict(),
        )
        # Since activities are "In Progress" by default, total should be 0
        self.assertEqual(total_hours, 0)

        # Complete all activities
        for activity in volunteer.activities:
            activity.status = "Completed"
        volunteer.save(ignore_permissions=True)

        # Recalculate total hours
        total_hours = frappe.call(
            "verenigingen.verenigingen.doctype.volunteer.volunteer.Volunteer.calculate_total_hours",
            doc=volunteer.as_dict(),
        )
        self.assertEqual(total_hours, 5.0)
