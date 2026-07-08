#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cost Center UI Integration Tests
================================

Comprehensive integration tests for the Cost Center Creation user interface,
focusing on JavaScript component behavior, button interactions, dialog functionality,
and real-world user workflows.

These tests validate the complete user experience from account group input
to cost center creation confirmation, ensuring proper error handling,
progress feedback, and result presentation.

Test Coverage:
- Button state management and visibility
- Dialog interaction flows
- Form validation and error display
- Progress indication during processing
- Result presentation and confirmation
- Error scenario handling in UI
- Accessibility and usability aspects
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import random_string

from verenigingen.tests.e_boekhouden.fixtures.cost_center_test_factory import CostCenterTestDataFactory
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCostCenterUIIntegration(EnhancedTestCase):
    """
    Integration tests for Cost Center Creation UI components

    Tests the complete user interface workflow including:
    - JavaScript button interactions
    - Dialog opening and closing
    - Form submission and validation
    - Progress indication
    - Result display and error handling
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CostCenterTestDataFactory(seed=12345, use_faker=False)

    def setUp(self):
        super().setUp()

        # Restore CostCenterTestDataFactory (parent class overrides with EnhancedTestDataFactory)
        self.factory = self.__class__.factory

        # Create test company and settings
        self.test_company = self.factory.create_test_company()
        self.test_settings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name
        )

        # Track for cleanup
        self.factory.track_document("Company", self.test_company.name)

    def _ensure_cost_center_mapping_row(self, settings):
        """Test setup helper: append one minimal cost center mapping row if none
        exist yet, so a later "missing company" check is reached instead of
        short-circuiting on "no mappings configured"."""
        if not settings.cost_center_mappings:
            settings.append(
                "cost_center_mappings",
                {
                    "group_code": "500",
                    "group_name": "Test Group",
                    "cost_center_name": "Test Cost Center",
                    "create_cost_center": 1,
                    "is_group": 0,
                },
            )
            settings.save(ignore_permissions=True)

    def _persist_settings(self, settings):
        """Test setup helper: save E-Boekhouden Settings bypassing permissions.

        This is scaffolding to reach a specific real-data state before invoking
        the whitelisted function under test -- not itself a test of permission
        boundaries.
        """
        settings.save(ignore_permissions=True)

    def test_parse_groups_button_functionality(self):
        """Test Parse Groups & Configure Cost Centers button behavior"""

        # Generate test data
        scenario = self.factory.generate_cost_center_mapping_scenario("mixed_suggestions")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)

        # Set up settings with account group mappings
        self.test_settings.account_group_mappings = text_input
        self.test_settings.save()

        # Test button behavior via API (simulating JavaScript call)
        # parse_groups_and_suggest_cost_centers is a module-level function, use frappe.call
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name,
        )

        # Verify the function returns expected structure
        self.assertTrue(result.get("success"), f"Parse should succeed: {result.get('error')}")
        self.assertIn("suggestions", result, "Result should contain suggestions")
        self.assertIn("total_groups", result, "Result should contain total_groups")

    def test_preview_dialog_functionality(self):
        """Test cost center preview dialog behavior against the real preview function

        (Previously patched preview_cost_center_creation and asserted on the mock's
        own hard-coded return -- a mock-into-tautology that could never fail. Now
        exercises the real, unmocked API call against real settings data.)
        """

        # Set up test mappings
        self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name, with_mappings=True, mapping_scenario="happy_path"
        )

        # Simulate preview button click against the real function
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation"
        )

        # Verify preview structure and real content
        self.assertTrue(result["success"], f"Preview should succeed: {result.get('error')}")
        self.assertIn("preview_results", result, "Should return preview results")
        self.assertGreater(len(result["preview_results"]), 0, "Should have preview items")
        self.assertGreater(result["would_create"], 0, "Should report cost centers to create")

        first = result["preview_results"][0]
        self.assertIn("group_code", first)
        self.assertIn("cost_center_name", first)
        self.assertIn("action", first)

    def test_create_cost_centers_dialog_functionality(self):
        """Test cost center creation dialog against the real creation function

        (Previously patched create_cost_centers_from_mappings and asserted on the
        mock's own hard-coded return -- a mock-into-tautology. Now exercises the
        real, unmocked function and verifies the created cost centers actually
        exist in the database.)
        """

        # Set up test mappings
        self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name, with_mappings=True, mapping_scenario="happy_path"
        )

        # Simulate create button click against the real function
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings"
        )

        # Verify creation results structure and real effect
        self.assertTrue(result["success"], f"Creation should succeed: {result.get('error')}")
        self.assertIn("created_count", result, "Should return created count")
        self.assertIn("created_cost_centers", result, "Should return created list")
        self.assertGreaterEqual(result["created_count"], 1, "Should create cost centers")

        for created in result["created_cost_centers"]:
            self.assertTrue(
                frappe.db.exists("Cost Center", created["cost_center_id"]),
                f"Cost center {created['cost_center_id']} should exist in database",
            )
            self.factory.track_document("Cost Center", created["cost_center_id"])

    def test_error_handling_in_ui_workflow(self):
        """Test error handling throughout the UI workflow against the real functions

        (Previously patched all three whitelisted functions and asserted on the
        mocks' own hard-coded returns -- mock-into-tautology that could never fail
        regardless of what the real functions do. Now drives the real rejection
        paths with real settings state.)
        """

        # Test 1: Empty account group mappings -> real rejection from parse_groups_and_suggest_cost_centers
        self.test_settings.account_group_mappings = ""
        self.test_settings.save()

        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text="",
            company=self.test_company.name,
        )

        self.assertFalse(result["success"], "Should fail with empty mappings")
        self.assertEqual(result["error"], "No account group mappings provided")

        # Test 2: Missing company configuration -> real rejection from create_cost_centers_from_mappings
        # (needs at least one cost center mapping row so the company check is reached)
        original_company = self.test_settings.default_company
        self._ensure_cost_center_mapping_row(self.test_settings)

        # Use db_set to bypass validation when clearing required field
        frappe.db.set_value("E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", None)
        self.test_settings.reload()

        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings"
        )

        self.assertFalse(result["success"], "Should fail without company")
        self.assertIn("company", result["error"].lower(), "Error should mention company")

        # Restore company
        frappe.db.set_value(
            "E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", original_company
        )
        self.test_settings.reload()

        # Test 3: No cost center mappings configured -> real rejection from preview_cost_center_creation
        self.test_settings.cost_center_mappings = []
        self._persist_settings(self.test_settings)

        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation"
        )

        self.assertFalse(result["success"], "Should fail without mappings")
        self.assertIn("mappings", result["error"].lower(), "Error should mention mappings")

    def test_button_state_management(self):
        """Test button visibility and state management"""

        # Test initial state - no mappings configured
        settings = frappe.get_single("E-Boekhouden Settings")
        settings.cost_center_mappings = []
        settings.save()

        # Verify buttons should be disabled/hidden without mappings
        # (This would be tested in JavaScript, here we test the data conditions)
        self.assertEqual(len(settings.cost_center_mappings), 0, "Initially no mappings should exist")

        # Test after parsing groups
        scenario = self.factory.generate_cost_center_mapping_scenario("mixed_suggestions")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)

        # Simulate parsing groups (which populates mappings)
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name,
        )

        # "mixed_suggestions" always yields valid "<code> <name>" lines, so parsing
        # deterministically succeeds -- assert it directly instead of silently
        # skipping the rest of the test on an `if result["success"]:` guard (which
        # would pass trivially even if parsing started failing).
        self.assertTrue(
            result["success"], f"Parsing mixed_suggestions scenario should succeed: {result.get('error')}"
        )

        # Update settings with parsed mappings (simulate UI behavior)
        settings = frappe.get_single("E-Boekhouden Settings")
        settings.cost_center_mappings = []

        for suggestion in result["suggestions"]:
            settings.append(
                "cost_center_mappings",
                {
                    "group_code": suggestion["group_code"],
                    "group_name": suggestion["group_name"],
                    "create_cost_center": suggestion["create_cost_center"],
                    "cost_center_name": suggestion.get("cost_center_name", ""),
                    "suggestion_reason": suggestion.get("reason", ""),
                },
            )

        settings.save()

        # Now buttons should be enabled
        self.assertGreater(len(settings.cost_center_mappings), 0, "Mappings should exist after parsing")

        # Count mappings that should create cost centers
        create_mappings = [m for m in settings.cost_center_mappings if m.create_cost_center]
        self.assertGreater(len(create_mappings), 0, "Some mappings should be configured for creation")

    # NOTE (2026-07-08 false-confidence remediation): test_progress_indication_simulation
    # was deleted here. It patched parse_groups_and_suggest_cost_centers with a fake
    # `time.sleep(0.1)` side effect and asserted on the *mock's* timing/return value --
    # it never called the real function, so it proved nothing about production code.
    # The real, unmocked large-dataset timing path is already covered for real by
    # TestCostCenterUIWorkflows.test_large_dataset_workflow_performance below (same
    # "large_dataset" scenario, real parse_groups_and_suggest_cost_centers call), so
    # deleting this mock-artifact test does not drop any real coverage.

    def test_result_display_formatting(self):
        """Test proper formatting of created/skipped/failed results in a genuinely mixed outcome

        (Previously mocked create_cost_centers_from_mappings entirely and asserted
        the mock's own hard-coded dict back at itself -- a pure mock-into-tautology.
        Now drives the real function for the created+skipped rows, and stubs only
        the low-level per-row helper `create_single_cost_center` -- a true
        collaborator boundary, not the function under test -- to force a
        deterministic single failure. A real DB-level failure (e.g. an
        over-length name) isn't usable here: the Cost Center Mapping child table's
        `cost_center_name` field shares Frappe's Data-field 140-char length limit
        with Cost Center's own field, so an over-long name would already be
        rejected by `settings.save()` before create_cost_centers_from_mappings ever
        runs.)
        """
        self.test_settings.cost_center_mappings = []
        self.test_settings.append(
            "cost_center_mappings",
            {
                "group_code": "500",
                "group_name": "Personeelskosten",
                "create_cost_center": 1,
                "cost_center_name": "UI Format Test Cost Center",
                "suggestion_reason": "test",
            },
        )
        self.test_settings.append(
            "cost_center_mappings",
            {
                "group_code": "501",
                "group_name": "Personeelskosten Duplicate",
                "create_cost_center": 1,
                "cost_center_name": "UI Format Test Cost Center",  # same name -> real "already exists" skip
                "suggestion_reason": "test",
            },
        )
        self.test_settings.append(
            "cost_center_mappings",
            {
                "group_code": "502",
                "group_name": "Failing Group",
                "create_cost_center": 1,
                "cost_center_name": "UI Format Test Cost Center Failing",
                "suggestion_reason": "test",
            },
        )
        self.test_settings.save()

        from verenigingen.e_boekhouden.doctype.e_boekhouden_settings import (
            e_boekhouden_settings as ecs_module,
        )

        real_create_single = ecs_module.create_single_cost_center

        def create_single_with_one_failure(mapping, company):
            if mapping.group_code == "502":
                return {"success": False, "skipped": False, "error": "Simulated creation failure"}
            return real_create_single(mapping, company)

        with patch.object(
            ecs_module, "create_single_cost_center", side_effect=create_single_with_one_failure
        ):
            result = frappe.call(
                "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings"
            )

        # Verify result structure for UI display
        self.assertTrue(
            result["success"], f"Mixed results should still succeed overall: {result.get('error')}"
        )

        # Verify counts against the real (non-mocked) outcome
        self.assertEqual(result["created_count"], 1, "Should create exactly one new cost center")
        self.assertEqual(result["skipped_count"], 1, "Duplicate name should be skipped, not recreated")
        self.assertEqual(result["failed_count"], 1, "Simulated failure should surface as a failed entry")

        # Verify each result has required fields for UI display
        created = result["created_cost_centers"][0]
        self.assertIn("group_code", created, "Created items should have group code")
        self.assertIn("cost_center_name", created, "Created items should have name")
        self.assertIn("cost_center_id", created, "Created items should have ID")
        self.assertTrue(
            frappe.db.exists("Cost Center", created["cost_center_id"]),
            "Created cost center should really exist in the database",
        )
        self.factory.track_document("Cost Center", created["cost_center_id"])

        skipped = result["skipped_cost_centers"][0]
        self.assertIn("reason", skipped, "Skipped items should have reason")
        self.assertIn("already exists", skipped["reason"].lower())

        failed = result["failed_cost_centers"][0]
        self.assertIn("error", failed, "Failed items should have error message")
        self.assertEqual(failed["error"], "Simulated creation failure")

    def test_form_validation_simulation(self):
        """Test rejection of malformed account-group-mapping input

        (Previously accepted either outcome -- "if not result['success']: ... else:
        ..." -- so it passed no matter what the real function did with these
        inputs. All four inputs are in fact deterministically rejected by
        parse_groups_and_suggest_cost_centers (none of them contain a parseable
        "<code> <name>" line), so this now asserts the specific, real rejection.)
        """
        invalid_inputs_and_errors = [
            ("", "No account group mappings provided"),  # Empty
            ("   \n  \n  ", "No account group mappings provided"),  # Whitespace only
            ("InvalidFormat", "No valid account groups found"),  # No space separator
            ("123\n456\n", "No valid account groups found"),  # Missing names
        ]

        for invalid_input, expected_error in invalid_inputs_and_errors:
            with self.subTest(input_desc=invalid_input[:10] + "..."):

                # Set invalid input
                self.test_settings.account_group_mappings = invalid_input
                self.test_settings.save()

                # Test parsing with invalid input
                result = frappe.call(
                    "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
                    group_mappings_text=invalid_input,
                    company=self.test_company.name,
                )

                self.assertFalse(result["success"], f"Should reject malformed input: {invalid_input!r}")
                self.assertEqual(result["error"], expected_error)

    def test_accessibility_compliance_simulation(self):
        """Test that rejection error messages are descriptive and mention the right cause

        (Previously guarded every assertion behind `if not result.get("success",
        True):`, so a scenario that unexpectedly started *succeeding* would skip
        all assertions and still pass. All three scenarios below are in fact
        deterministic real rejections, so this now asserts success is False
        directly instead of silently tolerating either outcome.)
        """

        # empty_input -> parse_groups_and_suggest_cost_centers rejects, mentioning "provided"
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text="",
            company=self.test_company.name,
        )
        self.assertFalse(result["success"], "Empty input should be rejected")
        error_message = result["error"].lower()
        self.assertGreater(len(error_message), 10, "Error message should be descriptive")
        self.assertTrue(
            any(word in error_message for word in ["empty", "missing", "provided", "required"]),
            f"Error should be descriptive: {error_message}",
        )

        # no_company -> create_cost_centers_from_mappings rejects, mentioning "company"
        original_company = self.test_settings.default_company
        original_mappings = self.test_settings.cost_center_mappings or []
        self._ensure_cost_center_mapping_row(self.test_settings)

        # Clear company using db_set to bypass validation
        frappe.db.set_value("E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", None)
        self.test_settings.reload()

        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings"
        )

        # Restore company
        frappe.db.set_value(
            "E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", original_company
        )
        if not original_mappings:
            self.test_settings.reload()
            self.test_settings.cost_center_mappings = []
            self._persist_settings(self.test_settings)
        self.test_settings.reload()

        self.assertFalse(result["success"], "Missing company should be rejected")
        error_message = result["error"].lower()
        self.assertIn("company", error_message, f"Error should mention company: {error_message}")

        # invalid_format -> parse_groups_and_suggest_cost_centers rejects, mentioning "valid"/"groups"
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text="123\n456",
            company=self.test_company.name,
        )
        self.assertFalse(result["success"], "Malformed input should be rejected")
        error_message = result["error"].lower()
        self.assertTrue(
            any(word in error_message for word in ["format", "valid", "groups"]),
            f"Error should mention format: {error_message}",
        )


class TestCostCenterUIWorkflows(EnhancedTestCase):
    """
    End-to-end workflow tests simulating complete user interactions
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CostCenterTestDataFactory(seed=12345, use_faker=False)

    def setUp(self):
        super().setUp()

        # Restore CostCenterTestDataFactory (parent class overrides with EnhancedTestDataFactory)
        self.factory = self.__class__.factory

        self.test_company = self.factory.create_test_company()
        self.test_settings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name
        )
        self.factory.track_document("Company", self.test_company.name)

        # Clean up any existing cost centers with happy_path scenario names
        # to ensure test isolation between runs
        self._cleanup_happy_path_cost_centers()

    def _cleanup_happy_path_cost_centers(self):
        """Remove cost centers that may conflict with happy_path test scenario."""
        scenario = self.factory.generate_cost_center_mapping_scenario("happy_path")
        for group in scenario["groups"]:
            group_name = group["name"]
            existing_cost_centers = frappe.get_all(
                "Cost Center", filters={"cost_center_name": group_name}, pluck="name"
            )
            for cc_name in existing_cost_centers:
                try:
                    frappe.delete_doc("Cost Center", cc_name, force=True, ignore_permissions=True)
                except Exception:
                    pass  # Ignore deletion errors (may have linked documents)
        frappe.db.commit()

    def test_complete_happy_path_workflow(self):
        """Test complete happy path user workflow"""

        # Step 1: User inputs account group mappings
        scenario = self.factory.generate_cost_center_mapping_scenario("happy_path")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)

        self.test_settings.account_group_mappings = text_input
        self.test_settings.save()

        # Step 2: User clicks "Parse Groups & Configure Cost Centers"
        parse_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name,
        )

        self.assertTrue(parse_result["success"], "Parsing should succeed")

        # Step 3: System populates cost center mappings
        suggestions = parse_result["suggestions"]
        self.test_settings.cost_center_mappings = []

        for suggestion in suggestions:
            self.test_settings.append(
                "cost_center_mappings",
                {
                    "group_code": suggestion["group_code"],
                    "group_name": suggestion["group_name"],
                    "create_cost_center": suggestion["create_cost_center"],
                    "cost_center_name": suggestion.get("cost_center_name", ""),
                    "suggestion_reason": suggestion.get("reason", ""),
                },
            )

        self.test_settings.save()

        # Step 4: User reviews and clicks "Preview Cost Centers"
        preview_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation"
        )

        self.assertTrue(preview_result["success"], "Preview should succeed")
        self.assertGreater(preview_result["would_create"], 0, "Should have cost centers to create")

        # Step 5: User confirms and clicks "Create Cost Centers"
        create_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings"
        )

        self.assertTrue(create_result["success"], "Creation should succeed")
        self.assertGreater(create_result["created_count"], 0, "Should create cost centers")
        self.assertEqual(create_result["failed_count"], 0, "Should have no failures")

        # Step 6: Verify cost centers were actually created
        for created_cc in create_result["created_cost_centers"]:
            cc_id = created_cc["cost_center_id"]
            self.assertTrue(
                frappe.db.exists("Cost Center", cc_id), f"Cost center {cc_id} should exist in database"
            )
            self.factory.track_document("Cost Center", cc_id)

        print(f"✅ Complete workflow test: Created {create_result['created_count']} cost centers")

    def test_error_recovery_workflow(self):
        """Test user workflow with error recovery"""

        # Step 1: User makes initial mistake - empty input
        self.test_settings.account_group_mappings = ""
        self.test_settings.save()

        parse_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text="",
            company=self.test_company.name,
        )

        self.assertFalse(parse_result["success"], "Should fail with empty input")

        # Step 2: User corrects mistake and tries again
        scenario = self.factory.generate_cost_center_mapping_scenario("mixed_suggestions")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)

        self.test_settings.account_group_mappings = text_input
        self.test_settings.save()

        parse_result_2 = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name,
        )

        self.assertTrue(parse_result_2["success"], "Should succeed after correction")

        # Step 3: Continue with normal workflow...
        # (Rest of workflow similar to happy path)

        print("✅ Error recovery workflow test completed")

    def test_large_dataset_workflow_performance(self):
        """Test workflow performance with large dataset"""

        # Generate large dataset
        scenario = self.factory.generate_cost_center_mapping_scenario("large_dataset")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)

        start_time = time.time()

        # Step 1: Parse large dataset
        parse_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name,
        )

        parse_time = time.time() - start_time

        self.assertTrue(parse_result["success"], "Large dataset parsing should succeed")
        self.assertLess(parse_time, 10.0, "Parsing should complete within 10 seconds")
        self.assertEqual(parse_result["total_groups"], len(groups), "Should process all groups")

        print(f"✅ Large dataset workflow: Processed {len(groups)} groups in {parse_time:.3f}s")


if __name__ == "__main__":
    unittest.main()
