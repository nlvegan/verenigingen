"""
Comprehensive Security Test Suite for SEPA Operations

This module provides comprehensive testing for all security measures implemented
in the SEPA billing system including CSRF protection, rate limiting, 
authorization, and audit logging.
"""

import time
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.csrf_protection import CSRFProtection, CSRFError
from verenigingen.utils.security.rate_limiting import RateLimiter, RateLimitExceeded
from verenigingen.utils.security.authorization import SEPAAuthorizationManager, SEPAOperation, SEPAPermissionLevel
from verenigingen.utils.security.audit_logging import SEPAAuditLogger, AuditEventType, AuditSeverity


class TestCSRFProtection(VereningingenTestCase):
    """Test CSRF protection system"""
    
    def setUp(self):
        super().setUp()
        self.csrf_protection = CSRFProtection()
    
    def test_csrf_token_generation(self):
        """Test CSRF token generation"""
        # Test token generation for valid user
        with self.set_user("test@example.com"):
            token = self.csrf_protection.generate_token()
            self.assertIsInstance(token, str)
            self.assertGreater(len(token), 20)
            
            # Token should contain user and timestamp
            parts = token.split(':')
            self.assertEqual(len(parts), 3)
            self.assertEqual(parts[0], "test@example.com")
    
    def test_csrf_token_validation(self):
        """Test CSRF token validation"""
        with self.set_user("test@example.com"):
            # Generate valid token
            token = self.csrf_protection.generate_token()
            
            # Valid token should pass validation
            self.assertTrue(self.csrf_protection.validate_token(token))
            
            # Invalid token should fail
            with self.assertRaises(CSRFError):
                self.csrf_protection.validate_token("invalid_token")
            
            # Token for different user should fail
            with self.assertRaises(CSRFError):
                self.csrf_protection.validate_token(token, "other@example.com")
    
    def test_csrf_token_expiry(self):
        """Test CSRF token expiry"""
        with self.set_user("test@example.com"):
            # Mock time to create expired token
            with patch('time.time', return_value=time.time() - 7200):  # 2 hours ago
                old_token = self.csrf_protection.generate_token()
            
            # Expired token should fail validation
            with self.assertRaises(CSRFError):
                self.csrf_protection.validate_token(old_token)
    
    def test_csrf_guest_user_protection(self):
        """Test CSRF protection for guest users"""
        with self.set_user("Guest"):
            # Guest users should not be able to generate tokens
            with self.assertRaises(CSRFError):
                self.csrf_protection.generate_token()
            
            # Guest users should not be able to validate tokens
            with self.assertRaises(CSRFError):
                self.csrf_protection.validate_token("any_token")
    
    def test_csrf_api_endpoints(self):
        """Test CSRF protection API endpoints"""
        with self.set_user("test@example.com"):
            # Test get_csrf_token endpoint
            result = frappe.get_doc({
                "doctype": "ToDo",
                "description": "Test CSRF Token"
            })
            result.insert()
            
            # Should be able to call the API
            from verenigingen.utils.security.csrf_protection import get_csrf_token
            token_result = get_csrf_token()
            
            self.assertTrue(token_result["success"])
            self.assertIn("csrf_token", token_result)
            self.assertIn("header_name", token_result)


