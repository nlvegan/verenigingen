"""

Team Member Lifecycle Tests

Integration tests for team member assignment and removal workflows.
These tests were moved from the Team DocType controller to maintain
proper separation of concerns.
"""

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTeamMemberLifecycle(EnhancedTestCase):
    """Test team member lifecycle operations"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Team members reference Team Role master records by literal name (e.g. "Team Member").
        # The before_tests hook that normally seeds these is unreliable for single-module runs,
        # so seed the standard Team Roles here to make this module pass in isolation.
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def setUp(self):
        """Set up test data"""
        super().setUp()
        # Team membership changes update volunteer assignment history via background event
        # subscribers (enqueued with a delay). Run them inline so these lifecycle tests can
        # assert on the real subscriber side effects deterministically.
        self._prev_run_events_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True
        self.test_volunteer = self.create_test_volunteer()
        self.test_team = self.create_test_team()

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_run_events_sync
        super().tearDown()
    
    def test_team_member_addition(self):
        """Test that adding a team member creates assignment history"""
        
        # Add volunteer to team
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Test Role",
            "team_role": "Team Member",
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        })
        
        self.test_team.save()
        
        # Check if assignment history was created
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        active_assignment = None
        
        for assignment in volunteer_doc.assignment_history or []:
            if (assignment.reference_name == self.test_team.name and 
                assignment.status == "Active"):
                active_assignment = assignment
                break
        
        self.assertIsNotNone(active_assignment, "Active assignment should be created")
        self.assertEqual(active_assignment.assignment_type, "Team")
        self.assertEqual(active_assignment.reference_doctype, "Team")
    
    def test_team_member_deactivation(self):
        """Test that deactivating a team member completes assignment history"""
        
        # First add the member
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Test Role",
            "team_role": "Team Member",
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        })
        self.test_team.save()
        
        # Now deactivate the member
        team_member = self.test_team.team_members[0]
        team_member.is_active = 0
        team_member.to_date = frappe.utils.today()
        team_member.status = "Completed"
        
        self.test_team.save()
        
        # Check if assignment history was completed
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        volunteer_doc.reload()
        
        completed_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if (assignment.reference_name == self.test_team.name and 
                assignment.status == "Completed"):
                completed_assignment = assignment
                break
        
        self.assertIsNotNone(completed_assignment, "Assignment should be completed")
        self.assertIsNotNone(completed_assignment.end_date, "End date should be set")
    
    def test_team_member_complete_removal(self):
        """Test that completely removing a team member preserves assignment history"""
        
        # Add and then deactivate member first
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Test Role", 
            "team_role": "Team Member",
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        })
        self.test_team.save()
        
        # Deactivate
        team_member = self.test_team.team_members[0]
        team_member.is_active = 0
        team_member.to_date = frappe.utils.today()
        team_member.status = "Completed"
        self.test_team.save()
        
        # Now completely remove from team
        self.test_team.team_members = []
        self.test_team.save()
        
        # Check that assignment history is still preserved
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        volunteer_doc.reload()
        
        preserved_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if (assignment.reference_name == self.test_team.name and 
                assignment.status == "Completed"):
                preserved_assignment = assignment
                break
        
        self.assertIsNotNone(preserved_assignment, "Assignment history should be preserved")
    
    def test_team_member_role_change(self):
        """Test that changing a team member's role updates assignment history"""
        
        # Add member with initial role
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Initial Role",
            "team_role": "Team Member",
            "from_date": frappe.utils.today(),
            "is_active": 1,
            "status": "Active",
        })
        self.test_team.save()
        
        # Change the role
        team_member = self.test_team.team_members[0]
        team_member.role = "Changed Role"
        team_member.team_role = "Team Leader"
        self.test_team.save()
        
        # Check that assignment history reflects the change
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        volunteer_doc.reload()
        
        # Should have one completed and one active assignment
        completed_assignments = [a for a in volunteer_doc.assignment_history or [] 
                               if a.reference_name == self.test_team.name and a.status == "Completed"]
        active_assignments = [a for a in volunteer_doc.assignment_history or []
                            if a.reference_name == self.test_team.name and a.status == "Active"]
        
        self.assertEqual(len(completed_assignments), 1, "Should have one completed assignment")
        self.assertEqual(len(active_assignments), 1, "Should have one active assignment")
        
        # The active assignment should have the new role
        active_assignment = active_assignments[0]
        self.assertIn("Team Leader", active_assignment.role)
    
    def create_test_team(self):
        """Create a test team"""
        import time
        import uuid
        
        # Use timestamp + UUID to ensure uniqueness
        unique_id = f"{int(time.time())}-{str(uuid.uuid4())[:8]}"
        team_name = f"Test Team {unique_id}"
        
        # Clean up any existing team with this name first
        existing = DocumentExistenceValidator.check_document_exists("Team", {"team_name": team_name})
        if existing:
            frappe.delete_doc("Team", existing, force=True)
        
        team = frappe.get_doc({
            "doctype": "Team",
            "team_name": team_name,
            "status": "Active",
            "team_type": "Project Team",
            "start_date": frappe.utils.today(),
        })
        team.insert()
        return team