# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for SEPA Sandbox Mode utility.

Tests the SEPASandbox class used for safe SEPA testing that prevents
accidental production bank submissions.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.sepa_sandbox import SandboxCheckResult, SEPASandbox, get_sandbox


class TestSEPASandbox(FrappeTestCase):
    """Test suite for SEPASandbox class."""

    def setUp(self):
        """Set up test fixtures."""
        self.sandbox = SEPASandbox()
        self.original_setting = frappe.conf.get("sepa_sandbox_mode")

    def tearDown(self):
        """Restore original sandbox mode setting."""
        if self.original_setting is not None:
            frappe.conf.sepa_sandbox_mode = self.original_setting
        elif hasattr(frappe.conf, "sepa_sandbox_mode"):
            delattr(frappe.conf, "sepa_sandbox_mode")

    def test_sandbox_mode_disabled_by_default(self):
        """Sandbox mode should be disabled by default."""
        frappe.conf.sepa_sandbox_mode = False
        self.assertFalse(self.sandbox.is_sandbox_mode())

    def test_sandbox_mode_enabled_when_configured(self):
        """Sandbox mode should be enabled when configured."""
        frappe.conf.sepa_sandbox_mode = True
        self.assertTrue(self.sandbox.is_sandbox_mode())

    def test_sandbox_mode_disabled_when_not_set(self):
        """Sandbox mode should be disabled when not configured at all."""
        if hasattr(frappe.conf, "sepa_sandbox_mode"):
            delattr(frappe.conf, "sepa_sandbox_mode")
        self.assertFalse(self.sandbox.is_sandbox_mode())

    def test_msg_id_prefixed_in_sandbox_mode(self):
        """Message IDs should be prefixed with TEST- in sandbox mode."""
        frappe.conf.sepa_sandbox_mode = True
        result = self.sandbox.get_sandbox_msg_id("BATCH-001")
        self.assertEqual(result, "TEST-BATCH-001")

    def test_msg_id_unchanged_in_production_mode(self):
        """Message IDs should be unchanged in production mode."""
        frappe.conf.sepa_sandbox_mode = False
        result = self.sandbox.get_sandbox_msg_id("BATCH-001")
        self.assertEqual(result, "BATCH-001")

    def test_msg_id_not_double_prefixed(self):
        """Already prefixed IDs should not be prefixed again."""
        frappe.conf.sepa_sandbox_mode = True
        result = self.sandbox.get_sandbox_msg_id("TEST-BATCH-001")
        self.assertEqual(result, "TEST-BATCH-001")

    def test_upload_blocked_in_sandbox_mode(self):
        """Bank upload should be blocked in sandbox mode."""
        frappe.conf.sepa_sandbox_mode = True
        result = self.sandbox.check_upload_allowed()
        self.assertFalse(result.allowed)
        self.assertTrue(result.sandbox_mode)
        self.assertIn("sandbox", result.message.lower())

    def test_upload_allowed_in_production_mode(self):
        """Bank upload should be allowed in production mode."""
        frappe.conf.sepa_sandbox_mode = False
        result = self.sandbox.check_upload_allowed()
        self.assertTrue(result.allowed)
        self.assertFalse(result.sandbox_mode)

    def test_sandbox_check_result_dataclass(self):
        """SandboxCheckResult should be a proper dataclass with expected fields."""
        result = SandboxCheckResult(allowed=True, message="Test", sandbox_mode=False)
        self.assertTrue(result.allowed)
        self.assertEqual(result.message, "Test")
        self.assertFalse(result.sandbox_mode)

    def test_generate_test_iban_valid_format_nl(self):
        """Generated Dutch test IBAN should have valid format."""
        iban = self.sandbox.generate_test_iban("NL")
        self.assertTrue(iban.startswith("NL"))
        self.assertEqual(len(iban), 18)  # Dutch IBANs are 18 chars

    def test_generate_test_iban_valid_format_de(self):
        """Generated German test IBAN should have valid format."""
        iban = self.sandbox.generate_test_iban("DE")
        self.assertTrue(iban.startswith("DE"))
        self.assertEqual(len(iban), 22)  # German IBANs are 22 chars

    def test_generate_test_iban_valid_format_be(self):
        """Generated Belgian test IBAN should have valid format."""
        iban = self.sandbox.generate_test_iban("BE")
        self.assertTrue(iban.startswith("BE"))
        self.assertEqual(len(iban), 16)  # Belgian IBANs are 16 chars

    def test_generate_test_iban_different_countries(self):
        """Should generate test IBANs for different countries."""
        nl_iban = self.sandbox.generate_test_iban("NL")
        de_iban = self.sandbox.generate_test_iban("DE")
        self.assertTrue(nl_iban.startswith("NL"))
        self.assertTrue(de_iban.startswith("DE"))

    def test_generate_test_iban_lowercase_country(self):
        """Should handle lowercase country codes."""
        iban = self.sandbox.generate_test_iban("nl")
        self.assertTrue(iban.startswith("NL"))

    def test_generate_test_iban_unknown_country(self):
        """Should generate fallback IBAN for unknown country codes."""
        iban = self.sandbox.generate_test_iban("XX")
        self.assertTrue(iban.startswith("XX"))
        # Fallback format: country + 2 check digits + 16 digits = 20 chars
        self.assertEqual(len(iban), 20)

    def test_generate_test_iban_uniqueness(self):
        """Generated IBANs should be unique (random suffix)."""
        ibans = [self.sandbox.generate_test_iban("NL") for _ in range(10)]
        # All should be unique (though technically there's a tiny chance of collision)
        unique_ibans = set(ibans)
        self.assertGreater(len(unique_ibans), 1)

    def test_singleton_accessor(self):
        """get_sandbox() should return singleton instance."""
        s1 = get_sandbox()
        s2 = get_sandbox()
        self.assertIs(s1, s2)

    def test_singleton_is_sepa_sandbox_instance(self):
        """get_sandbox() should return SEPASandbox instance."""
        sandbox = get_sandbox()
        self.assertIsInstance(sandbox, SEPASandbox)
