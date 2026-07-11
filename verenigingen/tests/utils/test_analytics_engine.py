"""Integration tests for verenigingen.utils.analytics_engine.AnalyticsEngine.

AnalyticsEngine is consumed directly as a class by
verenigingen/www/monitoring_dashboard.py (the live monitoring dashboard page).
Each public method is defensively coded to always return a dict and to surface
failures as ``{"error": ...}`` rather than raising, so callers can render a
partial dashboard.

These tests pin the public contract of all six methods (which transitively
exercises ~44 private helpers) and guard the ``tabError Log`` ``owner`` column
regression: the analytics SQL previously selected a non-existent ``user``
column, so ``analyze_error_patterns`` (and the dashboard's error panel)
returned ``{"error": ...}`` on every call. See the owner-column fix in the same
change that added this file.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.analytics_engine import AUDIT_CRITICAL_DOCTYPES, AnalyticsEngine


class TestAnalyticsEngine(VereningingenTestCase):
    """Contract + regression tests for the analytics engine."""

    def setUp(self):
        super().setUp()
        self.engine = AnalyticsEngine()

    # -- helpers ---------------------------------------------------------

    def _make_error_log(self, error_text, method="test_analytics", owner=None):
        """Insert a tabError Log row and return its name.

        FrappeTestCase rolls back after each test, so the row is visible to the
        engine's raw SQL within the same test and disappears afterwards; it is
        also tracked for class-level cleanup as a belt-and-braces measure.
        """
        doc = frappe.get_doc({"doctype": "Error Log", "method": method, "error": error_text}).insert(
            ignore_permissions=True
        )
        if owner:
            # owner is auto-set to the session user on insert; override it so
            # affected-user aggregation has more than one distinct value.
            frappe.db.set_value("Error Log", doc.name, "owner", owner, update_modified=False)
        self.track_class_doc("Error Log", doc.name)
        return doc.name

    # -- analyze_error_patterns -----------------------------------------

    def test_analyze_error_patterns_returns_contract(self):
        """Happy path returns the documented structure with no error key."""
        result = self.engine.analyze_error_patterns(days=7)

        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result, f"analyze_error_patterns failed: {result.get('error')}")
        self.assertIn("total_errors", result)
        self.assertIn("analysis_period", result)
        self.assertIn("patterns", result)
        self.assertIn("recommendations", result)

        # If there is any error-log data the pattern breakdown is fully built.
        if result["total_errors"] > 0:
            for key in (
                "daily_trends",
                "hourly_patterns",
                "error_types",
                "user_impact",
                "recurring_issues",
                "severity_distribution",
                "growth_trends",
            ):
                self.assertIn(key, result["patterns"])

    def test_analyze_error_patterns_counts_seeded_errors(self):
        """Regression: seeded Error Log rows are counted via the owner column.

        Pre-fix the SQL selected/grouped by a non-existent ``user`` column, so
        this method always returned ``{"error": ...}`` regardless of data. We
        seed rows owned by two distinct users and assert the method both
        succeeds and reflects them.
        """
        signature = f"AnalyticsEngineRegression {frappe.generate_hash(length=10)}"
        self._make_error_log(signature, owner="Administrator")
        self._make_error_log(signature, owner="Guest")
        self._make_error_log(signature, owner="Guest")

        result = self.engine.analyze_error_patterns(days=1)

        self.assertNotIn("error", result, "owner-column regression: method must not error on real data")
        self.assertGreaterEqual(result["total_errors"], 1)

        # user_impact aggregation runs over the owner-derived 'user' key.
        user_impact = result["patterns"]["user_impact"]
        self.assertIn("total_affected_users", user_impact)
        self.assertIsInstance(user_impact["total_affected_users"], int)

    def test_analyze_error_patterns_invalid_days_returns_error(self):
        """Bad input is caught and returned as a structured error, not raised."""
        result = self.engine.analyze_error_patterns(days="not-a-number")

        self.assertIsInstance(result, dict)
        self.assertIn("error", result)

    # -- forecast_performance_trends ------------------------------------

    def test_forecast_performance_trends_contract(self):
        result = self.engine.forecast_performance_trends(days_back=7, forecast_days=3)

        self.assertNotIn("error", result, f"forecast failed: {result.get('error')}")
        for key in (
            "analysis_period",
            "forecast_period",
            "historical_metrics",
            "forecasts",
            "trend_alerts",
            "capacity_planning",
            "confidence_score",
        ):
            self.assertIn(key, result)

        # Every metric category produces either a forecast or an explicit
        # insufficient-data marker.
        for category in ("api_performance", "database_performance", "system_load", "business_metrics"):
            self.assertIn(category, result["forecasts"])

    def test_performance_trend_like_queries_escape_percent(self):
        """Regression: LIKE '%...%' filters must escape % under positional params.

        The trend helpers pass start/end as ``%s`` params while their WHERE
        clauses contain ``error LIKE '%API%'`` / ``'%database%'``. With a single
        unescaped ``%`` MySQLdb raises ``ProgrammingError: not enough arguments
        for format string``; the helpers swallow it and return ``[]``, so the
        database/API performance forecasts were permanently empty. We seed a
        matching row and assert the helper returns it.
        """
        from datetime import timedelta

        from frappe.utils import now_datetime

        self._make_error_log("Simulated database connection timeout during SQL execution")
        self._make_error_log("Simulated API endpoint failure in REST handler")

        end = now_datetime()
        start = end - timedelta(days=1)

        db_trends = self.engine._get_database_performance_trends(start, end)
        api_trends = self.engine._get_api_performance_trends(start, end)

        self.assertIsInstance(db_trends, list)
        self.assertIsInstance(api_trends, list)
        self.assertGreaterEqual(len(db_trends), 1, "database-trend LIKE query silently returned no rows")
        self.assertGreaterEqual(len(api_trends), 1, "api-trend LIKE query silently returned no rows")

    # -- identify_error_hotspots ----------------------------------------

    def test_identify_error_hotspots_contract(self):
        result = self.engine.identify_error_hotspots(days=7)

        self.assertNotIn("error", result, f"hotspots failed: {result.get('error')}")
        self.assertIn("hotspots", result)
        for dimension in (
            "functional_areas",
            "user_groups",
            "time_periods",
            "error_types",
            "system_components",
        ):
            self.assertIn(dimension, result["hotspots"])

    # -- get_performance_recommendations --------------------------------

    def test_get_performance_recommendations_contract(self):
        result = self.engine.get_performance_recommendations()

        self.assertNotIn("error", result, f"recommendations failed: {result.get('error')}")
        self.assertIn("recommendations", result)
        self.assertIn("prioritized_actions", result)
        for category in (
            "error_patterns",
            "database_optimizations",
            "api_improvements",
            "caching_strategies",
            "resource_optimizations",
            "monitoring_enhancements",
            "business_process_optimizations",
        ):
            self.assertIn(category, result["recommendations"])

    # -- identify_compliance_gaps ---------------------------------------

    def test_identify_compliance_gaps_contract(self):
        result = self.engine.identify_compliance_gaps()

        self.assertNotIn("error", result, f"compliance failed: {result.get('error')}")
        self.assertIn("overall_compliance_score", result)
        self.assertIsInstance(result["overall_compliance_score"], (int, float))
        self.assertIn("compliance_areas", result)
        self.assertIn("sepa_compliance", result["compliance_areas"])
        self.assertIn("audit_trail_completeness", result["compliance_areas"])

    # -- _check_audit_trail_gaps (C6: was a hardcoded 85.0 stub) ---------

    def test_check_audit_trail_gaps_measures_real_tracking(self):
        """The audit-trail score must be COMPUTED from real change-tracking
        config, not the former fabricated 85.0. Every compliance-critical
        doctype in this app has track_changes enabled, so a correct real
        measurement scores 100 and reports no gaps."""
        result = self.engine._check_audit_trail_gaps()

        # Not the old hardcoded stub value.
        self.assertNotEqual(result["score"], 85.0, "score must be measured, not the 85.0 stub")
        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["status"], "compliant")
        self.assertEqual(result["recommendations"], [])
        # Every installed critical doctype is reported as tracked.
        for dt in AUDIT_CRITICAL_DOCTYPES:
            if frappe.db.exists("DocType", dt):
                self.assertIs(
                    result["coverage_by_process"].get(dt),
                    True,
                    f"{dt} is a track_changes doctype and must count as covered",
                )

    def test_audit_trail_coverage_flags_untracked_doctype(self):
        """A doctype without change tracking must drop the score and be named in
        the recommendations (Error Log is a core, non-track_changes doctype)."""
        result = self.engine._audit_trail_coverage(["Member", "Error Log"])

        self.assertEqual(result["score"], 50.0)
        self.assertEqual(result["status"], "gap_identified")
        self.assertIs(result["coverage_by_process"]["Member"], True)
        self.assertIs(result["coverage_by_process"]["Error Log"], False)
        self.assertTrue(
            any("Error Log" in rec for rec in result["recommendations"]),
            "the untracked doctype must be named in a remediation recommendation",
        )

    def test_audit_trail_coverage_skips_missing_doctype(self):
        """Nonexistent doctypes are skipped, not counted or crashed on."""
        result = self.engine._audit_trail_coverage(["Member", "Nonexistent DocType XYZ"])

        self.assertNotIn("Nonexistent DocType XYZ", result["coverage_by_process"])
        self.assertIn("Member", result["coverage_by_process"])
        self.assertEqual(result["score"], 100.0)

    # -- generate_insights_report ---------------------------------------

    def test_generate_insights_report_aggregates(self):
        """The umbrella report nests all sub-analyses and stays error-free.

        Notably ``error_analysis`` is the output of analyze_error_patterns, so a
        clean nested result also guards the owner-column regression end to end.
        """
        result = self.engine.generate_insights_report()

        self.assertNotIn("error", result, f"insights failed: {result.get('error')}")
        for key in (
            "executive_summary",
            "error_analysis",
            "performance_forecast",
            "compliance_status",
            "health_trends",
            "business_impact",
            "optimization_recommendations",
            "priority_actions",
        ):
            self.assertIn(key, result)

        self.assertNotIn(
            "error",
            result["error_analysis"],
            "nested error_analysis must succeed (owner-column regression guard)",
        )
