#!/usr/bin/env python3
"""
Unit Tests for Admin Tools Security
====================================

Tests for admin tools security hardening and RCE prevention.
"""

import unittest
import frappe
from verenigingen.tests.utils.base import VereningingenTestCase

from unittest.mock import patch, MagicMock
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
            
        # Ensure no dangerous patterns. Substring matches false-positive on legitimate
        # names (e.g. ``cleanup_imported_data`` contains ``import``,
        # ``member_import_cleanup`` contains ``import``); the strong guarantee that
        # these strings can't reach arbitrary code is provided by
        # test_allowed_methods_resolve, which actually imports each one.
        dangerous_patterns = ['eval(', 'exec(', 'compile(']
        for method in ALLOWED_ADMIN_METHODS:
            for pattern in dangerous_patterns:
                self.assertNotIn(pattern, method)
            # Block dunder-attribute access via the dotted path
            for component in method.split('.'):
                self.assertFalse(
                    component.startswith('__') and component.endswith('__'),
                    f"Method {method} contains dunder component '{component}'",
                )

    def test_allowed_methods_resolve(self):
        """Every method in ALLOWED_ADMIN_METHODS must import + resolve to a callable.

        Catches bugs like a referenced module being moved/renamed without updating
        the allow-list — string literals are invisible to AST-based import validators.
        """
        unresolved = []
        for method in ALLOWED_ADMIN_METHODS:
            module_path, function_name = method.rsplit('.', 1)
            try:
                module = import_module(module_path)
            except ImportError as e:
                unresolved.append(f"{method}: module not found ({e})")
                continue
            func = getattr(module, function_name, None)
            if func is None:
                unresolved.append(f"{method}: function missing in {module_path}")
            elif not callable(func):
                unresolved.append(f"{method}: resolved object is not callable")
        if unresolved:
            self.fail(
                "ALLOWED_ADMIN_METHODS contains unresolvable entries:\n  - "
                + "\n  - ".join(unresolved)
            )

    def _build_admin_context(self):
        """Run ``get_context`` as Administrator and return the populated
        context object. Extracted from the test method so the temporary
        ``frappe.set_user("Administrator")`` bypass lives in a helper —
        ``get_context`` checks the role and would refuse otherwise."""
        class _Ctx:
            pass

        original_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            ctx = _Ctx()
            get_context(ctx)
        finally:
            frappe.set_user(original_user)
        return ctx

    def test_ui_tool_methods_are_allowed_and_resolve(self):
        """Every method wired to a UI button in get_context() must be in
        ALLOWED_ADMIN_METHODS and resolve at import time.

        Catches the inverse bug: a tool button whose method string is not in
        the allow-list, which would fail at click time with "Method not allowed".
        """
        ctx = self._build_admin_context()

        # Collect every method string from every *_tools list on the context
        ui_methods = set()
        for attr_name in dir(ctx):
            if attr_name.endswith('_tools'):
                tools = getattr(ctx, attr_name, None)
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict) and 'method' in tool:
                            ui_methods.add(tool['method'])

        self.assertGreater(len(ui_methods), 0, "Expected at least one UI tool method")

        # Every UI method must be in the allow-list
        not_allowed = ui_methods - ALLOWED_ADMIN_METHODS
        self.assertFalse(
            not_allowed,
            f"UI tool methods missing from ALLOWED_ADMIN_METHODS (clicks will fail "
            f"with 'Method not allowed'):\n  - " + "\n  - ".join(sorted(not_allowed)),
        )

        # Every UI method must resolve at import time
        unresolved = []
        for method in ui_methods:
            module_path, function_name = method.rsplit('.', 1)
            try:
                module = import_module(module_path)
            except ImportError as e:
                unresolved.append(f"{method}: module not found ({e})")
                continue
            if not callable(getattr(module, function_name, None)):
                unresolved.append(f"{method}: function missing or not callable")
        if unresolved:
            self.fail(
                "UI tool methods do not resolve:\n  - " + "\n  - ".join(unresolved)
            )

    def test_execute_admin_tool_permission_denied(self):
        """A non-admin, non-System Manager user is denied at the permission gate.

        ``execute_admin_tool`` is wrapped with @critical_api which runs its own
        framework-level check before the function body. That check raises
        ``verenigingen.utils.error_handling.PermissionError`` (not
        ``frappe.PermissionError`` — they are separate classes). Either flavor
        satisfies the security contract: the call is denied before any tool
        logic runs.

        We test the real boundary by switching to Guest (no admin role) rather
        than mocking has_permission / get_roles — that way Frappe's real
        permission check fires.
        """
        from verenigingen.utils.error_handling import PermissionError as VPermErr

        original_user = frappe.session.user
        frappe.set_user("Guest")  # not "Administrator" — fails the user==Administrator check
        try:
            with self.assertRaises((frappe.PermissionError, VPermErr)):
                execute_admin_tool("verenigingen.utils.some_method")
        finally:
            frappe.set_user(original_user)
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_execute_admin_tool_method_not_allowed(self, _mock_log):
        """Test that non-whitelisted methods are blocked.

        ``frappe.log_error`` is patched: admin_tools logs the unauthorized
        attempt before throwing, and earlier tests in this module mock
        ``importlib.import_module``, which can poison Frappe's controller
        cache for "Error Log" and break the framework log_error call.
        """
        with self.assertRaises(frappe.PermissionError) as context:
            execute_admin_tool("os.system")
        self.assertIn("not allowed", str(context.exception).lower())
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
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
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_execute_admin_tool_module_path_validation(self, _mock_log):
        """Module paths not under verenigingen./frappe. are rejected.

        Each invalid path is temporarily added to ALLOWED_ADMIN_METHODS to
        bypass the allow-list gate so the secondary module-path-prefix gate
        (admin_tools.py:736) is the one under test. We add+discard directly
        rather than ``patch.object(set, '__contains__')`` because Python 3.12
        forbids patching dunders on built-in set instances.
        """
        invalid_paths = [
            "subprocess.call",
            "eval.something",
            "../../../etc/passwd",
            "builtins.eval",
        ]
        for path in invalid_paths:
            ALLOWED_ADMIN_METHODS.add(path)
            try:
                with self.assertRaises(frappe.PermissionError):
                    execute_admin_tool(path)
            finally:
                ALLOWED_ADMIN_METHODS.discard(path)
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('importlib.import_module')
    def test_explicit_allowance_bypasses_whitelist_attribute(self, mock_import):
        """Methods in ALLOWED_ADMIN_METHODS execute even without the
        ``__func_is_whitelisted__`` attribute.

        This locks in the intentional behavior at admin_tools.py:750/801: the
        ALLOWED_ADMIN_METHODS set is the authoritative gate, and a method
        present there bypasses the whitelist-attribute check (with an audit log
        warning). The "Method not allowed" gate is covered separately by
        test_execute_admin_tool_method_not_allowed.
        """
        mock_func = MagicMock(return_value={"ok": True})
        # Explicitly no __func_is_whitelisted__ attribute
        del mock_func.__func_is_whitelisted__

        mock_module = MagicMock()
        mock_module.test_function = mock_func
        mock_import.return_value = mock_module

        test_method = "verenigingen.test.test_function"
        ALLOWED_ADMIN_METHODS.add(test_method)
        try:
            result = execute_admin_tool(test_method)
            self.assertTrue(result['success'])
            mock_func.assert_called_once()
        finally:
            ALLOWED_ADMIN_METHODS.discard(test_method)
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
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
        
        # Mock justified: Infrastructure - external dependency, not the boundary under test
        with patch('importlib.import_module') as mock_import:
            mock_func = MagicMock(return_value={"test": "result"})
            mock_func.__func_is_whitelisted__ = True
            
            mock_module = MagicMock()
            setattr(mock_module, test_method.split('.')[-1], mock_func)
            mock_import.return_value = mock_module
            
            execute_admin_tool(test_method)

            # Check audit logging — admin_tools emits a pre-execution
            # "Admin tool executed: …" log and a post-execution
            # "Admin tool completed successfully: …" log. Walk all calls.
            mock_logger.info.assert_called()
            messages = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
            self.assertTrue(
                any("Admin tool executed" in m for m in messages),
                f"Expected pre-execution audit log, got: {messages}",
            )
            self.assertTrue(
                any(test_method in m for m in messages),
                f"Expected method name in audit log, got: {messages}",
            )
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_execute_admin_tool_argument_validation(self, _mock_log):
        """JSON args that don't decode to a dict are rejected.

        Uses ``get_system_health`` as a real allowed, side-effect-free method
        and patches ``json.loads`` to return a list. The dict-shape gate at
        admin_tools.py:844 should fire and the outer ``except Exception``
        surfaces it as ``success=False``.

        We deliberately do NOT patch ``importlib.import_module``: combining it
        with ``patch('json.loads', ...)`` makes admin_tools take the no-args
        branch (likely an import-machinery interaction), bypassing the very
        gate this test exercises.
        """
        test_method = "verenigingen.utils.performance_dashboard.get_system_health"
        self.assertIn(test_method, ALLOWED_ADMIN_METHODS)

        # Mock justified: Infrastructure - external dependency, not the boundary under test
        with patch('json.loads', return_value=["list", "not", "dict"]):
            result = execute_admin_tool(test_method, '{"forced":"to_parse"}')
        self.assertFalse(result['success'])
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_execute_admin_tool_error_sanitization(self, _mock_log):
        """Errors are sanitized in production mode, exposed in developer mode.

        ``frappe.conf`` is a frappe._dict, not an object with ``__dict__`` —
        ``patch.object(frappe.conf, 'developer_mode', ...)`` raises
        ``TypeError: 'NoneType' object is not subscriptable``. Save/restore
        the key directly instead.
        """
        test_method = list(ALLOWED_ADMIN_METHODS)[0] if ALLOWED_ADMIN_METHODS else None
        if not test_method:
            self.skipTest("No allowed methods to test")

        original_dev_mode = frappe.conf.get('developer_mode')
        # Mock justified: Infrastructure - external dependency, not the boundary under test
        with patch('importlib.import_module') as mock_import:
            mock_func = MagicMock(side_effect=Exception("Sensitive database error with passwords"))
            mock_func.__func_is_whitelisted__ = True
            mock_module = MagicMock()
            setattr(mock_module, test_method.split('.')[-1], mock_func)
            mock_import.return_value = mock_module

            try:
                # Production mode → sanitized error
                frappe.conf['developer_mode'] = 0
                result = execute_admin_tool(test_method)
                self.assertFalse(result['success'])
                self.assertNotIn("password", result['error'].lower())
                self.assertEqual(result['error'], "An error occurred while executing the tool")

                # Developer mode → raw error
                frappe.conf['developer_mode'] = 1
                result = execute_admin_tool(test_method)
                self.assertFalse(result['success'])
                self.assertIn("Sensitive database error", result['error'])
            finally:
                if original_dev_mode is None:
                    frappe.conf.pop('developer_mode', None)
                else:
                    frappe.conf['developer_mode'] = original_dev_mode


