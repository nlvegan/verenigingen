"""#1761: rate-limit counters (and rules) were keyed on the bare function name.

Two same-named endpoints in different modules therefore shared one counter, so
anonymous calls to the guest ``webhooks.mollie_subscription_webhook`` exhausted
the registered ``payment_gateways.mollie_subscription_webhook`` (found in the
review of #1770). Both functions are driven through their real decorators here.

Rule lookup: a row named by the full dotted path wins; the bare-name row (what
every shipped fixture and every operator-tuned row is) still applies to both.
"""

from unittest.mock import MagicMock

import frappe
import redis

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import webhooks
from verenigingen.verenigingen_payments.utils import payment_gateways

BARE = "mollie_subscription_webhook"
GUEST_TWIN = webhooks.mollie_subscription_webhook
REGISTERED = payment_gateways.mollie_subscription_webhook
LIMIT = 3
FIELDS = ["rate_limit_scope", "rate_limit_calls", "rate_limit_period_seconds"]


def _counters():
    r = redis.from_url(frappe.conf.redis_cache)
    return r, r.keys(f"cor_rate_limit:{frappe.local.site}:*:*{BARE}*")


class TestCorKeyIsModuleQualified(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.original = frappe.db.get_value("Critical Operation Rule", BARE, FIELDS, as_dict=True)
        self.assertIsNotNone(self.original, "rule row missing on this site")
        self.addCleanup(self._put_back_tuned_rule_and_request)
        self._drop_twin_counters()
        # TUNED row (operator set 3/h global): proves a bare-name row still applies.
        frappe.db.set_value(
            "Critical Operation Rule",
            BARE,
            {"rate_limit_scope": "global", "rate_limit_calls": LIMIT, "rate_limit_period_seconds": 3600},
        )
        self.rate_limit_patch.stop()  # the real limiter is under test, not the stub
        self.expectErrorLog("Mollie Webhook Security Failure", "Mollie Security - CRITICAL", "Webhook Processing Error")
        self._saved = (frappe.flags.in_test, getattr(frappe.local, "request", None))
        frappe.flags.in_test = False  # Mock justified: Infrastructure - execution context
        frappe.local.request = MagicMock(  # Mock justified: Infrastructure - simulated request
            method="POST", environ={"REMOTE_ADDR": "203.0.113.9"}
        )

    def _put_back_tuned_rule_and_request(self):
        frappe.flags.in_test, frappe.local.request = self._saved  # Mock justified: Infrastructure
        frappe.db.set_value("Critical Operation Rule", BARE, dict(self.original), update_modified=False)
        for name in ("webhooks.mollie_subscription_webhook", "payment_gateways.mollie_subscription_webhook"):
            frappe.db.delete("Critical Operation Rule", {"operation_name": f"{self._module_of_short_name(name)}.{BARE}"})
        self._drop_twin_counters()

    @staticmethod
    def _module_of_short_name(short):
        return {"webhooks": GUEST_TWIN, "payment_gateways": REGISTERED}[short.split(".")[0]].__module__

    def _drop_twin_counters(self):
        r, keys = _counters()
        for k in keys:
            r.delete(k)

    def _call_expecting_limiter_verdict(self, fn):
        """Return the rate-limit refusal message, or None if the call got past the limiter."""
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - only a rate-limit refusal matters here
            if "Rate limit" in str(e):
                return str(e)
        return None

    def _use_up_own_limit(self, fn):
        for i in range(LIMIT):
            self.assertIsNone(self._call_expecting_limiter_verdict(fn), f"call {i + 1} refused before the limit")
        self.assertIsNotNone(self._call_expecting_limiter_verdict(fn), "control: the function's own limit must still apply")

    def test_exhausting_the_guest_twin_does_not_refuse_the_registered_handler(self):
        self._use_up_own_limit(GUEST_TWIN)
        self.assertIsNone(self._call_expecting_limiter_verdict(REGISTERED), "registered handler refused by the guest twin's calls")

    def test_exhausting_the_registered_handler_does_not_refuse_the_guest_twin(self):
        self._use_up_own_limit(REGISTERED)
        self.assertIsNone(self._call_expecting_limiter_verdict(GUEST_TWIN))

    def test_a_row_named_by_the_dotted_path_applies_to_that_function_only(self):
        frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": f"{GUEST_TWIN.__module__}.{BARE}",
                "operation_type": "public",
                "security_level": "public",
                "enabled": 1,
                "description": "#1761 test row",
                "business_context": "#1761 test row",
                "rate_limit_calls": 1,
                "rate_limit_period_seconds": 3600,
                "rate_limit_scope": "global",
            }
        ).insert()
        self.assertIsNone(self._call_expecting_limiter_verdict(GUEST_TWIN))
        self.assertIn("/1 requests", self._call_expecting_limiter_verdict(GUEST_TWIN) or "", "dotted row (1 call) not applied")
        # The registered handler still runs under the tuned bare row (3 calls).
        for i in range(LIMIT):
            self.assertIsNone(self._call_expecting_limiter_verdict(REGISTERED), f"registered call {i + 1}")
        self.assertIsNotNone(self._call_expecting_limiter_verdict(REGISTERED))

    def test_counters_are_one_per_function(self):
        self._call_expecting_limiter_verdict(GUEST_TWIN)
        self._call_expecting_limiter_verdict(REGISTERED)
        _, keys = _counters()
        self.assertEqual(len(keys), 2, keys)


class TestRequireRoleKeepsTheFunctionIdentity(EnhancedTestCase):
    """`require_role` returned a bare `wrapper`, so every function it decorated got
    the rate-limit key `...authorization.wrapper` (one shared bucket, and a lookup of
    a bare row named "wrapper")."""

    def test_require_role_endpoints_get_distinct_keys(self):
        from verenigingen.api import schedule_maintenance as sm

        funcs = (sm.get_schedule_health_report, sm.cleanup_orphaned_schedules, sm.prevent_orphaned_schedules)
        keys = {f"{f.__module__}.{f.__name__}" for f in funcs}
        self.assertEqual(len(keys), 3, keys)
        self.assertFalse(any(k.endswith(".wrapper") for k in keys), keys)
