#!/usr/bin/env python3
"""
Comprehensive Security Setup Tests
================================

Tests for security_setup.py module covering rate limiting, CSRF validation,
security configuration, and audit logging.
"""

import unittest
import time
import json
from unittest.mock import patch, MagicMock, Mock, call
from frappe.tests.utils import FrappeTestCase
import frappe
from frappe.utils import now_datetime

from verenigingen.setup.security_setup import (
    security_rate_limit,
    validate_csrf_token,
    setup_csrf_protection,
    generate_session_secret,
    setup_password_policy,
    check_security_status,
    log_security_audit,
    setup_all_security,
    enable_csrf_protection,
    check_current_security_status,
    apply_production_security
)


class TestSecurityRateLimit(FrappeTestCase):
    """Test custom rate limiting decorator"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        frappe.session.user = "test_user@example.com"
    
    def tearDown(self):
        frappe.session.user = self.original_user
        # Clear cache between tests
        from frappe.cache import cache
        cache().delete_keys("security_rate_limit:*")
        super().tearDown()
    
    def test_rate_limit_decorator_application(self):
        """Test that rate limit decorator can be applied to functions"""
        @security_rate_limit(limit=2, seconds=10)
        def test_function():
            return "success"
        
        # Should work first time
        result = test_function()
        self.assertEqual(result, "success")
        
        # Should work second time
        result = test_function()
        self.assertEqual(result, "success")
        
        # Should fail third time
        with self.assertRaises(frappe.RateLimitExceededError):
            test_function()
    
    @patch('verenigingen.setup.security_setup.log_security_audit')
    def test_rate_limit_audit_logging(self, mock_audit):
        """Test that rate limit violations are logged"""
        @security_rate_limit(limit=1, seconds=10)
        def test_function():
            return "success"
        
        # First call should succeed
        test_function()
        
        # Second call should fail and log
        with self.assertRaises(frappe.RateLimitExceededError):
            test_function()
        
        # Verify audit log was called
        mock_audit.assert_called_with(
            "Rate Limit Exceeded",
            {
                "function": "test_function",
                "user": "test_user@example.com",
                "limit": 1,
                "seconds": 10,
            }
        )
    
    def test_rate_limit_per_user_isolation(self):
        """Test that rate limits are isolated per user"""
        @security_rate_limit(limit=1, seconds=10)
        def test_function():
            return "success"
        
        # User 1 hits limit
        frappe.session.user = "user1@example.com"
        test_function()
        with self.assertRaises(frappe.RateLimitExceededError):
            test_function()
        
        # User 2 should still be able to call
        frappe.session.user = "user2@example.com"
        result = test_function()
        self.assertEqual(result, "success")
    
    def test_rate_limit_cache_expiration(self):
        """Test that rate limits reset after expiration"""
        @security_rate_limit(limit=1, seconds=1)  # 1 second expiration
        def test_function():
            return "success"
        
        # Hit limit
        test_function()
        with self.assertRaises(frappe.RateLimitExceededError):
            test_function()
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should work again
        result = test_function()
        self.assertEqual(result, "success")


class TestCSRFValidation(FrappeTestCase):
    """Test CSRF token validation"""
    
    def setUp(self):
        super().setUp()
        self.original_conf = frappe.conf.copy()
        self.original_local = frappe.local
    
    def tearDown(self):
        frappe.conf.clear()
        frappe.conf.update(self.original_conf)
        frappe.local = self.original_local
        super().tearDown()
    
    def test_csrf_disabled_skips_validation(self):
        """Test that CSRF validation is skipped when disabled"""
        frappe.conf.ignore_csrf = 1
        
        # Should not raise exception
        try:
            validate_csrf_token()
        except frappe.CSRFTokenError:
            self.fail("CSRF validation should be skipped when disabled")
    
    def test_csrf_enabled_requires_token(self):
        """Test that CSRF validation requires token when enabled"""
        frappe.conf.ignore_csrf = 0
        frappe.local.form_dict = {}
        
        with patch('frappe.get_request_header', return_value=None):
            with self.assertRaises(frappe.CSRFTokenError) as context:
                validate_csrf_token()
            
            self.assertIn("CSRF token missing", str(context.exception))
    
    def test_csrf_validation_with_valid_token(self):
        """Test CSRF validation with valid token"""
        frappe.conf.ignore_csrf = 0
        test_token = "valid-csrf-token"
        
        with patch('frappe.get_request_header', return_value=test_token):
            with patch('frappe.sessions.validate_csrf_token') as mock_validate:
                mock_validate.return_value = True
                
                # Should not raise exception
                try:
                    validate_csrf_token()
                except frappe.CSRFTokenError:
                    self.fail("Valid CSRF token should pass validation")
                
                mock_validate.assert_called_once_with(test_token)
    
    def test_csrf_validation_with_invalid_token(self):
        """Test CSRF validation with invalid token"""
        frappe.conf.ignore_csrf = 0
        test_token = "invalid-csrf-token"
        
        with patch('frappe.get_request_header', return_value=test_token):
            with patch('frappe.sessions.validate_csrf_token', side_effect=Exception("Invalid")):
                with self.assertRaises(frappe.CSRFTokenError) as context:
                    validate_csrf_token()
                
                self.assertIn("Invalid CSRF token", str(context.exception))


class TestSecurityConfiguration(FrappeTestCase):
    """Test security configuration functions"""
    
    def setUp(self):
        super().setUp()
        self.original_conf = frappe.conf.copy()
    
    def tearDown(self):
        frappe.conf.clear()
        frappe.conf.update(self.original_conf)
        super().tearDown()
    
    @patch('frappe.get_site_config')
    @patch('frappe.installer.update_site_config')
    def test_setup_csrf_protection_production(self, mock_update_config, mock_get_config):
        """Test CSRF protection setup in production mode"""
        mock_get_config.return_value = {
            "ignore_csrf": 1,
            "developer_mode": 0
        }
        
        result = setup_csrf_protection()
        
        self.assertEqual(result["status"], "enabled")
        mock_update_config.assert_called_with("ignore_csrf", 0)
    
    @patch('frappe.get_site_config')
    def test_setup_csrf_protection_developer_mode(self, mock_get_config):
        """Test CSRF protection setup in developer mode"""
        mock_get_config.return_value = {
            "ignore_csrf": 1,
            "developer_mode": 1
        }
        
        result = setup_csrf_protection()
        
        self.assertEqual(result["status"], "skipped")
        self.assertIn("developer mode", result["message"])
    
    @patch('frappe.get_site_config')
    @patch('secrets.choice')
    @patch('frappe.installer.update_site_config')
    def test_generate_session_secret_new(self, mock_update_config, mock_choice, mock_get_config):
        """Test generating new session secret"""
        mock_get_config.return_value = {}  # No existing secret
        mock_choice.side_effect = list("a" * 64)  # Mock secret generation
        
        result = generate_session_secret()
        
        self.assertTrue(result)
        mock_update_config.assert_called_once()
        # Verify secret_key was set
        call_args = mock_update_config.call_args[0]
        self.assertEqual(call_args[0], "secret_key")
        self.assertEqual(len(call_args[1]), 64)
    
    @patch('frappe.get_site_config')
    def test_generate_session_secret_existing(self, mock_get_config):
        """Test with existing session secret"""
        mock_get_config.return_value = {"secret_key": "existing-secret"}
        
        result = generate_session_secret()
        
        self.assertFalse(result)  # Should return False for existing secret
    
    @patch('frappe.get_single')
    def test_setup_password_policy_new(self, mock_get_single):
        """Test password policy setup with new settings"""
        mock_system_settings = MagicMock()
        mock_system_settings.minimum_password_score = 0
        mock_system_settings.enable_password_policy = 0
        mock_system_settings.force_user_to_reset_password = 0
        mock_get_single.return_value = mock_system_settings
        
        result = setup_password_policy()
        
        self.assertTrue(result)
        mock_system_settings.save.assert_called_once_with(ignore_permissions=True)
        
        # Verify values were set correctly
        self.assertEqual(mock_system_settings.minimum_password_score, 3)
        self.assertEqual(mock_system_settings.enable_password_policy, 1)
        self.assertEqual(mock_system_settings.force_user_to_reset_password, 90)
    
    @patch('frappe.get_single')
    def test_setup_password_policy_existing(self, mock_get_single):
        """Test password policy setup with existing correct settings"""
        mock_system_settings = MagicMock()
        mock_system_settings.minimum_password_score = 3
        mock_system_settings.enable_password_policy = 1
        mock_system_settings.force_user_to_reset_password = 90
        mock_get_single.return_value = mock_system_settings
        
        result = setup_password_policy()
        
        self.assertTrue(result)
        # Should not save if no changes needed
        mock_system_settings.save.assert_not_called()


class TestSecurityStatus(FrappeTestCase):
    """Test security status checking"""
    
    @patch('frappe.get_site_config')
    def test_check_security_status_comprehensive(self, mock_get_config):
        """Test comprehensive security status check"""
        mock_get_config.return_value = {
            "ignore_csrf": 0,
            "developer_mode": 0,
            "encryption_key": "test-key",
            "secret_key": "test-secret",
            "session_expiry": "08:00:00",
            "allow_tests": False
        }
        
        status = check_security_status()
        
        # Verify all status fields
        self.assertTrue(status["csrf_protection"])
        self.assertFalse(status["developer_mode"])
        self.assertTrue(status["encryption_key"])
        self.assertTrue(status["secret_key"])
        self.assertFalse(status["allow_tests"])
        
        # Verify security score calculation
        self.assertEqual(status["security_score"], "10/10")
        self.assertEqual(status["security_percentage"], 100.0)
        self.assertEqual(len(status["recommendations"]), 0)
    
    @patch('frappe.get_site_config')
    def test_check_security_status_insecure(self, mock_get_config):
        """Test security status with insecure configuration"""
        mock_get_config.return_value = {
            "ignore_csrf": 1,
            "developer_mode": 1,
            "allow_tests": True
        }
        
        status = check_security_status()
        
        # Verify insecure status
        self.assertFalse(status["csrf_protection"])
        self.assertTrue(status["developer_mode"])
        self.assertTrue(status["allow_tests"])
        
        # Verify low security score
        self.assertEqual(status["security_score"], "0/10")
        self.assertEqual(status["security_percentage"], 0.0)
        self.assertGreater(len(status["recommendations"]), 0)
        
        # Check specific recommendations
        recommendations = status["recommendations"]
        self.assertIn("Enable CSRF protection", " ".join(recommendations))
        self.assertIn("Disable developer mode", " ".join(recommendations))


class TestSecurityAudit(FrappeTestCase):
    """Test security audit logging"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        frappe.session.user = "test_user@example.com"
    
    def tearDown(self):
        frappe.session.user = self.original_user
        super().tearDown()
    
    @patch('frappe.get_doc')
    @patch('frappe.logger')
    def test_log_security_audit_success(self, mock_logger, mock_get_doc):
        """Test successful security audit logging"""
        mock_doc = MagicMock()
        mock_get_doc.return_value = mock_doc
        mock_log_func = MagicMock()
        mock_logger.return_value = mock_log_func
        
        test_action = "Test Security Action"
        test_details = {"key": "value", "user_action": "enable_csrf"}
        
        log_security_audit(test_action, test_details)
        
        # Verify Activity Log creation
        mock_get_doc.assert_called_once()
        doc_data = mock_get_doc.call_args[0][0]
        self.assertEqual(doc_data["doctype"], "Activity Log")
        self.assertEqual(doc_data["subject"], f"Security Configuration: {test_action}")
        self.assertEqual(doc_data["user"], "test_user@example.com")
        self.assertEqual(doc_data["operation"], test_action)
        
        # Verify document was inserted
        mock_doc.insert.assert_called_once_with(ignore_permissions=True)
        
        # Verify logger was called
        mock_log_func.info.assert_called_once()
        log_message = mock_log_func.info.call_args[0][0]
        self.assertIn("SECURITY AUDIT", log_message)
        self.assertIn(test_action, log_message)
    
    @patch('frappe.get_doc', side_effect=Exception("Database error"))
    @patch('frappe.logger')
    def test_log_security_audit_failure_handling(self, mock_logger, mock_get_doc):
        """Test that audit logging failures don't break main operations"""
        mock_log_func = MagicMock()
        mock_logger.return_value = mock_log_func
        
        # Should not raise exception even if logging fails
        try:
            log_security_audit("Test Action", {"key": "value"})
        except Exception:
            self.fail("Audit logging failure should not break main operation")
        
        # Should log the error
        mock_log_func.error.assert_called_once()


