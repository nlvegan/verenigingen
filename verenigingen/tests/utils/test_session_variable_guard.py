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
