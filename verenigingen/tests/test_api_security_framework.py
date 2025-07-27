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
from verenigingen.utils.security.rate_limiting import get_rate_limiter
from verenigingen.utils.security.csrf_protection import CSRFProtection


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
        self.assertTrue(critical_profile.requires_csrf)
        self.assertTrue(critical_profile.requires_audit)
        self.assertTrue(critical_profile.ip_restrictions)
        self.assertIn("System Manager", critical_profile.required_roles)

        public_profile = self.framework.get_security_profile(SecurityLevel.PUBLIC)
        self.assertFalse(public_profile.requires_csrf)
        self.assertEqual(public_profile.required_roles, [])

    def test_authentication_validation(self):
        """Test authentication validation logic"""

        # Test guest user rejection for secured endpoints
        profile = self.framework.get_security_profile(SecurityLevel.HIGH)

        with patch("frappe.session.user", "Guest"):
            with self.assertRaises(Exception):
                self.framework.validate_authentication(profile)

        # Test authenticated user acceptance
        with patch("frappe.session.user", "test@example.com"):
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
            "description": "Normal text" * 1000,  # Very long text
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
        with patch("frappe.session.user", "test@example.com"):
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
        with patch("frappe.session.user", "unauthorized@example.com"):
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
            classification_confidence=self.classifier._classify_operation_type.__class__.HIGH,
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
        with patch("frappe.session.user", "test@example.com"):
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
        with patch("frappe.session.user", "unauthorized@example.com"):
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
        with patch("frappe.session.user", "test@example.com"):
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
            "test_security_event",
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


if __name__ == "__main__":
    unittest.main()
