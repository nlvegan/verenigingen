"""
Test suite for VolunteerAssignmentService

Tests the assignment aggregation service that consolidates volunteer assignments
from multiple sources (Board positions, Teams, Activities) using optimized UNION queries.

Author: Verenigingen Development Team
License: MIT
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.services.volunteer.assignment_service import VolunteerAssignmentService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerAssignmentService(EnhancedTestCase):
    """Test suite for VolunteerAssignmentService"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # AssignmentQueryBuilder caches results on frappe.local (request-level
        # cache). In production this is cleared at request end, but the test
        # framework reuses one frappe.local across tests and rolls back the DB
        # via savepoints, which makes autonamed Volunteer names recur. A stale
        # cache entry keyed by a recurring volunteer name would leak a prior
        # test's results into this one, so clear it before and after each test.
        self._clear_assignment_cache()

        # Create test member and volunteer
        self.test_member = self.create_test_member(
            first_name="Assignment",
            last_name="Tester",
            email="assignmenttester@example.com",
        )
        self.test_volunteer = self.create_test_volunteer(self.test_member.name)

        # Create test chapter for tests that need it
        self.test_chapter = self.create_test_chapter()

        # Create test team for tests that need it
        self.test_team = self.create_test_team()

        # Create test team roles for team member assignments
        self.developer_role = self.ensure_team_role("Developer")
        self.designer_role = self.ensure_team_role("Designer")
        self.coordinator_role = self.ensure_team_role("Coordinator")

        # Ensure the Chapter Role records referenced by board-position tests exist.
        # The chapter_role link field (labeled "Board Role") points at the Chapter
        # Role doctype, so these named records must exist before appending board members.
        for chapter_role_name in ("Secretary", "Chair", "Treasurer"):
            self.factory.ensure_chapter_role(chapter_role_name)

    def tearDown(self):
        """Clear the request-level assignment cache so it cannot leak into the next test."""
        self._clear_assignment_cache()
        super().tearDown()

    @staticmethod
    def _clear_assignment_cache():
        """Drop the AssignmentQueryBuilder request-level cache from frappe.local."""
        if hasattr(frappe.local, "_volunteer_assignment_cache"):
            delattr(frappe.local, "_volunteer_assignment_cache")

    def test_get_aggregated_assignments_empty(self):
        """Test getting aggregated assignments when volunteer has none"""
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        self.assertIsInstance(assignments, list)
        self.assertEqual(len(assignments), 0)

    def test_get_aggregated_assignments_with_board_position(self):
        """Test aggregated assignments includes board positions"""
        # Create a test chapter
        test_chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Test Chapter Assignment {frappe.generate_hash(length=6)}",
                "chapter_head": self.test_member.name,
                "status": "Active",
            }
        )
        test_chapter.insert()

        # Add volunteer to chapter board
        test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                "email": self.test_volunteer.email,
                "chapter_role": "Treasurer",
                "from_date": today(),
                "is_active": 1,
            },
        )
        test_chapter.save()

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify board position is included
        self.assertEqual(len(assignments), 1)
        board_assignment = assignments[0]
        self.assertEqual(board_assignment["source_type"], "Board Position")
        self.assertEqual(board_assignment["source_doctype"], "Chapter Board Member")
        self.assertEqual(board_assignment["role"], "Treasurer")
        self.assertTrue(board_assignment["is_active"])
        self.assertEqual(board_assignment["editable"], False)  # Board positions are not editable

    def test_get_aggregated_assignments_with_team_membership(self):
        """Test aggregated assignments includes team memberships"""
        # Add volunteer to team
        self.test_team.append(
            "team_members",  # Correct child table name
            {
                "volunteer": self.test_volunteer.name,
                "team_role": self.developer_role.name,
                "from_date": today(),
                "status": "Active",
            },
        )
        self.test_team.save()

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify team membership is included
        self.assertEqual(len(assignments), 1)
        team_assignment = assignments[0]
        self.assertEqual(team_assignment["source_type"], "Team")
        self.assertEqual(team_assignment["role"], self.developer_role.name)
        self.assertTrue(team_assignment["is_active"])
        self.assertEqual(team_assignment["editable"], False)  # Team memberships are not editable

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

    def test_get_aggregated_assignments_multiple_sources(self):
        """Test aggregated assignments from multiple sources"""
        # Add board position
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                "email": self.test_volunteer.email,
                "chapter_role": "Secretary",
                "from_date": add_days(today(), -30),
                "is_active": 1,
            },
        )
        self.test_chapter.save()

        # Add team membership
        self.test_team.append(
            "team_members",  # Correct child table name
            {
                "volunteer": self.test_volunteer.name,
                "team_role": self.designer_role.name,
                "from_date": add_days(today(), -20),
                "status": "Active",
            },
        )
        self.test_team.save()

        # Add activity
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
                "role": "Organizer",
                "start_date": add_days(today(), -10),
                "status": "Active",
            }
        )
        activity.insert()

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify all three assignments are included
        self.assertEqual(len(assignments), 3)

        # Verify they're sorted by start date (newest first)
        self.assertEqual(assignments[0]["source_type"], "Activity")  # Most recent
        self.assertEqual(assignments[1]["source_type"], "Team")  # Middle
        self.assertEqual(assignments[2]["source_type"], "Board Position")  # Oldest

    def test_get_aggregated_assignments_only_active(self):
        """Test that only active assignments are returned"""
        # Add active board position
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                "email": self.test_volunteer.email,
                "chapter_role": "Chair",
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save()

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
        self.assertEqual(assignments[0]["source_type"], "Board Position")
        self.assertTrue(assignments[0]["is_active"])

    def test_get_volunteer_history_empty(self):
        """Test getting volunteer history when volunteer has none"""
        service = VolunteerAssignmentService(self.test_volunteer.name)
        history = service.get_volunteer_history()

        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)

    def test_get_volunteer_history_includes_all_assignments(self):
        """Test volunteer history includes both active and completed assignments"""
        # Add active board position
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                "email": self.test_volunteer.email,
                "chapter_role": "Treasurer",
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save()

        # Add completed activity
        completed_activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
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

        # Verify both assignment types are included
        # Note: May have more than 2 entries due to archived records from assignment_history child table
        # (hooks can automatically archive assignments when they're created)
        self.assertGreaterEqual(len(history), 2)

        # Verify both assignment types are present
        assignment_types = [h["assignment_type"] for h in history]
        self.assertIn("Board Position", assignment_types)
        self.assertIn("Event", assignment_types)

        # Verify newest entry is the active board position (most recent start_date)
        self.assertEqual(history[0]["assignment_type"], "Board Position")
        self.assertEqual(history[0]["status"], "Active")

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

    def test_has_active_assignments_board_position(self):
        """Test has_active_assignments detects active board position"""
        # Add active board position
        self.test_chapter.append(
            "board_members",
            {
                "volunteer": self.test_volunteer.name,
                "volunteer_name": self.test_volunteer.volunteer_name,
                "email": self.test_volunteer.email,
                "chapter_role": "Chair",
                "from_date": today(),
                "is_active": 1,
            },
        )
        self.test_chapter.save()

        service = VolunteerAssignmentService(self.test_volunteer.name)
        result = service.has_active_assignments()

        self.assertTrue(result)

    def test_has_active_assignments_team_membership(self):
        """Test has_active_assignments detects active team membership"""
        # Add active team membership
        self.test_team.append(
            "team_members",  # Correct child table name
            {
                "volunteer": self.test_volunteer.name,
                "team_role": self.coordinator_role.name,
                "from_date": today(),
                "status": "Active",
            },
        )
        self.test_team.save()

        service = VolunteerAssignmentService(self.test_volunteer.name)
        result = service.has_active_assignments()

        self.assertTrue(result)

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

    def test_aggregated_assignments_reference_links(self):
        """Test that activities with reference documents have proper links"""
        # Create activity with reference (skip link validation for test data)
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Event",
                "role": "Coordinator",
                "start_date": today(),
                "status": "Active",
                "reference_doctype": "Event",
                "reference_name": "EVENT-001",
            }
        )
        # Insert with ignore_links to skip link validation for non-existent Event reference
        activity.insert(ignore_links=True)

        # Get assignments
        service = VolunteerAssignmentService(self.test_volunteer.name)
        assignments = service.get_aggregated_assignments()

        # Verify reference information
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["reference_display"], "Event: EVENT-001")
        self.assertIn("/app/event/EVENT-001", assignments[0]["reference_link"])

    def test_service_initialization(self):
        """Test VolunteerAssignmentService initialization"""
        service = VolunteerAssignmentService(self.test_volunteer.name)

        self.assertEqual(service.volunteer_name, self.test_volunteer.name)
        self.assertIsNone(service.volunteer_doc)  # Lazy loaded

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


def run_tests():
    """Helper function to run tests from console"""
    import sys

    suite = unittest.TestLoader().loadTestsFromTestCase(TestVolunteerAssignmentService)
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_tests()
