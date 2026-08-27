"""
Unit tests for MollieConfigurationService

Tests the cached configuration service that replaced direct frappe.get_single() calls.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.mollie_account_fixtures import (
    ensure_mollie_gl_accounts,
    provisioned_mollie_settings,
)
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
        """A fully configured system validates clean.

        Used to be wrapped in `if settings.mollie_clearing_account and
        settings.mollie_bank_account:` and so asserted NOTHING on a site where the
        Single was unconfigured -- which was every test site, since nothing
        provisioned it. It now provisions the configuration it is about.
        """
        with provisioned_mollie_settings():
            result = get_mollie_config().validate_all_mollie_accounts(raise_on_error=False)

        self.assertTrue(result["valid"], f"a provisioned system must validate: {result['errors']}")
        for purpose in ("clearing_account", "bank_account", "fees_account"):
            self.assertIn(purpose, result["accounts"])
            self.assertTrue(
                result["accounts"][purpose].get("valid"), f"{purpose}: {result['accounts'][purpose]}"
            )

    def test_validate_all_mollie_accounts_identifies_missing_accounts(self):
        """Each required account, blanked deliberately, is named in the errors.

        Previously ran only `if not settings.mollie_clearing_account or not
        settings.mollie_bank_account`, i.e. only on an unconfigured site, and then
        asserted whichever half happened to be missing. Now it blanks each one in
        turn and asserts that specific error.
        """
        for field, expected in (
            ("mollie_clearing_account", "clearing"),
            ("mollie_bank_account", "bank"),
        ):
            with self.subTest(missing=field):
                with provisioned_mollie_settings(**{field: ""}):
                    result = get_mollie_config().validate_all_mollie_accounts(raise_on_error=False)
                self.assertFalse(result["valid"], f"blanking {field} must invalidate the configuration")
                self.assertIn(expected, " ".join(result["errors"]).lower())

    def test_validate_all_mollie_accounts_handles_optional_fees_account(self):
        """A missing fees account is a WARNING, not an error -- it is optional.

        The `if not fees_result.get("configured", True):` this replaces meant the
        body ran only when the fees account happened to be unset, and the "optional
        means still valid" half was never asserted at all.
        """
        with provisioned_mollie_settings(payment_processing_fees_account=""):
            result = get_mollie_config().validate_all_mollie_accounts(raise_on_error=False)

        self.assertTrue(result["valid"], "a missing fees account must not invalidate the configuration")
        self.assertFalse(result["accounts"]["fees_account"].get("configured", True))
        self.assertIn("fees", " ".join(result["warnings"]).lower())

    def test_validate_all_mollie_accounts_with_raise_on_error(self):
        """`raise_on_error=True` raises on an incomplete configuration, and does
        NOT raise on a complete one.

        Both halves matter and neither was asserted: the body ran only `if not
        settings.mollie_clearing_account or not settings.mollie_bank_account`, so on
        a configured site the test was a no-op, and the "does not raise" case had no
        coverage anywhere.
        """
        with provisioned_mollie_settings(mollie_clearing_account=""):
            with self.assertRaises(frappe.ValidationError) as context:
                get_mollie_config().validate_all_mollie_accounts(raise_on_error=True)
        self.assertIn("validation failed", str(context.exception).lower())

        with provisioned_mollie_settings():
            # Must not raise. Without this half, the assertion above is equally
            # consistent with "raises when incomplete" and "always raises".
            result = get_mollie_config().validate_all_mollie_accounts(raise_on_error=True)
        self.assertTrue(result["valid"])

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


class TestMollieAccountCoherence(FrappeTestCase):
    """The accounts must belong to the company this app books into (#540).

    `validate_all_mollie_accounts` validated each account in isolation and so
    accepted veg11's live state:

        Verenigingen Settings.company    = 'Nederlandse Vereniging voor Veganisme'
        mollie_bank_account     -> company 'TEST-Payment-Integration-Company'
        mollie_clearing_account -> company 'TEST-Payment-Integration-Company'

    Settlements are booked into `Verenigingen Settings.company`, so those accounts
    post into a leaked test company's ledger. The deployment step recorded for #538
    was "split these two fields", which against those values would have switched on
    a live pipeline doing exactly that.

    Every test provisions its own configuration, so none depends on ambient Singles
    state.
    """

    def setUp(self):
        MollieConfigurationService.clear_cache()
        self.addCleanup(MollieConfigurationService.clear_cache)

    def _validate(self, **overrides):
        with provisioned_mollie_settings(**overrides):
            return get_mollie_config().validate_all_mollie_accounts(raise_on_error=False)

    def _foreign_account(self, company, account_type="Bank"):
        """A leaf account in some OTHER company than `company`.

        ONE query. Picking a company and then looking inside it made an earlier
        version of this test skip: the company it happened to choose on test_site_1
        had no bank account, and a test that skips proves as much as one that never
        ran.
        """
        return frappe.db.get_value(
            "Account",
            {"company": ["!=", company], "account_type": account_type, "is_group": 0},
            "name",
        )

    def test_a_provisioned_configuration_is_valid(self):
        """The control. Without it, every assertion below is equally consistent with
        "the guard fires" and "validation now rejects everything"."""
        result = self._validate()
        self.assertTrue(
            result["valid"],
            f"a coherent provisioned configuration must validate; errors: {result['errors']}",
        )
        self.assertEqual(result["errors"], [])

    def test_one_account_configured_as_both_sides_is_still_valid(self):
        """clearing == bank must NOT be rejected.

        `_book_settlement_payout` treats one account as a supported configuration --
        with no intermediate there is nothing to drain -- and
        `test_one_account_configured_as_both_sides_needs_no_payout_leg` asserts the
        resulting accounting. An earlier version of this guard rejected it, which
        made the two settlement pipelines disagree about the same config and produced
        the per-run Error Log row that code deliberately avoids. veg11 is in this
        configuration today.
        """
        accounts = ensure_mollie_gl_accounts()
        result = self._validate(mollie_bank_account=accounts["clearing_account"])
        self.assertTrue(
            result["valid"],
            f"one account as both sides is supported, not an error; got {result['errors']}",
        )

    def test_a_bank_account_in_another_company_is_an_error(self):
        accounts = ensure_mollie_gl_accounts()
        foreign = self._foreign_account(accounts["company"])
        self.assertTrue(foreign, "precondition: the site needs a leaf Bank account elsewhere")

        result = self._validate(mollie_bank_account=foreign)
        self.assertFalse(result["valid"], "an account outside the booking company must be refused")
        errors = " ".join(result["errors"]).lower()
        self.assertIn("bank account", errors)
        self.assertIn("booked into", errors)

    def test_a_clearing_account_in_another_company_is_an_error(self):
        accounts = ensure_mollie_gl_accounts()
        foreign = self._foreign_account(accounts["company"])
        self.assertTrue(foreign)

        result = self._validate(mollie_clearing_account=foreign)
        self.assertFalse(result["valid"])
        self.assertIn("clearing account", " ".join(result["errors"]).lower())

    def test_a_fees_account_in_another_company_is_an_error(self):
        """The fees account is in scope, contrary to an earlier version of this guard.

        `_create_mollie_fee_entry` derives the Journal Entry's company from the
        CLEARING account and stamps the fees account into the same entry, so a
        cross-company fees account is rejected by ERPNext at posting time --
        measured: "Account Tax Expense - _TC2 does not belong to Company
        TEST-Payment-Integration-Company". Same coherence class, same rejection;
        catching it here costs one comparison.
        """
        accounts = ensure_mollie_gl_accounts()
        foreign = self._foreign_account(accounts["company"], account_type="")
        foreign = foreign or frappe.db.get_value(
            "Account", {"company": ["!=", accounts["company"]], "is_group": 0}, "name"
        )
        self.assertTrue(foreign, "precondition: the site needs a leaf account in another company")

        result = self._validate(payment_processing_fees_account=foreign)
        self.assertFalse(result["valid"], "a fees account outside the booking company must be refused")
        self.assertIn("fees account", " ".join(result["errors"]).lower())

    def test_the_coherence_errors_also_raise_when_asked_to(self):
        """`raise_on_error=True` is what a pre-flight check uses, so the new errors
        have to participate in it and not only in the result dict."""
        accounts = ensure_mollie_gl_accounts()
        foreign = self._foreign_account(accounts["company"])
        self.assertTrue(foreign)
        with provisioned_mollie_settings(mollie_bank_account=foreign):
            with self.assertRaises(frappe.ValidationError):
                get_mollie_config().validate_all_mollie_accounts(raise_on_error=True)

    def test_skipping_the_settlement_account_skips_only_that_account(self):
        """`skip_settlement_account=True` (virtual-account payments) must ignore a
        foreign BANK account but still catch a foreign CLEARING one -- both callers
        that pass it resolve the clearing account."""
        accounts = ensure_mollie_gl_accounts()
        foreign = self._foreign_account(accounts["company"])
        self.assertTrue(foreign)

        with provisioned_mollie_settings(mollie_bank_account=foreign):
            skipped = get_mollie_config().validate_all_mollie_accounts(
                raise_on_error=False, skip_settlement_account=True
            )
        self.assertNotIn("booked into", " ".join(skipped["errors"]).lower())

        with provisioned_mollie_settings(mollie_clearing_account=foreign):
            still_caught = get_mollie_config().validate_all_mollie_accounts(
                raise_on_error=False, skip_settlement_account=True
            )
        self.assertFalse(still_caught["valid"], "a foreign clearing account must still be refused")


if __name__ == "__main__":
    unittest.main()
