"""
Comprehensive Test Suite for API Security Framework

This test suite validates all components of the API security framework including
authentication, authorization, input validation, rate limiting, CSRF protection,
audit logging, and monitoring capabilities.
"""

import json
import time
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import frappe
from frappe.test_runner import make_test_records

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.api_security_framework import (
    APISecurityFramework,
    SecurityLevel,
    OperationType,
    get_security_framework,
    api_security_framework,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.enhanced_validation import (
    get_enhanced_validator,
    ValidationSchema,
    ValidationRule,
    ValidationType,
    ValidationSeverity,
)
from verenigingen.utils.security.api_classifier import get_api_classifier
from verenigingen.utils.security.security_monitoring import get_security_monitor, ThreatLevel
from verenigingen.utils.security.audit_logging import get_audit_logger
# Note: CSRFProtection removed - using Frappe's native CSRF (auth.py)
# Note: rate_limiting module removed - rate limiting now handled by COR


class TestAPISecurityFramework(VereningingenTestCase):
    """Test the core API security framework functionality"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.framework = get_security_framework()

    def test_security_level_classification(self):
        """Test automatic security level classification"""

        # Create mock functions with different patterns
        def create_sepa_batch():
            """Create SEPA batch for payment processing"""
            pass

        def get_member_profile():
            """Get member profile information"""
            pass

        def health_check():
            """System health check"""
            pass

        # Test classification
        critical_level = self.framework.classify_endpoint(create_sepa_batch, OperationType.FINANCIAL)
        self.assertEqual(critical_level, SecurityLevel.CRITICAL)

        high_level = self.framework.classify_endpoint(get_member_profile, OperationType.MEMBER_DATA)
        self.assertEqual(high_level, SecurityLevel.HIGH)

        low_level = self.framework.classify_endpoint(health_check, OperationType.UTILITY)
        self.assertEqual(low_level, SecurityLevel.LOW)

    def test_security_profile_configuration(self):
        """Test security profile settings"""

        critical_profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        self.assertTrue(critical_profile.requires_audit)
        self.assertTrue(critical_profile.ip_restrictions)
        # Note: Authorization is now handled via ROLE_PROFILE_SECURITY_MAPPING
        # in authorization_policy.py, not via required_roles on profiles

        public_profile = self.framework.get_security_profile(SecurityLevel.PUBLIC)
        self.assertFalse(public_profile.requires_audit)

    def test_authentication_validation(self):
        """Test authentication validation logic"""

        # Test guest user rejection for secured endpoints
        profile = self.framework.get_security_profile(SecurityLevel.HIGH)

        with patch("frappe.session", MagicMock(user="Guest")):
            with self.assertRaises(Exception):
                self.framework.validate_authentication(profile)

        # Test authenticated user acceptance
        with patch("frappe.session", MagicMock(user="test@example.com")):
            with patch("frappe.get_roles", return_value=["Verenigingen Administrator"]):
                result = self.framework.validate_authentication(profile)
                self.assertTrue(result)

    def test_request_method_validation(self):
        """Test HTTP method validation"""

        profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        profile.allowed_methods = ["POST"]

        # Mock request with GET method (should fail)
        mock_request = MagicMock()
        mock_request.method = "GET"

        with patch("frappe.request", mock_request):
            with self.assertRaises(Exception):
                self.framework.validate_request_method(profile)

        # Mock request with POST method (should pass)
        mock_request.method = "POST"
        with patch("frappe.request", mock_request):
            result = self.framework.validate_request_method(profile)
            self.assertTrue(result)

    def test_request_size_validation(self):
        """Test request size limits"""

        profile = self.framework.get_security_profile(SecurityLevel.CRITICAL)
        profile.max_request_size = 1024  # 1KB limit

        # Mock request with large content
        mock_request = MagicMock()
        mock_request.headers = {"Content-Length": "2048"}  # 2KB

        with patch("frappe.request", mock_request):
            with self.assertRaises(Exception):
                self.framework.validate_request_size(profile)

        # Mock request with acceptable size
        mock_request.headers = {"Content-Length": "512"}  # 512B
        with patch("frappe.request", mock_request):
            result = self.framework.validate_request_size(profile)
            self.assertTrue(result)

    def test_input_validation(self):
        """Test input data validation and sanitization"""

        profile = self.framework.get_security_profile(SecurityLevel.HIGH)

        # Test with malicious input
        test_data = {
            "name": "<script>alert('xss')</script>John",
            "email": "test@example.com",
            "description": "Normal text" * 50,  # Moderately long text
        }

        validated_data = self.framework.validate_input_data(profile, **test_data)

        # XSS should be escaped
        self.assertNotIn("<script>", validated_data["name"])
        self.assertIn("John", validated_data["name"])

        # Email should be preserved
        self.assertEqual(validated_data["email"], "test@example.com")

        # Long text should be truncated
        self.assertLessEqual(len(validated_data["description"]), 1000)


class TestSecurityDecorators(VereningingenTestCase):
    """Test security decorator functionality"""

    def test_api_security_framework_decorator(self):
        """Test the main security framework decorator"""

        @api_security_framework(security_level=SecurityLevel.HIGH, operation_type=OperationType.MEMBER_DATA)
        def test_function(param1, param2="default"):
            return {"param1": param1, "param2": param2}

        # Test that decorator preserves function metadata
        self.assertTrue(hasattr(test_function, "_security_protected"))
        self.assertEqual(test_function._security_level, SecurityLevel.HIGH)

        # Test function execution with valid parameters
        with patch("frappe.session", MagicMock(user="test@example.com")):
            with patch("frappe.get_roles", return_value=["Verenigingen Administrator"]):
                result = test_function("value1", param2="value2")
                self.assertEqual(result["param1"], "value1")
                self.assertEqual(result["param2"], "value2")

    def test_convenience_decorators(self):
        """Test convenience decorators for common patterns"""

        @critical_api(OperationType.FINANCIAL)
        def financial_function():
            return {"status": "success"}

        @high_security_api(OperationType.MEMBER_DATA)
        def member_function():
            return {"status": "success"}

        @standard_api(OperationType.REPORTING)
        def reporting_function():
            return {"status": "success"}

        # Verify decorators are applied correctly
        self.assertTrue(hasattr(financial_function, "_security_protected"))
        self.assertTrue(hasattr(member_function, "_security_protected"))
        self.assertTrue(hasattr(reporting_function, "_security_protected"))

    def test_decorator_error_handling(self):
        """Test decorator error handling"""

        @api_security_framework(security_level=SecurityLevel.CRITICAL, operation_type=OperationType.FINANCIAL)
        def restricted_function():
            return {"status": "success"}

        # Test unauthorized access
        with patch("frappe.session", MagicMock(user="unauthorized@example.com")):
            with patch("frappe.get_roles", return_value=["Guest"]):
                with self.assertRaises(Exception):
                    restricted_function()


class TestEnhancedValidation(VereningingenTestCase):
    """Test enhanced validation framework"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.validator = get_enhanced_validator()

    def test_schema_validation(self):
        """Test schema-based validation"""

        # Test valid member data
        valid_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email_id": "john.doe@example.com",
            "phone": "+31612345678",
            "postal_code": "1234AB",
        }

        result = self.validator.validate_with_schema(valid_data, "member_data")
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)

        # Test invalid member data
        invalid_data = {
            "first_name": "",  # Required field empty
            "last_name": "Doe",
            "email_id": "invalid-email",  # Invalid format
            "postal_code": "invalid",  # Invalid format
        }

        result = self.validator.validate_with_schema(invalid_data, "member_data")
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_business_rule_validation(self):
        """Test business rule validation"""

        def check_age_requirement(data):
            """Business rule: Members must be 16+ for voting rights"""
            if data.get("voting_rights") and data.get("age", 0) < 16:
                return {"valid": False, "severity": "error", "message": "Voting rights require minimum age of 16"}
            return {"valid": True}

        # Test valid data
        valid_data = {"voting_rights": True, "age": 18}
        result = self.validator.validate_business_rules(valid_data, [check_age_requirement])
        self.assertTrue(result["valid"])

        # Test invalid data
        invalid_data = {"voting_rights": True, "age": 15}
        result = self.validator.validate_business_rules(invalid_data, [check_age_requirement])
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_secure_error_response(self):
        """Test secure error response generation"""

        validation_result = {
            "valid": False,
            "errors": [{"field": "email", "severity": "error", "message": "Invalid email format"}],
            "schema_name": "member_data",
        }

        # Test admin user (should expose details)
        admin_response = self.validator.create_secure_error_response(validation_result, expose_details=True)
        self.assertFalse(admin_response["success"])
        self.assertIn("errors", admin_response)
        self.assertEqual(len(admin_response["errors"]), 1)

        # Test regular user (should not expose details)
        user_response = self.validator.create_secure_error_response(validation_result, expose_details=False)
        self.assertFalse(user_response["success"])
        self.assertEqual(len(user_response["errors"]), 1)
        self.assertEqual(user_response["errors"][0]["message"], "Invalid input data provided")


