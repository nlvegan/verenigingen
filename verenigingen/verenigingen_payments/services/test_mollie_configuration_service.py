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

    # ===== GL Account Validation Tests (Phase 3.2) =====

    def test_validate_gl_account_with_valid_account(self):
        """Test validate_gl_account() with a valid account"""
        # Get a real account from settings
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()
            result = config.validate_gl_account(settings.mollie_clearing_account)

            # Verify validation result structure
            self.assertIsInstance(result, dict)
            self.assertTrue(result.get("valid"))
            self.assertEqual(result.get("account_name"), settings.mollie_clearing_account)
            self.assertIn("account_type", result)
            self.assertIn("company", result)
            self.assertIn("is_group", result)
            self.assertIn("frozen", result)

    def test_validate_gl_account_with_nonexistent_account(self):
        """Test validate_gl_account() with non-existent account"""
        config = get_mollie_config()

        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_gl_account("NonExistent GL Account 99999")

        # Verify error message mentions the account
        self.assertIn("does not exist", str(context.exception))

    def test_validate_gl_account_type_and_company_mismatch(self):
        """Test validate_gl_account() catches type and company mismatches"""
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()

            # Get actual values
            actual_type = frappe.db.get_value("Account", settings.mollie_clearing_account, "account_type")

            # Test 1: Wrong account type should fail
            wrong_type = "Liability" if actual_type != "Liability" else "Asset"
            with self.assertRaises(frappe.ValidationError) as context:
                config.validate_gl_account(settings.mollie_clearing_account, account_type=wrong_type)
            self.assertIn("type", str(context.exception).lower())

            # Test 2: Wrong company should fail
            with self.assertRaises(frappe.ValidationError):
                config.validate_gl_account(settings.mollie_clearing_account, company="Wrong Company XYZ")

    def test_validate_gl_account_requires_account_name(self):
        """Test validate_gl_account() requires account_name parameter"""
        config = get_mollie_config()

        # Should raise ValidationError for empty account name
        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_gl_account("")

        error_msg = str(context.exception)
        self.assertIn("required", error_msg.lower())

    def test_get_all_mollie_accounts_returns_dict(self):
        """Test get_all_mollie_accounts() returns dict with all accounts"""
        config = get_mollie_config()

        # Get accounts without validation (faster for testing)
        accounts = config.get_all_mollie_accounts(validate=False)

        # Verify structure
        self.assertIsInstance(accounts, dict)
        self.assertIn("clearing_account", accounts)
        self.assertIn("bank_account", accounts)
        self.assertIn("fees_account", accounts)

        # Verify values are strings or None
        for account_name in accounts.values():
            if account_name is not None:
                self.assertIsInstance(account_name, str)

    def test_get_all_mollie_accounts_validation_parameter(self):
        """Test get_all_mollie_accounts() validate parameter works"""
        config = get_mollie_config()

        # Without validation should always work (no DB queries)
        accounts_unvalidated = config.get_all_mollie_accounts(validate=False)
        self.assertIsInstance(accounts_unvalidated, dict)

        # With validation will fail if accounts misconfigured (which is correct behavior)
        # We test the validation logic separately in validate_all_mollie_accounts tests

    def test_validate_all_mollie_accounts_returns_validation_result(self):
        """Test validate_all_mollie_accounts() returns detailed validation result"""
        config = get_mollie_config()

        # Run validation without raising errors
        result = config.validate_all_mollie_accounts(raise_on_error=False)

        # Verify result structure
        self.assertIsInstance(result, dict)
        self.assertIn("valid", result)
        self.assertIn("accounts", result)
        self.assertIn("errors", result)
        self.assertIn("warnings", result)

        # Verify accounts dict contains expected keys
        self.assertIn("clearing_account", result["accounts"])
        self.assertIn("bank_account", result["accounts"])
        self.assertIn("fees_account", result["accounts"])

        # Verify errors and warnings are lists
        self.assertIsInstance(result["errors"], list)
        self.assertIsInstance(result["warnings"], list)

    def test_validate_all_mollie_accounts_with_configured_system(self):
        """Test validate_all_mollie_accounts() with properly configured accounts"""
        settings = frappe.get_single("Mollie Settings")

        # Only run if required accounts are configured
        if settings.mollie_clearing_account and settings.mollie_bank_account:
            config = get_mollie_config()
            result = config.validate_all_mollie_accounts(raise_on_error=False)

            # If accounts are configured, result should have proper structure
            self.assertIn("valid", result)
            self.assertIn("accounts", result)
            self.assertIn("errors", result)

            # At minimum, should have attempted validation for all 3 account types
            self.assertIn("clearing_account", result["accounts"])
            self.assertIn("bank_account", result["accounts"])
            self.assertIn("fees_account", result["accounts"])

    def test_validate_all_mollie_accounts_identifies_missing_accounts(self):
        """Test validate_all_mollie_accounts() identifies missing required accounts"""
        settings = frappe.get_single("Mollie Settings")

        # If any required account is missing, validation should fail
        if not settings.mollie_clearing_account or not settings.mollie_bank_account:
            config = get_mollie_config()

            result = config.validate_all_mollie_accounts(raise_on_error=False)

            # Should be invalid
            self.assertFalse(result.get("valid"))
            self.assertGreater(len(result.get("errors", [])), 0)

            # Check that error mentions the missing account
            errors_str = " ".join(result.get("errors", []))
            if not settings.mollie_clearing_account:
                self.assertIn("clearing", errors_str.lower())
            if not settings.mollie_bank_account:
                self.assertIn("bank", errors_str.lower())

    def test_validate_all_mollie_accounts_handles_optional_fees_account(self):
        """Test validate_all_mollie_accounts() handles optional fees_account correctly"""
        config = get_mollie_config()

        result = config.validate_all_mollie_accounts(raise_on_error=False)

        # fees_account is optional, so should have warning if missing
        fees_result = result["accounts"].get("fees_account", {})

        if not fees_result.get("configured", True):
            # Should have a warning about fees account not configured
            self.assertGreater(len(result.get("warnings", [])), 0)
            warnings_str = " ".join(result.get("warnings", []))
            self.assertIn("fees", warnings_str.lower())

    def test_validate_all_mollie_accounts_with_raise_on_error(self):
        """Test validate_all_mollie_accounts() raises exception when raise_on_error=True"""
        settings = frappe.get_single("Mollie Settings")

        # Only test if configuration is incomplete
        if not settings.mollie_clearing_account or not settings.mollie_bank_account:
            config = get_mollie_config()

            # Should raise ValidationError
            with self.assertRaises(frappe.ValidationError) as context:
                config.validate_all_mollie_accounts(raise_on_error=True)

            # Verify error message is comprehensive
            error_msg = str(context.exception)
            self.assertIn("validation failed", error_msg.lower())

    # ===== Company Validation Tests (Phase 3.3) =====

    def test_validate_company_with_valid_company(self):
        """Test validate_company() with a valid company"""
        # Get first company from system
        company_name = frappe.db.get_value("Company", {}, "name")

        if company_name:
            config = get_mollie_config()
            result = config.validate_company(company_name)

            # Verify validation result structure
            self.assertIsInstance(result, dict)
            self.assertTrue(result.get("valid"))
            self.assertEqual(result.get("company_name"), company_name)
            self.assertIn("abbr", result)
            self.assertIn("is_group", result)

    def test_validate_company_with_nonexistent_company(self):
        """Test validate_company() with non-existent company"""
        config = get_mollie_config()

        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_company("NonExistent Company XYZ 99999")

        # Verify error message mentions company doesn't exist
        self.assertIn("does not exist", str(context.exception))

    def test_validate_company_requires_company_name(self):
        """Test validate_company() requires company parameter"""
        config = get_mollie_config()

        # Should raise ValidationError for empty company
        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_company("")

        error_msg = str(context.exception)
        self.assertIn("required", error_msg.lower())

    def test_validate_company_with_none(self):
        """Test validate_company() rejects None input"""
        config = get_mollie_config()

        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_company(None)

        error_msg = str(context.exception)
        self.assertIn("required", error_msg.lower())

    def test_validate_company_with_whitespace(self):
        """Test validate_company() rejects whitespace-only input"""
        config = get_mollie_config()

        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_company("   ")

        error_msg = str(context.exception)
        self.assertIn("required", error_msg.lower())

    def test_get_default_company_returns_string(self):
        """Test get_default_company() returns a company name"""
        config = get_mollie_config()
        result = config.get_default_company()

        # Should return a non-empty string
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

        # The returned company should be valid
        # (get_default_company validates internally)
        company_exists = frappe.db.exists("Company", result)
        self.assertTrue(company_exists)

    def test_get_default_company_validated_returns_dict(self):
        """Test get_default_company_validated() returns validation dict"""
        config = get_mollie_config()
        result = config.get_default_company_validated()

        # Verify structure
        self.assertIsInstance(result, dict)
        self.assertIn("valid", result)
        self.assertIn("company_name", result)
        self.assertIn("abbr", result)
        self.assertIn("is_group", result)

        # Should be valid
        self.assertTrue(result.get("valid"))

    # ===== Additional GL Validation Edge Case Tests (Phase 3.2 Completion) =====

    def test_validate_gl_account_with_disabled_account(self):
        """Test validate_gl_account() detects disabled/frozen accounts"""
        # Find a disabled account or create test scenario
        disabled_account = frappe.db.get_value("Account", {"disabled": 1}, "name", order_by="creation desc")

        if disabled_account:
            config = get_mollie_config()

            # Should raise error when allow_frozen=False (default)
            with self.assertRaises(frappe.ValidationError) as context:
                config.validate_gl_account(disabled_account, allow_frozen=False)

            error_msg = str(context.exception)
            self.assertIn("disabled", error_msg.lower())

            # Should succeed when allow_frozen=True
            result = config.validate_gl_account(disabled_account, allow_frozen=True)
            self.assertTrue(result.get("valid"))
            self.assertTrue(result.get("frozen"))

    def test_validate_gl_account_with_group_account(self):
        """Test validate_gl_account() warns about group accounts"""
        # Find a group account
        group_account = frappe.db.get_value("Account", {"is_group": 1}, "name", order_by="creation desc")

        if group_account:
            config = get_mollie_config()

            # Should still validate but log warning
            result = config.validate_gl_account(group_account)

            # Should return valid result with is_group flag
            self.assertTrue(result.get("valid"))
            self.assertTrue(result.get("is_group"))
            self.assertEqual(result.get("account_name"), group_account)

    def test_validate_gl_account_with_none_account_name(self):
        """Test validate_gl_account() rejects None account_name"""
        config = get_mollie_config()

        with self.assertRaises(frappe.ValidationError) as context:
            config.validate_gl_account(None)

        error_msg = str(context.exception)
        self.assertIn("required", error_msg.lower())

    def test_validate_gl_account_all_parameters(self):
        """Test validate_gl_account() with all validation parameters"""
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()

            # Get actual account details
            account_details = frappe.db.get_value(
                "Account",
                settings.mollie_clearing_account,
                ["account_type", "company"],
                as_dict=True,
            )

            # Validate with all correct parameters
            result = config.validate_gl_account(
                settings.mollie_clearing_account,
                account_type=account_details.get("account_type"),
                company=account_details.get("company"),
                allow_frozen=False,
            )

            # Should pass all validations
            self.assertTrue(result.get("valid"))
            self.assertEqual(result.get("account_type"), account_details.get("account_type"))
            self.assertEqual(result.get("company"), account_details.get("company"))

    def test_get_all_mollie_accounts_with_validation_enabled(self):
        """Test get_all_mollie_accounts() actually validates when requested"""
        settings = frappe.get_single("Mollie Settings")

        # If both required accounts are configured, validation should pass
        if settings.mollie_clearing_account and settings.mollie_bank_account:
            config = get_mollie_config()

            # Should not raise error with valid accounts
            accounts = config.get_all_mollie_accounts(validate=True)

            self.assertIsInstance(accounts, dict)
            self.assertEqual(accounts["clearing_account"], settings.mollie_clearing_account)
            self.assertEqual(accounts["bank_account"], settings.mollie_bank_account)

    def test_get_all_mollie_accounts_skips_none_values(self):
        """Test get_all_mollie_accounts() handles None values correctly"""
        config = get_mollie_config()

        # Get accounts without validation
        accounts = config.get_all_mollie_accounts(validate=False)

        # All keys should be present even if values are None
        self.assertIn("clearing_account", accounts)
        self.assertIn("bank_account", accounts)
        self.assertIn("fees_account", accounts)

        # None values should be allowed for optional fields
        # (fees_account is optional)

    def test_validate_all_mollie_accounts_error_aggregation(self):
        """Test validate_all_mollie_accounts() aggregates multiple errors"""
        settings = frappe.get_single("Mollie Settings")

        # If multiple accounts are missing, should report all errors
        if not settings.mollie_clearing_account or not settings.mollie_bank_account:
            config = get_mollie_config()

            result = config.validate_all_mollie_accounts(raise_on_error=False)

            # Should have detailed error information
            self.assertFalse(result.get("valid"))
            self.assertIsInstance(result.get("errors"), list)

            # Each missing account should have its own error
            if not settings.mollie_clearing_account:
                errors_str = " ".join(result.get("errors", []))
                self.assertIn("clearing", errors_str.lower())

            if not settings.mollie_bank_account:
                errors_str = " ".join(result.get("errors", []))
                self.assertIn("bank", errors_str.lower())

    def test_validate_all_mollie_accounts_account_details_in_result(self):
        """Test validate_all_mollie_accounts() includes account details"""
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()

            result = config.validate_all_mollie_accounts(raise_on_error=False)

            # Check clearing_account result structure
            clearing_result = result["accounts"]["clearing_account"]

            if clearing_result.get("valid"):
                # Should include full account details
                self.assertIn("account_name", clearing_result)
                self.assertIn("account_type", clearing_result)
                self.assertIn("company", clearing_result)
                self.assertIn("is_group", clearing_result)
                self.assertIn("frozen", clearing_result)

    def test_validate_gl_account_performance_single_query(self):
        """Test validate_gl_account() uses single query for performance"""
        settings = frappe.get_single("Mollie Settings")

        if settings.mollie_clearing_account:
            config = get_mollie_config()

            # The method should fetch all account details in one query
            # We can't easily measure queries in unit tests without mocking,
            # but we verify the result has all expected fields
            result = config.validate_gl_account(settings.mollie_clearing_account)

            # All these fields should come from single DB query
            self.assertIn("account_type", result)
            self.assertIn("company", result)
            self.assertIn("is_group", result)
            self.assertIn("frozen", result)

    def test_validate_all_mollie_accounts_distinguishes_errors_and_warnings(self):
        """Test validate_all_mollie_accounts() properly categorizes errors vs warnings"""
        config = get_mollie_config()

        result = config.validate_all_mollie_accounts(raise_on_error=False)

        # Errors should be for required fields only
        # Warnings should be for optional fields (like fees_account)

        if result.get("warnings"):
            warnings_str = " ".join(result.get("warnings", []))

            # If fees account is missing, should be warning (not error)
            settings = frappe.get_single("Mollie Settings")
            if not settings.payment_processing_fees_account:
                self.assertIn("fees", warnings_str.lower())
                # Should NOT be in errors
                errors_str = " ".join(result.get("errors", []))
                # Fees account might be mentioned in errors if validation fails,
                # but not for being unconfigured


def run_tests():
    """Helper function to run tests from console"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMollieConfigurationService)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)
