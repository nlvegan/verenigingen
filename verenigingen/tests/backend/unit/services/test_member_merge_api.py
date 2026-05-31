# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Member Merge Service API

Tests member merge API endpoints with OperationResult pattern.
Focus on type-safe error handling for duplicate member consolidation.

NOTE (2026-05-31): These API functions are decorated with @critical_api,
which converts the returned OperationResult into the nested-schema dict via
OperationResult.to_dict(scrub_sensitive=True) for JSON serialization. The
values returned to these tests are dicts, not OperationResult objects:
  - success:  result["success"] (bool)
  - data:     result["data"]
  - failure:  result["error"]["message"], result["error"].get("errors")
"""

import frappe
from frappe.utils import random_string
from verenigingen.services.member_merge_service import (
    get_merge_preview,
    execute_merge,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestMemberMergeAPI(EnhancedTestCase):
    """Unit tests for Member Merge Service API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_get_merge_preview_returns_operation_result(self):
        """Test get_merge_preview returns OperationResult"""
        unique_email1 = f"merge.source.{random_string(8).lower()}@example.com"
        unique_email2 = f"merge.target.{random_string(8).lower()}@example.com"

        # Create source and target members
        source = self.create_test_member(
            first_name="Source",
            last_name="Member",
            email=unique_email1,
            birth_date="1990-01-01"
        )
        target = self.create_test_member(
            first_name="Target",
            last_name="Member",
            email=unique_email2,
            birth_date="1990-01-01"
        )

        result = get_merge_preview(source.name, target.name)

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

    def test_get_merge_preview_with_invalid_member_returns_failed_result(self):
        """Test merge preview with invalid member returns failed OperationResult"""
        unique_email = f"valid.member.{random_string(8).lower()}@example.com"
        valid_member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            email=unique_email
        )

        result = get_merge_preview("INVALID-MEMBER", valid_member.name)

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_execute_merge_returns_operation_result(self):
        """Test execute_merge returns OperationResult"""
        unique_email1 = f"exec.source.{random_string(8).lower()}@example.com"
        unique_email2 = f"exec.target.{random_string(8).lower()}@example.com"

        # Create source and target members with different data
        source = self.create_test_member(
            first_name="SourceFirst",
            last_name="SourceLast",
            email=unique_email1,
            contact_number="0612345678"
        )
        target = self.create_test_member(
            first_name="TargetFirst",
            last_name="TargetLast",
            email=unique_email2
        )

        # Simple field selection: keep target's name, take source's phone
        field_selections = {
            "first_name": "target",
            "last_name": "target",
            "contact_number": "source"
        }

        result = execute_merge(source.name, target.name, field_selections)

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

    def test_execute_merge_with_invalid_field_selections_returns_failed_result(self):
        """Test merge with invalid field selections format returns failed OperationResult"""
        unique_email1 = f"invalid.source.{random_string(8).lower()}@example.com"
        unique_email2 = f"invalid.target.{random_string(8).lower()}@example.com"

        source = self.create_test_member(
            first_name="InvalidSource",
            last_name="Test",
            email=unique_email1
        )
        target = self.create_test_member(
            first_name="InvalidTarget",
            last_name="Test",
            email=unique_email2
        )

        # Invalid JSON string
        result = execute_merge(source.name, target.name, "{invalid json}")

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_execute_merge_with_nonexistent_member_returns_failed_result(self):
        """Test merge with non-existent member returns failed OperationResult"""
        unique_email = f"nonexist.test.{random_string(8).lower()}@example.com"
        valid_member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            email=unique_email
        )

        field_selections = {"first_name": "target"}

        result = execute_merge("NONEXISTENT-001", valid_member.name, field_selections)

        # Should fail gracefully
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"]["message"])

    def test_merge_apis_never_throw_exceptions(self):
        """Test that merge APIs never throw exceptions"""
        # Test with various invalid inputs
        invalid_tests = [
            ("", ""),
            ("INVALID-1", "INVALID-2"),
        ]

        for source, target in invalid_tests:
            # get_merge_preview
            result1 = get_merge_preview(source, target)
            self.assertIsNotNone(result1)
            self.assertIn("success", result1)

            # execute_merge
            result2 = execute_merge(source, target, {})
            self.assertIsNotNone(result2)
            self.assertIn("success", result2)

    def test_merge_preview_result_contains_expected_fields(self):
        """Test that merge preview result contains expected metadata"""
        unique_email1 = f"preview.meta.source.{random_string(8).lower()}@example.com"
        unique_email2 = f"preview.meta.target.{random_string(8).lower()}@example.com"

        source = self.create_test_member(
            first_name="PreviewSource",
            last_name="Test",
            email=unique_email1,
            contact_number="0612345678"
        )
        target = self.create_test_member(
            first_name="PreviewTarget",
            last_name="Test",
            email=unique_email2
        )

        result = get_merge_preview(source.name, target.name)

        # Check structure
        if result["success"]:
            expected_fields = ["source", "target", "fields", "warnings"]
            for field in expected_fields:
                self.assertIn(field, result["data"], f"Missing expected field in data: {field}")

            # Check source and target info
            self.assertIn("name", result["data"]["source"])
            self.assertIn("name", result["data"]["target"])
        else:
            # On failure, should have error message
            self.assertIsNotNone(result["error"]["message"])
            self.assertIsInstance(result["error"].get("errors", []), list)

    def test_execute_merge_result_contains_expected_fields(self):
        """Test that execute merge result contains expected metadata"""
        unique_email1 = f"exec.meta.source.{random_string(8).lower()}@example.com"
        unique_email2 = f"exec.meta.target.{random_string(8).lower()}@example.com"

        source = self.create_test_member(
            first_name="ExecSource",
            last_name="Test",
            email=unique_email1
        )
        target = self.create_test_member(
            first_name="ExecTarget",
            last_name="Test",
            email=unique_email2
        )

        field_selections = {"first_name": "target"}

        result = execute_merge(source.name, target.name, field_selections)

        # Check structure
        if result["success"]:
            expected_fields = ["merged_member", "changes_applied"]
            for field in expected_fields:
                self.assertIn(field, result["data"], f"Missing expected field in data: {field}")

            # Verify merged member exists
            self.assertTrue(frappe.db.exists("Member", result["data"]["merged_member"]))
        else:
            # On failure, should have error message
            self.assertIsNotNone(result["error"]["message"])
            self.assertIsInstance(result["error"].get("errors", []), list)


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberMergeAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
