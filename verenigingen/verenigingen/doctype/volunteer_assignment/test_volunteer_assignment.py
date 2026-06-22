# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.volunteer.assignment_query_builder import AssignmentQueryBuilder
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerAssignment(EnhancedTestCase):
    def setUp(self):
        super().setUp()  # EnhancedTestCase handles permissions and factory setup

        # The assignment aggregation cache lives on frappe.local and is keyed by
        # volunteer name, which repeats across rolled-back tests (sequential
        # autoname). Clear it so a prior test's cached history can't mask the
        # assignments this test creates (e.g. get_volunteer_history()).
        AssignmentQueryBuilder.clear_request_cache()

        # Create test data
        self.test_member = self.create_test_member()
        self.test_volunteer = self.create_test_volunteer(self.test_member)

    def tearDown(self):
        # EnhancedTestCase handles cleanup automatically via database rollback
        super().tearDown()

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
        # Use timestamp-based unique suffix to avoid collisions
        import time

        unique_suffix = str(int(time.time() * 1000000) % 1000000)

        # Create a test region first
        test_region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Test Region {unique_suffix}",
                "region_code": f"TR{unique_suffix[:3]}",
            }
        )
        test_region.insert()

        # Create a test chapter (Chapter uses 'prompt' autoname, so we must set the name)
        # Chapter name validation only allows letters, numbers, spaces, hyphens and underscores
        chapter_name = f"Test Chapter {unique_suffix}"
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": chapter_name,
                "chapter_head": self.test_member.name,
                "region": test_region.name,
                "introduction": "Test chapter for assignment tests",
            }
        )
        chapter.insert()

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
