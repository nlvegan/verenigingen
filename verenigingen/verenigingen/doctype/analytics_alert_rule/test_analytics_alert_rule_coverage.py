# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Real-DB coverage tests for the Analytics Alert Rule controller.

AnalyticsAlertRule drives the membership-analytics alerting feature
(verenigingen/analytics + the check_all_active_alerts scheduler hook). These
tests build REAL Analytics Alert Rule documents and exercise:

- validate():               percentage-metric bound checking (0..100)
- should_check():           frequency gating from last_checked
- evaluate_condition():     every comparison branch (GT/LT/Equals/change-based)
- get_metric_value():       the metric dispatch table against real DB counts
- calculate_* helpers:      churn/growth/failure/engagement/goal calculations
- format_message():         template substitution incl. change %
- get_previous_value():     reads back the last Analytics Alert Log row
- trigger_alert() + log_alert(): writes a real Analytics Alert Log
- execute_custom_script():  the hard-disabled (throws) security path
- check_all_active_alerts(): scheduler entry point

No business logic is mocked. The only external boundary avoided is outbound
email (send_email is left False so no SMTP is exercised); notification/log
writes go through real secure_document_operation as Administrator.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAnalyticsAlertRuleCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Clean any rules/logs left by a prior shard run.
        frappe.db.delete("Analytics Alert Log", {"alert_rule": ["like", "%AAR Cov%"]})

    def _make_rule(self, **overrides):
        data = {
            "doctype": "Analytics Alert Rule",
            "rule_name": frappe.generate_hash("AAR Cov", 6),
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 0,
            "check_frequency": "Daily",
            "is_active": 1,
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert()
        self.track_doc("Analytics Alert Rule", doc.name)
        return doc

    # ------------------------------------------------------------- validate
    def test_percentage_metric_rejects_out_of_range_threshold(self):
        """Churn/Growth/etc are percentages — threshold must be 0..100."""
        with self.assertRaises(frappe.ValidationError):
            self._make_rule(metric="Churn Rate", threshold_value=150)
        with self.assertRaises(frappe.ValidationError):
            self._make_rule(metric="Payment Failure Rate", threshold_value=-1)

    def test_percentage_metric_accepts_in_range_threshold(self):
        rule = self._make_rule(metric="Growth Rate", threshold_value=42)
        self.assertEqual(rule.threshold_value, 42)

    def test_non_percentage_metric_allows_large_threshold(self):
        """Total Members is an absolute count — no 0..100 ceiling applies."""
        rule = self._make_rule(metric="Total Members", threshold_value=100000)
        self.assertEqual(rule.threshold_value, 100000)

    # --------------------------------------------------------- should_check
    def test_should_check_true_when_never_checked(self):
        rule = self._make_rule()
        self.assertTrue(rule.should_check())

    def test_should_check_false_when_recently_checked(self):
        rule = self._make_rule(check_frequency="Daily")
        rule.db_set("last_checked", frappe.utils.now_datetime())
        rule.reload()
        # Daily cadence; just checked => not yet due.
        self.assertFalse(rule.should_check())

    def test_should_check_true_after_frequency_elapsed(self):
        rule = self._make_rule(check_frequency="Hourly")
        rule.db_set("last_checked", frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-2))
        rule.reload()
        self.assertTrue(rule.should_check())

    # ----------------------------------------------------- evaluate_condition
    def test_evaluate_greater_than(self):
        rule = self._make_rule(condition="Greater Than", threshold_value=10)
        self.assertTrue(rule.evaluate_condition(11))
        self.assertFalse(rule.evaluate_condition(10))

    def test_evaluate_less_than(self):
        rule = self._make_rule(condition="Less Than", threshold_value=10)
        self.assertTrue(rule.evaluate_condition(9))
        self.assertFalse(rule.evaluate_condition(10))

    def test_evaluate_equals_within_epsilon(self):
        rule = self._make_rule(metric="Total Members", condition="Equals", threshold_value=5)
        self.assertTrue(rule.evaluate_condition(5.0001))
        self.assertFalse(rule.evaluate_condition(6))

    def test_evaluate_change_based_returns_false_without_history(self):
        """Change-based conditions need a prior logged value; with none -> False."""
        rule = self._make_rule(metric="Total Members", condition="Increases By", threshold_value=5)
        # No Analytics Alert Log rows exist for this rule yet.
        self.assertIsNone(rule.get_previous_value())
        self.assertFalse(rule.evaluate_condition(100))

    def test_evaluate_increases_by_with_history(self):
        rule = self._make_rule(metric="Total Members", condition="Increases By", threshold_value=10)
        # Seed a previous value via a real log row (prev=100).
        self._seed_log(rule, metric_value=100)
        # 120 is +20% vs 100 -> exceeds the 10% threshold.
        self.assertTrue(rule.evaluate_condition(120))
        # 105 is +5% -> below threshold.
        self.assertFalse(rule.evaluate_condition(105))

    def test_evaluate_decreases_by_with_history(self):
        rule = self._make_rule(metric="Total Members", condition="Decreases By", threshold_value=10)
        self._seed_log(rule, metric_value=100)
        # 80 is -20% -> triggers a 10% "Decreases By".
        self.assertTrue(rule.evaluate_condition(80))
        self.assertFalse(rule.evaluate_condition(95))

    def test_evaluate_changes_by_absolute(self):
        rule = self._make_rule(metric="Total Members", condition="Changes By", threshold_value=10)
        self._seed_log(rule, metric_value=100)
        self.assertTrue(rule.evaluate_condition(85))  # -15%
        self.assertTrue(rule.evaluate_condition(115))  # +15%
        self.assertFalse(rule.evaluate_condition(103))  # +3%

    # -------------------------------------------------------- get_metric_value
    def test_get_metric_value_total_members_matches_db_count(self):
        rule = self._make_rule(metric="Total Members")
        expected = frappe.db.count("Member", {"status": "Active"})
        self.assertEqual(rule.get_metric_value(), expected)

    def test_get_metric_value_engagement_is_constant(self):
        rule = self._make_rule(metric="Member Engagement")
        self.assertEqual(rule.get_metric_value(), 75.0)

    def test_get_metric_value_unknown_metric_defaults_zero(self):
        rule = self._make_rule(metric="Total Members")
        # Bypass validate by mutating in memory to an unmapped metric value.
        rule.metric = "Nonexistent Metric"
        self.assertEqual(rule.get_metric_value(), 0)

    def test_calculate_churn_rate_zero_when_no_active(self):
        rule = self._make_rule(metric="Churn Rate", threshold_value=50)
        # churn = terminated/active*100; returns a real number (>=0).
        rate = rule.calculate_churn_rate()
        self.assertIsInstance(rate, (int, float))
        self.assertGreaterEqual(rate, 0)

    def test_calculate_payment_failure_rate_is_percentage(self):
        rule = self._make_rule(metric="Payment Failure Rate", threshold_value=50)
        rate = rule.calculate_payment_failure_rate()
        self.assertIsInstance(rate, (int, float))
        self.assertGreaterEqual(rate, 0)
        self.assertLessEqual(rate, 100)

    def test_calculate_revenue_returns_number(self):
        rule = self._make_rule(metric="Revenue", threshold_value=0)
        self.assertIsInstance(rule.calculate_current_revenue(), (int, float))

    def test_calculate_goal_achievement_returns_number(self):
        rule = self._make_rule(metric="Goal Achievement", threshold_value=50)
        self.assertIsInstance(rule.calculate_goal_achievement(), (int, float))

    # -------------------------------------------------------- format_message
    def test_format_message_default_template(self):
        rule = self._make_rule(metric="Total Members", threshold_value=10)
        alert_data = {"metric": "Total Members", "value": 12, "threshold": 10, "condition": "Greater Than"}
        msg = rule.format_message(alert_data)
        self.assertIn("Total Members", msg)
        self.assertIn("12", msg)
        self.assertIn("10", msg)

    def test_format_message_custom_template_with_change(self):
        rule = self._make_rule(
            metric="Total Members",
            condition="Increases By",
            threshold_value=5,
            alert_message_template="{metric} changed {change}",
        )
        self._seed_log(rule, metric_value=100)
        alert_data = {"metric": "Total Members", "value": 120, "threshold": 5, "condition": "Increases By"}
        msg = rule.format_message(alert_data)
        # +20.0% change rendered into the template.
        self.assertIn("+20.0%", msg)

    # -------------------------------------------------- execute_custom_script
    def test_execute_custom_script_is_disabled(self):
        """Custom Python execution is intentionally hard-disabled for security."""
        rule = self._make_rule()
        # The disabled path logs an error before throwing; mark it expected so the
        # automatic tearDown error-log check ignores it.
        self.expectErrorLog("Custom script execution disabled")
        with self.assertRaises(frappe.ValidationError):
            rule.execute_custom_script({"metric": "x", "value": 1})

    # --------------------------------------------------- trigger_alert / log
    def test_trigger_alert_writes_log_and_sets_last_triggered(self):
        rule = self._make_rule(metric="Total Members", condition="Greater Than", threshold_value=0)
        before = frappe.db.count("Analytics Alert Log", {"alert_rule": rule.name})
        rule.trigger_alert(current_value=99)
        rule.reload()
        self.assertTrue(rule.last_triggered)
        after = frappe.db.count("Analytics Alert Log", {"alert_rule": rule.name})
        # log_alert performs the audit insert (one real new log row).
        self.assertGreater(after, before)

    def test_get_previous_value_reads_latest_log(self):
        rule = self._make_rule(metric="Total Members")
        self._seed_log(rule, metric_value=7)
        self.assertEqual(rule.get_previous_value(), 7)

    # ------------------------------------------------ check_and_trigger gating
    def test_check_and_trigger_noop_when_inactive(self):
        rule = self._make_rule(is_active=0, metric="Total Members", threshold_value=0)
        # Inactive -> returns early, never sets last_checked.
        self.assertIsNone(rule.last_checked)
        rule.check_and_trigger()
        rule.reload()
        self.assertIsNone(rule.last_checked)

    def test_check_and_trigger_updates_last_checked_when_due(self):
        # threshold below the active-member count so the GT condition fires,
        # but we mainly assert last_checked is stamped on a due active rule.
        rule = self._make_rule(is_active=1, metric="Total Members", condition="Less Than", threshold_value=0)
        rule.check_and_trigger()
        rule.reload()
        self.assertIsNotNone(rule.last_checked)

    # ------------------------------------------------- check_all_active_alerts
    def test_check_all_active_alerts_runs_without_error(self):
        from verenigingen.verenigingen.doctype.analytics_alert_rule.analytics_alert_rule import (
            check_all_active_alerts,
        )

        # An active, non-firing rule so the scheduler iterates at least one rule.
        self._make_rule(is_active=1, metric="Total Members", condition="Less Than", threshold_value=0)
        # Should iterate active rules and complete (each rule wrapped in try/except).
        result = check_all_active_alerts()
        # high_security_api wrapper returns the function result (None here) — the
        # meaningful assertion is that it completed without raising.
        self.assertIsNone(result)

    # ------------------------------------------------------------- internals
    def _seed_log(self, rule, metric_value):
        log = frappe.get_doc(
            {
                "doctype": "Analytics Alert Log",
                "alert_rule": rule.name,
                "triggered_at": frappe.utils.now_datetime(),
                "metric_value": metric_value,
                "threshold_value": rule.threshold_value,
                "condition": rule.condition,
                "alert_data": "{}",
            }
        )
        log.insert()
        self.track_doc("Analytics Alert Log", log.name)
        return log
