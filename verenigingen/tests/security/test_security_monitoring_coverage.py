"""
Coverage-focused test suite for verenigingen/utils/security/security_monitoring.py

This complements ``test_api_security_framework.py`` (which already covers the
happy paths of ``record_api_call``, ``record_security_event`` for auth/rate-limit
and ``get_security_dashboard``). Here we target the still-uncovered branches:

  * CSRF / validation / endpoint-probing threat detection
  * performance-anomaly incident creation (LOW threat + auto-resolve enqueue)
  * the threat-classification thresholds (HIGH user vs CRITICAL IP brute force)
  * incident lifecycle: _create_incident, _auto_resolve_incident, resolve_incident
  * the security-score computation and the metrics snapshot (p95, active users)
  * the business-rule anomaly detectors (real DB) and detect_business_rule_anomalies
  * run_business_rule_monitoring + analyze_security_trends background jobs
  * SecurityTester + module-level singletons / setup
  * the @high_security_api whitelist endpoints (admin success + non-admin deny)

Threat-detection tests build a FRESH ``SecurityMonitor()`` rather than the shared
singleton so the sliding-window / incident state is deterministic.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.security_monitoring import (
    MonitoringMetric,
    SecurityMonitor,
    SecurityTester,
    ThreatLevel,
    analyze_security_trends,
    get_security_dashboard,
    get_security_monitor,
    get_security_tester,
    resolve_security_incident,
    run_business_rule_monitoring,
    run_security_tests,
    setup_security_monitoring,
)


class RecordingAuditLogger:
    """A thin collaborator stand-in for the audit logger.

    Creating a HIGH/CRITICAL ``SecurityIncident`` (the behaviour under test in
    this module) intentionally calls ``audit_logger.log_event("suspicious_
    activity", ...)``. The REAL audit logger's alert path recurses unbounded for
    a ``suspicious_activity`` event (audit_logging._check_alert_conditions ->
    _trigger_security_alert -> log_event -> ... ; threshold is count=1/1min) --
    a genuine production bug reported separately. We do NOT want the
    security-monitoring incident tests held hostage by that subsystem bug, and
    the audit-logging *side effect* (not its internals) is what matters here:
    we assert the monitor calls the logger with the right event type/severity.

    This is a collaborator double injected onto the monitor's plain
    ``audit_logger`` attribute -- it is NOT a Frappe auth/permission primitive
    and NOT the function under test, so it is allowed by the test-quality rules.
    """

    def __init__(self):
        self.events = []

    def log_event(self, event_type, severity=None, **kwargs):
        self.events.append({"event_type": event_type, "severity": severity, **kwargs})
        return f"audit_stub_{len(self.events)}"


def _make_isolated_monitor():
    """A fresh SecurityMonitor whose audit logger is the recording double."""
    monitor = SecurityMonitor()
    monitor.audit_logger = RecordingAuditLogger()
    return monitor


# Error-Log titles emitted by the REAL audit subsystem's recursion bug (see
# RecordingAuditLogger). Tests that must exercise the SHARED singleton (the
# whitelist endpoints, the background job) cannot inject the double, so they
# tolerate this known noise in the automatic tearDown Error Log check.
_AUDIT_NOISE_PATTERNS = (
    "Audit System Error",
    "Audit Alert Error",
    "Security Alert Error",
    "Audit logging failed",
    "Alert checking failed",
    "Security alert failed",
    "maximum recursion depth",
)


class TestThreatDetection(VereningingenTestCase):
    """Threat-classification thresholds and incident creation."""

    def setUp(self):
        super().setUp()
        # Fresh, isolated monitor so window/incident counts are deterministic
        # and the audit-logger recursion bug does not perturb the run.
        self.monitor = _make_isolated_monitor()

    # -- authentication ----------------------------------------------------

    def test_auth_failures_below_threshold_create_no_incident(self):
        """9 user auth failures (< threshold of 10) must NOT raise an incident."""
        for _ in range(9):
            self.monitor.record_security_event(
                MonitoringMetric.AUTHENTICATION_FAILURES,
                user="below@example.com",
                endpoint="/api/login",
                ip_address="10.0.0.1",
            )
        self.assertEqual(len(self.monitor.incidents), 0)

    def test_user_auth_threshold_creates_high_credential_attack(self):
        """10 failures for one user -> HIGH credential_attack with correct fields."""
        for _ in range(10):
            self.monitor.record_security_event(
                MonitoringMetric.AUTHENTICATION_FAILURES,
                user="victim@example.com",
                endpoint="/api/login",
                ip_address="10.0.0.2",
            )
        credential = [i for i in self.monitor.incidents if i.incident_type == "credential_attack"]
        self.assertTrue(credential, "expected a credential_attack incident")
        inc = credential[-1]
        self.assertEqual(inc.threat_level, ThreatLevel.HIGH)
        self.assertEqual(inc.user, "victim@example.com")
        self.assertEqual(inc.source_ip, "10.0.0.2")
        self.assertEqual(inc.endpoint, "authentication")
        self.assertGreaterEqual(inc.details["failure_count"], 10)
        # A HIGH incident must be escalated to the audit logger as a
        # "suspicious_activity" event with ERROR severity (CRITICAL would be
        # CRITICAL). Verify the side effect via the recording double.
        suspicious = [e for e in self.monitor.audit_logger.events if e["event_type"] == "suspicious_activity"]
        self.assertTrue(suspicious, "HIGH incident should log a suspicious_activity audit event")
        self.assertEqual(suspicious[-1]["details"]["incident_type"], "credential_attack")

    def test_ip_brute_force_creates_critical_incident(self):
        """20 failures from one IP (threshold*2) -> CRITICAL brute_force_attack.

        Spread across distinct users so the per-user HIGH branch does not fire
        first for any single user, proving the IP branch is independent.
        """
        for n in range(20):
            self.monitor.record_security_event(
                MonitoringMetric.AUTHENTICATION_FAILURES,
                user=f"user{n}@example.com",
                endpoint="/api/login",
                ip_address="10.0.0.99",
            )
        brute = [i for i in self.monitor.incidents if i.incident_type == "brute_force_attack"]
        self.assertTrue(brute, "expected a brute_force_attack incident")
        inc = brute[-1]
        self.assertEqual(inc.threat_level, ThreatLevel.CRITICAL)
        self.assertEqual(inc.source_ip, "10.0.0.99")
        self.assertEqual(inc.user, "multiple_users")

    # -- CSRF --------------------------------------------------------------

    def test_csrf_threshold_creates_high_incident(self):
        """5 CSRF failures for one user -> HIGH csrf_attack."""
        for _ in range(5):
            self.monitor.record_security_event(
                MonitoringMetric.CSRF_FAILURES,
                user="csrf@example.com",
                endpoint="/api/form",
                ip_address="10.0.0.3",
            )
        csrf = [i for i in self.monitor.incidents if i.incident_type == "csrf_attack"]
        self.assertTrue(csrf, "expected a csrf_attack incident")
        self.assertEqual(csrf[-1].threat_level, ThreatLevel.HIGH)
        self.assertEqual(csrf[-1].details["failure_count"], 5)

    def test_csrf_below_threshold_no_incident(self):
        for _ in range(4):
            self.monitor.record_security_event(
                MonitoringMetric.CSRF_FAILURES,
                user="csrf2@example.com",
                endpoint="/api/form",
                ip_address="10.0.0.4",
            )
        self.assertEqual([i for i in self.monitor.incidents if i.incident_type == "csrf_attack"], [])

    # -- validation --------------------------------------------------------

    def test_validation_errors_threshold_creates_input_fuzzing(self):
        """20 validation errors (across endpoints) -> MEDIUM input_fuzzing."""
        for n in range(20):
            self.monitor.record_security_event(
                MonitoringMetric.VALIDATION_ERRORS,
                user="fuzzer@example.com",
                endpoint=f"/api/endpoint/{n}",  # distinct endpoints => no endpoint_probing
                ip_address="10.0.0.5",
            )
        fuzzing = [i for i in self.monitor.incidents if i.incident_type == "input_fuzzing"]
        self.assertTrue(fuzzing, "expected an input_fuzzing incident")
        self.assertEqual(fuzzing[-1].threat_level, ThreatLevel.MEDIUM)
        # source_ip is taken from the first matching validation event
        self.assertEqual(fuzzing[-1].source_ip, "10.0.0.5")

    def test_endpoint_probing_detected_on_single_endpoint(self):
        """>=10 validation errors on ONE endpoint -> MEDIUM endpoint_probing."""
        for _ in range(11):
            self.monitor.record_security_event(
                MonitoringMetric.VALIDATION_ERRORS,
                user="prober@example.com",
                endpoint="/api/target",
                ip_address="10.0.0.6",
            )
        probing = [i for i in self.monitor.incidents if i.incident_type == "endpoint_probing"]
        self.assertTrue(probing, "expected an endpoint_probing incident")
        inc = probing[-1]
        self.assertEqual(inc.threat_level, ThreatLevel.MEDIUM)
        self.assertEqual(inc.endpoint, "/api/target")
        self.assertGreaterEqual(inc.details["error_count"], 10)

    # -- rate limit (extra branch: IP automated attack) --------------------

    def test_rate_limit_ip_automated_attack(self):
        """100 violations from one IP (threshold*2) -> HIGH automated_attack."""
        for n in range(100):
            self.monitor.record_security_event(
                MonitoringMetric.RATE_LIMIT_VIOLATIONS,
                user=f"u{n}@example.com",  # distinct users so per-user branch stays quiet
                endpoint="/api/data",
                ip_address="10.0.0.7",
            )
        automated = [i for i in self.monitor.incidents if i.incident_type == "automated_attack"]
        self.assertTrue(automated, "expected an automated_attack incident")
        self.assertEqual(automated[-1].threat_level, ThreatLevel.HIGH)

    # -- performance anomaly (LOW threat + auto-resolve enqueue) -----------

    def test_performance_anomaly_creates_low_incident(self):
        """A response time >3x the endpoint average creates a LOW perf anomaly.

        Needs >=10 prior samples on the endpoint to establish a baseline.
        ``_create_incident`` for a LOW threat also enqueues an auto-resolve job;
        this exercises that branch without raising.
        """
        endpoint = "/api/slow"
        with self.assertNoErrorLog():
            for _ in range(12):
                self.monitor.record_api_call(
                    endpoint=endpoint, user="u@example.com", response_time=0.1, status="success"
                )
            # 5.0s >> 3 * 0.1s average -> anomaly
            self.monitor.record_api_call(
                endpoint=endpoint, user="u@example.com", response_time=5.0, status="success"
            )
        anomalies = [i for i in self.monitor.incidents if i.incident_type == "performance_anomaly"]
        self.assertTrue(anomalies, "expected a performance_anomaly incident")
        inc = anomalies[-1]
        self.assertEqual(inc.threat_level, ThreatLevel.LOW)
        self.assertEqual(inc.endpoint, endpoint)
        self.assertGreater(inc.details["response_time"], inc.details["average_time"])


class TestIncidentLifecycle(VereningingenTestCase):
    """Direct exercise of the incident bookkeeping helpers."""

    def setUp(self):
        super().setUp()
        self.monitor = _make_isolated_monitor()

    def _make_incident(self, threat=ThreatLevel.MEDIUM):
        self.monitor._create_incident(
            threat,
            "test_incident",
            "synthetic incident",
            "1.2.3.4",
            "tester@example.com",
            "/api/x",
            {"k": "v"},
        )
        return self.monitor.incidents[-1]

    def test_create_incident_registers_active_threat(self):
        inc = self._make_incident()
        self.assertIn(inc.incident_id, self.monitor.active_threats)
        self.assertFalse(inc.resolved)
        self.assertEqual(inc.details, {"k": "v"})

    def test_resolve_incident_marks_resolved_and_removes_active(self):
        inc = self._make_incident()
        self.monitor.resolve_incident(inc.incident_id, "handled by ops")
        self.assertTrue(inc.resolved)
        self.assertEqual(inc.resolution_notes, "handled by ops")
        self.assertNotIn(inc.incident_id, self.monitor.active_threats)

    def test_resolve_unknown_incident_is_noop(self):
        # Unknown id must not raise and must not invent an active threat.
        self.monitor.resolve_incident("DOES_NOT_EXIST", "noop")
        self.assertNotIn("DOES_NOT_EXIST", self.monitor.active_threats)

    def test_auto_resolve_incident(self):
        inc = self._make_incident(ThreatLevel.LOW)
        self.monitor._auto_resolve_incident(inc.incident_id)
        self.assertTrue(inc.resolved)
        self.assertEqual(inc.resolution_notes, "Auto-resolved (low severity)")
        self.assertNotIn(inc.incident_id, self.monitor.active_threats)

    def test_auto_resolve_incident_signature_has_no_delay_kwarg(self):
        """Regression for the enqueue bug: _create_incident used to call
        frappe.enqueue(self._auto_resolve_incident, incident_id=..., delay=300),
        but frappe.enqueue has no `delay` param, so `delay` was forwarded to
        _auto_resolve_incident, which raised TypeError in the worker on EVERY
        LOW incident. _auto_resolve_incident must accept only incident_id, so a
        forwarded `delay` would still break it — pin the signature."""
        import inspect

        params = list(inspect.signature(self.monitor._auto_resolve_incident).parameters)
        self.assertEqual(params, ["incident_id"], "extra params would re-break the enqueue call")


class TestSecurityScoreAndMetrics(VereningingenTestCase):
    """_calculate_security_score and _update_metrics_snapshot branches."""

    def setUp(self):
        super().setUp()
        self.monitor = _make_isolated_monitor()

    def test_perfect_score_with_no_events(self):
        self.assertEqual(self.monitor._calculate_security_score(0, 0, 0, 0), 100.0)

    def test_score_deductions_are_capped(self):
        """Each category caps its deduction; the score never goes below 0."""
        # auth cap 20, rate cap 15, csrf cap 25, validation cap 10 => max 70 off
        score = self.monitor._calculate_security_score(1000, 1000, 1000, 1000)
        self.assertEqual(score, 30.0)

    def test_csrf_weighted_more_than_auth(self):
        """One CSRF failure (-3) deducts more than one auth failure (-2)."""
        csrf_score = self.monitor._calculate_security_score(0, 0, 1, 0)
        auth_score = self.monitor._calculate_security_score(1, 0, 0, 0)
        self.assertLess(csrf_score, auth_score)

    def test_active_critical_incident_lowers_score(self):
        """An active CRITICAL incident deducts 15 points from the base score."""
        baseline = self.monitor._calculate_security_score(0, 0, 0, 0)
        self.monitor._create_incident(ThreatLevel.CRITICAL, "t", "d", "ip", "u", "e", {})
        with_incident = self.monitor._calculate_security_score(0, 0, 0, 0)
        self.assertEqual(baseline - with_incident, 15.0)

    def test_metrics_snapshot_records_active_users_and_p95(self):
        """A snapshot computes the average/p95 response time and active-user count."""
        for i in range(10):
            self.monitor.record_api_call(
                endpoint="/api/m", user="m@example.com", response_time=float(i), status="ok"
            )
        snap = self.monitor.metrics_history[-1]
        self.assertEqual(snap.api_calls_total, 10)
        self.assertGreater(snap.response_time_avg, 0)
        self.assertGreaterEqual(snap.response_time_p95, snap.response_time_avg)
        # responses over 5.0s are counted as "failed"
        self.assertEqual(snap.api_calls_failed, len([i for i in range(10) if float(i) > 5.0]))


class TestSecurityDashboard(VereningingenTestCase):
    """Dashboard serialisation including active incidents + threat summary counts."""

    def setUp(self):
        super().setUp()
        self.monitor = _make_isolated_monitor()

    def test_dashboard_counts_threats_by_level(self):
        self.monitor._create_incident(ThreatLevel.CRITICAL, "a", "d", "ip", "u", "e", {})
        self.monitor._create_incident(ThreatLevel.HIGH, "b", "d", "ip", "u", "e", {})
        self.monitor._create_incident(ThreatLevel.MEDIUM, "c", "d", "ip", "u", "e", {})
        dash = self.monitor.get_security_dashboard()
        summary = dash["threat_summary"]
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["high"], 1)
        self.assertEqual(summary["medium"], 1)
        self.assertEqual(summary["low"], 0)
        # active_incidents are dataclass-serialised dicts
        self.assertEqual(len(dash["active_incidents"]), 3)
        self.assertIn("incident_id", dash["active_incidents"][0])

    def test_dashboard_empty_when_no_metrics(self):
        dash = self.monitor.get_security_dashboard()
        self.assertIsNone(dash["current_metrics"])
        self.assertEqual(dash["recent_incidents"], [])


class TestBusinessRuleMonitoring(VereningingenTestCase):
    """The DB-backed business-rule anomaly detectors run against the real schema."""

    def setUp(self):
        super().setUp()
        self.monitor = SecurityMonitor()

    def test_check_high_value_payments_returns_alert_shape(self):
        """With a very low threshold any recent Payment Entry surfaces; the alert
        shape and severity must be correct regardless of how many exist."""
        alerts = self.monitor.check_high_value_payments(threshold=0.01)
        for a in alerts:
            self.assertEqual(a["type"], "HIGH_VALUE_PAYMENT")
            self.assertEqual(a["severity"], "CRITICAL")
            self.assertIn("payment_name", a)
            self.assertIn("amount", a)

    def test_check_high_value_payments_high_threshold_empty(self):
        """An astronomically high threshold yields no alerts (query/filter works)."""
        alerts = self.monitor.check_high_value_payments(threshold=10**12)
        self.assertEqual(alerts, [])

    def test_check_unusual_member_operations_runs(self):
        alerts = self.monitor.check_unusual_member_operations()
        self.assertIsInstance(alerts, list)
        for a in alerts:
            self.assertEqual(a["type"], "BULK_MEMBER_UPDATE")
            self.assertEqual(a["severity"], "HIGH")

    def test_check_financial_pattern_anomalies_runs(self):
        alerts = self.monitor.check_financial_pattern_anomalies()
        self.assertIsInstance(alerts, list)
        for a in alerts:
            self.assertIn(a["type"], {"ROUND_AMOUNT_PATTERN", "HIGH_DISCOUNT_PATTERN"})

    def test_monitor_policy_changes_runs(self):
        alerts = self.monitor.monitor_policy_changes()
        self.assertIsInstance(alerts, list)
        for a in alerts:
            self.assertEqual(a["type"], "POLICY_CHANGE")
            self.assertEqual(a["severity"], "CRITICAL")
            self.assertIn("rule_name", a)

    def test_check_sepa_operation_anomalies_runs(self):
        alerts = self.monitor.check_sepa_operation_anomalies()
        self.assertIsInstance(alerts, list)
        for a in alerts:
            self.assertEqual(a["type"], "RAPID_SEPA_CREATION")
            self.assertEqual(a["severity"], "HIGH")

    def test_detect_business_rule_anomalies_aggregates_all(self):
        """The aggregate detector combines all five detectors without raising."""
        with self.assertNoErrorLog():
            alerts = self.monitor.detect_business_rule_anomalies()
        self.assertIsInstance(alerts, list)
        # Each member detector returns alerts of its own known types.
        known_types = {
            "HIGH_VALUE_PAYMENT",
            "BULK_MEMBER_UPDATE",
            "ROUND_AMOUNT_PATTERN",
            "HIGH_DISCOUNT_PATTERN",
            "POLICY_CHANGE",
            "RAPID_SEPA_CREATION",
        }
        for a in alerts:
            self.assertIn(a["type"], known_types)


class TestBackgroundJobs(VereningingenTestCase):
    """run_business_rule_monitoring + analyze_security_trends."""

    def test_run_business_rule_monitoring_handles_missing_security_alert_doctype(self):
        """``Security Alert`` doctype is NOT shipped on this site. The job swallows
        the resulting insert failure and logs an error rather than crashing.

        This characterises the known dead alert-persistence path: if any alert is
        produced, the insert into the nonexistent doctype fails and is logged.
        """
        if frappe.db.exists("DocType", "Security Alert"):
            self.skipTest("Security Alert doctype exists; dead-path assumption invalid")

        monitor = get_security_monitor()
        alerts = monitor.detect_business_rule_anomalies()

        if alerts:
            # An alert exists -> the per-alert insert into the missing "Security
            # Alert" doctype fails and is logged (a known dead persistence path).
            # Tolerate those rows in the automatic tearDown Error Log check.
            self.expectErrorLog("Business rule monitoring", "Security Alert", "DoesNotExistError")
            # Must not raise: the job wraps each insert in try/except.
            run_business_rule_monitoring()
        else:
            # No alerts on this clean site -> no error should be logged.
            with self.assertNoErrorLog():
                run_business_rule_monitoring()

    def test_analyze_security_trends_returns_summary(self):
        with self.assertNoErrorLog():
            result = analyze_security_trends(days=7)
        self.assertNotIn("error", result)
        self.assertIn("api_activity_trends", result)
        self.assertIn("financial_operation_trends", result)
        self.assertIn("security_rules_status", result)
        summary = result["summary"]
        self.assertEqual(summary["total_days_analyzed"], 7)
        self.assertIn("active_security_rules", summary)
        self.assertIn("total_security_rules", summary)

    def test_analyze_security_trends_period_string(self):
        result = analyze_security_trends(days=1)
        self.assertIn("analysis_period", result)
        self.assertIn(" to ", result["analysis_period"])


class TestSecurityTester(VereningingenTestCase):
    """SecurityTester aggregation + the module-level singleton/setup helpers."""

    def test_run_security_tests_aggregates_categories(self):
        tester = SecurityTester()
        # Regression: run_security_tests() used to log the audit event with the
        # invalid type "security_tests_executed", which the API Audit Log Select
        # rejected -> the audit record was silently dropped and an Error Log
        # written. With the fix ("other") no Error Log is produced.
        with self.assertNoErrorLog():
            results = tester.run_security_tests()
        self.assertEqual(results["tests_passed"] + results["tests_failed"], 5)
        # All built-in test stubs return passed=True today -> 100.0 score.
        self.assertEqual(results["tests_passed"], 5)
        self.assertEqual(results["overall_score"], 100.0)
        categories = {d["category"] for d in results["test_details"]}
        self.assertEqual(
            categories,
            {
                "Authentication Security",
                "CSRF Protection",
                "Input Validation",
                "Rate Limiting",
                "Audit Logging",
            },
        )

    def test_get_security_tester_is_singleton(self):
        self.assertIs(get_security_tester(), get_security_tester())

    def test_get_security_monitor_is_singleton(self):
        self.assertIs(get_security_monitor(), get_security_monitor())

    def test_setup_security_monitoring_reinitialises_singletons(self):
        """setup_security_monitoring rebuilds both globals and logs an init event."""
        with self.assertNoErrorLog():
            setup_security_monitoring()
        monitor = get_security_monitor()
        self.assertIn("auth_failures_per_minute", monitor.thresholds)
        self.assertEqual(monitor.sliding_windows["auth_failures"].maxlen, 100)


class TestWhitelistEndpoints(VereningingenTestCase):
    """The @high_security_api endpoints: admin success + non-admin deny."""

    def setUp(self):
        super().setUp()
        # Resolving an incident / accumulated suspicious_activity audit events can
        # trip the audit-logger recursion noise (see _AUDIT_NOISE_PATTERNS above).
        self.expectErrorLog(*_AUDIT_NOISE_PATTERNS)

    def test_get_security_dashboard_endpoint_as_admin(self):
        # Default test user is Administrator (has System Manager).
        result = get_security_dashboard()
        self.assertTrue(result["success"])
        self.assertIn("dashboard", result)
        self.assertIn("threat_summary", result["dashboard"])

    def test_run_security_tests_endpoint_as_admin(self):
        result = run_security_tests()
        self.assertTrue(result["success"])
        self.assertEqual(result["results"]["tests_passed"], 5)

    def test_resolve_security_incident_endpoint_as_admin(self):
        # Seed a real incident on the shared monitor, then resolve it via the API.
        # Swap in the recording double for the HIGH-incident audit call so the
        # real audit logger's recursion bug does not flood the run; restore after.
        monitor = get_security_monitor()
        original_logger = monitor.audit_logger
        monitor.audit_logger = RecordingAuditLogger()
        try:
            monitor._create_incident(ThreatLevel.HIGH, "api_test", "d", "ip", "u", "e", {})
            incident_id = monitor.incidents[-1].incident_id
            result = resolve_security_incident(incident_id, "resolved via api")
        finally:
            monitor.audit_logger = original_logger
        self.assertTrue(result["success"])
        self.assertNotIn(incident_id, monitor.active_threats)

    def test_dashboard_endpoint_denied_for_non_admin(self):
        """A user WITHOUT System Manager must be refused by the endpoint guard.

        We create a real low-privilege user and exercise the endpoint as them.
        The @high_security_api decorator may reject earlier (auth/role profile);
        either way the privileged dashboard data must NOT be returned.
        """
        user = self._make_plain_user()
        with self.as_user(user):
            with self.assertRaises(Exception):
                get_security_dashboard()

    def _make_plain_user(self):
        """Create a minimal enabled User with no admin roles."""
        email = "monitoring-plain-user@example.com"
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True, ignore_permissions=True)
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Plain",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user.name
