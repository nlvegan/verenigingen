"""
Tests for Security Utilities
=============================

Comprehensive tests for security utilities in:
- verenigingen/utils/error_handling.py (mask_iban, sanitize_audit_details)
- verenigingen/utils/secure_operations.py (validate_justification, can_request_system_escalation,
  get_system_user_for_operation)

These utilities are critical for:
- PII protection in audit logs
- Role-based access control for system escalation
- Audit compliance through justification requirements
"""

import unittest
from unittest.mock import patch, MagicMock

import frappe

from verenigingen.utils.error_handling import (
    ConfigurationError,
    mask_iban,
    sanitize_audit_details,
    sanitize_error_for_audit,
)
from verenigingen.utils.secure_operations import (
    ESCALATION_ALLOWED_ROLES,
    MAX_JUSTIFICATION_LENGTH,
    MIN_JUSTIFICATION_LENGTH,
    can_request_system_escalation,
    get_system_user_for_operation,
    validate_justification,
)


class TestMaskIban(unittest.TestCase):
    """Tests for mask_iban() function"""

    def test_standard_style_dutch_iban(self):
        """Test standard masking of Dutch IBAN"""
        result = mask_iban("NL91ABNA0417164300")
        self.assertEqual(result, "NL************4300")

    def test_standard_style_german_iban(self):
        """Test standard masking of German IBAN"""
        result = mask_iban("DE89370400440532013000")
        self.assertEqual(result, "DE****************3000")

    def test_brief_style_dutch_iban(self):
        """Test brief masking style (first 4 + last 4)"""
        result = mask_iban("NL91ABNA0417164300", style="brief")
        self.assertEqual(result, "NL91****4300")

    def test_brief_style_german_iban(self):
        """Test brief masking of German IBAN"""
        result = mask_iban("DE89370400440532013000", style="brief")
        self.assertEqual(result, "DE89****3000")

    def test_iban_with_spaces(self):
        """Test that IBANs with spaces are handled correctly"""
        result = mask_iban("NL91 ABNA 0417 1643 00")
        # Spaces are removed, then masked
        self.assertEqual(result, "NL************4300")

    def test_iban_lowercase(self):
        """Test that lowercase IBANs are uppercased"""
        result = mask_iban("nl91abna0417164300")
        self.assertEqual(result, "NL************4300")

    def test_empty_iban(self):
        """Test that empty string returns empty string"""
        result = mask_iban("")
        self.assertEqual(result, "")

    def test_none_iban(self):
        """Test that None returns None"""
        result = mask_iban(None)
        self.assertIsNone(result)

    def test_short_iban(self):
        """Test handling of very short strings (edge case)"""
        result = mask_iban("NL91")
        # Less than 6 chars should be fully masked
        self.assertEqual(result, "****")

    def test_exactly_six_chars(self):
        """Test IBAN with exactly 6 characters"""
        result = mask_iban("NL9112")
        # Should show country code + last 4
        self.assertEqual(result, "NL9112")

    def test_brief_style_short_iban(self):
        """Test brief style with short IBAN (less than 8 chars)"""
        result = mask_iban("NL91ABC", style="brief")
        # Too short for brief style, returns as-is
        self.assertEqual(result, "NL91ABC")


