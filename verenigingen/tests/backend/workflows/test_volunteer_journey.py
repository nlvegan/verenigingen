# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Volunteer Journey Workflow Test
Tests the complete volunteer lifecycle from member to active volunteer
"""


import frappe
from frappe.utils import add_days, today
from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerJourney(VereningingenTestCase):
    """
    Volunteer Journey Test

    Stage 1: Member becomes volunteer
    Stage 2: Complete volunteer profile
    Stage 3: Join teams/assignments
    Stage 4: Submit expenses
    Stage 5: Expense approval workflow
    Stage 6: Track volunteer hours
    Stage 7: Generate reports
    Stage 8: Deactivate volunteer status
    """

    def setUp(self):
        """Set up the volunteer journey test"""
        super().setUp()

        # Create test environment using factory methods
        self.test_chapter = self.create_test_chapter(
            chapter_name="Volunteer Journey Chapter"
        )

        # Create base member for volunteer journey
        self.base_member = self.create_test_member(
            first_name="Verenigingen Volunteer",
            last_name="Journey",
            email="volunteer.journey@example.com"
        )

    def test_complete_volunteer_journey(self):
        """Test the complete volunteer journey from member to deactivation"""

        stages = [
            {
                "name": "Stage 1: Member Becomes Volunteer",
                "function": self._stage_1_become_volunteer,
                "validations": [self._validate_volunteer_created]},
            {
                "name": "Stage 2: Complete Volunteer Profile",
                "function": self._stage_2_complete_profile,
                "validations": [self._validate_profile_completed]},
            {
                "name": "Stage 3: Join Teams/Assignments",
                "function": self._stage_3_join_teams,
                "validations": [self._validate_team_assignments]},
            {
                "name": "Stage 4: Submit Expenses",
                "function": self._stage_4_submit_expenses,
                "validations": [self._validate_expenses_submitted]},
            {
                "name": "Stage 5: Expense Approval Workflow",
                "function": self._stage_5_expense_approval,
                "validations": [self._validate_expenses_approved]},
            {
                "name": "Stage 6: Track Volunteer Hours",
                "function": self._stage_6_track_hours,
                "validations": [self._validate_hours_tracked]},
            {
                "name": "Stage 7: Generate Reports",
                "function": self._stage_7_generate_reports,
                "validations": [self._validate_reports_generated]},
            {
                "name": "Stage 8: Deactivate Volunteer Status",
                "function": self._stage_8_deactivate_volunteer,
                "validations": [self._validate_volunteer_deactivated]},
        ]

        self.define_workflow(stages)

        with self.workflow_transaction():
            self.execute_workflow()

        # Final validations
        self._validate_complete_volunteer_journey()

    def _create_test_chapter(self):
        """Create a test chapter for the volunteer journey"""
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": "Volunteer Test Chapter",
                "region": "Test Region",
                "postal_codes": "2000-8999",
                "introduction": "Test chapter for volunteer journey testing"}
        )
        chapter.insert(ignore_permissions=True)
        self.track_doc("Chapter", chapter.name)
        return chapter

    def _create_base_member(self):
        """Create a base member to start the volunteer journey"""
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "TestVolunteer",
                "last_name": "Journey",
                "email": "volunteer.journey@example.com",
                "contact_number": "+31687654321",
                "payment_method": "Bank Transfer",
                "status": "Active",
                "primary_chapter": self.test_chapter.name}
        )
        member.insert(ignore_permissions=True)

        # Add to chapter
        member.append(
            "chapter_members",
            {
                "chapter": self.test_chapter.name,
                "chapter_join_date": today(),
                "enabled": 1,
                "status": "Active"},
        )
        member.save(ignore_permissions=True)

        self.track_doc("Member", member.name)

        # Create user account for the member
        user = TestUserFactory.create_member_user(
            email="volunteer.journey@example.com", member_name=member.name
        )
        self.track_doc("User", user.name)

        return member

    # Stage 1: Member Becomes Volunteer
    def _stage_1_become_volunteer(self, context):
        """Stage 1: Member decides to become a volunteer"""
        member_name = self.base_member.name
        user_email = self.base_member.email

        with self.as_user(user_email):
            # Create volunteer record
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"{self.base_member.first_name} {self.base_member.last_name}",
                    "email": user_email,
                    "member": member_name,
                    "status": "Active",
                    "start_date": today(),
                    "motivation": "I want to help the community and contribute to our organization's mission."}
            )
            volunteer.insert(ignore_permissions=True)

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer.name, "Created")

        return {"volunteer_name": volunteer.name, "member_name": member_name, "user_email": user_email}

    def _validate_volunteer_created(self, context):
        """Validate volunteer record was created correctly"""
        volunteer_name = context.get("volunteer_name")
        self.assertIsNotNone(volunteer_name)

        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(volunteer.member, context.get("member_name"))
        self.assertIsNotNone(volunteer.start_date)

    # Stage 2: Complete Volunteer Profile
    def _stage_2_complete_profile(self, context):
        """Stage 2: Complete volunteer profile with skills and interests"""
        volunteer_name = context.get("volunteer_name")
        user_email = context.get("user_email")

        with self.as_user(user_email):
            volunteer = frappe.get_doc("Volunteer", volunteer_name)

            # Add skills and interests
            volunteer.skills = "Event Management, Social Media, Public Speaking"
            volunteer.interests = "Community Events, Youth Programs, Environmental Projects"
            volunteer.availability = "Weekends and evenings"
            volunteer.emergency_contact_name = "Emergency Contact"
            volunteer.emergency_contact_phone = "+31612345678"

            # Add volunteer interests
            if not volunteer.volunteer_interests:
                volunteer.append(
                    "volunteer_interests", {"interest_category": "Events", "interest_level": "High"}
                )
                volunteer.append(
                    "volunteer_interests", {"interest_category": "Youth Programs", "interest_level": "Medium"}
                )

            volunteer.save()

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Profile Completed")

        return {"profile_completed": True}

    def _validate_profile_completed(self, context):
        """Validate volunteer profile was completed"""
        volunteer_name = context.get("volunteer_name")
        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        self.assertIsNotNone(volunteer.skills)
        self.assertIsNotNone(volunteer.interests)
        self.assertIsNotNone(volunteer.availability)

        # Check volunteer interests were added
        self.assertTrue(len(volunteer.volunteer_interests) > 0, "No volunteer interests added")

    # Stage 3: Join Teams/Assignments
    def _stage_3_join_teams(self, context):
        """Stage 3: Join multiple teams and get assignments"""
        volunteer_name = context.get("volunteer_name")
        context.get("user_email")

        teams_created = []

        with self.as_user(self.admin_user.name):
            # Create multiple teams
            team_configs = [
                {
                    "team_name": "Events Team",
                    "team_type": "Project Team",
                    "volunteer_role": "Event Coordinator",
                    "role_type": "Team Leader"},
                {
                    "team_name": "Outreach Team",
                    "team_type": "Standing Committee",
                    "volunteer_role": "Community Liaison",
                    "role_type": "Team Member"},
                {
                    "team_name": "Social Media Team",
                    "team_type": "Working Group",
                    "volunteer_role": "Content Creator",
                    "role_type": "Specialist"},
            ]

            for config in team_configs:
                # Create team
                team = frappe.get_doc(
                    {
                        "doctype": "Team",
                        "team_name": config["team_name"],
                        "chapter": self.test_chapter.name,
                        "status": "Active",
                        "team_type": config["team_type"],
                        "start_date": today(),
                        "description": f"Test team for {config['team_name']}"}
                )
                team.insert(ignore_permissions=True)

                # Add volunteer to team
                team.append(
                    "team_members",
                    {
                        "volunteer": volunteer_name,
                        "volunteer_name": f"{self.base_member.first_name} {self.base_member.last_name}",
                        "role": config["volunteer_role"],
                        "role_type": config["role_type"],
                        "from_date": today(),
                        "is_active": 1,
                        "status": "Active"},
                )
                team.save(ignore_permissions=True)

                teams_created.append({"team_name": team.name, "role": config["volunteer_role"]})

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Teams Joined")

        return {"teams_joined": teams_created}

    def _validate_team_assignments(self, context):
        """Validate volunteer was assigned to teams correctly"""
        teams_joined = context.get("teams_joined", [])
        volunteer_name = context.get("volunteer_name")

        self.assertTrue(len(teams_joined) >= 2, "Volunteer should be assigned to multiple teams")

        # Check each team assignment
        for team_info in teams_joined:
            team = frappe.get_doc("Team", team_info["team_name"])
            team_members = [tm for tm in team.team_members if tm.volunteer == volunteer_name]
            self.assertTrue(len(team_members) > 0, f"Volunteer not found in {team_info['team_name']}")

            # Check role assignment
            member = team_members[0]
            self.assertEqual(member.status, "Active")
            self.assertTrue(member.is_active)

    # Stage 4: Submit Expenses
    def _stage_4_submit_expenses(self, context):
        """Stage 4: Submit various volunteer expenses"""
        volunteer_name = context.get("volunteer_name")
        user_email = context.get("user_email")

        expenses_created = []

        with self.as_user(user_email):
            # Create multiple expenses
            expense_configs = [
                {
                    "description": "Travel to community event",
                    "amount": 25.50,
                    "expense_type": "Travel",
                    "receipt_required": True},
                {
                    "description": "Event supplies and materials",
                    "amount": 75.00,
                    "expense_type": "Materials",
                    "receipt_required": True},
                {
                    "description": "Parking fees for volunteer activities",
                    "amount": 15.00,
                    "expense_type": "Parking",
                    "receipt_required": False},
            ]

            for config in expense_configs:
                expense = frappe.get_doc(
                    {
                        "doctype": "Volunteer Expense",
                        "volunteer": volunteer_name,
                        "amount": config["amount"],
                        "description": config["description"],
                        "expense_date": today(),
                        "expense_type": config.get("expense_type", "General"),
                        "status": "Draft"}
                )
                expense.insert(ignore_permissions=True)

                expenses_created.append({"expense_name": expense.name, "amount": config["amount"]})

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Expenses Submitted")

        return {"expenses_submitted": expenses_created}

    def _validate_expenses_submitted(self, context):
        """Validate expenses were submitted correctly"""
        expenses_submitted = context.get("expenses_submitted", [])
        volunteer_name = context.get("volunteer_name")

        self.assertTrue(len(expenses_submitted) >= 2, "Multiple expenses should be submitted")

        total_amount = 0
        for expense_info in expenses_submitted:
            expense = frappe.get_doc("Volunteer Expense", expense_info["expense_name"])
            self.assertEqual(expense.volunteer, volunteer_name)
            self.assertEqual(expense.status, "Draft")
            total_amount += expense.amount

        self.assertGreater(total_amount, 0, "Total expense amount should be positive")

    # Stage 5: Expense Approval Workflow
    def _stage_5_expense_approval(self, context):
        """Stage 5: Process expense approvals"""
        expenses_submitted = context.get("expenses_submitted", [])
        volunteer_name = context.get("volunteer_name")

        approved_expenses = []

        with self.as_user(self.admin_user.name):
            for expense_info in expenses_submitted:
                expense = frappe.get_doc("Volunteer Expense", expense_info["expense_name"])

                # Submit for approval
                expense.status = "Submitted"
                expense.submitted_on = today()
                expense.save(ignore_permissions=True)

                # Approve expense
                expense.status = "Approved"
                expense.approved_by = self.admin_user.name
                expense.approved_on = today()
                expense.approval_notes = "Approved for volunteer journey test"
                expense.save(ignore_permissions=True)

                approved_expenses.append(expense_info)

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Expenses Approved")

        return {"expenses_approved": approved_expenses}

    def _validate_expenses_approved(self, context):
        """Validate expenses were approved"""
        expenses_approved = context.get("expenses_approved", [])

        for expense_info in expenses_approved:
            expense = frappe.get_doc("Volunteer Expense", expense_info["expense_name"])
            self.assertEqual(expense.status, "Approved")
            self.assertIsNotNone(expense.approved_by)
            self.assertIsNotNone(expense.approved_on)

    # Stage 6: Track Volunteer Hours
    def _stage_6_track_hours(self, context):
        """Stage 6: Track volunteer hours and activities"""
        volunteer_name = context.get("volunteer_name")
        user_email = context.get("user_email")
        teams_joined = context.get("teams_joined", [])

        activities_logged = []

        with self.as_user(user_email):
            # Log volunteer activities
            activity_configs = [
                {
                    "activity_name": "Community Event Organization",
                    "hours": 4.5,
                    "activity_date": today(),
                    "team": teams_joined[0]["team_name"] if teams_joined else None},
                {
                    "activity_name": "Social Media Content Creation",
                    "hours": 2.0,
                    "activity_date": add_days(today(), -1),
                    "team": teams_joined[-1]["team_name"] if len(teams_joined) > 1 else None},
                {
                    "activity_name": "Volunteer Training Session",
                    "hours": 3.0,
                    "activity_date": add_days(today(), -2),
                    "team": None,  # General activity
                },
            ]

            for config in activity_configs:
                activity = frappe.get_doc(
                    {
                        "doctype": "Volunteer Activity",
                        "volunteer": volunteer_name,
                        "activity_name": config["activity_name"],
                        "hours": config["hours"],
                        "activity_date": config["activity_date"],
                        "team": config.get("team"),
                        "status": "Completed",
                        "description": f"Test activity: {config['activity_name']}"}
                )
                activity.insert(ignore_permissions=True)

                activities_logged.append({"activity_name": activity.name, "hours": config["hours"]})

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Hours Tracked")

        return {"activities_logged": activities_logged}

    def _validate_hours_tracked(self, context):
        """Validate volunteer hours were tracked"""
        activities_logged = context.get("activities_logged", [])
        volunteer_name = context.get("volunteer_name")

        self.assertTrue(len(activities_logged) >= 2, "Multiple activities should be logged")

        total_hours = 0
        for activity_info in activities_logged:
            activity = frappe.get_doc("Volunteer Activity", activity_info["activity_name"])
            self.assertEqual(activity.volunteer, volunteer_name)
            self.assertEqual(activity.status, "Completed")
            total_hours += activity.hours

        self.assertGreater(total_hours, 5, "Total volunteer hours should be substantial")

    # Stage 7: Generate Reports
    def _stage_7_generate_reports(self, context):
        """Stage 7: Generate volunteer reports and analytics"""
        volunteer_name = context.get("volunteer_name")
        activities_logged = context.get("activities_logged", [])
        expenses_approved = context.get("expenses_approved", [])

        # Calculate totals for reporting - optimized batch queries
        activity_names = [activity["activity_name"] for activity in activities_logged]
        expense_names = [expense["expense_name"] for expense in expenses_approved]
        
        # Batch fetch for better performance
        activity_hours = frappe.get_all(
            "Volunteer Activity", 
            filters={"name": ["in", activity_names]},
            fields=["hours"]
        ) if activity_names else []
        
        expense_amounts = frappe.get_all(
            "Volunteer Expense",
            filters={"name": ["in", expense_names]}, 
            fields=["amount"]
        ) if expense_names else []
        
        total_hours = sum(item["hours"] for item in activity_hours)
        total_expenses = sum(item["amount"] for item in expense_amounts)

        # Update volunteer aggregated data
        with self.as_user(self.admin_user.name):
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.total_hours_logged = total_hours
            volunteer.total_expenses = total_expenses
            volunteer.last_activity_date = today()
            volunteer.save()

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Reports Generated")

        return {"total_hours": total_hours, "total_expenses": total_expenses, "report_generated": True}

    def _validate_reports_generated(self, context):
        """Validate reports were generated correctly"""
        volunteer_name = context.get("volunteer_name")
        total_hours = context.get("total_hours", 0)
        total_expenses = context.get("total_expenses", 0)

        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        # Check aggregated data
        if hasattr(volunteer, "total_hours_logged"):
            self.assertEqual(volunteer.total_hours_logged, total_hours)
        if hasattr(volunteer, "total_expenses"):
            self.assertEqual(volunteer.total_expenses, total_expenses)

        self.assertTrue(context.get("report_generated"), "Report should be generated")

    # Stage 8: Deactivate Volunteer Status
    def _stage_8_deactivate_volunteer(self, context):
        """Stage 8: Deactivate volunteer status"""
        volunteer_name = context.get("volunteer_name")
        user_email = context.get("user_email")

        with self.as_user(user_email):
            # Volunteer decides to step down
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Inactive"
            volunteer.end_date = today()
            volunteer.deactivation_reason = "Volunteer journey test completion"
            volunteer.save()

            # Deactivate team memberships
            teams = frappe.get_all(
                "Team", filters={"team_members.volunteer": volunteer_name}, fields=["name"]
            )

            for team_info in teams:
                team = frappe.get_doc("Team", team_info.name)
                for member in team.team_members:
                    if member.volunteer == volunteer_name:
                        member.is_active = 0
                        member.status = "Completed"
                        member.to_date = today()
                team.save(ignore_permissions=True)

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Deactivated")

        return {"volunteer_deactivated": True}

    def _validate_volunteer_deactivated(self, context):
        """Validate volunteer was deactivated correctly"""
        volunteer_name = context.get("volunteer_name")
        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        self.assertEqual(volunteer.status, "Inactive")
        self.assertIsNotNone(volunteer.end_date)

        # Check team memberships are deactivated
        teams = frappe.get_all("Team", filters={"team_members.volunteer": volunteer_name}, fields=["name"])

        for team_info in teams:
            team = frappe.get_doc("Team", team_info.name)
            active_memberships = [
                tm for tm in team.team_members if tm.volunteer == volunteer_name and tm.is_active
            ]
            self.assertEqual(len(active_memberships), 0, "All team memberships should be deactivated")

    def _validate_complete_volunteer_journey(self):
        """Final validation of complete volunteer journey"""
        # Check that all major state transitions occurred
        transitions = self.state_manager.get_transitions()

        # Should have volunteer state transitions
        volunteer_transitions = [t for t in transitions if t["entity_type"] == "Verenigingen Volunteer"]
        self.assertTrue(len(volunteer_transitions) > 0, "No volunteer transitions recorded")

        # Check progression through key states
        workflow_context = self.get_workflow_context()
        volunteer_name = workflow_context.get("volunteer_name")

        if volunteer_name:
            final_state = self.state_manager.get_state("Verenigingen Volunteer", volunteer_name)
            self.assertEqual(final_state, "Deactivated", "Volunteer should be in final deactivated state")

            # Validate journey completeness
            frappe.get_doc("Volunteer", volunteer_name)

            # Should have activities, expenses, and team assignments
            activities = frappe.get_all("Volunteer Activity", filters={"volunteer": volunteer_name})
            expenses = frappe.get_all("Volunteer Expense", filters={"volunteer": volunteer_name})

            self.assertTrue(len(activities) > 0, "Volunteer should have logged activities")
            self.assertTrue(len(expenses) > 0, "Volunteer should have submitted expenses")

            # Should have gone through complete lifecycle
            expected_states = [
                "Created",
                "Profile Completed",
                "Teams Joined",
                "Expenses Submitted",
                "Hours Tracked",
                "Deactivated",
            ]
            volunteer_states = [t["to_state"] for t in volunteer_transitions]

            for state in expected_states:
                if state in volunteer_states:
                    self.assertIn(state, volunteer_states, f"Missing expected state: {state}")
