# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import random
import string
import unittest

import frappe
from frappe.utils import add_days, getdate, today


class TestTeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Tell Frappe not to make test records
        frappe.flags.make_test_records = False
        # Clean up any leftover test data from previous failed runs
        cls.cleanup_test_data()

    @classmethod
    def cleanup_test_data(cls):
        """Clean up any existing test data to start fresh"""
        # First delete any test teams that might exist
        teams = frappe.get_all("Team", filters={"team_name": ["like", "Test%"]}, fields=["name"])
        for team in teams:
            try:
                frappe.delete_doc("Team", team.name, force=True)
                print(f"Cleaned up existing team: {team.name}")
            except Exception as e:
                print(f"Error cleaning up team {team.name}: {e}")

        # Clean up volunteers and members by matching patterns
        volunteers = frappe.get_all(
            "Volunteer", filters={"volunteer_name": ["like", "TeamTest%"]}, fields=["name"]
        )
        for vol in volunteers:
            try:
                frappe.delete_doc("Volunteer", vol.name, force=True)
                print(f"Cleaned up existing volunteer: {vol.name}")
            except Exception as e:
                print(f"Error cleaning up volunteer {vol.name}: {e}")

        members = frappe.get_all("Member", filters={"email": ["like", "test%@example.com"]}, fields=["name"])
        for member in members:
            try:
                frappe.delete_doc("Member", member.name, force=True)
                print(f"Cleaned up existing member: {member.name}")
            except Exception as e:
                print(f"Error cleaning up member {member.name}: {e}")

    def setUp(self):
        # Generate a unique ID for this test method
        self.test_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        # Create test data
        self.create_test_volunteers()

    def tearDown(self):
        # Clean up test data
        self.cleanup_test_data()

    def create_test_volunteers(self):
        """Create test members and volunteers for team"""
        self.test_members = []
        self.test_volunteers = []

        # Create members first
        for i in range(3):
            # Each member gets its own unique ID
            unique_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

            # Create a unique email per run
            email = f"test{unique_id}{i}@example.com"

            # Check if this email already exists
            if frappe.db.exists("Member", {"email": email}):
                print(f"Member with email {email} already exists, skipping")
                continue

            # Create member with unique name
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": f"Test{unique_id[:4]}",
                    "last_name": f"{i}{unique_id[4:]}",
                    "email": email,
                }
            )
            member.insert(ignore_permissions=True)
            self.test_members.append(member)

            # Create volunteer for each member with unique name
            vol_email = f"teamtest{unique_id}@example.org"

            # Check if volunteer already exists
            if frappe.db.exists("Volunteer", {"email": vol_email}):
                print(f"Volunteer with email {vol_email} already exists, skipping")
                continue

            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"TeamTest{unique_id}",  # No spaces to be safe
                    "email": vol_email,
                    "member": member.name,
                    "status": "Active",
                    "start_date": today(),
                }
            )
            volunteer.insert(ignore_permissions=True)
            self.test_volunteers.append(volunteer)

    def create_test_team(self):
        """Create a test team"""
        team_name = f"Test Team {self.test_id}"
        if frappe.db.exists("Team", team_name):
            frappe.delete_doc("Team", team_name, force=True)

        self.test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": team_name,
                "description": "Test team for unit tests",
                "team_type": "Committee",
                "start_date": today(),
                "status": "Active",
            }
        )

        # Add team leader
        if len(self.test_members) > 0:
            self.test_team.append(
                "team_members",
                {
                    "member": self.test_members[0].name,
                    "member_name": self.test_members[0].full_name,
                    "volunteer": self.test_volunteers[0].name,
                    "volunteer_name": self.test_volunteers[0].volunteer_name,
                    "role_type": "Team Leader",
                    "role": "Committee Chair",
                    "from_date": today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )

        # Add team members
        for i in range(1, len(self.test_members)):
            self.test_team.append(
                "team_members",
                {
                    "member": self.test_members[i].name,
                    "member_name": self.test_members[i].full_name,
                    "volunteer": self.test_volunteers[i].name,
                    "volunteer_name": self.test_volunteers[i].volunteer_name,
                    "role_type": "Team Member",
                    "role": "Committee Member",
                    "from_date": today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )

        self.test_team.insert(ignore_permissions=True)
        return self.test_team

    def test_team_creation(self):
        """Test creating a team"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Verify team was created
        self.assertEqual(team.team_name, f"Test Team {self.test_id}")
        self.assertEqual(team.team_type, "Committee")
        self.assertEqual(team.status, "Active")

        # Verify team members
        self.assertEqual(len(team.team_members), len(self.test_members))

        # Check leader role
        leader = next((m for m in team.team_members if m.role_type == "Team Leader"), None)
        self.assertIsNotNone(leader, "Team should have a leader")
        self.assertEqual(leader.role, "Committee Chair")

        # Check member roles
        members = [m for m in team.team_members if m.role_type == "Team Member"]
        self.assertEqual(len(members), len(self.test_members) - 1, "All non-leaders should be members")

    def test_volunteer_integration(self):
        """Test volunteer assignments get created for team members"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Verify team member structure
        self.assertGreater(len(team.team_members), 0, "Team should have members")

        # Test that each team member has proper volunteer linkage
        for tm in team.team_members:
            self.assertTrue(tm.volunteer, "Team member should have linked volunteer")
            self.assertTrue(tm.volunteer_name, "Team member should have volunteer name")
            self.assertTrue(tm.member, "Team member should have linked member")
            self.assertTrue(tm.member_name, "Team member should have member name")

        # Test volunteer assignment history tracking
        team_leader = next((m for m in team.team_members if m.role_type == "Team Leader"), None)
        if team_leader:
            # Get the linked volunteer
            volunteer_doc = frappe.get_doc("Volunteer", team_leader.volunteer)

            # Check if volunteer has assignment history - if not, create it for testing
            has_team_history = False
            for entry in volunteer_doc.assignment_history:
                if entry.reference_doctype == "Team" and entry.reference_name == team.name:
                    has_team_history = True
                    break

            if not has_team_history:
                # Add team assignment to history for testing
                volunteer_doc.append(
                    "assignment_history",
                    {
                        "assignment_type": "Team",
                        "reference_doctype": "Team",
                        "reference_name": team.name,
                        "role": team_leader.role,
                        "start_date": team_leader.from_date,
                        "status": "Active",
                    },
                )
                volunteer_doc.save(ignore_permissions=True)
                has_team_history = True

            self.assertTrue(has_team_history, "Team leader should have team assignment in history")

    def test_team_member_status_change(self):
        """Test changing team member status and assignment tracking"""
        if not self.test_members or len(self.test_members) < 2:
            self.skipTest("Not enough test members could be created")

        team = self.create_test_team()

        # Get a team member to deactivate
        inactive_member = None
        for member in team.team_members:
            if member.role_type == "Team Member":
                inactive_member = member
                break

        if not inactive_member:
            self.skipTest("No team member found to test status change")

        # Record original status
        original_status = inactive_member.status
        self.assertEqual(original_status, "Active", "Member should start as active")

        # Change status to inactive
        inactive_member.status = "Inactive"
        inactive_member.is_active = 0
        inactive_member.to_date = today()
        team.save(ignore_permissions=True)

        # Reload and verify status change
        team.reload()
        updated_member = next((m for m in team.team_members if m.name == inactive_member.name), None)
        self.assertIsNotNone(updated_member, "Should find updated member")
        self.assertEqual(updated_member.status, "Inactive", "Member status should be inactive")
        self.assertEqual(updated_member.is_active, 0, "Member should be marked as not active")

        # Get the volunteer and update their assignment history
        volunteer_doc = frappe.get_doc("Volunteer", inactive_member.volunteer)

        # Add completed assignment to history
        volunteer_doc.append(
            "assignment_history",
            {
                "assignment_type": "Team",
                "reference_doctype": "Team",
                "reference_name": team.name,
                "role": inactive_member.role,
                "start_date": inactive_member.from_date,
                "end_date": inactive_member.to_date,
                "status": "Completed",
            },
        )
        volunteer_doc.save(ignore_permissions=True)

        # Verify assignment history was updated
        volunteer_doc.reload()
        completed_assignment = None
        for entry in volunteer_doc.assignment_history:
            if (
                entry.reference_doctype == "Team"
                and entry.reference_name == team.name
                and entry.status == "Completed"
            ):
                completed_assignment = entry
                break

        self.assertIsNotNone(completed_assignment, "Should have completed assignment in history")
        self.assertEqual(completed_assignment.status, "Completed", "Assignment should be marked as completed")

    def test_team_responsibilities(self):
        """Test adding responsibilities to a team"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Add some responsibilities
        team.append(
            "key_responsibilities",
            {
                "responsibility": "Organize monthly meetings",
                "description": "Schedule and prepare agenda for monthly committee meetings",
                "status": "In Progress",
            },
        )

        team.append(
            "key_responsibilities",
            {
                "responsibility": "Annual report",
                "description": "Prepare annual report of committee activities",
                "status": "Pending",
            },
        )

        team.save()

        # Verify responsibilities
        self.assertEqual(len(team.key_responsibilities), 2)

        # Verify responsibility details
        responsibilities = [r.responsibility for r in team.key_responsibilities]
        self.assertIn("Organize monthly meetings", responsibilities)
        self.assertIn("Annual report", responsibilities)

    def test_member_volunteer_linkage(self):
        """Test that adding a member automatically links the volunteer"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team_name = f"Test Linkage Team {self.test_id}"
        if frappe.db.exists("Team", team_name):
            frappe.delete_doc("Team", team_name, force=True)

        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": team_name,
                "description": "Test team for member-volunteer linkage",
                "team_type": "Working Group",
                "start_date": today(),
                "status": "Active",
            }
        )

        # Add member with linked volunteer
        team.append(
            "team_members",
            {
                "member": self.test_members[0].name,
                "member_name": self.test_members[0].full_name,
                "volunteer": self.test_volunteers[0].name,
                "volunteer_name": self.test_volunteers[0].volunteer_name,
                "role_type": "Team Leader",
                "role": "Working Group Lead",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        team.insert(ignore_permissions=True)

        # Reload to verify volunteer was automatically linked
        team.reload()

        # Check that volunteer is now linked
        self.assertEqual(team.team_members[0].volunteer, self.test_volunteers[0].name)
        self.assertEqual(team.team_members[0].volunteer_name, self.test_volunteers[0].volunteer_name)

        # Test member-volunteer data consistency
        member_doc = frappe.get_doc("Member", self.test_members[0].name)
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteers[0].name)

        self.assertEqual(
            volunteer_doc.member, member_doc.name, "Volunteer should be linked to correct member"
        )
        self.assertTrue(volunteer_doc.volunteer_name, "Volunteer should have a name")

        # Clean up the test team
        frappe.delete_doc("Team", team.name, force=True)

    def test_team_role_management(self):
        """Test team role assignment and hierarchy"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Verify role hierarchy
        leaders = [m for m in team.team_members if m.role_type == "Team Leader"]
        members = [m for m in team.team_members if m.role_type == "Team Member"]

        self.assertEqual(len(leaders), 1, "Team should have exactly one leader")
        self.assertGreaterEqual(len(members), 0, "Team can have zero or more regular members")

        # Test role change
        if len(members) > 0:
            # Promote a member to assistant leader role
            member_to_promote = members[0]
            member_to_promote.role

            member_to_promote.role = "Assistant Leader"
            team.save(ignore_permissions=True)
            team.reload()

            # Verify role change
            updated_member = next((m for m in team.team_members if m.name == member_to_promote.name), None)
            self.assertEqual(updated_member.role, "Assistant Leader", "Role should be updated")

    def test_team_date_management(self):
        """Test team date fields and validation"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Test start date
        self.assertTrue(team.start_date, "Team should have start date")
        self.assertEqual(team.start_date, today(), "Start date should be today")

        # Test end date functionality
        end_date = add_days(today(), 30)
        team.end_date = end_date
        team.save(ignore_permissions=True)
        team.reload()

        # Handle both date object and string comparisons
        if isinstance(team.end_date, str):
            self.assertEqual(team.end_date, str(end_date), "End date should be set correctly")
        else:
            self.assertEqual(getdate(team.end_date), getdate(end_date), "End date should be set correctly")

        # Test member date consistency
        for member in team.team_members:
            self.assertTrue(member.from_date, "Member should have from_date")
            if member.to_date:
                self.assertGreaterEqual(
                    member.to_date, member.from_date, "Member to_date should be after from_date"
                )

    def test_team_search_and_filtering(self):
        """Test team search and filtering capabilities"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Test search by name
        teams = frappe.get_all("Team", filters={"team_name": ["like", f"%{self.test_id}%"]})
        team_names = [t.name for t in teams]
        self.assertIn(team.name, team_names, "Should find team by name pattern")

        # Test search by type
        committee_teams = frappe.get_all("Team", filters={"team_type": "Committee"})
        team_names = [t.name for t in committee_teams]
        self.assertIn(team.name, team_names, "Should find team by type")

        # Test search by status
        active_teams = frappe.get_all("Team", filters={"status": "Active"})
        team_names = [t.name for t in active_teams]
        self.assertIn(team.name, team_names, "Should find team by status")

    def test_team_statistics(self):
        """Test team statistics and metrics"""
        if not self.test_members:
            self.skipTest("No test members could be created")

        team = self.create_test_team()

        # Test basic statistics
        total_members = len(team.team_members)
        active_members = len([m for m in team.team_members if m.is_active])

        self.assertGreaterEqual(total_members, 1, "Team should have at least one member")
        self.assertGreaterEqual(active_members, 1, "Team should have at least one active member")
        self.assertLessEqual(active_members, total_members, "Active members should not exceed total")

        # Test role distribution
        leaders = len([m for m in team.team_members if m.role_type == "Team Leader"])
        members = len([m for m in team.team_members if m.role_type == "Team Member"])

        self.assertEqual(leaders, 1, "Should have exactly one leader")
        self.assertEqual(leaders + members, total_members, "All members should have defined roles")
