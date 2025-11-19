"""
Comprehensive tests for VolunteerActivityService

Tests the activity management logic for volunteers including adding activities,
ending activities, and validation logic.

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe.utils import today, add_days

from verenigingen.services.volunteer.activity_service import VolunteerActivityService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerActivityService(EnhancedTestCase):
    """Test suite for VolunteerActivityService"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test member and volunteer
        self.test_member = self.create_test_member(
            first_name="Activity",
            last_name="Tester",
            email="activitytester@example.com"
        )
        self.test_volunteer = self.create_test_volunteer(self.test_member.name)

    def test_add_activity_basic(self):
        """Test adding a basic activity"""
        service = VolunteerActivityService(self.test_volunteer.name)

        activity_name = service.add_activity(
            activity_type="Event",
            role="Organizer",
            description="Test event organization"
        )

        # Verify activity was created
        self.assertTrue(frappe.db.exists("Volunteer Activity", activity_name))

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.volunteer, self.test_volunteer.name)
        self.assertEqual(activity.activity_type, "Event")
        self.assertEqual(activity.role, "Organizer")
        self.assertEqual(activity.description, "Test event organization")
        self.assertEqual(activity.status, "Active")

    def test_add_activity_with_dates(self):
        """Test adding activity with custom start and end dates"""
        service = VolunteerActivityService(self.test_volunteer.name)

        start_date = add_days(today(), -7)
        end_date = add_days(today(), 7)

        activity_name = service.add_activity(
            activity_type="Project",
            role="Developer",
            start_date=start_date,
            end_date=end_date
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(str(activity.start_date), str(start_date))
        self.assertEqual(str(activity.end_date), str(end_date))

    def test_add_activity_with_reference(self):
        """Test adding activity with reference document"""
        # Create a test Event to reference
        event = frappe.get_doc({
            "doctype": "Event",
            "subject": "Test Event for Activity",
            "starts_on": today(),
            "event_type": "Public"
        })
        event.insert()

        service = VolunteerActivityService(self.test_volunteer.name)

        activity_name = service.add_activity(
            activity_type="Event",
            role="Volunteer",
            reference_doctype="Event",
            reference_name=event.name
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.reference_doctype, "Event")
        self.assertEqual(activity.reference_name, event.name)

    def test_add_activity_with_hours(self):
        """Test adding activity with estimated hours"""
        service = VolunteerActivityService(self.test_volunteer.name)

        activity_name = service.add_activity(
            activity_type="Workshop",
            role="Facilitator",
            estimated_hours=8.5,
            notes="Estimated 8.5 hours for workshop"
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.estimated_hours, 8.5)
        self.assertEqual(activity.notes, "Estimated 8.5 hours for workshop")

    def test_add_activity_missing_type(self):
        """Test that activity_type is required"""
        service = VolunteerActivityService(self.test_volunteer.name)

        with self.assertRaises(frappe.ValidationError):
            service.add_activity(
                activity_type=None,
                role="Tester"
            )

    def test_add_activity_missing_role(self):
        """Test that role is required"""
        service = VolunteerActivityService(self.test_volunteer.name)

        with self.assertRaises(frappe.ValidationError):
            service.add_activity(
                activity_type="Event",
                role=None
            )

    def test_add_activity_invalid_dates(self):
        """Test that end date cannot be before start date"""
        service = VolunteerActivityService(self.test_volunteer.name)

        with self.assertRaises(frappe.ValidationError):
            service.add_activity(
                activity_type="Project",
                role="Developer",
                start_date=today(),
                end_date=add_days(today(), -5)
            )

    def test_end_activity_basic(self):
        """Test ending an activity"""
        service = VolunteerActivityService(self.test_volunteer.name)

        # Create activity first
        activity_name = service.add_activity(
            activity_type="Training",
            role="Participant"
        )

        # End the activity
        service.end_activity(activity_name)

        # Verify activity was updated
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.status, "Completed")
        self.assertEqual(str(activity.end_date), str(today()))

    def test_end_activity_with_custom_date(self):
        """Test ending activity with custom end date"""
        service = VolunteerActivityService(self.test_volunteer.name)

        # Create activity
        activity_name = service.add_activity(
            activity_type="Campaign",
            role="Coordinator",
            start_date=add_days(today(), -30)
        )

        # End with custom date
        custom_end_date = add_days(today(), -1)
        service.end_activity(activity_name, end_date=custom_end_date)

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(str(activity.end_date), str(custom_end_date))
        self.assertEqual(activity.status, "Completed")

    def test_end_activity_with_notes(self):
        """Test ending activity with completion notes"""
        service = VolunteerActivityService(self.test_volunteer.name)

        # Create activity with existing notes
        activity_name = service.add_activity(
            activity_type="Workshop",
            role="Organizer",
            notes="Initial planning notes"
        )

        # End with completion notes
        service.end_activity(
            activity_name,
            notes="Successfully completed workshop with 25 participants"
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertIn("Successfully completed workshop", activity.notes)
        self.assertIn("Initial planning notes", activity.notes)

    def test_end_activity_validates_ownership(self):
        """Test that you can only end activities belonging to the volunteer"""
        # Create activity for first volunteer
        service1 = VolunteerActivityService(self.test_volunteer.name)
        activity_name = service1.add_activity(
            activity_type="Event",
            role="Helper"
        )

        # Create second volunteer
        other_member = self.create_test_member(
            first_name="Other",
            last_name="Volunteer",
            email="othervolunteer@example.com"
        )
        other_volunteer = self.create_test_volunteer(other_member.name)

        # Try to end activity from wrong volunteer
        service2 = VolunteerActivityService(other_volunteer.name)

        with self.assertRaises(frappe.ValidationError):
            service2.end_activity(activity_name)

    def test_end_activity_validates_end_date(self):
        """Test that end date cannot be before start date"""
        service = VolunteerActivityService(self.test_volunteer.name)

        # Create activity
        start_date = today()
        activity_name = service.add_activity(
            activity_type="Project",
            role="Developer",
            start_date=start_date
        )

        # Try to end with date before start
        with self.assertRaises(frappe.ValidationError):
            service.end_activity(
                activity_name,
                end_date=add_days(start_date, -5)
            )

    def test_end_nonexistent_activity(self):
        """Test error handling for nonexistent activity"""
        service = VolunteerActivityService(self.test_volunteer.name)

        with self.assertRaises(frappe.ValidationError):
            service.end_activity("NONEXISTENT-ACTIVITY-123")

    def test_activity_lifecycle_integration(self):
        """Test complete activity lifecycle"""
        service = VolunteerActivityService(self.test_volunteer.name)

        # Create activity
        activity_name = service.add_activity(
            activity_type="Community Organizing",
            role="Lead Organizer",
            description="Organize community events",
            start_date=add_days(today(), -14),
            estimated_hours=20.0,
            notes="Initial campaign planning"
        )

        # Verify initial state
        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.status, "Active")
        self.assertIsNone(activity.end_date)

        # End activity
        service.end_activity(
            activity_name,
            end_date=today(),
            notes="Campaign successfully completed"
        )

        # Verify final state
        activity.reload()
        self.assertEqual(activity.status, "Completed")
        self.assertEqual(str(activity.end_date), str(today()))
        self.assertIn("Campaign successfully completed", activity.notes)


