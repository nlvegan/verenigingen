# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.test_base import VereningingenTestCase


class TestVolunteerActivity(VereningingenTestCase):
    def setUp(self):
        # Initialize the docs to delete list
        self._docs_to_delete = []

        # Create test data
        self.test_member = self.create_test_member()
        self._docs_to_delete.append(("Member", self.test_member.name))

        self.test_volunteer = self.create_test_volunteer(self.test_member)
        self._docs_to_delete.append(("Volunteer", self.test_volunteer.name))

    def tearDown(self):
        # Clean up test data
        for doctype, name in self._docs_to_delete:
            try:
                frappe.delete_doc(doctype, name, force=True)
            except Exception:
                pass

    def create_test_activity(self):
        """Create a test volunteer activity"""
        activity = frappe.get_doc(
            {
                "doctype": "Volunteer Activity",
                "volunteer": self.test_volunteer.name,
                "activity_type": "Project",
                "role": "Project Coordinator",
                "description": "Test volunteer activity",
                "status": "Active",
                "start_date": today(),
            }
        )
        activity.insert(ignore_permissions=True)
        self._docs_to_delete.append(("Volunteer Activity", activity.name))
        return activity

    def test_activity_creation(self):
        """Test creating a volunteer activity"""
        activity = self.create_test_activity()

        # Basic validation
        self.assertEqual(activity.volunteer, self.test_volunteer.name)
        self.assertEqual(activity.status, "Active")

    def test_activity_completion(self):
        """Test completing a volunteer activity"""
        activity = self.create_test_activity()

        # Get today's date as a date object for proper comparison later
        today_date = getdate(today())

        # Set activity to completed
        activity.status = "Completed"
        activity.end_date = today()
        activity.actual_hours = 10
        activity.save()

        # Reload activity to get fresh data
        activity.reload()

        # Verify activity updated correctly
        self.assertEqual(activity.status, "Completed")

        # Convert activity.end_date to string for comparison if needed
        if isinstance(activity.end_date, str):
            self.assertEqual(activity.end_date, today())
        else:
            # Compare date objects
            self.assertEqual(activity.end_date, today_date)

        self.assertEqual(activity.actual_hours, 10)

        # Reload volunteer to check if activity was added to history
        self.test_volunteer.reload()

        # Check assignment history for this activity
        has_history_entry = False
        for entry in self.test_volunteer.assignment_history:
            if (
                entry.reference_doctype == "Volunteer Activity"
                and entry.reference_name == activity.name
                and entry.status == "Completed"
            ):
                has_history_entry = True
                break

        self.assertTrue(has_history_entry, "Activity should be recorded in volunteer's assignment history")

    def test_date_validation(self):
        """Test date validation in volunteer activity"""
        activity = self.create_test_activity()

        # Try to set end date before start date (should raise exception)
        with self.assertRaises(Exception):
            activity.end_date = add_days(today(), -10)  # 10 days before start date
            activity.save()

    def test_activity_deletion(self):
        """Test deletion of activity and its effect on volunteer record"""
        activity = self.create_test_activity()

        # First complete the activity to add it to history
        activity.status = "Completed"
        activity.end_date = today()
        activity.save()

        # Reload volunteer to check history
        self.test_volunteer.reload()

        # Verify activity is in history
        history_before_count = len(self.test_volunteer.assignment_history)

        # Now delete the activity
        activity.delete()

        # Reload volunteer again
        self.test_volunteer.reload()

        # History should now have one less entry
        history_after_count = len(self.test_volunteer.assignment_history)

        # This test might fail if on_trash isn't working correctly
        # In a real implementation, the history entry should be removed when the activity is deleted
        self.assertEqual(
            history_before_count - 1,
            history_after_count,
            "Activity entry should be removed from volunteer history when deleted",
        )