class TestSanitizeAuditDetails(unittest.TestCase):
    """Tests for sanitize_audit_details() function"""

    def test_iban_field_masked(self):
        """Test that IBAN fields are properly masked"""
        details = {"iban": "NL91ABNA0417164300"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["iban"], "NL************4300")

    def test_bank_account_field_masked(self):
        """Test that bank_account fields are masked like IBANs"""
        details = {"bank_account": "DE89370400440532013000"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["bank_account"], "DE****************3000")

    def test_account_number_field_masked(self):
        """Test that account_number fields are masked"""
        details = {"account_number": "NL91ABNA0417164300"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["account_number"], "NL************4300")

    def test_password_field_redacted(self):
        """Test that password fields are fully redacted"""
        details = {"password": "supersecret123"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["password"], "[REDACTED]")

    def test_secret_field_redacted(self):
        """Test that secret fields are fully redacted"""
        details = {"secret": "my-api-secret"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["secret"], "[REDACTED]")

    def test_token_field_redacted(self):
        """Test that token fields are fully redacted"""
        details = {"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["token"], "[REDACTED]")

    def test_api_key_field_redacted(self):
        """Test that api_key fields are fully redacted"""
        details = {"api_key": "live_abc123xyz"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["api_key"], "[REDACTED]")

    def test_error_field_sanitized(self):
        """Test that error fields have PII redacted"""
        details = {"error": "Failed for user@example.com"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["error"], "Failed for [EMAIL REDACTED]")

    def test_traceback_field_sanitized(self):
        """Test that traceback fields are sanitized"""
        details = {"traceback": "Error at line 10\n  File '/path/to/file.py'"}
        result = sanitize_audit_details(details)
        # Should only keep first line
        self.assertNotIn("File", result["traceback"])

    def test_message_field_sanitized(self):
        """Test that message fields have PII redacted"""
        details = {"message": "Contact +31612345678 for help"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["message"], "Contact [PHONE REDACTED] for help")

    def test_regular_field_pii_sanitized(self):
        """Test that regular fields have PII redacted but are otherwise preserved"""
        details = {"user_email": "test@example.com", "amount": "100.50"}
        result = sanitize_audit_details(details)
        self.assertEqual(result["user_email"], "[EMAIL REDACTED]")
        self.assertEqual(result["amount"], "100.50")

    def test_none_value_preserved(self):
        """Test that None values are preserved"""
        details = {"optional_field": None}
        result = sanitize_audit_details(details)
        self.assertIsNone(result["optional_field"])

    def test_empty_details(self):
        """Test that empty dict returns empty dict"""
        result = sanitize_audit_details({})
        self.assertEqual(result, {})

    def test_none_details(self):
        """Test that None returns empty dict"""
        result = sanitize_audit_details(None)
        self.assertEqual(result, {})

    def test_numeric_values_converted_to_string(self):
        """Test that numeric values are converted to strings"""
        details = {"amount": 100.50, "count": 5}
        result = sanitize_audit_details(details)
        self.assertEqual(result["amount"], "100.5")
        self.assertEqual(result["count"], "5")

    def test_combined_sensitive_data(self):
        """Test handling of multiple sensitive fields together"""
        details = {
            "iban": "NL91ABNA0417164300",
            "password": "secret",
            "error": "Failed for test@test.com with IBAN DE89370400440532013000",
            "amount": 500,
        }
        result = sanitize_audit_details(details)

        self.assertEqual(result["iban"], "NL************4300")
        self.assertEqual(result["password"], "[REDACTED]")
        self.assertIn("[EMAIL REDACTED]", result["error"])
        self.assertIn("DE****************3000", result["error"])
        self.assertEqual(result["amount"], "500")


class TestSanitizeErrorForAuditWithIban(unittest.TestCase):
    """Tests for IBAN redaction in sanitize_error_for_audit()"""

    def test_iban_in_error_message_redacted(self):
        """Test that IBANs in error messages are redacted"""
        error = "Invalid IBAN: NL91ABNA0417164300"
        result = sanitize_error_for_audit(error)
        self.assertIn("NL************4300", result)
        self.assertNotIn("NL91ABNA0417164300", result)

    def test_multiple_ibans_redacted(self):
        """Test that multiple IBANs are all redacted"""
        error = "Transfer from NL91ABNA0417164300 to DE89370400440532013000 failed"
        result = sanitize_error_for_audit(error)
        self.assertIn("NL************4300", result)
        self.assertIn("DE****************3000", result)

    def test_iban_and_email_both_redacted(self):
        """Test that both IBANs and emails are redacted"""
        error = "User test@example.com IBAN NL91ABNA0417164300 invalid"
        result = sanitize_error_for_audit(error)
        self.assertIn("[EMAIL REDACTED]", result)
        self.assertIn("NL************4300", result)


class TestValidateJustification(unittest.TestCase):
    """Tests for validate_justification() function"""

    def test_valid_justification(self):
        """Test that valid justification passes"""
        result = validate_justification("This is a valid justification for the operation", "test_op")
        self.assertEqual(result, "This is a valid justification for the operation")

    def test_empty_justification_rejected(self):
        """Test that empty justification raises ValidationError"""
        with self.assertRaises(frappe.ValidationError) as context:
            validate_justification("", "test_op")
        self.assertIn("required", str(context.exception).lower())

    def test_none_justification_rejected(self):
        """Test that None justification raises ValidationError"""
        with self.assertRaises(frappe.ValidationError) as context:
            validate_justification(None, "test_op")
        self.assertIn("required", str(context.exception).lower())

    def test_short_justification_rejected(self):
        """Test that justification shorter than MIN_JUSTIFICATION_LENGTH is rejected"""
        short = "x" * (MIN_JUSTIFICATION_LENGTH - 1)
        with self.assertRaises(frappe.ValidationError) as context:
            validate_justification(short, "test_op")
        self.assertIn("at least", str(context.exception).lower())

    def test_exactly_min_length_accepted(self):
        """Test that justification exactly at MIN_JUSTIFICATION_LENGTH passes"""
        exact = "x" * MIN_JUSTIFICATION_LENGTH
        result = validate_justification(exact, "test_op")
        self.assertEqual(result, exact)

    def test_long_justification_truncated(self):
        """Test that justification over MAX_JUSTIFICATION_LENGTH is truncated"""
        long_text = "x" * (MAX_JUSTIFICATION_LENGTH + 100)
        result = validate_justification(long_text, "test_op")
        self.assertEqual(len(result), MAX_JUSTIFICATION_LENGTH)
        self.assertTrue(result.endswith("..."))

    def test_whitespace_only_rejected(self):
        """Test that whitespace-only justification is rejected"""
        with self.assertRaises(frappe.ValidationError):
            validate_justification("          ", "test_op")

    def test_whitespace_stripped(self):
        """Test that leading/trailing whitespace is stripped"""
        result = validate_justification("  Valid justification  ", "test_op")
        self.assertEqual(result, "Valid justification")

    def test_operation_name_in_error(self):
        """Test that operation name appears in error message"""
        with self.assertRaises(frappe.ValidationError) as context:
            validate_justification("short", "my_special_operation")
        self.assertIn("my_special_operation", str(context.exception))


class TestCanRequestSystemEscalation(unittest.TestCase):
    """Tests for can_request_system_escalation() function"""

    def test_administrator_can_escalate(self):
        """Test that Administrator user can always escalate"""
        result = can_request_system_escalation("Administrator")
        self.assertTrue(result)

    def test_allowed_roles_can_escalate(self):
        """Test that users with allowed roles can escalate"""
        # Test each allowed role
        for role in ESCALATION_ALLOWED_ROLES:
            with self.subTest(role=role):
                with patch("frappe.get_roles") as mock_get_roles:
                    mock_get_roles.return_value = [role]
                    result = can_request_system_escalation("test_user@example.com")
                    self.assertTrue(result, f"User with role {role} should be able to escalate")

    def test_user_without_allowed_roles_cannot_escalate(self):
        """Test that users without allowed roles cannot escalate"""
        with patch("frappe.get_roles") as mock_get_roles:
            mock_get_roles.return_value = ["Guest", "Website User"]
            result = can_request_system_escalation("regular_user@example.com")
            self.assertFalse(result)

    def test_current_user_used_when_none_provided(self):
        """Test that current session user is checked when no user provided"""
        with patch.object(frappe.session, "user", "Administrator"):
            result = can_request_system_escalation()
            self.assertTrue(result)

    def test_multiple_roles_with_one_allowed(self):
        """Test that user with multiple roles including one allowed can escalate"""
        with patch("frappe.get_roles") as mock_get_roles:
            mock_get_roles.return_value = [
                "Guest",
                "Website User",
                "Verenigingen Staff",
            ]
            result = can_request_system_escalation("user@example.com")
            self.assertTrue(result)

    def test_exception_during_role_check_returns_false(self):
        """Test that exceptions during role check result in False (fail-safe)"""
        with patch("frappe.get_roles") as mock_get_roles:
            mock_get_roles.side_effect = Exception("Database error")
            result = can_request_system_escalation("user@example.com")
            self.assertFalse(result)


class TestGetSystemUserForOperation(unittest.TestCase):
    """Tests for get_system_user_for_operation() function"""

    def test_returns_configured_creation_user(self):
        """Test that configured creation_user is returned"""
        with patch("frappe.get_single") as mock_get_single:
            mock_settings = MagicMock()
            mock_settings.creation_user = "system@example.com"
            mock_get_single.return_value = mock_settings

            with patch("frappe.db.exists") as mock_exists:
                mock_exists.return_value = True

                with patch("frappe.get_doc") as mock_get_doc:
                    mock_user = MagicMock()
                    mock_user.enabled = True
                    mock_get_doc.return_value = mock_user

                    result = get_system_user_for_operation("test operation")
                    self.assertEqual(result, "system@example.com")

    def test_raises_error_when_creation_user_not_configured(self):
        """Test that ConfigurationError is raised when creation_user is empty"""
        with patch("frappe.get_single") as mock_get_single:
            mock_settings = MagicMock()
            mock_settings.creation_user = None
            mock_get_single.return_value = mock_settings

            with self.assertRaises(ConfigurationError) as context:
                get_system_user_for_operation("test operation")

            self.assertIn("not configured", str(context.exception).lower())

    def test_raises_error_when_creation_user_does_not_exist(self):
        """Test that ConfigurationError is raised when creation_user doesn't exist"""
        with patch("frappe.get_single") as mock_get_single:
            mock_settings = MagicMock()
            mock_settings.creation_user = "nonexistent@example.com"
            mock_get_single.return_value = mock_settings

            with patch("frappe.db.exists") as mock_exists:
                mock_exists.return_value = False

                with self.assertRaises(ConfigurationError) as context:
                    get_system_user_for_operation("test operation")

                self.assertIn("does not exist", str(context.exception).lower())

    def test_raises_error_when_creation_user_is_disabled(self):
        """Test that ConfigurationError is raised when creation_user is disabled"""
        with patch("frappe.get_single") as mock_get_single:
            mock_settings = MagicMock()
            mock_settings.creation_user = "disabled@example.com"
            mock_get_single.return_value = mock_settings

            with patch("frappe.db.exists") as mock_exists:
                mock_exists.return_value = True

                with patch("frappe.get_doc") as mock_get_doc:
                    mock_user = MagicMock()
                    mock_user.enabled = False
                    mock_get_doc.return_value = mock_user

                    with self.assertRaises(ConfigurationError) as context:
                        get_system_user_for_operation("test operation")

                    self.assertIn("disabled", str(context.exception).lower())

    def test_no_fallback_to_administrator(self):
        """Test that function does NOT fall back to Administrator"""
        with patch("frappe.get_single") as mock_get_single:
            mock_settings = MagicMock()
            mock_settings.creation_user = ""
            mock_get_single.return_value = mock_settings

            with self.assertRaises(ConfigurationError):
                result = get_system_user_for_operation("test operation")
                # Should raise, not return "Administrator"
                self.assertNotEqual(result, "Administrator")

    def test_exception_wrapped_in_configuration_error(self):
        """Test that unexpected exceptions are wrapped in ConfigurationError"""
        with patch("frappe.get_single") as mock_get_single:
            mock_get_single.side_effect = Exception("Database connection failed")

            with self.assertRaises(ConfigurationError) as context:
                get_system_user_for_operation("test operation")

            self.assertIn("could not determine", str(context.exception).lower())


class TestEscalationAllowedRolesConfiguration(unittest.TestCase):
    """Tests for ESCALATION_ALLOWED_ROLES configuration"""

    def test_escalation_roles_is_frozenset(self):
        """Test that ESCALATION_ALLOWED_ROLES is immutable"""
        self.assertIsInstance(ESCALATION_ALLOWED_ROLES, frozenset)

    def test_system_manager_in_allowed_roles(self):
        """Test that System Manager is in allowed roles"""
        self.assertIn("System Manager", ESCALATION_ALLOWED_ROLES)

    def test_verenigingen_administrator_in_allowed_roles(self):
        """Test that Verenigingen Administrator is in allowed roles"""
        self.assertIn("Verenigingen Administrator", ESCALATION_ALLOWED_ROLES)

    def test_verenigingen_staff_in_allowed_roles(self):
        """Test that Verenigingen Staff is in allowed roles"""
        self.assertIn("Verenigingen Staff", ESCALATION_ALLOWED_ROLES)

    def test_guest_not_in_allowed_roles(self):
        """Test that Guest is NOT in allowed roles"""
        self.assertNotIn("Guest", ESCALATION_ALLOWED_ROLES)

    def test_website_user_not_in_allowed_roles(self):
        """Test that Website User is NOT in allowed roles"""
        self.assertNotIn("Website User", ESCALATION_ALLOWED_ROLES)


class TestJustificationLengthConfiguration(unittest.TestCase):
    """Tests for justification length configuration"""

    def test_min_length_is_reasonable(self):
        """Test that MIN_JUSTIFICATION_LENGTH is at least 5"""
        self.assertGreaterEqual(MIN_JUSTIFICATION_LENGTH, 5)

    def test_max_length_is_reasonable(self):
        """Test that MAX_JUSTIFICATION_LENGTH is reasonable"""
        self.assertGreaterEqual(MAX_JUSTIFICATION_LENGTH, 100)
        self.assertLessEqual(MAX_JUSTIFICATION_LENGTH, 10000)

    def test_min_less_than_max(self):
        """Test that MIN < MAX"""
        self.assertLess(MIN_JUSTIFICATION_LENGTH, MAX_JUSTIFICATION_LENGTH)


if __name__ == "__main__":
    unittest.main()
