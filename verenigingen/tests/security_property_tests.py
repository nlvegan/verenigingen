#!/usr/bin/env python3
"""
Property-Based Security Testing Utilities
==========================================

Implements property-based testing for security controls using hypothesis library
to generate edge cases and attack scenarios that might not be covered by
traditional example-based tests.
"""

import string
import random
from functools import wraps
from unittest.mock import patch, MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase

# Try to import hypothesis for property-based testing
try:
    from hypothesis import given, strategies as st, example, settings
    from hypothesis.strategies import composite
    HYPOTHESIS_AVAILABLE = True
except ImportError:
    # Fallback to manual property testing if hypothesis not available
    HYPOTHESIS_AVAILABLE = False
    print("⚠️  Hypothesis not available. Install with: pip install hypothesis")


class SecurityPropertyTestCase(FrappeTestCase):
    """Base class for property-based security testing"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        frappe.session.user = "test_security@example.com"
    
    def tearDown(self):
        frappe.session.user = self.original_user
        super().tearDown()


# Custom strategies for security testing
if HYPOTHESIS_AVAILABLE:
    
    @composite
    def malicious_method_names(draw):
        """Generate potentially malicious method names for testing"""
        dangerous_patterns = [
            "__import__",
            "eval",
            "exec", 
            "compile",
            "getattr",
            "setattr",
            "delattr",
            "open",
            "file",
            "input",
            "raw_input"
        ]
        
        injection_chars = [";", "&", "|", "`", "$", "(", ")", "{", "}", "[", "]"]
        
        # Generate various malicious patterns
        pattern_type = draw(st.integers(min_value=0, max_value=3))
        
        if pattern_type == 0:
            # Direct dangerous method
            return draw(st.sampled_from(dangerous_patterns))
        elif pattern_type == 1:
            # Method with injection characters
            base = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
            injection = draw(st.sampled_from(injection_chars))
            suffix = draw(st.text(alphabet=string.ascii_letters + string.digits, max_size=5))
            return f"{base}{injection}{suffix}"
        elif pattern_type == 2:
            # Path traversal attempts
            levels = draw(st.integers(min_value=1, max_value=5))
            traversal = "../" * levels
            target = draw(st.text(alphabet=string.ascii_letters, min_size=3, max_size=10))
            return f"{traversal}{target}"
        else:
            # Module path manipulation
            parts = draw(st.lists(st.text(alphabet=string.ascii_letters, min_size=1, max_size=8), min_size=2, max_size=5))
            return ".".join(parts)
    
    
    @composite  
    def csrf_attack_payloads(draw):
        """Generate various CSRF attack payloads"""
        payload_types = [
            "",  # Empty token
            "invalid-token-format",  # Invalid format
            "a" * 1000,  # Extremely long token
            "<script>alert('xss')</script>",  # XSS attempt in token
            "../../../etc/passwd",  # Path traversal
            "token'; DROP TABLE users; --",  # SQL injection attempt
        ]
        
        return draw(st.sampled_from(payload_types))
    
    
    @composite
    def rate_limit_attack_scenarios(draw):
        """Generate rate limiting attack scenarios"""
        scenario = draw(st.integers(min_value=0, max_value=2))
        
        if scenario == 0:
            # Burst attack - many requests quickly
            return {
                'type': 'burst',
                'requests': draw(st.integers(min_value=10, max_value=100)),
                'interval': draw(st.floats(min_value=0.001, max_value=0.1))
            }
        elif scenario == 1:
            # Distributed attack - different users
            return {
                'type': 'distributed',
                'users': draw(st.integers(min_value=5, max_value=20)),
                'requests_per_user': draw(st.integers(min_value=3, max_value=15))
            }
        else:
            # Slow drain attack - just under limit
            return {
                'type': 'slow_drain',
                'limit': draw(st.integers(min_value=5, max_value=50)),
                'requests': lambda limit: limit - 1,
                'duration': draw(st.integers(min_value=30, max_value=300))
            }


class PropertyBasedAdminToolsSecurityTests(SecurityPropertyTestCase):
    """Property-based tests for admin tools security"""
    
    @given(malicious_method_names()) if HYPOTHESIS_AVAILABLE else lambda x: x
    @example("__import__('os').system('rm -rf /')")
    @example("eval('malicious_code')")
    @example("../../../etc/passwd")
    def test_admin_tools_blocks_all_malicious_methods(self, malicious_method):
        """Property: Admin tools should block ALL malicious method calls"""
        from verenigingen.templates.pages.admin_tools import execute_admin_tool
        
        with patch('frappe.has_permission', return_value=True):
            result = execute_admin_tool(malicious_method)
            
            # Property: No malicious method should ever succeed
            self.assertFalse(result.get('success', False), 
                           f"Malicious method should be blocked: {malicious_method}")
            
            # Property: Error should be logged for security monitoring
            # This would be verified through audit log checks in real implementation
    
    def test_admin_tools_whitelist_invariant(self):
        """Property: Only methods in whitelist should be executable"""
        from verenigingen.templates.pages.admin_tools import ALLOWED_ADMIN_METHODS, execute_admin_tool
        
        # Generate some methods that are definitely not in whitelist
        non_whitelisted_methods = [
            "os.system",
            "subprocess.call", 
            "builtins.eval",
            "sys.exit",
            "frappe.delete_doc"  # Valid module but not whitelisted
        ]
        
        with patch('frappe.has_permission', return_value=True):
            for method in non_whitelisted_methods:
                if method not in ALLOWED_ADMIN_METHODS:
                    result = execute_admin_tool(method)
                    self.assertFalse(result.get('success', False),
                                   f"Non-whitelisted method should be blocked: {method}")


class PropertyBasedCSRFTests(SecurityPropertyTestCase):
    """Property-based tests for CSRF protection"""
    
    @given(csrf_attack_payloads()) if HYPOTHESIS_AVAILABLE else lambda x: x
    @example("")
    @example("<script>alert('xss')</script>")
    @example("../../../etc/passwd")
    def test_csrf_validation_rejects_all_invalid_tokens(self, invalid_token):
        """Property: CSRF validation should reject ALL invalid tokens"""
        from verenigingen.setup.security_setup import validate_csrf_token
        
        frappe.conf.ignore_csrf = 0  # Enable CSRF protection
        
        with patch('frappe.get_request_header', return_value=invalid_token):
            with patch('frappe.sessions.validate_csrf_token', side_effect=Exception("Invalid")):
                
                with self.assertRaises(frappe.CSRFTokenError):
                    validate_csrf_token()
    
    def test_csrf_disabled_always_passes(self):
        """Property: When CSRF is disabled, validation should always pass"""
        from verenigingen.setup.security_setup import validate_csrf_token
        
        frappe.conf.ignore_csrf = 1  # Disable CSRF protection
        
        # Should never raise exception regardless of token
        malicious_tokens = ["", "invalid", "<script>", "../../../etc/passwd"]
        
        for token in malicious_tokens:
            with patch('frappe.get_request_header', return_value=token):
                try:
                    validate_csrf_token()  # Should not raise
                except frappe.CSRFTokenError:
                    self.fail(f"CSRF validation should pass when disabled, but failed for: {token}")


class PropertyBasedRateLimitTests(SecurityPropertyTestCase):
    """Property-based tests for rate limiting"""
    
    def test_rate_limit_invariant_under_limit(self):
        """Property: Requests under rate limit should always succeed"""
        from verenigingen.setup.security_setup import security_rate_limit
        
        @security_rate_limit(limit=5, seconds=60)
        def test_function():
            return "success"
        
        # Property: First 5 calls should always succeed
        for i in range(5):
            try:
                result = test_function()
                self.assertEqual(result, "success", f"Call {i+1} should succeed")
            except frappe.RateLimitExceededError:
                self.fail(f"Call {i+1} should not be rate limited")
    
    def test_rate_limit_invariant_over_limit(self):
        """Property: Requests over rate limit should always fail"""
        from verenigingen.setup.security_setup import security_rate_limit
        
        @security_rate_limit(limit=2, seconds=60)
        def test_function():
            return "success"
        
        # Use up the limit
        test_function()
        test_function()
        
        # Property: All subsequent calls should fail
        for i in range(5):  # Try 5 more times
            with self.assertRaises(frappe.RateLimitExceededError):
                test_function()
    
    @given(rate_limit_attack_scenarios()) if HYPOTHESIS_AVAILABLE else lambda x: x
    def test_rate_limiting_resilient_to_attack_patterns(self, attack_scenario):
        """Property: Rate limiting should be resilient to various attack patterns"""
        from verenigingen.setup.security_setup import security_rate_limit
        
        @security_rate_limit(limit=3, seconds=10)
        def test_function():
            return "success"
        
        if attack_scenario['type'] == 'burst':
            # Burst attack should be stopped by rate limiting
            success_count = 0
            for _ in range(attack_scenario['requests']):
                try:
                    test_function()
                    success_count += 1
                except frappe.RateLimitExceededError:
                    break
            
            # Should hit rate limit quickly
            self.assertLessEqual(success_count, 3, "Burst attack should be rate limited")


class PropertyBasedSecurityStatusTests(SecurityPropertyTestCase):
    """Property-based tests for security status checking"""
    
    def test_security_score_monotonic_property(self):
        """Property: Security score should increase as security features are enabled"""
        from verenigingen.setup.security_setup import check_security_status
        
        # Test various configuration combinations
        configs = [
            {},  # No security features
            {"ignore_csrf": 0},  # Just CSRF
            {"ignore_csrf": 0, "secret_key": "test"},  # CSRF + secret
            {"ignore_csrf": 0, "secret_key": "test", "encryption_key": "test"},  # More features
        ]
        
        previous_score = -1
        for config in configs:
            with patch('frappe.get_site_config', return_value=config):
                status = check_security_status()
                current_score = float(status['security_score'].split('/')[0])
                
                # Property: Score should never decrease as we add security features
                self.assertGreaterEqual(current_score, previous_score,
                                      f"Security score should not decrease: {previous_score} -> {current_score}")
                previous_score = current_score
    
    def test_security_recommendations_consistency(self):
        """Property: Security recommendations should be consistent with status"""
        from verenigingen.setup.security_setup import check_security_status
        
        insecure_config = {
            "ignore_csrf": 1,
            "developer_mode": 1,
            "allow_tests": 1
        }
        
        with patch('frappe.get_site_config', return_value=insecure_config):
            status = check_security_status()
            
            # Property: If CSRF is disabled, there should be a recommendation to enable it
            if not status['csrf_protection']:
                recommendations = ' '.join(status['recommendations']).lower()
                self.assertIn('csrf', recommendations, 
                            "Should recommend enabling CSRF when disabled")
            
            # Property: If developer mode is on, should recommend disabling in production
            if status['developer_mode']:
                recommendations = ' '.join(status['recommendations']).lower()
                self.assertIn('developer', recommendations,
                            "Should recommend disabling developer mode")


# Manual property testing for when hypothesis is not available
class ManualPropertyTests(SecurityPropertyTestCase):
    """Manual property-based tests when hypothesis is not available"""
    
    def test_admin_tools_security_properties_manual(self):
        """Manual property testing for admin tools security"""
        from verenigingen.templates.pages.admin_tools import execute_admin_tool
        
        # Test various malicious method patterns
        malicious_patterns = [
            "__import__('os').system('rm -rf /')",
            "eval('print(\"pwned\")')",
            "exec('malicious_code')",
            "../../../etc/passwd",
            "os.system",
            "subprocess.call",
            "builtins.eval",
            "method'; import os; os.system('ls'); '",
        ]
        
        with patch('frappe.has_permission', return_value=True):
            for pattern in malicious_patterns:
                result = execute_admin_tool(pattern)
                self.assertFalse(result.get('success', False),
                               f"Malicious pattern should be blocked: {pattern}")
    
    def test_csrf_validation_properties_manual(self):
        """Manual property testing for CSRF validation"""
        from verenigingen.setup.security_setup import validate_csrf_token
        
        invalid_tokens = [
            "",
            "invalid-token",
            "a" * 1000,  # Very long token
            "<script>alert('xss')</script>",
            "../../../etc/passwd",
            "token'; DROP TABLE users; --",
        ]
        
        frappe.conf.ignore_csrf = 0
        
        for token in invalid_tokens:
            with patch('frappe.get_request_header', return_value=token):
                with patch('frappe.sessions.validate_csrf_token', side_effect=Exception("Invalid")):
                    with self.assertRaises(frappe.CSRFTokenError):
                        validate_csrf_token()


def run_property_based_security_tests():
    """Run all property-based security tests"""
    if not HYPOTHESIS_AVAILABLE:
        print("⚠️  Running manual property tests (install hypothesis for full coverage)")
        
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add property-based test cases
    test_cases = [
        PropertyBasedAdminToolsSecurityTests,
        PropertyBasedCSRFTests,
        PropertyBasedRateLimitTests,
        PropertyBasedSecurityStatusTests
    ]
    
    if not HYPOTHESIS_AVAILABLE:
        test_cases.append(ManualPropertyTests)
    
    for test_case in test_cases:
        suite.addTests(loader.loadTestsFromTestCase(test_case))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    import unittest
    success = run_property_based_security_tests()
    exit(0 if success else 1)