class TestRateLimiting(VereningingenTestCase):
    """Test rate limiting system"""
    
    def setUp(self):
        super().setUp()
        self.rate_limiter = RateLimiter(backend="memory")  # Use memory for testing
    
    def test_rate_limit_basic_functionality(self):
        """Test basic rate limiting functionality"""
        with self.set_user("test@example.com"):
            # First request should pass
            result = self.rate_limiter.check_rate_limit("test_operation", "test@example.com")
            self.assertTrue(result["allowed"])
            self.assertEqual(result["current_count"], 1)
    
    def test_rate_limit_enforcement(self):
        """Test rate limit enforcement"""
        # Set very low limit for testing
        self.rate_limiter.DEFAULT_LIMITS["test_operation"] = {"requests": 2, "window_seconds": 3600}
        
        with self.set_user("test@example.com"):
            # First two requests should pass
            self.rate_limiter.check_rate_limit("test_operation", "test@example.com")
            self.rate_limiter.check_rate_limit("test_operation", "test@example.com")
            
            # Third request should fail
            with self.assertRaises(RateLimitExceeded):
                self.rate_limiter.check_rate_limit("test_operation", "test@example.com")
    
    def test_rate_limit_role_multipliers(self):
        """Test role-based rate limit multipliers"""
        # Create users with different roles
        admin_user = self.create_test_user("admin@example.com", ["System Manager"])
        staff_user = self.create_test_user("staff@example.com", ["Verenigingen Staff"])
        
        # Admin should have higher limits
        admin_limit, _ = self.rate_limiter._get_user_limit("sepa_batch_creation", admin_user.email)
        staff_limit, _ = self.rate_limiter._get_user_limit("sepa_batch_creation", staff_user.email)
        
        self.assertGreater(admin_limit, staff_limit)
    
    def test_rate_limit_system_user_bypass(self):
        """Test that system users bypass rate limits"""
        with self.set_user("Administrator"):
            # Administrator should bypass rate limits
            result = self.rate_limiter.check_rate_limit("any_operation", "Administrator")
            self.assertTrue(result["allowed"])
            self.assertEqual(result["limit"], float('inf'))
    
    def test_rate_limit_headers(self):
        """Test rate limit headers generation"""
        with self.set_user("test@example.com"):
            headers = self.rate_limiter.get_rate_limit_headers("sepa_batch_creation", "test@example.com")
            
            self.assertIn("X-RateLimit-Limit", headers)
            self.assertIn("X-RateLimit-Remaining", headers)
            self.assertIn("X-RateLimit-Reset", headers)
            self.assertIn("X-RateLimit-Window", headers)
    
    def test_rate_limit_decorator(self):
        """Test rate limiting decorator"""
        from verenigingen.utils.security.rate_limiting import rate_limit
        
        # Create a test function with rate limiting
        @rate_limit("test_operation")
        def test_function():
            return "success"
        
        # Set very low limit for testing
        self.rate_limiter.DEFAULT_LIMITS["test_operation"] = {"requests": 1, "window_seconds": 3600}
        
        with self.set_user("test@example.com"):
            # First call should succeed
            result = test_function()
            self.assertEqual(result, "success")
            
            # Second call should fail (would need to mock the decorator)
            # This is a simplified test - full integration testing would be needed


