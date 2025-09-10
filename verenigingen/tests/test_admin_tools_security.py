#!/usr/bin/env python3
"""
Unit Tests for Admin Tools Security
====================================

Tests for admin tools security hardening and RCE prevention.
"""

import unittest
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from unittest.mock import patch, MagicMock, Mock
import json
from importlib import import_module
from verenigingen.templates.pages.admin_tools import (
    execute_admin_tool,
    ALLOWED_ADMIN_METHODS,
    get_context,
    json_encode_args
)


class TestAdminToolsSecurity(VereningingenTestCase):
    """Test suite for admin tools security"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.original_user = frappe.session.user
        # Set admin user for security testing
        # VereningingenTestCase handles permissions automatically
        
    def tearDown(self):
        """Clean up after tests"""
        frappe.session.user = self.original_user
        super().tearDown()
    
    def test_allowed_methods_whitelist(self):
        """Test that allowed methods list is properly defined"""
        # Check that it's a set (for O(1) lookup performance)
        self.assertIsInstance(ALLOWED_ADMIN_METHODS, set)
        
        # Check that all methods follow expected pattern
        for method in ALLOWED_ADMIN_METHODS:
            self.assertRegex(method, r'^verenigingen\.')
            self.assertIn('.', method)
            
        # Ensure no dangerous patterns (but allow legitimate words like "imported_data")
        dangerous_patterns = ['__', 'eval', 'exec', 'compile']
        for method in ALLOWED_ADMIN_METHODS:
            for pattern in dangerous_patterns:
                self.assertNotIn(pattern, method)
        
        # Check for dangerous import patterns more specifically
        for method in ALLOWED_ADMIN_METHODS:
            # Avoid false positives like "imported_data" but catch actual import statements
            if 'import' in method and not 'imported' in method:
                self.fail(f"Method {method} contains suspicious 'import' pattern")
    
    def test_execute_admin_tool_permission_denied(self):
        """Test permission checking in execute_admin_tool with real users"""
        # Test with regular user (no admin permissions)
        # VereningingenTestCase handles permissions automatically
        
        # Ensure user has only basic role
        user_doc = frappe.get_doc("User", "test_user@example.com")
        if not frappe.db.exists("User", "test_user@example.com"):
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": "test_user@example.com",
                "first_name": "Test",
                "last_name": "User",
                "enabled": 1
            })
            user_doc.insert()
        
        # Clear existing roles and add only Employee
        user_doc.roles = []
        user_doc.add_roles("Employee")
        
        with self.assertRaises(frappe.PermissionError) as context:
            execute_admin_tool("verenigingen.utils.some_method")
        
        self.assertIn("Insufficient permissions", str(context.exception))
    
    def test_execute_admin_tool_method_not_allowed(self):
        """Test that non-whitelisted methods are blocked"""
        # Admin user already set in setUp
        
        # Try to execute a non-whitelisted method
        result = execute_admin_tool("os.system")
        
        # Should be blocked even for admin users
        self.assertFalse(result.get('success'))
        self.assertIn('not allowed', result.get('error', '').lower())
    
    @patch('frappe.log_error')
    def test_execute_admin_tool_logs_unauthorized_attempts(self, mock_log):
        """Test that unauthorized attempts are logged"""
        # Admin user already set in setUp
        
        # Attempt to execute dangerous method - should be blocked by whitelist
        with self.assertRaises(frappe.PermissionError):
            execute_admin_tool("__import__('os').system('whoami')")
        
        # Check that security alert was logged
        mock_log.assert_called()
        call_args = mock_log.call_args[0]
        self.assertIn("Unauthorized admin tool execution attempt", call_args[0])
        self.assertIn("Administrator", call_args[0])
    
    def test_execute_admin_tool_module_path_validation(self):
        """Test that module paths are validated"""
        # Admin user already set in setUp
        
        # Try various invalid module paths
        invalid_paths = [
            "subprocess.call",
            "eval.something", 
            "../../../etc/passwd",
            "builtins.eval"
        ]
        
        for path in invalid_paths:
            # Add to allowed list to bypass first check
            with patch.object(ALLOWED_ADMIN_METHODS, '__contains__', return_value=True):
                with self.assertRaises(frappe.PermissionError):
                    execute_admin_tool(path)
    
    @patch('importlib.import_module')
    def test_execute_admin_tool_whitelist_decorator_check(self, mock_import):
        """Test that functions must have whitelist decorator"""
        # Admin user already set in setUp
        
        # Create a mock function without whitelist decorator
        mock_func = MagicMock()
        mock_func.__func_is_whitelisted__ = False
        
        mock_module = MagicMock()
        mock_module.test_function = mock_func
        mock_import.return_value = mock_module
        
        # Add to allowed methods
        test_method = "verenigingen.test.test_function"
        ALLOWED_ADMIN_METHODS.add(test_method)
        
        try:
            with self.assertRaises(frappe.PermissionError) as context:
                execute_admin_tool(test_method)
            
            self.assertIn("not properly whitelisted", str(context.exception))
        finally:
            # Clean up
            ALLOWED_ADMIN_METHODS.discard(test_method)
    
    @patch('frappe.logger')
    def test_execute_admin_tool_audit_logging(self, mock_logger_func):
        """Test that admin actions are logged for audit"""
        # Admin user already set in setUp
        mock_logger = MagicMock()
        mock_logger_func.return_value = mock_logger
        
        # Use a real allowed method
        test_method = list(ALLOWED_ADMIN_METHODS)[0] if ALLOWED_ADMIN_METHODS else None
        if not test_method:
            self.skipTest("No allowed methods to test")
        
        with patch('importlib.import_module') as mock_import:
            mock_func = MagicMock(return_value={"test": "result"})
            mock_func.__func_is_whitelisted__ = True
            
            mock_module = MagicMock()
            setattr(mock_module, test_method.split('.')[-1], mock_func)
            mock_import.return_value = mock_module
            
            execute_admin_tool(test_method)
            
            # Check audit logging
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args[0][0]
            self.assertIn("Admin tool executed", call_args)
            self.assertIn(test_method, call_args)
    
    def test_execute_admin_tool_argument_validation(self):
        """Test that arguments are properly validated"""
        # Admin user already set in setUp
        
        # Test with various invalid argument types
        test_method = list(ALLOWED_ADMIN_METHODS)[0] if ALLOWED_ADMIN_METHODS else None
        if not test_method:
            self.skipTest("No allowed methods to test")
        
        with patch('importlib.import_module') as mock_import:
            mock_func = MagicMock()
            mock_func.__func_is_whitelisted__ = True
            
            mock_module = MagicMock()
            setattr(mock_module, test_method.split('.')[-1], mock_func)
            mock_import.return_value = mock_module
            
            # Test with invalid JSON
            result = execute_admin_tool(test_method, "invalid json {]")
            self.assertFalse(result['success'])
            
            # Test with non-dict args after parsing
            with patch('json.loads', return_value=["list", "not", "dict"]):
                with self.assertRaises(frappe.ValidationError):
                    execute_admin_tool(test_method, '["list"]')
    
    def test_execute_admin_tool_error_sanitization(self):
        """Test that errors are sanitized in production mode"""
        # Admin user already set in setUp
        
        test_method = list(ALLOWED_ADMIN_METHODS)[0] if ALLOWED_ADMIN_METHODS else None
        if not test_method:
            self.skipTest("No allowed methods to test")
        
        with patch('importlib.import_module') as mock_import:
            mock_func = MagicMock(side_effect=Exception("Sensitive database error with passwords"))
            mock_func.__func_is_whitelisted__ = True
            
            mock_module = MagicMock()
            setattr(mock_module, test_method.split('.')[-1], mock_func)
            mock_import.return_value = mock_module
            
            # Test in production mode
            with patch.object(frappe.conf, 'developer_mode', 0):
                result = execute_admin_tool(test_method)
                
                self.assertFalse(result['success'])
                self.assertNotIn("password", result['error'].lower())
                self.assertEqual(result['error'], "An error occurred while executing the tool")
            
            # Test in developer mode
            with patch.object(frappe.conf, 'developer_mode', 1):
                result = execute_admin_tool(test_method)
                
                self.assertFalse(result['success'])
                self.assertIn("Sensitive database error", result['error'])


class TestAdminToolsContext(VereningingenTestCase):
    """Test admin tools page context generation"""
    
    def test_get_context_permission_check(self):
        """Test that get_context checks permissions"""
        frappe.session.user = "unauthorized@example.com"
        
        with patch('frappe.get_roles', return_value=['Guest']):
            with self.assertRaises(frappe.PermissionError):
                # Create a context object that behaves like Frappe's page context
                class MockContext(dict):
                    def __setattr__(self, key, value):
                        self[key] = value
                    def __getattr__(self, key):
                        try:
                            return self[key]
                        except KeyError:
                            raise AttributeError(key)
                
                context = MockContext()
                get_context(context)
    
    @patch('frappe.get_roles')
    def test_get_context_allowed_roles(self, mock_roles):
        """Test that correct roles are allowed"""
        allowed_scenarios = [
            ("Administrator", []),
            ("user@example.com", ["System Manager"]),
            ("user@example.com", ["Verenigingen Administrator"]),
            ("user@example.com", ["Other Role", "System Manager"])
        ]
        
        for user, roles in allowed_scenarios:
            frappe.session.user = user
            mock_roles.return_value = roles
            
            # Create a context object that behaves like Frappe's page context
            class MockContext(dict):
                def __setattr__(self, key, value):
                    self[key] = value
                def __getattr__(self, key):
                    try:
                        return self[key]
                    except KeyError:
                        raise AttributeError(key)
            
            context = MockContext()
            try:
                get_context(context)
                # Should not raise exception
            except frappe.PermissionError:
                self.fail(f"User {user} with roles {roles} should be allowed")
    
    def test_json_encode_args(self):
        """Test JSON encoding helper function"""
        # Test with None
        self.assertEqual(json_encode_args(None), "")
        
        # Test with dict
        test_dict = {"key": "value", "number": 123}
        encoded = json_encode_args(test_dict)
        self.assertEqual(json.loads(encoded), test_dict)
        
        # Test with complex nested structure
        complex_dict = {
            "nested": {"deep": {"value": True}},
            "list": [1, 2, 3],
            "null": None
        }
        encoded = json_encode_args(complex_dict)
        self.assertEqual(json.loads(encoded), complex_dict)


class TestRCEPrevention(VereningingenTestCase):
    """Specific tests for RCE (Remote Code Execution) prevention"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.original_user = frappe.session.user
        # Set admin user for security testing
        # VereningingenTestCase handles permissions automatically
        
    def tearDown(self):
        """Clean up after tests"""
        frappe.session.user = self.original_user
        super().tearDown()
    
    def test_prevent_code_injection_attempts(self):
        """Test various code injection attempts are blocked"""
        # Admin user already set in setUp
        
        injection_attempts = [
            "__import__('os').system('rm -rf /')",
            "eval('malicious code')",
            "exec('malicious code')",
            "compile('malicious', 'fake', 'exec')",
            "verenigingen.utils'; __import__('os').system('ls'); '",
            "verenigingen.utils.invoice_management'; import os; os.system('whoami'); '",
        ]
        
        for attempt in injection_attempts:
            result = execute_admin_tool(attempt)
            self.assertFalse(result.get('success', False), 
                           f"Injection attempt should be blocked: {attempt}")
    
    def test_prevent_path_traversal(self):
        """Test that path traversal attempts are blocked"""
        # Admin user already set in setUp
        
        traversal_attempts = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "verenigingen/../../../sensitive_module",
            "verenigingen/./././../../../evil",
        ]
        
        for attempt in traversal_attempts:
            with self.assertRaises((frappe.PermissionError, ValueError)):
                execute_admin_tool(attempt)
    
    def test_prevent_dynamic_import_manipulation(self):
        """Test that dynamic import manipulation is prevented"""
        # Admin user already set in setUp
        
        # Even if someone adds a malicious method to ALLOWED_ADMIN_METHODS
        malicious_method = "os.system"
        
        # Temporarily add to allowed methods
        original_methods = ALLOWED_ADMIN_METHODS.copy()
        ALLOWED_ADMIN_METHODS.add(malicious_method)
        
        try:
            # Should still be blocked by module path validation
            with self.assertRaises(frappe.PermissionError):
                execute_admin_tool(malicious_method)
        finally:
            # Restore original methods
            ALLOWED_ADMIN_METHODS.clear()
            ALLOWED_ADMIN_METHODS.update(original_methods)


