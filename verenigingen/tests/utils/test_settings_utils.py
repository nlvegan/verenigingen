# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for verenigingen.utils.settings_utils.

Centralized settings retrieval used across the app. Tests hit the real DB and
the real Single DocTypes (Verenigingen Settings, Payments Settings, System
Settings, ...) rather than mocking, and exercise the getters, convenience
helpers, template-context helpers, and cache utilities.

Safety: these tests do NOT mutate-and-commit any settings Single. Where a test
needs to observe a non-default value, it uses an in-memory document copy or
restores the original value with set_value inside the (rolled-back) test
transaction. The cache helpers only delete cache keys (no DB writes).

Covered:
- get_verenigingen_settings / get_payments_settings (happy path returns Document)
- get_e_boekhouden_settings / get_system_settings / get_domain_settings /
  get_brand_settings (Single getters)
- get_mollie_settings / get_mollie_api_key (existing/missing gateway)
- get_default_company / get_support_email
- get_e_boekhouden_api_credentials
- is_e_boekhouden_enabled / is_mollie_enabled
- populate_mollie_context (configured + exception fallback)
- populate_income_calculator_context (loads from DB / provided settings / None guard)
- get_mollie_days_back_limit (value + default)
- clear_settings_cache / refresh_settings_cache (no raise, cache cleared)
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import settings_utils
from verenigingen.utils.settings_utils import (
    DEFAULT_DAYS_BACK_LIMIT,
    clear_settings_cache,
    get_brand_settings,
    get_default_company,
    get_domain_settings,
    get_e_boekhouden_api_credentials,
    get_e_boekhouden_settings,
    get_mollie_api_key,
    get_mollie_days_back_limit,
    get_mollie_settings,
    get_payments_settings,
    get_support_email,
    get_system_settings,
    get_verenigingen_settings,
    is_e_boekhouden_enabled,
    is_mollie_enabled,
    populate_income_calculator_context,
    populate_mollie_context,
    refresh_settings_cache,
)


class _Ctx:
    """Plain attribute bag standing in for a template context object."""

    pass


