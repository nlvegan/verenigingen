#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced Cost Center Test Data Factory
=====================================

Specialized test data factory for Cost Center Creation testing with realistic
Dutch accounting data patterns, business rule validation, and comprehensive
scenario generation.

This factory extends the Enhanced Test Factory with specific capabilities for:
- Dutch RGS (Referentie Grootboekschema) account group generation
- Cost center mapping scenarios
- eBoekhouden settings configuration
- Company and currency setup
- Hierarchical cost center structures
- Error scenario generation

Key Features:
- Realistic Dutch accounting terminology
- RGS-compliant account group codes and structures
- Business rule validation for cost center suggestions
- Deterministic data generation for reproducible tests
- Comprehensive error scenario coverage
- Performance testing data sets
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

import frappe
from frappe.utils import now_datetime, getdate, random_string, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory


class CostCenterTestDataFactory(EnhancedTestDataFactory):
    """
    Enhanced test data factory specialized for Cost Center Creation testing
    
    Provides realistic Dutch accounting data patterns and comprehensive
    scenario generation for testing cost center creation functionality.
    """
    
    def __init__(self, seed: int = 12345, use_faker: bool = True):
        super().__init__(seed=seed, use_faker=use_faker)
        
        # Initialize Dutch accounting data patterns
        self._init_dutch_accounting_patterns()
        
    def _init_dutch_accounting_patterns(self):
        """Initialize Dutch accounting terminology and patterns"""
        
        # Common Dutch accounting terms by category
        self.dutch_terms = {
            "assets": [
                "Vaste activa", "Materiële vaste activa", "Immateriële vaste activa",
                "Financiële vaste activa", "Bedrijfsgebouwen", "Machines", "Inventaris",
                "Voorraden", "Debiteuren", "Liquide middelen", "Kas", "Bank"
            ],
            "liabilities": [
                "Eigen vermogen", "Vreemd vermogen", "Voorzieningen", "Langlopende schulden",
                "Kortlopende schulden", "Crediteuren", "Belastingschuld", "Sociale lasten"
            ],
            "revenue": [
                "Opbrengsten", "Netto-omzet", "Verkopen", "Dienstverlening", "Subsidies",
                "Donaties", "Giften", "Financiële baten", "Overige opbrengsten"
            ],
            "expenses": [
                "Personeelskosten", "Lonen", "Salarissen", "Sociale lasten", "Pensioenen",
                "Huisvestingskosten", "Huur", "Energie", "Kantoorkosten", "Telefoon",
                "Porto", "Vervoerskosten", "Reiskosten", "Advertentie", "Marketing",
                "Afschrijvingen", "Rente", "Overige kosten"
            ],
            "departments": [
                "Afdeling", "Departement", "Team", "Sector", "Dienst", "Bureau",
                "Centrale", "Unit", "Groep", "Divisie"
            ]
        }
        
        # RGS account code ranges
        self.rgs_ranges = {
            "fixed_assets": (100, 199),
            "current_assets": (200, 299), 
            "revenue": (300, 399),
            "other_income": (400, 499),
            "personnel_costs": (500, 599),
            "general_costs": (600, 699),
            "financial_costs": (700, 799),
            "other_costs": (800, 899)
        }
        
    def generate_rgs_account_group(self, category: str, sequence: int = None) -> Dict[str, Any]:
        """Generate RGS-compliant account group"""
        if sequence is None:
            sequence = self.get_next_sequence(f'rgs_{category}')
            
        if category not in self.rgs_ranges:
            raise ValueError(f"Unknown RGS category: {category}")
            
        start_code, end_code = self.rgs_ranges[category]
        code = f"{start_code + (sequence % (end_code - start_code)):03d}"
        
        # Generate realistic name based on category
        if category in ["fixed_assets", "current_assets"]:
            term_category = "assets"
        elif category == "revenue":
            term_category = "revenue"
        elif "costs" in category:
            term_category = "expenses"
        else:
            term_category = "expenses"  # Default
            
        base_terms = self.dutch_terms[term_category]
        name = self.random.choice(base_terms)
        
        # Add specificity for subcategories
        if sequence > 0 and self.random.choice([True, False]):
            if term_category == "expenses":
                specifics = ["kantoor", "verkoop", "productie", "onderhoud", "ontwikkeling"]
                name += f" {self.random.choice(specifics)}"
            elif term_category == "revenue":
                specifics = ["binnenland", "buitenland", "online", "retail", "wholesale"]
                name += f" {self.random.choice(specifics)}"
                
        return {
            "code": code,
            "name": name,
            "category": category,
            "rgs_compliant": True
        }
        
    def generate_hierarchical_account_groups(self, parent_category: str, 
                                           child_count: int = 5) -> List[Dict[str, Any]]:
        """Generate hierarchical account group structure"""
        groups = []
        
        # Generate parent group
        parent = self.generate_rgs_account_group(parent_category, 0)
        parent["is_parent"] = True
        groups.append(parent)
        
        # Generate child groups
        parent_code = int(parent["code"])
        for i in range(1, child_count + 1):
            child_code = f"{parent_code + i:03d}"
            child_name = f"{parent['name']} - {self.random.choice(['Type A', 'Type B', 'Speciaal', 'Overig'])}"
            
            child = {
                "code": child_code,
                "name": child_name,
                "category": parent_category,
                "parent_code": parent["code"],
                "is_child": True,
                "rgs_compliant": True
            }
            groups.append(child)
            
        return groups
        
    def generate_cost_center_mapping_scenario(self, scenario_type: str) -> Dict[str, Any]:
        """Generate specific cost center mapping scenarios for testing"""
        
        scenarios = {
            "happy_path": self._generate_happy_path_scenario,
            "mixed_suggestions": self._generate_mixed_suggestions_scenario,
            "hierarchical": self._generate_hierarchical_scenario,
            "large_dataset": self._generate_large_dataset_scenario,
            "edge_cases": self._generate_edge_cases_scenario,
            "error_prone": self._generate_error_prone_scenario
        }
        
        if scenario_type not in scenarios:
            raise ValueError(f"Unknown scenario type: {scenario_type}")
            
        return scenarios[scenario_type]()
        
    def _generate_happy_path_scenario(self) -> Dict[str, Any]:
        """Generate ideal happy path scenario"""
        groups = []
        
        # Include expense groups that should be suggested
        expense_groups = [
            self.generate_rgs_account_group("personnel_costs", i)
            for i in range(3)
        ]
        expense_groups.extend([
            self.generate_rgs_account_group("general_costs", i)
            for i in range(4)
        ])
        
        # Include revenue groups  
        revenue_groups = [
            self.generate_rgs_account_group("revenue", i)
            for i in range(2)
        ]
        
        groups.extend(expense_groups)
        groups.extend(revenue_groups)
        
        return {
            "scenario_type": "happy_path",
            "groups": groups,
            "expected_suggestions": len(expense_groups) + len(revenue_groups),  # All should be suggested
            "expected_created": len(expense_groups) + len(revenue_groups),
            "expected_failures": 0,
            "description": "Ideal scenario with only expense and revenue groups"
        }
        
    def _generate_mixed_suggestions_scenario(self) -> Dict[str, Any]:
        """Generate scenario with mixed suggestion outcomes"""
        groups = []
        
        # Add groups that should be suggested
        suggested_groups = [
            self.generate_rgs_account_group("personnel_costs", 0),
            self.generate_rgs_account_group("general_costs", 0),
            self.generate_rgs_account_group("revenue", 0)
        ]
        
        # Add groups that should NOT be suggested
        not_suggested_groups = [
            self.generate_rgs_account_group("fixed_assets", 0),
            self.generate_rgs_account_group("current_assets", 0),
        ]
        
        groups.extend(suggested_groups)
        groups.extend(not_suggested_groups)
        
        return {
            "scenario_type": "mixed_suggestions",
            "groups": groups,
            "expected_suggestions": len(suggested_groups),
            "expected_created": len(suggested_groups),
            "expected_failures": 0,
            "description": "Mixed groups with different suggestion outcomes"
        }
        
    def _generate_hierarchical_scenario(self) -> Dict[str, Any]:
        """Generate hierarchical cost center scenario"""
        groups = []
        
        # Generate hierarchical expense groups
        hierarchical_groups = self.generate_hierarchical_account_groups("general_costs", 4)
        groups.extend(hierarchical_groups)
        
        return {
            "scenario_type": "hierarchical",
            "groups": groups,
            "expected_suggestions": len(hierarchical_groups),  # All should be suggested
            "expected_created": len(hierarchical_groups),
            "expected_failures": 0,
            "has_hierarchy": True,
            "description": "Hierarchical parent-child cost center structure"
        }
        
    def _generate_large_dataset_scenario(self) -> Dict[str, Any]:
        """Generate large dataset for performance testing"""
        groups = []
        
        # Generate large number of groups across categories
        for category in ["personnel_costs", "general_costs", "revenue"]:
            category_groups = [
                self.generate_rgs_account_group(category, i)
                for i in range(50)  # 50 groups per category
            ]
            groups.extend(category_groups)
            
        return {
            "scenario_type": "large_dataset", 
            "groups": groups,
            "expected_suggestions": len(groups),  # All expense/revenue should be suggested
            "expected_created": len(groups),
            "expected_failures": 0,
            "is_performance_test": True,
            "description": f"Large dataset with {len(groups)} groups for performance testing"
        }
        
    def _generate_edge_cases_scenario(self) -> Dict[str, Any]:
        """Generate edge cases and boundary conditions"""
        groups = []
        
        # Edge cases
        edge_cases = [
            {"code": "999", "name": "Zeer Lange Naam Voor Een Kostengroep Die Mogelijk Problemen Veroorzaakt"},
            {"code": "001", "name": "A"},  # Very short name
            {"code": "500", "name": "Personeel & Kosten (50%)"},  # Special characters
            {"code": "600", "name": "Kosten - IT/Marketing"},  # Slashes and dashes
            {"code": "700", "name": "Müller & Søn BV"},  # Unicode characters
        ]
        
        for case in edge_cases:
            case["category"] = "edge_case"
            case["rgs_compliant"] = False
            
        groups.extend(edge_cases)
        
        return {
            "scenario_type": "edge_cases",
            "groups": groups,
            "expected_suggestions": len([g for g in groups if g["code"].startswith(("5", "6", "7"))]),
            "expected_created": len([g for g in groups if g["code"].startswith(("5", "6", "7"))]),
            "expected_failures": 0,
            "has_special_characters": True,
            "description": "Edge cases with special characters and boundary conditions"
        }
        
    def _generate_error_prone_scenario(self) -> Dict[str, Any]:
        """Generate scenario likely to cause errors"""
        groups = []
        
        # Problematic groups
        error_prone_groups = [
            {"code": "500", "name": "Duplicate Name Test"},
            {"code": "501", "name": "Duplicate Name Test"},  # Same name, different code
            {"code": "", "name": "Empty Code Test"},  # Invalid code
            {"code": "502", "name": ""},  # Invalid name
            {"code": "INVALID", "name": "Invalid Code Format"},  # Non-numeric code
        ]
        
        for group in error_prone_groups:
            group["category"] = "error_prone"
            group["rgs_compliant"] = False
            
        groups.extend(error_prone_groups)
        
        return {
            "scenario_type": "error_prone",
            "groups": groups,
            "expected_suggestions": 2,  # Only valid groups with 500-series codes
            "expected_created": 1,  # Only one due to duplicate names
            "expected_failures": 1,  # Duplicate name failure
            "has_errors": True,
            "description": "Error-prone scenario with duplicates and invalid data"
        }
        
    def create_test_eboekhouden_settings(self, company_name: str = None, 
                                       with_mappings: bool = False,
                                       mapping_scenario: str = None) -> frappe._dict:
        """Create test eBoekhouden settings document"""
        
        if not company_name:
            # Create test company
            company = self.create_test_company()
            company_name = company.name
            
        # Get or create settings
        settings_doc = frappe.get_single("E-Boekhouden Settings")
        
        # Configure with test values
        settings_doc.api_url = "https://api.test.e-boekhouden.nl"
        settings_doc.api_token = f"TEST_TOKEN_{self.test_run_id}"
        settings_doc.source_application = "TestVerenigingenERPNext"
        settings_doc.default_company = company_name
        settings_doc.default_currency = "EUR"
        settings_doc.fiscal_year_start_month = "1"
        
        # Clear existing mappings
        settings_doc.cost_center_mappings = []
        
        if with_mappings and mapping_scenario:
            scenario_data = self.generate_cost_center_mapping_scenario(mapping_scenario)
            self._add_mappings_to_settings(settings_doc, scenario_data)
            
        settings_doc.save()
        return settings_doc
        
    def _add_mappings_to_settings(self, settings_doc, scenario_data):
        """Add cost center mappings to settings based on scenario"""
        groups = scenario_data["groups"]
        
        for group in groups:
            # Determine if should create cost center based on RGS rules
            should_create, reason = self._should_suggest_cost_center_rgs(group["code"], group["name"])
            
            mapping = {
                "group_code": group["code"],
                "group_name": group["name"],
                "create_cost_center": should_create,
                "cost_center_name": self._clean_cost_center_name(group["name"]) if should_create else "",
                "suggestion_reason": reason,
                "is_group": group.get("is_parent", False),
                "account_count": self.random.randint(1, 20)
            }
            
            if group.get("parent_code"):
                # Find parent cost center if exists
                parent_mapping = next((m for m in settings_doc.cost_center_mappings 
                                     if m.group_code == group["parent_code"]), None)
                if parent_mapping and parent_mapping.create_cost_center:
                    mapping["parent_cost_center"] = parent_mapping.cost_center_name
                    
            settings_doc.append("cost_center_mappings", mapping)
            
    def _should_suggest_cost_center_rgs(self, code: str, name: str) -> Tuple[bool, str]:
        """RGS-based cost center suggestion logic"""
        name_lower = name.lower()
        
        # Expense groups are prime candidates  
        if code.startswith(('5', '6', '7')):
            if any(keyword in name_lower for keyword in ['personeel', 'kosten', 'uitgaven', 'lasten']):
                return True, "Expense group - good for cost tracking"
                
        # Revenue groups for departmental analysis
        if code.startswith('3'):
            if any(keyword in name_lower for keyword in ['opbrengst', 'omzet', 'verkoop']):
                return True, "Revenue group - useful for departmental income tracking"
                
        # Departmental indicators
        if any(keyword in name_lower for keyword in ['afdeling', 'team', 'departement']):
            return True, "Contains departmental keywords"
            
        # Balance sheet items usually don't need cost centers
        if code.startswith(('1', '2')):
            return False, "Balance sheet item - cost center not needed"
            
        return False, "Not suitable for cost center tracking"
        
    def _clean_cost_center_name(self, name: str) -> str:
        """Clean cost center name"""
        cleaned = name.strip()
        
        # Remove common accounting terms
        remove_terms = ['rekeningen', 'grootboek', 'accounts', 'groep']
        for term in remove_terms:
            cleaned = cleaned.replace(term, '').strip()
            
        # Capitalize first letter
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
            
        return cleaned
        
    def create_test_company(self, **kwargs) -> frappe._dict:
        """Create test company for cost center testing"""
        seq = self.get_next_sequence('company')
        
        defaults = {
            "company_name": f"TEST Company {seq} - {self.test_run_id[:8]}",
            "abbr": f"TC{seq:02d}",
            "default_currency": "EUR", 
            "country": "Netherlands"
        }
        
        data = {**defaults, **kwargs}
        
        # Check if company already exists
        if frappe.db.exists("Company", data["company_name"]):
            return frappe.get_doc("Company", data["company_name"])
            
        company_doc = frappe.get_doc({
            "doctype": "Company",
            **data
        })
        
        company_doc.insert()
        return company_doc
        
    def create_test_cost_center(self, company_name: str, **kwargs) -> frappe._dict:
        """Create test cost center with validation"""
        seq = self.get_next_sequence('cost_center')
        
        defaults = {
            "cost_center_name": f"TEST Cost Center {seq}",
            "company": company_name,
            "is_group": 0
        }
        
        data = {**defaults, **kwargs}
        
        # Check if cost center already exists
        existing = frappe.db.get_value(
            "Cost Center",
            {"cost_center_name": data["cost_center_name"], "company": company_name},
            "name"
        )
        
        if existing:
            return frappe.get_doc("Cost Center", existing)
            
        cost_center_doc = frappe.get_doc({
            "doctype": "Cost Center",
            **data
        })
        
        cost_center_doc.insert()
        return cost_center_doc
        
    def format_groups_as_text_input(self, groups: List[Dict[str, Any]]) -> str:
        """Format account groups as text input for API testing"""
        lines = []
        for group in groups:
            lines.append(f"{group['code']} {group['name']}")
        return "\n".join(lines)
        
    def generate_test_scenarios_suite(self) -> Dict[str, Dict[str, Any]]:
        """Generate complete suite of test scenarios"""
        scenarios = {}
        
        scenario_types = [
            "happy_path", "mixed_suggestions", "hierarchical", 
            "large_dataset", "edge_cases", "error_prone"
        ]
        
        for scenario_type in scenario_types:
            scenarios[scenario_type] = self.generate_cost_center_mapping_scenario(scenario_type)
            
        return scenarios
        
    def validate_cost_center_creation_result(self, result: Dict[str, Any], 
                                           expected_scenario: Dict[str, Any]) -> Dict[str, bool]:
        """Validate cost center creation results against expected scenario"""
        validations = {}
        
        # Basic success validation
        validations["success"] = result.get("success", False)
        
        # Count validations (allow some tolerance for business rule variations)
        if "expected_created" in expected_scenario:
            created_count = result.get("created_count", 0)
            expected_created = expected_scenario["expected_created"]
            # Allow 20% tolerance for suggestion variations
            tolerance = max(1, int(expected_created * 0.2))
            validations["created_count_ok"] = abs(created_count - expected_created) <= tolerance
            
        if "expected_failures" in expected_scenario:
            failed_count = result.get("failed_count", 0) 
            expected_failures = expected_scenario["expected_failures"]
            validations["failed_count_ok"] = failed_count == expected_failures
            
        # Structure validation
        required_keys = ["created_count", "skipped_count", "failed_count"]
        validations["has_required_keys"] = all(key in result for key in required_keys)
        
        return validations