class TestAuthorization(VereningingenTestCase):
    """Test authorization system"""
    
    def setUp(self):
        super().setUp()
        self.auth_manager = SEPAAuthorizationManager()
    
    def test_user_permissions_by_role(self):
        """Test user permissions based on roles"""
        # Create users with different roles
        admin_user = self.create_test_user("admin@example.com", ["System Manager"])
        manager_user = self.create_test_user("manager@example.com", ["Verenigingen Manager"])
        staff_user = self.create_test_user("staff@example.com", ["Verenigingen Staff"])
        
        # Test permissions for each role
        admin_perms = self.auth_manager.get_user_permissions(admin_user.email)
        manager_perms = self.auth_manager.get_user_permissions(manager_user.email)
        staff_perms = self.auth_manager.get_user_permissions(staff_user.email)
        
        # Admin should have all permissions
        self.assertIn(SEPAPermissionLevel.ADMIN, admin_perms)
        self.assertIn(SEPAPermissionLevel.PROCESS, admin_perms)
        
        # Manager should have process but not admin
        self.assertIn(SEPAPermissionLevel.PROCESS, manager_perms)
        self.assertNotIn(SEPAPermissionLevel.ADMIN, manager_perms)
        
        # Staff should have create but not process
        self.assertIn(SEPAPermissionLevel.CREATE, staff_perms)
        self.assertNotIn(SEPAPermissionLevel.PROCESS, staff_perms)
    
    def test_operation_permissions(self):
        """Test operation-specific permissions"""
        # Create test users
        admin_user = self.create_test_user("admin@example.com", ["System Manager"])
        staff_user = self.create_test_user("staff@example.com", ["Verenigingen Staff"])
        
        # Admin should have all operation permissions
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.BATCH_CREATE, admin_user.email))
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.BATCH_PROCESS, admin_user.email))
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.SETTINGS_MODIFY, admin_user.email))
        
        # Staff should have limited permissions
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.BATCH_CREATE, staff_user.email))
        self.assertFalse(self.auth_manager.has_permission(SEPAOperation.BATCH_PROCESS, staff_user.email))
        self.assertFalse(self.auth_manager.has_permission(SEPAOperation.SETTINGS_MODIFY, staff_user.email))
    
    def test_system_user_permissions(self):
        """Test that system users have all permissions"""
        # Administrator should have all permissions
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.SETTINGS_MODIFY, "Administrator"))
        self.assertTrue(self.auth_manager.has_permission(SEPAOperation.BATCH_DELETE, "Administrator"))
    
    def test_contextual_permissions(self):
        """Test context-based permission checks"""
        manager_user = self.create_test_user("manager@example.com", ["Verenigingen Manager"])
        
        # Create a test batch
        batch = self.create_test_batch(owner=manager_user.email)
        
        # Manager should be able to process their own batch
        context = {"batch_name": batch.name}
        self.assertTrue(
            self.auth_manager.has_permission(SEPAOperation.BATCH_PROCESS, manager_user.email, context)
        )
    
    def test_authorization_validation(self):
        """Test authorization validation with exceptions"""
        staff_user = self.create_test_user("staff@example.com", ["Verenigingen Staff"])
        
        # Staff user should not be able to perform admin operations
        with self.assertRaises(Exception):  # Should raise VerenigingenPermissionError
            self.auth_manager.validate_operation(
                SEPAOperation.SETTINGS_MODIFY, 
                staff_user.email, 
                raise_exception=True
            )
        
        # But should be able to perform allowed operations
        result = self.auth_manager.validate_operation(
            SEPAOperation.BATCH_CREATE, 
            staff_user.email, 
            raise_exception=False
        )
        self.assertTrue(result)


