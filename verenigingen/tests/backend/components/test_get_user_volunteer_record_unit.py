#!/usr/bin/env python3
"""
Unit tests specifically for get_user_volunteer_record function to prevent field omission bugs
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestGetUserVolunteerRecordUnit(VereningingenTestCase):
    """Unit tests for get_user_volunteer_record function"""

    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()

        # Create test member using factory method
        self.test_member = self.create_test_member(
            first_name="Unit",
            last_name="Test",
            email="unit.test@example.com"
        )

        # Create test volunteer linked to member using factory method
        self.test_volunteer = self.create_test_volunteer(
            member=self.test_member,
            volunteer_name="Unit Test Volunteer",
            email="unit.test@example.com"
        )

    def test_function_returns_all_required_fields(self):
        """Test that get_user_volunteer_record returns all required fields"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        with self.as_user(self.test_volunteer.email):
            result = get_user_volunteer_record()

            # Verify all required fields are present
            required_fields = ["name", "volunteer_name", "member"]

            self.assertIsNotNone(result, "Function should return a result")
            self.assertIsInstance(result, frappe._dict, "Result should be a frappe._dict")

            for field in required_fields:
                self.assertIn(field, result, f"Result must contain '{field}' field")
                self.assertIsNotNone(result[field], f"'{field}' field should not be None")

    def test_member_lookup_path_includes_member_field(self):
        """Test that member-based lookup path includes member field in query"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Mock the database calls to verify correct fields are requested
        with patch("frappe.db.get_value") as mock_get_value:
            # Mock member lookup
            mock_get_value.side_effect = [
                self.test_member.name,  # First call: member lookup
                frappe._dict(
                    {  # Second call: volunteer lookup
                        "name": self.test_volunteer.name,
                        "volunteer_name": self.test_volunteer.volunteer_name,
                        "member": self.test_member.name}
                ),
            ]

            with self.as_user(self.test_member.email):
                get_user_volunteer_record()

                # Verify the volunteer lookup call included the member field
                calls = mock_get_value.call_args_list
                self.assertEqual(len(calls), 2, "Should make two database calls")

                # Check the volunteer lookup call (second call)
                volunteer_call = calls[1]
                args, kwargs = volunteer_call

                # Verify the fields parameter includes 'member'
                fields = args[2] if len(args) > 2 else kwargs.get("fields", [])
                self.assertIn("name", fields, "Fields should include 'name'")
                self.assertIn("volunteer_name", fields, "Fields should include 'volunteer_name'")
                self.assertIn("member", fields, "Fields should include 'member' - THIS IS THE CRITICAL FIX")

    def test_direct_email_lookup_path_includes_member_field(self):
        """Test that direct email lookup path includes member field in query"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Mock scenario where member lookup fails but direct volunteer lookup succeeds
        with patch("frappe.db.get_value") as mock_get_value:
            mock_get_value.side_effect = [
                None,  # First call: member lookup fails
                frappe._dict(
                    {  # Second call: direct volunteer lookup
                        "name": self.test_volunteer.name,
                        "volunteer_name": self.test_volunteer.volunteer_name,
                        "member": self.test_member.name}
                ),
            ]

            with self.as_user(self.test_volunteer.email):
                get_user_volunteer_record()

                # Verify the direct volunteer lookup call included the member field
                calls = mock_get_value.call_args_list
                self.assertEqual(len(calls), 2, "Should make two database calls")

                # Check the direct volunteer lookup call (second call)
                volunteer_call = calls[1]
                args, kwargs = volunteer_call

                # Verify the fields parameter includes 'member'
                fields = args[2] if len(args) > 2 else kwargs.get("fields", [])
                self.assertIn("member", fields, "Direct lookup fields should include 'member'")

    def test_function_handles_volunteer_without_member_gracefully(self):
        """Test function handles volunteers without member links gracefully"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Create volunteer without member link
        volunteer_no_member = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "name": "UNIT-TEST-VOLUNTEER-NO-MEMBER",
                "volunteer_name": "Volunteer Without Member",
                "email": "no.member@example.com",
                "status": "Active",
                "start_date": today()}
        )
        volunteer_no_member.insert()
        self.track_doc("Volunteer", volunteer_no_member.name)

        try:
            with self.as_user(volunteer_no_member.email):
                result = get_user_volunteer_record()

                self.assertIsNotNone(result, "Should return volunteer even without member link")
                self.assertIn("member", result, "Should include member field")
                # Member field can be None for volunteers without member links

        finally:
            # Clean up handled automatically by VereningingenTestCase
            pass

    def test_function_returns_none_for_nonexistent_user(self):
        """Test function returns None for non-existent users"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        with self.as_user("nonexistent@example.com"):
            result = get_user_volunteer_record()

            self.assertIsNone(result, "Should return None for non-existent users")

    def test_field_completeness_regression(self):
        """Regression test: ensure no fields are accidentally omitted in future changes"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        with self.as_user(self.test_volunteer.email):
            result = get_user_volunteer_record()

            # Define the minimum required fields - add to this list if more become required
            minimum_required_fields = {
                "name": str,  # Volunteer name/ID
                "volunteer_name": str,  # Display name
                "member": (str, type(None)),  # Member link (can be None)
            }

            for field, expected_type in minimum_required_fields.items():
                self.assertIn(field, result, f"Field '{field}' is required and must not be omitted")

                if isinstance(expected_type, tuple):
                    self.assertIsInstance(
                        result[field], expected_type, f"Field '{field}' must be of type {expected_type}"
                    )
                else:
                    if result[field] is not None:  # Allow None values for optional fields
                        self.assertIsInstance(
                            result[field], expected_type, f"Field '{field}' must be of type {expected_type}"
                        )

    def test_database_query_optimization(self):
        """Test that database queries are optimized and don't fetch unnecessary fields"""
        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        with patch("frappe.db.get_value") as mock_get_value:
            mock_get_value.side_effect = [
                self.test_member.name,
                frappe._dict(
                    {
                        "name": self.test_volunteer.name,
                        "volunteer_name": self.test_volunteer.volunteer_name,
                        "member": self.test_member.name}
                ),
            ]

            with self.as_user(self.test_member.email):
                get_user_volunteer_record()

                # Verify that queries only fetch necessary fields
                calls = mock_get_value.call_args_list

                for call in calls:
                    args, kwargs = call

                    # If fields are specified, they should be minimal and necessary
                    if len(args) > 2:  # Fields parameter exists
                        fields = args[2]
                        if isinstance(fields, list):
                            # Ensure no obviously unnecessary fields are included
                            unnecessary_fields = ["creation", "modified", "modified_by", "owner", "docstatus"]
                            for unnecessary_field in unnecessary_fields:
                                self.assertNotIn(
                                    unnecessary_field,
                                    fields,
                                    f"Unnecessary field '{unnecessary_field}' should not be fetched for performance",
                                )

    # tearDown handled automatically by VereningingenTestCase