class TestAdminToolsIntegration(VereningingenTestCase):
    """Integration tests for admin tools"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.original_user = frappe.session.user
        # Set admin user for security testing
        # VereningingenTestCase handles permissions automatically
        
    def tearDown(self):
        """Clean up after tests"""
        frappe.session.user = self.original_user
        super().tearDown()
    
    def test_successful_execution_flow(self):
        """Test successful execution of an allowed admin tool"""
        # Admin user already set in setUp
        
        # Pick a real allowed method
        test_method = "verenigingen.setup.security_setup.check_current_security_status"
        
        if test_method not in ALLOWED_ADMIN_METHODS:
            self.skipTest(f"Method {test_method} not in allowed list")
        
        # Mock the actual function
        with patch('verenigingen.setup.security_setup.check_current_security_status') as mock_func:
            mock_func.return_value = {
                "success": True,
                "status": {"security_score": "5/10"}
            }
            mock_func.__func_is_whitelisted__ = True
            
            result = execute_admin_tool(test_method)
            
            self.assertTrue(result['success'])
            self.assertIn('result', result)
            self.assertIn('timestamp', result)
    
    def test_rate_limiting_integration(self):
        """Test that rate limiting works with admin tools"""
        # This would require Redis setup for proper testing
        # For now, ensure the decorators don't break functionality
        pass


def run_tests():
    """Run all admin tools security tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test cases
    suite.addTests(loader.loadTestsFromTestCase(TestAdminToolsSecurity))
    suite.addTests(loader.loadTestsFromTestCase(TestAdminToolsContext))
    suite.addTests(loader.loadTestsFromTestCase(TestRCEPrevention))
    suite.addTests(loader.loadTestsFromTestCase(TestAdminToolsIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)