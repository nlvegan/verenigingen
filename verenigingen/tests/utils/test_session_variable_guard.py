# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#1353: a MariaDB session variable set (and never restored) inside one test
CLASS must not leak into the next class sharing the same process/connection.

Established by #1350 / PR #1351: a CI shard runs every test module in ONE
process on ONE DB connection, and the harness's one automatic cleanup
(``frappe.db.rollback()``) never touches session-scoped ``SET SESSION ...``
state -- only the transaction. ``frappe.desk.notifications.get_open_count()``
ran ``SET SESSION max_statement_time = 1`` and never put it back; 81 modules
later, in the same shard, a deliberate 2-second lock-wait probe was killed by
the inherited 1-second statement ceiling instead of by the lock it was testing.
PR #1351 fixed that ONE call site with a local ``addCleanup``. This module
tests the harness-level backstop #1353 asked for instead: ``EnhancedTestCase``
and ``VereningingenTestCase`` must put every tracked session variable back to
its pre-harness value at the end of each test CLASS, regardless of who set it
or why, and regardless of whether that class cleans up after itself.

Drives two real test classes through ``unittest`` in ONE process (mirroring a
CI shard), because the defect this reproduces is specifically about ordering
ACROSS classes sharing a connection -- a test that called the guard module's
internal restore function directly would prove that function works and
nothing about whether the harness actually calls it between classes.

``lock_wait_timeout`` is used as the leaked variable, not ``max_statement_time``
(the one #1350 actually hit and PR #1351 already covers with its own
``addCleanup``): this proves the general harness mechanism #1353 asks for, for
a variable the issue itself lists as "not established" whether it leaks too.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils import session_variable_guard
from verenigingen.tests.utils.base import VereningingenTestCase

LEAK_VALUE = "97531"  # a lock_wait_timeout no real site would already have


def _current_lock_wait_timeout() -> str:
    return str(frappe.db.sql("SELECT @@session.lock_wait_timeout")[0][0])


def _run_classes_in_one_process(*test_classes):
    """Run each class's own suite in turn, sharing one ``TestResult`` -- exactly
    what a CI shard does running successive test classes in one process."""
    result = unittest.TestResult()
    for test_class in test_classes:
        unittest.TestLoader().loadTestsFromTestCase(test_class).run(result)
    return result


class TestSessionVariableGuard(unittest.TestCase):
    """Not itself an EnhancedTestCase/VereningingenTestCase: it has to observe
    the REAL session state across two independently-run harness classes, not
    run from inside one of them."""

    def setUp(self):
        self.original = _current_lock_wait_timeout()
        self.addCleanup(self._restore_original)

    def _restore_original(self):
        frappe.db.sql(f"SET SESSION lock_wait_timeout = {self.original}")

    def _assert_leak_is_contained(self, harness_base):
        seen = {}

        class _Leaky(harness_base):
            def test_leaks_a_session_variable(self):
                frappe.db.sql(f"SET SESSION lock_wait_timeout = {LEAK_VALUE}")
                # Deliberately no cleanup here -- this is the exact shape #1350
                # hit: a SET SESSION with no restore anywhere in the call.

        class _Observer(harness_base):
            def test_observes_the_session_after_the_leaky_class(self):
                seen["value"] = _current_lock_wait_timeout()

        result = _run_classes_in_one_process(_Leaky, _Observer)

        self.assertEqual(
            (result.errors, result.failures),
            ([], []),
            f"harness class setup/teardown itself failed: {result.errors or result.failures}",
        )
        self.assertIn(
            "value",
            seen,
            "the observer test never ran -- cannot assert what it saw",
        )
        self.assertEqual(
            seen["value"],
            self.original,
            f"{harness_base.__name__} leaked lock_wait_timeout={LEAK_VALUE} from an earlier "
            "class into this one instead of restoring the harness baseline",
        )

    def test_enhanced_test_case_resets_session_variables_between_classes(self):
        self._assert_leak_is_contained(EnhancedTestCase)

    def test_vereningingen_test_case_resets_session_variables_between_classes(self):
        self._assert_leak_is_contained(VereningingenTestCase)


class TestSessionVariableGuardSurvivesAPreexistingLeak(unittest.TestCase):
    """A leak that happens BEFORE the very first harness class ever runs in a
    process must not get folded into the guard's cached state and then
    actively RE-APPLIED by every later harness class.

    This app also has ~421 plain ``FrappeTestCase``-only classes, and other
    non-``EnhancedTestCase``/``VereningingenTestCase`` classes, that register
    no guard at all. An earlier revision of the guard module snapshotted the
    tracked variables' VALUES the first time any harness class asked for them
    -- so if one of those non-harness classes ran first in a shard and leaked
    a tracked variable, the "baseline" the guard cached was already the leaked
    value, and every later harness class then dutifully restored EVERYONE
    back to it. Measured against that revision (commit 35d9dc7ad): a plain
    ``unittest.TestCase`` set ``lock_wait_timeout = 97531`` and left it; the
    first ``EnhancedTestCase`` afterward saw 97531 (expected -- nothing has
    run yet to fix it), and a SECOND ``EnhancedTestCase`` still saw 97531
    after the first one's own cleanup ran -- the restore was defending the
    leak instead of undoing it.
    """

    def setUp(self):
        self.original = _current_lock_wait_timeout()
        self.addCleanup(self._restore_original)
        self._blank_guard_module_caches()

    def _restore_original(self):
        frappe.db.sql(f"SET SESSION lock_wait_timeout = {self.original}")

    def _blank_guard_module_caches(self):
        """Simulate this being the very first call in a fresh process: blank
        every private lazily-populated cache the guard module holds (matched
        by a `_..._cache` name, not a hardcoded attribute name, so this test
        does not care which internal caching scheme the module uses). Without
        this, whatever this test PROCESS already computed earlier -- from a
        clean session, before this test's leak -- would mask the defect this
        test exists to catch.
        """
        for name in list(vars(session_variable_guard)):
            if name.startswith("_") and name.endswith("_cache"):
                setattr(session_variable_guard, name, None)

    def test_a_leak_before_the_first_harness_class_does_not_survive_as_the_restored_value(self):
        class _NonHarnessLeak(unittest.TestCase):
            """A plain unittest.TestCase -- like one of this app's ~421
            FrappeTestCase-only (or otherwise non-EnhancedTestCase /
            non-VereningingenTestCase) classes -- that leaks a tracked
            session variable and registers no guard for it at all."""

            def test_leaks_before_any_harness_class_runs(self):
                frappe.db.sql(f"SET SESSION lock_wait_timeout = {LEAK_VALUE}")

        seen = {}

        class _FirstHarnessClass(EnhancedTestCase):
            def test_observes_state_right_after_the_leak(self):
                seen["first"] = _current_lock_wait_timeout()

        class _SecondHarnessClass(EnhancedTestCase):
            def test_observes_state_after_the_first_harness_classs_cleanup(self):
                seen["second"] = _current_lock_wait_timeout()

        result = _run_classes_in_one_process(_NonHarnessLeak, _FirstHarnessClass, _SecondHarnessClass)

        self.assertEqual(
            (result.errors, result.failures),
            ([], []),
            f"harness class setup/teardown itself failed: {result.errors or result.failures}",
        )
        self.assertEqual(
            seen.get("first"),
            LEAK_VALUE,
            "test setup did not actually leak the session variable before the first harness class",
        )
        self.assertEqual(
            seen.get("second"),
            self.original,
            "a SECOND harness class still observed the value a NON-harness class leaked before "
            "the first harness class ever ran, instead of the server's true default -- the "
            "restore is defending the leak it should be undoing",
        )