class TestAdminToolsContext(VereningingenTestCase):
    """Test admin tools page context generation"""
    
    def test_get_context_permission_check(self):
        """Test that get_context checks permissions"""
        frappe.session.user = "unauthorized@example.com"
        
        # Mock justified: Infrastructure - external dependency, not the boundary under test
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
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
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
    
    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_prevent_code_injection_attempts(self, _mock_log):
        """Test various code injection attempts are blocked.

        ``frappe.log_error`` is patched: each blocked attempt logs a
        security alert before throwing, and we don't want those test-time
        log writes to interact with Frappe's controller cache (see
        test_execute_admin_tool_method_not_allowed for the same reason).
        """
        injection_attempts = [
            "__import__('os').system('rm -rf /')",
            "eval('malicious code')",
            "exec('malicious code')",
            "compile('malicious', 'fake', 'exec')",
            "verenigingen.utils'; __import__('os').system('ls'); '",
            "verenigingen.utils.invoice_management'; import os; os.system('whoami'); '",
        ]
        for attempt in injection_attempts:
            with self.assertRaises(
                frappe.PermissionError,
                msg=f"Injection attempt should be blocked: {attempt}",
            ):
                execute_admin_tool(attempt)

    # Mock justified: Infrastructure - external dependency, not the boundary under test
    @patch('frappe.log_error')
    def test_prevent_path_traversal(self, _mock_log):
        """Test that path traversal attempts are blocked."""
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
        # Mock justified: Infrastructure - external dependency, not the boundary under test
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