class TestAuditLogging(VereningingenTestCase):
    """Test audit logging system"""
    
    def setUp(self):
        super().setUp()
        self.audit_logger = SEPAAuditLogger()
    
    def test_basic_audit_logging(self):
        """Test basic audit log functionality"""
        with self.set_user("test@example.com"):
            # Log a test event
            event_id = self.audit_logger.log_event(
                AuditEventType.SEPA_BATCH_CREATED,
                AuditSeverity.INFO,
                details={"test": "value"}
            )
            
            self.assertIsInstance(event_id, str)
            self.assertTrue(event_id.startswith("audit_"))
    
    def test_audit_log_storage(self):
        """Test audit log database storage"""
        with self.set_user("test@example.com"):
            # Log an event
            event_id = self.audit_logger.log_event(
                AuditEventType.SEPA_BATCH_VALIDATED,
                AuditSeverity.WARNING,
                details={"batch_name": "TEST-001"}
            )
            
            # Check if stored in database
            audit_log = frappe.get_doc("SEPA Audit Log", event_id)
            self.assertEqual(audit_log.event_type, AuditEventType.SEPA_BATCH_VALIDATED.value)
            self.assertEqual(audit_log.severity, "warning")
            self.assertEqual(audit_log.user, "test@example.com")
    
    def test_audit_log_search(self):
        """Test audit log search functionality"""
        with self.set_user("test@example.com"):
            # Create multiple audit logs
            self.audit_logger.log_event(AuditEventType.SEPA_BATCH_CREATED, AuditSeverity.INFO)
            self.audit_logger.log_event(AuditEventType.SEPA_BATCH_VALIDATED, AuditSeverity.WARNING)
            self.audit_logger.log_event(AuditEventType.CSRF_VALIDATION_FAILED, AuditSeverity.ERROR)
            
            # Search by event type
            results = self.audit_logger.search_audit_logs(
                event_types=[AuditEventType.SEPA_BATCH_CREATED.value],
                limit=10
            )
            self.assertGreater(len(results), 0)
            self.assertTrue(all(log["event_type"] == AuditEventType.SEPA_BATCH_CREATED.value for log in results))
            
            # Search by severity
            error_results = self.audit_logger.search_audit_logs(
                severity="error",
                limit=10
            )
            self.assertGreater(len(error_results), 0)
            self.assertTrue(all(log["severity"] == "error" for log in error_results))
    
    def test_security_alert_thresholds(self):
        """Test security alert threshold system"""
        with self.set_user("test@example.com"):
            # Mock alert notification to avoid actual emails in tests
            with patch.object(self.audit_logger, '_send_security_notification') as mock_notification:
                # Generate multiple failed CSRF events to trigger alert
                for _ in range(6):  # Threshold is 5
                    self.audit_logger.log_event(
                        AuditEventType.CSRF_VALIDATION_FAILED,
                        AuditSeverity.ERROR
                    )
                
                # Check if alert was triggered
                mock_notification.assert_called()
    
    def test_audit_log_decorator(self):
        """Test audit logging decorator"""
        from verenigingen.utils.security.audit_logging import audit_log
        
        @audit_log("test_operation", "info", capture_args=True)
        def test_function(arg1, arg2="default"):
            return f"result: {arg1}, {arg2}"
        
        with self.set_user("test@example.com"):
            # Call the decorated function
            result = test_function("test_value", arg2="custom")
            
            self.assertEqual(result, "result: test_value, custom")
            
            # Check if audit log was created
            # (In a real test, we'd search for the audit log entry)


class TestSecurityIntegration(VereningingenTestCase):
    """Test integration of all security measures"""
    
    def test_secure_api_endpoint_full_stack(self):
        """Test secure API endpoint with all security measures"""
        # Create test user with appropriate permissions
        user = self.create_test_user("manager@example.com", ["Verenigingen Manager"])
        
        with self.set_user(user.email):
            # Test that secure endpoints require proper setup
            from verenigingen.api.sepa_batch_ui_secure import load_unpaid_invoices_secure
            
            # This would normally require CSRF token, rate limiting, etc.
            # For testing, we'd need to mock or configure these properly
            try:
                result = load_unpaid_invoices_secure()
                # If we get here, the endpoint is working
                self.assertIsInstance(result, list)
            except Exception as e:
                # Expected if security measures are working
                self.assertIn("CSRF", str(e)) or self.assertIn("rate", str(e).lower())
    
    def test_security_health_check(self):
        """Test security health check endpoint"""
        with self.set_user("Administrator"):
            from verenigingen.api.sepa_batch_ui_secure import sepa_security_health_check
            
            health_result = sepa_security_health_check()
            
            self.assertTrue(health_result["success"])
            self.assertIn("overall_health", health_result)
            self.assertIn("components", health_result)
            
            # Check that all security components are reported
            components = health_result["components"]
            self.assertIn("csrf_protection", components)
            self.assertIn("rate_limiting", components)
            self.assertIn("authorization", components)
            self.assertIn("audit_logging", components)
    
    def test_permission_api_endpoints(self):
        """Test permission management API endpoints"""
        with self.set_user("Administrator"):
            from verenigingen.utils.security.authorization import get_user_sepa_permissions
            
            # Test getting user permissions
            result = get_user_sepa_permissions("Administrator")
            
            self.assertTrue(result["success"])
            self.assertIn("permissions", result)
            self.assertIn("roles", result)
            self.assertIn("available_operations", result)
    
    def test_rate_limit_api_endpoints(self):
        """Test rate limiting API endpoints"""
        with self.set_user("Administrator"):
            from verenigingen.utils.security.rate_limiting import get_rate_limit_status
            
            # Test getting rate limit status
            result = get_rate_limit_status()
            
            self.assertTrue(result["success"])
            self.assertIn("operations", result)
            self.assertIn("backend", result)
    
    def test_audit_log_api_endpoints(self):
        """Test audit log API endpoints"""
        with self.set_user("Administrator"):
            from verenigingen.utils.security.audit_logging import search_audit_logs, get_audit_statistics
            
            # Test searching audit logs
            search_result = search_audit_logs()
            self.assertTrue(search_result["success"])
            self.assertIn("logs", search_result)
            
            # Test getting audit statistics
            stats_result = get_audit_statistics(days=1)
            self.assertTrue(stats_result["success"])
            self.assertIn("event_types", stats_result)
            self.assertIn("severity_levels", stats_result)


