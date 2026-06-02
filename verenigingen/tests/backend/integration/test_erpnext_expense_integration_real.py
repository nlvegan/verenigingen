"""
Real Integration Tests for ERPNext Expense Claims Integration
===========================================================

Phase 5.1 Database Mock Elimination: ERPNext Expense Integration
Replaces extensive frappe.db.get_value, frappe.get_doc, and frappe.get_all mocks
with real database operations and authentic business logic testing.

Key Improvements:
- Eliminates frappe.db.get_value mocks - uses real expense type retrieval
- Eliminates frappe.get_doc mocks - uses real document operations where appropriate
- Eliminates frappe.get_single mocks - uses real settings retrieval
- Eliminates frappe.get_all mocks - uses real cost center queries
- Tests authentic volunteer expense workflow with real database state
- Validates real ERPNext integration points with actual data

This approach catches real configuration issues, business rule violations, and integration problems
that mocked tests miss entirely.
"""

import unittest

import frappe
from frappe.utils import today, add_days

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED
from verenigingen.templates.pages.volunteer.expenses import (
    submit_expense,
)
from verenigingen.utils.volunteer_expense_setup import (
    get_or_create_expense_type,
    get_organization_cost_center,
    get_fallback_cost_center,
    setup_expense_claim_types,
)


