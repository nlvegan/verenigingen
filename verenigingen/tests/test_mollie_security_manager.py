"""
Comprehensive Tests for Mollie Security Manager

Tests the security manager functionality including:
- Encryption key creation and storage for Single DocTypes (critical bug fix)
- API key rotation with zero downtime
- Webhook signature validation
- Security audit logging
"""

import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import frappe
from cryptography.fernet import Fernet
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.test_mollie_api_data_factory import MollieApiDataFactory
from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
    MollieSecurityManager,
    SecurityException
)


class TestMollieSecurityManager(FrappeTestCase):
    """
    Test suite for Mollie Security Manager
    
    Focuses on testing the critical fixes:
    1. Encryption key storage for Single DocTypes
    2. API key rotation mechanisms
    3. Webhook signature validation
    4. Security audit trail
    """
    
    def setUp(self):
        """Set up test environment"""
        self.factory = MollieApiDataFactory(seed=42)
        
        # Mock Mollie Settings
        self.mock_settings = Mock()
        self.mock_settings.name = "Mollie Settings"
        self.mock_settings.get_password = Mock()
        self.mock_settings.db_set = Mock()
        
        # Create security manager instance
        self.security_manager = MollieSecurityManager(self.mock_settings)
    
    def test_encryption_key_creation_for_single_doctype(self):
        """Test encryption key creation and storage for Single DocType (critical bug fix)"""
        # Mock no existing encryption key
        self.mock_settings.get_password.return_value = None
        
        # Mock frappe.db.set_value for Single DocType
        with patch('frappe.db.set_value') as mock_set_value, \
             patch('frappe.db.commit') as mock_commit:
            
            # Create security manager (should generate new key)
            security_manager = MollieSecurityManager(self.mock_settings)
            
            # Should have attempted to store encryption key using proper method
            mock_set_value.assert_called_once()
            call_args = mock_set_value.call_args[0]
            
            # Should use correct parameters for Single DocType
            self.assertEqual(call_args[0], "Mollie Settings")  # DocType
            self.assertIsNone(call_args[1])  # None for Single DocType
            self.assertEqual(call_args[2], "encryption_key")  # Field name
            
            # Should commit the transaction
            mock_commit.assert_called_once()
    
    def test_encryption_key_fallback_mechanism(self):
        """Test fallback encryption key mechanism when storage fails"""
        # Mock no existing encryption key
        self.mock_settings.get_password.return_value = None
        
        # Mock frappe.db.set_value to raise exception (storage failure)
        with patch('frappe.db.set_value', side_effect=Exception("Database error")), \
             patch('frappe.log_error') as mock_log_error, \
             patch('frappe.local.conf', {'secret_key': 'test_site_secret'}):
            
            # Create security manager (should use fallback key)
            security_manager = MollieSecurityManager(self.mock_settings)
            
            # Should have logged the error
            mock_log_error.assert_called_once()
            
            # Should still have a valid encryption key
            self.assertIsNotNone(security_manager.encryption_key)
            self.assertIsInstance(security_manager.encryption_key, bytes)
    
    def test_encrypt_decrypt_sensitive_data(self):
        """Test encryption and decryption of sensitive data"""
        # Mock existing encryption key
        test_key = base64.urlsafe_b64encode(Fernet.generate_key()).decode('utf-8')
        self.mock_settings.get_password.return_value = test_key
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Test data
        sensitive_data = "test_api_key_12345"
        
        # Encrypt data
        encrypted = security_manager.encrypt_sensitive_data(sensitive_data)
        
        # Should return encrypted string
        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(encrypted, sensitive_data)
        
        # Decrypt data
        decrypted = security_manager.decrypt_sensitive_data(encrypted)
        
        # Should match original data
        self.assertEqual(decrypted, sensitive_data)
    
    def test_encrypt_empty_data_handling(self):
        """Test encryption handling of empty or None data"""
        # Test empty string
        encrypted_empty = self.security_manager.encrypt_sensitive_data("")
        self.assertEqual(encrypted_empty, "")
        
        # Test None
        encrypted_none = self.security_manager.encrypt_sensitive_data(None)
        self.assertEqual(encrypted_none, "")
        
        # Test decryption of empty data
        decrypted_empty = self.security_manager.decrypt_sensitive_data("")
        self.assertEqual(decrypted_empty, "")
    
    def test_webhook_signature_validation_success(self):
        """Test successful webhook signature validation"""
        # Create test webhook data
        webhook_data = self.factory.generate_webhook_payload()
        payload = webhook_data["payload"]
        webhook_secret = "test_webhook_secret_123"
        
        # Calculate correct signature
        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        # Mock webhook secret
        self.mock_settings.get_password.return_value = webhook_secret
        
        # Mock audit log creation
        with patch.object(self.security_manager, '_create_audit_log') as mock_audit:
            # Validate signature
            result = self.security_manager.validate_webhook_signature(payload, expected_signature)
            
            # Should return True
            self.assertTrue(result)
            
            # Should create audit log
            mock_audit.assert_called_once_with(
                "WEBHOOK_VALIDATED", 
                "success", 
                {"signature": expected_signature[:20] + "..."}
            )
    
    def test_webhook_signature_validation_failure(self):
        """Test webhook signature validation with invalid signature"""
        payload = '{"resource": "payment", "id": "tr_test123"}'
        invalid_signature = "invalid_signature_123"
        webhook_secret = "test_webhook_secret_123"
        
        # Mock webhook secret
        self.mock_settings.get_password.return_value = webhook_secret
        
        # Mock security alert creation
        with patch.object(self.security_manager, '_create_security_alert') as mock_alert:
            # Should raise SecurityException
            with self.assertRaises(SecurityException) as context:
                self.security_manager.validate_webhook_signature(payload, invalid_signature)
            
            # Should contain appropriate error message
            self.assertIn("signature validation failed", str(context.exception).lower())
            
            # Should create security alert
            mock_alert.assert_called_with(
                "WEBHOOK_SIGNATURE_INVALID", 
                "critical", 
                f"Received: {invalid_signature[:20]}..."
            )
    
    def test_webhook_timestamp_validation(self):
        """Test webhook timestamp validation for replay attack prevention"""
        # Create recent timestamp
        recent_timestamp = datetime.now().isoformat()
        
        # Should pass validation
        with patch('frappe.utils.get_datetime', return_value=datetime.fromisoformat(recent_timestamp)), \
             patch('frappe.utils.now_datetime', return_value=datetime.now()):
            
            result = self.security_manager._validate_webhook_timestamp(recent_timestamp)
            self.assertTrue(result)
        
        # Create old timestamp (replay attack)
        old_timestamp = (datetime.now() - timedelta(minutes=10)).isoformat()
        
        # Should fail validation
        with patch('frappe.utils.get_datetime', return_value=datetime.fromisoformat(old_timestamp)), \
             patch('frappe.utils.now_datetime', return_value=datetime.now()):
            
            result = self.security_manager._validate_webhook_timestamp(old_timestamp)
            self.assertFalse(result)
    
    def test_api_key_rotation_success(self):
        """Test successful API key rotation with zero downtime"""
        current_key = "test_current_key_123"
        new_key = "test_new_key_456"
        
        # Mock current and pending keys
        def mock_get_password(field, raise_exception=True):
            if field == "secret_key":
                return current_key
            elif field == "secret_key_pending":
                return new_key
            return None
        
        self.mock_settings.get_password.side_effect = mock_get_password
        
        # Mock API connectivity test
        with patch.object(self.security_manager, '_test_api_connectivity', return_value=True) as mock_test, \
             patch('frappe.db.set_value') as mock_set_value, \
             patch('frappe.utils.now', return_value="2025-08-18 12:00:00"), \
             patch('frappe.utils.add_days', return_value="2025-08-19 12:00:00"), \
             patch.object(self.security_manager, '_schedule_fallback_cleanup') as mock_schedule, \
             patch.object(self.security_manager, '_create_audit_log') as mock_audit:
            
            # Perform rotation
            result = self.security_manager.rotate_api_keys()
            
            # Should test new key connectivity
            mock_test.assert_called_once_with(new_key)
            
            # Should update database values
            self.assertGreater(mock_set_value.call_count, 0)
            
            # Should schedule fallback cleanup
            mock_schedule.assert_called_once()
            
            # Should create audit log
            mock_audit.assert_called_once_with(
                "API_KEY_ROTATION", 
                "success", 
                {"rotation_date": "2025-08-18 12:00:00"}
            )
            
            # Should return success status
            self.assertEqual(result["status"], "success")
            self.assertIn("rotation_date", result)
    
    def test_api_key_rotation_failure(self):
        """Test API key rotation failure handling"""
        current_key = "test_current_key_123"
        new_key = "test_invalid_key_456"
        
        # Mock current and pending keys
        def mock_get_password(field, raise_exception=True):
            if field == "secret_key":
                return current_key
            elif field == "secret_key_pending":
                return new_key
            return None
        
        self.mock_settings.get_password.side_effect = mock_get_password
        
        # Mock API connectivity test to fail
        with patch.object(self.security_manager, '_test_api_connectivity', return_value=False), \
             patch('frappe.db.set_value') as mock_set_value, \
             patch.object(self.security_manager, '_create_audit_log') as mock_audit, \
             patch.object(self.security_manager, '_create_security_alert') as mock_alert:
            
            # Should raise SecurityException
            with self.assertRaises(SecurityException) as context:
                self.security_manager.rotate_api_keys()
            
            # Should contain appropriate error message
            self.assertIn("validation failed", str(context.exception))
            
            # Should rollback fallback key
            fallback_calls = [call for call in mock_set_value.call_args_list 
                             if len(call[0]) >= 3 and call[0][2] == "secret_key_fallback" and call[0][3] == ""]
            self.assertGreater(len(fallback_calls), 0)
            
            # Should create audit log and security alert
            mock_audit.assert_called()
            mock_alert.assert_called()
    
    def test_api_connectivity_test(self):
        """Test API connectivity testing with Mollie client"""
        test_api_key = "test_api_key_123"
        
        # Mock Mollie client
        with patch('mollie.api.client.Client') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.set_api_key = Mock()
            mock_client.methods.list = Mock(return_value=["ideal", "creditcard"])
            
            # Test successful connectivity
            result = self.security_manager._test_api_connectivity(test_api_key)
            
            # Should set API key and test connection
            mock_client.set_api_key.assert_called_once_with(test_api_key)
            mock_client.methods.list.assert_called_once()
            
            # Should return True for successful test
            self.assertTrue(result)
    
    def test_api_connectivity_test_failure(self):
        """Test API connectivity test with connection failure"""
        test_api_key = "invalid_api_key"
        
        # Mock Mollie client to raise exception
        with patch('mollie.api.client.Client') as mock_client_class, \
             patch('frappe.log_error') as mock_log_error:
            
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            mock_client.set_api_key = Mock()
            mock_client.methods.list.side_effect = Exception("API Error: Unauthorized")
            
            # Test failed connectivity
            result = self.security_manager._test_api_connectivity(test_api_key)
            
            # Should return False for failed test
            self.assertFalse(result)
            
            # Should log the error
            mock_log_error.assert_called_once()
    
    def test_security_alert_creation(self):
        """Test security alert creation and notification"""
        alert_type = "TEST_ALERT"
        severity = "critical"
        details = "Test security incident"
        
        # Mock system managers
        with patch('frappe.log_error') as mock_log_error, \
             patch('frappe.utils.user.get_system_managers', return_value=["admin@test.com"]), \
             patch('frappe.sendmail') as mock_sendmail, \
             patch('frappe.utils.now', return_value="2025-08-18 12:00:00"), \
             patch('frappe.local.site', "test.site.com"):
            
            # Create security alert
            self.security_manager._create_security_alert(alert_type, severity, details)
            
            # Should log error
            mock_log_error.assert_called_once()
            log_message = mock_log_error.call_args[0][0]
            self.assertIn(alert_type, log_message)
            self.assertIn(severity, log_message)
            self.assertIn(details, log_message)
            
            # Should send email for critical alerts
            mock_sendmail.assert_called_once()
            email_args = mock_sendmail.call_args[1]
            self.assertIn("admin@test.com", email_args["recipients"])
            self.assertIn(alert_type, email_args["subject"])
    
    def test_audit_log_creation(self):
        """Test security audit log creation"""
        action = "TEST_ACTION"
        status = "success"
        details = {"test": "data"}
        
        # Mock audit log DocType exists
        with patch('frappe.db.exists', return_value=True), \
             patch('frappe.new_doc') as mock_new_doc, \
             patch('frappe.session.user', "test@user.com"), \
             patch('frappe.utils.now', return_value="2025-08-18 12:00:00"), \
             patch.object(self.security_manager, '_calculate_integrity_hash', return_value="test_hash"):
            
            # Mock audit log document
            mock_audit_doc = Mock()
            mock_new_doc.return_value = mock_audit_doc
            mock_audit_doc.update = Mock()
            mock_audit_doc.insert = Mock()
            
            # Create audit log
            self.security_manager._create_audit_log(action, status, details)
            
            # Should create new audit log document
            mock_new_doc.assert_called_once_with("Mollie Audit Log")
            
            # Should update with correct data
            mock_audit_doc.update.assert_called_once()
            update_data = mock_audit_doc.update.call_args[0][0]
            self.assertEqual(update_data["action"], action)
            self.assertEqual(update_data["status"], status)
            self.assertEqual(update_data["details"], json.dumps(details))
            self.assertEqual(update_data["user"], "test@user.com")
            
            # Should insert with system permissions
            self.assertTrue(mock_audit_doc.flags.ignore_permissions)
            mock_audit_doc.insert.assert_called_once()
    
    def test_integrity_hash_calculation(self):
        """Test integrity hash calculation for audit logs"""
        # Mock audit log document
        mock_audit_log = Mock()
        mock_audit_log.action = "TEST_ACTION"
        mock_audit_log.status = "success"
        mock_audit_log.details = '{"test": "data"}'
        mock_audit_log.timestamp = "2025-08-18 12:00:00"
        mock_audit_log.user = "test@user.com"
        
        # Calculate hash
        hash_result = self.security_manager._calculate_integrity_hash(mock_audit_log)
        
        # Should return SHA256 hash
        self.assertIsInstance(hash_result, str)
        self.assertEqual(len(hash_result), 64)  # SHA256 hex length
        
        # Should be deterministic
        hash_result2 = self.security_manager._calculate_integrity_hash(mock_audit_log)
        self.assertEqual(hash_result, hash_result2)


