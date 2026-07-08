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
from frappe.utils import get_datetime, now_datetime

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
    def test_dashboard_returns_nested_operation_result_with_fresh_timestamps(self):
        """The decorated endpoint's nested timestamps are real, fresh values.

        Strengthened from a pure envelope/shape check: both the outer
        OperationResult ``timestamp`` and the inner payload's ``generated_at``
        must parse as real datetimes taken during this call, not placeholders.
        """
        before = now_datetime()
        result = get_security_dashboard_data(24)
        after = now_datetime()

        self.assertIs(result["success"], True)
        outer_ts = get_datetime(result["timestamp"])
        self.assertTrue(before <= outer_ts <= after, f"Outer timestamp {outer_ts} not in [{before}, {after}]")

        # Payload is nested one level deeper (OperationResult.ok wraps a dict
        # that itself has a "data" key).
        payload = result["data"]
        self.assertEqual(payload["time_range_hours"], 24)
        generated_at = get_datetime(payload["generated_at"])
        self.assertTrue(
            before <= generated_at <= after, f"generated_at {generated_at} not in [{before}, {after}]"
        )

    def test_dashboard_summary_section_reflects_seeded_data(self):
        """The full endpoint's summary section is wired to real audit-log data.

        Strengthened from a pure key-presence check (which stays true even if
        ``dashboard_data["summary"]`` were replaced by a static placeholder):
        this proves ``get_security_dashboard_data`` actually calls through to
        ``_get_security_summary`` by observing the counts move when new rows
        are seeded, exercised end-to-end through the whitelisted endpoint
        (unlike ``test_summary_counts_reflect_seeded_records``, which calls
        the helper directly).
        """
        before_summary = get_security_dashboard_data(24)["data"]["data"]["summary"]

        self._make_audit_log("Payment Processing", "Compliant", "wiring-check-ok")
        self._make_audit_log("Payment Processing", "Failed", "wiring-check-bad")

        payload = get_security_dashboard_data(24)["data"]["data"]
        after_summary = payload["summary"]

        self.assertEqual(after_summary["total_security_events"] - before_summary["total_security_events"], 2)
        self.assertEqual(after_summary["failed_operations"] - before_summary["failed_operations"], 1)

        # All seven sections remain present alongside the now-verified summary.
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

    def test_metrics_summary_reflects_seeded_data(self):
        """get_security_metrics_summary's total_events_24h moves with real data.

        Strengthened from a key-presence check to prove the flat summary
        endpoint is actually wired to ``_get_security_summary`` (not a
        hardcoded shape), by observing the count increase after seeding.
        """
        before = get_security_metrics_summary()["data"]["total_events_24h"]

        self._make_audit_log("Payment Processing", "Compliant", "metrics-wiring-check")

        result = get_security_metrics_summary()
        self.assertTrue(result["success"])
        data = result["data"]

        self.assertEqual(data["total_events_24h"] - before, 1)
        self.assertIsInstance(data["security_score"], (int, float))
        self.assertIn(data["framework_status"], ("HEALTHY", "DEGRADED", "ERROR"))

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

    def test_summary_success_rate_exact_value(self):
        """success_rate is the exact (total-failed)/total*100 computation.

        Strengthened from a ``0 <= x <= 100`` bounds check (true for almost
        any plausible/buggy formula) to an exact expected value: 1 failed out
        of 3 seeded events must yield 66.7, not merely "somewhere in range".
        """
        cutoff = now_datetime()
        self._make_audit_log("Payment Processing", "Failed", "sr-bad")
        self._make_audit_log("Payment Processing", "Compliant", "sr-ok")
        self._make_audit_log("Payment Processing", "Compliant", "sr-ok-2")

        summary = _get_security_summary(cutoff)
        self.assertEqual(summary["total_security_events"], 3)
        self.assertEqual(summary["success_rate"], 66.7)

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
    def test_framework_health_reports_real_cor_count(self):
        """rate_limiting health message reflects the real enabled COR count.

        Strengthened from "the key exists" to an exact value tied to live
        database state: the message must literally embed
        ``frappe.db.count("Critical Operation Rule", {"enabled": 1})``, not a
        hardcoded or stale number.
        """
        expected_count = frappe.db.count("Critical Operation Rule", {"enabled": 1})
        health = _get_framework_health_status()

        self.assertEqual(
            health["components"]["rate_limiting"],
            f"✅ OPERATIONAL (COR-based, {expected_count} rules)",
        )

    def test_framework_health_healthy_in_test_env(self):
        """All non-COR components report the exact operational string.

        Strengthened from a loose ``assertIn("OPERATIONAL", value)``
        substring check (which would still pass if the "✅" marker were
        dropped or the message reworded) to an exact match against the
        documented success string.
        """
        health = _get_framework_health_status()
        self.assertEqual(health["overall_status"], "HEALTHY")
        for comp in ("api_security_framework", "audit_logging", "csrf_protection"):
            self.assertEqual(health["components"][comp], "✅ OPERATIONAL")

    # ------------------------------------------------------------------ #
    # Documented dead-filter behaviour (process_type mismatch)           #
    # ------------------------------------------------------------------ #
    def test_rate_limit_and_auth_filters_never_match_valid_process_types(self):
        """CHARACTERIZATION / KNOWN BUG: these sections are permanently empty.

        ``_get_rate_limit_violations`` / ``_get_authentication_failures``
        filter on ``process_type`` values ("rate_limit_exceeded",
        "unauthorized_access_attempt", "authentication_failed") that are NOT
        valid ``SEPA Audit Log`` ``process_type`` Select options (only
        Mandate Creation / Batch Generation / Bank Submission / Payment
        Processing exist). So even a seeded "Failed" event using a real,
        valid process_type is never counted in either section.

        This test pins that (buggy) behaviour as a tripwire: if someone adds
        those process_type values to the Select options (or fixes the filter
        to key off a real value/field), this test will fail and must be
        updated to assert detection instead of permanent zero counts.
        """
        self._make_audit_log("Payment Processing", "Failed", "auth-tripwire")

        payload = get_security_dashboard_data(24)["data"]["data"]

        self.assertEqual(payload["rate_limit_violations"]["total_violations"], 0)
        self.assertEqual(payload["authentication_failures"]["total_failures"], 0)