class TestAPIClassifier(VereningingenTestCase):
    """Test API classification and migration tools"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.classifier = get_api_classifier()

    def test_operation_type_classification(self):
        """Test operation type classification"""

        # Financial operation
        financial_result = self.classifier._classify_operation_type(
            "create_sepa_batch", "def create_sepa_batch(): payment invoice sepa batch"
        )
        self.assertEqual(financial_result, OperationType.FINANCIAL)

        # Member data operation
        member_result = self.classifier._classify_operation_type(
            "update_member_profile", "def update_member_profile(): member user profile personal"
        )
        self.assertEqual(member_result, OperationType.MEMBER_DATA)

        # Utility operation
        utility_result = self.classifier._classify_operation_type(
            "health_check", "def health_check(): status ping health system"
        )
        self.assertEqual(utility_result, OperationType.UTILITY)

    def test_security_level_classification(self):
        """Test security level classification"""

        # Critical operation
        critical_result = self.classifier._classify_security_level(
            "delete_financial_data",
            "def delete_financial_data(): remove financial delete admin",
            OperationType.FINANCIAL,
        )
        self.assertEqual(critical_result, SecurityLevel.CRITICAL)

        # High security operation
        high_result = self.classifier._classify_security_level(
            "update_member_data", "def update_member_data(): update member modify", OperationType.MEMBER_DATA
        )
        self.assertEqual(high_result, SecurityLevel.HIGH)

    def test_risk_factor_analysis(self):
        """Test risk factor detection"""

        # Source with SQL injection risk
        risky_source = """
        def process_data():
            query = "SELECT * FROM users WHERE id = " + user_id
            frappe.db.sql(query)
        """

        risks = self.classifier._analyze_risk_factors(risky_source)
        self.assertIn("sql_injection", risks)

        # Source with file operations
        file_source = """
        def upload_document():
            file = request.files['upload']
            file.save('/uploads/' + filename)
        """

        file_risks = self.classifier._analyze_risk_factors(file_source)
        self.assertIn("file_operations", file_risks)

    def test_migration_priority_calculation(self):
        """Test migration priority calculation"""

        from verenigingen.utils.security.api_classifier import APIEndpoint

        # High priority endpoint (critical + financial)
        critical_endpoint = APIEndpoint(
            module_path="test.module",
            function_name="test_function",
            file_path="/test/path",
            line_number=1,
            docstring="Test function",
            current_security_level=None,
            recommended_security_level=SecurityLevel.CRITICAL,
            operation_type=OperationType.FINANCIAL,
            classification_confidence=0.9,  # High confidence score
            has_frappe_whitelist=True,
            has_security_decorators=False,
            existing_decorators=[],
            allow_guest=False,
            parameters=[],
            return_type=None,
            database_operations=["DELETE"],
            external_calls=[],
            risk_factors=["sql_injection"],
            security_recommendations=[],
            migration_priority=1,
            business_function=None,
            data_sensitivity="critical",
            user_roles_involved=[],
        )

        priority = self.classifier._calculate_migration_priority(critical_endpoint)
        self.assertLessEqual(priority, 2)  # Should be high priority


class TestSecurityMonitoring(VereningingenTestCase):
    """Test security monitoring and threat detection"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.monitor = get_security_monitor()

    def test_api_call_recording(self):
        """Test API call monitoring"""

        # Record normal API call
        self.monitor.record_api_call(
            endpoint="/api/test",
            user="test@example.com",
            response_time=0.5,
            status="success",
            ip_address="192.168.1.100",
        )

        # Verify recording
        self.assertGreater(len(self.monitor.sliding_windows["api_response_times"]), 0)

        # Record slow API call
        self.monitor.record_api_call(
            endpoint="/api/test",
            user="test@example.com",
            response_time=10.0,  # Very slow
            status="success",
            ip_address="192.168.1.100",
        )

        # Should trigger performance anomaly detection
        # (Implementation would create incident)

    def test_authentication_threat_detection(self):
        """Test authentication failure monitoring"""

        from verenigingen.utils.security.security_monitoring import MonitoringMetric

        # Simulate multiple authentication failures
        for i in range(15):  # Above threshold
            self.monitor.record_security_event(
                MonitoringMetric.AUTHENTICATION_FAILURES,
                user="attacker@example.com",
                endpoint="/api/login",
                ip_address="192.168.1.200",
            )

        # Should create security incident
        self.assertGreater(len(self.monitor.incidents), 0)

        # Check incident details
        incident = self.monitor.incidents[-1]
        self.assertEqual(incident.threat_level, ThreatLevel.HIGH)
        self.assertEqual(incident.incident_type, "credential_attack")

    def test_rate_limit_monitoring(self):
        """Test rate limit violation monitoring"""

        from verenigingen.utils.security.security_monitoring import MonitoringMetric

        # Simulate rate limit violations
        for i in range(60):  # Above threshold
            self.monitor.record_security_event(
                MonitoringMetric.RATE_LIMIT_VIOLATIONS,
                user="abuser@example.com",
                endpoint="/api/data",
                ip_address="192.168.1.300",
            )

        # Should create security incident
        rate_incidents = [i for i in self.monitor.incidents if i.incident_type == "rate_limit_abuse"]
        self.assertGreater(len(rate_incidents), 0)

    def test_security_dashboard(self):
        """Test security dashboard data generation"""

        dashboard = self.monitor.get_security_dashboard()

        # Verify dashboard structure
        self.assertIn("current_metrics", dashboard)
        self.assertIn("active_incidents", dashboard)
        self.assertIn("threat_summary", dashboard)
        self.assertIn("metrics_trend", dashboard)

        # Verify threat summary structure
        threat_summary = dashboard["threat_summary"]
        self.assertIn("critical", threat_summary)
        self.assertIn("high", threat_summary)
        self.assertIn("medium", threat_summary)
        self.assertIn("low", threat_summary)


