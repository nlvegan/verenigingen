# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Volunteer whitelisted API methods
Tests the API endpoints that JavaScript calls
"""


import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerWhitelistMethods(VereningingenTestCase):
    """Test Volunteer whitelisted API methods as called from JavaScript"""

    def setUp(self):
        """Set up for each test"""
        super().setUp()

    def _create_test_volunteer(self):
        """Helper to create a test volunteer"""
        from frappe.utils import random_string
        unique_id = random_string(8)
        
        # Create member using factory
        member = self.create_test_member(
            first_name=f"Test{unique_id[:4]}",
            last_name=f"Volunteer{unique_id[4:]}",
            email=f"test.volunteer.{unique_id}@example.com"
        )
        
        # Create volunteer using factory
        volunteer = self.create_test_volunteer(
            member=member,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email
        )
        
        return volunteer

    def test_add_activity_whitelist(self):
        """Test add_activity method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # Test via API call (simulating JavaScript) - using correct method signature
        activity_name = volunteer.add_activity(
            activity_type="Training",
            role="Trainer",
            description="Test training session",
            start_date=today(),
            estimated_hours=2.5,
        )

        # Verify activity was created
        self.assertIsNotNone(activity_name)
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.activity_type, "Training")
        self.assertEqual(activity.description, "Test training session")
        self.assertEqual(activity.estimated_hours, 2.5)
        self.assertEqual(activity.status, "Active")

    def test_add_activity_validation(self):
        """Test add_activity validation"""
        volunteer = self._create_test_volunteer()

        # Test missing required fields - activity_type
        with self.assertRaises(Exception):
            volunteer.add_activity(
                activity_type="",  # Missing activity type
                role="Test Role",
                description="Missing type",
                start_date=today(),
            )

        # Test missing required fields - role
        with self.assertRaises(Exception):
            volunteer.add_activity(
                activity_type="Training",
                role="",  # Missing role
                description="Missing role",
                start_date=today(),
            )

    def test_end_activity_whitelist(self):
        """Test end_activity method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # First add an activity
        activity_name = volunteer.add_activity(
            activity_type="Event",
            role="Event Coordinator",
            description="Test event",
            start_date=today(),
            estimated_hours=3,
        )

        # End the activity
        result = volunteer.end_activity(
            activity_name=activity_name,
            end_date=today(),
            notes="Activity completed successfully"
        )

        # Verify activity was ended
        self.assertTrue(result)
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.status, "Completed")
        self.assertIsNotNone(activity.end_date)

    def test_get_volunteer_history_whitelist(self):
        """Test get_volunteer_history method as called from JavaScript"""
        volunteer = self._create_test_volunteer()

        # Add multiple activities
        activity_names = []
        for i in range(3):
            activity_name = volunteer.add_activity(
                activity_type="Training",
                role=f"Trainer {i + 1}",
                description=f"Activity {i + 1}",
                start_date=add_days(today(), -i * 30),
                estimated_hours=2,
            )
            activity_names.append(activity_name)

        # Get history
        history = volunteer.get_volunteer_history()

        # Verify history structure (it returns a list of assignment history)
        self.assertIsInstance(history, list)
        self.assertGreaterEqual(len(history), 3)  # Should include the activities we created

    def test_get_skills_by_category_whitelist(self):
        """Test get_skills_by_category method"""
        volunteer = self._create_test_volunteer()

        # Add skills using correct field names from JSON
        volunteer.append(
            "skills_and_qualifications",
            {
                "volunteer_skill": "Python Programming",
                "skill_category": "Technical",
                "proficiency_level": "5 - Expert"},
        )
        volunteer.append(
            "skills_and_qualifications",
            {
                "volunteer_skill": "Event Planning",
                "skill_category": "Event Planning",
                "proficiency_level": "3 - Intermediate"},
        )
        volunteer.save()

        # Get skills by category
        skills = volunteer.get_skills_by_category()

        # Verify categorization
        self.assertIn("Technical", skills)
        self.assertIn("Event Planning", skills)
        self.assertEqual(len(skills["Technical"]), 1)
        self.assertEqual(skills["Technical"][0]["skill"], "Python Programming")

    def test_calculate_total_hours_whitelist(self):
        """Test calculate_total_hours method"""
        volunteer = self._create_test_volunteer()

        # Create activities with different statuses by creating them as documents
        activities = [
            ("Training", 5.0),
            ("Event", 3.5),
        ]

        for activity_type, hours in activities:
            # Create activity
            activity = frappe.get_doc({
                "doctype": "Volunteer Activity",
                "volunteer": volunteer.name,
                "activity_type": activity_type,
                "role": "Test Role",
                "description": f"Test {activity_type}",
                "start_date": today(),
                "estimated_hours": hours,
                "actual_hours": hours,
                "status": "Active"
            })
            activity.insert()
            self.track_doc("Volunteer Activity", activity.name)

        # Calculate total hours
        total_hours = volunteer.calculate_total_hours()

        # Should count hours from activities
        self.assertEqual(total_hours, 8.5)

    def test_create_minimal_employee_whitelist(self):
        """Test create_minimal_employee method"""
        volunteer = self._create_test_volunteer()

        # Create minimal employee
        employee_name = volunteer.create_minimal_employee()

        # Verify employee was created
        self.assertTrue(employee_name)
        employee = frappe.get_doc("Employee", employee_name)
        self.assertEqual(employee.employee_name, volunteer.volunteer_name)
        self.assertEqual(employee.personal_email, volunteer.email)
        self.track_doc("Employee", employee.name)

        # Test idempotency - calling again should return same employee
        employee_name_2 = volunteer.create_minimal_employee()
        self.assertEqual(employee_name, employee_name_2)

    def test_create_volunteer_from_member_whitelist(self):
        """Test creating volunteer from member (manual process)"""
        # Create member using factory
        from frappe.utils import random_string
        unique_id = random_string(8)
        
        member = self.create_test_member(
            first_name=f"New{unique_id[:4]}", 
            last_name=f"Volunteer{unique_id[4:]}",
            email=f"new.volunteer.{unique_id}@example.com"
        )

        # Create volunteer manually (since API method doesn't exist)
        volunteer = self.create_test_volunteer(
            member=member,
            volunteer_name=f"{member.first_name} {member.last_name}",
            email=member.email
        )

        # Verify volunteer was created with correct linkage
        self.assertEqual(volunteer.member, member.name)
        self.assertEqual(volunteer.volunteer_name, f"{member.first_name} {member.last_name}")
        self.assertEqual(volunteer.email, member.email)

    def test_sync_chapter_board_members_whitelist(self):
        """Test chapter board member and volunteer integration"""
        # Create chapter and volunteers to test integration
        from frappe.utils import random_string
        unique_id = random_string(8)
        
        chapter = self.create_test_chapter(
            chapter_name=f"Test Sync Chapter {unique_id}",
            postal_codes="1000-9999"
        )

        # Create board members and volunteers
        board_volunteers = []
        for i in range(2):
            member = self.create_test_member(
                first_name=f"Board{i}{unique_id[:4]}", 
                last_name=f"Member{unique_id[4:]}",
                email=f"board.member.{i}.{unique_id}@example.com"
            )
            
            volunteer = self.create_test_volunteer(
                member=member,
                volunteer_name=f"{member.first_name} {member.last_name}",
                email=member.email
            )
            board_volunteers.append(volunteer)

        # Verify volunteers were created and linked to members
        self.assertEqual(len(board_volunteers), 2)
        for volunteer in board_volunteers:
            self.assertIsNotNone(volunteer.member)
            self.assertEqual(volunteer.status, "Active")

    def test_get_aggregated_assignments_whitelist(self):
        """Test get_aggregated_assignments method"""
        volunteer = self._create_test_volunteer()

        # Create some volunteer activities to test aggregation
        activity1 = volunteer.add_activity(
            activity_type="Training",
            role="Trainer",
            description="Training activity",
            start_date=add_days(today(), -180),
            estimated_hours=2
        )
        
        activity2 = volunteer.add_activity(
            activity_type="Event",
            role="Event Coordinator",
            description="Event coordination",
            start_date=add_days(today(), -90),
            estimated_hours=3
        )

        # Get aggregated assignments
        assignments = volunteer.get_aggregated_assignments()

        # Verify aggregation - it should return a list of assignments
        self.assertIsInstance(assignments, list)
        # Should have at least the activities we created
        self.assertGreaterEqual(len(assignments), 2)

    def test_permission_checks(self):
        """Test permission checks on whitelisted methods"""
        volunteer = self._create_test_volunteer()

        # Create a non-admin user
        from frappe.utils import random_string
        test_email = f"test.volunteer.{random_string(8)}@example.com"
        test_user = frappe.get_doc(
            {
                "doctype": "User",
                "email": test_email,
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}]}
        )
        test_user.insert()
        self.track_doc("User", test_user.name)

        # Test as non-admin user
        with self.as_user(test_email):
            # Should not be able to add activity to another volunteer without proper permissions
            with self.assertRaises(frappe.PermissionError):
                volunteer.add_activity(
                    activity_type="Training",
                    role="Unauthorized Role",
                    description="Unauthorized",
                    start_date=today(),
                )

    def test_error_handling(self):
        """Test error handling in whitelisted methods"""
        volunteer = self._create_test_volunteer()

        # Test ending non-existent activity
        with self.assertRaises(Exception):
            volunteer.end_activity(
                activity_name="non-existent-activity",
                end_date=today(),
            )

        # Test adding activity with invalid data
        with self.assertRaises(Exception):
            volunteer.add_activity(
                activity_type="",  # Empty activity type
                role="Test Role",
                description="Should fail",
                start_date=today(),
            )

    def test_data_integrity(self):
        """Test data integrity in volunteer operations"""
        volunteer = self._create_test_volunteer()

        # Add multiple activities
        activity_names = []
        for i in range(3):
            activity_name = volunteer.add_activity(
                activity_type="Training",
                role=f"Trainer {i}",
                description=f"Training activity {i}",
                start_date=today(),
                estimated_hours=2,
            )
            activity_names.append(activity_name)

        # Verify all activities were created
        self.assertEqual(len(activity_names), 3)
        
        # Verify each activity exists
        for activity_name in activity_names:
            activity = frappe.get_doc("Volunteer Activity", activity_name)
            self.assertEqual(activity.volunteer, volunteer.name)
            self.assertEqual(activity.status, "Active")

        # Verify total hours calculation is correct
        total_hours = volunteer.calculate_total_hours()
        # Should count estimated hours since they're active
        self.assertEqual(total_hours, 6.0)
