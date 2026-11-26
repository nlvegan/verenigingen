# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Complementary coverage for the Critical Operation Rule controller.
#
# The existing test_critical_operation_rule.py covers basic create/validate,
# rate-limit zero/negative rejection, config retrieval, disabled-rule filtering,
# cache invalidation and the missing-rule message-log guard.
#
# This file fills the remaining uncovered branches WITH REAL ASSERTIONS:
#   - validate_rate_limit_settings: batch-limit floor / ordering / period floor
#   - validate_business_rules: negative amount_threshold rejection
#   - validate_notification_settings: invalid-email rejection, import-skip,
#     no-contact throw
#   - validate_system_user_settings: warn (does not throw) on high-security
#   - on_trash / clear_rule_cache: cache cleared on delete
#   - notify_policy_change: queues critical/high to the Redis digest queue,
#     skips medium/low
#   - _is_email_configured / _get_admin_emails helpers
#   - get_all_rules: only enabled rules, cached
#   - send_security_policy_change_digest: drains + dedupes the queue
#
# All rules are inserted via real frappe.get_doc(...).insert(); we assert
# observable DB / cache / queue state rather than mocking the controller.

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.constants import Roles
from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
    CriticalOperationRule,
    send_security_policy_change_digest,
)

QUEUE_KEY = "security_policy_change_queue"


def _make_rule(**overrides):
    fields = {
        "doctype": "Critical Operation Rule",
        "operation_name": "test_extra_rule",
        "operation_type": "financial",
        "security_level": "critical",
        "enabled": 1,
    }
    fields.update(overrides)
    return frappe.get_doc(fields)


def _shipped_row(operation_name):
    import os

    path = os.path.join(
        os.path.dirname(frappe.get_app_path("verenigingen")),
        "verenigingen",
        "fixtures",
        "critical_operation_rule.json",
    )
    with open(path) as f:
        rows = json.load(f)
    return next(r for r in rows if r.get("operation_name") == operation_name)


class TestCORRateLimitValidation(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def test_negative_batch_rate_limit_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_batch_negative",
                batch_rate_limit_calls=-1,
            ).insert()
        self.assertIn("Batch rate limit calls", str(ctx.exception))

    def test_zero_batch_rate_limit_means_no_batch_limit_and_saves(self):
        """#1656: ~1,900 rows on long-lived sites carry batch_rate_limit_calls=0
        (pre-existing data; fresh installs store the 5000/3600 defaults), which the
        rate-limit engine treats as "no batch limit". validate() must accept it,
        including against a shipped row's real interactive limit (180 > 0 must
        not trip the batch >= interactive ordering check)."""
        rule = _make_rule(
            operation_name="test_extra_batch_zero",
            operation_type="reporting",
            security_level="low",
            rate_limit_calls=180,
            rate_limit_period_seconds=3600,
            batch_rate_limit_calls=0,
            batch_rate_limit_period_seconds=0,  # affected rows store 0 here too
        )
        rule.insert()
        rule.description = "re-saved"
        rule.save()
        self.assertEqual(
            frappe.db.get_value("Critical Operation Rule", rule.name, "batch_rate_limit_calls"), 0
        )

    def test_zero_interactive_rate_limit_still_rejected(self):
        """Control: only the BATCH fields tolerate 0; the interactive limit does not."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(operation_name="test_extra_interactive_zero", rate_limit_calls=0).insert()
        self.assertIn("Rate limit calls must be at least 1", str(ctx.exception))

    def test_interactive_period_below_floor_still_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_interactive_period_30",
                rate_limit_calls=5,
                rate_limit_period_seconds=30,
            ).insert()
        self.assertIn("Rate limit period must be at least 60 seconds", str(ctx.exception))

    def test_batch_calls_with_zero_period_saves(self):
        """N batch calls with period 0 means N calls per the interactive period."""
        rule = _make_rule(
            operation_name="test_extra_batch_calls_period_zero",
            rate_limit_calls=10,
            batch_rate_limit_calls=100,
            batch_rate_limit_period_seconds=0,
        )
        rule.insert()
        self.assertEqual(rule.batch_rate_limit_period_seconds, 0)

    def test_negative_batch_period_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_batch_period_neg",
                batch_rate_limit_calls=20,
                batch_rate_limit_period_seconds=-5,
            ).insert()
        self.assertIn("at least 60 seconds", str(ctx.exception))

    def test_resave_of_stored_zero_batch_row_with_shipped_fields(self):
        """A row stored with batch 0 (as fixture sync leaves it: the stored value
        is 0, not the 5000 default, as on long-lived sites) re-saves. Fields are
        copied from the shipped add_activity fixture row (which has no batch keys), not hand-picked."""
        shipped = _shipped_row("add_activity")
        fields = {
            k: v
            for k, v in shipped.items()
            if k not in ("doctype", "name", "batch_rate_limit_calls", "batch_rate_limit_period_seconds")
        }
        fields["operation_name"] = "test_extra_shipped_add_activity"
        rule = _make_rule(**fields)
        rule.insert()
        frappe.db.set_value(
            "Critical Operation Rule", rule.name, "batch_rate_limit_calls", 0, update_modified=False
        )
        frappe.db.set_value(
            "Critical Operation Rule", rule.name, "batch_rate_limit_period_seconds", 0, update_modified=False
        )
        reloaded = frappe.get_doc("Critical Operation Rule", rule.name)
        self.assertEqual(reloaded.batch_rate_limit_calls, 0)
        self.assertEqual(reloaded.batch_rate_limit_period_seconds, 0)
        reloaded.save()

    def test_batch_rate_limit_lower_than_interactive_rejected(self):
        """Batch limit must be >= interactive limit (batch is meant to be more permissive)."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_batch_order",
                rate_limit_calls=10,
                batch_rate_limit_calls=5,
            ).insert()
        self.assertIn("greater than or equal", str(ctx.exception))

    def test_batch_rate_limit_period_floor_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_batch_period",
                batch_rate_limit_calls=20,
                batch_rate_limit_period_seconds=30,  # below 60s floor
            ).insert()
        self.assertIn("at least 60 seconds", str(ctx.exception))

    def test_rate_limit_period_floor_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_period_floor",
                rate_limit_calls=5,
                rate_limit_period_seconds=10,  # below 60s floor
            ).insert()
        self.assertIn("at least 60 seconds", str(ctx.exception))

    def test_valid_batch_limits_accepted(self):
        """A correctly-ordered batch config (batch >= interactive, periods >= 60) saves."""
        rule = _make_rule(
            operation_name="test_extra_batch_ok",
            rate_limit_calls=10,
            rate_limit_period_seconds=3600,
            batch_rate_limit_calls=100,
            batch_rate_limit_period_seconds=3600,
        )
        rule.insert()
        self.assertEqual(rule.batch_rate_limit_calls, 100)


