"""
JavaScript API Integration Tests
Tests for common issues between JavaScript and Python API integration
"""

import os
import re
import json
import frappe
import unittest
from pathlib import Path
from unittest.mock import patch

class JavaScriptAPIIntegrationTestCase(unittest.TestCase):
    """Test JavaScript API integration for common issues"""
    
    def setUp(self):
        self.app_path = Path(frappe.get_app_path('verenigingen'))
        self.api_path = self.app_path / 'api'
        self.js_paths = [
            self.app_path / 'public' / 'js',
            self.app_path / 'verenigingen' / 'doctype',
            self.app_path / 'verenigingen' / 'report'
        ]
        
    def get_js_files(self):
        """Get JavaScript files from relevant directories only"""
        js_files = []
        for js_path in self.js_paths:
            if js_path.exists():
                js_files.extend(js_path.glob('**/*.js'))
        return js_files
    
    def test_boolean_parameter_handling(self):
        """Test that boolean parameters are handled correctly in API functions"""
        
        # Known functions that should use cint() for boolean parameters
        functions_to_check = [
            ('member_management.py', 'get_members_without_chapter'),
            ('payment_dashboard.py', 'get_payment_history'),
            ('suspension_api.py', 'bulk_suspend_members'),
            ('dd_batch_scheduler.py', 'toggle_auto_batch_creation'),
            ('anbi_operations.py', 'update_donor_consent'),
        ]
        
        for filename, function_name in functions_to_check:
            api_file = self.api_path / filename
            if api_file.exists():
                with open(api_file, 'r') as f:
                    content = f.read()
                    
                # Check if function exists
                if f'def {function_name}' in content:
                    # Look for dangerous int() usage
                    function_match = re.search(
                        rf'def {function_name}\s*\([^)]*\):(.*?)(?=\ndef|\Z)', 
                        content, 
                        re.DOTALL
                    )
                    
                    if function_match:
                        func_content = function_match.group(1)
                        
                        # Check for int() usage with variables (not literals)
                        int_usage = re.findall(r'int\s*\(\s*([a-zA-Z_][a-zA-Z0-9_.*\[\]]*)\s*\)', func_content)
                        if int_usage:
                            # Check if cbool is used instead
                            for var in int_usage:
                                if 'cbool' not in func_content and 'frappe.utils.cint' not in func_content:
                                    self.fail(
                                        f"Function {function_name} in {filename} uses int({var}) "
                                        f"which may fail with boolean strings. Use cbool() instead."
                                    )
    
    def test_api_function_whitelist(self):
        """Test that API functions called from JavaScript are properly whitelisted"""
        
        # Known API calls that should be whitelisted
        critical_api_calls = [
            ('membership_application.py', 'submit_application'),
            ('member_management.py', 'assign_member_to_chapter'),
            ('payment_processing.py', 'send_overdue_payment_reminders'),
            ('payment_processing.py', 'export_overdue_payments'),
            ('payment_processing.py', 'execute_bulk_payment_action'),
        ]
        
        for filename, function_name in critical_api_calls:
            api_file = self.api_path / filename
            if api_file.exists():
                with open(api_file, 'r') as f:
                    content = f.read()
                    
                # Check if function exists
                if f'def {function_name}' in content:
                    # Check if it's whitelisted
                    whitelist_pattern = rf'@frappe\.whitelist\([^)]*\)\s*def {function_name}\s*\('
                    if not re.search(whitelist_pattern, content):
                        self.fail(
                            f"Function {function_name} in {filename} is not whitelisted with "
                            f"@frappe.whitelist() but may be called from JavaScript"
                        )
    
    def test_member_doctype_boolean_conversions(self):
        """Test specific boolean conversions in member doctype that were causing issues"""
        
        member_file = self.app_path / 'verenigingen' / 'doctype' / 'member' / 'member.py'
        if member_file.exists():
            with open(member_file, 'r') as f:
                content = f.read()
                
            # Test that specific boolean conversions use cint()
            critical_conversions = [
                'used_for_memberships',
                'used_for_donations', 
                'send_welcome_email'
            ]
            
            for param in critical_conversions:
                # Should use frappe.utils.cint() not int()
                if f'int({param})' in content:
                    self.fail(
                        f"Member doctype uses int({param}) which fails with boolean strings. "
                        f"Should use frappe.utils.cint({param}) instead."
                    )
                    
                # Should have the proper conversion
                if param in content and f'cbool({param})' not in content:
                    # Only fail if the parameter is actually used in assignments
                    if f'{param} =' in content or f'.{param} =' in content:
                        self.fail(
                            f"Member doctype should use cbool({param}) for boolean conversion"
                        )
    
    def test_api_method_existence(self):
        """Test that API methods referenced in JavaScript actually exist"""
        
        # Test some critical API endpoints
        test_cases = [
            ('verenigingen.api.membership_application.submit_application', 'submit_application'),
            ('verenigingen.api.member_management.get_members_without_chapter', 'get_members_without_chapter'),
            ('verenigingen.api.payment_dashboard.get_payment_history', 'get_payment_history'),
            ('verenigingen.api.suspension_api.bulk_suspend_members', 'bulk_suspend_members'),
        ]
        
        for method_path, function_name in test_cases:
            try:
                # Try to get the method
                method = frappe.get_attr(method_path)
                self.assertIsNotNone(method, f"Method {method_path} should exist")
                
                # Check if it's callable
                self.assertTrue(callable(method), f"Method {method_path} should be callable")
                
            except AttributeError:
                self.fail(f"Method {method_path} not found - check if function exists and is whitelisted")
    
    def test_javascript_frappe_call_syntax(self):
        """Test JavaScript frappe.call syntax for common issues"""
        
        js_files = self.get_js_files()
        
        for js_file in js_files:
            try:
                with open(js_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Look for frappe.call with boolean parameters
                frappe_calls = re.findall(r'frappe\.call\s*\(\s*\{([^}]+)\}\s*\)', content, re.DOTALL)
                
                for call in frappe_calls:
                    # Check for common boolean parameter patterns
                    boolean_params = [
                        'send_welcome_email', 'used_for_memberships', 'used_for_donations',
                        'suspend_user', 'suspend_teams', 'enabled', 'disabled'
                    ]
                    
                    for param in boolean_params:
                        if param in call:
                            # Check if it's being set to true/false (which will be sent as strings)
                            if re.search(rf'{param}\s*:\s*(true|false)', call):
                                # This is OK - just document that the Python side should handle it
                                pass
                            
                            # Check for problematic patterns
                            if re.search(rf'{param}\s*:\s*"true"|{param}\s*:\s*"false"', call):
                                self.fail(
                                    f"File {js_file} has {param} set to string boolean in frappe.call. "
                                    f"Use boolean true/false instead of string \"true\"/\"false\""
                                )
                                
            except Exception as e:
                # Skip files that can't be read (like binary files)
                continue
    
    def test_critical_api_endpoints(self):
        """Test that critical API endpoints are working correctly"""
        
        # Test endpoints that are known to handle boolean parameters
        test_endpoints = [
            {
                'method': 'verenigingen.api.member_management.get_members_without_chapter',
                'args': {'limit': 10, 'offset': 0},
                'expected_type': list
            },
            {
                'method': 'verenigingen.api.payment_dashboard.get_dashboard_data',
                'args': {},
                'expected_type': dict
            }
        ]
        
        for endpoint in test_endpoints:
            try:
                # Try to call the method
                result = frappe.get_attr(endpoint['method'])(**endpoint['args'])
                
                # Check that it returns the expected type
                self.assertIsInstance(
                    result, 
                    endpoint['expected_type'],
                    f"Method {endpoint['method']} should return {endpoint['expected_type'].__name__}"
                )
                
            except Exception as e:
                self.fail(f"Method {endpoint['method']} failed: {str(e)}")
    
    def test_boolean_string_conversion(self):
        """Test that the cbool() function properly handles boolean strings"""
        
        from verenigingen.utils.boolean_utils import cbool
        
        # Test cases that were causing the original issue
        test_cases = [
            ('true', 1),
            ('false', 0),
            (True, 1),
            (False, 0),
            ('1', 1),
            ('0', 0),
            (1, 1),
            (0, 0),
            (None, 0),
            ('', 0),
        ]
        
        for input_val, expected in test_cases:
            result = cbool(input_val)
            self.assertEqual(
                result, 
                expected,
                f"cbool({repr(input_val)}) should return {expected}, got {result}"
            )

class JavaScriptAPIIntegrationRunner:
    """Runner for JavaScript API integration tests"""
    
    def run_all_tests(self):
        """Run all JavaScript API integration tests"""
        
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add all test methods
        test_methods = [
            'test_boolean_parameter_handling',
            'test_api_function_whitelist',
            'test_member_doctype_boolean_conversions',
            'test_api_method_existence',
            'test_javascript_frappe_call_syntax',
            'test_critical_api_endpoints',
            'test_boolean_string_conversion'
        ]
        
        for method in test_methods:
            suite.addTest(JavaScriptAPIIntegrationTestCase(method))
        
        # Run tests
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        return result.wasSuccessful()

def run_js_api_integration_tests():
    """Entry point for running JavaScript API integration tests"""
    runner = JavaScriptAPIIntegrationRunner()
    return runner.run_all_tests()

if __name__ == '__main__':
    # Run as standalone script
    success = run_js_api_integration_tests()
    exit(0 if success else 1)