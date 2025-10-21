"""
Unit tests for MollieConfigurationService

Tests the cached configuration service that replaced direct frappe.get_single() calls.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
    MollieConfigurationService,
    get_mollie_config,
)


class TestMollieConfigurationService(FrappeTestCase):
    """Test MollieConfigurationService functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Clear cache before each test
        MollieConfigurationService.clear_cache()

    def tearDown(self):
        """Clean up after tests"""
        MollieConfigurationService.clear_cache()

    def test_get_mollie_config_returns_service(self):
        """Test that get_mollie_config() returns the service class"""
        config = get_mollie_config()
        self.assertEqual(config, MollieConfigurationService)

    def test_get_settings_returns_dict(self):
        """Test that get_settings() returns a dictionary"""
        config = get_mollie_config()
        settings = config.get_settings()

        self.assertIsInstance(settings, dict)
        # Should have the expected fields
        self.assertIn("test_mode", settings)
        self.assertIn("enable_backend_api", settings)
        self.assertIn("enable_subscriptions", settings)

    def test_get_settings_returns_copy(self):
        """Test that get_settings() returns a copy, not the cached dict"""
        config = get_mollie_config()

        settings1 = config.get_settings()
        settings2 = config.get_settings()

        # Should be equal but not the same object
        self.assertEqual(settings1, settings2)
        self.assertIsNot(settings1, settings2)

    def test_settings_are_cached(self):
        """Test that settings are cached between calls"""
        config = get_mollie_config()

        # First call loads from DB
        settings1 = config.get_settings()

        # Second call should use cache (same values)
        settings2 = config.get_settings()

        self.assertEqual(settings1, settings2)

    def test_clear_cache_works(self):
        """Test that clear_cache() actually clears the cache"""
        config = get_mollie_config()

        # Load settings into cache
        config.get_settings()

        # Clear cache
        config.clear_cache()

        # Next call should reload from DB (we can't easily test this,
        # but at least verify it doesn't error)
        settings = config.get_settings()
        self.assertIsInstance(settings, dict)

    def test_is_test_mode_returns_bool(self):
        """Test is_test_mode() returns boolean"""
        config = get_mollie_config()
        result = config.is_test_mode()

        self.assertIsInstance(result, bool)

    def test_is_backend_api_enabled_returns_bool(self):
        """Test is_backend_api_enabled() returns boolean"""
        config = get_mollie_config()
        result = config.is_backend_api_enabled()

        self.assertIsInstance(result, bool)

    def test_is_subscriptions_enabled_returns_bool(self):
        """Test is_subscriptions_enabled() returns boolean"""
        config = get_mollie_config()
        result = config.is_subscriptions_enabled()

        self.assertIsInstance(result, bool)

    def test_get_dues_payment_creation_mode_returns_valid_value(self):
        """Test get_dues_payment_creation_mode() returns valid mode"""
        config = get_mollie_config()
        result = config.get_dues_payment_creation_mode()

        self.assertIsInstance(result, str)
        self.assertIn(result, ["Bank Transaction", "Payment Entry"])

    def test_get_fees_account_optional_returns_string_or_none(self):
        """Test get_fees_account_optional() returns string or None"""
        config = get_mollie_config()
        result = config.get_fees_account_optional()

        # Should be either a string or None
        self.assertTrue(result is None or isinstance(result, str))

    def test_validate_configuration_returns_dict(self):
        """Test validate_configuration() returns expected structure"""
        config = get_mollie_config()
        result = config.validate_configuration()

        self.assertIsInstance(result, dict)
        self.assertIn("valid", result)
        self.assertIn("missing_fields", result)
        self.assertIn("warnings", result)

        self.assertIsInstance(result["valid"], bool)
        self.assertIsInstance(result["missing_fields"], list)
        self.assertIsInstance(result["warnings"], list)

    def test_get_clearing_account_with_configuration(self):
        """Test get_clearing_account() when configured"""
        # Get the actual settings to check if clearing account is configured
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()
            result = config.get_clearing_account()

            self.assertIsInstance(result, str)
            self.assertEqual(result, settings.mollie_clearing_account)
        else:
            # If not configured, should raise ValidationError
            config = get_mollie_config()
            with self.assertRaises(frappe.ValidationError):
                config.get_clearing_account()

    def test_get_bank_account_gl_with_configuration(self):
        """Test get_bank_account_gl() when configured"""
        # Get the actual settings to check if bank account is configured
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_bank_account:
            config = get_mollie_config()
            result = config.get_bank_account_gl()

            self.assertIsInstance(result, str)
            self.assertEqual(result, settings.mollie_bank_account)
        else:
            # If not configured, should raise ValidationError
            config = get_mollie_config()
            with self.assertRaises(frappe.ValidationError):
                config.get_bank_account_gl()

    def test_get_fees_account_raises_when_not_configured(self):
        """Test get_fees_account() raises error when not configured"""
        # Get the actual settings
        settings = frappe.get_single("Mollie Settings")

        if not settings.payment_processing_fees_account:
            config = get_mollie_config()
            with self.assertRaises(frappe.ValidationError):
                config.get_fees_account()


def run_tests():
    """Helper function to run tests from console"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMollieConfigurationService)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)
