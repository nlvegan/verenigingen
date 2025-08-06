# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Volunteer controller whitelisted methods
Tests the API endpoints that JavaScript calls
"""


import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.tests.utils.setup_helpers import TestEnvironmentSetup


class TestVolunteerWhitelistMethods(VereningingenUnitTestCase):
    """Test Volunteer whitelisted API methods as called from JavaScript"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = TestEnvironmentSetup.create_standard_test_environment()

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        self.builder.cleanup()
        super().tearDown()

    def test_validate_member_link_method(self):
        """Test validation of member linkage"""
        # Create member
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create volunteer with valid member link
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test Volunteer {frappe.utils.random_string(8)}",
                "email": f"volunteer.{frappe.utils.random_string(8)}@test.com",
                "member": member.name,
                "status": "Active",
                "start_date": today()}
        )

        # Should not raise error
        volunteer.insert()
        self.track_doc("Volunteer", volunteer.name)

        # Test with invalid member link
        volunteer2 = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Test Invalid Volunteer {frappe.utils.random_string(8)}",
                "email": f"volunteer.invalid.{frappe.utils.random_string(8)}@test.com",
                "member": "INVALID-MEMBER",
                "status": "Active",
                "start_date": today()}
        )

        with self.assertRaises(frappe.DoesNotExistError):
            volunteer2.insert()

    def test_update_aggregated_data_method(self):
        """Test aggregated data updates"""
        # Create volunteer with team assignment
        test_data = (
            self.builder.with_member()
            .with_volunteer_profile()
            .with_team_assignment(team_name=None, role="Event Coordinator")  # Let builder create a new team
            .build()
        )

        volunteer = test_data["volunteer"]

        # Verify assignment history was created
        volunteer.reload()
        self.assertTrue(volunteer.assignment_history)

        active_assignments = [a for a in volunteer.assignment_history if a.status == "Active"]
        self.assertEqual(len(active_assignments), 1)
        self.assertEqual(active_assignments[0].role, "Event Coordinator")

    def test_get_active_assignments_method(self):
        """Test getting active assignments"""
        # Create volunteer with multiple assignments
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]

        # Add multiple assignments manually
        volunteer.append(
            "assignment_history",
            {"assignment_type": "Team", "role": "Active Role", "start_date": today(), "status": "Active"},
        )

        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Committee",
                "role": "Completed Role",
                "start_date": add_days(today(), -90),
                "end_date": add_days(today(), -30),
                "status": "Completed"},
        )

        volunteer.save()

        # Test get_activity_assignments
        active = volunteer.get_activity_assignments()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].role, "Active Role")

    def test_calculate_total_hours_method(self):
        """Test total volunteer hours calculation"""
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]

        # Add assignments with hours
        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Project Member",
                "start_date": add_days(today(), -60),
                "end_date": add_days(today(), -30),
                "status": "Completed",
                "actual_hours": 40},
        )

        volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Event",
                "role": "Event Helper",
                "start_date": add_days(today(), -20),
                "end_date": add_days(today(), -10),
                "status": "Completed",
                "actual_hours": 20},
        )

        volunteer.save()

        # Test total hours calculation
        total_hours = volunteer.calculate_total_hours()
        self.assertEqual(total_hours, 60)

    def test_get_skills_by_category_method(self):
        """Test skills categorization"""
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]

        # Add skills in different categories
        skills_data = [
            {
                "skill_category": "Technical",
                "volunteer_skill": "Python Programming",
                "proficiency_level": "4 - Advanced"},
            {
                "skill_category": "Technical",
                "volunteer_skill": "Database Design",
                "proficiency_level": "3 - Intermediate"},
            {
                "skill_category": "Communication",
                "volunteer_skill": "Public Speaking",
                "proficiency_level": "4 - Advanced"},
        ]

        for skill in skills_data:
            volunteer.append("skills_and_qualifications", skill)

        volunteer.save()

        # Test skill categorization
        skills_by_category = volunteer.get_skills_by_category()

        self.assertIn("Technical", skills_by_category)
        self.assertIn("Communication", skills_by_category)
        self.assertEqual(len(skills_by_category["Technical"]), 2)
        self.assertEqual(len(skills_by_category["Communication"]), 1)

    def test_get_aggregated_assignments_method(self):
        """Test aggregated assignments from multiple sources"""
        # Create volunteer with team and activity
        test_data = (
            self.builder.with_chapter(None)  # Let builder create a new chapter
            .with_member()
            .with_volunteer_profile()
            .with_team_assignment(team_name=None, role="Team Member")  # Let builder create a new team
            .build()
        )

        volunteer = test_data["volunteer"]

        # Create a volunteer activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": volunteer.name,
                "activity_type": "Project",
                "role": "Project Coordinator",
                "description": "Test activity",
                "status": "Active",
                "start_date": today()}
        )
        activity.insert(ignore_permissions=True)
        self.track_doc("Volunteer Activity", activity.name)

        # Test aggregated assignments
        aggregated = volunteer.get_aggregated_assignments()

        # Should include both team assignment and activity
        self.assertGreaterEqual(len(aggregated), 2)

        # Check for both sources
        sources = [a.get("source_type") for a in aggregated]
        self.assertIn("Team", sources)
        self.assertIn("Activity", sources)

    def test_assignment_history_lifecycle(self):
        """Test assignment history creation and completion"""
        # Create volunteer
        test_data = self.builder.with_member().with_volunteer_profile().build()

        volunteer = test_data["volunteer"]

        # Create a team for testing
        team_doc = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Test Team {frappe.utils.random_string(8)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today()}
        )
        team_doc.insert(ignore_permissions=True)
        self.track_doc("Team", team_doc.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "role": "Test Role",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active"},
        )
        team_doc.save()

        # Verify assignment history created
        volunteer.reload()
        active_assignment = None
        for assignment in volunteer.assignment_history:
            if assignment.reference_name == team_doc.name and assignment.status == "Active":
                active_assignment = assignment
                break

        self.assertIsNotNone(active_assignment)
        self.assertEqual(active_assignment.role, "Test Role")

        # Remove from team (should complete assignment)
        team_doc.reload()
        team_doc.team_members[0].is_active = 0
        team_doc.team_members[0].to_date = today()
        team_doc.team_members[0].status = "Completed"
        team_doc.save()

        # Verify assignment completed
        volunteer.reload()
        completed_assignment = None
        for assignment in volunteer.assignment_history:
            if assignment.reference_name == team_doc.name and assignment.status == "Completed":
                completed_assignment = assignment
                break

        self.assertIsNotNone(completed_assignment)
        self.assertEqual(str(completed_assignment.end_date), today())

    def test_volunteer_status_transitions(self):
        """Test volunteer status state machine"""
        test_data = self.builder.with_member().with_volunteer_profile(status="New").build()

        volunteer = test_data["volunteer"]

        # Test valid transitions
        valid_transitions = [
            ("New", "Onboarding"),
            ("Onboarding", "Active"),
            ("Active", "Inactive"),
            ("Inactive", "Active"),
            ("Active", "Retired"),
        ]

        for from_status, to_status in valid_transitions:
            volunteer.status = from_status
            volunteer.save()

            volunteer.status = to_status
            volunteer.save()

            volunteer.reload()
            self.assertEqual(volunteer.status, to_status)

    def test_volunteer_permission_integration(self):
        """Test volunteer-specific permissions"""
        # Create volunteer with member user
        test_data = self.builder.with_member().with_volunteer_profile().build()

        test_data["volunteer"]
        member = test_data["member"]

        # Create user for member
        user = self.create_test_user(
            email=f"volunteer.user.{frappe.utils.random_string(8)}@test.com", roles=["Member", "Verenigingen Volunteer"]
        )

        # Reload member to avoid timestamp issues
        member = frappe.get_doc("Member", member.name)
        member.user = user.name
        member.save()

        # Test permission query
        from verenigingen.permissions import get_volunteer_permission_query

        with self.as_user(user.name):
            query = get_volunteer_permission_query(user.name)

            # Member should be able to see their own volunteer record
            self.assertNotEqual(query.strip(), "1=0")

    def test_volunteer_expense_workflow(self):
        """Test volunteer expense submission and approval"""
        test_data = (
            self.builder.with_chapter()  # Add chapter first
            .with_member()
            .with_volunteer_profile()
            .with_expense(100, "Travel expense")
            .build()
        )

        test_data["volunteer"]
        expense = test_data["expenses"][0]

        # Test expense workflow
        self.assertEqual(expense.status, "Draft")

        # Submit expense
        expense.status = "Submitted"
        expense.save()

        # Approve expense
        expense.status = "Approved"
        expense.approval_date = today()
        expense.save()

        # Verify expense status
        expense.reload()
        self.assertEqual(expense.status, "Approved")

    def test_volunteer_communication_preferences(self):
        """Test volunteer communication settings"""
        test_data = self.builder.with_member().with_volunteer_profile().build()

        test_data["volunteer"]

        # Test communication preferences
        # This would test opt-in/opt-out settings

    def test_volunteer_availability_tracking(self):
        """Test volunteer availability and commitment"""
        test_data = (
            self.builder.with_member()
            .with_volunteer_profile(commitment_level="Weekly", preferred_work_style="Hybrid")
            .build()
        )

        volunteer = test_data["volunteer"]

        self.assertEqual(volunteer.commitment_level, "Weekly")
        self.assertEqual(volunteer.preferred_work_style, "Hybrid")
