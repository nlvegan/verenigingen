"""#1763: mollie_subscription_webhook was a `global` 30 calls/h rule.

One counter for every sender, so the 31st notification in an hour was refused
(403, before the payload was verified). Its siblings are global 5000/h.

A fixture edit alone reaches fresh installs only (setup_critical_operation_rules
runs in after_install and never overwrites an existing row), so the behaviour
tests below go through the patch that carries the new value to existing sites.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import frappe
import redis

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

RULE = "mollie_subscription_webhook"
SIBLING = "handle_mollie_payment_webhook"
OLD_VALUES = {"rate_limit_scope": "global", "rate_limit_calls": 30, "rate_limit_period_seconds": 3600}
FIELDS = list(OLD_VALUES)


def _fixture_rule(name):
    path = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "critical_operation_rule.json"
    return next(r for r in json.loads(path.read_text()) if r["name"] == name)


def _counter_keys():
    r = redis.from_url(frappe.conf.redis_cache)
    return r, r.keys(f"cor_rate_limit:{frappe.local.site}:*:{RULE}*")


class TestMollieSubscriptionWebhookRateLimit(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.original = frappe.db.get_value("Critical Operation Rule", RULE, FIELDS, as_dict=True)
        self.assertIsNotNone(self.original, "rule row missing on this site")
        self.addCleanup(self._put_back_original_rule)
        self._clear_counters()

    def _put_back_original_rule(self):
        frappe.db.set_value("Critical Operation Rule", RULE, dict(self.original), update_modified=False)
        self._clear_counters()
        r, keys = _counter_keys()
        self.assertEqual(keys, [], "rate-limit counter leaked")

    def _clear_counters(self):
        r, keys = _counter_keys()
        for k in keys:
            r.delete(k)

    def _run_patch(self):
        from verenigingen.patches.v2_2.raise_mollie_subscription_webhook_rate_limit import execute

        execute()

    def test_fixture_is_not_a_low_global_ceiling(self):
        mine, sibling = _fixture_rule(RULE), _fixture_rule(SIBLING)
        self.assertEqual(mine["rate_limit_scope"], sibling["rate_limit_scope"])
        self.assertEqual(mine["rate_limit_calls"], sibling["rate_limit_calls"])
        self.assertEqual(mine["rate_limit_period_seconds"], sibling["rate_limit_period_seconds"])

    def test_patch_moves_an_untouched_old_row_to_the_fixture(self):
        frappe.db.set_value("Critical Operation Rule", RULE, OLD_VALUES)
        self._run_patch()
        row = frappe.db.get_value("Critical Operation Rule", RULE, FIELDS, as_dict=True)
        fixture = _fixture_rule(RULE)
        for f in FIELDS:
            self.assertEqual(row[f], fixture[f], f)

    def test_patch_leaves_a_customised_row_alone(self):
        """Each of the three guarded fields is varied on its own, so a guard that
        only looks at one of them (e.g. calls == 30) is caught."""
        customised = [
            {"rate_limit_scope": "global", "rate_limit_calls": 77, "rate_limit_period_seconds": 3600},
            {"rate_limit_scope": "per_user", "rate_limit_calls": 30, "rate_limit_period_seconds": 3600},
            {"rate_limit_scope": "global", "rate_limit_calls": 30, "rate_limit_period_seconds": 7200},
        ]
        for custom in customised:
            with self.subTest(custom=custom):
                frappe.db.set_value("Critical Operation Rule", RULE, dict(custom))
                self._run_patch()
                row = frappe.db.get_value("Critical Operation Rule", RULE, FIELDS, as_dict=True)
                self.assertEqual(dict(row), custom)

    def test_the_31st_call_through_the_real_decorator_is_not_refused(self):
        """Behaviour: an existing site (old row) after migrate. Calls run as
        Administrator because the role gate refuses Guest before the limiter."""
        from verenigingen.verenigingen_payments.utils.payment_gateways import (
            mollie_subscription_webhook,
        )

        frappe.db.set_value("Critical Operation Rule", RULE, OLD_VALUES)
        self._run_patch()
        old_calls = OLD_VALUES["rate_limit_calls"]

        saved_flag, saved_req = frappe.flags.in_test, getattr(frappe.local, "request", None)
        # EnhancedTestCase replaces validate_rate_limits with a stub; this test is
        # about the real limiter, so take the stub off (teardown tolerates a stopped patch).
        self.rate_limit_patch.stop()
        # Each call logs a "Mollie Webhook Security Failure" Error Log row (no credentials).
        self.expectErrorLog("Mollie Webhook Security Failure", "Mollie Security - CRITICAL")
        # Restored in finally, not addCleanup: cleanups run AFTER the harness tearDown.
        frappe.flags.in_test = False  # Mock justified: Infrastructure - execution context
        frappe.local.request = MagicMock(  # Mock justified: Infrastructure - simulated request
            method="POST", environ={"REMOTE_ADDR": "203.0.113.9"}
        )
        try:
            for i in range(old_calls + 1):
                try:
                    mollie_subscription_webhook()
                except frappe.PermissionError as e:
                    self.fail(f"call {i + 1} refused: {e}")
                except Exception as e:  # noqa: BLE001 - only a rate-limit refusal matters here
                    if "Rate limit" in str(e):
                        self.fail(f"call {i + 1} rate-limited: {e}")
        finally:
            frappe.flags.in_test = saved_flag  # Mock justified: Infrastructure - restore
            frappe.local.request = saved_req  # Mock justified: Infrastructure - restore

        # Control: the real limiter really counted these calls (a stubbed limiter
        # would also "not refuse" and prove nothing).
        r, keys = _counter_keys()
        self.assertEqual(len(keys), 1)
        self.assertEqual(int(r.get(keys[0])), old_calls + 1)
