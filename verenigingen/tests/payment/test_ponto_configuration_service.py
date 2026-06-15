"""
Tests for Ponto Configuration Service.

Integration tests for PontoConfigurationService: real Ponto Settings singleton,
real Frappe cache (cache hit/miss/clear), permission gating, client-id resolution,
account-mapping helpers, company resolution, and config validation.

No external HTTP is involved here (configuration_service does not call Ponto's API),
so every test exercises real code paths against a real (backed-up) singleton.

Usage:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_ponto_configuration_service
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.verenigingen_payments.ponto.services.configuration_service import (
    PontoConfigurationService,
    get_ponto_config,
)

TEST_IBAN_A = "NL91ABNA0417164300"
TEST_IBAN_B = "NL20INGB0001234567"
ACCOUNT_ID_A = "11111111-1111-1111-1111-111111111111"
ACCOUNT_ID_B = "22222222-2222-2222-2222-222222222222"


class TestPontoConfigurationService(FrappeTestCase):
    """Integration tests for PontoConfigurationService."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._singleton_backup = SingletonBackup("Ponto Settings")
        cls._singleton_backup.backup()
        cls._setup_test_settings()

    @classmethod
    def tearDownClass(cls):
        cls._singleton_backup.restore()
        PontoConfigurationService.clear_cache()
        super().tearDownClass()

    @classmethod
    def _setup_test_settings(cls):
        """Configure a Ponto Settings singleton with two account mappings."""
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_mode = 1
        settings.use_ibanity_mtls = 0
        settings.sandbox_client_id = "test_sandbox_client"
        settings.sandbox_client_secret = "test_sandbox_secret"
        settings.production_client_id = "test_prod_client"
        settings.production_client_secret = "test_prod_secret"
        settings.organization_id = "org-test-001"
        settings.auto_sync_enabled = 1
        settings.sync_interval_hours = 6
        settings.enable_webhooks = 1

        settings.set("bank_account_mappings", [])
        settings.append(
            "bank_account_mappings",
            {
                "enabled": 1,
                "ponto_account_id": ACCOUNT_ID_A,
                "ponto_account_name": "Checking",
                "ponto_iban": TEST_IBAN_A,
                "bank_account": None,
            },
        )
        settings.append(
            "bank_account_mappings",
            {
                "enabled": 0,
                "ponto_account_id": ACCOUNT_ID_B,
                "ponto_account_name": "Savings",
                "ponto_iban": TEST_IBAN_B,
                "bank_account": None,
            },
        )
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        # Tests run as Administrator (System Manager) — passes permission gate.
        PontoConfigurationService.clear_cache()

    def tearDown(self):
        PontoConfigurationService.clear_cache()
        super().tearDown()

    # -------------------------------------------------------------------------
    # Factory / basic access
    # -------------------------------------------------------------------------

    def test_get_ponto_config_returns_service_class(self):
        """Factory returns the service class (all methods are classmethods)."""
        config = get_ponto_config()
        self.assertIs(config, PontoConfigurationService)

    def test_get_settings_returns_expected_fields(self):
        """get_settings exposes the cached non-sensitive config fields."""
        settings = PontoConfigurationService.get_settings()
        self.assertTrue(settings["sandbox_mode"])
        self.assertEqual(settings["sandbox_client_id"], "test_sandbox_client")
        self.assertEqual(settings["organization_id"], "org-test-001")
        self.assertIn("bank_account_mappings", settings)
        # Secrets must never be cached.
        self.assertNotIn("sandbox_client_secret", settings)
        self.assertNotIn("production_client_secret", settings)

    # -------------------------------------------------------------------------
    # Cache behaviour (real Frappe cache)
    # -------------------------------------------------------------------------

    def test_get_settings_caches_after_first_call(self):
        """First call is a cache miss; the value is then stored in cache."""
        cache = frappe.cache()
        cache.delete_value(PontoConfigurationService.CACHE_KEY)
        self.assertIsNone(cache.get_value(PontoConfigurationService.CACHE_KEY))

        PontoConfigurationService.get_settings()

        # Now populated.
        self.assertIsNotNone(cache.get_value(PontoConfigurationService.CACHE_KEY))

    def test_get_settings_returns_immutable_copy(self):
        """Mutating a returned dict must not corrupt the cached value."""
        first = PontoConfigurationService.get_settings()
        first["organization_id"] = "MUTATED"
        second = PontoConfigurationService.get_settings()
        self.assertEqual(second["organization_id"], "org-test-001")

    def test_cache_hit_does_not_reflect_uncommitted_db_change(self):
        """A cached read returns the cached value, not a fresh DB read."""
        PontoConfigurationService.get_settings()  # warm cache
        # Direct DB change WITHOUT clearing cache.
        frappe.db.set_value(
            "Ponto Settings", "Ponto Settings", "organization_id", "changed-in-db",
            update_modified=False,
        )
        cached = PontoConfigurationService.get_settings()
        self.assertEqual(cached["organization_id"], "org-test-001")
        # After clearing cache, the new value is visible.
        PontoConfigurationService.clear_cache()
        fresh = PontoConfigurationService.get_settings()
        self.assertEqual(fresh["organization_id"], "changed-in-db")
        # Restore.
        frappe.db.set_value(
            "Ponto Settings", "Ponto Settings", "organization_id", "org-test-001",
            update_modified=False,
        )
        PontoConfigurationService.clear_cache()

    def test_clear_cache_removes_entry(self):
        PontoConfigurationService.get_settings()
        PontoConfigurationService.clear_cache()
        self.assertIsNone(frappe.cache().get_value(PontoConfigurationService.CACHE_KEY))

    # -------------------------------------------------------------------------
    # Permission gating
    # -------------------------------------------------------------------------

    def test_get_settings_denied_for_unauthorized_user(self):
        """A user without an allowed role is rejected with PermissionError."""
        original = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaises(frappe.PermissionError):
                PontoConfigurationService.get_settings()
        finally:
            frappe.set_user(original)

    # -------------------------------------------------------------------------
    # Client ID resolution
    # -------------------------------------------------------------------------

    def test_is_sandbox_mode_true(self):
        self.assertTrue(PontoConfigurationService.is_sandbox_mode())

    def test_get_active_client_id_sandbox(self):
        self.assertEqual(PontoConfigurationService.get_active_client_id(), "test_sandbox_client")

    def test_get_active_client_id_production(self):
        """When sandbox_mode is off, the production client id is returned."""
        frappe.db.set_value(
            "Ponto Settings", "Ponto Settings", "sandbox_mode", 0, update_modified=False
        )
        PontoConfigurationService.clear_cache()
        try:
            self.assertEqual(PontoConfigurationService.get_active_client_id(), "test_prod_client")
        finally:
            frappe.db.set_value(
                "Ponto Settings", "Ponto Settings", "sandbox_mode", 1, update_modified=False
            )
            PontoConfigurationService.clear_cache()

    def test_get_active_client_id_missing_throws(self):
        """Missing client id for the active environment throws a config error."""
        frappe.db.set_value(
            "Ponto Settings", "Ponto Settings", "sandbox_client_id", "", update_modified=False
        )
        PontoConfigurationService.clear_cache()
        try:
            with self.assertRaises(frappe.ValidationError):
                PontoConfigurationService.get_active_client_id()
        finally:
            frappe.db.set_value(
                "Ponto Settings", "Ponto Settings", "sandbox_client_id",
                "test_sandbox_client", update_modified=False,
            )
            PontoConfigurationService.clear_cache()

    def test_get_active_client_secret_reads_from_db(self):
        """Client secret is fetched directly from the settings doc (not cached)."""
        secret = PontoConfigurationService.get_active_client_secret()
        self.assertEqual(secret, "test_sandbox_secret")

    # -------------------------------------------------------------------------
    # Account-mapping helpers
    # -------------------------------------------------------------------------

    def test_get_enabled_account_mappings(self):
        enabled = PontoConfigurationService.get_enabled_account_mappings()
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0]["ponto_account_id"], ACCOUNT_ID_A)

    def test_get_all_account_mappings(self):
        self.assertEqual(len(PontoConfigurationService.get_all_account_mappings()), 2)

    def test_get_mapping_for_ponto_account_found(self):
        mapping = PontoConfigurationService.get_mapping_for_ponto_account(ACCOUNT_ID_B)
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["ponto_iban"], TEST_IBAN_B)

    def test_get_mapping_for_ponto_account_not_found(self):
        self.assertIsNone(PontoConfigurationService.get_mapping_for_ponto_account("nope"))

    def test_get_bank_account_for_disabled_mapping_returns_none(self):
        """Disabled mapping (B) yields no bank account even if one were linked."""
        self.assertIsNone(
            PontoConfigurationService.get_bank_account_for_ponto_account(ACCOUNT_ID_B)
        )

    def test_get_bank_account_for_enabled_unmapped_returns_none(self):
        """Enabled mapping with no bank_account linked returns None."""
        self.assertIsNone(
            PontoConfigurationService.get_bank_account_for_ponto_account(ACCOUNT_ID_A)
        )

    def test_get_first_enabled_ponto_account_id(self):
        self.assertEqual(
            PontoConfigurationService.get_first_enabled_ponto_account_id(), ACCOUNT_ID_A
        )

    def test_get_first_enabled_bank_account_none_when_unlinked(self):
        self.assertIsNone(PontoConfigurationService.get_first_enabled_bank_account())

    # -------------------------------------------------------------------------
    # Feature flags / scalar getters
    # -------------------------------------------------------------------------

    def test_is_webhooks_enabled(self):
        self.assertTrue(PontoConfigurationService.is_webhooks_enabled())

    def test_is_auto_sync_enabled(self):
        self.assertTrue(PontoConfigurationService.is_auto_sync_enabled())

    def test_get_sync_interval_hours(self):
        self.assertEqual(PontoConfigurationService.get_sync_interval_hours(), 6)

    # -------------------------------------------------------------------------
    # Company resolution
    # -------------------------------------------------------------------------

    def test_get_default_company_resolves(self):
        """A company should resolve from Verenigingen Settings or defaults."""
        company = PontoConfigurationService.get_default_company()
        self.assertTrue(company)
        self.assertTrue(frappe.db.exists("Company", company))

    # -------------------------------------------------------------------------
    # Configuration validation
    # -------------------------------------------------------------------------

    def test_validate_configuration_valid_with_warning(self):
        """Valid credentials but enabled-yet-unlinked account -> valid + warning."""
        result = PontoConfigurationService.validate_configuration()
        self.assertTrue(result["valid"])
        self.assertEqual(result["missing_fields"], [])
        # Account A is enabled but has no bank_account => warning expected.
        self.assertTrue(any("not linked" in w for w in result["warnings"]))

    def test_validate_configuration_missing_credentials(self):
        """Missing sandbox client id flags the field and marks invalid."""
        frappe.db.set_value(
            "Ponto Settings", "Ponto Settings", "sandbox_client_id", "", update_modified=False
        )
        PontoConfigurationService.clear_cache()
        try:
            result = PontoConfigurationService.validate_configuration()
            self.assertFalse(result["valid"])
            self.assertIn("sandbox_client_id", result["missing_fields"])
        finally:
            frappe.db.set_value(
                "Ponto Settings", "Ponto Settings", "sandbox_client_id",
                "test_sandbox_client", update_modified=False,
            )
            PontoConfigurationService.clear_cache()

    # -------------------------------------------------------------------------
    # Atomic counter / sync-time updates
    # -------------------------------------------------------------------------

    def test_update_last_sync_time_sets_global_and_clears_cache(self):
        PontoConfigurationService.get_settings()  # warm cache
        PontoConfigurationService.update_last_sync_time(ACCOUNT_ID_A)
        # Cache cleared by the update.
        self.assertIsNone(frappe.cache().get_value(PontoConfigurationService.CACHE_KEY))
        # Global last_sync_time persisted.
        self.assertIsNotNone(
            frappe.db.get_value("Ponto Settings", "Ponto Settings", "last_sync_time")
        )
        # Mapping row last_sync_time persisted.
        row_sync = frappe.db.get_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": ACCOUNT_ID_A},
            "last_sync_time",
        )
        self.assertIsNotNone(row_sync)

    def test_increment_transactions_imported_adds_count(self):
        before = frappe.db.get_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": ACCOUNT_ID_A},
            "transactions_imported",
        ) or 0
        PontoConfigurationService.increment_transactions_imported(ACCOUNT_ID_A, 5)
        after = frappe.db.get_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": ACCOUNT_ID_A},
            "transactions_imported",
        )
        self.assertEqual(after, before + 5)

    def test_increment_transactions_imported_ignores_nonpositive(self):
        before = frappe.db.get_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": ACCOUNT_ID_A},
            "transactions_imported",
        )
        PontoConfigurationService.increment_transactions_imported(ACCOUNT_ID_A, 0)
        after = frappe.db.get_value(
            "Ponto Bank Account Mapping",
            {"parent": "Ponto Settings", "ponto_account_id": ACCOUNT_ID_A},
            "transactions_imported",
        )
        self.assertEqual(after, before)

    def test_increment_transactions_imported_unknown_account_noop(self):
        """Unknown account id is a no-op (no row to update)."""
        # Should not raise.
        PontoConfigurationService.increment_transactions_imported("does-not-exist", 3)
