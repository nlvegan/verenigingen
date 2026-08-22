"""The harness logger must produce output, and the harness must keep using it.

The bug this guards against is not a crash: it is a `.warning()` that goes
nowhere. Under `bench run-tests` a bare `frappe.logger()` sits at ERROR (see
the `harness_logger` module docstring for the measurement), so every
"log the failure and continue" in the test harness wrote nothing at all.

So the assertions here are about *observable output*, plus a source guard that
fails if a bare `frappe.logger()` is reintroduced into the harness — the
behavioural tests cannot catch that, because a discarded log looks exactly
like no log.

Every test that cares about a level reconfigures the logger under a known
`VERENIGINGEN_TEST_LOG_LEVEL` rather than reading whatever the process was
started with. An earlier version of this file asserted against the ambient
configuration, which made the suite go red under the very env var its own
docstring tells you to set.
"""

import ast
import contextlib
import io
import logging
import os
import sys
import unittest
from pathlib import Path

import frappe

from verenigingen.tests import harness_logger
from verenigingen.tests.harness_logger import (
    DEFAULT_LEVEL,
    LEVEL_ENV_VAR,
    LOGGER_NAME,
    get_harness_logger,
)

# The harness files whose swallowed setup failures started #291/#309. Others in
# `tests/` log for their own debugging; these log about a failure OTHER tests
# depend on -- missing master data, a leaked row, a mutated Single, a guard that
# stopped guarding. That is the entry test: cross-test consequence, not "this
# file happens to be clean". A module whose swallowed failure only makes its own
# assertions vacuous stays off the list; #490 tracks those separately.
#
# Add a file here only once it has ZERO bare `frappe.logger()` calls, or this
# test fails on it immediately.
HARNESS_FILES = (
    "verenigingen/tests/fixtures/enhanced_test_factory.py",
    "verenigingen/tests/setup/__init__.py",
    "verenigingen/tests/utils/__init__.py",
    # A Single restored wrongly carries one test's value into every later test in
    # the shard, and said so nowhere (#433, fixed in #486).
    "verenigingen/tests/fixtures/singleton_backup.py",
    # The guard every test's tearDown runs through. If its capture breaks it stops
    # reporting Error Log rows for the whole suite (#433, fixed in #486).
    "verenigingen/tests/utils/error_log_guard.py",
    # A builder cleanup failure leaves submitted rows behind that redden LATER
    # tests in the same shard -- the #433 leak itself (fixed in #486).
    "verenigingen/tests/backend/unit/controllers/test_member_controller.py",
    # A leaked customer/mandate on the SHARED Mollie test account outlives the
    # run and affects every later run against it (fixed in #486).
    "verenigingen/verenigingen_payments/mollie/tests/test_recurring_charge_live.py",
    # Fixture rows this suite fails to delete stay resident on the site and break
    # later tests, exactly as in #330.
    "verenigingen/tests/payment/test_sepa_race_condition_manager.py",
)


@contextlib.contextmanager
def reconfigured(level_value):
    """Rebuild the harness logger with `VERENIGINGEN_TEST_LOG_LEVEL=level_value`.

    `None` means the variable is unset, i.e. the default path. Reaches for the
    module's private configure flag on purpose: the level is resolved once and
    cached, so there is no public way to ask "what would a fresh process do?".
    """
    original_env = os.environ.get(LEVEL_ENV_VAR)
    logger = logging.getLogger(LOGGER_NAME)
    original_handlers = logger.handlers[:]
    original_level = logger.level

    def apply(value):
        if value is None:
            os.environ.pop(LEVEL_ENV_VAR, None)
        else:
            os.environ[LEVEL_ENV_VAR] = value
        logger.handlers = []
        setattr(logger, harness_logger._CONFIGURED_FLAG, False)
        return get_harness_logger()

    try:
        yield apply(level_value)
    finally:
        apply(original_env)
        logger.handlers = original_handlers
        logger.setLevel(original_level)


@contextlib.contextmanager
def captured_stream(logger):
    """Swap the logger's stream for a buffer, restoring it even on failure."""
    handler = _stream_handler(logger)
    original = handler.stream
    buffer = io.StringIO()
    handler.setStream(buffer)
    try:
        yield buffer
    finally:
        handler.setStream(original)


