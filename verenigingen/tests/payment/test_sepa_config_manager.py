# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for verenigingen_payments.utils.sepa_config_manager.

The SEPAConfigManager aggregates SEPA configuration from several sources
(Verenigingen Settings for the company reference, Verenigingen Payments
Settings for SEPA/financial parameters, the Company doctype, and hard-coded
defaults / bank tables).

These tests are written CONFIG-DETERMINISTICALLY: rather than asserting
against whatever ambient values happen to live on the test/veg11 site, we
patch the two settings accessors the manager actually reads
(`frappe.get_single` for "Verenigingen Settings" and the module-level
`get_payments_settings` import) so each resolution path, default, override
and missing-config branch is exercised independently of site state.

Only framework boundaries (settings accessors, frappe.logger / log_error,
the IBAN validator) are stubbed where needed; no business logic of the
manager itself is mocked.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import sepa_config_manager as scm
from verenigingen.verenigingen_payments.utils.sepa_config_manager import (
    SEPAConfigManager,
    get_sepa_config_manager,
)


class _FakeSettings:
    """Stand-in for a Frappe single Document.

    Critically, this mirrors a real Document's attribute semantics: missing
    attributes raise AttributeError, so the manager's
    `getattr(settings, field, default)` calls fall through to their coded
    defaults (a frappe._dict would instead return None and defeat the
    defaults -- which is NOT how the real Payments Settings doc behaves).
    """

    def __init__(self, **fields):
        self.__dict__.update(fields)


def _fake_payment_settings(**overrides):
    """Build an object standing in for Verenigingen Payments Settings.

    Only keys present override the manager's getattr() defaults; absent keys
    fall through to the defaults coded in get_company_sepa_config().
    """
    return _FakeSettings(**overrides)


def _fake_general_settings(company=None):
    return _FakeSettings(company=company)


class _PatchedManagerMixin:
    """Provides a helper to instantiate a manager with patched config sources."""

    def _make_manager(self, payment_overrides=None, company=None, company_name=None):
        """Return (manager, patchers) with settings sources patched.

        company_name: the company_name value returned by the patched Company doc.
        company: the company link value on general settings.
        """
        payment_settings = _fake_payment_settings(**(payment_overrides or {}))
        general_settings = _fake_general_settings(company=company)

        # Patch the module-level get_payments_settings import.
        p1 = patch.object(scm, "get_payments_settings", return_value=payment_settings)

        # Patch frappe.get_single (used for "Verenigingen Settings") and
        # frappe.get_doc (used to load the Company). We route by docname.
        real_get_single = frappe.get_single
        real_get_doc = frappe.get_doc

        def fake_get_single(doctype):
            if doctype == "Verenigingen Settings":
                return general_settings
            return real_get_single(doctype)

        def fake_get_doc(*args, **kwargs):
            if args and args[0] == "Company":
                return frappe._dict({"company_name": company_name or ""})
            return real_get_doc(*args, **kwargs)

        p2 = patch.object(frappe, "get_single", side_effect=fake_get_single)
        p3 = patch.object(frappe, "get_doc", side_effect=fake_get_doc)
        # Avoid depending on a configured global default company.
        p4 = patch.object(frappe.defaults, "get_global_default", return_value=None)

        for p in (p1, p2, p3, p4):
            p.start()
            self.addCleanup(p.stop)

        return SEPAConfigManager()


