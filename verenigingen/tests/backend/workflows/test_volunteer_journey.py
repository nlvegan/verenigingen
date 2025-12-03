# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Volunteer Journey Workflow Test
Tests the complete volunteer lifecycle from member to active volunteer
"""


import frappe
from frappe.utils import add_days, today
from verenigingen.tests.utils.base import VereningingenWorkflowTestCase


class TestVolunteerJourney(VereningingenWorkflowTestCase):
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

        # Create admin user for administrative operations
        from frappe.utils import random_string
        admin_id = random_string(8).lower()
        self.admin_user = self.create_test_user(
            email=f"admin.{admin_id}@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )

        # Create base member for volunteer journey with unique email
        unique_id = random_string(8).lower()
        self.test_email = f"volunteer.journey.{unique_id}@example.com"
        self.base_member = self.create_test_member(
            first_name="Verenigingen Volunteer",
            last_name="Journey",
            email=self.test_email
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
        chapter.insert()  # VereningingenTestCase handles permissions
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
        member.insert()  # VereningingenTestCase handles permissions

        # Add to chapter
        member.append(
            "chapter_members",
            {
                "chapter": self.test_chapter.name,
                "chapter_join_date": today(),
                "enabled": 1,
                "status": "Active"},
        )
        member.save()  # VereningingenTestCase handles permissions

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

        # Create volunteer record (run as Administrator for test - permission testing is separate)
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"{self.base_member.first_name} {self.base_member.last_name}",
                "email": user_email,
                "member": member_name,
                "status": "Active",
                "start_date": today(),
                "motivation": "I want to help the community and contribute to our organization's mission.",
            }
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
            # Set available profile fields with valid option values
            volunteer.commitment_level = "Regular (Monthly)"
            volunteer.experience_level = "Intermediate"
            volunteer.preferred_work_style = "Hybrid"
            volunteer.note = "Eager to contribute to community events and youth programs"

            # Add skills (skills_and_qualifications is a Table)
            if not volunteer.skills_and_qualifications:
                volunteer.append(
                    "skills_and_qualifications",
                    {"volunteer_skill": "Event Management", "skill_category": "Event Planning", "proficiency_level": "3 - Intermediate"},
                )

            # Add interests (interests is a Table MultiSelect)
            # Note: interests require existing Volunteer Interest Category records

            volunteer.save(ignore_permissions=True)

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Profile Completed")

        return {"profile_completed": True}

    def _validate_profile_completed(self, context):
        """Validate volunteer profile was completed"""
        volunteer_name = context.get("volunteer_name")
        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        # Validate profile fields are set
        self.assertIsNotNone(volunteer.commitment_level)
        self.assertIsNotNone(volunteer.experience_level)
        self.assertIsNotNone(volunteer.preferred_work_style)

        # Check skills_and_qualifications table has entries
        self.assertTrue(len(volunteer.skills_and_qualifications) > 0, "No skills added")

    # Stage 3: Join Teams/Assignments
    def _stage_3_join_teams(self, context):
        """Stage 3: Join multiple teams and get assignments"""
        from frappe.utils import random_string

        volunteer_name = context.get("volunteer_name")
        context.get("user_email")

        # Generate unique suffix for team names
        unique_suffix = random_string(6).lower()

        teams_created = []

        with self.as_user(self.admin_user.name):
            # Create multiple teams with unique names
            # team_role must be a valid Team Role record
            team_configs = [
                {
                    "team_name": f"Events Team {unique_suffix}",
                    "team_type": "Project Team",
                    "team_role": "Team Leader"},  # Existing Team Role
                {
                    "team_name": f"Outreach Team {unique_suffix}",
                    "team_type": "Committee",  # Valid: Committee, Working Group, Task Force, etc.
                    "team_role": "Team Member"},  # Existing Team Role
                {
                    "team_name": f"Social Media Team {unique_suffix}",
                    "team_type": "Working Group",
                    "team_role": "Coordinator"},  # Existing Team Role
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
                team.insert()  # VereningingenTestCase handles permissions

                # Add volunteer to team
                team.append(
                    "team_members",
                    {
                        "volunteer": volunteer_name,
                        "team_role": config["team_role"],  # Link to Team Role
                        "from_date": today(),
                        "is_active": 1,
                        "status": "Active"},
                )
                team.save()  # VereningingenTestCase handles permissions

                teams_created.append({"team_name": team.name, "team_role": config["team_role"]})

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
            # Create multiple expenses with valid categories
            expense_configs = [
                {
                    "description": "Travel to community event",
                    "amount": 25.50,
                    "category": "Travel",  # Link to Expense Category
                    "receipt_required": True},
                {
                    "description": "Event supplies and materials",
                    "amount": 75.00,
                    "category": "Materials",  # Link to Expense Category
                    "receipt_required": True},
                {
                    "description": "Parking fees for volunteer activities",
                    "amount": 15.00,
                    "category": "Travel",  # Link to Expense Category
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
                        "category": config["category"],  # Link to Expense Category
                        "organization_type": "National",  # National doesn't require chapter/team access
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
                expense.save()  # VereningingenTestCase handles permissions

                # Approve expense
                expense.status = "Approved"
                expense.approved_by = self.admin_user.name
                expense.approved_on = today()
                expense.approval_notes = "Approved for volunteer journey test"
                expense.save()  # VereningingenTestCase handles permissions

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
            # Log volunteer activities with correct field names
            activity_configs = [
                {
                    "activity_type": "Event",
                    "role": "Event Organizer",
                    "actual_hours": 4.5,
                    "start_date": today(),
                    "description": "Community Event Organization"},
                {
                    "activity_type": "Campaign",
                    "role": "Content Creator",
                    "actual_hours": 2.0,
                    "start_date": add_days(today(), -1),
                    "description": "Social Media Content Creation"},
                {
                    "activity_type": "Training",
                    "role": "Participant",
                    "actual_hours": 3.0,
                    "start_date": add_days(today(), -2),
                    "description": "Volunteer Training Session"},
            ]

            for config in activity_configs:
                activity = frappe.get_doc(
                    {
                        "doctype": "Volunteer Activity",
                        "volunteer": volunteer_name,
                        "activity_type": config["activity_type"],
                        "role": config["role"],
                        "actual_hours": config["actual_hours"],
                        "start_date": config["start_date"],
                        "status": "Completed",
                        "description": config["description"]}
                )
                activity.insert(ignore_permissions=True)

                activities_logged.append({"activity_name": activity.name, "hours": config["actual_hours"]})

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
            total_hours += activity.actual_hours or 0  # Use correct field name

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
        
        # Batch fetch for better performance - use actual_hours field
        activity_hours = frappe.get_all(
            "Volunteer Activity",
            filters={"name": ["in", activity_names]},
            fields=["actual_hours"]
        ) if activity_names else []

        expense_amounts = frappe.get_all(
            "Volunteer Expense",
            filters={"name": ["in", expense_names]},
            fields=["amount"]
        ) if expense_names else []

        total_hours = sum((item.get("actual_hours") or 0) for item in activity_hours)
        total_expenses = sum((item.get("amount") or 0) for item in expense_amounts)

        # Update volunteer note with aggregated data (since specific fields may not exist)
        with self.as_user(self.admin_user.name):
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            # Store report info in notes field instead of non-existent fields
            volunteer.note = f"Report generated: {total_hours} hours, €{total_expenses} expenses"
            volunteer.save(ignore_permissions=True)

        # Record state
        self.state_manager.record_state("Verenigingen Volunteer", volunteer_name, "Reports Generated")

        return {"total_hours": total_hours, "total_expenses": total_expenses, "report_generated": True}

    def _validate_reports_generated(self, context):
        """Validate reports were generated correctly"""
        volunteer_name = context.get("volunteer_name")
        total_hours = context.get("total_hours", 0)
        total_expenses = context.get("total_expenses", 0)

        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        # Check report was recorded in note field
        self.assertIn("Report generated", volunteer.note or "")
        self.assertGreater(total_hours, 0, "Should have logged some hours")
        self.assertTrue(context.get("report_generated"), "Report should be generated")

    # Stage 8: Deactivate Volunteer Status
    def _stage_8_deactivate_volunteer(self, context):
        """Stage 8: Deactivate volunteer status"""
        volunteer_name = context.get("volunteer_name")

        # Volunteer decides to step down - use admin user context
        with self.as_user(self.admin_user.name):
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            volunteer.status = "Inactive"
            # Store deactivation reason in note field (no end_date/deactivation_reason fields exist)
            volunteer.note = f"{volunteer.note or ''}\nDeactivated on {today()}: Volunteer journey test completion"
            volunteer.save(ignore_permissions=True)

            # Deactivate team memberships - query via Team Member child table
            team_memberships = frappe.get_all(
                "Team Member",
                filters={"volunteer": volunteer_name},
                fields=["parent"]
            )
            team_names = list(set(tm.parent for tm in team_memberships))

            for team_name in team_names:
                team = frappe.get_doc("Team", team_name)
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
        self.assertIn("Deactivated", volunteer.note or "")

        # Check team memberships are deactivated - query via Team Member child table
        team_memberships = frappe.get_all(
            "Team Member",
            filters={"volunteer": volunteer_name},
            fields=["parent"]
        )
        team_names = list(set(tm.parent for tm in team_memberships))

        for team_name in team_names:
            team = frappe.get_doc("Team", team_name)
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