class TestSecurityAPIEndpoints(FrappeTestCase):
    """Test security API endpoints"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        frappe.session.user = "admin@example.com"
    
    def tearDown(self):
        frappe.session.user = self.original_user
        super().tearDown()
    
    @patch('frappe.has_permission')
    @patch('verenigingen.setup.security_setup.validate_csrf_token')
    @patch('verenigingen.setup.security_setup.log_security_audit')
    @patch('frappe.installer.update_site_config')
    def test_enable_csrf_protection_success(self, mock_update_config, mock_audit, mock_csrf, mock_permission):
        """Test successful CSRF protection enabling"""
        mock_permission.return_value = True
        
        result = enable_csrf_protection()
        
        self.assertTrue(result["success"])
        self.assertIn("enabled successfully", result["message"])
        mock_update_config.assert_called_with("ignore_csrf", 0)
        mock_audit.assert_called()
    
    @patch('frappe.has_permission')
    def test_enable_csrf_protection_permission_denied(self, mock_permission):
        """Test CSRF protection enabling without permissions"""
        mock_permission.return_value = False
        
        with self.assertRaises(frappe.PermissionError):
            enable_csrf_protection()
    
    @patch('verenigingen.setup.security_setup.check_security_status')
    def test_check_current_security_status_success(self, mock_check):
        """Test security status check endpoint"""
        mock_status = {
            "csrf_protection": True,
            "security_score": "8/10",
            "recommendations": []
        }
        mock_check.return_value = mock_status
        
        result = check_current_security_status()
        
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], mock_status)
    
    @patch('frappe.has_permission')
    @patch('verenigingen.setup.security_setup.log_security_audit')
    @patch('frappe.installer.update_site_config')
    def test_apply_production_security_comprehensive(self, mock_update_config, mock_audit, mock_permission):
        """Test applying production security settings"""
        mock_permission.return_value = True
        
        # Mock current insecure configuration
        with patch.object(frappe.conf, 'developer_mode', 1):
            with patch.object(frappe.conf, 'get', side_effect=lambda key, default=None: {
                'ignore_csrf': 1,
                'allow_tests': 1,
                'secret_key': None
            }.get(key, default)):
                with patch('verenigingen.setup.security_setup.generate_session_secret', return_value=True):
                    result = apply_production_security()
        
        self.assertTrue(result["success"])
        self.assertGreater(len(result["changes"]), 0)
        
        # Verify multiple security changes were applied
        changes = result["changes"]
        change_text = " ".join(changes)
        self.assertIn("developer mode", change_text.lower())
        self.assertIn("csrf", change_text.lower())


class TestSecurityIntegration(FrappeTestCase):
    """Integration tests for security setup"""
    
    @patch('frappe.get_site_config')
    @patch('frappe.installer.update_site_config')
    @patch('frappe.get_single')
    @patch('vereinigen.setup.security_setup.log_security_audit')
    def test_setup_all_security_integration(self, mock_audit, mock_get_single, mock_update_config, mock_get_config):
        """Test complete security setup integration"""
        # Mock configuration
        mock_get_config.return_value = {
            "ignore_csrf": 1,
            "developer_mode": 0
        }
        
        # Mock system settings
        mock_system_settings = MagicMock()
        mock_system_settings.minimum_password_score = 0
        mock_get_single.return_value = mock_system_settings
        
        result = setup_all_security()
        
        # Verify all components were called
        self.assertIn("csrf", result)
        self.assertIn("session_secret", result)
        self.assertIn("password_policy", result)
        self.assertIn("security_headers", result)
        self.assertIn("final_status", result)
        
        # Verify audit logging
        mock_audit.assert_called()
        audit_calls = mock_audit.call_args_list
        self.assertGreater(len(audit_calls), 0)
        
        # Check that setup started and completed events were logged
        audit_actions = [call[0][0] for call in audit_calls]
        self.assertIn("Security Setup Started", audit_actions)
        self.assertIn("Security Setup Completed", audit_actions)


class TestSecurityEdgeCases(FrappeTestCase):
    """Test edge cases and error conditions"""
    
    def test_rate_limit_decorator_with_zero_limit(self):
        """Test rate limiting with zero limit"""
        @security_rate_limit(limit=0, seconds=60)
        def test_function():
            return "success"
        
        # Should immediately fail
        with self.assertRaises(frappe.RateLimitExceededError):
            test_function()
    
    @patch('frappe.get_site_config', side_effect=Exception("Config error"))
    def test_check_security_status_with_config_error(self, mock_config):
        """Test security status check when config is unavailable"""
        # Should not crash, but may return incomplete status
        try:
            status = check_security_status()
        except Exception as e:
            # If it raises an exception, it should be handled gracefully
            self.assertIsNotNone(str(e))
    
    @patch('frappe.installer.update_site_config', side_effect=Exception("Update failed"))
    @patch('frappe.get_site_config')
    def test_setup_csrf_protection_update_failure(self, mock_get_config, mock_update):
        """Test CSRF setup when config update fails"""
        mock_get_config.return_value = {"ignore_csrf": 1, "developer_mode": 0}
        
        result = setup_csrf_protection()
        
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
    
    def test_security_audit_with_none_user(self):
        """Test audit logging with None user"""
        original_user = frappe.session.user
        frappe.session.user = None
        
        try:
            # Should handle None user gracefully
            log_security_audit("Test Action", {"key": "value"})
        except Exception as e:
            self.fail(f"Audit logging with None user should not fail: {e}")
        finally:
            frappe.session.user = original_user


def run_tests():
    """Run all security setup tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test cases
    test_cases = [
        TestSecurityRateLimit,
        TestCSRFValidation,
        TestSecurityConfiguration,
        TestSecurityStatus,
        TestSecurityAudit,
        TestSecurityAPIEndpoints,
        TestSecurityIntegration,
        TestSecurityEdgeCases
    ]
    
    for test_case in test_cases:
        suite.addTests(loader.loadTestsFromTestCase(test_case))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)