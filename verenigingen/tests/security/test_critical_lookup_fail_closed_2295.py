"""#2295: an ERRORED "is this operation critical?" lookup must not read as "not critical".

``check_critical_operation_integration`` used to turn any exception into
``{"is_critical": False}`` and cache that for 300s, so one failure skipped the critical
gate for the endpoint for five minutes. Below it, the registry swallowed its own load
errors into "no rule".

The error is injected at ``frappe.db.exists`` for the "Critical Operation Rule" doctype,
which is below every swallowing layer (framework except, registry except, rule lookup).
Real ``@critical_api`` / ``@standard_api`` functions are called; the side effect is a list
append inside the endpoint body.
"""

import tempfile
from unittest.mock import patch

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import ValidationError as VValidationError
from verenigingen.utils.secure_operations import get_critical_operations_registry
from verenigingen.utils.security.api_security_framework import (
    _fixture_critical_operation_names,
    critical_api,
    get_security_framework,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.types import OperationType

RULE_OP = "probe_2295_ruled_credit"
UNRULED_CRITICAL_OP = "probe_2295_unruled_critical"
PLAIN_OP = "probe_2295_plain_read"
# A name the shipped fixtures define at security_level critical, on a high-level decorator.
FIXTURE_CRITICAL_OP = "admin_cancel_subscription"
THRESHOLD = 100
_PAGES = "verenigingen.templates.pages."
REAL_FIXTURE_CRITICAL_ENDPOINTS = (
    (_PAGES + "mollie_payments_debug", "admin_cancel_subscription"),
    (_PAGES + "mollie_payments_debug", "admin_revoke_mandate"),
    (_PAGES + "mollie_payments_debug", "admin_delete_customer"),
    (_PAGES + "mollie_bulk_payment_creation", "create_bulk_payments"),
    (_PAGES + "mollie_subscription_recreation", "recreate_subscriptions"),
    (
        "verenigingen.verenigingen_payments.page.mollie_bulk_payment_discovery.mollie_bulk_payment_discovery",
        "process_payment",
    ),
)
SIDE_EFFECTS = []


@critical_api(OperationType.FINANCIAL)
def probe_2295_ruled_credit(amount=None):
    SIDE_EFFECTS.append(("ruled", amount))
    return {"ok": True}


@critical_api(OperationType.FINANCIAL)
def probe_2295_unruled_critical(amount=None):
    SIDE_EFFECTS.append(("unruled_critical", amount))
    return {"ok": True}


@standard_api(OperationType.REPORTING)
def probe_2295_plain_read():
    SIDE_EFFECTS.append(("plain", None))
    return {"ok": True}


@high_security_api(OperationType.FINANCIAL)
def admin_cancel_subscription():
    SIDE_EFFECTS.append(("fixture_critical", None))
    return {"ok": True}


# Matches the fixture key "api_fix_stuck_schedule" ONLY through the api_<name> runtime name.
API_PREFIXED_OP = "fix_stuck_schedule"


@high_security_api(OperationType.FINANCIAL)
def fix_stuck_schedule():
    SIDE_EFFECTS.append(("api_prefixed", None))
    return {"ok": True}


ALL_OPS = (RULE_OP, UNRULED_CRITICAL_OP, PLAIN_OP, FIXTURE_CRITICAL_OP, API_PREFIXED_OP)
_real_exists = frappe.db.exists


def _exists_raising(error):
    def exists(dt, *args, **kwargs):
        if dt == "Critical Operation Rule":
            raise error
        return _real_exists(dt, *args, **kwargs)

    return exists


class TestCriticalLookupFailClosed(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        SIDE_EFFECTS.clear()
        self._remove_probe_rule()
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": RULE_OP,
                "operation_type": "financial",
                "security_level": "critical",
                "enabled": 1,
                "enable_business_validation": 1,
                "amount_threshold": THRESHOLD,
                "audit_level": "minimal",
            }
        )
        rule.flags.ignore_permissions = True
        rule.insert()
        self._reset_caches()

    def tearDown(self):
        self._remove_probe_rule()
        self._reset_caches()
        super().tearDown()

    def _remove_probe_rule(self):
        for name in frappe.get_all("Critical Operation Rule", {"operation_name": RULE_OP}, pluck="name"):
            frappe.delete_doc("Critical Operation Rule", name, force=True)

    def _reset_caches(self):
        registry = get_critical_operations_registry()
        for op in ALL_OPS:
            registry.operation_configs.pop(op, None)
            frappe.cache().delete_value(f"critical_operation_rule:{op}")
            frappe.cache.delete_value(f"critical_op_check:{__name__}.{op}")
        frappe.cache().delete_value("critical_operation_rules")
        frappe.cache().delete_value("critical_lookup_failure_logged:RuntimeError")

    def _call(self, fn, **kwargs):
        with self.set_user("Administrator"):
            return fn(**kwargs)

    def _errored(self, fn, error=None, **kwargs):
        """Call ``fn`` while every Critical Operation Rule existence lookup raises."""
        self.expectErrorLog("Critical operation lookup failed")
        injected = _exists_raising(error or RuntimeError("simulated lookup failure"))
        # Mock justified: a transient DB error cannot be produced on demand.
        with patch.object(frappe.db, "exists", injected):
            return self._call(fn, **kwargs)

    def _lookup_error_logs(self):
        return frappe.db.count("Error Log", {"method": ["like", "%Critical operation lookup failed%"]})

    def test_control_healthy_lookup_enforces_the_rule(self):
        with self.assertRaises(VValidationError) as ctx:
            self._call(probe_2295_ruled_credit, amount=THRESHOLD + 1)
        self.assertIn("Critical business rule violations", str(ctx.exception))
        self.assertEqual(SIDE_EFFECTS, [])

    def test_healthy_path_is_unchanged(self):
        self._call(probe_2295_ruled_credit, amount=THRESHOLD - 1)
        self._call(probe_2295_plain_read)
        self.assertEqual(SIDE_EFFECTS, [("ruled", THRESHOLD - 1), ("plain", None)])

    def test_errored_lookup_for_an_endpoint_with_a_fixture_critical_rule_is_refused(self):
        before = self._lookup_error_logs()
        with self.assertRaises(VValidationError) as ctx:
            self._errored(admin_cancel_subscription)
        self.assertEqual(SIDE_EFFECTS, [], "the critical operation ran although its lookup errored")
        message = str(ctx.exception)
        for leak in (FIXTURE_CRITICAL_OP, "simulated", "RuntimeError", "lookup failure"):
            self.assertNotIn(leak, message)
        self.assertEqual(self._lookup_error_logs(), before + 1)

    def test_errored_lookup_for_a_critical_api_endpoint_without_a_fixture_rule_proceeds(self):
        """Maintainer ruling: the decorator level alone does not make an endpoint "known critical"."""
        before = self._lookup_error_logs()
        self.assertEqual(self._errored(probe_2295_unruled_critical, amount=1), {"ok": True})
        self.assertEqual(SIDE_EFFECTS, [("unruled_critical", 1)])
        self.assertIsNone(frappe.cache.get_value(f"critical_op_check:{__name__}.{UNRULED_CRITICAL_OP}"))
        self.assertEqual(self._lookup_error_logs(), before + 1)

    def test_errored_lookup_refuses_an_endpoint_matching_only_via_the_api_prefixed_name(self):
        self.assertNotIn(API_PREFIXED_OP, _fixture_critical_operation_names())
        self.assertIn(f"api_{API_PREFIXED_OP}", _fixture_critical_operation_names())
        with self.assertRaises(VValidationError):
            self._errored(fix_stuck_schedule)
        self.assertEqual(SIDE_EFFECTS, [])

    def test_a_cache_error_in_the_log_dedup_does_not_mask_the_lookup_error(self):
        """The cache raising must behave exactly as without it: proceed or generic refusal, row written."""
        before = self._lookup_error_logs()
        # Mock justified: a Redis outage cannot be produced on demand.
        cache = frappe.cache()
        real_get, real_set = cache.get_value, cache.set_value

        def failing(real):
            def call(key, *args, **kwargs):
                if str(key).startswith("critical_lookup_failure_logged"):
                    raise ConnectionError("redis down")
                return real(key, *args, **kwargs)

            return call

        with (
            patch.object(cache, "get_value", failing(real_get)),
            patch.object(cache, "set_value", failing(real_set)),
        ):
            self.assertEqual(self._errored(probe_2295_plain_read), {"ok": True})
            self.assertEqual(self._lookup_error_logs(), before + 1)
            with self.assertRaises(VValidationError) as ctx:
                self._errored(admin_cancel_subscription)
        self.assertNotIn("redis", str(ctx.exception).lower())
        self.assertEqual(SIDE_EFFECTS, [("plain", None)])
        self.assertEqual(self._lookup_error_logs(), before + 2)

    def test_malformed_fixture_json_gives_the_generic_refusal_and_a_log_row(self):
        self.expectErrorLog("Critical operation fixtures unreadable")
        _fixture_critical_operation_names.cache_clear()
        try:
            with tempfile.TemporaryDirectory() as bad_dir:
                with open(f"{bad_dir}/critical_operation_rule.json", "w") as handle:
                    handle.write("[{not json")
                before = frappe.db.count("Error Log", {"method": ["like", "%fixtures unreadable%"]})
                # Mock justified: the shipped fixtures cannot be made malformed on demand.
                with patch.object(frappe, "get_app_path", return_value=bad_dir):
                    with self.assertRaises(VValidationError) as ctx:
                        self._errored(probe_2295_plain_read)
                self.assertNotIn("JSON", str(ctx.exception))
                self.assertEqual(SIDE_EFFECTS, [])
                after = frappe.db.count("Error Log", {"method": ["like", "%fixtures unreadable%"]})
                self.assertEqual(after, before + 1)
        finally:
            _fixture_critical_operation_names.cache_clear()

    def test_the_six_shipped_critical_endpoints_match_their_fixture_keys(self):
        """The runtime operation names of the real endpoints hit the fixture's critical keys.

        A key mismatch (bare versus module-qualified) would make the refusal match nothing.
        """
        import importlib

        framework_cls = type(get_security_framework())
        critical = _fixture_critical_operation_names()
        for module, function in REAL_FIXTURE_CRITICAL_ENDPOINTS:
            func = getattr(importlib.import_module(module), function)
            names = set(framework_cls._potential_operation_names(func))
            self.assertTrue(names & critical, f"{module}.{function} matches no fixture-critical key")

    def test_errored_lookup_for_an_endpoint_without_a_rule_proceeds(self):
        """Opposite harm: a transient blip must not block ordinary endpoints."""
        self.assertEqual(self._errored(probe_2295_plain_read), {"ok": True})
        self.assertEqual(SIDE_EFFECTS, [("plain", None)])

    def test_nothing_is_cached_after_an_error(self):
        # RULE_OP has a database rule only (not a shipped fixture), so it proceeds on error.
        self._errored(probe_2295_ruled_credit, amount=1)
        self.assertIsNone(frappe.cache.get_value(f"critical_op_check:{__name__}.{RULE_OP}"))
        # The next call, lookup healthy, is a fully normal critical call: the rule applies.
        SIDE_EFFECTS.clear()
        with self.assertRaises(VValidationError) as ctx:
            self._call(probe_2295_ruled_credit, amount=THRESHOLD + 1)
        self.assertIn("Critical business rule violations", str(ctx.exception))
        self.assertEqual(SIDE_EFFECTS, [])

    def test_nothing_is_cached_after_an_error_for_a_proceeding_endpoint_either(self):
        self._errored(probe_2295_plain_read)
        self.assertIsNone(frappe.cache.get_value(f"critical_op_check:{__name__}.{PLAIN_OP}"))

    def test_a_deadlock_propagates_unflattened(self):
        with self.assertRaises(QueryDeadlockError):
            self._errored(probe_2295_ruled_credit, error=QueryDeadlockError("1213"), amount=1)
        self.assertEqual(SIDE_EFFECTS, [])
        with self.assertRaises(QueryDeadlockError):
            self._errored(probe_2295_plain_read, error=QueryDeadlockError("1213"))
        self.assertEqual(SIDE_EFFECTS, [])

    def test_a_failed_registry_load_does_not_leave_an_empty_singleton(self):
        """Layer two: _load_configs used to swallow into {} and the singleton kept it."""
        import verenigingen.utils.secure_operations as secure_operations

        saved = secure_operations._critical_operations_registry
        secure_operations._critical_operations_registry = None
        frappe.cache().delete_value("critical_operation_rules")
        real_get_all = frappe.get_all

        def get_all(doctype, *args, **kwargs):
            if doctype == "Critical Operation Rule":
                raise RuntimeError("simulated load failure")
            return real_get_all(doctype, *args, **kwargs)

        try:
            # Mock justified: a transient DB error cannot be produced on demand.
            with patch.object(frappe, "get_all", get_all):
                with self.assertRaises(RuntimeError):
                    get_critical_operations_registry()
            self.assertIsNone(secure_operations._critical_operations_registry)
        finally:
            secure_operations._critical_operations_registry = saved

    def test_a_sustained_failure_writes_one_error_log_row_per_window(self):
        before = self._lookup_error_logs()
        for _i in range(5):
            self._errored(probe_2295_plain_read)
        self.assertEqual(self._lookup_error_logs(), before + 1)
        self.assertEqual(len(SIDE_EFFECTS), 5, "dedup of the log must not change who proceeds")

    def test_unreadable_fixtures_fail_closed_and_are_not_cached(self):
        """An empty fixture set would silently disable every refusal; it must refuse instead."""
        self.expectErrorLog("Critical operation fixtures unreadable")
        _fixture_critical_operation_names.cache_clear()
        try:
            with tempfile.TemporaryDirectory() as empty_dir:
                # Mock justified: the shipped fixtures cannot be made unreadable on demand.
                with patch.object(frappe, "get_app_path", return_value=empty_dir):
                    with self.assertRaises(VValidationError):
                        self._errored(probe_2295_plain_read)
            self.assertEqual(SIDE_EFFECTS, [])
            # Not cached: with the real fixtures back, the next errored call decides normally.
            self.assertEqual(self._errored(probe_2295_plain_read), {"ok": True})
            with self.assertRaises(VValidationError):
                self._errored(admin_cancel_subscription)
        finally:
            _fixture_critical_operation_names.cache_clear()