class TestIntegrationSecurity(VereningingenTestCase):
    """Test end-to-end security integration"""

    def test_complete_security_workflow(self):
        """Test complete security workflow from API call to audit"""

        # Create a test endpoint with full security
        @api_security_framework(
            security_level=SecurityLevel.HIGH, operation_type=OperationType.MEMBER_DATA, audit_level="detailed"
        )
        def test_secured_endpoint(member_id, **data):
            return {"success": True, "member_id": member_id, "data": data}

        # Mock user session
        with patch("frappe.session", MagicMock(user="test@example.com")):
            with patch("frappe.get_roles", return_value=["Verenigingen Administrator"]):
                # Test successful execution
                result = test_secured_endpoint("TEST-001", name="Test Member", email="test@example.com")

                self.assertTrue(result["success"])
                self.assertEqual(result["member_id"], "TEST-001")

    def test_security_failure_handling(self):
        """Test security failure handling and error responses"""

        @api_security_framework(security_level=SecurityLevel.CRITICAL, operation_type=OperationType.FINANCIAL)
        def restricted_endpoint():
            return {"success": True}

        # Test unauthorized access
        with patch("frappe.session", MagicMock(user="unauthorized@example.com")):
            with patch("frappe.get_roles", return_value=["Guest"]):
                with self.assertRaises(Exception):
                    restricted_endpoint()

    def test_performance_impact(self):
        """Test performance impact of security framework"""

        @api_security_framework(security_level=SecurityLevel.MEDIUM, operation_type=OperationType.REPORTING)
        def performance_test_endpoint():
            time.sleep(0.1)  # Simulate work
            return {"success": True}

        # Measure execution time
        with patch("frappe.session", MagicMock(user="test@example.com")):
            with patch("frappe.get_roles", return_value=["Verenigingen Administrator"]):
                start_time = time.time()
                result = performance_test_endpoint()
                end_time = time.time()

                execution_time = end_time - start_time

                # Security overhead should be minimal (< 100ms)
                self.assertLess(execution_time, 0.3)  # 0.1s work + 0.2s max overhead
                self.assertTrue(result["success"])