def _stream_handler(logger) -> logging.StreamHandler:
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            return handler
    raise AssertionError(f"{LOGGER_NAME} has no StreamHandler: {logger.handlers}")


class TestHarnessLoggerEmits(unittest.TestCase):
    """Output, at the default configuration."""

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.logger = stack.enter_context(reconfigured(None))
        self.buffer = stack.enter_context(captured_stream(self.logger))

    def test_warning_reaches_the_stream(self):
        """The whole point: at the DEFAULT level, a warning is written."""
        get_harness_logger().warning("master data missing")

        self.assertIn("master data missing", self.buffer.getvalue())
        self.assertIn("WARNING", self.buffer.getvalue())

    def test_prefix_identifies_the_caller(self):
        get_harness_logger("master-data").warning("role %s absent", "Auditor")

        self.assertIn("master-data: role Auditor absent", self.buffer.getvalue())

    def test_exc_info_survives_the_prefix_adapter(self):
        try:
            raise ValueError("fixture file unreadable")
        except ValueError:
            get_harness_logger("fixtures").warning("load failed", exc_info=True)

        output = self.buffer.getvalue()
        self.assertIn("fixtures: load failed", output)
        self.assertIn("ValueError: fixture file unreadable", output)

    def test_info_is_off_by_default(self):
        """WARNING, not DEBUG: the harness should not narrate a green run."""
        get_harness_logger().info("loaded 12 fixtures")

        self.assertEqual(self.buffer.getvalue(), "")

    def test_writes_to_stderr_not_stdout(self):
        """Reason #2 this module exists. Nothing else pins the sink."""
        with reconfigured(None) as logger:
            self.assertIs(_stream_handler(logger).stream, sys.stderr)

    def test_repeated_calls_do_not_stack_handlers(self):
        get_harness_logger()
        get_harness_logger("a")
        get_harness_logger("b")

        self.assertEqual(len(self.logger.handlers), 1)

    def test_records_do_not_reach_the_root_logger(self):
        """Propagation would mean a second, unformatted copy via lastResort."""
        root_records = []

        class _Collector(logging.Handler):
            def emit(self, record):
                root_records.append(record)

        collector = _Collector()
        logging.getLogger().addHandler(collector)
        self.addCleanup(logging.getLogger().removeHandler, collector)

        get_harness_logger().warning("only once")

        self.assertIn("only once", self.buffer.getvalue())
        self.assertEqual(root_records, [])


class TestHarnessLoggerLevelResolution(unittest.TestCase):
    """`VERENIGINGEN_TEST_LOG_LEVEL` — the module's only branching logic.

    Its docstring promises that an unparseable value must not silently mean
    "log nothing", which is the failure mode the whole module exists to fix.
    Nothing enforced that until these tests.
    """

    def test_env_var_lowers_the_level(self):
        with reconfigured("DEBUG") as logger, captured_stream(logger) as buffer:
            get_harness_logger().debug("drained 3 docs")

            self.assertEqual(logger.level, logging.DEBUG)
            self.assertIn("drained 3 docs", buffer.getvalue())

    def test_env_var_raises_the_level(self):
        with reconfigured("ERROR") as logger, captured_stream(logger) as buffer:
            get_harness_logger().warning("suppressed")

            self.assertEqual(logger.level, logging.ERROR)
            self.assertEqual(buffer.getvalue(), "")

    def test_unparseable_value_falls_back_to_warning(self):
        """Not to ERROR, and not to silence."""
        with reconfigured("chatty") as logger, captured_stream(logger) as buffer:
            get_harness_logger().warning("still audible")

            self.assertEqual(logger.level, DEFAULT_LEVEL)
            self.assertIn("still audible", buffer.getvalue())

    def test_default_is_warning_when_unset(self):
        with reconfigured(None) as logger:
            self.assertEqual(logger.level, DEFAULT_LEVEL)

    def test_level_does_not_depend_on_frappe_log_level(self):
        """`frappe.log_level` is None under `bench run-tests`; that is exactly
        when `frappe.logger()` falls back to ERROR. This logger must not care.
        """
        original = frappe.log_level
        frappe.log_level = None
        try:
            with reconfigured(None) as logger:
                self.assertTrue(logger.isEnabledFor(logging.WARNING))
        finally:
            frappe.log_level = original


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
