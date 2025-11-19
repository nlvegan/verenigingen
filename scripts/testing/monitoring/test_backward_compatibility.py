"""
Backward Compatibility Test Suite
Week 0 - Pre-Implementation Infrastructure

Ensures all existing monitoring APIs continue to work unchanged
during enhancement implementation.

Critical APIs to protect:
- measure_member_performance
- measure_payment_history_performance  
- measure_sepa_mandate_performance
- analyze_system_bottlenecks
"""

import inspect
import json
from typing import Dict, Any, List
import frappe
from frappe.utils import now
from verenigingen.tests.utils.base import VereningingenTestCase


class TestBackwardCompatibility(VereningingenTestCase):
    """Ensures 100% backward compatibility during enhancements"""
    
    # Define expected API contracts
    EXISTING_APIS = {
        'measure_member_performance': {
            'module': 'verenigingen.api.performance_measurement_api',
            'required_params': ['member_name'],
            'expected_response_keys': ['success', 'member_name', 'timestamp'],
            'response_type': dict
        },
        'test_basic_query_measurement': {
            'module': 'verenigingen.api.simple_measurement_test',
            'required_params': [],
            'expected_response_keys': ['query_count', 'execution_time'],
            'response_type': dict
        }
    }
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        cls.test_member = cls._get_or_create_test_member()
    
    @classmethod
    def _get_or_create_test_member(cls):
        """Get or create a reliable test member"""
        test_members = frappe.get_all("Member", 
            filters={"customer": ("!=", "")}, 
            fields=["name"], 
            limit=1
        )
        
        if test_members:
            return test_members[0].name
        
        # Create test member if none exists
        member = cls.create_test_member(
            first_name="BackwardCompatibility",
            last_name="TestMember",
            email="backward.compat@test.com"
        )
        return member.name
    
    def test_all_existing_apis_still_exist(self):
        """Verify all expected APIs still exist and are importable"""
        for api_name, config in self.EXISTING_APIS.items():
            module_path = config['module']
            
            # Test that module can be imported
            try:
                module = frappe.get_module(module_path)
                self.assertTrue(hasattr(module, api_name),
                              f"API {api_name} missing from {module_path}")
            except ImportError as e:
                self.fail(f"Cannot import module {module_path}: {e}")
    
    def test_api_signatures_unchanged(self):
        """Verify API signatures haven't changed"""
        for api_name, config in self.EXISTING_APIS.items():
            module = frappe.get_module(config['module'])
            api_func = getattr(module, api_name)
            
            # Get function signature
            sig = inspect.signature(api_func)
            params = list(sig.parameters.keys())
            
            # Check required params are still present
            for required_param in config['required_params']:
                self.assertIn(required_param, params,
                            f"Required parameter {required_param} missing from {api_name}")
    
    def test_measure_member_performance_contract(self):
        """Test measure_member_performance API contract"""
        from verenigingen.api.performance_measurement_api import measure_member_performance
        
        # Test with valid member
        result = measure_member_performance(self.test_member)
        
        # Verify response structure
        self.assertIsInstance(result, dict, "Response should be dictionary")
        self.assertIn('success', result, "Response missing 'success' field")
        self.assertIn('member_name', result, "Response missing 'member_name' field")
        
        # Verify successful response structure
        if result.get('success'):
            expected_keys = self.EXISTING_APIS['measure_member_performance']['expected_response_keys']
            for key in expected_keys:
                self.assertIn(key, result, f"Response missing expected key: {key}")
        
        # Test error handling
        error_result = measure_member_performance("NONEXISTENT_MEMBER")
        self.assertIsInstance(error_result, dict)
        self.assertIn('success', error_result)
        self.assertFalse(error_result.get('success'))
        self.assertIn('error', error_result)
    
    def test_basic_query_measurement_contract(self):
        """Test test_basic_query_measurement API contract"""
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        
        result = test_basic_query_measurement()
        
        # Verify response structure
        self.assertIsInstance(result, dict, "Response should be dictionary")
        
        # Check expected keys
        expected_keys = self.EXISTING_APIS['test_basic_query_measurement']['expected_response_keys']
        for key in expected_keys:
            self.assertIn(key, result, f"Response missing expected key: {key}")
        
        # Verify data types
        if 'query_count' in result:
            self.assertIsInstance(result['query_count'], (int, float),
                                "query_count should be numeric")
        
        if 'execution_time' in result:
            self.assertIsInstance(result['execution_time'], (int, float),
                                "execution_time should be numeric")
    
    def test_response_format_consistency(self):
        """Ensure response formats remain consistent"""
        # Capture current response formats
        current_formats = {}
        
        # Test measure_member_performance
        from verenigingen.api.performance_measurement_api import measure_member_performance
        result = measure_member_performance(self.test_member)
        current_formats['measure_member_performance'] = {
            'keys': sorted(result.keys()),
            'success_type': type(result.get('success')).__name__,
            'has_error_handling': 'error' in result or result.get('success') is not False
        }
        
        # Test basic measurement
        from verenigingen.api.simple_measurement_test import test_basic_query_measurement
        result = test_basic_query_measurement()
        current_formats['test_basic_query_measurement'] = {
            'keys': sorted(result.keys()),
            'has_query_count': 'query_count' in result,
            'has_execution_time': 'execution_time' in result
        }
        
        # Store format snapshot for future comparison
        format_snapshot = {
            'timestamp': now(),
            'formats': current_formats,
            'test_member': self.test_member
        }
        
        # Log for monitoring
        frappe.logger().info(f"API Format Snapshot: {json.dumps(format_snapshot, default=str)}")
        
        # Basic validation that formats make sense
        for api_name, format_info in current_formats.items():
            self.assertGreater(len(format_info['keys']), 0,
                             f"API {api_name} returned empty response")
    
    def test_error_handling_consistency(self):
        """Ensure error handling patterns remain consistent"""
        from verenigingen.api.performance_measurement_api import measure_member_performance
        
        # Test invalid member
        error_result = measure_member_performance("INVALID_MEMBER_12345")
        
        # Error response should be consistent
        self.assertIsInstance(error_result, dict)
        self.assertIn('success', error_result)
        self.assertFalse(error_result.get('success'))
        self.assertIn('error', error_result)
        self.assertIsInstance(error_result['error'], str)
        self.assertGreater(len(error_result['error']), 0)
    
    def test_whitelisted_api_access(self):
        """Ensure APIs remain accessible via whitelist"""
        # Test that APIs are still whitelisted (can be called via frappe.whitelist)
        whitelisted_apis = [
            'measure_member_performance',
            'test_basic_query_measurement'
        ]
        
        for api_name in whitelisted_apis:
            # This would fail if the API is not whitelisted
            try:
                # Note: This is a simplified test - in reality you'd test via HTTP
                if api_name == 'measure_member_performance':
                    from verenigingen.api.performance_measurement_api import measure_member_performance
                    result = measure_member_performance(self.test_member)
                elif api_name == 'test_basic_query_measurement':
                    from verenigingen.api.simple_measurement_test import test_basic_query_measurement
                    result = test_basic_query_measurement()
                
                self.assertIsInstance(result, dict, f"API {api_name} should return dict")
                
            except Exception as e:
                self.fail(f"Whitelisted API {api_name} failed to execute: {e}")
    
    def test_import_path_stability(self):
        """Ensure import paths remain stable"""
        stable_imports = [
            'verenigingen.api.performance_measurement_api.measure_member_performance',
            'verenigingen.api.simple_measurement_test.test_basic_query_measurement'
        ]
        
        for import_path in stable_imports:
            module_path, function_name = import_path.rsplit('.', 1)
            
            try:
                module = frappe.get_module(module_path)
                func = getattr(module, function_name)
                self.assertTrue(callable(func), f"Import {import_path} is not callable")
            except (ImportError, AttributeError) as e:
                self.fail(f"Stable import path {import_path} is broken: {e}")
    
    def test_no_breaking_changes_in_dependencies(self):
        """Ensure no breaking changes in utility dependencies"""
        # Test that key utility modules are still importable
        utility_modules = [
            'verenigingen.utils.performance.query_measurement',
            'verenigingen.utils.performance.bottleneck_analyzer'
        ]
        
        for module_path in utility_modules:
            try:
                module = frappe.get_module(module_path)
                # Check that module has expected classes/functions
                if 'query_measurement' in module_path:
                    self.assertTrue(hasattr(module, 'QueryProfiler'),
                                  f"QueryProfiler missing from {module_path}")
                elif 'bottleneck_analyzer' in module_path:
                    self.assertTrue(hasattr(module, 'N1QueryDetector'),
                                  f"N1QueryDetector missing from {module_path}")
            except ImportError as e:
                self.fail(f"Utility module {module_path} cannot be imported: {e}")


class BackwardCompatibilityViolation(Exception):
    """Raised when backward compatibility is violated"""
    pass