# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt
"""
Coverage sweep for the Mollie Settings DocType controller.

These tests exercise the real controller methods (URL generation, currency
validation, credential pre-checks, password accessors, webhook-sync helpers and
the whitelisted endpoints) without making outbound Mollie API calls. Password
fields are set in-memory so ``get_password`` returns the in-memory value (see
frappe ``Document.get_password``), which keeps the tests deterministic and
network-free in both CI (empty Mollie Settings) and on a configured site.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import (
    get_mollie_settings,
    test_mollie_connection,
    verify_webhook_url_sync,
)


class TestMollieSettingsCoverage(EnhancedTestCase):
    """Real-integration coverage for MollieSettings controller methods."""

    def setUp(self):
        super().setUp()
        # Start every test from the persisted singleton state, not a previous
        # test's in-memory mutation of the cached Single document.
        frappe.clear_document_cache("Mollie Settings", "Mollie Settings")
        self.settings = frappe.get_single("Mollie Settings")

    # ------------------------------------------------------------------
    # Currency validation (LIVE: utils/payment_gateways.py:160)
    # ------------------------------------------------------------------
    def test_validate_transaction_currency_supported(self):
        """A supported currency must not raise."""
        # Should not raise for any supported currency
        self.settings.validate_transaction_currency("EUR")
        self.settings.validate_transaction_currency("USD")

    def test_validate_transaction_currency_unsupported_raises(self):
        """An unsupported currency raises a ValidationError mentioning the code."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.settings.validate_transaction_currency("XYZ")
        self.assertIn("XYZ", str(ctx.exception))

    # ------------------------------------------------------------------
    # Redirect URL (LIVE: utils/payment_gateways.py:165,497)
    # ------------------------------------------------------------------
    def test_get_redirect_url_uses_configured_override(self):
        """If redirect_url is configured it is returned verbatim."""
        self.settings.redirect_url = "https://example.org/custom-return"
        url = self.settings.get_redirect_url("Donation", "DON-0001", "tr_abc")
        self.assertEqual(url, "https://example.org/custom-return")

    def test_get_redirect_url_default_includes_tracking_params(self):
        """Without an override the default success URL carries doctype/docname/payment_id."""
        self.settings.redirect_url = None
        url = self.settings.get_redirect_url("Donation", "DON-0002", "tr_xyz")
        self.assertIn("payment-success?", url)
        self.assertIn("doctype=Donation", url)
        self.assertIn("docname=DON-0002", url)
        self.assertIn("payment_id=tr_xyz", url)

    def test_get_redirect_url_default_without_payment_id(self):
        """payment_id is omitted from the default URL when not supplied."""
        self.settings.redirect_url = None
        url = self.settings.get_redirect_url("Donation", "DON-0003")
        self.assertIn("docname=DON-0003", url)
        self.assertNotIn("payment_id=", url)

    # ------------------------------------------------------------------
    # Webhook URL generation (LIVE: payment_gateways, subscription sync)
    # ------------------------------------------------------------------
    def test_controller_webhook_url(self):
        """get_webhook_url delegates to MollieClient and points at the payment webhook."""
        url = self.settings.get_webhook_url()
        self.assertTrue(url.startswith("https://"))
        self.assertIn("mollie_payment_webhook", url)

    def test_test_and_live_webhook_urls_carry_env(self):
        """Per-env webhook URLs are HTTPS and carry the correct env query param."""
        test_url = self.settings.get_test_webhook_url()
        live_url = self.settings.get_live_webhook_url()
        self.assertTrue(test_url.startswith("https://"))
        self.assertTrue(live_url.startswith("https://"))
        self.assertIn("env=test", test_url)
        self.assertIn("env=live", live_url)
        self.assertIn("mollie_payment_webhook", test_url)

    def test_subscription_webhook_url(self):
        """Subscription webhook URL is HTTPS and targets the subscription endpoint."""
        url = self.settings.get_subscription_webhook_url()
        self.assertTrue(url.startswith("https://"))
        self.assertIn("mollie_subscription_webhook", url)

    def test_update_webhook_urls_populates_fields(self):
        """update_webhook_urls writes the computed per-env URLs onto the document."""
        self.settings.testing_webhook_url = "stale"
        self.settings.live_webhook_url = "stale"
        self.settings.update_webhook_urls()
        self.assertEqual(self.settings.testing_webhook_url, self.settings.get_test_webhook_url())
        self.assertEqual(self.settings.live_webhook_url, self.settings.get_live_webhook_url())

    def test_validate_and_update_webhook_urls_brings_into_sync(self):
        """validate_and_update_webhook_urls corrects out-of-sync URLs in memory."""
        self.settings.testing_webhook_url = "https://veg11.veganisme.org/wrong"
        self.settings.live_webhook_url = "https://veg11.veganisme.org/wrong"
        self.settings.validate_and_update_webhook_urls()
        self.assertEqual(self.settings.testing_webhook_url, self.settings.get_test_webhook_url())
        self.assertEqual(self.settings.live_webhook_url, self.settings.get_live_webhook_url())

    def test_update_subscription_webhook_url_delegates(self):
        """The deprecated alias still populates the live/test webhook URL fields."""
        self.settings.testing_webhook_url = "stale"
        self.settings.update_subscription_webhook_url()
        self.assertEqual(self.settings.testing_webhook_url, self.settings.get_test_webhook_url())

    # ------------------------------------------------------------------
    # _ensure_https_url security validation
    # ------------------------------------------------------------------
    def test_ensure_https_converts_http_for_allowed_domain(self):
        """An http URL on a whitelisted domain is upgraded to https."""
        result = self.settings._ensure_https_url("http://veg11.veganisme.org/api/method/x")
        self.assertEqual(result, "https://veg11.veganisme.org/api/method/x")

    def test_ensure_https_passes_through_https(self):
        """An https URL on a whitelisted domain is returned unchanged."""
        url = "https://veg11.veganisme.org/api/method/x"
        self.assertEqual(self.settings._ensure_https_url(url), url)

    def test_ensure_https_rejects_non_whitelisted_domain(self):
        """A URL whose host is not whitelisted is rejected."""
        # The validator logs a security Error Log before raising; mark it expected.
        self.expectErrorLog("Mollie Webhook Security")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.settings._ensure_https_url("https://evil.attacker.example/api")
        self.assertIn("not authorized", str(ctx.exception))

    def test_ensure_https_rejects_missing_netloc(self):
        """A URL without a network location is rejected as malformed."""
        with self.assertRaises(frappe.ValidationError):
            self.settings._ensure_https_url("not-a-url")

    def test_ensure_https_rejects_bad_scheme(self):
        """A non-HTTP(S) scheme is rejected."""
        with self.assertRaises(frappe.ValidationError):
            self.settings._ensure_https_url("ftp://veg11.veganisme.org/file")

    def test_ensure_https_rejects_overlong_url(self):
        """A URL longer than 2048 chars is rejected (DoS guard)."""
        long_url = "https://veg11.veganisme.org/" + ("a" * 2100)
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.settings._ensure_https_url(long_url)
        self.assertIn("maximum length", str(ctx.exception))

    def test_ensure_https_rejects_path_traversal(self):
        """Path traversal sequences in the URL path are rejected."""
        with self.assertRaises(frappe.ValidationError):
            self.settings._ensure_https_url("https://veg11.veganisme.org/../etc/passwd")

    def test_allowed_domains_includes_site(self):
        """The current site domain is always in the allowed-domains list."""
        domains = self.settings._get_allowed_webhook_domains()
        self.assertIn(frappe.local.site, domains)

    # ------------------------------------------------------------------
    # Password / key accessors (in-memory values; no DB commit, no network)
    # ------------------------------------------------------------------
    def test_get_active_api_key_follows_test_mode(self):
        """get_active_api_key returns the test key in test mode, live key otherwise."""
        self.settings.test_mode = 1
        self.settings.test_secret_key = "test_inmem_key"
        self.settings.live_secret_key = "live_inmem_key"
        self.assertEqual(self.settings.get_active_api_key(), "test_inmem_key")
        # get_api_key is a deprecated alias and must match (LIVE alias caller)
        self.assertEqual(self.settings.get_api_key(), "test_inmem_key")

        self.settings.test_mode = 0
        self.assertEqual(self.settings.get_active_api_key(), "live_inmem_key")

    def test_get_webhook_secret_follows_test_mode(self):
        """get_webhook_secret returns testing vs live secret based on test_mode."""
        self.settings.testing_webhook_secret_key = "test_ws"
        self.settings.live_webhook_secret_key = "live_ws"

        self.settings.test_mode = 1
        self.assertEqual(self.settings.get_webhook_secret(), "test_ws")

        self.settings.test_mode = 0
        self.assertEqual(self.settings.get_webhook_secret(), "live_ws")

    def test_get_organization_token_gated_by_flag(self):
        """The org token is only returned when backend API is enabled."""
        self.settings.organization_access_token = "org_tok_inmem"
        self.settings.enable_backend_api = 1
        self.assertEqual(self.settings.get_organization_token(), "org_tok_inmem")

        self.settings.enable_backend_api = 0
        self.assertIsNone(self.settings.get_organization_token())

    # ------------------------------------------------------------------
    # Credential pre-validation (no network: short-circuits before API call)
    # ------------------------------------------------------------------
    def test_validate_credentials_noop_without_profile(self):
        """With no profile_id the validator returns early without raising."""
        self.settings.profile_id = ""
        # Must not raise
        self.settings.validate_mollie_credentials()

    def test_validate_credentials_requires_test_key_in_test_mode(self):
        """Test mode with profile set but no test secret key raises before any API call."""
        self.settings.profile_id = "pfl_dummy"
        self.settings.test_mode = 1
        self.settings.test_secret_key = ""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.settings.validate_mollie_credentials()
        self.assertIn("Test Secret Key", str(ctx.exception))

    def test_validate_credentials_requires_live_key_in_live_mode(self):
        """Live mode with profile set but no live secret key raises before any API call."""
        self.settings.profile_id = "pfl_dummy"
        self.settings.test_mode = 0
        self.settings.live_secret_key = ""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.settings.validate_mollie_credentials()
        self.assertIn("Live Secret Key", str(ctx.exception))

    # ------------------------------------------------------------------
    # Mollie client construction (no network on set_api_key)
    # ------------------------------------------------------------------
    def test_get_mollie_client_returns_configured_client(self):
        """get_mollie_client returns a Client when an API key is available."""
        self.settings.test_mode = 1
        self.settings.test_secret_key = "test_dummy_client_key"
        client = self.settings.get_mollie_client()
        self.assertIsNotNone(client)
        # Confirms set_api_key path was taken on a real Mollie SDK Client
        self.assertTrue(hasattr(client, "methods"))

    def test_register_payment_gateway_runs(self):
        """register_payment_gateway is side-effect-light and must not raise."""
        # Called during on_update; verify it completes cleanly.
        self.settings.register_payment_gateway()

    # ------------------------------------------------------------------
    # Whitelisted endpoints (callable as Administrator in test context)
    # ------------------------------------------------------------------
    def test_whitelisted_get_mollie_settings(self):
        """get_mollie_settings returns the singleton document."""
        doc = get_mollie_settings()
        self.assertEqual(doc.doctype, "Mollie Settings")

    def test_whitelisted_verify_webhook_url_sync(self):
        """verify_webhook_url_sync reports sync status with expected/current URLs."""
        result = verify_webhook_url_sync()
        self.assertTrue(result["success"])
        self.assertIn("in_sync", result)
        self.assertIn("expected_urls", result)
        self.assertIn("current_urls", result)

    # ------------------------------------------------------------------
    # Document lifecycle entry points (no network: profile short-circuit)
    # ------------------------------------------------------------------
    def test_validate_entry_point_syncs_webhook_urls(self):
        """validate() runs credential pre-check + webhook sync without raising."""
        self.settings.profile_id = ""  # short-circuit credential API call
        self.settings.testing_webhook_url = "https://veg11.veganisme.org/wrong"
        self.settings.validate()
        # webhook URLs brought into sync by validate_and_update_webhook_urls
        self.assertEqual(self.settings.testing_webhook_url, self.settings.get_test_webhook_url())

    def test_on_update_entry_point_runs_cleanly(self):
        """on_update() clears config cache, refreshes URLs and registers the gateway."""
        self.settings.testing_webhook_url = "stale"
        self.settings.on_update()
        self.assertEqual(self.settings.testing_webhook_url, self.settings.get_test_webhook_url())
        self.assertEqual(self.settings.live_webhook_url, self.settings.get_live_webhook_url())

    def test_next_payment_date_clamps_invalid_day(self):
        """An out-of-range payment day (>28) falls back to the 25th."""
        self.settings.quarterly_yearly_payment_months = "1,4,7,10"
        self.settings.payment_day_of_month = 31  # invalid -> fallback to 25
        result = self.settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("-25"))

    def test_whitelisted_test_connection_short_circuits_without_profile(self):
        """test_mollie_connection succeeds (no network) when no profile is configured."""
        # Neutralise profile_id deterministically so validate_mollie_credentials
        # returns early instead of calling the Mollie API. Rolled back by the
        # EnhancedTestCase transaction.
        frappe.db.set_value("Mollie Settings", "Mollie Settings", "profile_id", "", update_modified=False)
        frappe.clear_document_cache("Mollie Settings", "Mollie Settings")
        result = test_mollie_connection()
        self.assertTrue(result["success"])
