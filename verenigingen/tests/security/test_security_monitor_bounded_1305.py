"""#1305: SecurityMonitor.incidents / active_threats must not grow without bound.

#962 made the READ side windowed; the underlying storage still grew by one entry
per incident for the life of a worker. These tests lower the (instance-level)
caps so growth past them is cheap to produce, and pin that in-window behaviour
readers depend on is unchanged.
"""

from datetime import timedelta

from freezegun import freeze_time
from frappe.utils import get_datetime

from verenigingen.tests.security.security_monitor_test_helpers import (
    make_isolated_security_monitor as _make_isolated_monitor,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.security_monitoring import SecurityMonitor, ThreatLevel


def _1305_fill(monitor, count, level=ThreatLevel.HIGH):
    for n in range(count):
        monitor._create_incident(level, f"t{n}", "d", "ip", "u", "e", {})


class TestSecurityMonitorBounded1305(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.monitor = _make_isolated_monitor()
        self.monitor.MAX_INCIDENTS = 5
        self.monitor.MAX_ACTIVE_THREATS = 5

    def test_incidents_history_is_capped_keeping_the_newest(self):
        _1305_fill(self.monitor, 8)
        self.assertEqual(len(self.monitor.incidents), 5)
        self.assertEqual([i.incident_type for i in self.monitor.incidents], ["t3", "t4", "t5", "t6", "t7"])

    def test_active_threats_is_capped_evicting_the_oldest(self):
        _1305_fill(self.monitor, 8)
        self.assertEqual(len(self.monitor.active_threats), 5)
        kept = sorted(i.incident_type for i in self.monitor.active_threats.values())
        self.assertEqual(kept, ["t3", "t4", "t5", "t6", "t7"])

    def test_incident_ids_stay_unique_once_history_is_capped(self):
        """The id used len(self.incidents); a capped list stops growing, so ids
        within one second would collide and overwrite each other in active_threats."""
        with freeze_time("2026-01-01 12:00:00"):
            _1305_fill(self.monitor, 12)
        ids = [i.incident_id for i in self.monitor.incidents]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(len(self.monitor.active_threats), 5)

    def test_default_caps_are_generous(self):
        """Guard against someone 'fixing' memory by capping at a trivial size."""
        self.assertGreaterEqual(SecurityMonitor.MAX_INCIDENTS, 1000)
        self.assertGreaterEqual(SecurityMonitor.MAX_ACTIVE_THREATS, 1000)

    def test_in_window_incidents_under_the_cap_are_all_reported(self):
        """Control: below the cap nothing is dropped; dashboard + score see all."""
        _1305_fill(self.monitor, 4)
        dash = self.monitor.get_security_dashboard()
        self.assertEqual(len(dash["active_incidents"]), 4)
        self.assertEqual(dash["threat_summary"]["high"], 4)
        self.assertEqual(len(dash["recent_incidents"]), 4)
        self.assertEqual(100.0 - self.monitor._calculate_security_score(0, 0, 0, 0), 4 * 10.0)

    def test_resolve_incident_still_works_on_a_retained_incident(self):
        _1305_fill(self.monitor, 8)
        retained = self.monitor.incidents[-1]
        self.assertIn(retained.incident_id, self.monitor.active_threats)
        self.monitor.resolve_incident(retained.incident_id, "handled")
        self.assertTrue(retained.resolved)
        self.assertNotIn(retained.incident_id, self.monitor.active_threats)

    def test_dashboard_recent_incidents_is_the_last_ten(self):
        self.monitor.MAX_INCIDENTS = 50
        self.monitor.MAX_ACTIVE_THREATS = 50
        _1305_fill(self.monitor, 12)
        dash = self.monitor.get_security_dashboard()
        self.assertEqual([i["incident_type"] for i in dash["recent_incidents"]], [f"t{n}" for n in range(2, 12)])

    def test_medium_flood_cannot_evict_critical_or_high(self):
        self.monitor._create_incident(ThreatLevel.CRITICAL, "crit", "d", "ip", "u", "e", {})
        self.monitor._create_incident(ThreatLevel.HIGH, "high", "d", "ip", "u", "e", {})
        critical = self.monitor.incidents[0]
        _1305_fill(self.monitor, 20, ThreatLevel.MEDIUM)

        self.assertEqual(len(self.monitor.active_threats), 5)
        dash = self.monitor.get_security_dashboard()
        self.assertEqual(dash["threat_summary"]["critical"], 1)
        self.assertEqual(dash["threat_summary"]["high"], 1)
        self.assertEqual(100.0 - self.monitor._calculate_security_score(0, 0, 0, 0), 15.0 + 10.0)
        self.monitor.resolve_incident(critical.incident_id, "handled")
        self.assertTrue(critical.resolved)

    def test_flood_evicts_the_oldest_mediums_first(self):
        """Control: within a tier eviction is still oldest-first (3 survive of 8)."""
        self.monitor._create_incident(ThreatLevel.HIGH, "high", "d", "ip", "u", "e", {})
        _1305_fill(self.monitor, 8, ThreatLevel.MEDIUM)
        kept = sorted(i.incident_type for i in self.monitor.active_threats.values())
        self.assertEqual(kept, ["high", "t4", "t5", "t6", "t7"])

    def test_out_of_window_entry_is_evicted_before_an_in_window_low(self):
        _1305_fill(self.monitor, 1, ThreatLevel.HIGH)  # old, will be aged
        aged = self.monitor.incidents[0]
        aged.timestamp = get_datetime() - timedelta(hours=self.monitor.ACTIVE_INCIDENT_WINDOW_HOURS, minutes=1)
        self.monitor.MAX_ACTIVE_THREATS = 5
        for n in range(3):
            self.monitor._create_incident(ThreatLevel.MEDIUM, f"m{n}", "d", "ip", "u", "e", {})
        # LOW would normally be evicted before a HIGH/MEDIUM; the aged HIGH goes first.
        self.monitor.active_threats["low_in_window"] = type(aged)(
            incident_id="low_in_window",
            timestamp=get_datetime(),
            threat_level=ThreatLevel.LOW,
            incident_type="low",
            description="d",
            source_ip="ip",
            user="u",
            endpoint="e",
            details={},
        )
        self.monitor._create_incident(ThreatLevel.MEDIUM, "trigger", "d", "ip", "u", "e", {})
        self.assertNotIn(aged.incident_id, self.monitor.active_threats)
        self.assertIn("low_in_window", self.monitor.active_threats)
