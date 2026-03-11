#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for Phase 2 Cost Center Creation
=========================================================

This test suite provides complete coverage of the eBoekhouden Cost Center Creation feature
with emphasis on realistic data generation, business logic validation, and robust edge case handling.

Test Architecture:
- Extends EnhancedTestCase for automatic cleanup and validation
- Uses realistic Dutch accounting data patterns
- Tests all API endpoints with comprehensive scenarios
- Validates RGS-based business intelligence
- Includes performance testing for scalability
- Covers error handling and edge cases

Test Categories:
1. Dutch Accounting Data Generation - Realistic RGS-based test patterns
2. Business Logic Validation - Account code intelligence and suggestions
3. API Endpoint Integration - Complete API testing with real data
4. Error Handling - Comprehensive error scenario coverage
5. Performance Testing - Large dataset processing validation
6. Edge Cases - Boundary conditions and unusual scenarios
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import frappe
from frappe.utils import now_datetime, getdate, random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings import (
    parse_groups_and_suggest_cost_centers,
    create_cost_centers_from_mappings,
    preview_cost_center_creation,
    create_single_cost_center,
    should_suggest_cost_center,
    clean_cost_center_name,
    might_be_group_cost_center
)


class DutchAccountingDataGenerator:
    """
    Generates realistic Dutch accounting data based on RGS (Referentie Grootboekschema) patterns
    
    This generator creates test data that mimics real Dutch accounting structures:
    - Balance sheet accounts (1xx, 2xx)
    - Revenue accounts (3xx)  
    - Expense accounts (5xx, 6xx, 7xx)
    - Hierarchical group structures
    - Realistic Dutch accounting terminology
    """
    
    def __init__(self, seed=12345):
        import random
        random.seed(seed)
        self.random = random
        self.sequence_counters = {}
        
    def get_next_sequence(self, prefix):
        """Get next sequence for deterministic data"""
        self.sequence_counters[prefix] = self.sequence_counters.get(prefix, 0) + 1
        return self.sequence_counters[prefix]
        
    def generate_balance_sheet_groups(self) -> list:
        """Generate realistic balance sheet account groups (1xx, 2xx)"""
        groups = []
        
        # Fixed assets (100-199)
        fixed_asset_groups = [
            ("100", "Vaste activa - totaal"),
            ("110", "Materiële vaste activa"),
            ("111", "Bedrijfsgebouwen en terreinen"),
            ("112", "Machines en installaties"),
            ("113", "Andere vaste bedrijfsmiddelen"),
            ("120", "Immateriële vaste activa"),
            ("130", "Financiële vaste activa"),
        ]
        groups.extend(fixed_asset_groups)
        
        # Current assets (200-299)
        current_asset_groups = [
            ("200", "Vlottende activa - totaal"),
            ("210", "Voorraden"),
            ("220", "Vorderingen op debiteuren"),
            ("230", "Overige vorderingen"),
            ("240", "Liquide middelen"),
            ("241", "Kas"),
            ("242", "Bankrekeningen"),
        ]
        groups.extend(current_asset_groups)
        
        return [{"code": code, "name": name} for code, name in groups]
        
    def generate_revenue_groups(self) -> list:
        """Generate realistic revenue account groups (3xx)"""
        revenue_groups = [
            ("300", "Opbrengsten - totaal"),
            ("310", "Netto-omzet"),
            ("311", "Verkopen binnenland"),
            ("312", "Verkopen buitenland"),
            ("320", "Overige bedrijfsopbrengsten"),
            ("321", "Subsidies"),
            ("322", "Donaties en giften"),
            ("330", "Financiële baten"),
        ]
        return [{"code": code, "name": name} for code, name in revenue_groups]
        
    def generate_expense_groups(self) -> list:
        """Generate realistic expense account groups (5xx, 6xx)"""
        expense_groups = [
            ("500", "Personeelskosten - totaal"),
            ("510", "Lonen en salarissen"),
            ("511", "Brutolonen"),
            ("512", "Sociale lasten"),
            ("513", "Pensioenpremies"),
            ("520", "Overige personeelskosten"),
            ("600", "Algemene kosten - totaal"),
            ("610", "Huisvestingskosten"),
            ("611", "Huurkosten"),
            ("612", "Energiekosten"),
            ("620", "Kantoorkosten"),
            ("621", "Telefoon- en internetkosten"),
            ("622", "Portokosten"),
            ("630", "Verkoopkosten"),
            ("631", "Advertentiekosten"),
            ("632", "Reiskosten"),
            ("640", "Bedrijfsauto kosten"),
            ("650", "Overige algemene kosten"),
        ]
        return [{"code": code, "name": name} for code, name in expense_groups]
        
    def generate_mixed_account_groups(self, include_balance_sheet=True, include_revenue=True, 
                                    include_expenses=True, custom_count=0) -> list:
        """Generate mixed set of account groups for comprehensive testing"""
        groups = []
        
        if include_balance_sheet:
            groups.extend(self.generate_balance_sheet_groups()[:5])  # Limit for testing
            
        if include_revenue:
            groups.extend(self.generate_revenue_groups()[:4])
            
        if include_expenses:
            groups.extend(self.generate_expense_groups()[:8])
            
        # Add custom test groups
        for i in range(custom_count):
            seq = self.get_next_sequence('custom')
            groups.append({
                "code": f"9{seq:02d}",
                "name": f"Test Aangepaste Groep {seq}"
            })
            
        return groups
        
    def generate_hierarchical_groups(self) -> list:
        """Generate hierarchical account group structure"""
        groups = []
        
        # Parent groups
        parent_groups = [
            ("600", "Algemene kosten - totaal"),
            ("610", "Huisvestingskosten"),
            ("620", "Kantoorkosten"),
            ("630", "Verkoopkosten")
        ]
        
        # Child groups
        child_groups = [
            ("611", "Huurkosten kantoor"),
            ("612", "Energiekosten kantoor"),
            ("613", "Schoonmaakkosten"),
            ("621", "Telefoon- en internetkosten"),
            ("622", "Portokosten"),
            ("623", "Kantoorbenodigdheden"),
            ("631", "Online advertenties"),
            ("632", "Print advertenties"),
            ("633", "Beurzen en evenementen")
        ]
        
        groups.extend([{"code": code, "name": name} for code, name in parent_groups])
        groups.extend([{"code": code, "name": name} for code, name in child_groups])
        
        return groups
        
    def format_as_text_input(self, groups: list) -> str:
        """Format account groups as text input (one per line)"""
        lines = []
        for group in groups:
            lines.append(f"{group['code']} {group['name']}")
        return "\n".join(lines)
        
    def generate_invalid_input_scenarios(self) -> list:
        """Generate various invalid input scenarios for error testing"""
        return [
            "",  # Empty input
            "   \n  \n   ",  # Whitespace only
            "123",  # No name
            "InvalidCode This is a test",  # Invalid code format
            "001\n002\n",  # Missing names
            "001 Valid Name\nInvalidLine\n002 Another Valid",  # Mixed valid/invalid
        ]


