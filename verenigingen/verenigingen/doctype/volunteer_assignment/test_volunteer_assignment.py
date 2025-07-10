# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import random

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.test_base import VereningingenTestCase


class TestVolunteerAssignment(VereningingenTestCase):
    def setUp(self):
        # Initialize the cleanup list
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

    def test_basic_assignment(self):
        """Test creating a basic assignment in assignment_history without external references"""
        # Use 'Other' assignment type that doesn't require external references
        self.test_volunteer.append(
            "assignment_history",
            {"assignment_type": "Other", "role": "Test Role", "start_date": today(), "status": "Active"},
        )
        self.test_volunteer.save()

        # Verify assignment was created
        self.assertEqual(len(self.test_volunteer.assignment_history), 1)
        self.assertEqual(self.test_volunteer.assignment_history[0].assignment_type, "Other")
        self.assertEqual(self.test_volunteer.assignment_history[0].role, "Test Role")

    def test_board_assignment(self):
        """Test creating a board position assignment"""
        # Create a test chapter with name
        chapter_name = f"Test_Chapter_{random.randint(1000, 9999)}"

        if not frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": chapter_name,  # Explicitly set name
                    "chapter_head": self.test_member.name,
                    "region": "Test Region",
                    "introduction": "Test chapter for assignment tests",
                }
            )
            chapter.insert()
            self._docs_to_delete.append(("Chapter", chapter_name))

        # Add board assignment to assignment_history
        self.test_volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Board Position",
                "reference_doctype": "Chapter",
                "reference_name": chapter_name,
                "role": "Test Board Role",
                "start_date": today(),
                "status": "Active",
            },
        )
        self.test_volunteer.save()

        # Verify assignment was created
        self.assertEqual(len(self.test_volunteer.assignment_history), 1)
        self.assertEqual(self.test_volunteer.assignment_history[0].assignment_type, "Board Position")
        self.assertEqual(self.test_volunteer.assignment_history[0].reference_doctype, "Chapter")
        self.assertEqual(self.test_volunteer.assignment_history[0].reference_name, chapter_name)

    def test_assignment_dates(self):
        """Test assignment date validations"""
        # Use an assignment without external references
        self.test_volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Other",  # Other doesn't require references
                "role": "Test Role",
                "start_date": today(),
                "status": "Active",
            },
        )
        self.test_volunteer.save()

        # Update with an invalid end date
        assignment = self.test_volunteer.assignment_history[0]
        assignment.end_date = add_days(today(), -10)  # End date before start date

        # Should raise validation error
        with self.assertRaises(Exception):
            self.test_volunteer.save()

    def test_assignment_completion(self):
        """Test completing an assignment"""
        # Create an assignment without external references
        self.test_volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Other",  # Other doesn't require references
                "role": "Test Role",
                "start_date": add_days(today(), -30),
                "status": "Active",
            },
        )
        self.test_volunteer.save()

        # Get the assignment and update its status
        assignment = self.test_volunteer.assignment_history[0]
        assignment.status = "Completed"
        assignment.end_date = today()
        self.test_volunteer.save()

        # Reload volunteer
        self.test_volunteer.reload()

        # Verify assignment was updated
        self.assertEqual(self.test_volunteer.assignment_history[0].status, "Completed")
        self.assertEqual(getdate(self.test_volunteer.assignment_history[0].end_date), getdate(today()))

    def test_volunteer_history(self):
        """Test retrieving volunteer assignment history"""
        # Add assignment without external reference
        self.test_volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Other",  # Other doesn't require references
                "role": "Active Role",
                "start_date": today(),
                "status": "Active",
            },
        )

        # Add another completed assignment
        self.test_volunteer.append(
            "assignment_history",
            {
                "assignment_type": "Other",  # Other doesn't require references
                "role": "Completed Role",
                "start_date": add_days(today(), -100),
                "end_date": add_days(today(), -10),
                "status": "Completed",
            },
        )

        self.test_volunteer.save()

        # Get volunteer history if the method exists
        if hasattr(self.test_volunteer, "get_volunteer_history"):
            history = self.test_volunteer.get_volunteer_history()

            # Verify history content
            self.assertEqual(len(history), 2)

            # Check both assignments are in history
            statuses = [item.get("status") for item in history]
            self.assertIn("Active", statuses)
            self.assertIn("Completed", statuses)
        else:
            # Otherwise just check the assignment_history field
            self.assertEqual(len(self.test_volunteer.assignment_history), 2)

            # Verify both statuses exist
            statuses = [a.status for a in self.test_volunteer.assignment_history]
            self.assertIn("Active", statuses)
            self.assertIn("Completed", statuses)
