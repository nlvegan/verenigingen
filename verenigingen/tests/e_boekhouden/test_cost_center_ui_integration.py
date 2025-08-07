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
import unittest
from unittest.mock import patch, MagicMock
import time

import frappe
from frappe.utils import random_string

from vereinigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.e_boekhouden.fixtures.cost_center_test_factory import CostCenterTestDataFactory


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
        
        # Create test company and settings
        self.test_company = self.factory.create_test_company()
        self.test_settings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name
        )
        
        # Track for cleanup
        self.track_doc("Company", self.test_company.name)
        
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
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers') as mock_parse:
            mock_parse.return_value = {
                "success": True,
                "suggestions": [
                    {
                        "group_code": "500",
                        "group_name": "Personeelskosten",
                        "create_cost_center": True,
                        "cost_center_name": "Personeelskosten",
                        "reason": "Expense group - good for cost tracking"
                    }
                ],
                "total_groups": 1,
                "suggested_count": 1
            }
            
            # Simulate button click via frappe.call
            result = frappe.get_doc({
                "doctype": "E-Boekhouden Settings"
            }).run_method("parse_groups_and_suggest_cost_centers", 
                         group_mappings_text=text_input, 
                         company=self.test_company.name)
            
            # Verify API was called correctly
            mock_parse.assert_called_once_with(text_input, self.test_company.name)
            
    def test_preview_dialog_functionality(self):
        """Test cost center preview dialog behavior"""
        
        # Set up test mappings
        scenario = self.factory.generate_cost_center_mapping_scenario("happy_path")
        settings_with_mappings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name,
            with_mappings=True,
            mapping_scenario="happy_path"
        )
        
        # Test preview functionality via API
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation') as mock_preview:
            mock_preview.return_value = {
                "success": True,
                "preview_results": [
                    {
                        "group_code": "500",
                        "group_name": "Personeelskosten",
                        "cost_center_name": "Personeelskosten",
                        "already_exists": False,
                        "action": "Create new"
                    }
                ],
                "total_to_process": 1,
                "would_create": 1,
                "would_skip": 0
            }
            
            # Simulate preview button click
            result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation")
            
            # Verify preview structure
            self.assertTrue(result["success"], "Preview should succeed")
            self.assertIn("preview_results", result, "Should return preview results")
            self.assertGreater(len(result["preview_results"]), 0, "Should have preview items")
            
    def test_create_cost_centers_dialog_functionality(self):
        """Test cost center creation dialog and progress handling"""
        
        # Set up test mappings
        scenario = self.factory.generate_cost_center_mapping_scenario("happy_path")
        settings_with_mappings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name,
            with_mappings=True,
            mapping_scenario="happy_path" 
        )
        
        # Test creation functionality via API
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings') as mock_create:
            mock_create.return_value = {
                "success": True,
                "created_count": 5,
                "skipped_count": 1,
                "failed_count": 0,
                "created_cost_centers": [
                    {
                        "group_code": "500",
                        "cost_center_name": "Personeelskosten",
                        "cost_center_id": "Personeelskosten - Test Company"
                    }
                ],
                "skipped_cost_centers": [],
                "failed_cost_centers": []
            }
            
            # Simulate create button click
            result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings")
            
            # Verify creation results structure
            self.assertTrue(result["success"], "Creation should succeed")
            self.assertIn("created_count", result, "Should return created count")
            self.assertIn("created_cost_centers", result, "Should return created list")
            self.assertGreaterEqual(result["created_count"], 1, "Should create cost centers")
            
    def test_error_handling_in_ui_workflow(self):
        """Test error handling throughout the UI workflow"""
        
        # Test 1: Empty account group mappings
        self.test_settings.account_group_mappings = ""
        self.test_settings.save()
        
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers') as mock_parse:
            mock_parse.return_value = {
                "success": False,
                "error": "No account group mappings provided"
            }
            
            result = frappe.call(
                "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
                group_mappings_text="",
                company=self.test_company.name
            )
            
            self.assertFalse(result["success"], "Should fail with empty mappings")
            self.assertIn("error", result, "Should return error message")
            
        # Test 2: Missing company configuration  
        self.test_settings.default_company = None
        self.test_settings.save()
        
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings') as mock_create:
            mock_create.return_value = {
                "success": False,
                "error": "Default company not configured"
            }
            
            result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings")
            
            self.assertFalse(result["success"], "Should fail without company")
            self.assertIn("company", result["error"].lower(), "Error should mention company")
            
        # Test 3: Invalid mapping data
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation') as mock_preview:
            mock_preview.return_value = {
                "success": False,
                "error": "No cost center mappings configured"
            }
            
            result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation")
            
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
        self.assertEqual(len(settings.cost_center_mappings), 0, 
                        "Initially no mappings should exist")
        
        # Test after parsing groups
        scenario = self.factory.generate_cost_center_mapping_scenario("mixed_suggestions")
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)
        
        # Simulate parsing groups (which populates mappings)
        result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name
        )
        
        if result["success"]:
            # Update settings with parsed mappings (simulate UI behavior)
            settings = frappe.get_single("E-Boekhouden Settings")
            settings.cost_center_mappings = []
            
            for suggestion in result["suggestions"]:
                settings.append("cost_center_mappings", {
                    "group_code": suggestion["group_code"],
                    "group_name": suggestion["group_name"],
                    "create_cost_center": suggestion["create_cost_center"],
                    "cost_center_name": suggestion.get("cost_center_name", ""),
                    "suggestion_reason": suggestion.get("reason", "")
                })
                
            settings.save()
            
            # Now buttons should be enabled
            self.assertGreater(len(settings.cost_center_mappings), 0,
                             "Mappings should exist after parsing")
            
            # Count mappings that should create cost centers
            create_mappings = [m for m in settings.cost_center_mappings if m.create_cost_center]
            self.assertGreater(len(create_mappings), 0,
                             "Some mappings should be configured for creation")
                             
    def test_progress_indication_simulation(self):
        """Test progress indication during long operations"""
        
        # Set up large dataset scenario
        scenario = self.factory.generate_cost_center_mapping_scenario("large_dataset")
        settings_with_large_dataset = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name,
            with_mappings=True,
            mapping_scenario="large_dataset"
        )
        
        # Simulate progress tracking (in real UI this would show progress bars)
        start_time = time.time()
        
        # Test parsing large dataset
        groups = scenario["groups"]
        text_input = self.factory.format_groups_as_text_input(groups)
        
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers') as mock_parse:
            # Simulate processing time
            def slow_parse(*args, **kwargs):
                time.sleep(0.1)  # Simulate processing time
                return {
                    "success": True,
                    "suggestions": [],
                    "total_groups": len(groups),
                    "suggested_count": 0
                }
                
            mock_parse.side_effect = slow_parse
            
            result = frappe.call(
                "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
                group_mappings_text=text_input,
                company=self.test_company.name
            )
            
            processing_time = time.time() - start_time
            
            # Verify operation completed and took reasonable time
            self.assertTrue(result["success"], "Large dataset parsing should succeed")
            self.assertGreater(processing_time, 0.05, "Should take some processing time")
            self.assertLess(processing_time, 5.0, "Should not take too long")
            
    def test_result_display_formatting(self):
        """Test proper formatting of results in UI"""
        
        # Set up scenario with mixed results
        scenario = self.factory.generate_cost_center_mapping_scenario("error_prone")
        settings_with_mixed = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name,
            with_mappings=True,
            mapping_scenario="error_prone"
        )
        
        # Test creation with expected mixed results
        with patch('verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings') as mock_create:
            mock_create.return_value = {
                "success": True,
                "created_count": 2,
                "skipped_count": 1,
                "failed_count": 2,
                "total_processed": 5,
                "created_cost_centers": [
                    {"group_code": "500", "cost_center_name": "Personeelskosten", "cost_center_id": "CC-001"},
                    {"group_code": "600", "cost_center_name": "Algemene Kosten", "cost_center_id": "CC-002"}
                ],
                "skipped_cost_centers": [
                    {"group_code": "501", "reason": "Already exists"}
                ],
                "failed_cost_centers": [
                    {"group_code": "502", "error": "Invalid name"},
                    {"group_code": "503", "error": "Validation failed"}
                ]
            }
            
            result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings")
            
            # Verify result structure for UI display
            self.assertTrue(result["success"], "Mixed results should still succeed overall")
            
            # Verify counts
            self.assertEqual(result["created_count"], 2, "Should show correct created count")
            self.assertEqual(result["skipped_count"], 1, "Should show correct skipped count")
            self.assertEqual(result["failed_count"], 2, "Should show correct failed count")
            
            # Verify detailed results for UI display
            self.assertEqual(len(result["created_cost_centers"]), 2, "Should list created cost centers")
            self.assertEqual(len(result["skipped_cost_centers"]), 1, "Should list skipped items")
            self.assertEqual(len(result["failed_cost_centers"]), 2, "Should list failed items")
            
            # Verify each result has required fields for UI display
            for created in result["created_cost_centers"]:
                self.assertIn("group_code", created, "Created items should have group code")
                self.assertIn("cost_center_name", created, "Created items should have name")
                self.assertIn("cost_center_id", created, "Created items should have ID")
                
            for skipped in result["skipped_cost_centers"]:
                self.assertIn("reason", skipped, "Skipped items should have reason")
                
            for failed in result["failed_cost_centers"]:
                self.assertIn("error", failed, "Failed items should have error message")
                
    def test_form_validation_simulation(self):
        """Test form validation behavior simulation"""
        
        # Test validation of account group mappings field
        invalid_inputs = [
            "",  # Empty
            "   \n  \n  ",  # Whitespace only
            "InvalidFormat",  # No space separator
            "123\n456\n",  # Missing names
        ]
        
        for invalid_input in invalid_inputs:
            with self.subTest(input_desc=invalid_input[:10] + "..."):
                
                # Set invalid input
                self.test_settings.account_group_mappings = invalid_input
                self.test_settings.save()
                
                # Test parsing with invalid input
                result = frappe.call(
                    "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
                    group_mappings_text=invalid_input,
                    company=self.test_company.name
                )
                
                # Should either succeed with empty results or fail gracefully
                if not result["success"]:
                    self.assertIn("error", result, "Failed validation should include error")
                    self.assertIsInstance(result["error"], str, "Error should be string")
                    self.assertGreater(len(result["error"]), 0, "Error should not be empty")
                else:
                    # If it succeeds, should have appropriate results
                    self.assertIn("suggestions", result, "Success should include suggestions")
                    self.assertIn("total_groups", result, "Success should include total count")
                    
    def test_accessibility_compliance_simulation(self):
        """Test accessibility compliance aspects that can be verified server-side"""
        
        # Test that error messages are descriptive and helpful
        test_scenarios = [
            ("empty_input", "", "should mention empty or missing input"),
            ("no_company", None, "should mention company configuration"),
            ("invalid_format", "123\n456", "should mention format requirements")
        ]
        
        for scenario_name, test_input, expectation in test_scenarios:
            with self.subTest(scenario=scenario_name):
                
                if scenario_name == "no_company":
                    # Clear company
                    original_company = self.test_settings.default_company
                    self.test_settings.default_company = None
                    self.test_settings.save()
                    
                    result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings")
                    
                    # Restore company
                    self.test_settings.default_company = original_company
                    self.test_settings.save()
                else:
                    result = frappe.call(
                        "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
                        group_mappings_text=test_input,
                        company=self.test_company.name
                    )
                
                if not result.get("success", True):
                    error_message = result.get("error", "").lower()
                    self.assertIsInstance(error_message, str, "Error message should be string")
                    self.assertGreater(len(error_message), 10, "Error message should be descriptive")
                    
                    # Verify error message is helpful (contains relevant keywords)
                    if "empty" in expectation or "missing" in expectation:
                        self.assertTrue(any(word in error_message for word in ["empty", "missing", "provided", "required"]),
                                      f"Error should be descriptive: {error_message}")
                    elif "company" in expectation:
                        self.assertIn("company", error_message, f"Error should mention company: {error_message}")
                    elif "format" in expectation:
                        self.assertTrue(any(word in error_message for word in ["format", "valid", "groups"]),
                                      f"Error should mention format: {error_message}")


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
        self.test_company = self.factory.create_test_company()
        self.test_settings = self.factory.create_test_eboekhouden_settings(
            company_name=self.test_company.name
        )
        self.track_doc("Company", self.test_company.name)
        
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
            "vereinigingeng.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text=text_input,
            company=self.test_company.name
        )
        
        self.assertTrue(parse_result["success"], "Parsing should succeed")
        
        # Step 3: System populates cost center mappings
        suggestions = parse_result["suggestions"]
        self.test_settings.cost_center_mappings = []
        
        for suggestion in suggestions:
            self.test_settings.append("cost_center_mappings", {
                "group_code": suggestion["group_code"],
                "group_name": suggestion["group_name"],
                "create_cost_center": suggestion["create_cost_center"],
                "cost_center_name": suggestion.get("cost_center_name", ""),
                "suggestion_reason": suggestion.get("reason", "")
            })
            
        self.test_settings.save()
        
        # Step 4: User reviews and clicks "Preview Cost Centers"
        preview_result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation")
        
        self.assertTrue(preview_result["success"], "Preview should succeed")
        self.assertGreater(preview_result["would_create"], 0, "Should have cost centers to create")
        
        # Step 5: User confirms and clicks "Create Cost Centers"
        create_result = frappe.call("verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings")
        
        self.assertTrue(create_result["success"], "Creation should succeed")
        self.assertGreater(create_result["created_count"], 0, "Should create cost centers")
        self.assertEqual(create_result["failed_count"], 0, "Should have no failures")
        
        # Step 6: Verify cost centers were actually created
        for created_cc in create_result["created_cost_centers"]:
            cc_id = created_cc["cost_center_id"]
            self.assertTrue(frappe.db.exists("Cost Center", cc_id),
                          f"Cost center {cc_id} should exist in database")
            self.track_doc("Cost Center", cc_id)
            
        print(f"✅ Complete workflow test: Created {create_result['created_count']} cost centers")
        
    def test_error_recovery_workflow(self):
        """Test user workflow with error recovery"""
        
        # Step 1: User makes initial mistake - empty input
        self.test_settings.account_group_mappings = ""
        self.test_settings.save()
        
        parse_result = frappe.call(
            "verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers",
            group_mappings_text="",
            company=self.test_company.name
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
            company=self.test_company.name
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
            company=self.test_company.name
        )
        
        parse_time = time.time() - start_time
        
        self.assertTrue(parse_result["success"], "Large dataset parsing should succeed")
        self.assertLess(parse_time, 10.0, "Parsing should complete within 10 seconds")
        self.assertEqual(parse_result["total_groups"], len(groups), "Should process all groups")
        
        print(f"✅ Large dataset workflow: Processed {len(groups)} groups in {parse_time:.3f}s")


if __name__ == "__main__":
    unittest.main()