# Convenience functions for test usage
def create_cost_center_test_factory(seed=12345, use_faker=True):
    """Create cost center test factory instance"""
    return CostCenterTestDataFactory(seed=seed, use_faker=use_faker)


def generate_dutch_accounting_test_data(scenario_type="mixed_suggestions", seed=12345):
    """Generate Dutch accounting test data for specified scenario"""
    factory = CostCenterTestDataFactory(seed=seed)
    return factory.generate_cost_center_mapping_scenario(scenario_type)


if __name__ == "__main__":
    # Example usage and testing
    print("Testing CostCenterTestDataFactory...")
    
    try:
        factory = CostCenterTestDataFactory(seed=12345, use_faker=False)
        
        # Test RGS account group generation
        print("\\n=== Testing RGS Account Group Generation ===")
        expense_group = factory.generate_rgs_account_group("personnel_costs", 0)
        print(f"Generated expense group: {expense_group}")
        
        revenue_group = factory.generate_rgs_account_group("revenue", 0) 
        print(f"Generated revenue group: {revenue_group}")
        
        # Test hierarchical groups
        print("\\n=== Testing Hierarchical Groups ===")
        hierarchical = factory.generate_hierarchical_account_groups("general_costs", 3)
        for group in hierarchical:
            print(f"  {group['code']}: {group['name']} (Parent: {group.get('is_parent', False)})")
            
        # Test scenario generation
        print("\\n=== Testing Scenario Generation ===")
        scenarios = ["happy_path", "mixed_suggestions", "hierarchical"]
        for scenario_type in scenarios:
            scenario = factory.generate_cost_center_mapping_scenario(scenario_type)
            print(f"{scenario_type}: {len(scenario['groups'])} groups, "
                  f"expect {scenario['expected_suggestions']} suggestions")
                  
        print("\\n✅ CostCenterTestDataFactory testing completed successfully")
        
    except Exception as e:
        print(f"❌ CostCenterTestDataFactory testing failed: {e}")
        raise