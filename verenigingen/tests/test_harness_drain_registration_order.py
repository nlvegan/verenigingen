"""The cleanup REGISTRATION ORDER in EnhancedTestCase.setUp is pinned on the setUp-failure path (#1522).

`EnhancedTestCase.setUp` registers three cleanups -- `_drain_captured_inserts`,
`_drain_tracked_documents`, `_uninstall_insert_capture` -- in that order, so LIFO runs
uninstall first, then tracked, then captured. `test_harness_drains_survive_setup_failure`
does not pin this: reversing the registrations leaves it green (#1522).

Measured on test_site_4 (2026-11-18): with a submitted Journal Entry or Sales Invoice
posted in a failing setUp, no stranded GL Entry / Payment Ledger Entry rows were observed
under either registration order, so there is no ledger-based assertion here. The order is
pinned structurally instead: each drain override records what ran, and in what position,
from the cleanup stack as it really executed.
"""

import io
import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _RecordsCleanupOrder(EnhancedTestCase):
    """setUp raises after the base class registers its cleanups.

    The overrides are the callables the base `setUp` binds into `addCleanup`, so they sit in the
    real cleanup stack at the real position. No `test_*` methods, for the reason given in
    test_harness_drains_survive_setup_failure.
    """

    drain_log = None

    def _drain_captured_inserts(self):
        self._record("captured")
        super()._drain_captured_inserts()

    def _drain_tracked_documents(self):
        self._record("tracked")
        super()._drain_tracked_documents()

    def _record(self, which):
        # (which drain, was Document.db_insert still patched when it started)
        type(self).drain_log.append((which, getattr(self, "_orig_db_insert", None) is not None))

    def setUp(self):
        type(self).drain_log = []
        super().setUp()
        raise RuntimeError("simulated setUp failure after the cleanups were registered (#1522)")

    def step_one_setup_fails(self):
        self.fail("setUp should have raised before this test body ever runs")


class DrainRegistrationOrderTest(unittest.TestCase):
    def _run_failing_setup(self):
        suite = unittest.TestSuite()
        suite.addTest(_RecordsCleanupOrder("step_one_setup_fails"))
        unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)
        return _RecordsCleanupOrder.drain_log

    def test_capture_is_uninstalled_before_either_drain_runs(self):
        log = self._run_failing_setup()

        self.assertEqual({"captured", "tracked"}, {which for which, _ in log}, f"both drains must run: {log}")
        self.assertEqual(
            [False, False],
            [still_patched for _, still_patched in log],
            "a drain started while Document.db_insert was still patched: _uninstall_insert_capture "
            "must be the FIRST cleanup to run (registered LAST)",
        )

    def test_tracked_drain_runs_before_the_captured_drain(self):
        """`_drain_tracked_documents` defers a blocked Member to the captured drain by reading
        `_captured_inserts` (#1306); if the captured drain ran first it would have emptied that list."""
        log = self._run_failing_setup()

        self.assertEqual(["tracked", "captured"], [which for which, _ in log])