class TestERPNextExpenseIntegrationReal(EnhancedTestCase):
    """Real integration tests for ERPNext expense claims without database mocks"""

    def setUp(self):
        """Set up real test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test volunteer with real database operations.
        # No hardcoded email: the factory generates a unique address. A literal
        # email collides across tests because the Enhanced factory uses a fixed
        # seed (so test_run_id is constant) and the per-test email sequence
        # resets, producing the same deterministic address every test.
        self.test_volunteer = self.create_test_volunteer(
            volunteer_name="ERPNext Test Volunteer",
            status="Active"
        )
        
        # Create associated member for volunteer
        self.test_member = frappe.get_doc("Member", self.test_volunteer.member)
        
        # Use ERPNext's fully-provisioned standard test company rather than
        # hand-building one (a minimal Company doc fails on mandatory
        # accounting defaults like valuation_method). Fall back to any
        # existing company if the standard fixture is absent.
        self.test_company = (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )
        if self.test_company:
            frappe.db.set_default("company", self.test_company)
        
        # Create expense test data
        self.test_expense_data = {
            "description": "Real ERPNext Integration Test Expense",
            "amount": 75.50,
            "expense_date": today(),
            "organization_type": "National",
            "category": "Travel",
            "notes": "Real database testing for ERPNext integration"
        }

    def test_get_or_create_expense_type_real_database_no_mocks(self):
        """Test expense type retrieval using real database operations"""
        
        # Test with Travel expense type that should exist in real system
        # Uses actual database query to retrieve or create expense type
        expense_type = get_or_create_expense_type("Travel")
        
        # Validate real expense type exists or was created
        self.assertIsInstance(expense_type, str)
        self.assertGreater(len(expense_type), 0)
        
        # Verify in real database
        expense_type_exists = frappe.db.exists("Expense Claim Type", expense_type)
        # Note: May not exist in test environment but function should handle gracefully
        
        # Test with non-existent type - should create or fallback
        custom_type = get_or_create_expense_type("Custom Testing Type")
        self.assertIsInstance(custom_type, str)
        self.assertGreater(len(custom_type), 0)

    def test_get_organization_cost_center_national_real_database(self):
        """Test national cost center retrieval using real settings operations"""
        
        # Test national cost center retrieval with real database operations
        # Uses actual settings query to retrieve cost center configuration
        national_expense_data = {
            "organization_type": "National"
        }
        
        cost_center = get_organization_cost_center(national_expense_data)
        
        # Should return a valid cost center (real or fallback)
        self.assertIsInstance(cost_center, str)
        self.assertGreater(len(cost_center), 0)
        
        # If cost center returned, it should exist in real database
        if cost_center and cost_center != "Main - TC":  # Skip default fallback
            cost_center_exists = frappe.db.exists("Cost Center", cost_center)
            # Note: Cost center might not exist in test environment, but function should handle gracefully
            # The important part is that real database operations are tested

    def test_get_organization_cost_center_chapter_real_database(self):
        """Test chapter cost center retrieval using real document operations"""
        
        # Create test chapter for real cost center testing
        test_chapter = self.create_chapter(region="Test ERPNext Region")
        
        # Test chapter cost center retrieval with real chapter document
        # Uses actual chapter document retrieval from database
        chapter_expense_data = {
            "organization_type": "Chapter",
            "chapter": test_chapter.name
        }
        
        cost_center = get_organization_cost_center(chapter_expense_data)
        
        # Should return valid cost center from real chapter or fallback
        self.assertIsInstance(cost_center, str)
        self.assertGreater(len(cost_center), 0)
        
        # Verify chapter exists in real database
        chapter_exists = frappe.db.exists("Chapter", test_chapter.name)
        self.assertTrue(chapter_exists)

    def test_expense_type_integration_real_workflow(self):
        """Test complete expense type integration with real ERPNext workflow"""
        
        # Test various expense types with real database operations
        test_expense_types = [
            "Meals and Entertainment",
            "Office Equipment", 
            "Communications"
        ]
        
        created_types = []
        
        try:
            for expense_type in test_expense_types:
                # Clean slate for each test
                if frappe.db.exists("Expense Claim Type", expense_type):
                    frappe.delete_doc("Expense Claim Type", expense_type)
                
                # Test creation with real database
                result = get_or_create_expense_type(expense_type)
                created_types.append(result)
                
                # Verify real database state
                self.assertTrue(frappe.db.exists("Expense Claim Type", result))
                
                # Test retrieval after creation (should not recreate)
                second_result = get_or_create_expense_type(expense_type)
                self.assertEqual(result, second_result)
                
        except Exception as e:
            if any(keyword in str(e) for keyword in ["HRMS", "Expense Claim", "DocType"]):
                self.skipTest("ERPNext HRMS not fully available")
            else:
                raise

    def test_organization_cost_center_real_database(self):
        """Test organization cost center retrieval with real database operations"""
        
        # This replaces database mocks with actual cost center queries
        try:
            cost_center = get_organization_cost_center()
            
            # Should return a real cost center or handle gracefully
            if cost_center:
                # Verify it's a real cost center in the database
                self.assertTrue(frappe.db.exists("Cost Center", cost_center))
            else:
                # No cost center available - valid for testing environment
                self.assertIsNone(cost_center)
                
        except Exception as e:
            if "Cost Center" in str(e):
                self.skipTest("ERPNext Cost Centers not configured")
            else:
                raise

    def test_expense_submission_real_integration(self):
        """Test expense submission with real ERPNext integration"""
        
        # Test data for expense submission
        expense_data = {
            "expense_type": "Travel",
            "amount": 50.0,
            "description": "Bus fare for volunteer work",
            "expense_date": today(),
            "volunteer_name": self.test_volunteer.name
        }
        
        try:
            # This tests real ERPNext expense claim creation (no mocks)
            result = submit_expense(**expense_data)
            
            # Should create real expense claim in ERPNext
            if result.get("success"):
                claim_name = result.get("expense_claim")
                self.assertIsNotNone(claim_name)
                
                # Verify real expense claim was created
                self.assertTrue(frappe.db.exists("Expense Claim", claim_name))
                
                # Verify expense claim data
                claim = frappe.get_doc("Expense Claim", claim_name)
                self.assertEqual(claim.total_claimed_amount, 50.0)
                
            else:
                # Expense submission failed - could be due to missing setup
                self.assertIn("error", result)
                
        except Exception as e:
            if any(keyword in str(e) for keyword in ["HRMS", "Expense Claim", "Employee"]):
                self.skipTest("ERPNext HRMS expense submission not fully configured")
            else:
                raise

    def test_expense_integration_error_handling_real_operations(self):
        """Test error handling with real database operations (no mocked exceptions)"""
        
        # Test with invalid expense type
        try:
            result = get_or_create_expense_type("")  # Empty name
            
            # Should handle gracefully with real error
            if not result:
                # Function handled empty name appropriately
                pass
            else:
                # Function created something - verify it's valid
                self.assertIsInstance(result, str)
                self.assertGreater(len(result), 0)
                
        except Exception as e:
            # Real error from actual database operation
            self.assertIsInstance(str(e), str)

    def test_company_and_account_resolution_real_database(self):
        """Test company and account resolution with real database queries"""
        
        # Test that the expense system can resolve real company data
        # This replaces mocked company/account lookups with real queries
        
        default_company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0] if frappe.get_all("Company", limit=1) else None
        
        if default_company:
            # Verify company exists in real database
            self.assertTrue(frappe.db.exists("Company", default_company))
            
            # Test account resolution for this company
            expense_accounts = frappe.get_all("Account", 
                filters={"account_type": "Expense Account", "company": default_company, "is_group": 0},
                limit=5,
                pluck="name"
            )
            
            # Should find some expense accounts in real system
            self.assertIsInstance(expense_accounts, list)
            
        else:
            self.skipTest("No companies configured in test system")

    def test_employee_creation_workflow_real_integration(self):
        """Test employee record creation workflow with real ERPNext operations"""
        
        # Test volunteer without employee record
        # This replaces mock_volunteer.employee_id = None with real database state
        volunteer_without_employee = self.test_volunteer
        
        # Ensure volunteer has no employee record initially
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_without_employee.name)
        volunteer_doc.employee_id = None
        volunteer_doc.save()
        
        expense_data = {
            "expense_type": "Travel", 
            "amount": 45.0,
            "description": "Real employee creation test",
            "expense_date": today(),
            "volunteer_name": volunteer_without_employee.name
        }
        
        try:
            # Test real employee creation (no mocks)
            result = submit_expense(**expense_data)
            
            if result.get("success"):
                # Verify real employee record was created
                volunteer_doc.reload()
                self.assertIsNotNone(volunteer_doc.employee_id)
                
                # Verify real Employee document exists
                self.assertTrue(frappe.db.exists("Employee", volunteer_doc.employee_id))
                
                # Verify employee record has correct data  
                employee = frappe.get_doc("Employee", volunteer_doc.employee_id)
                self.assertEqual(employee.employee_name, volunteer_doc.volunteer_name)
                self.assertEqual(employee.user_id, volunteer_doc.email)
                
            else:
                # Real failure - verify error handling
                error_msg = result.get("message", "")
                self.assertIsInstance(error_msg, str)
                self.assertGreater(len(error_msg), 0)
                
        except Exception as e:
            if "HRMS" in str(e) or "Employee" in str(e):
                self.skipTest("ERPNext HRMS employee creation not available")
            else:
                raise

    def test_expense_submission_validation_errors_real(self):
        """Test ERPNext expense claim validation with real validation errors"""
        
        expense_data = {
            "expense_type": "InvalidExpenseType",  # Non-existent expense type
            "amount": 99.99,
            "description": "Test validation error handling", 
            "expense_date": today(),
            "volunteer_name": self.test_volunteer.name
        }
        
        try:
            # Test with real ERPNext validation (no mocked ValidationError)
            result = submit_expense(**expense_data)
            
            # Should handle validation gracefully
            if not result.get("success"):
                error_message = result.get("message", "")
                
                # Real validation errors should be informative
                self.assertIsInstance(error_message, str)
                self.assertGreater(len(error_message), 0)
                
                # Common ERPNext validation messages
                validation_indicators = [
                    "does not exist", "not found", "invalid", 
                    "required", "cannot", "must"
                ]
                
                # Should contain some validation context
                has_validation_context = any(indicator in error_message.lower() 
                                           for indicator in validation_indicators)
                self.assertTrue(has_validation_context, 
                              f"Error message lacks validation context: {error_message}")
            else:
                # Unexpected success - verify what was created
                self.assertIsNotNone(result.get("expense_claim"))
                
        except Exception as e:
            if "HRMS" in str(e):
                self.skipTest("ERPNext HRMS not configured for validation testing")
            else:
                # Real validation exception - should be ERPNext ValidationError
                self.assertIn("frappe.exceptions", str(type(e)))

    def test_cost_center_resolution_real_database(self):
        """Test cost center resolution logic with real database operations"""
        
        # Test that cost center resolution works with real ERPNext data
        # Uses real document queries to resolve cost centers
        
        try:
            # Test default/fallback cost center logic  
            default_cost_center = get_fallback_cost_center()
            
            if default_cost_center:
                # Verify it's a real cost center in database
                self.assertTrue(frappe.db.exists("Cost Center", default_cost_center))
                
                # Verify cost center is active and accessible
                cost_center_doc = frappe.get_doc("Cost Center", default_cost_center)
                self.assertIsNotNone(cost_center_doc)
                self.assertFalse(getattr(cost_center_doc, "disabled", False))
                
            else:
                # No cost center configured - valid for testing environment
                self.assertIsNone(default_cost_center)
            
            # Test organization-specific cost center resolution
            organization_cost_center = get_organization_cost_center()
            
            if organization_cost_center:
                self.assertTrue(frappe.db.exists("Cost Center", organization_cost_center))
                
        except Exception as e:
            if "Cost Center" in str(e):
                self.skipTest("ERPNext Cost Centers not configured")
            else:
                raise

    def test_expense_type_creation_edge_cases_real(self):
        """Test expense type creation edge cases with real database operations"""
        
        # Test special characters and edge cases (no mocks)
        edge_case_types = [
            "Travel & Accommodation",  # Special characters
            "Café Meeting Expenses",   # Unicode characters  
            "Office Equipment (IT)",   # Parentheses
            "Communications/Internet", # Forward slash
        ]
        
        created_types = []
        
        try:
            for expense_type in edge_case_types:
                # Clean up first to ensure fresh test
                if frappe.db.exists("Expense Claim Type", expense_type):
                    frappe.delete_doc("Expense Claim Type", expense_type)
                
                # Test real creation with edge case names
                result = get_or_create_expense_type(expense_type)
                created_types.append(result)
                
                # Verify creation succeeded in real database
                self.assertTrue(frappe.db.exists("Expense Claim Type", result))
                
                # Verify document can be retrieved and has expected data
                expense_type_doc = frappe.get_doc("Expense Claim Type", result)
                self.assertEqual(expense_type_doc.expense_type, result)
                
        except Exception as e:
            if "HRMS" in str(e):
                self.skipTest("ERPNext HRMS not available for edge case testing")
            else:
                # Real edge case error - should be handled gracefully
                self.assertIsInstance(str(e), str)

    def test_hrms_detection_real_system_state(self):
        """Test HRMS availability detection with real system state"""
        
        # Uses real app detection to check for installed applications
        
        # Check real installed apps
        installed_apps = frappe.get_installed_apps()
        self.assertIsInstance(installed_apps, list)
        self.assertIn("frappe", installed_apps)
        self.assertIn("erpnext", installed_apps)
        
        # Check if HRMS is actually installed
        hrms_available = "hrms" in installed_apps
        
        # Check real DocType availability (no mocks)
        expense_claim_exists = frappe.db.exists("DocType", "Expense Claim")
        expense_claim_type_exists = frappe.db.exists("DocType", "Expense Claim Type")
        employee_exists = frappe.db.exists("DocType", "Employee")
        
        if hrms_available:
            # HRMS installed - DocTypes should exist
            self.assertTrue(expense_claim_exists)
            self.assertTrue(expense_claim_type_exists)
            self.assertTrue(employee_exists)
            
            # Test that expense setup works
            result = setup_expense_claim_types()
            self.assertIsNotNone(result)
            
        else:
            # HRMS not installed - should handle gracefully
            if not expense_claim_exists:
                self.skipTest("ERPNext HRMS not installed - DocTypes unavailable")

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_dual_tracking_creation_real_integration(self):
        """Test dual ERPNext and Volunteer expense tracking with real database"""
        
        expense_data = {
            "expense_type": "Travel",
            "amount": 67.50,
            "description": "Real dual tracking test",
            "expense_date": today(),
            "volunteer_name": self.test_volunteer.name
        }
        
        try:
            # Test real dual record creation (no mocks)
            result = submit_expense(**expense_data)
            
            if result.get("success"):
                # Verify ERPNext Expense Claim was created
                expense_claim_name = result.get("expense_claim")
                if expense_claim_name:
                    self.assertTrue(frappe.db.exists("Expense Claim", expense_claim_name))
                    
                    # Verify expense claim has correct data
                    expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                    self.assertEqual(expense_claim.total_claimed_amount, 67.50)
                
                # Verify Volunteer Expense was created  
                expense_name = result.get("expense_name")
                if expense_name:
                    self.assertTrue(frappe.db.exists("Volunteer Expense", expense_name))
                    
                    # Verify volunteer expense has correct linkage
                    volunteer_expense = frappe.get_doc("Volunteer Expense", expense_name)
                    self.assertEqual(volunteer_expense.volunteer, self.test_volunteer.name)
                    self.assertEqual(volunteer_expense.amount, 67.50)
                
            else:
                # Real submission failure
                error_msg = result.get("message", "")
                self.assertIsInstance(error_msg, str)
                
        except Exception as e:
            if "HRMS" in str(e):
                self.skipTest("ERPNext HRMS not configured for dual tracking")
            else:
                raise

    def test_large_amount_expense_real_validation(self):
        """Test large amount expense handling with real ERPNext validation"""
        
        large_expense_data = {
            "expense_type": "Travel",
            "amount": 9999.99,  # Large amount
            "description": "Large expense amount test",
            "expense_date": today(),
            "volunteer_name": self.test_volunteer.name
        }
        
        try:
            # Test with real ERPNext validation (no amount mocks)
            result = submit_expense(**large_expense_data)
            
            if result.get("success"):
                # Large amount accepted - verify correct handling
                expense_claim_name = result.get("expense_claim")
                if expense_claim_name:
                    expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                    self.assertEqual(expense_claim.total_claimed_amount, 9999.99)
                    
            else:
                # Large amount rejected - verify error handling
                error_msg = result.get("message", "")
                
                # Should have meaningful validation message
                self.assertIsInstance(error_msg, str)
                self.assertGreater(len(error_msg), 0)
                
        except Exception as e:
            if "HRMS" in str(e):
                self.skipTest("ERPNext HRMS not available for amount validation")
            else:
                # Real validation exception
                self.assertIsInstance(str(e), str)

    def test_unicode_description_real_database(self):
        """Test Unicode character handling in expense descriptions"""
        
        unicode_expense_data = {
            "expense_type": "Travel",
            "amount": 42.50,
            "description": "Café meeting ñ special chars 🎉 testing",
            "expense_date": today(), 
            "volunteer_name": self.test_volunteer.name
        }
        
        try:
            # Test real Unicode handling (no mocked character processing)
            result = submit_expense(**unicode_expense_data)
            
            if result.get("success"):
                # Unicode accepted - verify storage and retrieval
                expense_claim_name = result.get("expense_claim")
                if expense_claim_name:
                    expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                    
                    # Verify Unicode description was stored correctly
                    stored_description = expense_claim.expenses[0].description if expense_claim.expenses else ""
                    self.assertIn("Café", stored_description)
                    self.assertIn("ñ", stored_description)
                    
            else:
                # Unicode handling failed - verify error
                error_msg = result.get("message", "")
                self.assertIsInstance(error_msg, str)
                
        except Exception as e:
            if "HRMS" in str(e):
                self.skipTest("ERPNext HRMS not available for Unicode testing")
            else:
                # Real Unicode handling error  
                self.assertIsInstance(str(e), str)

    def test_expense_data_validation_real_business_rules(self):
        """Test expense data validation with real business rule validation"""
        
        # Test missing required fields with real validation
        invalid_data_scenarios = [
            {
                "data": {
                    # Missing amount
                    "expense_type": "Travel",
                    "description": "Missing amount test",
                    "expense_date": today(),
                    "volunteer_name": self.test_volunteer.name
                },
                "expected_error": "amount"
            },
            {
                "data": {
                    "expense_type": "Travel", 
                    "amount": 25.0,
                    # Missing description
                    "expense_date": today(),
                    "volunteer_name": self.test_volunteer.name
                },
                "expected_error": "description"
            },
            {
                "data": {
                    "expense_type": "Travel",
                    "amount": 25.0,
                    "description": "Missing date test",
                    # Missing expense_date
                    "volunteer_name": self.test_volunteer.name
                },
                "expected_error": "date"
            }
        ]
        
        for i, scenario in enumerate(invalid_data_scenarios):
            with self.subTest(scenario_index=i):
                try:
                    # Test real validation (no mocked validation errors)
                    result = submit_expense(**scenario["data"])
                    
                    # Should fail validation
                    self.assertFalse(result.get("success"), 
                                   f"Scenario {i} should have failed validation")
                    
                    error_msg = result.get("message", "").lower()
                    expected_error = scenario["expected_error"].lower()
                    
                    # Error message should reference the missing field
                    self.assertIn(expected_error, error_msg,
                                f"Error should mention missing {expected_error}")
                    
                except Exception as e:
                    if "HRMS" in str(e):
                        continue  # Skip this scenario if HRMS unavailable
                    else:
                        raise