"""#2621: a source over threshold must not open a new MEDIUM incident per event.

Drives the real entry point (`record_security_event`) so the detectors decide.
Each test builds its own isolated monitor, so no process-wide state leaks.
"""

from freezegun import freeze_time

from verenigingen.tests.security.security_monitor_test_helpers import (
    make_isolated_security_monitor as _make_isolated_monitor,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.security_monitoring import MonitoringMetric, ThreatLevel

RATE = MonitoringMetric.RATE_LIMIT_VIOLATIONS


def _fire(monitor, metric, n, user="flood@example.com", ip="10.0.0.1", endpoint="ep"):
    for _ in range(n):
        monitor.record_security_event(metric, user, endpoint, ip_address=ip)


def _active(monitor, incident_type):
    return [i for i in monitor.active_threats.values() if i.incident_type == incident_type]


class TestSecurityMonitorDedupe2621(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.monitor = _make_isolated_monitor()
        self.threshold = self.monitor.thresholds["rate_limit_violations_per_hour"]

    def test_one_source_over_threshold_yields_one_incident_with_count(self):
        # threshold-1 events fire nothing; the next 7 each cross it.
        _fire(self.monitor, RATE, self.threshold - 1)
        self.assertEqual(self.monitor.incidents, [])
        _fire(self.monitor, RATE, 7)

        found = _active(self.monitor, "rate_limit_abuse")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].occurrence_count, 7)
        self.assertEqual(len(self.monitor.incidents), 1)
        self.assertGreaterEqual(found[0].last_seen, found[0].timestamp)

    def test_fuzzing_and_probing_detectors_dedupe_too(self):
        _fire(self.monitor, MonitoringMetric.VALIDATION_ERRORS, 25, endpoint="ep")
        for kind in ("input_fuzzing", "endpoint_probing"):
            self.assertEqual(len(_active(self.monitor, kind)), 1, kind)
        self.assertEqual(_active(self.monitor, "input_fuzzing")[0].occurrence_count, 6)

    def test_two_sources_yield_two_incidents(self):
        _fire(self.monitor, RATE, self.threshold + 2, user="a@example.com", ip="10.0.0.1")
        _fire(self.monitor, RATE, self.threshold + 2, user="b@example.com", ip="10.0.0.2")
        users = sorted(i.user for i in _active(self.monitor, "rate_limit_abuse"))
        self.assertEqual(users, ["a@example.com", "b@example.com"])

    def test_critical_survives_a_medium_flood_from_another_source(self):
        self.monitor._create_incident(ThreatLevel.CRITICAL, "brute_force_attack", "d", "9.9.9.9", "x", "e", {})
        _fire(self.monitor, RATE, self.threshold + 30)
        summary = self.monitor.get_security_dashboard()["threat_summary"]
        self.assertEqual((summary["critical"], summary["medium"]), (1, 1))
        self.assertEqual(self.monitor._calculate_security_score(0, 0, 0, 0), 85.0)

    def test_medium_never_merges_into_a_high_incident(self):
        # Same user and ip: the HIGH incident is separate from the MEDIUM one.
        _fire(self.monitor, RATE, self.threshold * 2)
        levels = {i.incident_type: i.threat_level for i in self.monitor.active_threats.values()}
        self.assertEqual(levels["rate_limit_abuse"], ThreatLevel.MEDIUM)
        self.assertEqual(levels["automated_attack"], ThreatLevel.HIGH)
        high = _active(self.monitor, "automated_attack")
        self.assertEqual(len(high), 1)
        self.assertEqual(high[0].occurrence_count, 1)

    def test_high_repeats_are_never_merged_and_each_is_audited(self):
        _fire(self.monitor, RATE, self.threshold * 2 + 2)
        high = _active(self.monitor, "automated_attack")
        self.assertEqual(len(high), 3)
        self.assertTrue(all(i.occurrence_count == 1 for i in high))
        audited = [e for e in self.monitor.audit_logger.events if e["details"].get("incident_type") == "automated_attack"]
        self.assertEqual(len(audited), 3)

    def test_resolved_incident_does_not_swallow_a_new_event(self):
        _fire(self.monitor, RATE, self.threshold + 2)
        first = _active(self.monitor, "rate_limit_abuse")[0]
        self.monitor.resolve_incident(first.incident_id, "handled")

        _fire(self.monitor, RATE, 1)
        fresh = _active(self.monitor, "rate_limit_abuse")
        self.assertEqual(len(fresh), 1)
        self.assertNotEqual(fresh[0].incident_id, first.incident_id)
        self.assertEqual(fresh[0].occurrence_count, 1)
        self.assertEqual(first.occurrence_count, 3)  # resolved row not touched afterwards

    def test_incident_outside_the_window_does_not_swallow_a_new_event(self):
        with freeze_time("2026-01-01 00:00:00"):
            _fire(self.monitor, RATE, self.threshold)
        with freeze_time("2026-01-03 00:00:00"):
            self.monitor.sliding_windows["rate_limit_violations"].clear()
            _fire(self.monitor, RATE, self.threshold)
            self.assertEqual(len(self.monitor.incidents), 2)
            self.assertEqual(len(self.monitor.get_security_dashboard()["active_incidents"]), 1)