class TestVolunteerActivityServiceEdgeCases(EnhancedTestCase):
    """Edge case tests for activity service"""

    def test_add_activity_defaults_start_date(self):
        """Test that start_date defaults to today if not provided"""
        member = self.create_test_member(
            first_name="Edge",
            last_name="Case",
            email="edgecase@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        service = VolunteerActivityService(volunteer.name)

        activity_name = service.add_activity(
            activity_type="Other",
            role="Tester"
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(str(activity.start_date), str(today()))

    def test_end_activity_defaults_end_date(self):
        """Test that end_date defaults to today if not provided"""
        member = self.create_test_member(
            first_name="Default",
            last_name="Date",
            email="defaultdate@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        service = VolunteerActivityService(volunteer.name)

        # Create and end activity
        activity_name = service.add_activity(
            activity_type="Training",
            role="Trainee"
        )
        service.end_activity(activity_name)

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(str(activity.end_date), str(today()))

    def test_add_activity_with_all_fields(self):
        """Test adding activity with all optional fields populated"""
        member = self.create_test_member(
            first_name="Complete",
            last_name="Activity",
            email="completeactivity@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        service = VolunteerActivityService(volunteer.name)

        activity_name = service.add_activity(
            activity_type="Coalition Work",
            role="Representative",
            description="Represent organization in coalition meetings",
            start_date=add_days(today(), -30),
            end_date=add_days(today(), 30),
            reference_doctype="Project",
            reference_name=None,  # No actual project, just testing field
            estimated_hours=15.5,
            notes="Monthly coalition attendance required"
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        self.assertEqual(activity.volunteer, volunteer.name)
        self.assertEqual(activity.activity_type, "Coalition Work")
        self.assertEqual(activity.role, "Representative")
        self.assertEqual(activity.description, "Represent organization in coalition meetings")
        self.assertEqual(activity.estimated_hours, 15.5)
        self.assertEqual(activity.notes, "Monthly coalition attendance required")

    def test_multiple_activities_same_volunteer(self):
        """Test creating multiple activities for same volunteer"""
        member = self.create_test_member(
            first_name="Multi",
            last_name="Activity",
            email="multiactivity@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        service = VolunteerActivityService(volunteer.name)

        # Create multiple activities
        activity1 = service.add_activity(
            activity_type="Event",
            role="Setup Crew"
        )
        activity2 = service.add_activity(
            activity_type="Workshop",
            role="Facilitator"
        )
        activity3 = service.add_activity(
            activity_type="Campaign",
            role="Volunteer"
        )

        # Verify all activities exist
        self.assertTrue(frappe.db.exists("Volunteer Activity", activity1))
        self.assertTrue(frappe.db.exists("Volunteer Activity", activity2))
        self.assertTrue(frappe.db.exists("Volunteer Activity", activity3))

        # Verify all belong to same volunteer
        for activity_name in [activity1, activity2, activity3]:
            activity = frappe.get_doc("Volunteer Activity", activity_name)
            self.assertEqual(activity.volunteer, volunteer.name)

    def test_end_activity_preserves_original_notes(self):
        """Test that ending activity preserves original notes"""
        member = self.create_test_member(
            first_name="Notes",
            last_name="Preservation",
            email="notespreserve@example.com"
        )
        volunteer = self.create_test_volunteer(member.name)

        service = VolunteerActivityService(volunteer.name)

        # Create activity with initial notes
        activity_name = service.add_activity(
            activity_type="Media/Advocacy",
            role="Spokesperson",
            notes="Media training completed on 2025-01-15"
        )

        # End activity with additional notes
        service.end_activity(
            activity_name,
            notes="Interview conducted successfully"
        )

        activity = frappe.get_doc("Volunteer Activity", activity_name)
        # Both original and completion notes should be present
        self.assertIn("Media training completed", activity.notes)
        self.assertIn("Interview conducted successfully", activity.notes)
