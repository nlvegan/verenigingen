# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB coverage tests for verenigingen/services/infrastructure/service_config.py.

Covers ServiceConfig (validation, env overrides, validate_and_set rollback,
merge, type/choice validators), ConfigurationManager (registration, settings
loading, file save/load round-trip, validation aggregation, summary) and
EnvironmentConfig (environment-specific config loading).

These are pure-logic infra modules; the only DB touch point is
ConfigurationManager.load_from_settings() which reads the real
"Verenigingen Settings" Single. We exercise that against the real doctype and
derive expectations from its actual fields. load_from_settings maps the REAL
field (member_id_start) onto the member_services config - see
test_load_from_settings_reads_real_member_fields. A minimum_membership_age ->
minimum_age mapping used to live there too; removed in #673 (dead, no
consumer, and it silently accepted the exact missing/zero setting
AgeValidator._get_configurable_min_age deliberately refuses on).
"""

import json
import os
import tempfile

import frappe

from verenigingen.services.infrastructure.service_config import (
    ConfigurationManager,
    EnvironmentConfig,
    ServiceConfig,
    get_config_manager,
    get_global_config,
    get_service_config,
    validate_service_configuration,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_error_handler import ServiceError


class TestServiceConfig(EnhancedTestCase):
    """ServiceConfig container: set/get, validators, env overrides, merge."""

    def setUp(self):
        super().setUp()
        # Ensure no leaked env overrides from prior tests/process
        for k in list(os.environ):
            if k.startswith("VERENIGINGEN_"):
                # Only clean the synthetic keys we use below; leave real ones.
                if k in ("VERENIGINGEN_MAXVALUE", "VERENIGINGEN_FLAG", "VERENIGINGEN_RATIO"):
                    del os.environ[k]

    def test_set_and_get_roundtrip(self):
        cfg = ServiceConfig()
        cfg.set("limit", 100)
        self.assertEqual(cfg.get("limit"), 100)
        self.assertIsNone(cfg.get("missing"))
        self.assertEqual(cfg.get("missing", "fallback"), "fallback")

    def test_required_key_tracked(self):
        cfg = ServiceConfig()
        cfg.set("token", "abc", required=True)
        # token present -> validate finds no missing-required error
        self.assertEqual(cfg.validate(), [])

    def test_get_required_raises_when_absent(self):
        cfg = ServiceConfig()
        with self.assertRaises(ServiceError):
            cfg.get_required("nope")

    def test_get_required_returns_value(self):
        cfg = ServiceConfig({"present": 7})
        self.assertEqual(cfg.get_required("present"), 7)

    def test_validate_reports_missing_required(self):
        cfg = ServiceConfig()
        cfg._required_keys.add("api_key")  # required but never set
        errors = cfg.validate()
        self.assertTrue(any("api_key" in e for e in errors))

    def test_type_validator_passes_and_fails(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("count", int, min_value=1, max_value=10)
        cfg.set("count", 5)
        self.assertEqual(cfg.validate(), [])
        cfg.set("count", 99)  # above max
        errors = cfg.validate()
        self.assertTrue(any("count" in e for e in errors))

    def test_type_validator_wrong_type(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("count", int)
        cfg.set("count", "not-an-int")
        errors = cfg.validate()
        self.assertTrue(any("count" in e for e in errors))

    def test_type_validator_below_min(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("age", int, min_value=16, max_value=120)
        cfg.set("age", 5)
        errors = cfg.validate()
        self.assertTrue(any("age" in e for e in errors))

    def test_choice_validator(self):
        cfg = ServiceConfig()
        cfg.add_choice_validator("status", ["Active", "Inactive"])
        cfg.set("status", "Active")
        self.assertEqual(cfg.validate(), [])
        cfg.set("status", "Bogus")
        errors = cfg.validate()
        self.assertTrue(any("status" in e for e in errors))

    def test_custom_validator_exception_is_captured(self):
        cfg = ServiceConfig()

        def boom(value):
            raise RuntimeError("validator exploded")

        cfg.add_validator("x", boom)
        cfg.set("x", 1)
        errors = cfg.validate()
        # Exception path appends a "validator error for x" message rather than raising
        self.assertTrue(any("x" in e and "error" in e.lower() for e in errors))

    def test_none_value_skips_validator(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("count", int)
        cfg.set("count", None)
        # value is None -> validator skipped, no error
        self.assertEqual(cfg.validate(), [])

    def test_env_override_string_and_typed(self):
        cfg = ServiceConfig({"maxvalue": 1, "flag": "x", "ratio": "x"})
        os.environ["VERENIGINGEN_MAXVALUE"] = "42"
        os.environ["VERENIGINGEN_FLAG"] = "true"
        os.environ["VERENIGINGEN_RATIO"] = "3.5"
        try:
            self.assertEqual(cfg.get("maxvalue"), 42)
            self.assertIs(cfg.get("flag"), True)
            self.assertEqual(cfg.get("ratio"), 3.5)
        finally:
            del os.environ["VERENIGINGEN_MAXVALUE"]
            del os.environ["VERENIGINGEN_FLAG"]
            del os.environ["VERENIGINGEN_RATIO"]

    def test_get_required_satisfied_by_env(self):
        cfg = ServiceConfig()
        os.environ["VERENIGINGEN_FLAG"] = "false"
        try:
            # not in _config but present via env -> no raise, converted to bool
            self.assertIs(cfg.get_required("flag"), False)
        finally:
            del os.environ["VERENIGINGEN_FLAG"]

    def test_convert_env_value_string_fallthrough(self):
        cfg = ServiceConfig()
        self.assertEqual(cfg._convert_env_value("plain-text"), "plain-text")
        self.assertEqual(cfg._convert_env_value("10"), 10)
        self.assertEqual(cfg._convert_env_value("1.25"), 1.25)
        self.assertIs(cfg._convert_env_value("FALSE"), False)

    def test_validate_and_set_success(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("count", int, min_value=0, max_value=10)
        self.assertTrue(cfg.validate_and_set("count", 5, required=True))
        self.assertEqual(cfg.get("count"), 5)
        self.assertIn("count", cfg._required_keys)

    def test_validate_and_set_rolls_back_on_failure(self):
        cfg = ServiceConfig({"count": 3})
        cfg.add_type_validator("count", int, min_value=0, max_value=10)
        with self.assertRaises(ValueError):
            cfg.validate_and_set("count", 999)  # exceeds max
        # old value restored
        self.assertEqual(cfg.get("count"), 3)

    def test_validate_and_set_rollback_when_no_prior_value(self):
        cfg = ServiceConfig()
        cfg.add_type_validator("count", int, min_value=0, max_value=10)
        with self.assertRaises(ValueError):
            cfg.validate_and_set("count", 999)
        # key removed entirely (no prior value to restore)
        self.assertNotIn("count", cfg.to_dict())

    def test_merge(self):
        a = ServiceConfig({"x": 1})
        a._required_keys.add("x")
        b = ServiceConfig({"y": 2})
        b.add_type_validator("y", int)
        a.merge(b)
        self.assertEqual(a.get("y"), 2)
        self.assertIn("x", a._required_keys)
        self.assertIn("y", a._validators)

    def test_to_dict_is_copy(self):
        cfg = ServiceConfig({"a": 1})
        d = cfg.to_dict()
        d["a"] = 999
        self.assertEqual(cfg.get("a"), 1)


class TestConfigurationManager(EnhancedTestCase):
    """ConfigurationManager: service configs, settings load, file IO, summary."""

    def test_register_and_get_service_config(self):
        mgr = ConfigurationManager()
        cfg = ServiceConfig({"k": "v"})
        mgr.register_service_config("svc_a", cfg)
        self.assertIs(mgr.get_service_config("svc_a"), cfg)

    def test_get_service_config_creates_default(self):
        mgr = ConfigurationManager()
        cfg = mgr.get_service_config("brand_new")
        self.assertIsInstance(cfg, ServiceConfig)
        # second call returns the same auto-created instance
        self.assertIs(mgr.get_service_config("brand_new"), cfg)

    def test_global_config_set_get(self):
        mgr = ConfigurationManager()
        mgr.set_global_config("cache_timeout", 60)
        self.assertEqual(mgr.get_global_config("cache_timeout"), 60)
        self.assertEqual(mgr.get_global_config("absent", "dflt"), "dflt")

    def test_load_from_settings_reads_real_member_fields(self):
        """load_from_settings maps the REAL Verenigingen Settings field onto the
        member_services config:

            member_id_start -> id_start_number

        Previously this referenced a stale name (member_id_start_number) that
        never matched, so the configured value silently fell through to the
        hardcoded default. Here we set a non-default value (non-committed,
        rolled back) and assert it flows into the config.

        `id_length` and `default_status` have NO backing field on the doctype, so
        they keep their hardcoded defaults.
        """
        orig_start = frappe.db.get_single_value("Verenigingen Settings", "member_id_start")
        try:
            frappe.db.set_single_value(
                "Verenigingen Settings", "member_id_start", 5000, update_modified=False
            )

            mgr = ConfigurationManager()
            mgr.load_from_settings()  # real Single read; must not raise

            member_cfg = mgr.get_service_config("member_services")
            # Real configured value flows through (NOT the 1000 default):
            self.assertEqual(member_cfg.get("id_start_number"), 5000)
            # No backing field -> hardcoded defaults retained:
            self.assertEqual(member_cfg.get("id_length"), 6)
            self.assertEqual(member_cfg.get("default_status"), "Active")
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "member_id_start", orig_start, update_modified=False
            )

    def test_load_from_settings_no_longer_maps_a_minimum_age(self):
        """A `minimum_membership_age -> minimum_age` mapping used to live in
        `_load_member_service_settings`, with a hardcoded default of 16 and
        min_val=0 -- silently accepting the exact missing/zero setting
        `AgeValidator._get_configurable_min_age` deliberately refuses on (#673).
        It had no consumer, so it is removed rather than reconciled with a
        policy it never enforced. Pin the setting to that refused value (0) and
        confirm member_services carries no `minimum_age` key at all -- age
        minimums for actual validation come solely from
        AgeValidator._get_configurable_min_age.

        `get_service_config()` auto-creates an empty ServiceConfig for an unknown
        service name, and `load_from_settings()`'s outer `except Exception` (this
        module, `load_from_settings`) swallows a total loader failure silently --
        so a bare "minimum_age is absent" assertion would also pass if the loader
        never ran at all. Assert `id_length` alongside it: that key is set
        unconditionally by `_load_member_service_settings` whenever it runs, so
        its presence proves the loader actually executed rather than died upstream.
        """
        orig_age = frappe.db.get_single_value("Verenigingen Settings", "minimum_membership_age")
        try:
            frappe.db.set_single_value(
                "Verenigingen Settings", "minimum_membership_age", 0, update_modified=False
            )

            mgr = ConfigurationManager()
            mgr.load_from_settings()  # real Single read; must not raise

            member_cfg = mgr.get_service_config("member_services")
            self.assertIsNone(member_cfg.get("minimum_age"))
            # Proves the loader actually ran (see docstring) rather than the
            # negative assertion above passing because of a silently swallowed
            # loader failure leaving member_cfg empty.
            self.assertEqual(member_cfg.get("id_length"), 6)
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "minimum_membership_age", orig_age, update_modified=False
            )

    def test_save_and_load_file_roundtrip(self):
        mgr = ConfigurationManager()
        mgr.set_global_config("cache_timeout", 120)
        svc = ServiceConfig({"limit": 50})
        mgr.register_service_config("data_svc", svc)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            path = fh.name
        try:
            mgr.save_to_file(path)
            with open(path) as f:
                on_disk = json.load(f)
            self.assertEqual(on_disk["global"]["cache_timeout"], 120)
            self.assertEqual(on_disk["services"]["data_svc"]["limit"], 50)

            # Load into a fresh manager
            mgr2 = ConfigurationManager()
            mgr2.load_from_file(path)
            self.assertEqual(mgr2.get_global_config("cache_timeout"), 120)
            self.assertEqual(mgr2.get_service_config("data_svc").get("limit"), 50)
        finally:
            os.unlink(path)

    def test_save_to_file_raises_service_error_on_bad_path(self):
        mgr = ConfigurationManager()
        with self.assertRaises(ServiceError):
            mgr.save_to_file("/nonexistent-dir-xyz/cfg.json")

    def test_load_from_file_raises_service_error_on_missing(self):
        mgr = ConfigurationManager()
        with self.assertRaises(ServiceError):
            mgr.load_from_file("/nonexistent-dir-xyz/cfg.json")

    def test_validate_all_configurations_aggregates_errors(self):
        mgr = ConfigurationManager()
        # Make global config invalid
        mgr._global_config.add_type_validator("g", int)
        mgr.set_global_config("g", "not-int")
        # Make a service config invalid
        svc = ServiceConfig()
        svc.add_type_validator("s", int)
        svc.set("s", "also-not-int")
        mgr.register_service_config("svc_bad", svc)

        all_errors = mgr.validate_all_configurations()
        self.assertIn("global", all_errors)
        self.assertIn("svc_bad", all_errors)

    def test_validate_all_configurations_clean(self):
        mgr = ConfigurationManager()
        mgr.set_global_config("ok", 1)
        self.assertEqual(mgr.validate_all_configurations(), {})

    def test_configuration_summary(self):
        mgr = ConfigurationManager()
        mgr.set_global_config("a", 1)
        mgr.register_service_config("svc_one", ServiceConfig())
        summary = mgr.get_configuration_summary()
        self.assertIn("a", summary["global_config_keys"])
        self.assertEqual(summary["service_count"], 1)
        self.assertIn("svc_one", summary["services"])
        self.assertTrue(summary["validation_status"])


class TestEnvironmentConfig(EnhancedTestCase):
    """EnvironmentConfig: environment detection and config injection."""

    def setUp(self):
        super().setUp()
        self._saved_env = os.environ.get("VERENIGINGEN_ENVIRONMENT")

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop("VERENIGINGEN_ENVIRONMENT", None)
        else:
            os.environ["VERENIGINGEN_ENVIRONMENT"] = self._saved_env
        super().tearDown()

    def test_default_environment_is_development(self):
        os.environ.pop("VERENIGINGEN_ENVIRONMENT", None)
        self.assertEqual(EnvironmentConfig.get_current_environment(), "development")
        self.assertTrue(EnvironmentConfig.is_development())
        self.assertFalse(EnvironmentConfig.is_production())

    def test_production_environment(self):
        os.environ["VERENIGINGEN_ENVIRONMENT"] = "production"
        self.assertTrue(EnvironmentConfig.is_production())
        self.assertFalse(EnvironmentConfig.is_development())

    def test_load_environment_config_development(self):
        os.environ["VERENIGINGEN_ENVIRONMENT"] = "development"
        mgr = ConfigurationManager()
        EnvironmentConfig.load_environment_config(mgr)
        self.assertIs(mgr.get_global_config("debug_logging"), True)
        self.assertEqual(mgr.get_global_config("cache_timeout"), 60)
        self.assertIs(mgr.get_global_config("strict_validation"), False)

    def test_load_environment_config_testing(self):
        os.environ["VERENIGINGEN_ENVIRONMENT"] = "testing"
        mgr = ConfigurationManager()
        EnvironmentConfig.load_environment_config(mgr)
        self.assertEqual(mgr.get_global_config("cache_timeout"), 0)
        self.assertIs(mgr.get_global_config("strict_validation"), True)

    def test_load_environment_config_production(self):
        os.environ["VERENIGINGEN_ENVIRONMENT"] = "production"
        mgr = ConfigurationManager()
        EnvironmentConfig.load_environment_config(mgr)
        self.assertIs(mgr.get_global_config("debug_logging"), False)
        self.assertEqual(mgr.get_global_config("cache_timeout"), 3600)

    def test_load_environment_config_unknown_noop(self):
        os.environ["VERENIGINGEN_ENVIRONMENT"] = "staging"
        mgr = ConfigurationManager()
        EnvironmentConfig.load_environment_config(mgr)
        # staging has no branch -> nothing injected
        self.assertIsNone(mgr.get_global_config("cache_timeout"))


class TestModuleLevelHelpers(EnhancedTestCase):
    """Module-level singleton accessors."""

    def test_get_config_manager_singleton(self):
        m1 = get_config_manager()
        m2 = get_config_manager()
        self.assertIs(m1, m2)

    def test_get_service_config_helper(self):
        cfg = get_service_config("member_services")
        self.assertIsInstance(cfg, ServiceConfig)

    def test_get_global_config_helper(self):
        # get_config_manager() ran load_from_settings + env config; in the
        # default 'development' test environment cache_timeout is seeded to 60.
        # We assert the helper round-trips a value we set ourselves to avoid
        # depending on ambient environment.
        mgr = get_config_manager()
        mgr.set_global_config("sweep_probe", "xyz")
        self.assertEqual(get_global_config("sweep_probe"), "xyz")

    def test_validate_service_configuration_helper(self):
        # A fresh service config has no required keys and no validators, so a
        # clean validation must return an empty error list (not just "a list").
        errors = validate_service_configuration("some_fresh_service")
        self.assertEqual(errors, [])
