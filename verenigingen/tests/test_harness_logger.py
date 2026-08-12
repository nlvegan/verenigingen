"""The harness logger must produce output, and the harness must keep using it.

The bug this guards against is not a crash: it is a `.warning()` that goes
nowhere. Under `bench run-tests` a bare `frappe.logger()` sits at ERROR (see
`harness_logger` module docstring for the measurement), so every
"log the failure and continue" in the test harness wrote nothing at all.

So the assertions here are about *observable output*, plus a source guard that
fails if a bare `frappe.logger()` is reintroduced into the harness — the tests
above cannot catch that, because a discarded log looks exactly like no log.
"""

import ast
import io
import logging
import unittest
from pathlib import Path

import frappe

from verenigingen.tests.harness_logger import (
    DEFAULT_LEVEL,
    LOGGER_NAME,
    get_harness_logger,
)

# The harness files whose swallowed setup failures started #291/#309. Others in
# `tests/` log for their own debugging; these log about master data every other
# test depends on.
HARNESS_FILES = (
    "verenigingen/tests/fixtures/enhanced_test_factory.py",
    "verenigingen/tests/setup/__init__.py",
    "verenigingen/tests/utils/__init__.py",
)


class TestHarnessLoggerEmits(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(LOGGER_NAME)
        get_harness_logger()  # ensure configured before we borrow its handler

    def _capture(self, emit):
        """Run `emit` with the harness logger's stream swapped for a buffer."""
        handler = self.logger.handlers[0]
        original = handler.stream
        buffer = io.StringIO()
        handler.setStream(buffer)
        try:
            emit()
        finally:
            handler.setStream(original)
        return buffer.getvalue()

    def test_warning_reaches_the_stream(self):
        output = self._capture(lambda: get_harness_logger().warning("master data missing"))

        self.assertIn("master data missing", output)
        self.assertIn("WARNING", output)

    def test_prefix_identifies_the_caller(self):
        output = self._capture(lambda: get_harness_logger("master-data").warning("role %s absent", "Auditor"))

        self.assertIn("master-data: role Auditor absent", output)

    def test_exc_info_survives_the_prefix_adapter(self):
        def emit():
            try:
                raise ValueError("fixture file unreadable")
            except ValueError:
                get_harness_logger("fixtures").warning("load failed", exc_info=True)

        output = self._capture(emit)

        self.assertIn("fixtures: load failed", output)
        self.assertIn("ValueError: fixture file unreadable", output)

    def test_enabled_for_warning_regardless_of_frappe_log_level(self):
        """The property a bare `frappe.logger()` does not have.

        `frappe.log_level` is None under `bench run-tests`, which is exactly
        when the frappe logger falls back to ERROR. Pin it to None here so the
        assertion is about this logger's own level, not the ambient one.
        """
        original = frappe.log_level
        frappe.log_level = None
        try:
            self.assertTrue(get_harness_logger().isEnabledFor(logging.WARNING))
            self.assertEqual(self.logger.level, DEFAULT_LEVEL)
        finally:
            frappe.log_level = original

    def test_repeated_calls_do_not_stack_handlers(self):
        get_harness_logger()
        get_harness_logger("a")
        get_harness_logger("b")

        self.assertEqual(len(self.logger.handlers), 1)

    def test_does_not_propagate_to_the_root_logger(self):
        """Propagation would mean a second, unformatted copy via lastResort."""
        self.assertFalse(self.logger.propagate)


class TestHarnessUsesTheHarnessLogger(unittest.TestCase):
    """Fail if a bare `frappe.logger()` comes back into the setup harness.

    Matched on the AST rather than by grepping text so a call inside a string
    or comment does not count, and so `frappe.logger("named")` — which has a
    handler of its own and is not the bug — is left alone.
    """

    def test_no_bare_frappe_logger_in_harness_files(self):
        app_root = Path(frappe.get_app_path("verenigingen")).parent

        offenders = []
        for relative in HARNESS_FILES:
            path = app_root / relative
            self.assertTrue(path.exists(), f"{relative} moved; update HARNESS_FILES")
            for line in _bare_frappe_logger_lines(path):
                offenders.append(f"{relative}:{line}")

        self.assertEqual(
            offenders,
            [],
            "These call `frappe.logger()` with no module name, which resolves to level "
            "ERROR under `bench run-tests` and discards the message. Use "
            "`verenigingen.tests.harness_logger.get_harness_logger` instead:\n  "
            + "\n  ".join(offenders),
        )


def _bare_frappe_logger_lines(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.args or node.keywords:
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "logger"
            and isinstance(func.value, ast.Name)
            and func.value.id == "frappe"
        ):
            yield node.lineno