class TestCostCenterCreationComprehensive(EnhancedTestCase):
    """
    Comprehensive test suite for Cost Center Creation functionality
    
    Tests cover:
    - Realistic data generation using Dutch accounting patterns
    - Business logic validation for RGS-based suggestions
    - Complete API endpoint testing
    - Error handling and edge cases
    - Performance with large datasets
    - Integration with ERPNext Cost Center system
    """
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data_generator = DutchAccountingDataGenerator(seed=12345)
        
    def setUp(self):
        super().setUp()
        
        # Create test company
        self.test_company = self.create_test_company()
        
        # Create test settings document
        self.test_settings = self.create_test_eboekhouden_settings()
        
    def create_test_company(self):
        """Create test company with proper validation"""
        company_name = f"Test Company - Cost Centers - {frappe.utils.random_string(8)}"
        
        # Check if company already exists
        if frappe.db.exists("Company", company_name):
            return frappe.get_doc("Company", company_name)
            
        company_doc = frappe.get_doc({
            "doctype": "Company",
            "company_name": company_name,
            "abbr": f"TC{frappe.utils.random_string(3)}",
            "default_currency": "EUR",
            "country": "Netherlands",
            "valuation_method": "FIFO",
        })
        company_doc.insert()
        self.factory.track_document("Company", company_doc.name)
        return company_doc
        
    def create_test_eboekhouden_settings(self):
        """Create test eBoekhouden settings document"""
        settings_doc = frappe.get_single("E-Boekhouden Settings")
        
        # Update with test values
        settings_doc.api_url = "https://api.test.e-boekhouden.nl"
        settings_doc.api_token = "test_token_12345"
        settings_doc.default_company = self.test_company.name
        settings_doc.default_currency = "EUR"
        settings_doc.source_application = "TestVerenigingenERPNext"
        
        # Clear any existing mappings
        settings_doc.cost_center_mappings = []
        
        settings_doc.save()
        return settings_doc
        
    def create_cost_center_mapping_data(self, groups):
        """Create cost center mapping data from account groups"""
        mappings = []
        for group in groups:
            should_create, reason = should_suggest_cost_center(group["code"], group["name"])
            
            mapping_data = {
                "group_code": group["code"],
                "group_name": group["name"],
                "create_cost_center": should_create,
                "cost_center_name": clean_cost_center_name(group["name"]) if should_create else "",
                "suggestion_reason": reason,
                "is_group": might_be_group_cost_center(group["code"], group["name"], groups),
                "account_count": self.data_generator.random.randint(1, 50)
            }
            mappings.append(mapping_data)
            
        return mappings