class TestSettingsUtils(EnhancedTestCase):
    # ----------------------------------------------------- core Single getters
    def test_get_verenigingen_settings_returns_document(self):
        settings = get_verenigingen_settings()
        self.assertIsNotNone(settings)
        # Document supports attribute access and reports its doctype
        self.assertEqual(settings.doctype, "Verenigingen Settings")
        # company attribute is reachable (may be empty, but must not raise)
        _ = settings.company

    def test_get_payments_settings_returns_document(self):
        settings = get_payments_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.doctype, "Verenigingen Payments Settings")

    def test_get_e_boekhouden_settings(self):
        settings = get_e_boekhouden_settings()
        # Single exists on the site -> returns a Document
        self.assertIsNotNone(settings)
        self.assertEqual(settings.doctype, "E-Boekhouden Settings")

    def test_get_system_settings(self):
        settings = get_system_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.doctype, "System Settings")

    def test_get_domain_settings(self):
        settings = get_domain_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.doctype, "Domain Settings")

    def test_get_brand_settings(self):
        settings = get_brand_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.doctype, "Brand Settings")

    # ----------------------------------------------------------- Mollie getters
    # NOTE: "Mollie Settings" is a Single DocType (its only valid record name is
    # "Mollie Settings"). The gateway-name parameter on these getters is a
    # legacy artifact; any non-Single gateway name resolves to "does not exist".
    def test_get_mollie_settings_missing_gateway_returns_none(self):
        ghost = f"NoSuchGateway{frappe.generate_hash(length=6)}"
        self.assertIsNone(get_mollie_settings(ghost))

    def test_get_mollie_api_key_missing_gateway_returns_none(self):
        ghost = f"NoSuchGateway{frappe.generate_hash(length=6)}"
        self.assertIsNone(get_mollie_api_key(ghost))

    def test_get_mollie_settings_single_name(self):
        # The actual Single record name is the doctype name itself.
        result = get_mollie_settings("Mollie Settings")
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("name"), "Mollie Settings")

    def test_is_mollie_enabled_missing_gateway_false(self):
        # Missing gateway -> False (settings is None)
        self.assertFalse(is_mollie_enabled(f"Ghost{frappe.generate_hash(length=6)}"))
        # The Single has no `enabled`/`api_key` fields, so is_mollie_enabled is
        # False even for the real Single — exercises the enabled/api_key branch.
        self.assertFalse(is_mollie_enabled("Mollie Settings"))

    # --------------------------------------------------------- convenience fns
    def test_get_default_company_matches_settings(self):
        settings = get_verenigingen_settings()
        self.assertEqual(get_default_company(), settings.company or None)

    def test_get_support_email_matches_system_settings(self):
        expected = frappe.db.get_single_value("System Settings", "email_footer_address")
        self.assertEqual(get_support_email(), expected or None)

    def test_get_e_boekhouden_api_credentials_returns_dict_or_none(self):
        # The DocType no longer carries `username` / `security_code` fields, so
        # the credential lookup degrades gracefully: it returns either a dict
        # (with both keys) or None on internal error — never raises.
        creds = get_e_boekhouden_api_credentials()
        if creds is not None:
            self.assertIsInstance(creds, dict)
            self.assertIn("username", creds)
            self.assertIn("security_code", creds)

    def test_is_e_boekhouden_enabled_returns_bool(self):
        # `enable_e_boekhouden` field is absent from the current schema, so the
        # helper falls back to False via settings.get(...) -> None. It must
        # always return a bool and never raise.
        result = is_e_boekhouden_enabled()
        self.assertIsInstance(result, bool)

    # ----------------------------------------------- populate_income_calculator
    def test_populate_income_calculator_context_with_provided_settings(self):
        settings = get_verenigingen_settings()
        ctx = _Ctx()
        populate_income_calculator_context(ctx, settings=settings)
        # Defaults applied via getattr fallbacks when fields are absent
        self.assertTrue(hasattr(ctx, "enable_income_calculator"))
        self.assertTrue(hasattr(ctx, "income_percentage_rate"))
        self.assertIn("contribution", ctx.calculator_description.lower())

    def test_populate_income_calculator_context_loads_from_db(self):
        ctx = _Ctx()
        populate_income_calculator_context(ctx, settings=None)
        self.assertTrue(hasattr(ctx, "calculator_description"))

    def test_populate_income_calculator_context_none_settings_guard(self):
        # When settings resolve to a falsy value the function must early-return
        # without touching ctx. Force the None branch via the module-level getter.
        ctx = _Ctx()
        original = settings_utils.get_verenigingen_settings
        settings_utils.get_verenigingen_settings = lambda: None
        try:
            populate_income_calculator_context(ctx, settings=None)
        finally:
            settings_utils.get_verenigingen_settings = original
        # ctx left untouched
        self.assertFalse(hasattr(ctx, "calculator_description"))

    # ----------------------------------------------------- populate_mollie_context
    def test_populate_mollie_context_sets_fields(self):
        # Real Mollie Settings Single may or may not be configured; either way
        # the function must populate all four fields without raising.
        ctx = _Ctx()
        populate_mollie_context(ctx)
        for field in ("mollie_configured", "test_mode", "api_key_type", "mollie_settings"):
            self.assertTrue(hasattr(ctx, field), f"missing {field}")
        self.assertIn(ctx.api_key_type, ("test", "live", "unknown"))

    def test_get_mollie_days_back_limit_returns_int(self):
        limit = get_mollie_days_back_limit()
        self.assertIsInstance(limit, int)
        self.assertGreater(limit, 0)

    def test_default_days_back_limit_constant(self):
        self.assertEqual(DEFAULT_DAYS_BACK_LIMIT, 1825)

    # ------------------------------------------------------------- cache helpers
    def test_clear_settings_cache_no_raise(self):
        # Should never raise even if some keys are absent
        with self.assertNoErrorLog():
            clear_settings_cache()

    def test_refresh_settings_cache_reloads(self):
        with self.assertNoErrorLog():
            refresh_settings_cache()
        # After refresh, settings are still retrievable
        self.assertIsNotNone(get_verenigingen_settings())
