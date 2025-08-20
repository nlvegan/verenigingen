"""
Unit Tests for Security Wrappers

This module provides focused unit tests for the security wrapper functions,
testing specific edge cases and security validation logic in isolation.

Key Testing Areas:
1. Parameter validation logic
2. Security logging functionality  
3. Error handling and recovery
4. Performance characteristics
5. Backward compatibility

Author: Security Team
Date: 2025-08-20
Version: 1.0
"""

import unittest
from unittest.mock import patch, Mock, MagicMock
import logging
from verenigingen.utils.security_wrappers import (
    safe_get_roles,
    safe_has_role, 
    safe_has_any_role,
    _is_valid_user_parameter,
    get_security_audit_info,
    validate_security_wrapper_installation
)


class SecurityWrappersUnitTests(unittest.TestCase):
    """Unit tests for security wrapper functions"""
    
    def setUp(self):
        """Set up test environment"""
        # Mock frappe session
        self.mock_session = Mock()
        self.mock_session.user = "test@example.com"
    
    def test_is_valid_user_parameter(self):
        """Test user parameter validation logic"""
        
        # Valid parameters
        self.assertTrue(_is_valid_user_parameter(None))  # None is valid (current user)
        self.assertTrue(_is_valid_user_parameter("user@example.com"))
        self.assertTrue(_is_valid_user_parameter("Guest"))
        self.assertTrue(_is_valid_user_parameter("Administrator"))
        
        # Invalid parameters
        self.assertFalse(_is_valid_user_parameter(""))  # Empty string
        self.assertFalse(_is_valid_user_parameter("   "))  # Whitespace only
        self.assertFalse(_is_valid_user_parameter("None"))  # String "None"
        self.assertFalse(_is_valid_user_parameter("null"))  # String "null"
        self.assertFalse(_is_valid_user_parameter("undefined"))  # String "undefined"
        self.assertFalse(_is_valid_user_parameter(123))  # Non-string
        self.assertFalse(_is_valid_user_parameter([]))  # Non-string
        self.assertFalse(_is_valid_user_parameter({}))  # Non-string
        self.assertFalse(_is_valid_user_parameter("a" * 300))  # Too long
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    def test_safe_get_roles_valid_user(self, mock_frappe):
        """Test safe_get_roles with valid user parameters"""
        
        # Setup mocks
        mock_frappe.get_roles.return_value = ["Guest", "Member"]
        mock_frappe.session = self.mock_session
        
        # Test with explicit user
        roles = safe_get_roles("test@example.com")
        self.assertEqual(roles, ["Guest", "Member"])
        mock_frappe.get_roles.assert_called_with("test@example.com")
        
        # Test with None (current user)
        roles = safe_get_roles(None)
        self.assertEqual(roles, ["Guest", "Member"])
        mock_frappe.get_roles.assert_called_with("test@example.com")
        
        # Test with Guest user
        roles = safe_get_roles("Guest")
        self.assertEqual(roles, ["Guest"])
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    @patch('verenigingen.utils.security_wrappers.security_logger')
    def test_safe_get_roles_invalid_user(self, mock_logger, mock_frappe):
        """Test safe_get_roles with invalid user parameters"""
        
        mock_frappe.session = self.mock_session
        
        # Test invalid parameters return empty list
        test_cases = ["", "   ", "None", "null", 123, [], {}]
        
        for invalid_user in test_cases:
            roles = safe_get_roles(invalid_user)
            self.assertEqual(roles, [], f"Failed for invalid user: {repr(invalid_user)}")
            
        # Verify warning was logged
        self.assertTrue(mock_logger.warning.called)
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    def test_safe_get_roles_frappe_error(self, mock_frappe):
        """Test safe_get_roles when frappe.get_roles raises exception"""
        
        mock_frappe.session = self.mock_session
        mock_frappe.get_roles.side_effect = Exception("Database error")
        
        # Should return empty list on error
        roles = safe_get_roles("test@example.com")
        self.assertEqual(roles, [])
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    def test_safe_get_roles_invalid_return_type(self, mock_frappe):
        """Test safe_get_roles when frappe.get_roles returns non-list"""
        
        mock_frappe.session = self.mock_session
        mock_frappe.get_roles.return_value = "invalid"  # Not a list
        
        # Should return empty list for invalid return type
        roles = safe_get_roles("test@example.com")
        self.assertEqual(roles, [])
    
    @patch('verenigingen.utils.security_wrappers.safe_get_roles')
    def test_safe_has_role(self, mock_safe_get_roles):
        """Test safe_has_role function"""
        
        mock_safe_get_roles.return_value = ["Guest", "Member", "Volunteer"]
        
        # Test positive case
        self.assertTrue(safe_has_role("test@example.com", "Member"))
        
        # Test negative case
        self.assertFalse(safe_has_role("test@example.com", "Admin"))
        
        # Test invalid role parameter
        self.assertFalse(safe_has_role("test@example.com", ""))
        self.assertFalse(safe_has_role("test@example.com", None))
        self.assertFalse(safe_has_role("test@example.com", 123))
    
    @patch('verenigingen.utils.security_wrappers.safe_has_role')
    def test_safe_has_any_role(self, mock_safe_has_role):
        """Test safe_has_any_role function"""
        
        # Mock safe_has_role to return True for "Member" only
        def mock_has_role_side_effect(user, role):
            return role == "Member"
        
        mock_safe_has_role.side_effect = mock_has_role_side_effect
        
        # Test positive case
        self.assertTrue(safe_has_any_role("test@example.com", ["Admin", "Member", "Guest"]))
        
        # Test negative case
        self.assertFalse(safe_has_any_role("test@example.com", ["Admin", "SuperUser"]))
        
        # Test invalid roles parameter
        self.assertFalse(safe_has_any_role("test@example.com", None))
        self.assertFalse(safe_has_any_role("test@example.com", ""))
        self.assertFalse(safe_has_any_role("test@example.com", 123))
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    @patch('verenigingen.utils.security_wrappers.security_logger')
    def test_administrative_role_logging(self, mock_logger, mock_frappe):
        """Test that administrative role access is logged"""
        
        mock_frappe.session = self.mock_session
        mock_frappe.get_roles.return_value = ["System Manager", "Administrator"]
        
        # Call safe_get_roles
        roles = safe_get_roles("admin@example.com")
        
        # Verify logging was called for admin roles
        mock_logger.info.assert_called()
        log_call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Administrative role access", log_call_args)
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    @patch('verenigingen.utils.security_wrappers.security_logger')
    def test_privileged_role_check_logging(self, mock_logger, mock_frappe):
        """Test that privileged role checks are logged"""
        
        mock_frappe.session = self.mock_session
        
        # Mock safe_get_roles to return admin roles
        with patch('verenigingen.utils.security_wrappers.safe_get_roles') as mock_safe_get_roles:
            mock_safe_get_roles.return_value = ["System Manager"]
            
            # Check privileged role
            result = safe_has_role("admin@example.com", "System Manager")
            self.assertTrue(result)
            
            # Verify privileged role check was logged
            mock_logger.info.assert_called()
            log_call_args = mock_logger.info.call_args[0][0]
            self.assertIn("Privileged role check", log_call_args)
    
    @patch('verenigingen.utils.security_wrappers.frappe')
    def test_get_security_audit_info(self, mock_frappe):
        """Test security audit info function"""
        
        mock_frappe.session = self.mock_session
        mock_frappe.session.sid = "test_session_id"
        
        with patch('verenigingen.utils.security_wrappers.safe_get_roles') as mock_safe_get_roles:
            with patch('verenigingen.utils.security_wrappers.safe_has_any_role') as mock_safe_has_any_role:
                
                mock_safe_get_roles.return_value = ["Guest", "Member"]
                mock_safe_has_any_role.return_value = False
                
                audit_info = get_security_audit_info()
                
                # Verify structure
                self.assertIn("current_user", audit_info)
                self.assertIn("user_roles", audit_info)
                self.assertIn("has_admin_access", audit_info)
                self.assertIn("session_sid", audit_info)
                self.assertIn("is_guest", audit_info)
                
                # Verify values
                self.assertEqual(audit_info["current_user"], "test@example.com")
                self.assertEqual(audit_info["user_roles"], ["Guest", "Member"])
                self.assertFalse(audit_info["has_admin_access"])
                self.assertEqual(audit_info["session_sid"], "test_session_id")
                self.assertFalse(audit_info["is_guest"])
    
    def test_validate_security_wrapper_installation(self):
        """Test security wrapper validation function"""
        
        with patch('verenigingen.utils.security_wrappers.safe_get_roles') as mock_safe_get_roles:
            with patch('verenigingen.utils.security_wrappers.safe_has_role') as mock_safe_has_role:
                with patch('verenigingen.utils.security_wrappers.safe_has_any_role') as mock_safe_has_any_role:
                    
                    # Mock successful validation
                    mock_safe_get_roles.side_effect = [
                        ["Guest"],  # For None parameter
                        [],         # For empty string
                        []          # For "None" string
                    ]
                    mock_safe_has_role.return_value = False
                    mock_safe_has_any_role.return_value = False
                    
                    # Should pass validation
                    result = validate_security_wrapper_installation()
                    self.assertTrue(result)
    
    def test_validate_security_wrapper_installation_failure(self):
        """Test security wrapper validation failure scenarios"""
        
        with patch('verenigingen.utils.security_wrappers.safe_get_roles') as mock_safe_get_roles:
            
            # Mock validation failure
            mock_safe_get_roles.side_effect = Exception("Validation error")
            
            # Should fail validation
            result = validate_security_wrapper_installation()
            self.assertFalse(result)
    
    def test_performance_characteristics(self):
        """Test performance characteristics of security wrappers"""
        
        with patch('verenigingen.utils.security_wrappers.frappe') as mock_frappe:
            mock_frappe.session = self.mock_session
            mock_frappe.get_roles.return_value = ["Guest"]
            
            import time
            
            # Measure performance
            start_time = time.time()
            
            for _ in range(1000):
                safe_get_roles("test@example.com")
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Should be very fast (less than 0.1 seconds for 1000 calls)
            self.assertLess(duration, 0.1, f"Security wrappers too slow: {duration:.3f}s")
    
    def test_backward_compatibility_aliases(self):
        """Test backward compatibility aliases"""
        
        from verenigingen.utils.security_wrappers import get_user_roles, has_user_role
        
        with patch('verenigingen.utils.security_wrappers.safe_get_roles') as mock_safe_get_roles:
            with patch('verenigingen.utils.security_wrappers.safe_has_role') as mock_safe_has_role:
                
                mock_safe_get_roles.return_value = ["Guest"]
                mock_safe_has_role.return_value = True
                
                # Test aliases work
                roles = get_user_roles("test@example.com")
                self.assertEqual(roles, ["Guest"])
                
                has_role = has_user_role("test@example.com", "Guest")
                self.assertTrue(has_role)


if __name__ == "__main__":
    unittest.main()