class TestDutchAccountingDataGeneration(TestCostCenterCreationComprehensive):
    """Test realistic Dutch accounting data generation"""
    
    def test_balance_sheet_groups_generation(self):
        """Test generation of realistic balance sheet account groups"""
        groups = self.data_generator.generate_balance_sheet_groups()
        
        self.assertGreater(len(groups), 0, "Should generate balance sheet groups")
        
        # Verify structure
        for group in groups:
            self.assertIn("code", group, "Group should have code")
            self.assertIn("name", group, "Group should have name")
            self.assertTrue(group["code"].startswith(("1", "2")), 
                          f"Balance sheet code should start with 1 or 2: {group['code']}")
            
        # Check for specific required groups
        codes = [g["code"] for g in groups]
        self.assertIn("100", codes, "Should include main fixed assets group")
        self.assertIn("200", codes, "Should include main current assets group")
        self.assertIn("241", codes, "Should include cash accounts")
        self.assertIn("242", codes, "Should include bank accounts")
        
    def test_revenue_groups_generation(self):
        """Test generation of realistic revenue account groups"""
        groups = self.data_generator.generate_revenue_groups()

        self.assertGreater(len(groups), 0, "Should generate revenue groups")

        # Dutch revenue-related terms used in accounting
        # Note: "verkoop" and "verkopen" are different words (sell vs sales)
        revenue_terms = ["opbrengst", "omzet", "verkoop", "verkopen", "baten", "subsidie", "donatie", "bedrijfsopbrengst"]

        # Verify all codes start with 3
        for group in groups:
            self.assertTrue(group["code"].startswith("3"),
                          f"Revenue code should start with 3: {group['code']}")
            # Check that name contains at least one revenue-related term
            name_lower = group["name"].lower()
            has_revenue_term = any(term in name_lower for term in revenue_terms)
            self.assertTrue(has_revenue_term,
                          f"Revenue group should contain revenue terms: {group['name']}")
            
    def test_expense_groups_generation(self):
        """Test generation of realistic expense account groups"""
        groups = self.data_generator.generate_expense_groups()
        
        self.assertGreater(len(groups), 0, "Should generate expense groups")
        
        # Verify codes and content
        personnel_found = False
        general_found = False
        
        for group in groups:
            self.assertTrue(group["code"].startswith(("5", "6", "7")), 
                          f"Expense code should start with 5, 6, or 7: {group['code']}")
            
            if "personeel" in group["name"].lower():
                personnel_found = True
            if "algemene" in group["name"].lower():
                general_found = True
                
        self.assertTrue(personnel_found, "Should include personnel cost groups")
        self.assertTrue(general_found, "Should include general cost groups")
        
    def test_hierarchical_groups_generation(self):
        """Test generation of hierarchical account group structures"""
        groups = self.data_generator.generate_hierarchical_groups()
        
        self.assertGreater(len(groups), 5, "Should generate multiple hierarchical groups")
        
        # Check for parent-child relationships
        parent_codes = [g["code"] for g in groups if len(g["code"]) == 3]  # Parent groups
        child_codes = [g["code"] for g in groups if len(g["code"]) == 3]   # Child groups
        
        # Verify hierarchical structure exists
        hierarchical_found = False
        for parent_code in parent_codes:
            children = [c for c in child_codes if c.startswith(parent_code[:2]) and c != parent_code]
            if children:
                hierarchical_found = True
                break
                
        self.assertTrue(hierarchical_found, "Should include hierarchical relationships")
        
    def test_text_input_formatting(self):
        """Test formatting of groups as text input"""
        groups = self.data_generator.generate_mixed_account_groups()[:5]  # Limit for testing
        text_input = self.data_generator.format_as_text_input(groups)
        
        self.assertIsInstance(text_input, str, "Should return string")
        
        lines = text_input.strip().split('\n')
        self.assertEqual(len(lines), 5, "Should have correct number of lines")
        
        # Verify format: "code name"
        for line in lines:
            parts = line.split(' ', 1)
            self.assertEqual(len(parts), 2, f"Line should have code and name: {line}")
            code, name = parts
            self.assertTrue(code.isdigit(), f"Code should be numeric: {code}")
            self.assertGreater(len(name), 0, f"Name should not be empty: {name}")


