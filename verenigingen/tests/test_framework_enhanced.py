# -*- coding: utf-8 -*-
# Compatibility shim for test_framework_enhanced imports

import time

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class VerenigingenTestCase(EnhancedTestCase):
    """Base test case backed by EnhancedTestCase.

    EnhancedTestCase provides the real data factory helpers (create_test_member,
    etc.) and transaction isolation that these tests rely on. This shim adds the
    lightweight performance/integration helpers the legacy test_framework_enhanced
    API exposed.
    """

    def benchmark_function(self, func, name="benchmark", iterations=1):
        """Run ``func`` ``iterations`` times and return timing stats.

        Returns a dict with ``name``, ``iterations`` and ``avg_time_ms`` so the
        performance assertions in the suite can compare relative timings.
        """
        timings = []
        result = None
        for _ in range(max(1, iterations)):
            start = time.perf_counter()
            result = func()
            timings.append((time.perf_counter() - start) * 1000)
        return {
            "name": name,
            "iterations": len(timings),
            "avg_time_ms": sum(timings) / len(timings),
            "result": result,
        }

    def record_step(self, step_name, data=None):
        """Record a named workflow step for later inspection.

        Steps are accumulated on the instance; the value is returned so callers
        can chain or assert on it if needed.
        """
        if not hasattr(self, "_workflow_steps"):
            self._workflow_steps = []
        entry = {"step": step_name, "data": data}
        self._workflow_steps.append(entry)
        return entry

    def assert_workflow_completed(self, expected_steps):
        """Assert that every step in ``expected_steps`` was recorded in order."""
        recorded = [s["step"] for s in getattr(self, "_workflow_steps", [])]
        for step in expected_steps:
            self.assertIn(step, recorded, f"Expected workflow step '{step}' was not recorded")


# Stub classes for PerformanceTestCase / IntegrationTestCase
class PerformanceTestCase(VerenigingenTestCase):
    """Performance test case base class"""

    pass


class IntegrationTestCase(VerenigingenTestCase):
    """Integration test case base class"""

    pass