class TestMollieSecurityManagerEdgeCases(FrappeTestCase):
    """
    Test edge cases and error scenarios for Mollie Security Manager
    """
    
    def setUp(self):
        """Set up edge case test environment"""
        self.factory = MollieApiDataFactory(seed=43)
        
        # Mock settings
        self.mock_settings = Mock()
        self.mock_settings.name = "Mollie Settings"
        self.mock_settings.get_password = Mock()
    
    def test_webhook_validation_missing_secret(self):
        """Test webhook validation when webhook secret is not configured"""
        # Mock no webhook secret
        self.mock_settings.get_password.return_value = None
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Mock security alert creation
        with patch.object(security_manager, '_create_security_alert') as mock_alert, \
             patch('frappe.log_error') as mock_log_error:
            
            # Should raise SecurityException
            with self.assertRaises(SecurityException) as context:
                security_manager.validate_webhook_signature("payload", "signature")
            
            # Should contain appropriate error message
            self.assertIn("not configured", str(context.exception))
            
            # Should create security alert
            mock_alert.assert_called_with("WEBHOOK_SECRET_MISSING", "critical")
            
            # Should log error
            mock_log_error.assert_called_once()
    
    def test_api_key_rotation_no_current_key(self):
        """Test API key rotation when no current key exists"""
        # Mock no current key
        self.mock_settings.get_password.return_value = None
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Should raise SecurityException
        with self.assertRaises(SecurityException) as context:
            security_manager.rotate_api_keys()
        
        # Should contain appropriate error message
        self.assertIn("No current API key found", str(context.exception))
    
    def test_api_key_rotation_no_pending_key(self):
        """Test API key rotation when no pending key exists"""
        # Mock current key but no pending key
        def mock_get_password(field, raise_exception=True):
            if field == "secret_key":
                return "current_key"
            elif field == "secret_key_pending":
                return None
            return None
        
        self.mock_settings.get_password.side_effect = mock_get_password
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Mock database operations
        with patch('frappe.db.set_value'), \
             patch('frappe.utils.now', return_value="2025-08-18 12:00:00"):
            
            # Should raise SecurityException
            with self.assertRaises(SecurityException) as context:
                security_manager.rotate_api_keys()
            
            # Should contain appropriate error message
            self.assertIn("No pending API key found", str(context.exception))
    
    def test_encryption_with_invalid_data_types(self):
        """Test encryption with various data types"""
        # Mock encryption key
        test_key = base64.urlsafe_b64encode(Fernet.generate_key()).decode('utf-8')
        self.mock_settings.get_password.return_value = test_key
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Test with integer
        encrypted_int = security_manager.encrypt_sensitive_data(12345)
        decrypted_int = security_manager.decrypt_sensitive_data(encrypted_int)
        self.assertEqual(decrypted_int, "12345")
        
        # Test with float
        encrypted_float = security_manager.encrypt_sensitive_data(123.45)
        decrypted_float = security_manager.decrypt_sensitive_data(encrypted_float)
        self.assertEqual(decrypted_float, "123.45")
        
        # Test with boolean
        encrypted_bool = security_manager.encrypt_sensitive_data(True)
        decrypted_bool = security_manager.decrypt_sensitive_data(encrypted_bool)
        self.assertEqual(decrypted_bool, "True")
    
    def test_decrypt_invalid_data(self):
        """Test decryption with invalid encrypted data"""
        # Mock encryption key
        test_key = base64.urlsafe_b64encode(Fernet.generate_key()).decode('utf-8')
        self.mock_settings.get_password.return_value = test_key
        
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Test with invalid encrypted data
        with patch('frappe.log_error') as mock_log_error:
            with self.assertRaises(SecurityException) as context:
                security_manager.decrypt_sensitive_data("invalid_encrypted_data")
            
            # Should contain appropriate error message
            self.assertIn("Failed to decrypt data", str(context.exception))
            
            # Should log error
            mock_log_error.assert_called_once()
    
    def test_audit_log_creation_when_doctype_missing(self):
        """Test audit log creation when DocType doesn't exist yet"""
        security_manager = MollieSecurityManager(self.mock_settings)
        
        # Mock DocType doesn't exist
        with patch('frappe.db.exists', return_value=False), \
             patch('frappe.log_error') as mock_log_error:
            
            # Should not raise exception, but log error
            security_manager._create_audit_log("TEST_ACTION", "success")
            
            # Should log error about missing DocType
            mock_log_error.assert_called_once()
            log_message = mock_log_error.call_args[0][0]
            self.assertIn("DocType not created yet", log_message)