class TestSEPAConfigManagerCompanyConfig(_PatchedManagerMixin, EnhancedTestCase):
    """get_company_sepa_config: defaults, overrides, company resolution, caching."""

    def test_defaults_when_payment_settings_empty(self):
        manager = self._make_manager(payment_overrides={}, company=None)
        config = manager.get_company_sepa_config()

        # Empty payment settings -> coded defaults.
        self.assertEqual(config["company_iban"], "")
        self.assertEqual(config["company_bic"], "")
        self.assertEqual(config["creditor_id"], "")
        self.assertEqual(config["batch_creation_days"], "19,20")
        self.assertEqual(config["enable_auto_batch_creation"], 0)
        self.assertEqual(config["batch_processing_lead_time"], 7)
        self.assertEqual(config["send_batch_notifications"], 1)
        self.assertEqual(config["max_retry_attempts"], 3)
        self.assertEqual(config["circuit_breaker_threshold"], 5)
        self.assertEqual(config["invoice_lookback_days"], 60)
        self.assertEqual(config["mandate_cache_timeout"], 300)
        self.assertEqual(config["sepa_xml_version"], "pain.008.001.08")

    def test_overrides_flow_through(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "company_bic": "RABONL2U",
                "creditor_id": "NL98ZZZ999999999999",
                "batch_creation_days": "5,15,25",
                "enable_auto_batch_creation": 1,
                "max_retry_attempts": 7,
                "invoice_lookback_days": 90,
            }
        )
        config = manager.get_company_sepa_config()
        self.assertEqual(config["company_iban"], "NL39RABO0300065264")
        self.assertEqual(config["company_bic"], "RABONL2U")
        self.assertEqual(config["creditor_id"], "NL98ZZZ999999999999")
        self.assertEqual(config["batch_creation_days"], "5,15,25")
        self.assertEqual(config["enable_auto_batch_creation"], 1)
        self.assertEqual(config["max_retry_attempts"], 7)
        self.assertEqual(config["invoice_lookback_days"], 90)

    def test_company_resolution_from_general_settings(self):
        manager = self._make_manager(company="My Test Org", company_name="My Test Org BV")
        config = manager.get_company_sepa_config()
        self.assertEqual(config["company"], "My Test Org")
        self.assertEqual(config["company_name"], "My Test Org BV")

    def test_no_company_yields_empty_strings(self):
        manager = self._make_manager(company=None)
        config = manager.get_company_sepa_config()
        self.assertEqual(config["company"], "")
        self.assertEqual(config["company_name"], "")

    def test_account_holder_falls_back_to_company_name(self):
        # No explicit company_account_holder -> uses company_name.
        manager = self._make_manager(company="Org", company_name="Org Naam")
        config = manager.get_company_sepa_config()
        self.assertEqual(config["company_account_holder"], "Org Naam")

    def test_account_holder_explicit_wins(self):
        manager = self._make_manager(
            payment_overrides={"company_account_holder": "Explicit Holder"},
            company="Org",
            company_name="Org Naam",
        )
        config = manager.get_company_sepa_config()
        self.assertEqual(config["company_account_holder"], "Explicit Holder")

    def test_company_config_is_cached(self):
        manager = self._make_manager(payment_overrides={"company_iban": "NL39RABO0300065264"})
        first = manager.get_company_sepa_config()
        # Mutate cache directly to prove the second call hits cache, not reload.
        manager._settings_cache["company_sepa"]["company_iban"] = "MUTATED"
        second = manager.get_company_sepa_config()
        self.assertIs(first, second)
        self.assertEqual(second["company_iban"], "MUTATED")


class TestSEPAConfigManagerBankConfig(_PatchedManagerMixin, EnhancedTestCase):
    """get_bank_specific_config: known banks, unknown defaults, caching."""

    def test_known_bank_ing(self):
        manager = SEPAConfigManager()
        cfg = manager.get_bank_specific_config("INGBNL2A")
        self.assertEqual(cfg["name"], "ING Bank N.V.")
        self.assertTrue(cfg["requires_structured_address"])
        self.assertEqual(cfg["mandate_id_max_length"], 35)
        self.assertEqual(cfg["creditor_id_validation"], "strict")

    def test_known_bank_triodos_ethical_flag(self):
        manager = SEPAConfigManager()
        cfg = manager.get_bank_specific_config("TRIONL2U")
        self.assertEqual(cfg["name"], "Triodos Bank N.V.")
        self.assertTrue(cfg["ethical_screening"])

    def test_unknown_bank_gets_default_config(self):
        manager = SEPAConfigManager()
        cfg = manager.get_bank_specific_config("XXXXNL00")
        self.assertEqual(cfg["name"], "Bank with BIC XXXXNL00")
        self.assertTrue(cfg["requires_structured_address"])
        self.assertEqual(cfg["max_remittance_length"], 140)
        self.assertEqual(cfg["preferred_address_format"], "structured")

    def test_bank_config_is_cached(self):
        manager = SEPAConfigManager()
        first = manager.get_bank_specific_config("INGBNL2A")
        second = manager.get_bank_specific_config("INGBNL2A")
        self.assertIs(first, second)


