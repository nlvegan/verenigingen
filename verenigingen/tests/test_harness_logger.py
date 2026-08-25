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
# The ratchet is PER FILE. Pinning `tests/utils/__init__.py` does not cover its
# siblings, which is why `factories.py` and `cleanup_savepoint.py` are named here
# individually.
#
# Add a file here only once it has ZERO bare `frappe.logger()` calls, or this
# test fails on it immediately. That -- not the criterion above -- is why three files
# this change converted are absent: `test_api_regression` (3 left),
# `test_direct_debit_batch_refactoring` (3) and `test_sepa_xml_compliance` (10, nine of
# them the handlers that make its tests vacuous, #490). They are candidates, not
# exclusions, and an earlier revision of this list wrongly described them as excluded on
# principle.
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
    # Same cleanup shape, and the PRECEDENT this whole change cites -- it already
    # used get_harness_logger while its sibling above did not. Leaving it unpinned
    # would mean the one example nothing protects.
    "verenigingen/tests/payment/test_sepa_reconciliation.py",
    # The cleanup every builder-driven tearDown runs through. Its swallowed failures
    # are OTHER tests' leaked rows by definition, and eight call sites discard the
    # list it returns (#483, #489), so the log is the only record.
    "verenigingen/tests/utils/factories.py",
    # The savepoint helper those cleanups rely on. A failed undo means the attempt was
    # NOT undone while the caller reports only the original error (#499).
    "verenigingen/tests/utils/cleanup_savepoint.py",
    # setUpClass writes and COMMITS a Single. When that write fails, its tests read
    # whatever a previous run committed -- measured on test_site_4, where all four
    # Verenigingen Payments Settings values were resident from an earlier run while
    # this suite's own write was failing. That is a cross-RUN consequence.
    "verenigingen/verenigingen_payments/tests/test_sepa_xml_adapter.py",
    # Sweeps webhook Users. Its refusal to sweep is the only record that rows other
    # suites resolve were left behind.
    "verenigingen/tests/test_webhook_user_setup.py",
    # Builds board memberships other suites resolve by name.
    "verenigingen/tests/backend/comprehensive/test_chapter_assignment_comprehensive.py",
)