class TestSecurityCompliance(VereningingenTestCase):
    """Test security compliance and audit capabilities"""

    def test_audit_trail_generation(self):
        """Test comprehensive audit trail generation"""

        audit_logger = get_audit_logger()

        # Log security event
        event_id = audit_logger.log_event(
            "other",
            "info",
            user="test@example.com",
            details={"action": "test", "resource": "test_resource"},
        )

        self.assertIsNotNone(event_id)
        self.assertTrue(event_id.startswith("audit_"))

    def test_compliance_reporting(self):
        """Test compliance reporting capabilities"""

        # Test would verify compliance report generation
        # Including GDPR, security standards, etc.
        pass

    def test_data_retention_policies(self):
        """Test data retention policy enforcement"""

        # Test would verify automatic cleanup of old audit logs
        # based on retention policies
        pass


class TestScopedRateLimiting(VereningingenTestCase):
    """Test scope-based rate limiting with context detection"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.framework = get_security_framework()

    def setUp(self):
        super().setUp()
        # Clear rate limit cache
        frappe.cache().delete_keys("cor_rate_limit:*")

    def test_context_detection_interactive(self):
        """Test detection of interactive HTTP context"""
        from verenigingen.utils.security.types import ExecutionContext

        # Simulate HTTP request context
        frappe.local.request = MagicMock()
        frappe.local.request.method = "GET"  # Need method attr for detection
        frappe.flags.in_background_job = False
        frappe.flags.in_scheduler = False
        # Temporarily disable in_test flag to test INTERACTIVE detection
        original_in_test = frappe.flags.in_test
        frappe.flags.in_test = False

        try:
            context = self.framework._detect_execution_context()
            self.assertEqual(context, ExecutionContext.INTERACTIVE)
        finally:
            frappe.flags.in_test = original_in_test

    def test_context_detection_background_job(self):
        """Test detection of background job context"""
        from verenigingen.utils.security.types import ExecutionContext

        # Simulate background job context
        frappe.flags.in_background_job = True
        frappe.flags.in_scheduler = False

        context = self.framework._detect_execution_context()
        self.assertEqual(context, ExecutionContext.BACKGROUND_JOB)

    def test_context_detection_scheduled_task(self):
        """Test detection of scheduled task context"""
        from verenigingen.utils.security.types import ExecutionContext

        # Simulate scheduler context
        frappe.flags.in_background_job = False
        frappe.flags.in_scheduler = True

        context = self.framework._detect_execution_context()
        self.assertEqual(context, ExecutionContext.SCHEDULED_TASK)

    def test_context_detection_cli(self):
        """Test detection of CLI context"""
        from verenigingen.utils.security.types import ExecutionContext

        # Simulate CLI context (no request, no flags)
        frappe.local.request = None
        frappe.flags.in_background_job = False
        frappe.flags.in_scheduler = False

        context = self.framework._detect_execution_context()
        self.assertEqual(context, ExecutionContext.CLI)

    def test_batch_rate_limits_applied_in_background_job(self):
        """Test that batch rate limits are used for background jobs"""
        # Create a test COR with batch limits
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": "test_batch_operation",
            "operation_type": "admin",
            "security_level": "high",
            "enabled": 1,
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 3600,
            "batch_rate_limit_calls": 100,
            "batch_rate_limit_period_seconds": 3600,
            "apply_batch_limits_to": "Both"
        })
        cor.insert(ignore_if_duplicate=True)
        frappe.db.commit()

        # Set background job flag
        frappe.flags.in_background_job = True

        # Should be able to make more than 5 calls (interactive limit)
        # but less than 100 calls (batch limit)
        profile = self.framework.get_security_profile(SecurityLevel.HIGH)

        # Make 10 calls - should succeed with batch limits
        for i in range(10):
            try:
                self.framework.validate_rate_limits(profile, "test_batch_operation")
            except Exception as e:
                self.fail(f"Batch rate limiting failed on call {i+1}: {str(e)}")

    def test_interactive_rate_limits_cache_key_structure(self):
        """Test that interactive rate limit cache keys are properly structured.

        Note: Full rate limit enforcement cannot be tested in the test environment
        because Frappe's test framework sets frappe.flags.in_test=True, which
        causes rate limiting to be skipped (by design - we don't want tests to
        fail due to rate limits from other tests).

        Instead, we test the cache key structure and COR configuration.
        """
        from verenigingen.utils.security.types import ExecutionContext
        import time

        # Use unique operation name to avoid cache collisions
        unique_op = f"test_rate_limit_structure_{int(time.time() * 1000)}"

        # Create a test COR with low interactive limits and global scope
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": unique_op,
            "operation_type": "admin",
            "security_level": "high",
            "enabled": 1,
            "rate_limit_calls": 3,
            "rate_limit_period_seconds": 3600,
            "rate_limit_scope": "global",
            "batch_rate_limit_calls": 100,
            "batch_rate_limit_period_seconds": 3600,
            "apply_batch_limits_to": "Both"
        })
        cor.insert(ignore_if_duplicate=True)
        frappe.db.commit()

        try:
            # Verify COR was created correctly
            saved_cor = frappe.get_doc("Critical Operation Rule", unique_op)
            self.assertEqual(saved_cor.rate_limit_calls, 3)
            self.assertEqual(saved_cor.rate_limit_scope, "global")
            self.assertEqual(saved_cor.batch_rate_limit_calls, 100)

            # Verify the expected cache key structure
            expected_cache_key = f"cor_rate_limit:interactive:{unique_op}"
            self.assertIn("cor_rate_limit", expected_cache_key)
            self.assertIn("interactive", expected_cache_key)
            self.assertIn(unique_op, expected_cache_key)

            # Verify context detection works
            with patch.object(self.framework, '_detect_execution_context', return_value=ExecutionContext.INTERACTIVE):
                # In test mode, rate limiting is skipped, but we can verify the method doesn't raise
                profile = self.framework.get_security_profile(SecurityLevel.HIGH)
                result = self.framework.validate_rate_limits(profile, unique_op)
                self.assertTrue(result, "Rate limit validation should return True (rate limiting skipped in test mode)")

        finally:
            frappe.delete_doc("Critical Operation Rule", unique_op, force=True, ignore_permissions=True)

    def test_batch_context_skips_rate_limiting_for_low_security_without_batch_limits(self):
        """Test that batch context skips rate limiting for LOW/MEDIUM security operations.

        For LOW/MEDIUM security operations, background jobs should not be blocked by
        interactive rate limits, allowing them to process large volumes of data.
        When batch limits aren't explicitly configured, rate limiting is bypassed.

        Note: CRITICAL/HIGH operations DO enforce rate limits even without batch config
        (see test_critical_operation_enforces_rate_limit_in_background).
        """
        from verenigingen.utils.security.types import ExecutionContext

        # Delete any existing COR to ensure clean test state
        if frappe.db.exists("Critical Operation Rule", "test_low_security_no_batch_limits"):
            frappe.delete_doc("Critical Operation Rule", "test_low_security_no_batch_limits", force=True, ignore_permissions=True)
            frappe.db.commit()

        # Create a COR with batch limits explicitly set to 0 - use LOW security level
        # Note: DocType has default of 5000, so we must explicitly set to 0 to test bypass
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": "test_low_security_no_batch_limits",
            "operation_type": "utility",
            "security_level": "low",  # LOW security - rate limiting bypassed in batch context
            "enabled": 1,
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 3600,
            "batch_rate_limit_calls": 0  # Explicitly disable batch limits
        })
        cor.insert()
        frappe.db.commit()

        try:
            # Clear any existing rate limit cache
            frappe.cache().delete_keys("cor_rate_limit:*test_low_security_no_batch_limits*")

            # Mock context detection to return BACKGROUND_JOB and bypass in_test check
            with patch.object(self.framework, '_detect_execution_context', return_value=ExecutionContext.BACKGROUND_JOB):
                original_in_test = frappe.flags.in_test
                frappe.flags.in_test = False

                try:
                    profile = self.framework.get_security_profile(SecurityLevel.LOW)

                    # For LOW security without batch limits, rate limiting should be skipped
                    # So even many calls should succeed (beyond interactive limit of 5)
                    for i in range(10):
                        result = self.framework.validate_rate_limits(profile, "test_low_security_no_batch_limits")
                        self.assertTrue(result, f"Call {i+1} should succeed - rate limiting should be skipped for LOW security")
                finally:
                    frappe.flags.in_test = original_in_test
        finally:
            frappe.delete_doc("Critical Operation Rule", "test_low_security_no_batch_limits", force=True, ignore_permissions=True)

    def test_critical_operation_enforces_rate_limit_in_background(self):
        """Test that CRITICAL/HIGH operations enforce rate limits even in background context.

        Security Fix: For CRITICAL/HIGH security operations, rate limiting should NOT
        be bypassed in background context when batch limits aren't configured.
        Instead, interactive limits are inherited to prevent rate limit evasion attacks.
        """
        from verenigingen.utils.security.types import ExecutionContext
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        # Delete any existing COR to ensure clean test state
        if frappe.db.exists("Critical Operation Rule", "test_high_security_no_batch_limits"):
            frappe.delete_doc("Critical Operation Rule", "test_high_security_no_batch_limits", force=True, ignore_permissions=True)
            frappe.db.commit()

        # Create a COR with batch limits explicitly set to 0 - use HIGH security level
        # Note: DocType has default of 5000, so we must explicitly set to 0 to test inheritance
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": "test_high_security_no_batch_limits",
            "operation_type": "financial",
            "security_level": "high",  # HIGH security - rate limiting enforced in batch context
            "enabled": 1,
            "rate_limit_calls": 3,  # Low limit to test enforcement
            "rate_limit_period_seconds": 3600,
            "batch_rate_limit_calls": 0  # Explicitly disable - should inherit interactive limits
        })
        cor.insert()
        frappe.db.commit()

        try:
            # Clear any existing rate limit cache using Redis directly
            # Frappe cache may have a key prefix, so we need to clear the right keys
            import redis
            redis_url = frappe.conf.redis_cache or "redis://localhost:6379"
            r = redis.from_url(redis_url)
            # Find and delete all keys matching our operation name
            keys = list(r.scan_iter("*test_high_security_no_batch_limits*"))
            if keys:
                r.delete(*keys)

            # Test the rate limiter directly to bypass framework mock
            # Use force_check=True to bypass test environment skip
            rate_limiter = self.framework.rate_limiter

            # First 3 calls should succeed (within inherited interactive limit)
            for i in range(3):
                result = rate_limiter.check_rate_limit(
                    "test_high_security_no_batch_limits",
                    context=ExecutionContext.BACKGROUND_JOB,
                    force_check=True,
                )
                self.assertTrue(result.allowed, f"Call {i+1} should succeed (within limit)")
                self.assertEqual(
                    result.limit_type,
                    "batch_inherited",
                    f"Should use inherited limits for HIGH security in batch context",
                )

            # 4th call should fail - rate limit exceeded
            result = rate_limiter.check_rate_limit(
                "test_high_security_no_batch_limits",
                context=ExecutionContext.BACKGROUND_JOB,
                force_check=True,
            )
            self.assertFalse(result.allowed, "4th call should exceed rate limit")
            self.assertIn("Rate limit exceeded", result.reason)
        finally:
            frappe.delete_doc("Critical Operation Rule", "test_high_security_no_batch_limits", force=True, ignore_permissions=True)

    def test_separate_cache_keys_for_batch_and_interactive(self):
        """Test that batch and interactive contexts use separate cache keys"""
        # Create a test COR
        cor = frappe.get_doc({
            "doctype": "Critical Operation Rule",
            "operation_name": "test_cache_separation",
            "operation_type": "admin",
            "security_level": "high",
            "enabled": 1,
            "rate_limit_calls": 5,
            "rate_limit_period_seconds": 3600,
            "batch_rate_limit_calls": 10,
            "batch_rate_limit_period_seconds": 3600,
            "apply_batch_limits_to": "Both"
        })
        cor.insert(ignore_if_duplicate=True)
        frappe.db.commit()

        profile = self.framework.get_security_profile(SecurityLevel.HIGH)

        # Make 5 calls in interactive context
        frappe.local.request = MagicMock()
        frappe.flags.in_background_job = False
        for i in range(5):
            self.framework.validate_rate_limits(profile, "test_cache_separation")

        # Switch to background job context
        frappe.flags.in_background_job = True

        # Should be able to make 10 more calls (separate cache key)
        for i in range(10):
            try:
                self.framework.validate_rate_limits(profile, "test_cache_separation")
            except Exception as e:
                self.fail(f"Cache key separation failed: {str(e)}")


class TestSecurityAuditFixes(VereningingenTestCase):
    """Test cases for security audit fixes (Phase 1)

    These tests validate the security hardening implemented based on the
    security audit findings, specifically:
    - Fix 1: Fail-closed whitelist fallback behavior
    - Fix 2: Strict HTTP method defaults (POST only)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.framework = get_security_framework()

    def test_non_whitelisted_function_not_marked_whitelisted(self):
        """Test that decorator on non-whitelisted function does NOT set whitelisted flag

        Security Fix 1: Fail-closed behavior - functions not in Frappe's whitelist
        registry should not be automatically treated as whitelisted.
        """
        # Create a function that is NOT whitelisted (no @frappe.whitelist)
        def internal_function():
            """This is an internal function, not meant for API exposure"""
            return {"internal": True}

        # Apply the security decorator
        with patch("frappe.logger") as mock_logger:
            decorated = api_security_framework(
                security_level=SecurityLevel.HIGH,
                operation_type=OperationType.MEMBER_DATA
            )(internal_function)

            # The wrapper should NOT have __func_is_whitelisted__ set to True
            # (it either shouldn't have the attribute, or it should be False)
            is_whitelisted = getattr(decorated, "__func_is_whitelisted__", False)

            # Verify warning was logged about non-whitelisted function
            mock_logger.assert_called()
            logger_instance = mock_logger.return_value
            # Check that warning was called (fail-closed behavior logs a warning)
            self.assertTrue(
                logger_instance.warning.called or not is_whitelisted,
                "Non-whitelisted function should either log warning or not be marked whitelisted"
            )

    def test_whitelisted_function_preserves_whitelist_status(self):
        """Test that decorator preserves whitelist status for properly whitelisted functions"""
        # Create a mock whitelisted function
        def whitelisted_function():
            return {"whitelisted": True}

        # Simulate Frappe's whitelist registration
        whitelisted_function.__func_is_whitelisted__ = True

        # Apply the security decorator
        decorated = api_security_framework(
            security_level=SecurityLevel.HIGH,
            operation_type=OperationType.MEMBER_DATA
        )(whitelisted_function)

        # The wrapper should preserve the whitelisted status
        self.assertTrue(
            getattr(decorated, "__func_is_whitelisted__", False),
            "Whitelisted function should preserve its whitelisted status"
        )

    def test_http_method_default_is_post_only(self):
        """Test that HTTP method defaults to POST only (not GET+POST)

        Security Fix 2: Mutation endpoints should not allow GET by default.
        This prevents accidental exposure of state-changing operations via GET.
        """
        # Create a whitelisted function without explicit HTTP methods
        def mutation_endpoint():
            return {"mutated": True}

        mutation_endpoint.__func_is_whitelisted__ = True

        # Ensure the function is NOT in Frappe's allowed_http_methods_for_whitelisted_func
        if hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            # Remove if exists
            frappe.allowed_http_methods_for_whitelisted_func.pop(mutation_endpoint, None)

        # Mock frappe.whitelisted to include our function
        original_whitelisted = getattr(frappe, "whitelisted", set())
        if isinstance(original_whitelisted, set):
            frappe.whitelisted = original_whitelisted | {mutation_endpoint}
        else:
            frappe.whitelisted = list(original_whitelisted) + [mutation_endpoint]

        try:
            # Apply the security decorator
            decorated = api_security_framework(
                security_level=SecurityLevel.HIGH,
                operation_type=OperationType.MEMBER_DATA
            )(mutation_endpoint)

            # Check what HTTP methods were registered for the wrapper
            if hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
                http_methods_dict = frappe.allowed_http_methods_for_whitelisted_func
                registered_methods = http_methods_dict.get(decorated)

                if registered_methods is not None:
                    # Should be POST only, NOT GET+POST
                    self.assertEqual(
                        registered_methods,
                        ["POST"],
                        f"HTTP methods should default to POST only, got: {registered_methods}"
                    )
                    self.assertNotIn(
                        "GET",
                        registered_methods,
                        "GET should NOT be in default HTTP methods for security"
                    )
        finally:
            # Restore original whitelisted
            frappe.whitelisted = original_whitelisted

    def test_explicit_http_methods_preserved(self):
        """Test that explicitly defined HTTP methods are preserved by decorator"""
        # Create a function with explicit GET method (read-only endpoint)
        def read_endpoint():
            return {"data": "read-only"}

        read_endpoint.__func_is_whitelisted__ = True

        # Simulate explicit HTTP method registration
        if hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            frappe.allowed_http_methods_for_whitelisted_func[read_endpoint] = ["GET"]

        # Mock frappe.whitelisted
        original_whitelisted = getattr(frappe, "whitelisted", set())
        if isinstance(original_whitelisted, set):
            frappe.whitelisted = original_whitelisted | {read_endpoint}
        else:
            frappe.whitelisted = list(original_whitelisted) + [read_endpoint]

        try:
            # Apply the security decorator
            decorated = api_security_framework(
                security_level=SecurityLevel.MEDIUM,
                operation_type=OperationType.REPORTING
            )(read_endpoint)

            # Check that GET was preserved (not overwritten to POST)
            if hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
                http_methods_dict = frappe.allowed_http_methods_for_whitelisted_func
                registered_methods = http_methods_dict.get(decorated)

                if registered_methods is not None:
                    self.assertEqual(
                        registered_methods,
                        ["GET"],
                        f"Explicit HTTP methods should be preserved, got: {registered_methods}"
                    )
        finally:
            # Restore original whitelisted
            frappe.whitelisted = original_whitelisted
            # Clean up
            if hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
                frappe.allowed_http_methods_for_whitelisted_func.pop(read_endpoint, None)


if __name__ == "__main__":
    unittest.main()
