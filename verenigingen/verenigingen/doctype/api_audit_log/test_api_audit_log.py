"""
Test cases for API Audit Log DocType
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now

from verenigingen.verenigingen.doctype.api_audit_log.api_audit_log import APIAuditLog


class TestAPIAuditLog(unittest.TestCase):
    """Test cases for API Audit Log functionality"""

    def setUp(self):
        """Set up test data"""
        # Clean up any existing test entries
        frappe.db.delete("API Audit Log", {"event_id": ["like", "test_%"]})
        frappe.db.commit()

    def tearDown(self):
        """Clean up test data"""
        frappe.db.delete("API Audit Log", {"event_id": ["like", "test_%"]})
        frappe.db.commit()

    def test_create_basic_audit_entry(self):
        """Test creating a basic audit entry"""
        audit_data = {
            "event_id": "test_basic_001",
            "timestamp": now(),
            "event_type": "api_call_success",
            "severity": "info",
            "user": "test@example.com",
            "ip_address": "127.0.0.1",
            "details": {"endpoint": "/api/test", "method": "GET"},
        }

        audit_doc = frappe.new_doc("API Audit Log")
        audit_doc.update(audit_data)
        audit_doc.insert()

        # Verify the document was created
        saved_doc = frappe.get_doc("API Audit Log", audit_doc.name)
        self.assertEqual(saved_doc.event_id, "test_basic_001")
        self.assertEqual(saved_doc.event_type, "api_call_success")
        self.assertEqual(saved_doc.severity, "info")
        self.assertEqual(saved_doc.user, "test@example.com")

    def test_create_audit_entry_static_method(self):
        """Test creating audit entry using static method"""
        event_data = {
            "event_id": "test_static_001",
            "timestamp": now(),
            "event_type": "csrf_validation_failed",
            "severity": "warning",
            "user": "guest@example.com",
            "ip_address": "192.168.1.1",
            "user_agent": "TestAgent/1.0",
            "details": {"csrf_token": "invalid", "endpoint": "/api/secure"},
        }

        entry_name = APIAuditLog.create_audit_entry(event_data)
        self.assertIsNotNone(entry_name)

        # Verify the entry exists
        saved_doc = frappe.get_doc("API Audit Log", entry_name)
        self.assertEqual(saved_doc.event_id, "test_static_001")
        self.assertEqual(saved_doc.event_type, "csrf_validation_failed")
        self.assertEqual(saved_doc.severity, "warning")

    def test_required_field_validation(self):
        """Test validation of required fields"""
        # Test missing event_id
        with self.assertRaises(frappe.ValidationError):
            audit_doc = frappe.new_doc("API Audit Log")
            audit_doc.timestamp = now()
            audit_doc.severity = "info"
            # Missing event_id and event_type
            audit_doc.insert()

    def test_auto_event_id_generation(self):
        """Test automatic event ID generation"""
        audit_doc = frappe.new_doc("API Audit Log")
        audit_doc.event_type = "system_error"
        audit_doc.severity = "error"
        audit_doc.user = "system@example.com"

        # Don't set event_id - should be auto-generated
        audit_doc.insert()

        self.assertIsNotNone(audit_doc.event_id)
        self.assertTrue(audit_doc.event_id.startswith("api_audit_"))

    def test_immutable_after_creation(self):
        """Test that audit entries cannot be modified after creation"""
        audit_doc = frappe.new_doc("API Audit Log")
        audit_doc.event_id = "test_immutable_001"
        audit_doc.event_type = "api_call_success"
        audit_doc.severity = "info"
        audit_doc.user = "test@example.com"
        audit_doc.insert()

        # Try to modify the document
        with self.assertRaises(frappe.ValidationError):
            audit_doc.severity = "warning"
            audit_doc.save()

    def test_cleanup_old_entries(self):
        """Test cleanup of old audit entries"""
        # Create old entry
        old_date = add_days(now(), -100)
        old_audit = frappe.new_doc("API Audit Log")
        old_audit.event_id = "test_old_001"
        old_audit.timestamp = old_date
        old_audit.event_type = "api_call_success"
        old_audit.severity = "info"
        old_audit.user = "old@example.com"
        old_audit.insert()

        # Create recent entry
        recent_audit = frappe.new_doc("API Audit Log")
        recent_audit.event_id = "test_recent_001"
        recent_audit.timestamp = now()
        recent_audit.event_type = "api_call_success"
        recent_audit.severity = "info"
        recent_audit.user = "recent@example.com"
        recent_audit.insert()

        # Run cleanup with 90-day retention
        APIAuditLog.cleanup_old_entries(retention_days=90)

        # Verify old entry was deleted and recent entry remains
        old_exists = frappe.db.exists("API Audit Log", old_audit.name)
        recent_exists = frappe.db.exists("API Audit Log", recent_audit.name)

        self.assertFalse(old_exists)
        self.assertTrue(recent_exists)

    def test_security_event_logging(self):
        """Test logging of security events"""
        security_events = [
            ("unauthorized_access_attempt", "warning"),
            ("rate_limit_exceeded", "error"),
            ("suspicious_activity", "critical"),
            ("failed_login_attempt", "warning"),
        ]

        created_docs = []
        for event_type, severity in security_events:
            event_data = {
                "event_id": f"test_security_{event_type}",
                "timestamp": now(),
                "event_type": event_type,
                "severity": severity,
                "user": "security_test@example.com",
                "ip_address": "10.0.0.1",
                "details": {"test_event": True, "source": "unit_test"},
            }

            entry_name = APIAuditLog.create_audit_entry(event_data)
            self.assertIsNotNone(entry_name)
            created_docs.append(entry_name)

        # Verify all security events were logged
        self.assertEqual(len(created_docs), 4)

        # Verify event types are correctly stored
        for i, doc_name in enumerate(created_docs):
            doc = frappe.get_doc("API Audit Log", doc_name)
            expected_type, expected_severity = security_events[i]
            self.assertEqual(doc.event_type, expected_type)
            self.assertEqual(doc.severity, expected_severity)

    @patch("frappe.log_error")
    def test_error_handling_in_static_method(self, mock_log_error):
        """Test error handling in static method"""
        # Pass invalid data that should cause an error
        invalid_data = {
            "event_id": None,  # Invalid - should be string
            "timestamp": "invalid_date",  # Invalid date format
            "event_type": "invalid_type",  # Not in select options
            "severity": "invalid_severity",  # Not in select options
        }

        # Should return None and log error
        result = APIAuditLog.create_audit_entry(invalid_data)
        self.assertIsNone(result)

        # Verify error was logged
        mock_log_error.assert_called_once()
        call_args = mock_log_error.call_args[0]
        self.assertIn("Failed to create API audit entry", call_args[0])
        self.assertEqual(call_args[1], "API Audit Error")


if __name__ == "__main__":
    unittest.main()
