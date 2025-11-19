"""
Test Team Background Job Integration

Tests the asynchronous background job path for team member changes.
This complements the synchronous tests in test_team_member_lifecycle.py
by specifically testing the on_update() → background jobs path.

Critical: These tests verify that background job handlers properly accept
the **kwargs parameters passed by frappe.enqueue().
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTeamBackgroundJobs(EnhancedTestCase):
    """Test team background job processing for member changes"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.test_volunteer = self.create_test_volunteer()

        # Create team with unique name for this test
        import time
        import uuid
        unique_id = f"{int(time.time())}-{str(uuid.uuid4())[:8]}"

        self.test_team = frappe.get_doc({
            "doctype": "Team",
            "team_name": f"BG Job Test Team {unique_id}",
            "status": "Active",
            "team_type": "Project Team",
            "start_date": today(),
        })
        self.test_team.insert()
        frappe.db.commit()

        # Reload to simulate existing team
        self.test_team = frappe.get_doc("Team", self.test_team.name)

    def test_background_job_parameter_acceptance(self):
        """
        Test that background job handlers accept **kwargs parameters.

        This is a regression test for the bug where handlers like
        handle_role_profile_assignments() didn't accept **kwargs,
        causing TypeError: unexpected keyword argument 'dedupe'
        """
        # Get initial assignment count
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        initial_count = len(volunteer_doc.assignment_history or [])

        # Add member to EXISTING team - triggers on_update() path
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Background Job Test",
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active",
        })

        # Save triggers on_update() → background job emission
        self.test_team.save()
        frappe.db.commit()

        # Process background jobs synchronously in test mode
        # frappe.enqueue() in tests runs immediately by default
        # but we need to ensure all jobs complete
        try:
            # Try to flush any pending jobs if the method exists
            if hasattr(frappe, 'enqueue') and hasattr(frappe.enqueue, 'flush'):
                frappe.enqueue.flush()
        except Exception:
            pass

        # Wait a moment for background processing
        import time
        time.sleep(2)

        # Reload volunteer to check if assignment history was updated
        volunteer_doc.reload()
        new_count = len(volunteer_doc.assignment_history or [])

        # Check if assignment was created via background job
        # Note: This might be created immediately via handle_team_member_changes()
        # but we're primarily testing that background jobs don't crash
        found_assignment = False
        for assignment in volunteer_doc.assignment_history:
            if (assignment.reference_name == self.test_team.name and
                assignment.status == "Active"):
                found_assignment = True
                break

        # The key test: Verify NO errors in error log from background jobs
        recent_errors = frappe.get_all(
            "Error Log",
            filters={
                "creation": [">=", frappe.utils.add_to_date(frappe.utils.now(), hours=-1)],
                "error": ["like", "%team_subscribers%"]
            },
            fields=["name", "error"],
            limit=10
        )

        # Filter for **kwargs errors specifically
        kwargs_errors = [
            e for e in recent_errors
            if "unexpected keyword argument 'dedupe'" in e.error
            or "unexpected keyword argument" in e.error
        ]

        self.assertEqual(
            len(kwargs_errors), 0,
            f"Background job handlers should accept **kwargs parameters. Found errors: {kwargs_errors}"
        )

        # Also verify assignment was created (either sync or async)
        self.assertTrue(
            found_assignment,
            "Assignment history should be created for team member addition"
        )

    def test_role_profile_assignment_background_job(self):
        """
        Test that role profile assignment background job runs without errors.

        Tests handle_role_profile_assignments() specifically.
        """
        # Add member which should trigger role profile assignment
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Profile Test",
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active",
        })

        # This should emit team_membership_changed event
        # Which queues handle_role_profile_assignments background job
        self.test_team.save()
        frappe.db.commit()

        # Wait for background processing
        import time
        time.sleep(2)

        # Check for errors specific to handle_role_profile_assignments
        errors = frappe.get_all(
            "Error Log",
            filters={
                "creation": [">=", frappe.utils.add_to_date(frappe.utils.now(), hours=-1)],
                "error": ["like", "%handle_role_profile_assignments%"]
            },
            limit=5
        )

        kwargs_errors = [
            e for e in errors
            if "unexpected keyword argument" in frappe.get_doc("Error Log", e.name).error
        ]

        self.assertEqual(
            len(kwargs_errors), 0,
            f"handle_role_profile_assignments should not crash with kwargs errors: {kwargs_errors}"
        )

    def test_member_addition_to_existing_team_full_workflow(self):
        """
        Integration test: Add member to existing team and verify full workflow.

        Tests the complete on_update() → background jobs → assignment history path.
        """
        # Verify team exists and has no members
        self.assertEqual(len(self.test_team.team_members or []), 0)

        # Get initial volunteer assignment count
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        initial_assignments = len([
            a for a in volunteer_doc.assignment_history or []
            if a.reference_name == self.test_team.name
        ])

        # Add member to existing team
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Integration Test Member",
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active",
        })

        # Save triggers on_update() which emits events
        self.test_team.save()
        frappe.db.commit()

        # Wait for background processing
        import time
        time.sleep(2)

        # Verify assignment history was updated
        volunteer_doc.reload()
        new_assignments = len([
            a for a in volunteer_doc.assignment_history or []
            if a.reference_name == self.test_team.name and a.status == "Active"
        ])

        self.assertGreater(
            new_assignments, initial_assignments,
            "Assignment history should be created when adding member to existing team"
        )

        # Verify the assignment details
        active_assignment = None
        for a in volunteer_doc.assignment_history:
            if a.reference_name == self.test_team.name and a.status == "Active":
                active_assignment = a
                break

        self.assertIsNotNone(active_assignment)
        self.assertEqual(active_assignment.assignment_type, "Team")
        self.assertEqual(active_assignment.reference_doctype, "Team")

    def test_member_role_change_on_existing_team(self):
        """
        Test that changing a member's role on existing team triggers background jobs.
        """
        # First add a member
        self.test_team.append("team_members", {
            "volunteer": self.test_volunteer.name,
            "volunteer_name": self.test_volunteer.volunteer_name,
            "role": "Initial Role",
            "team_role": "Team Member",
            "from_date": today(),
            "is_active": 1,
            "status": "Active",
        })
        self.test_team.save()
        frappe.db.commit()

        import time
        time.sleep(1)

        # Reload team
        self.test_team = frappe.get_doc("Team", self.test_team.name)

        # Change the role
        member = self.test_team.team_members[0]
        member.role = "Changed Role"
        member.team_role = "Team Leader"

        # This triggers on_update() → role_changed event → background jobs
        self.test_team.save()
        frappe.db.commit()

        time.sleep(2)

        # Check no background job errors
        errors = frappe.get_all(
            "Error Log",
            filters={
                "creation": [">=", frappe.utils.add_to_date(frappe.utils.now(), minutes=-5)],
                "error": ["like", "%team_subscribers%"]
            },
            limit=10
        )

        kwargs_errors = [
            e for e in errors
            if "unexpected keyword argument" in frappe.get_doc("Error Log", e.name).error
        ]

        self.assertEqual(
            len(kwargs_errors), 0,
            "Role change should not trigger background job parameter errors"
        )

    def test_all_team_subscriber_handlers_exist_and_accept_kwargs(self):
        """
        Meta-test: Verify all handler functions exist and have correct signatures.

        This prevents future regression where new handlers are added without **kwargs.
        """
        from verenigingen.events import team_events
        import inspect

        # Get all event subscribers
        event_types = ["team_membership_changed", "team_settings_changed", "team_leadership_changed"]

        for event_type in event_types:
            subscribers = team_events._get_team_event_subscribers(event_type)

            self.assertGreater(
                len(subscribers), 0,
                f"Event {event_type} should have at least one subscriber"
            )

            for subscriber_path in subscribers:
                # Import the handler function
                module_path, function_name = subscriber_path.rsplit(".", 1)
                module = frappe.get_module(module_path)
                handler = getattr(module, function_name)

                # Check function signature
                sig = inspect.signature(handler)
                params = list(sig.parameters.keys())

                # Should have event_name, event_data, **kwargs
                self.assertIn(
                    "event_name", params,
                    f"{subscriber_path} should have 'event_name' parameter"
                )
                self.assertIn(
                    "event_data", params,
                    f"{subscriber_path} should have 'event_data' parameter"
                )

                # Check for **kwargs
                has_kwargs = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )

                self.assertTrue(
                    has_kwargs,
                    f"{subscriber_path} MUST accept **kwargs to handle frappe.enqueue() parameters "
                    f"(dedupe, delay, timeout, etc.). Current signature: {sig}"
                )

    def tearDown(self):
        """Clean up test data"""
        try:
            # Remove volunteer from team
            if hasattr(self, 'test_team'):
                team = frappe.get_doc("Team", self.test_team.name)
                team.team_members = []
                team.save()
                frappe.db.commit()

            # Clean up volunteer assignment history
            if hasattr(self, 'test_volunteer'):
                volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
                assignments_to_remove = []
                for assignment in volunteer_doc.assignment_history or []:
                    if hasattr(self, 'test_team') and assignment.reference_name == self.test_team.name:
                        assignments_to_remove.append(assignment)

                for assignment in assignments_to_remove:
                    volunteer_doc.assignment_history.remove(assignment)

                if assignments_to_remove:
                    volunteer_doc.save()
                    frappe.db.commit()
        except Exception:
            pass

        super().tearDown()