class TestMollieSecurityManagerFallbackCleanup(FrappeTestCase):
    """
    Test the fallback key cleanup functionality
    """
    
    def test_cleanup_fallback_key_expired(self):
        """Test cleanup of expired fallback key"""
        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import cleanup_fallback_key
        
        # Mock expired fallback key
        expired_time = datetime.now() - timedelta(hours=25)  # Expired
        
        mock_settings = Mock()
        mock_settings.fallback_key_expiry = expired_time.isoformat()
        
        with patch('frappe.get_single', return_value=mock_settings), \
             patch('frappe.db.set_value') as mock_set_value, \
             patch('frappe.utils.get_datetime', return_value=expired_time), \
             patch('frappe.utils.now_datetime', return_value=datetime.now()), \
             patch('verenigingen.verenigingen_payments.core.security.mollie_security_manager.MollieSecurityManager') as mock_security_class:
            
            mock_security_manager = Mock()
            mock_security_class.return_value = mock_security_manager
            
            # Run cleanup
            cleanup_fallback_key()
            
            # Should clear fallback key
            mock_set_value.assert_any_call("Mollie Settings", None, "secret_key_fallback", "")
            
            # Should create audit log
            mock_security_manager._create_audit_log.assert_called_once_with(
                "FALLBACK_KEY_CLEANUP", "success"
            )
    
    def test_cleanup_fallback_key_not_expired(self):
        """Test that non-expired fallback key is not cleaned up"""
        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import cleanup_fallback_key
        
        # Mock non-expired fallback key
        future_time = datetime.now() + timedelta(hours=5)  # Not expired
        
        mock_settings = Mock()
        mock_settings.fallback_key_expiry = future_time.isoformat()
        
        with patch('frappe.get_single', return_value=mock_settings), \
             patch('frappe.db.set_value') as mock_set_value, \
             patch('frappe.utils.get_datetime', return_value=future_time), \
             patch('frappe.utils.now_datetime', return_value=datetime.now()):
            
            # Run cleanup
            cleanup_fallback_key()
            
            # Should not clear fallback key
            mock_set_value.assert_not_called()
    
    def test_cleanup_fallback_key_error_handling(self):
        """Test error handling in fallback key cleanup"""
        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import cleanup_fallback_key
        
        # Mock exception during cleanup
        with patch('frappe.get_single', side_effect=Exception("Database error")), \
             patch('frappe.log_error') as mock_log_error:
            
            # Should not raise exception
            cleanup_fallback_key()
            
            # Should log error
            mock_log_error.assert_called_once()
            log_message = mock_log_error.call_args[0][0]
            self.assertIn("cleanup failed", log_message)


if __name__ == '__main__':
    unittest.main()
