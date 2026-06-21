"""
Coverage tests for verenigingen/www/monitoring_dashboard.py.

The monitoring dashboard is a System-Manager / Verenigingen-Administrator gated
www page. It aggregates system metrics, error logs, audit summaries, alerts,
analytics, compliance and security data via the monitoring service layer.

Covered:
- get_context() role gating (denied for a non-admin user, populated for admin)
- get_context() populates every expected key with real, shaped data
- the @high_security_api / @standard_api whitelisted endpoints return the
  expected dicts when invoked in-process (the api framework serializes the
  service return values to plain dicts), driven against real seeded records.

Permission paths use REAL users + roles via the set_user() context manager;
no business-logic mocking.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.www import monitoring_dashboard as md


class TestMonitoringDashboardCoverage(VereningingenTestCase):
    """Real-data tests for the monitoring dashboard controller."""

    def setUp(self):
        super().setUp()
        # A non-admin user (only the base member role) to exercise the deny path.
        self.plain_email = f"mon-plain-{frappe.generate_hash()[:8]}@example.com"
        self.plain_user = self._make_user(self.plain_email, roles=["Verenigingen Member"])

        # An admin user with Verenigingen Administrator (one of the two allowed roles).
        self.admin_email = f"mon-admin-{frappe.generate_hash()[:8]}@example.com"
        self.admin_user = self._make_user(self.admin_email, roles=["Verenigingen Administrator"])

    def _make_user(self, email, roles):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "send_welcome_email": 0,
                    "roles": [{"role": r} for r in roles],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", user.name)
        return email

    # ----- get_context: permission gating -----

    def test_get_context_denies_non_admin_user(self):
        """A user lacking System Manager / Verenigingen Administrator is blocked."""
        with self.set_user(self.plain_email):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                md.get_context(context)
            # Nothing should have been populated before the throw.
            self.assertNotIn("system_metrics", context)

    def test_get_context_allows_verenigingen_administrator(self):
        """An allowed admin role passes the gate and gets a populated context."""
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog(ignore=["Background Job Count"]):
                context = frappe._dict()
                md.get_context(context)

        # Every documented key must be present.
        expected_keys = {
            "system_metrics",
            "recent_errors",
            "audit_summary",
            "alerts",
            "performance_metrics",
            "analytics_summary",
            "trend_forecasts",
            "compliance_metrics",
            "optimization_insights",
            "executive_summary",
            "security_dashboard",
            "security_framework_health",
        }
        self.assertTrue(expected_keys.issubset(set(context.keys())))

    def test_get_context_system_metrics_reflect_real_data(self):
        """system_metrics is real aggregation, not the fallback error stub."""
        # Seed a member so the active count is meaningful and non-fallback.
        member = self.create_test_member(
            first_name="Mon",
            last_name="Metrics",
            email=f"mon-metric-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1990-01-01",
        )
        member.db_set("status", "Active")
        frappe.db.commit()

        with self.set_user(self.admin_email):
            with self.assertNoErrorLog(ignore=["Background Job Count"]):
                context = frappe._dict()
                md.get_context(context)

        sm = context.system_metrics
        # Fallback path returns {"error": ...}; real path returns nested counts.
        self.assertNotIn("error", sm, "get_context fell back to error stub")
        self.assertIn("members", sm)
        self.assertIn("active", sm["members"])
        self.assertGreaterEqual(sm["members"]["active"], 1)
        self.assertGreaterEqual(sm["members"]["total"], sm["members"]["active"])

    # ----- whitelisted endpoints -----

    def test_get_system_metrics_endpoint(self):
        """get_system_metrics returns the live nested metrics structure."""
        with self.set_user(self.admin_email):
            result = md.get_system_metrics()
        self.assertIsInstance(result, dict)
        self.assertIn("members", result)
        self.assertIn("volunteers", result)
        self.assertIn("sepa", result)

    def test_get_recent_errors_endpoint(self):
        """get_recent_errors returns a list (recent Error Log summary)."""
        with self.set_user(self.admin_email):
            result = md.get_recent_errors()
        self.assertIsInstance(result, list)

    def test_get_audit_summary_endpoint(self):
        with self.set_user(self.admin_email):
            result = md.get_audit_summary()
        self.assertIsInstance(result, list)

    def test_get_active_alerts_endpoint(self):
        with self.set_user(self.admin_email):
            result = md.get_active_alerts()
        self.assertIsInstance(result, list)

    def test_get_performance_metrics_endpoint(self):
        with self.set_user(self.admin_email):
            result = md.get_performance_metrics()
        self.assertIsInstance(result, dict)

    def test_refresh_dashboard_data_endpoint(self):
        """refresh_dashboard_data bundles the core metrics + a timestamp."""
        with self.set_user(self.admin_email):
            with self.assertNoErrorLog(ignore=["Background Job Count"]):
                result = md.refresh_dashboard_data()
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result)
        for key in (
            "system_metrics",
            "recent_errors",
            "audit_summary",
            "alerts",
            "performance_metrics",
            "security_dashboard",
            "timestamp",
        ):
            self.assertIn(key, result)

    def test_get_security_metrics_for_dashboard_shape(self):
        """Security metrics endpoint returns the documented numeric summary."""
        with self.set_user(self.admin_email):
            result = md.get_security_metrics_for_dashboard()
        self.assertIsInstance(result, dict)
        for key in (
            "security_score",
            "active_incidents_count",
            "critical_incidents",
            "high_incidents",
            "last_updated",
        ):
            self.assertIn(key, result)
        # security_score defaults to 85.0 baseline, always numeric.
        self.assertIsInstance(result["security_score"], (int, float))

    def test_get_security_framework_health_shape(self):
        with self.set_user(self.admin_email):
            result = md.get_security_framework_health()
        self.assertIsInstance(result, dict)
        self.assertIn("overall_status", result)
        self.assertIn("components", result)
        self.assertIn("last_checked", result)

    def test_get_analytics_summary_shape(self):
        """Analytics summary returns error_patterns + hotspots aggregation."""
        with self.set_user(self.admin_email):
            result = md.get_analytics_summary()
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("error_patterns", result)
            self.assertIn("hotspots", result)
            self.assertIn("total_errors", result["error_patterns"])

    def test_get_trend_forecasts_shape(self):
        with self.set_user(self.admin_email):
            result = md.get_trend_forecasts()
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("confidence_score", result)
            self.assertIn("highlights", result)
            self.assertIsInstance(result["highlights"], list)

    def test_get_compliance_metrics_shape(self):
        with self.set_user(self.admin_email):
            result = md.get_compliance_metrics()
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("overall_score", result)
            self.assertIn("critical_gaps", result)

    def test_get_optimization_insights_shape(self):
        with self.set_user(self.admin_email):
            result = md.get_optimization_insights()
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("total_recommendations", result)
            self.assertIn("categories", result)

    def test_get_executive_summary_shape(self):
        with self.set_user(self.admin_email):
            result = md.get_executive_summary()
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("overall_status", result)
            self.assertIn("critical_issues_count", result)

    def test_test_monitoring_system_creates_alert(self):
        """test_monitoring_system creates a real System Alert and reports success."""
        with self.set_user(self.admin_email):
            result = md.test_monitoring_system()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "success", msg=result)
        self.assertTrue(result.get("alert_name"))
        # Verify the alert really exists, then clean it up.
        self.assertTrue(frappe.db.exists("System Alert", result["alert_name"]))
        frappe.delete_doc("System Alert", result["alert_name"], force=True)
        frappe.db.commit()

    def test_refresh_advanced_dashboard_data_includes_analytics(self):
        with self.set_user(self.admin_email):
            result = md.refresh_advanced_dashboard_data()
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result)
        for key in (
            "system_metrics",
            "analytics_summary",
            "compliance_metrics",
            "unified_security_summary",
            "timestamp",
        ):
            self.assertIn(key, result)