@contextlib.contextmanager
def reconfigured(level_value):
    """Rebuild the harness logger with `VERENIGINGEN_TEST_LOG_LEVEL=level_value`.

    `None` means the variable is unset, i.e. the default path. Empties `handlers` on
    purpose: the level is resolved once and cached, so there is no public way to ask
    "what would a fresh process do?", and detaching the handler is what makes
    `_configured_logger` rebuild -- its guard asks whether OUR handler is still
    attached, not whether we ever configured it.
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
        return get_harness_logger()

    try:
        yield apply(level_value)
    finally:
        apply(original_env)
        logger.handlers = original_handlers
        logger.setLevel(original_level)


class HandlerMustFollowStderrTest(unittest.TestCase):
    """The handler must resolve `sys.stderr` when it emits, not when it was built.

    `frappe/testing/result.py` replaces `sys.stderr` with a fresh `io.StringIO` at
    `startTestRun` (`:54-59`) and AGAIN at every `startTest` (`:99-104`), reading each
    buffer back into the report once and then never again. A plain
    `logging.StreamHandler(sys.stderr)` stores the stream OBJECT, so a logger first
    configured inside a test is bound for the rest of the process to that one test's
    buffer -- every later harness record lands somewhere nothing reads, with
    `VERENIGINGEN_TEST_LOG_LEVEL` silently dead. Measured under the real `TestResult`
    before the fix: three warnings from three tests, all three in test 1's buffer, only
    the first surfaced (#514).

    It does not bite today only because `verenigingen/tests/setup/__init__.py:14` and
    `verenigingen/tests/fixtures/enhanced_test_factory.py:204` call
    `get_harness_logger()` at IMPORT time, i.e. before `startTestRun` -- an undocumented,
    unpinned invariant that every converted site depends on. This is what pins it.

    `test_writes_to_stderr_not_stdout` does not: it rebuilds the logger itself, so it
    compares `handler.stream` with `sys.stderr` at a moment when they agree whether the
    binding is lazy or not.
    """

    def setUp(self):
        self.logger = logging.getLogger(LOGGER_NAME)
        self._handlers = self.logger.handlers[:]
        self._level = self.logger.level
        self._propagate = self.logger.propagate
        # Start from the state that produces the bug: nothing attached, so the first
        # configure happens inside the redirect below.
        self.logger.handlers = []

    def tearDown(self):
        self.logger.handlers = self._handlers
        self.logger.setLevel(self._level)
        self.logger.propagate = self._propagate

    def test_a_later_record_reaches_the_stderr_of_its_own_moment(self):
        first = io.StringIO()
        with contextlib.redirect_stderr(first):
            get_harness_logger("pin").warning("during-the-first-stream")

        # Control: without this the test could pass on a handler that writes nowhere.
        self.assertIn(
            "during-the-first-stream",
            first.getvalue(),
            "precondition: the first record must reach the stream in force at the time",
        )

        later = io.StringIO()
        with contextlib.redirect_stderr(later):
            get_harness_logger("pin").warning("after-the-stream-was-replaced")

        self.assertIn(
            "after-the-stream-was-replaced",
            later.getvalue(),
            "the handler is still writing to the stream it was BUILT with. Under "
            "`bench run-tests` that is one dead test buffer, and every harness "
            "warning after it is invisible (#514)",
        )
        self.assertNotIn("after-the-stream-was-replaced", first.getvalue())

    def test_a_logger_object_cached_before_the_swap_follows_it_too(self):
        """The shape `tests/setup` and `enhanced_test_factory` actually use.

        Both bind `logger = get_harness_logger(...)` once at module level and call
        `.warning()` on that object for the rest of the process. Records from an adapter
        go straight to the logger's handlers, so nothing re-enters
        `_configured_logger()` -- a fix that only re-checked the binding on the next
        `get_harness_logger()` call would leave these two silent.
        """
        with contextlib.redirect_stderr(io.StringIO()):
            cached = get_harness_logger("cached")

        later = io.StringIO()
        with contextlib.redirect_stderr(later):
            cached.warning("from-the-cached-adapter")

        self.assertIn(
            "cached: from-the-cached-adapter",
            later.getvalue(),
            "a module-level logger captured before the swap is exactly the "
            "load-bearing case, and it never calls get_harness_logger() again",
        )

    def test_set_stream_still_installs_the_stream_it_is_given(self):
        """A `stream` setter that swallowed the assignment would break `logging`.

        `Handler.setStream` reports the stream it replaced and assumes the new one is
        in force; `flush()` and `close()` go through `self.stream` as well. So the
        override has to be real, not a no-op that lets the lazy value win.
        """
        get_harness_logger()
        handler = _stream_handler(self.logger)

        explicit = io.StringIO()
        handler.setStream(explicit)
        try:
            with contextlib.redirect_stderr(io.StringIO()) as ignored:
                self.logger.warning("to-the-explicit-stream")
            self.assertIn("to-the-explicit-stream", explicit.getvalue())
            self.assertEqual("", ignored.getvalue())
            self.assertIs(explicit, handler.stream)
        finally:
            # `None` means "follow sys.stderr" -- the same thing it means to
            # `StreamHandler(stream=None)`.
            handler.setStream(None)

        self.assertIs(sys.stderr, handler.stream)


class ClassTeardownRecordsMustSurviveTest(unittest.TestCase):
    """An ERROR emitted while frappe's capture is installed must also reach real stderr.

    `frappe/testing/result.py` swaps `sys.stderr` for `_module_or_class_stderr_capture`
    at `startTestRun` (`:54-59`) and drains it only when `startTest` sees a NEW test
    class (`:75-89`). `stopTestRun` (`:61-64`) restores the streams and never drains
    it. So a record written after the last test of the last class -- `tearDownClass`,
    `tearDownModule`, `addClassCleanup` -- lands in a buffer nothing ever reads. In a
    single-module run that is every class-teardown record there is, which is the
    workflow this module exists for.

    Before the lazy resolve the handler held the real `sys.stderr`, so these records
    bypassed the captures and were always visible. That visibility was accidental --
    the same binding is #514 -- but it was load-bearing, so it is restored
    deliberately here rather than mourned in a comment.

    Measured through the real `TestResult` with `buffer=True`, one class, one test,
    a warning inside the test and an error in `tearDownClass`:

        emit strategy       in-test record                tearDownClass record
        lazy resolve only   report x1                     LOST
        mirror everything   report x1 + real-stderr x1    real-stderr x1
        mirror >= ERROR     report x1                     real-stderr x1

    The middle row is why the mirror is level-gated. Duplicating every in-test record
    would undo the attribution this handler gained, and attribution is the reason it
    resolves lazily at all. ERROR is where the gate sits because that is the level of
    the one class-teardown record that must not be lost: `SingletonBackup.restore()`'s
    "Failed to restore %s: %s" (`singleton_backup.py:292`), the message that is in
    `HARNESS_FILES` precisely because a Single restored wrongly once said so nowhere
    (#433). It is the only ERROR among the five logging calls the ten known
    harness-logger-backed class-teardown sites reach; see `_StderrHandler` for the walk.

    The residual limit, stated because it is not fixed: a `.warning()` or `.info()`
    from class teardown is still lost. Only `frappe/` can fix that properly, by
    draining the buffer in `stopTestRun`.
    """

    def setUp(self):
        self.logger = logging.getLogger(LOGGER_NAME)
        self._handlers = self.logger.handlers[:]
        self._level = self.logger.level
        self._real_stderr = sys.__stderr__
        self.addCleanup(self._restore_logger_and_real_stderr)
        self.logger.handlers = []
        get_harness_logger()
        self.handler = _stream_handler(self.logger)

    def _restore_logger_and_real_stderr(self):
        sys.__stderr__ = self._real_stderr
        self.logger.handlers = self._handlers
        self.logger.setLevel(self._level)

    @contextlib.contextmanager
    def _under_frappe_capture(self):
        """Stand in for the runner: `sys.stderr` is a capture buffer, real stderr is not."""
        capture, real = io.StringIO(), io.StringIO()
        sys.__stderr__ = real
        original = sys.stderr
        sys.stderr = capture
        try:
            yield capture, real
        finally:
            sys.stderr = original

    def test_an_error_from_class_teardown_also_reaches_the_real_stderr(self):
        with self._under_frappe_capture() as (capture, real):
            self.logger.error("TEARDOWN-ERROR")

        self.assertIn("TEARDOWN-ERROR", capture.getvalue())
        self.assertIn("TEARDOWN-ERROR", real.getvalue())

    def test_a_warning_keeps_its_single_attributed_copy(self):
        """The in-test path must not double-print -- that is what the mirror costs."""
        with self._under_frappe_capture() as (capture, real):
            self.logger.warning("IN-TEST-WARNING")

        self.assertIn("IN-TEST-WARNING", capture.getvalue())
        self.assertEqual("", real.getvalue())

    def test_an_explicit_stream_is_never_mirrored(self):
        """`setStream` is a caller naming a destination; honour it and only it.

        This is also what keeps `captured_stream` -- which every level test in this
        file runs through -- from spraying records onto the real stderr.
        """
        explicit = io.StringIO()
        self.handler.setStream(explicit)
        try:
            with self._under_frappe_capture() as (capture, real):
                self.logger.error("TO-THE-EXPLICIT-STREAM")

            self.assertIn("TO-THE-EXPLICIT-STREAM", explicit.getvalue())
            self.assertEqual("", real.getvalue())
            self.assertEqual("", capture.getvalue())
        finally:
            self.handler.setStream(None)

    def test_a_closed_stream_does_not_raise_into_the_caller(self):
        """Every call site is an `except` block, so a raise here IS a swallowed failure.

        `StreamHandler.emit` routes the write error to `Handler.handleError`, which
        writes its own diagnostic to `sys.stderr` -- the same closed object -- and
        catches only `OSError`. The `ValueError` therefore escapes `.error()` itself.
        Measured before this fallback: `ValueError: I/O operation on closed file`.
        """
        dead, real = io.StringIO(), io.StringIO()
        dead.close()
        sys.__stderr__ = real
        original = sys.stderr
        sys.stderr = dead
        try:
            self.logger.error("RECORD-INTO-CLOSED-STREAM")
        finally:
            sys.stderr = original

        self.assertIn("RECORD-INTO-CLOSED-STREAM", real.getvalue())


class AssertLogsMustNotDegradeTheLoggerTest(unittest.TestCase):
    """`assertLogs` takes the handler away and cannot give the flag back.

    It snapshots `handlers`/`level`/`propagate` on entry and restores that snapshot on
    exit, so a logger first configured INSIDE the block comes out with no handlers --
    while any "we configured this once" flag still says otherwise. Every later harness
    record in the process then goes to `logging.lastResort`: unformatted, no level, and
    `VERENIGINGEN_TEST_LOG_LEVEL` silently dead.

    That is a process-wide degradation caused by one test, which makes it exactly the
    order-dependence this harness keeps paying for. Pinned here rather than worked
    around at each `assertLogs` call site, because a workaround only protects the author
    who knows about it.
    """

    def setUp(self):
        self.logger = logging.getLogger(LOGGER_NAME)
        self._handlers = self.logger.handlers[:]
        self._level = self.logger.level
        self._propagate = self.logger.propagate

    def tearDown(self):
        self.logger.handlers = self._handlers
        self.logger.setLevel(self._level)
        self.logger.propagate = self._propagate

    def test_the_stderr_handler_comes_back_after_an_assertlogs_block(self):
        # Start from the state that produces the bug: nothing attached, so the first
        # configure happens inside assertLogs.
        self.logger.handlers = []

        with self.assertLogs(LOGGER_NAME, level="ERROR"):
            get_harness_logger("pin").error("inside")

        self.assertEqual(
            [],
            self.logger.handlers,
            "precondition: assertLogs is expected to restore the empty snapshot",
        )

        # The next caller must get a real handler back, not lastResort.
        logger = get_harness_logger("pin")
        handler = _stream_handler(self.logger)
        self.assertIs(handler.stream, sys.stderr)
        self.assertEqual(harness_logger.DEFAULT_LEVEL, self.logger.level)
        self.assertFalse(self.logger.propagate)
        with captured_stream(self.logger) as buffer:
            logger.warning("after")
        self.assertIn("pin: after", buffer.getvalue())


@contextlib.contextmanager
def captured_stream(logger):
    """Swap the logger's stream for a buffer, restoring it even on failure.

    Restores with `None` -- "follow `sys.stderr`" -- rather than with the object read
    out of `handler.stream` on the way in. Reading it resolves `sys.stderr` NOW, and
    putting that object back would pin it as an explicit override, which is #514
    re-created inside the helper that the tests for #514 run through.
    """
    handler = _stream_handler(logger)
    buffer = io.StringIO()
    handler.setStream(buffer)
    try:
        yield buffer
    finally:
        handler.setStream(None)


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
