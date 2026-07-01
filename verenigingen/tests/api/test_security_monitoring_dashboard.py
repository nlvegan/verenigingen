"""
Integration tests for verenigingen/api/security_monitoring_dashboard.py

These tests exercise the real security monitoring dashboard endpoints against
real ``SEPA Audit Log`` records (no mocking of the functions under test or of
frappe.db / frappe.get_doc). They verify:

- the nested OperationResult response shape produced by the @*_api decorators
- that seeded audit-log records are aggregated into the dashboard output
- the compliance_status -> severity/success mapping in recent events
- the security-summary counting + security-score maths
- the framework-health self-check

Notable production observation (see module report): the dashboard's
rate-limit / authentication-failure filters query for ``process_type`` values
("rate_limit_exceeded", "unauthorized_access_attempt", "authentication_failed")
that are NOT valid options of the SEPA Audit Log ``process_type`` Select field
(options: Mandate Creation / Batch Generation / Bank Submission / Payment
Processing). Those filters can therefore never match a real row, so those
sections are effectively always empty. The tests below document this behaviour
rather than assert a (currently impossible) non-empty result.
"""

import frappe
from frappe.utils import now_datetime

from verenigingen.api.security_monitoring_dashboard import (
    _calculate_security_score,
    _get_framework_health_status,
    _get_recent_security_events,
    _get_security_summary,
    get_security_dashboard_data,
    get_security_metrics_summary,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSecurityMonitoringDashboard(VereningingenTestCase):
    """Real-integration coverage for the security monitoring dashboard API."""

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #
    def _make_audit_log(self, process_type, compliance_status, action, details=None):
        """Create and track a real SEPA Audit Log row.

        ``process_type`` and ``compliance_status`` must be valid Select options.
        """
        event_id = f"TEST-SEC-{frappe.generate_hash(length=12)}"
        doc = frappe.get_doc(
            {
                "doctype": "SEPA Audit Log",
                "event_id": event_id,
                "timestamp": now_datetime(),
                "process_type": process_type,
                "action": action,
                "compliance_status": compliance_status,
                "user": frappe.session.user,
                "details": frappe.as_json(details) if details is not None else None,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("SEPA Audit Log", doc.name)
        return doc

    # ------------------------------------------------------------------ #
    # Response-shape tests (whitelisted wrappers)                         #
    # ------------------------------------------------------------------ #
    def test_dashboard_returns_nested_operation_result(self):
        """The decorated endpoint returns the nested OperationResult dict."""
        result = get_security_dashboard_data(24)

        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("timestamp", result)
        self.assertIn("data", result)
        # Payload is nested one level deeper (OperationResult.ok wraps a dict
        # that itself has a "data" key).
        payload = result["data"]
        self.assertIn("data", payload)
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["time_range_hours"], 24)

    def test_dashboard_inner_sections_present(self):
        """All seven dashboard sections are produced."""
        payload = get_security_dashboard_data(24)["data"]["data"]

        for section in (
            "summary",
            "recent_events",
            "rate_limit_violations",
            "authentication_failures",
            "api_usage_stats",
            "security_alerts",
            "framework_health",
        ):
            self.assertIn(section, payload)

    def test_hours_back_capped_at_one_week(self):
        """hours_back is capped to 168 (one week)."""
        payload = get_security_dashboard_data(1000)["data"]
        self.assertEqual(payload["time_range_hours"], 168)

    def test_hours_back_accepts_string(self):
        """hours_back passed as a string is coerced to int (web call path)."""
        payload = get_security_dashboard_data("48")["data"]
        self.assertEqual(payload["time_range_hours"], 48)

    def test_metrics_summary_shape(self):
        """get_security_metrics_summary returns the flat metrics payload."""
        result = get_security_metrics_summary()

        self.assertTrue(result["success"])
        data = result["data"]
        for key in (
            "security_score",
            "total_events_24h",
            "rate_violations_24h",
            "auth_failures_24h",
            "api_calls_24h",
            "framework_status",
        ):
            self.assertIn(key, data)

    # ------------------------------------------------------------------ #
    # Aggregation tests (seed known data, assert it appears)              #
    # ------------------------------------------------------------------ #
    def test_seeded_event_appears_in_recent_events(self):
        """A freshly created audit log shows up in recent events."""
        marker = f"unit-test-action-{frappe.generate_hash(length=8)}"
        self._make_audit_log("Payment Processing", "Compliant", marker)

        payload = get_security_dashboard_data(24)["data"]["data"]
        actions = [e["description"] for e in payload["recent_events"]]
        self.assertTrue(
            any(marker in desc for desc in actions),
            f"Seeded event '{marker}' not found in recent_events",
        )

    def test_recent_event_severity_and_success_mapping(self):
        """compliance_status maps to the documented severity + success flags."""
        cutoff = now_datetime()
        cases = {
            "Compliant": ("info", True),
            "Exception": ("critical", False),
            "Failed": ("error", False),
            "Pending Review": ("warning", False),
        }
        markers = {}
        for status in cases:
            marker = f"sev-{status.replace(' ', '')}-{frappe.generate_hash(length=6)}"
            markers[marker] = status
            self._make_audit_log("Payment Processing", status, marker)

        events = _get_recent_security_events(cutoff, limit=200)
        by_marker = {}
        for e in events:
            for marker in markers:
                if marker in e["description"]:
                    by_marker[marker] = e

        for marker, status in markers.items():
            self.assertIn(marker, by_marker, f"Missing event for {status}")
            expected_severity, expected_success = cases[status]
            self.assertEqual(by_marker[marker]["severity"], expected_severity)
            self.assertEqual(by_marker[marker]["success"], expected_success)

    def test_recent_event_parses_details_json(self):
        """The details JSON string is parsed back into a dict."""
        cutoff = now_datetime()
        marker = f"details-{frappe.generate_hash(length=8)}"
        self._make_audit_log("Payment Processing", "Compliant", marker, details={"foo": "bar", "n": 42})

        events = _get_recent_security_events(cutoff, limit=200)
        match = next((e for e in events if marker in e["description"]), None)
        self.assertIsNotNone(match, "Seeded event with details not found")
        self.assertEqual(match["details"], {"foo": "bar", "n": 42})

    def test_summary_counts_reflect_seeded_records(self):
        """Summary totals/failed/critical increase exactly by the seeded rows."""
        cutoff = now_datetime()
        before = _get_security_summary(cutoff)

        # 2 compliant, 1 failed, 1 exception (=> 2 failed_operations, 1 critical)
        self._make_audit_log("Payment Processing", "Compliant", "ok-1")
        self._make_audit_log("Payment Processing", "Compliant", "ok-2")
        self._make_audit_log("Payment Processing", "Failed", "bad-1")
        self._make_audit_log("Payment Processing", "Exception", "crit-1")

        after = _get_security_summary(cutoff)

        self.assertEqual(after["total_security_events"] - before["total_security_events"], 4)
        self.assertEqual(after["failed_operations"] - before["failed_operations"], 2)
        self.assertEqual(after["critical_alerts"] - before["critical_alerts"], 1)

    def test_summary_success_rate_bounds(self):
        """success_rate stays within 0..100 with seeded failures present."""
        cutoff = now_datetime()
        self._make_audit_log("Payment Processing", "Failed", "sr-bad")
        self._make_audit_log("Payment Processing", "Compliant", "sr-ok")

        summary = _get_security_summary(cutoff)
        self.assertGreaterEqual(summary["success_rate"], 0)
        self.assertLessEqual(summary["success_rate"], 100)

    # ------------------------------------------------------------------ #
    # Pure-function tests: security score maths                          #
    # ------------------------------------------------------------------ #
    def test_security_score_empty_is_high(self):
        """No events => quiet-period high score."""
        self.assertEqual(_calculate_security_score([]), 95)

    def test_security_score_perfect_when_all_compliant(self):
        """All-compliant events => full score of 100."""
        entries = [{"compliance_status": "Compliant"} for _ in range(5)]
        self.assertEqual(_calculate_security_score(entries), 100)

    def test_security_score_penalises_failures_and_criticals(self):
        """Failures/criticals reduce the score below a clean baseline."""
        clean = [{"compliance_status": "Compliant"} for _ in range(4)]
        dirty = clean + [
            {"compliance_status": "Failed"},
            {"compliance_status": "Exception"},
        ]
        self.assertLess(_calculate_security_score(dirty), _calculate_security_score(clean))
        # Exception counts as both a failure and a critical -> largest deduction.
        self.assertLess(_calculate_security_score(dirty), 100)

    # ------------------------------------------------------------------ #
    # Framework health                                                    #
    # ------------------------------------------------------------------ #
    def test_framework_health_reports_components(self):
        """Health check enumerates the four framework components."""
        health = _get_framework_health_status()

        self.assertIn(health["overall_status"], ("HEALTHY", "DEGRADED", "ERROR"))
        components = health["components"]
        for comp in (
            "api_security_framework",
            "audit_logging",
            "rate_limiting",
            "csrf_protection",
        ):
            self.assertIn(comp, components)

    def test_framework_health_healthy_in_test_env(self):
        """All components import cleanly in the test environment."""
        health = _get_framework_health_status()
        self.assertEqual(health["overall_status"], "HEALTHY")
        for value in health["components"].values():
            self.assertIn("OPERATIONAL", value)

    # ------------------------------------------------------------------ #
    # Documented dead-filter behaviour (process_type mismatch)           #
    # ------------------------------------------------------------------ #
    def test_rate_limit_and_auth_sections_have_stable_shape(self):
        """Rate-limit / auth-failure sections always return their zeroed shape.

        These filter on process_type values that are not valid SEPA Audit Log
        Select options, so they can never match a real row.
        """
        payload = get_security_dashboard_data(24)["data"]["data"]

        rl = payload["rate_limit_violations"]
        for key in ("total_violations", "unique_users", "unique_ips", "recent_violations"):
            self.assertIn(key, rl)

        af = payload["authentication_failures"]
        for key in ("total_failures", "unique_ips", "recent_failures"):
            self.assertIn(key, af)
