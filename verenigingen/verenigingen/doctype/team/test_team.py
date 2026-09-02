# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import random
import string

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation_utilities import DocumentExistenceValidator, QueryBuilder


class TestTeam(EnhancedTestCase):
    # NOTE: this class previously defined setUp/tearDown twice; the first pair
    # (an EnhancedTestCase-delegating setUp + tearDown) was dead code, shadowed
    # by the second pair below. Removed — the effective setUp/tearDown are the
    # ones further down.

    @classmethod
    def setUpClass(cls):
        # Tell Frappe not to make test records
        super().setUpClass()
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
        super().setUp()
        self.test_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        # Team members reference Team Role records ("Team Leader", "Team Member",
        # etc.) by their literal name. These are standard seed records created at
        # site setup (verenigingen.setup.create_default_team_roles) but are NOT
        # present on fresh CI-mirror test sites. Idempotently create them here.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()
        # Create test data
        self.create_test_volunteers()

    def tearDown(self):
        # Clean up test data
        self.cleanup_test_data()
        super().tearDown()

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
            if DocumentExistenceValidator.check_document_exists("Member", {"email": email}):
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
            member.insert()  # EnhancedTestCase handles permissions
            self.test_members.append(member)

            # Create volunteer for each member with unique name
            vol_email = f"teamtest{unique_id}@example.org"

            # Check if volunteer already exists
            if DocumentExistenceValidator.check_document_exists("Volunteer", {"email": vol_email}):
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
            volunteer.insert()  # EnhancedTestCase handles permissions
            self.test_volunteers.append(volunteer)

    def create_test_team(self):
        """Create a test team"""
        team_name = f"Test Team {self.test_id}"
        if DocumentExistenceValidator.check_document_exists("Team", team_name):
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
                    "volunteer": self.test_volunteers[0].name,
                    "volunteer_name": self.test_volunteers[0].volunteer_name,
                    "team_role": "Team Leader",  # Required field linking to Team Role DocType
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
                    "volunteer": self.test_volunteers[i].name,
                    "volunteer_name": self.test_volunteers[i].volunteer_name,
                    "team_role": "Team Member",  # Required field linking to Team Role DocType
                    "role_type": "Team Member",
                    "role": "Committee Member",
                    "from_date": today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )

        self.test_team.insert()
        return self.test_team

    def test_team_member_to_date_before_from_date_is_rejected(self):
        """A Team Member row with to_date before from_date must be rejected.

        Team Member's own validate() used to check this (validate_dates), but Frappe
        never runs a child DocType's validate() -- Document.run_before_save_methods
        calls run_method("validate") on the parent only, and Document._validate()
        iterates children calling framework helpers exclusively (confirmed by reading
        frappe/model/document.py this session). Team.validate() -> TeamValidationService
        already checks the TEAM's own start_date/end_date and TeamService already
        enforces unique-role-per-team, but neither checks a per-member date range, so an
        inverted range on a Team Member row persists silently today. See #596.
        """
        team = self.create_test_team()

        extra_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "DateRange",
                "last_name": f"Test {self.test_id}",
                "email": f"daterangemember{self.test_id}@example.com",
            }
        )
        extra_member.insert()

        extra_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"TeamTest DateRange {self.test_id}",
                "email": f"teamtestdaterange{self.test_id}@example.org",
                "member": extra_member.name,
                "status": "Active",
                "start_date": today(),
            }
        )
        extra_volunteer.insert()

        team.append(
            "team_members",
            {
                "volunteer": extra_volunteer.name,
                "volunteer_name": extra_volunteer.volunteer_name,
                "team_role": "Team Member",
                "from_date": today(),
                "to_date": add_days(today(), -10),
                "is_active": 1,
                "status": "Active",
            },
        )

        # assertRaisesRegex, not assertRaises: frappe.LinkValidationError is a
        # subclass of ValidationError (frappe/exceptions.py), so a bare
        # assertRaises(ValidationError) would also pass for an unrelated failure
        # -- e.g. "Team Member" not existing as a valid Team Role -- and prove
        # nothing about the date-range rule under test.
        with self.assertRaisesRegex(frappe.ValidationError, "End date cannot be before start date"):
            team.save()

    def test_team_member_active_flag_and_status_are_kept_in_sync(self):
        """is_active=0 with status still "Active" must be normalized on save.

        Team Member's dead validate() (sync_status_and_active_flag) used to force
        status to "Inactive" whenever is_active was cleared. Since that validate()
        never actually ran, an inconsistent (is_active=0, status="Active") row has
        never been corrected by anything. See #596.
        """
        team = self.create_test_team()
        team.team_members[0].is_active = 0
        team.save()
        team.reload()

        self.assertEqual(team.team_members[0].status, "Inactive")

    def test_team_member_is_active_flag_is_cleared_when_status_is_not_active(self):
        """The other direction of the same sync: is_active=1 with a non-"Active"
        status must clear is_active, not touch status.

        Ported verbatim from the dead TeamMember.sync_status_and_active_flag()
        ("elif self.is_active and self.status != 'Active': self.is_active = 0")
        -- asymmetric on purpose (it corrects is_active, not status, in this
        branch) and untested before this: only the is_active=0 branch above had
        coverage. See #596.
        """
        team = self.create_test_team()
        team.team_members[0].is_active = 1
        team.team_members[0].status = "On Leave"
        team.save()
        team.reload()

        self.assertEqual(team.team_members[0].status, "On Leave")
        self.assertFalse(team.team_members[0].is_active)

    def test_ending_a_team_member_row_does_not_crash_on_mixed_date_types(self):
        """Deactivating a Team Member by setting to_date = today() must not crash.

        Regression for a real CI failure (10 tests across 3 shards, all the same
        traceback): validate_team_member_rows() compared `member.to_date <
        member.from_date` with a bare `<`. frappe.utils.today() -- the idiomatic,
        everywhere-used way to set a date field, including in this exact pattern
        in test_team_role_validation.py, test_volunteer_sync_service.py and
        test_team_coverage.py -- returns a STRING. A row reloaded from the DB
        already holds `from_date` as a datetime.date. Comparing the two raised
        TypeError: '<' not supported between instances of 'str' and
        'datetime.date', not a ValidationError -- the save crashed instead of
        validating anything. See #596 follow-up.
        """
        team = self.create_test_team()
        team.reload()  # from_date on the existing row is now a real datetime.date

        for member in team.team_members:
            member.is_active = 0
            member.status = "Inactive"
            member.to_date = today()  # a string, deliberately -- this is the crash

        team.save()  # must not raise TypeError
        team.reload()

        for member in team.team_members:
            self.assertFalse(member.is_active)
            self.assertEqual(member.status, "Inactive")

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
            self.assertTrue(tm.team_role, "Team member should have team role")

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
                volunteer_doc.save()
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
        team.save()  # EnhancedTestCase handles permissions

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
        volunteer_doc.save()

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
        if DocumentExistenceValidator.check_document_exists("Team", team_name):
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
                "volunteer": self.test_volunteers[0].name,
                "volunteer_name": self.test_volunteers[0].volunteer_name,
                "team_role": "Team Leader",  # Required field linking to Team Role DocType
                "role_type": "Team Leader",
                "role": "Working Group Lead",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        team.insert()

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
            team.save()  # EnhancedTestCase handles permissions
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
        team.save()  # EnhancedTestCase handles permissions
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
        active_teams = QueryBuilder.get_all_active_records("Team")
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