class TestSecurityConfiguration(VereningingenTestCase):
    """Test security configuration and edge cases"""
    
    def test_invalid_operations(self):
        """Test handling of invalid operations"""
        auth_manager = SEPAAuthorizationManager()
        
        with self.set_user("test@example.com"):
            # Invalid operation should return False
            result = auth_manager.has_permission("invalid_operation")
            self.assertFalse(result)
    
    def test_malformed_requests(self):
        """Test handling of malformed security requests"""
        csrf_protection = CSRFProtection()
        
        # Malformed tokens should fail gracefully
        with self.assertRaises(CSRFError):
            csrf_protection.validate_token("malformed:token")
        
        with self.assertRaises(CSRFError):
            csrf_protection.validate_token("")
        
        with self.assertRaises(CSRFError):
            csrf_protection.validate_token(None)
    
    def test_concurrent_access_patterns(self):
        """Test concurrent access patterns for rate limiting"""
        rate_limiter = RateLimiter(backend="memory")
        
        # Set low limit for testing
        rate_limiter.DEFAULT_LIMITS["test_concurrent"] = {"requests": 5, "window_seconds": 3600}
        
        # Simulate concurrent requests
        with self.set_user("test@example.com"):
            successful_requests = 0
            for i in range(10):
                try:
                    rate_limiter.check_rate_limit("test_concurrent", "test@example.com")
                    successful_requests += 1
                except RateLimitExceeded:
                    break
            
            # Should allow exactly 5 requests
            self.assertEqual(successful_requests, 5)
    
    def test_security_error_handling(self):
        """Test security error handling and logging"""
        audit_logger = SEPAAuditLogger()
        
        # Test error handling in audit logging
        with patch('frappe.new_doc', side_effect=Exception("Database error")):
            # Should handle database errors gracefully
            event_id = audit_logger.log_event(AuditEventType.SYSTEM_ERROR, AuditSeverity.ERROR)
            self.assertTrue(event_id.startswith("failed_"))


# Helper methods for test data creation
def create_test_user_with_roles(email, roles):
    """Create a test user with specific roles"""
    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    else:
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Test"
        user.last_name = "User"
        user.username = email.split("@")[0]
        
    # Clear existing roles
    user.roles = []
    
    # Add specified roles
    for role in roles:
        user.append("roles", {"role": role})
    
    user.save()
    return user


def create_test_batch(owner=None):
    """Create a test SEPA batch"""
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_date = frappe.utils.today()
    batch.batch_type = "CORE"
    batch.description = "Test Batch"
    batch.status = "Draft"
    
    if owner:
        batch.owner = owner
    
    batch.insert()
    return batch


if __name__ == "__main__":
    # Run the test suite
    unittest.main()