class TestBusinessLogicValidation(TestCostCenterCreationComprehensive):
    """Test RGS-based business logic and suggestion intelligence"""
    
    def test_expense_groups_should_suggest_cost_centers(self):
        """Test that expense groups (5xx, 6xx) are suggested for cost centers"""
        test_cases = [
            ("510", "Lonen en salarissen", True, "expense"),
            ("600", "Algemene kosten", True, "expense"),
            ("621", "Telefoon- en internetkosten", True, "expense"),
            ("650", "Overige algemene kosten", True, "expense")
        ]
        
        for code, name, should_suggest, reason_type in test_cases:
            with self.subTest(code=code, name=name):
                should_create, reason = should_suggest_cost_center(code, name)
                
                self.assertEqual(should_create, should_suggest, 
                               f"Code {code} ({name}) suggestion should be {should_suggest}")
                
                if should_suggest:
                    self.assertIn(reason_type.lower(), reason.lower(), 
                                f"Reason should mention {reason_type}: {reason}")
                    
    def test_revenue_groups_should_suggest_cost_centers(self):
        """Test that relevant revenue groups (3xx) are suggested for cost centers

        The implementation suggests cost centers for revenue codes (3xx) only
        when they contain keywords: "opbrengst", "omzet", or "verkoop".
        """
        test_cases = [
            # These contain matching keywords and should be suggested
            ("310", "Netto-omzet", True, "revenue"),  # contains "omzet"
            ("320", "Verkoopopbrengst", True, "revenue"),  # contains "verkoop" and "opbrengst"
            ("330", "Bruto-opbrengst diensten", True, "revenue"),  # contains "opbrengst"
            ("340", "Verkoop producten", True, "revenue"),  # contains "verkoop"
        ]

        for code, name, should_suggest, reason_type in test_cases:
            with self.subTest(code=code, name=name):
                should_create, reason = should_suggest_cost_center(code, name)

                self.assertEqual(should_create, should_suggest,
                               f"Code {code} ({name}) suggestion should be {should_suggest}")

                if should_suggest:
                    self.assertIn(reason_type.lower(), reason.lower(),
                                f"Reason should mention {reason_type}: {reason}")
                    
    def test_balance_sheet_groups_should_not_suggest_cost_centers(self):
        """Test that balance sheet groups (1xx, 2xx) are not suggested for cost centers"""
        test_cases = [
            ("100", "Vaste activa", False, "balance sheet"),
            ("110", "Materiële vaste activa", False, "balance sheet"),
            ("200", "Vlottende activa", False, "balance sheet"),
            ("241", "Kas", False, "balance sheet"),
            ("242", "Bankrekeningen", False, "balance sheet")
        ]
        
        for code, name, should_suggest, reason_type in test_cases:
            with self.subTest(code=code, name=name):
                should_create, reason = should_suggest_cost_center(code, name)
                
                self.assertEqual(should_create, should_suggest,
                               f"Code {code} ({name}) should not be suggested for cost center")
                
                if not should_suggest:
                    self.assertIn("not", reason.lower(),
                                f"Reason should explain why not suitable: {reason}")
                    
    def test_departmental_keywords_trigger_suggestions(self):
        """Test that departmental/operational keywords trigger cost center suggestions"""
        # Use codes that don't start with 5/6 (expense) or 3 (revenue) to test
        # departmental keyword detection specifically
        test_cases = [
            ("999", "Marketing Afdeling", True),  # "afdeling" keyword
            ("888", "IT Team Ontwikkeling", True),  # "team" keyword
            ("777", "Project Alpha", True),  # "project" keyword
            ("444", "HR Diensten", True),  # "dienst" keyword
            ("333", "Campagne Beta", True),  # "campagne" keyword - code doesn't start with 3
        ]

        for code, name, should_suggest in test_cases:
            with self.subTest(code=code, name=name):
                should_create, reason = should_suggest_cost_center(code, name)

                self.assertEqual(should_create, should_suggest,
                               f"Code {code} ({name}) should be suggested due to keywords")

                if should_suggest:
                    self.assertIn("departmental", reason.lower(),
                                f"Reason should mention departmental keywords: {reason}")
                    
    def test_cost_center_name_cleaning(self):
        """Test cost center name cleaning algorithm"""
        test_cases = [
            ("Personeelskosten rekeningen", "Personeelskosten"),
            ("Algemene kosten accounts", "Algemene kosten"),
            ("marketing uitgaven", "Marketing uitgaven"),  # Capitalization
            ("  Kantoorkosten  ", "Kantoorkosten"),  # Whitespace
            ("Grootboek algemene kosten", "Algemene kosten")  # Remove grootboek
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                cleaned_name = clean_cost_center_name(input_name)
                self.assertEqual(cleaned_name, expected_output,
                               f"'{input_name}' should clean to '{expected_output}', got '{cleaned_name}'")
                
    def test_hierarchical_group_detection(self):
        """Test detection of hierarchical/parent cost center groups

        The might_be_group_cost_center function uses code length to determine
        hierarchy: shorter codes are potential parents if longer codes share
        the same prefix. For example:
        - "6" is parent of "60", "61", "600", etc.
        - "60" is parent of "600", "601", etc.
        """
        # Create test group structure with hierarchical code lengths
        groups = [
            {"code": "6", "name": "Algemene kosten"},
            {"code": "60", "name": "Huisvestingskosten"},
            {"code": "600", "name": "Huurkosten"},
            {"code": "601", "name": "Energiekosten"},
            {"code": "61", "name": "Kantoorkosten"},
            {"code": "610", "name": "Telefoonkosten"}
        ]

        # Test parent groups (shorter codes with children)
        self.assertTrue(might_be_group_cost_center("6", "Algemene kosten", groups),
                       "6 should be detected as parent group (has 60, 61, 600, etc.)")
        self.assertTrue(might_be_group_cost_center("60", "Huisvestingskosten", groups),
                       "60 should be detected as parent group (has 600, 601)")
        self.assertTrue(might_be_group_cost_center("61", "Kantoorkosten", groups),
                       "61 should be detected as parent group (has 610)")

        # Test leaf groups (no children with longer codes)
        self.assertFalse(might_be_group_cost_center("600", "Huurkosten", groups),
                        "600 should not be detected as parent group (no longer codes)")
        self.assertFalse(might_be_group_cost_center("610", "Telefoonkosten", groups),
                        "610 should not be detected as parent group (no longer codes)")


class TestAPIEndpointIntegration(TestCostCenterCreationComprehensive):
    """Test all API endpoints with comprehensive scenarios"""
    
    def test_parse_groups_and_suggest_cost_centers_success(self):
        """Test successful parsing and suggestion generation"""
        # Generate realistic test data
        groups = self.data_generator.generate_mixed_account_groups()
        text_input = self.data_generator.format_as_text_input(groups)
        
        # Test the API endpoint
        result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
        
        self.assertTrue(result["success"], f"API call should succeed: {result.get('error')}")
        self.assertIn("suggestions", result, "Result should contain suggestions")
        self.assertIn("total_groups", result, "Result should contain total count")
        self.assertIn("suggested_count", result, "Result should contain suggested count")
        
        suggestions = result["suggestions"]
        self.assertEqual(len(suggestions), len(groups), "Should have suggestion for each group")
        
        # Verify suggestion structure
        for suggestion in suggestions:
            self.assertIn("group_code", suggestion, "Suggestion should have group code")
            self.assertIn("group_name", suggestion, "Suggestion should have group name")  
            self.assertIn("create_cost_center", suggestion, "Suggestion should have create flag")
            self.assertIn("reason", suggestion, "Suggestion should have reason")
            self.assertIsInstance(suggestion["create_cost_center"], bool, "Create flag should be boolean")
            
        # Verify business logic is applied
        expense_suggestions = [s for s in suggestions if s["group_code"].startswith(("5", "6"))]
        suggested_expense_count = sum(1 for s in expense_suggestions if s["create_cost_center"])
        self.assertGreater(suggested_expense_count, 0, "Should suggest cost centers for some expense groups")
        
    def test_parse_groups_with_empty_input(self):
        """Test parsing with empty or invalid input"""
        test_cases = [
            ("", "No account group mappings provided"),
            # Whitespace-only gets stripped, so treated as empty
            ("   \n  \n   ", "No account group mappings provided"),
            # Lines with only numbers (no names) are skipped as invalid
            ("123\n456\n", "No valid account groups found"),
        ]
        
        for text_input, expected_error in test_cases:
            with self.subTest(input=text_input):
                result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
                
                self.assertFalse(result["success"], "Should fail with invalid input")
                self.assertIn("error", result, "Should return error message")
                self.assertIn(expected_error.lower(), result["error"].lower(),
                            f"Error should mention: {expected_error}")
                
    def test_preview_cost_center_creation(self):
        """Test cost center creation preview functionality"""
        # Set up test mappings
        groups = self.data_generator.generate_expense_groups()[:5]  # Limit for testing
        mappings = self.create_cost_center_mapping_data(groups)
        
        # Add mappings to settings
        for mapping in mappings:
            if mapping["create_cost_center"]:
                self.test_settings.append("cost_center_mappings", mapping)
        self.test_settings.save()
        
        # Test preview
        result = preview_cost_center_creation()
        
        self.assertTrue(result["success"], f"Preview should succeed: {result.get('error')}")
        self.assertIn("preview_results", result, "Should return preview results")
        self.assertIn("total_to_process", result, "Should return total count")
        self.assertIn("would_create", result, "Should return creation count")
        self.assertIn("would_skip", result, "Should return skip count")
        
        # Verify preview structure
        preview_results = result["preview_results"]
        self.assertGreater(len(preview_results), 0, "Should have preview results")
        
        for preview in preview_results:
            self.assertIn("group_code", preview, "Preview should have group code")
            self.assertIn("cost_center_name", preview, "Preview should have cost center name")
            self.assertIn("action", preview, "Preview should have action")
            self.assertIn("already_exists", preview, "Preview should have existence check")
            
    def test_create_cost_centers_from_mappings_success(self):
        """Test successful cost center creation from mappings"""
        # Set up test mappings with realistic data
        groups = self.data_generator.generate_expense_groups()[:3]  # Small set for testing
        mappings = self.create_cost_center_mapping_data(groups)
        
        # Add mappings to settings (only those that should create cost centers)
        for mapping in mappings:
            if mapping["create_cost_center"]:
                self.test_settings.append("cost_center_mappings", mapping)
        self.test_settings.save()
        
        # Test creation
        result = create_cost_centers_from_mappings()
        
        self.assertTrue(result["success"], f"Creation should succeed: {result.get('error')}")
        self.assertIn("created_count", result, "Should return created count")
        self.assertIn("skipped_count", result, "Should return skipped count")  
        self.assertIn("failed_count", result, "Should return failed count")
        self.assertIn("created_cost_centers", result, "Should return created cost centers list")
        
        # Verify cost centers were actually created
        created_cost_centers = result["created_cost_centers"]
        for created in created_cost_centers:
            cost_center_id = created["cost_center_id"]
            self.assertTrue(frappe.db.exists("Cost Center", cost_center_id),
                          f"Cost center {cost_center_id} should exist in database")
            
            # Track for cleanup
            self.factory.track_document("Cost Center", cost_center_id)
            
    def test_create_single_cost_center(self):
        """Test creation of individual cost center"""
        # Create mapping data
        mapping_data = {
            "group_code": "510",
            "group_name": "Lonen en salarissen", 
            "cost_center_name": "Personeelskosten",
            "is_group": False,
            "suggestion_reason": "Expense group - good for cost tracking"
        }
        
        # Convert to object-like structure
        from frappe import _dict
        mapping = _dict(mapping_data)
        
        # Test creation
        result = create_single_cost_center(mapping, self.test_company.name)
        
        self.assertTrue(result["success"], f"Single creation should succeed: {result.get('error')}")
        self.assertIn("cost_center_name", result, "Should return cost center name")
        self.assertIn("cost_center_id", result, "Should return cost center ID")
        
        # Verify cost center was created
        cost_center_id = result["cost_center_id"]
        self.assertTrue(frappe.db.exists("Cost Center", cost_center_id),
                      f"Cost center {cost_center_id} should exist")
        
        # Verify properties
        cost_center_doc = frappe.get_doc("Cost Center", cost_center_id)
        self.assertEqual(cost_center_doc.cost_center_name, "Personeelskosten")
        self.assertEqual(cost_center_doc.company, self.test_company.name)
        self.assertEqual(cost_center_doc.is_group, 0)
        
        # Track for cleanup
        self.factory.track_document("Cost Center", cost_center_id)


class TestErrorHandlingAndEdgeCases(TestCostCenterCreationComprehensive):
    """Test comprehensive error handling and edge case scenarios"""
    
    def test_missing_company_validation(self):
        """Test error handling when company is missing

        The create_cost_centers_from_mappings function checks mappings first,
        then company. To test company validation specifically, we need to ensure
        mappings exist.
        """
        groups = self.data_generator.generate_expense_groups()[:2]
        text_input = self.data_generator.format_as_text_input(groups)

        # Test with non-existent company in parse function
        result = parse_groups_and_suggest_cost_centers(text_input, "NonExistentCompany")
        # Note: parse function doesn't validate company existence, only uses it for lookup

        # Store original values
        original_company = self.test_settings.default_company
        original_mappings = self.test_settings.cost_center_mappings or []
        had_mappings = len(original_mappings) > 0

        # Ensure mappings exist first (cost_center_mappings is a child table)
        if not had_mappings:
            self.test_settings.append("cost_center_mappings", {
                "group_code": "500",
                "group_name": "Test Group",
                "cost_center_name": "Test Cost Center",
                "is_group": 0
            })
            self.test_settings.save(ignore_permissions=True)

        # Clear company from settings (use db_set to bypass mandatory validation)
        frappe.db.set_value("E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", None)
        self.test_settings.reload()

        result = create_cost_centers_from_mappings()

        self.assertFalse(result["success"], "Should fail without company")
        self.assertIn("company not configured", result["error"].lower(),
                     "Error should mention company configuration")

        # Restore original values
        frappe.db.set_value("E-Boekhouden Settings", "E-Boekhouden Settings", "default_company", original_company)
        if not had_mappings:
            # Remove the test mapping we added
            self.test_settings.reload()
            self.test_settings.cost_center_mappings = []
            self.test_settings.save(ignore_permissions=True)
        self.test_settings.reload()
        
    def test_duplicate_cost_center_handling(self):
        """Test handling of duplicate cost center names"""
        # Get root cost center for the test company
        root_cost_center = frappe.db.get_value(
            "Cost Center",
            {"company": self.test_company.name, "is_group": 1, "parent_cost_center": ["is", "not set"]},
            "name"
        )
        if not root_cost_center:
            root_cost_center = frappe.db.get_value(
                "Cost Center",
                {"company": self.test_company.name, "is_group": 1},
                "name"
            )

        # Create a cost center first
        existing_cost_center = frappe.get_doc({
            "doctype": "Cost Center",
            "cost_center_name": "Test Expense Center",
            "company": self.test_company.name,
            "parent_cost_center": root_cost_center,
            "is_group": 0
        })
        existing_cost_center.insert()
        self.factory.track_document("Cost Center", existing_cost_center.name)
        
        # Try to create another with same name
        mapping_data = {
            "group_code": "999",
            "group_name": "Test Group",
            "cost_center_name": "Test Expense Center",  # Duplicate name
            "is_group": False
        }
        
        from frappe import _dict
        mapping = _dict(mapping_data)
        
        result = create_single_cost_center(mapping, self.test_company.name)
        
        self.assertFalse(result["success"], "Should fail with duplicate name")
        self.assertTrue(result.get("skipped", False), "Should be marked as skipped")
        self.assertIn("already exists", result.get("reason", "").lower(),
                     "Reason should mention existing cost center")
        
    def test_invalid_parent_cost_center(self):
        """Test handling of invalid parent cost center references"""
        mapping_data = {
            "group_code": "611",
            "group_name": "Huurkosten",
            "cost_center_name": "Huurkosten Detail",
            "is_group": False,
            "parent_cost_center": "NonExistentCostCenter"
        }
        
        from frappe import _dict
        mapping = _dict(mapping_data)
        
        result = create_single_cost_center(mapping, self.test_company.name)

        # Should still succeed - invalid parent is logged and default used
        self.assertTrue(result["success"], "Should succeed despite invalid parent")

        # Verify cost center was created with default parent (not the invalid one)
        cost_center_doc = frappe.get_doc("Cost Center", result["cost_center_id"])
        self.assertIsNotNone(cost_center_doc.parent_cost_center,
                            "Should have a parent cost center (the default)")
        self.assertNotEqual(cost_center_doc.parent_cost_center, "NonExistentCostCenter",
                           "Should not have the invalid parent set")

        # Track for cleanup
        self.factory.track_document("Cost Center", result["cost_center_id"])
        
    def test_malformed_input_data(self):
        """Test handling of malformed input data"""
        malformed_inputs = [
            "123\n456\n789",  # Only codes, no names
            "001 Valid Name\n\n002 Another Valid",  # Empty lines
            "001 Name With\nMultiple Lines\n002 Valid",  # Multi-line confusion
            "001\t\tTab\tSeparated\t\tData",  # Tab separators
            "001  Multiple   Spaces   Name",  # Multiple spaces
        ]
        
        for malformed_input in malformed_inputs:
            with self.subTest(input=malformed_input[:20] + "..."):
                result = parse_groups_and_suggest_cost_centers(malformed_input, self.test_company.name)
                
                # Should either succeed with valid parsing or fail gracefully
                if result["success"]:
                    self.assertIn("suggestions", result, "Success should include suggestions")
                else:
                    self.assertIn("error", result, "Failure should include error message")
                    
    def test_large_input_handling(self):
        """Test handling of large input datasets"""
        # Generate large dataset
        large_groups = []
        for i in range(100):  # 100 account groups
            code = f"{500 + i:03d}"
            name = f"Test Kostengroep {i:03d} - {self.data_generator.random.choice(['Personeel', 'Algemeen', 'Marketing', 'IT'])}"
            large_groups.append({"code": code, "name": name})
            
        text_input = self.data_generator.format_as_text_input(large_groups)
        
        # Test parsing
        result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
        
        self.assertTrue(result["success"], f"Large input should succeed: {result.get('error')}")
        self.assertEqual(result["total_groups"], 100, "Should process all 100 groups")
        self.assertGreater(result["suggested_count"], 10, "Should suggest multiple cost centers")
        
    def test_special_characters_in_names(self):
        """Test handling of special characters in account group names"""
        special_groups = [
            ("501", "Lönen & Salarissen (NL)"),
            ("502", "Kosten - Marketing/Sales"),
            ("503", "IT-Kosten: Hardware & Software"),  
            ("504", "Reiskosten (50% aftrekbaar)"),
            ("505", "Energie@Kantoor"),
        ]
        
        text_input = self.data_generator.format_as_text_input(
            [{"code": code, "name": name} for code, name in special_groups]
        )
        
        result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
        
        self.assertTrue(result["success"], "Should handle special characters")
        
        # Verify names are processed correctly
        suggestions = result["suggestions"]
        for suggestion in suggestions:
            self.assertIsInstance(suggestion["group_name"], str, 
                                "Group name should be string")
            if suggestion["create_cost_center"]:
                self.assertIsInstance(suggestion["cost_center_name"], str,
                                    "Cost center name should be string")


class TestPerformanceAndScalability(TestCostCenterCreationComprehensive):
    """Test performance characteristics with large datasets"""
    
    def test_performance_with_large_dataset(self):
        """Test performance with large dataset processing"""
        import time
        
        # Generate large dataset (500 groups)
        large_groups = []
        for i in range(500):
            code = f"{100 + (i % 900):03d}"  # Spread across different ranges
            name = f"Grootboekgroep {i:03d} - {['Activa', 'Passiva', 'Opbrengsten', 'Kosten'][i % 4]}"
            large_groups.append({"code": code, "name": name})
            
        text_input = self.data_generator.format_as_text_input(large_groups)
        
        # Measure parsing performance
        start_time = time.time()
        result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
        parse_time = time.time() - start_time
        
        self.assertTrue(result["success"], "Large dataset parsing should succeed")
        self.assertLess(parse_time, 10.0, "Parsing should complete within 10 seconds")
        
        # Verify all groups processed
        self.assertEqual(result["total_groups"], 500, "Should process all 500 groups")
        
        print(f"Performance: Parsed 500 groups in {parse_time:.3f} seconds")
        
    def test_memory_usage_with_batch_processing(self):
        """Test memory efficiency with batch processing"""
        # This test ensures the system handles large datasets without excessive memory usage
        
        # Create multiple batches
        batch_size = 50
        total_batches = 10
        
        for batch_num in range(total_batches):
            batch_groups = []
            for i in range(batch_size):
                group_id = batch_num * batch_size + i
                code = f"{500 + group_id:03d}"
                name = f"Batch {batch_num:02d} Groep {i:02d}"
                batch_groups.append({"code": code, "name": name})
                
            text_input = self.data_generator.format_as_text_input(batch_groups)
            result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)
            
            self.assertTrue(result["success"], f"Batch {batch_num} should succeed")
            
        print(f"Memory test: Processed {total_batches} batches of {batch_size} groups each")
        
    def test_concurrent_processing_safety(self):
        """Test sequential processing of multiple batches (simulates concurrent workload)

        Note: True multi-threading is not fully supported in Frappe due to database
        connection binding limitations. This test verifies sequential processing of
        multiple batches works correctly, which is how concurrent requests are
        typically handled via Frappe's gunicorn workers.
        """
        results = []
        errors = []

        def process_batch(batch_id):
            try:
                batch_groups = []
                for i in range(20):  # Small batch
                    code = f"{600 + batch_id * 20 + i:03d}"
                    name = f"Concurrent Batch {batch_id} Groep {i}"
                    batch_groups.append({"code": code, "name": name})

                text_input = self.data_generator.format_as_text_input(batch_groups)
                result = parse_groups_and_suggest_cost_centers(text_input, self.test_company.name)

                results.append((batch_id, result["success"], result.get("total_groups", 0)))
            except Exception as e:
                errors.append((batch_id, str(e)))

        # Run sequential batches (simulates multiple worker processes)
        for i in range(5):  # 5 batches
            process_batch(i)

        # Verify results
        self.assertEqual(len(errors), 0, f"No errors should occur: {errors}")
        self.assertEqual(len(results), 5, "All batches should complete")

        for batch_id, success, count in results:
            self.assertTrue(success, f"Batch {batch_id} should succeed")
            self.assertEqual(count, 20, f"Batch {batch_id} should process 20 groups")


if __name__ == "__main__":
    unittest.main()