class TestSEPAConfigManagerXMLConfig(_PatchedManagerMixin, EnhancedTestCase):
    def test_xml_config_uses_default_version(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_xml_generation_config()
        self.assertEqual(cfg["xml_version"], "pain.008.001.08")
        self.assertIn("pain.008.001.08", cfg["namespace"])
        self.assertIn("pain.008.001.08.xsd", cfg["schema_location"])
        self.assertTrue(cfg["supports_structured_address"])

    def test_xml_config_respects_configured_version(self):
        manager = self._make_manager(payment_overrides={"sepa_xml_version": "pain.008.001.02"})
        cfg = manager.get_xml_generation_config()
        # NOTE: namespace/schema are hard-coded to .08; only xml_version reads config.
        self.assertEqual(cfg["xml_version"], "pain.008.001.02")


class TestSEPAConfigManagerBatchTiming(_PatchedManagerMixin, EnhancedTestCase):
    def test_default_creation_days_parsed(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_batch_timing_config()
        self.assertEqual(cfg["creation_days"], [19, 20])
        self.assertEqual(cfg["processing_lead_time"], 7)
        self.assertFalse(cfg["auto_creation_enabled"])
        self.assertFalse(cfg["auto_submit_enabled"])

    def test_custom_creation_days_parsed_and_whitespace_stripped(self):
        manager = self._make_manager(payment_overrides={"batch_creation_days": " 1, 15 , 28 "})
        cfg = manager.get_batch_timing_config()
        self.assertEqual(cfg["creation_days"], [1, 15, 28])

    def test_non_numeric_days_filtered_out(self):
        manager = self._make_manager(payment_overrides={"batch_creation_days": "10,foo,20,"})
        cfg = manager.get_batch_timing_config()
        self.assertEqual(cfg["creation_days"], [10, 20])

    def test_empty_creation_days_string_falls_back_to_default(self):
        # Empty string is falsy -> "or '19,20'" default kicks in.
        manager = self._make_manager(payment_overrides={"batch_creation_days": ""})
        cfg = manager.get_batch_timing_config()
        self.assertEqual(cfg["creation_days"], [19, 20])

    def test_is_creation_day_reflects_today(self):
        from frappe.utils import getdate, today

        day = getdate(today()).day
        manager = self._make_manager(payment_overrides={"batch_creation_days": str(day)})
        cfg = manager.get_batch_timing_config()
        self.assertEqual(cfg["current_day"], day)
        self.assertTrue(cfg["is_creation_day"])

    def test_auto_flags_coerced_to_bool(self):
        manager = self._make_manager(
            payment_overrides={"enable_auto_batch_creation": 1, "auto_submit_sepa_batches": 1}
        )
        cfg = manager.get_batch_timing_config()
        self.assertIs(cfg["auto_creation_enabled"], True)
        self.assertIs(cfg["auto_submit_enabled"], True)


class TestSEPAConfigManagerNotifications(_PatchedManagerMixin, EnhancedTestCase):
    def test_no_emails_means_no_recipients(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_notification_config()
        self.assertEqual(cfg["admin_emails"], [])
        self.assertFalse(cfg["has_recipients"])
        self.assertTrue(cfg["notifications_enabled"])

    def test_emails_parsed_and_stripped(self):
        manager = self._make_manager(
            payment_overrides={"financial_admin_emails": "a@x.org, b@x.org ,, c@x.org"}
        )
        cfg = manager.get_notification_config()
        self.assertEqual(cfg["admin_emails"], ["a@x.org", "b@x.org", "c@x.org"])
        self.assertTrue(cfg["has_recipients"])

    def test_notification_toggles_coerced_to_bool(self):
        manager = self._make_manager(
            payment_overrides={
                "send_batch_notifications": 0,
                "notification_critical_errors": 0,
                "notification_warnings": 0,
            }
        )
        cfg = manager.get_notification_config()
        self.assertFalse(cfg["notifications_enabled"])
        self.assertFalse(cfg["critical_errors_enabled"])
        self.assertFalse(cfg["warnings_enabled"])


class TestSEPAConfigManagerErrorHandling(_PatchedManagerMixin, EnhancedTestCase):
    def test_error_handling_defaults(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_error_handling_config()
        self.assertTrue(cfg["retry_enabled"])
        self.assertEqual(cfg["max_retries"], 3)
        self.assertTrue(cfg["circuit_breaker_enabled"])
        self.assertEqual(cfg["circuit_breaker_threshold"], 5)
        self.assertEqual(cfg["base_delay"], 1.0)
        self.assertEqual(cfg["max_delay"], 60.0)
        self.assertEqual(cfg["backoff_multiplier"], 2.0)

    def test_error_handling_overrides(self):
        manager = self._make_manager(
            payment_overrides={
                "enable_retry_mechanism": 0,
                "max_retry_attempts": 10,
                "circuit_breaker_enabled": 0,
                "circuit_breaker_threshold": 99,
            }
        )
        cfg = manager.get_error_handling_config()
        self.assertFalse(cfg["retry_enabled"])
        self.assertEqual(cfg["max_retries"], 10)
        self.assertFalse(cfg["circuit_breaker_enabled"])
        self.assertEqual(cfg["circuit_breaker_threshold"], 99)


class TestSEPAConfigManagerProcessingAndFiles(_PatchedManagerMixin, EnhancedTestCase):
    def test_processing_defaults(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_processing_config()
        self.assertEqual(cfg["lookback_days"], 60)
        self.assertTrue(cfg["coverage_verification"])
        self.assertEqual(cfg["mandate_cache_timeout"], 300)
        self.assertEqual(cfg["batch_size_limit"], 1000)
        self.assertTrue(cfg["pagination_enabled"])

    def test_processing_overrides(self):
        manager = self._make_manager(
            payment_overrides={
                "invoice_lookback_days": 30,
                "coverage_verification_enabled": 0,
                "mandate_cache_timeout": 60,
            }
        )
        cfg = manager.get_processing_config()
        self.assertEqual(cfg["lookback_days"], 30)
        self.assertFalse(cfg["coverage_verification"])
        self.assertEqual(cfg["mandate_cache_timeout"], 60)

    def test_file_handling_defaults(self):
        manager = self._make_manager(payment_overrides={})
        cfg = manager.get_file_handling_config()
        self.assertEqual(cfg["xml_version"], "pain.008.001.08")
        self.assertEqual(cfg["output_directory"], "")
        self.assertTrue(cfg["backup_files"])
        self.assertEqual(cfg["file_naming_pattern"], "SEPA-{batch_name}-{date}.xml")

    def test_file_handling_with_output_dir(self):
        manager = self._make_manager(
            payment_overrides={"sepa_output_directory": "/tmp/sepa", "backup_processed_files": 0}
        )
        cfg = manager.get_file_handling_config()
        self.assertEqual(cfg["output_directory"], "/tmp/sepa")
        self.assertFalse(cfg["backup_files"])


class TestSEPAConfigManagerValidation(_PatchedManagerMixin, EnhancedTestCase):
    def test_missing_required_fields_invalid(self):
        manager = self._make_manager(payment_overrides={})
        result = manager.validate_sepa_config()
        self.assertFalse(result["valid"])
        # All three required fields missing.
        self.assertTrue(any("Company IBAN" in e for e in result["errors"]))
        self.assertTrue(any("Creditor ID" in e for e in result["errors"]))
        self.assertTrue(any("Company Account Holder" in e for e in result["errors"]))

    def test_valid_config_passes(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "company_bic": "RABONL2U",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
                "financial_admin_emails": "admin@test.org",
                "sepa_output_directory": "/tmp/sepa",
            }
        )
        result = manager.validate_sepa_config()
        self.assertTrue(result["valid"], msg=str(result["errors"]))
        self.assertEqual(result["errors"], [])

    def test_invalid_iban_reported_as_error(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL00BANK0000000000",  # bad checksum
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        result = manager.validate_sepa_config()
        self.assertFalse(result["valid"])
        self.assertTrue(any("Invalid IBAN" in e for e in result["errors"]))

    def test_invalid_iban_includes_real_message(self):
        """validate_sepa_config surfaces the real IBAN validator message.

        validate_iban() (utils/validation/iban_validator.py) returns the failure
        reason under the key 'message'. validate_sepa_config must read that key so
        the specific reason (e.g. "Invalid IBAN checksum...") reaches the user
        rather than a generic "Unknown error".
        """
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL00BANK0000000000",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        result = manager.validate_sepa_config()
        iban_errors = [e for e in result["errors"] if "Invalid IBAN" in e]
        self.assertTrue(iban_errors)
        self.assertNotIn("Unknown error", iban_errors[0])

    def test_bic_auto_derived_from_iban_when_missing(self):
        """With a valid IBAN and no configured BIC, the manager auto-derives it.

        validate_sepa_config wires derive_bic_from_iban() (same iban_validator
        module) to fill in the BIC when none is configured, emitting a
        "BIC auto-derived" warning.
        """
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",  # valid, BIC RABONL2U
                "company_bic": "",  # not configured
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        result = manager.validate_sepa_config()
        self.assertTrue(any("auto-derived" in w for w in result["warnings"]))

    def test_notifications_enabled_without_recipients_warns(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
                "send_batch_notifications": 1,
                "financial_admin_emails": "",
            }
        )
        result = manager.validate_sepa_config()
        self.assertTrue(
            any("no admin email addresses configured" in w for w in result["warnings"])
        )

    def test_auto_batch_without_creation_days_invalid(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
                "enable_auto_batch_creation": 1,
                "batch_creation_days": "none",  # parses to [] (no digits)
            }
        )
        result = manager.validate_sepa_config()
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("no creation days configured" in e for e in result["errors"])
        )

    def test_missing_optional_fields_listed(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        result = manager.validate_sepa_config()
        # company_bic is auto-derived from the valid RABO IBAN (so it is no
        # longer reported as missing); only the output directory and admin
        # emails remain unset.
        self.assertEqual(len(result["missing_optional"]), 2)
        self.assertTrue(any("Output directory" in m for m in result["missing_optional"]))
        self.assertTrue(any("Admin emails" in m for m in result["missing_optional"]))

    def test_validation_result_is_cached(self):
        manager = self._make_manager(payment_overrides={})
        first = manager.validate_sepa_config()
        first["errors"].append("SENTINEL")
        second = manager.validate_sepa_config()
        self.assertIs(first, second)
        self.assertIn("SENTINEL", second["errors"])


class TestSEPAConfigManagerCompleteAndCache(_PatchedManagerMixin, EnhancedTestCase):
    def test_complete_config_has_all_sections(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        cfg = manager.get_complete_config()
        for key in (
            "company_sepa",
            "batch_timing",
            "notifications",
            "error_handling",
            "processing",
            "file_handling",
            "validation",
        ):
            self.assertIn(key, cfg)

    def test_cache_info_counts(self):
        manager = self._make_manager(payment_overrides={})
        # Nothing cached yet.
        info = manager.get_cache_info()
        self.assertEqual(info["total_cached_items"], 0)
        manager.get_company_sepa_config()
        manager.validate_sepa_config()
        info = manager.get_cache_info()
        self.assertEqual(info["settings_cache_size"], 1)
        self.assertEqual(info["validation_cache_size"], 1)
        self.assertEqual(info["total_cached_items"], 2)

    def test_clear_cache_empties_caches(self):
        manager = self._make_manager(payment_overrides={})
        manager.get_company_sepa_config()
        manager.validate_sepa_config()
        self.assertGreater(manager.get_cache_info()["total_cached_items"], 0)
        manager.clear_cache()
        self.assertEqual(manager.get_cache_info()["total_cached_items"], 0)
        # bank config cache is NOT cleared by clear_cache (documented behaviour).
        manager.get_bank_specific_config("INGBNL2A")
        manager.clear_cache()
        self.assertEqual(len(manager._bank_config_cache), 1)


class TestSEPAConfigManagerUpdateSetting(_PatchedManagerMixin, EnhancedTestCase):
    def test_update_known_setting_saves_and_clears_cache(self):
        saved = {}

        class FakeSettings:
            def save(self_inner):
                saved["called"] = True

        fake = FakeSettings()
        with patch.object(scm, "get_payments_settings", return_value=fake):
            manager = SEPAConfigManager()
            manager._settings_cache["company_sepa"] = {"x": 1}  # prime cache
            ok = manager.update_setting("company_sepa", "company_iban", "NL39RABO0300065264")
        self.assertTrue(ok)
        self.assertTrue(saved.get("called"))
        self.assertEqual(fake.company_iban, "NL39RABO0300065264")
        # cache cleared.
        self.assertEqual(manager._settings_cache, {})

    def test_update_unknown_setting_returns_false(self):
        with patch.object(scm, "get_payments_settings", return_value=frappe._dict()):
            manager = SEPAConfigManager()
            ok = manager.update_setting("nonsense", "bogus", "x")
        self.assertFalse(ok)

    def test_update_setting_swallows_exception_returns_false(self):
        class BoomSettings:
            def __setattr__(self_inner, k, v):
                raise RuntimeError("boom")

        with patch.object(scm, "get_payments_settings", return_value=BoomSettings()):
            manager = SEPAConfigManager()
            ok = manager.update_setting("company_sepa", "company_iban", "x")
        self.assertFalse(ok)


class TestSEPAConfigManagerSingletonAndAPI(_PatchedManagerMixin, EnhancedTestCase):
    def test_get_sepa_config_manager_is_singleton(self):
        scm._config_manager = None
        a = get_sepa_config_manager()
        b = get_sepa_config_manager()
        self.assertIs(a, b)

    def test_get_sepa_config_api_unknown_section(self):
        manager = self._make_manager(payment_overrides={})
        # Patch the singleton so the whitelisted API uses our patched manager.
        with patch.object(scm, "get_sepa_config_manager", return_value=manager):
            result = scm.get_sepa_config(section="does_not_exist")
        self.assertIn("error", result)

    def test_get_sepa_config_api_specific_section(self):
        manager = self._make_manager(payment_overrides={})
        with patch.object(scm, "get_sepa_config_manager", return_value=manager):
            result = scm.get_sepa_config(section="notification")
        # get_notification_config exists -> dict with admin_emails key.
        self.assertIn("admin_emails", result)

    def test_get_sepa_config_api_complete(self):
        manager = self._make_manager(
            payment_overrides={
                "company_iban": "NL39RABO0300065264",
                "creditor_id": "NL98ZZZ999999999999",
                "company_account_holder": "Test Org",
            }
        )
        with patch.object(scm, "get_sepa_config_manager", return_value=manager):
            result = scm.get_sepa_config()
        self.assertIn("company_sepa", result)


class TestSEPAConfigManagerDirectEditInvalidation(_PatchedManagerMixin, EnhancedTestCase):
    """#866: a direct edit to the backing Settings doctypes (Desk UI, another
    script, doc.save() outside this manager) must invalidate the singleton's
    cache, not just edits made through update_setting()."""

    def setUp(self):
        super().setUp()
        prev = scm._config_manager
        scm._config_manager = None
        self.addCleanup(setattr, scm, "_config_manager", prev)

    def test_clear_cache_on_settings_update_clears_singleton_cache(self):
        manager = get_sepa_config_manager()
        manager._settings_cache["sentinel"] = "value"
        manager._validation_cache["sentinel"] = "value"

        scm.clear_cache_on_settings_update()

        self.assertEqual(manager._settings_cache, {})
        self.assertEqual(manager._validation_cache, {})

    def test_clear_cache_on_settings_update_accepts_doc_events_signature(self):
        """doc_events calls handlers as fn(doc, method=None)."""
        manager = get_sepa_config_manager()
        manager._settings_cache["sentinel"] = "value"

        fake_doc = frappe._dict({"doctype": "Verenigingen Settings"})
        scm.clear_cache_on_settings_update(fake_doc, method="on_update")

        self.assertEqual(manager._settings_cache, {})

    def test_clear_cache_on_settings_update_is_safe_before_first_use(self):
        scm._config_manager = None

        scm.clear_cache_on_settings_update()  # must not raise

        # Building the singleton on demand (get-or-create) is fine here; the
        # important behaviour is that it does not error.
        self.assertIsNotNone(scm._config_manager)

    def _handlers_for(self, doctype, event):
        from verenigingen.hooks.doc_events import doc_events

        handlers = doc_events.get(doctype, {}).get(event, [])
        if isinstance(handlers, str):
            handlers = [handlers]
        return handlers

    def test_hooked_for_verenigingen_settings_on_update(self):
        target = "verenigingen.verenigingen_payments.utils.sepa_config_manager.clear_cache_on_settings_update"
        self.assertIn(target, self._handlers_for("Verenigingen Settings", "on_update"))

    def test_hooked_for_verenigingen_payments_settings_on_update(self):
        target = "verenigingen.verenigingen_payments.utils.sepa_config_manager.clear_cache_on_settings_update"
        self.assertIn(target, self._handlers_for("Verenigingen Payments Settings", "on_update"))


if __name__ == "__main__":
    unittest.main()