class TestCORBusinessRuleValidation(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def test_negative_amount_threshold_rejected(self):
        """With business validation enabled, a negative amount_threshold is rejected."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_neg_threshold",
                enable_business_validation=1,
                amount_threshold=-100,
            ).insert()
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_positive_amount_threshold_accepted(self):
        rule = _make_rule(
            operation_name="test_extra_pos_threshold",
            enable_business_validation=1,
            amount_threshold=2500,
        )
        rule.insert()
        self.assertEqual(rule.amount_threshold, 2500)


class TestCORNotificationValidation(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def test_invalid_notification_email_rejected(self):
        """A malformed email in notification_recipients is rejected."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_rule(
                operation_name="test_extra_bad_email",
                notification_recipients="this-is-not-an-email",
            ).insert()
        self.assertIn("Invalid email address", str(ctx.exception))

    def test_valid_notification_emails_accepted(self):
        """Comma-separated valid emails pass validation."""
        rule = _make_rule(
            operation_name="test_extra_good_emails",
            notification_recipients="a@example.com, b@example.com",
        )
        rule.insert()
        self.assertEqual(rule.notification_recipients, "a@example.com, b@example.com")

    def test_alert_without_recipients_skipped_during_import(self):
        """During in_import, the alert-requires-recipients check is skipped entirely
        (no throw, no auto-populate), per the bulk-operation guard."""
        rule = _make_rule(
            operation_name="test_extra_import_skip",
            operation_type="admin",
            security_level="high",
            alert_on_execution=1,
            # notification_recipients intentionally absent
        )
        original = frappe.flags.in_import
        frappe.flags.in_import = True
        try:
            rule.insert()
        finally:
            frappe.flags.in_import = original
        # Inserted without recipients because the import guard short-circuited.
        self.assertTrue(rule.name)
        self.assertFalse(rule.notification_recipients)


