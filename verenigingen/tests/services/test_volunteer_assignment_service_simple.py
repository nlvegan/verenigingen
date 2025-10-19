"""
Simplified tests for VolunteerAssignmentService focusing on core functionality

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.volunteer.assignment_service import VolunteerAssignmentService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerAssignmentServiceSimple(EnhancedTestCase):
    """Simplified test suite for VolunteerAssignmentService core functionality"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test member and volunteer
        self.test_member = self.create_test_member(
            first_name="Assignment",
            last_name="Tester",
            email="assignmenttest@example.com",
        )
        self.test_volunteer = self.create_test_volunteer(self.test_member.name)

    def test_service_initialization(self):
        """Test VolunteerAssignmentService initialization"""
        service = VolunteerAssignmentService(self.test_volunteer.name)

        self.assertEqual(service.volunteer_name, self.test_volunteer.name)
        self.assertIsNone(service.volunteer_doc)  # Lazy loaded

    def test_get_aggregated_assignments_empty(self):
        """Test getting aggregated assignments when volunteer has none"""
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        self.assertIsInstance(assignments, list)
        self.assertEqual(len(assignments), 0)

    def test_get_aggregated_assignments_with_activity(self):
        """Test aggregated assignments includes volunteer activities"""
        # Create a volunteer activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Workshop",
                "role": "Facilitator",
                "description": "Test workshop facilitation",
                "start_date": today(),
                "status": "Active",
            }
        )
        activity.insert()

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify activity is included
        self.assertEqual(len(assignments), 1)
        activity_assignment = assignments[0]
        self.assertEqual(activity_assignment["source_type"], "Activity")
        self.assertEqual(activity_assignment["role"], "Facilitator")
        self.assertTrue(activity_assignment["is_active"])
        self.assertEqual(activity_assignment["editable"], True)  # Activities are editable

    def test_get_aggregated_assignments_only_active(self):
        """Test that only active assignments are returned"""
        # Add active activity
        active_activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
                "role": "Organizer",
                "start_date": today(),
                "status": "Active",
            }
        )
        active_activity.insert()

        # Add inactive activity
        inactive_activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Training",
                "role": "Participant",
                "start_date": add_days(today(), -60),
                "end_date": add_days(today(), -30),
                "status": "Completed",
            }
        )
        inactive_activity.insert()

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify only active assignment is included
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["source_type"], "Activity")
        self.assertTrue(assignments[0]["is_active"])

    def test_get_volunteer_history_empty(self):
        """Test getting volunteer history when volunteer has none"""
        service = VolunteerAssignmentService(self.test_volunteer.name)
        history = service.get_volunteer_history()

        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)

    def test_get_volunteer_history_includes_all_assignments(self):
        """Test volunteer history includes both active and completed assignments"""
        # Add active activity
        active_activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
                "role": "Coordinator",
                "start_date": today(),
                "status": "Active",
            }
        )
        active_activity.insert()

        # Add completed activity
        completed_activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Workshop",
                "role": "Helper",
                "start_date": add_days(today(), -30),
                "end_date": add_days(today(), -29),
                "status": "Completed",
            }
        )
        completed_activity.insert()

        # Get history
        service = VolunteerAssignmentService(self.test_volunteer.name)
        history = service.get_volunteer_history()

        # Verify both assignments are included
        self.assertEqual(len(history), 2)

        # Verify they're sorted by start date (newest first)
        self.assertEqual(history[0]["assignment_type"], "Event")  # More recent
        self.assertEqual(history[0]["status"], "Active")
        self.assertEqual(history[1]["assignment_type"], "Workshop")  # Older
        self.assertEqual(history[1]["status"], "Completed")

    def test_get_volunteer_history_sorted_by_date(self):
        """Test volunteer history is sorted by start date (newest first)"""
        # Create multiple activities with different dates
        dates = [add_days(today(), -60), add_days(today(), -30), add_days(today(), -10)]

        for i, start_date in enumerate(dates):
            activity = frappe.get_doc(
                {
                    "doctype": "Volunteer Activity",
                    "volunteer": self.test_volunteer.name,
                    "activity_type": "Workshop",
                    "role": f"Role {i}",
                    "start_date": start_date,
                    "status": "Completed" if i < 2 else "Active",
                }
            )
            activity.insert()

        # Get history
        service = VolunteerAssignmentService(self.test_volunteer.name)
        history = service.get_volunteer_history()

        # Verify correct order (newest first)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["role"], "Role 2")  # Most recent
        self.assertEqual(history[1]["role"], "Role 1")  # Middle
        self.assertEqual(history[2]["role"], "Role 0")  # Oldest

    def test_has_active_assignments_none(self):
        """Test has_active_assignments when volunteer has no active assignments"""
        service = VolunteerAssignmentService(self.test_volunteer.name)
        result = service.has_active_assignments()

        self.assertFalse(result)

    def test_has_active_assignments_activity(self):
        """Test has_active_assignments detects active volunteer activity"""
        # Create active activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Project",
                "role": "Lead",
                "start_date": today(),
                "status": "Active",
            }
        )
        activity.insert()

        service = VolunteerAssignmentService(self.test_volunteer.name)
        result = service.has_active_assignments()

        self.assertTrue(result)

    def test_has_active_assignments_only_completed(self):
        """Test has_active_assignments returns false when only completed assignments exist"""
        # Create completed activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Training",
                "role": "Participant",
                "start_date": add_days(today(), -30),
                "end_date": add_days(today(), -29),
                "status": "Completed",
            }
        )
        activity.insert()

        service = VolunteerAssignmentService(self.test_volunteer.name)
        result = service.has_active_assignments()

        self.assertFalse(result)

    def test_lazy_loading_volunteer_doc(self):
        """Test that volunteer document is lazy loaded"""
        service = VolunteerAssignmentService(self.test_volunteer.name)

        # Initially None
        self.assertIsNone(service.volunteer_doc)

        # Load via private method
        volunteer_doc = service._load_volunteer()

        # Now loaded
        self.assertIsNotNone(service.volunteer_doc)
        self.assertEqual(volunteer_doc.name, self.test_volunteer.name)

        # Subsequent calls return cached instance
        volunteer_doc2 = service._load_volunteer()
        self.assertIs(volunteer_doc, volunteer_doc2)

    def test_delegation_from_volunteer_doctype(self):
        """Test that Volunteer DocType properly delegates to service"""
        # Create an activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Workshop",
                "role": "Trainer",
                "start_date": today(),
                "status": "Active",
            }
        )
        activity.insert()

        # Call via Volunteer DocType method
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        assignments = volunteer_doc.get_aggregated_assignments()

        # Verify delegation worked
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["source_type"], "Activity")
        self.assertEqual(assignments[0]["role"], "Trainer")

    def test_delegation_get_volunteer_history(self):
        """Test that get_volunteer_history delegates to service"""
        # Create an activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
                "role": "Helper",
                "start_date": add_days(today(), -7),
                "end_date": add_days(today(), -6),
                "status": "Completed",
            }
        )
        activity.insert()

        # Call via Volunteer DocType method
        volunteer_doc = frappe.get_doc("Volunteer", self.test_volunteer.name)
        history = volunteer_doc.get_volunteer_history()

        # Verify delegation worked
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["assignment_type"], "Event")
        self.assertEqual(history[0]["status"], "Completed")
