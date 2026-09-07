"""Regression for #630: the shared security-monitor singleton must not be a
back door between unrelated test classes.

#620 fixed a CI flake (``AssertionError: 40.0 != 100.0`` in
``test_security_framework_comprehensive.TestSecurityMonitoring.
test_security_score_calculation``) by saving/restoring
``SecurityMonitor.active_threats`` around that ONE class. That immunised the
victim's own assertion but did nothing about the polluter
(``test_api_security_framework.TestSecurityMonitoringThreatDetection``, which
still drove the real ``get_security_monitor()`` singleton past its incident
thresholds), and did nothing about ``incidents``/``sliding_windows``, which the
victim class also writes to the same shared singleton via its own
``test_api_call_recording`` / ``test_security_event_recording``.

These tests prove neither test class touches the process-wide singleton at
all -- pollution removed at the source, rather than the victim immunised
against one specific symptom of it.
"""

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.security_monitoring import get_security_monitor


class TestSecurityMonitorSingletonIsolation(VereningingenTestCase):
    """Run the two `TestSecurityMonitoring`-named classes and assert the real,
    process-wide singleton comes out exactly as it went in."""

    def _snapshot(self, monitor):
        return {
            "incidents": len(monitor.incidents),
            "active_threats": dict(monitor.active_threats),
            "sliding_windows": {k: len(v) for k, v in monitor.sliding_windows.items()},
        }

    def _run_and_assert_untouched(self, test_case_cls):
        import unittest

        shared_monitor = get_security_monitor()
        before = self._snapshot(shared_monitor)

        suite = unittest.TestLoader().loadTestsFromTestCase(test_case_cls)
        result = unittest.TestResult()
        suite.run(result)
        self.assertTrue(
            result.wasSuccessful(),
            f"{test_case_cls.__name__} itself failed: "
            f"failures={result.failures} errors={result.errors}",
        )

        after = self._snapshot(shared_monitor)
        self.assertEqual(
            after,
            before,
            f"{test_case_cls.__name__} mutated the shared get_security_monitor() "
            "singleton -- it must use an isolated monitor instead",
        )

    def test_threat_detection_class_does_not_touch_shared_singleton(self):
        from verenigingen.tests.security.test_api_security_framework import (
            TestSecurityMonitoringThreatDetection,
        )

        self._run_and_assert_untouched(TestSecurityMonitoringThreatDetection)

    def test_comprehensive_monitoring_class_does_not_touch_shared_singleton(self):
        from verenigingen.tests.security.test_security_framework_comprehensive import (
            TestSecurityMonitoring,
        )

        self._run_and_assert_untouched(TestSecurityMonitoring)