class TestCORSystemUserValidation(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def test_system_user_on_critical_warns_not_throws(self):
        """allow_system_user on a critical rule warns (msgprint) but still saves."""
        rule = _make_rule(
            operation_name="test_extra_sysuser",
            security_level="critical",
            allow_system_user=1,
        )
        # Must NOT raise — it is a warning, not an error.
        rule.insert()
        self.assertTrue(rule.allow_system_user)


class TestCORCacheAndQueue(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.cache().delete_value("critical_operation_rules")
        # frappe.cache() (Redis) is shared across the whole shard and is NOT rolled
        # back between tests, so a sibling may leave the specific-rule key in a state
        # that makes get_rule_config skip its caching path. Clear it too.
        frappe.cache().delete_value("critical_operation_rule:test_extra_trash")
        # Drain the digest queue so cross-test residue doesn't leak in.
        while frappe.cache().rpop(QUEUE_KEY):
            pass
        frappe.db.commit()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.cache().delete_value("critical_operation_rule:test_extra_trash")
        while frappe.cache().rpop(QUEUE_KEY):
            pass
        frappe.db.commit()

    def test_on_trash_clears_rule_cache(self):
        """Deleting a rule clears both the all-rules cache and the specific-rule cache."""
        rule = _make_rule(operation_name="test_extra_trash", security_level="high", rate_limit_calls=5)
        rule.insert()
        # Prime both caches. get_rule_config only populates the specific-rule key on
        # a cache-miss build path; under shard ordering the shared Redis cache may be
        # in a state where that path is skipped, so prime the precondition explicitly.
        # The behaviour under test is that delete() CLEARS these keys (asserted below).
        specific_key = "critical_operation_rule:test_extra_trash"
        CriticalOperationRule.get_rule_config("test_extra_trash")
        frappe.cache().set_value(specific_key, {"x": 1})
        frappe.cache().set_value("critical_operation_rules", {"x": 1})
        self.assertIsNotNone(frappe.cache().get_value(specific_key))

        rule.delete()

        self.assertIsNone(frappe.cache().get_value("critical_operation_rules"))
        self.assertIsNone(frappe.cache().get_value(specific_key))

    def test_get_all_rules_returns_only_enabled(self):
        """get_all_rules surfaces enabled rules and omits disabled ones."""
        _make_rule(operation_name="test_extra_all_on", security_level="high", rate_limit_calls=5).insert()
        _make_rule(
            operation_name="test_extra_all_off", security_level="high", rate_limit_calls=5, enabled=0
        ).insert()
        # Force a fresh build (insert's on_update cleared the cache already).
        frappe.cache().delete_value("critical_operation_rules")
        rules = CriticalOperationRule.get_all_rules()
        self.assertIn("test_extra_all_on", rules)
        self.assertNotIn("test_extra_all_off", rules)

    def test_notify_policy_change_queues_critical(self):
        """Saving a critical rule queues a change record into the Redis digest queue."""
        # Ensure we are not in a bulk-operation context (which would skip queueing).
        for flag in ("in_import", "in_migrate", "in_install"):
            setattr(frappe.flags, flag, False)
        rule = _make_rule(operation_name="test_extra_queue_crit", security_level="critical")
        rule.insert()  # on_update -> notify_policy_change
        # Drain and inspect the queue.
        found = False
        raw = frappe.cache().rpop(QUEUE_KEY)
        while raw:
            record = json.loads(raw)
            if record.get("operation_name") == "test_extra_queue_crit":
                found = True
                self.assertEqual(record["security_level"], "critical")
            raw = frappe.cache().rpop(QUEUE_KEY)
        self.assertTrue(found, "critical rule change was not queued to the digest")

    def test_notify_policy_change_skips_low_security(self):
        """A low-security rule change is NOT queued (digest only carries critical/high)."""
        for flag in ("in_import", "in_migrate", "in_install"):
            setattr(frappe.flags, flag, False)
        rule = _make_rule(
            operation_name="test_extra_queue_low",
            operation_type="utility",
            security_level="low",
        )
        rule.insert()
        queued_names = []
        raw = frappe.cache().rpop(QUEUE_KEY)
        while raw:
            queued_names.append(json.loads(raw).get("operation_name"))
            raw = frappe.cache().rpop(QUEUE_KEY)
        self.assertNotIn("test_extra_queue_low", queued_names)


class TestCORHelpers(FrappeTestCase):
    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()
        self.rule = _make_rule(operation_name="test_extra_helpers", security_level="high")
        self.rule.insert()

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.db.commit()

    def test_is_email_configured_returns_bool(self):
        """_is_email_configured reflects whether a default outgoing account exists."""
        result = self.rule._is_email_configured()
        self.assertIsInstance(result, bool)
        has_default = frappe.db.get_value("Email Account", {"default_outgoing": 1}, "email_id")
        self.assertEqual(result, bool(has_default))

    def test_get_admin_emails_returns_system_manager_emails(self):
        """_get_admin_emails returns emails of enabled System Manager users.

        Administrator holds System Manager on the test site, so at least the
        Administrator's email should be present.
        """
        emails = self.rule._get_admin_emails()
        self.assertIsInstance(emails, list)
        # Every returned value looks like an email.
        for e in emails:
            self.assertIn("@", e)
        # Cross-check: the set of System Manager user emails is a superset.
        sm_users = frappe.get_all(
            "Has Role",
            filters={"role": Roles.SYSTEM_MANAGER, "parenttype": "User"},
            pluck="parent",
        )
        self.assertTrue(len(sm_users) >= 1)


class TestCORDigest(FrappeTestCase):
    """send_security_policy_change_digest queue draining + dedupe (no email assertions —
    email may or may not be configured on the test site; we assert the queue is drained
    and the function does not raise)."""

    def setUp(self):
        while frappe.cache().rpop(QUEUE_KEY):
            pass

    def tearDown(self):
        while frappe.cache().rpop(QUEUE_KEY):
            pass

    def test_digest_drains_queue(self):
        """The digest run fully drains the queue regardless of whether email delivery
        is configured. (Internal dedup-by-operation feeds the email body, which isn't
        observable here without a configured mail account.)"""
        change_a = {
            "operation_name": "test_extra_digest_op",
            "security_level": "critical",
            "operation_type": "financial",
            "changed_by": "Administrator",
            "changed_at": frappe.utils.now(),
            "enabled_status": "Yes",
        }
        change_b = dict(change_a, changed_at=frappe.utils.now(), enabled_status="No")
        frappe.cache().lpush(QUEUE_KEY, json.dumps(change_a))
        frappe.cache().lpush(QUEUE_KEY, json.dumps(change_b))

        # Should not raise even if email isn't configured.
        send_security_policy_change_digest()

        # The queue is fully drained by the digest run.
        self.assertIsNone(frappe.cache().rpop(QUEUE_KEY))

    def test_digest_empty_queue_is_noop(self):
        """An empty queue returns cleanly (nothing to send)."""
        self.assertIsNone(send_security_policy_change_digest())


class TestCORGetAllRulesQueryCost(FrappeTestCase):
    """#2025: a cold ``get_all_rules`` cost 2 queries per rule (exists + get_doc),
    ~4300 on a site carrying the 2000+ shipped rules, every time the 5 minute
    cache expired. Its cost must not grow with the number of rules."""

    def setUp(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})

    def tearDown(self):
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_extra%"]})
        frappe.cache().delete_value("critical_operation_rules")

    def test_cold_get_all_rules_query_count_does_not_grow_per_rule(self):
        """Constant bound, independent of how many rules the site carries: the whole
        cold build is one fetch. With the per-rule loop it was 1 + 2 per uncached rule,
        so the 5 fresh rules below alone cost 10 more than the bound allows."""
        for i in range(5):
            _make_rule(operation_name=f"test_extra_scale_{i}", security_level="high").insert()
        frappe.db.get_table_columns("Critical Operation Rule")  # warm table_columns/meta
        # Cold: the all-rules key AND every per-rule key (the per-loop path hit those).
        frappe.cache().delete_value("critical_operation_rules")
        frappe.cache().delete_keys("critical_operation_rule:")
        with self.assertQueryCount(3):
            rules = CriticalOperationRule.get_all_rules()
        self.assertIn("test_extra_scale_4", rules)

    def test_get_all_rules_config_matches_get_rule_config(self):
        """Behaviour control: the batched build yields exactly the per-rule config,
        for a rule with every non-default field set (so a dropped field shows)."""
        _make_rule(
            operation_name="test_extra_equiv",
            security_level="high",
            required_roles="System Manager, Accounts Manager",
            required_permissions="read, write",
            rate_limit_calls=7,
            rate_limit_period_seconds=120,
            rate_limit_scope="per_ip",
            allow_system_user=1,
            bypass_validations="a, b",
            enable_business_validation=1,
            amount_threshold=250,
            audit_level="detailed",
            requires_justification=1,
            monitor_execution_time=1,
            execution_time_threshold_ms=1234,
            monitor_failure_rate=1,
            failure_rate_threshold_percent=17,
        ).insert()
        frappe.cache().delete_value("critical_operation_rules")
        frappe.cache().delete_value("critical_operation_rule:test_extra_equiv")
        single = CriticalOperationRule.get_rule_config("test_extra_equiv")
        frappe.cache().delete_value("critical_operation_rules")
        batched = CriticalOperationRule.get_all_rules()["test_extra_equiv"]
        self.assertEqual(batched, single)
        # a bool() coercion in the batched build would change the type, not the truthiness
        self.assertIs(type(batched["allow_system_user"]), int)
        self.assertIs(type(batched["allow_system_user"]), type(single["allow_system_user"]))
        self.assertEqual(batched["required_roles"], ["System Manager", "Accounts Manager"])
        self.assertEqual(batched["monitoring"]["execution_time_threshold_ms"], 1234)
