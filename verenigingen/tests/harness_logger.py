"""A logger for the test harness whose output actually exists.

Why this exists
---------------
Every bare ``frappe.logger()`` in the test harness discards ``.warning()``,
``.info()`` and ``.debug()`` outright. ``get_logger`` sets the level to
``frappe.log_level or default_log_level`` (``frappe/utils/logger.py:80``), and
``default_log_level`` is ``WARNING if frappe._dev_server else ERROR``
(``:12``). ``DEV_SERVER`` is unset under ``bench run-tests`` and
``frappe.log_level`` is only ever assigned by ``bench console``
(``frappe/commands/utils.py:640``), so the effective level is **ERROR**.

Measured under ``bench --site test_site_2 run-tests`` on 2026-08-12::

    frappe._dev_server: 0
    frappe.log_level:   None
    effective level:    40 ERROR
    isEnabledFor(WARNING): False

So a setup handler that catches an exception and "logs a warning and
continues" writes **nothing** — not to stdout, not to ``logs/frappe.log``.
That is how the ``Territory: Netherlands`` failure behind #291 stayed
invisible while it reddened four unrelated CI shards, and why #309 has to fix
the logging before any argument about which handlers should be fatal can be
observed at all.

Two things are different here, and both are needed:

1. **An explicit level**, not one inherited from a frappe global that is set
   for the console and nothing else.
2. **A stderr handler.** ``frappe.logger()`` attaches ``RotatingFileHandler``s
   and sets ``propagate = False``. Even at the right level its records land in
   ``logs/frappe.log``, which CI does not surface. A harness warning nobody
   reads is the bug this module exists to fix, one layer along. The handler
   resolves ``sys.stderr`` when it emits rather than storing it -- see
   ``_StderrHandler``; the test runner swaps that object out per test (#514).

This is deliberately *not* built on ``verenigingen.utils.service_logger`` —
that shim fixes handler attachment for the production service layer and says
so in its own docstring ("Frappe defaults these loggers to ERROR ... do not
rely on these for audit trails"). Production logging belongs in the site log;
harness diagnostics belong where the person reading a red CI job will see
them.

It sits in ``verenigingen.tests`` rather than the more natural
``verenigingen.tests.utils`` because that package's ``__init__`` imports
``verenigingen.tests.setup`` on the way in, and ``tests/setup`` is one of the
callers. Importing this from there would re-enter a half-initialised module.
``verenigingen/tests/__init__.py`` has no such side effect.

Usage::

    from verenigingen.tests.harness_logger import get_harness_logger

    logger = get_harness_logger("master-data")
    logger.warning("Could not create role %s: %s", role_name, e)
    # -> stderr: "WARNING verenigingen.tests.harness master-data: Could not ..."

Set ``VERENIGINGEN_TEST_LOG_LEVEL=DEBUG`` to see ``.info()``/``.debug()`` as
well; the default is ``WARNING``.
"""

import logging
import os
import sys

LOGGER_NAME = "verenigingen.tests.harness"
LEVEL_ENV_VAR = "VERENIGINGEN_TEST_LOG_LEVEL"
DEFAULT_LEVEL = logging.WARNING

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

# Marks the logger as configured by this module. Set on the logger object
# rather than kept in a module global so a caller that reaches for
# ``logging.getLogger(LOGGER_NAME)`` directly cannot end up with a second,
# duplicate handler through us.
_CONFIGURED_FLAG = "_verenigingen_harness_configured"
# The handler itself, stashed so `_configured_logger` can ask whether it is still
# attached. See its docstring: a "have we configured this" boolean cannot notice
# that something removed the handler behind our back.
_HANDLER_ATTR = "_verenigingen_harness_handler"


def get_harness_logger(prefix: str = "") -> logging.Logger | logging.LoggerAdapter:
    """Return the harness logger, configured to write WARNING+ to stderr.

    Args:
        prefix: Identifies the caller within the harness (e.g. ``"fixtures"``,
            ``"master-data"``). Prepended to every message. One logger name is
            shared on purpose so the handler is attached exactly once.
    """
    logger = _configured_logger()
    if not prefix:
        return logger
    return _PrefixedAdapter(logger, {"prefix": prefix})


class _StderrHandler(logging.StreamHandler):
    """A ``StreamHandler`` that resolves ``sys.stderr`` when it emits.

    ``logging.StreamHandler(sys.stderr)`` stores the stream OBJECT. That is fine in a
    normal process and wrong under the test runner: ``frappe/testing/result.py``
    replaces ``sys.stderr`` with a fresh ``io.StringIO`` at ``startTestRun``
    (``:54-59``) and again at every ``startTest`` (``:99-104``), reading each buffer
    into the report once and then dropping it. So a handler built inside a test is
    bound for the rest of the process to that one test's buffer, and every later
    harness record -- the whole point of this module -- goes somewhere nothing reads,
    taking ``VERENIGINGEN_TEST_LOG_LEVEL`` with it.

    Measured under the real ``TestResult`` before this class existed: three warnings
    from three tests, all three in test 1's buffer, only the first surfaced (#514).
    It stayed latent only because ``tests/setup/__init__.py`` and
    ``tests/fixtures/enhanced_test_factory.py`` configure the logger at IMPORT time,
    before ``startTestRun`` -- an invariant nothing documented or pinned.

    The lazy read is the stdlib's own answer to this: ``logging._StderrHandler``,
    which backs ``logging.lastResort``, is a ``StreamHandler`` with exactly this
    property and exactly this docstring reason. The setter is the part the stdlib
    leaves out (there, assignment raises): ``Handler.setStream`` returns the stream it
    replaced and assumes the new one is in force, and ``flush``/``close`` read
    ``self.stream``, so a setter that silently swallowed the assignment would turn
    every capture helper into a no-op. ``None`` means "follow ``sys.stderr``", the
    same thing it means to ``StreamHandler(stream=None)``.

    Fixing it here rather than by re-checking the binding in ``_configured_logger``:
    ``tests/setup`` and ``enhanced_test_factory`` cache the adapter at module level and
    call ``.warning()`` on it for the rest of the run. Records from an adapter go
    straight to the logger's handlers, so those two never re-enter
    ``_configured_logger`` and a guard could not reach them.

    What the lazy read costs, and what ``emit`` gives back
    -----------------------------------------------------
    Resolving lazily puts records INTO frappe's captures, which is the gain -- each one
    is attributed to the test that wrote it. It is also a loss, because one capture is
    never read: ``result.py`` drains ``_module_or_class_stderr_capture`` only when
    ``startTest`` sees a NEW class (``:75-89``), and ``stopTestRun`` (``:61-64``)
    restores the streams without draining it. Anything written after the last test of
    the last class -- ``tearDownClass``, ``tearDownModule``, ``addClassCleanup`` --
    lands there and is lost. In a single-module run that is EVERY class-teardown
    record, and a single-module run is the workflow this module exists for.

    The old bound handler bypassed the captures, so those records were always visible.
    That was an accident of the very bug this class fixes, but it was load-bearing.
    Measured 2026-08-25 by an AST call-graph walk over ``verenigingen/`` (real defs only,
    so the ``tearDownClass`` in this package's own docstring examples does not count):
    **eleven** ``tearDownClass`` bodies reach this logger -- nine through
    ``SingletonBackup.restore()`` -> ``_restore_singleton``, one through
    ``TestWebhookUserSetup._sweep_webhook_users``, and one through
    ``cls._test_instance.tearDown()`` (``test_chapter_permission_service_integration.py:182``),
    the only place in the repo where a class teardown invokes a per-test ``tearDown`` on a
    stashed instance -- which binds to ``EnhancedTestCase.tearDown`` and so drags the whole
    drain onto a class-teardown path. Between them they reach NINETEEN logging calls at
    three levels, of which TWO are at ERROR: ``_restore_singleton``'s "Failed to restore
    %s: %s" (``singleton_backup.py:292``) and ``ErrorLogGuardMixin._capture_test_error_logs``'
    "Error Log guard capture failed" (``error_log_guard.py:194``) -- both tracked precisely
    because a failure that said so nowhere is #433.

    Edges were resolved by callee name, EXCEPT that an attribute call's receiver was
    resolved to its class and bound through the MRO. That exception is not cosmetic:
    ``tearDown`` has 498 defs in this repo (``cleanup`` 7, ``restore`` 4), so resolving
    ``cls._test_instance.tearDown()`` by name alone links to all 498 and the walk returns
    34 calls at 6 ERRORs instead of 19 at 2. Receiver resolution is what excludes those,
    and it is also the only thing that keeps the phantom ``factories.py:260`` out of the
    set -- six teardowns call ``cls.factory.cleanup()``, but that receiver is
    ``CoreTestDataFactory``, whose ``cleanup`` uses ``print()``.

    Lifecycle methods were excluded as call TARGETS except on a non-``super()`` receiver.
    That second exception is the entirety of the third route, and dropping it
    unconditionally is what made an earlier revision of this paragraph say "ten" and
    "exactly one ERROR". Both alias-form loggers (``logger = get_harness_logger(...)``, as
    ``enhanced_test_factory`` and ``tests/setup`` cache them) and inline
    ``get_harness_logger(...).level(...)`` calls were matched; a scan for only one shape
    misses the other entirely, and route 3 is 13 alias-form calls to 1 inline -- an
    alias-blind scan reports it as a single call and the sixteen WARNINGs become one.

    So ``emit`` mirrors onto ``sys.__stderr__``, which the runner never swaps, for
    records at ERROR and above. Measured through the real ``TestResult`` with
    ``buffer=True`` -- one class, one test, a warning inside it and an error in
    ``tearDownClass``::

        emit strategy       in-test record                tearDownClass record
        lazy resolve only   report x1                     LOST
        mirror everything   report x1 + real-stderr x1    real-stderr x1
        mirror >= ERROR     report x1                     real-stderr x1

    The gate is what keeps the middle row from happening: mirroring everything
    duplicates every in-test record and gives back the attribution the lazy read was
    for. ERROR is where the gate sits because that is the level of the two
    class-teardown records that must not be lost, above. It does NOT cover the other
    seventeen -- see the residual limit.

    **The residual limit:** anything below ERROR from class teardown is still lost -- a
    ``.warning()``, ``.info()`` or ``.debug()``. Measured, that is seventeen of the
    nineteen: sixteen WARNING and one DEBUG. No INFO site is class-teardown-reachable
    today, so the gate's INFO behaviour is untested by that census rather than confirmed
    by it. Fixing the loss properly means draining the buffer in ``stopTestRun``, which is
    ``frappe/``'s to do, not this app's.
    """

    def __init__(self):
        # Deliberately not StreamHandler.__init__: it assigns self.stream, which our
        # setter would record as an explicit override of the very value we want to
        # keep resolving lazily.
        logging.Handler.__init__(self)
        self._explicit_stream = None

    @property
    def stream(self):
        if self._explicit_stream is not None:
            return self._explicit_stream
        return sys.stderr

    @stream.setter
    def stream(self, value):
        self._explicit_stream = value

    def emit(self, record):
        """Write the record, then make sure an ERROR is visible even under capture.

        Two measured failure modes, both answered by falling back to the real stderr.
        `ClassTeardownRecordsMustSurviveTest` holds the controls for each.
        """
        try:
            super().emit(record)
        except Exception:
            # A closed or detached `sys.stderr`. `StreamHandler.emit` hands the write
            # error to `Handler.handleError`, which writes its own diagnostic to the
            # SAME dead object and catches only `OSError` -- so the `ValueError`
            # escapes into the caller, and every caller here is an `except` block.
            # A logger that raises out of the handler it was called from is the exact
            # failure this module exists to prevent.
            self._write_to_real_stderr(record)
            return

        if record.levelno >= logging.ERROR and self._explicit_stream is None:
            self._write_to_real_stderr(record)

    def _write_to_real_stderr(self, record):
        """Mirror onto `sys.__stderr__`, the one stream the test runner never swaps.

        Skipped when the resolved stream already IS the real stderr, which is the
        normal non-test case and would otherwise print everything twice.
        """
        real = sys.__stderr__
        if real is None or real is self.stream:
            return
        try:
            real.write(self.format(record) + self.terminator)
            real.flush()
        except Exception:
            # Best-effort by construction: see above -- this must not raise either.
            pass


def _configured_logger() -> logging.Logger:
    """Return the logger, configuring it if OUR HANDLER is not currently attached.

    The guard asks whether the handler is there, not whether we have ever set it up.
    A boolean "configured once" flag is not equivalent, because something else can
    take the handler away and cannot clear the flag: `unittest`'s `assertLogs`
    snapshots `handlers`, `level` and `propagate` on entry and restores that snapshot
    on exit, so a logger first configured INSIDE an `assertLogs` block comes out with
    an empty handler list and a flag still saying "configured". Every later harness
    message in the process then falls through to `logging.lastResort` -- unformatted,
    and with `VERENIGINGEN_TEST_LOG_LEVEL` silently dead.

    Measured before this guard changed:

        after assertLogs: handlers=[] level=0 propagate=True flag=True
        later record      -> "later-message-A" via lastResort, no level, no name

    Keyed on identity, so it survives a caller that adds a handler of its own.
    """
    logger = logging.getLogger(LOGGER_NAME)
    existing = getattr(logger, _HANDLER_ATTR, None)
    if existing is not None and existing in logger.handlers:
        return logger

    handler = _StderrHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(_configured_level())
    # The root logger is unconfigured under `bench run-tests`, so propagating
    # would fall through to logging.lastResort -- a second, unformatted copy of
    # every record on stderr.
    logger.propagate = False
    setattr(logger, _HANDLER_ATTR, handler)
    setattr(logger, _CONFIGURED_FLAG, True)
    return logger


def _configured_level() -> int:
    """Resolve the level from the environment, falling back to WARNING.

    An unparseable value is not worth failing a test run over, but it must not
    silently mean "log nothing" either -- that is the failure mode this whole
    module is about -- so it falls back to the default.
    """
    requested = os.environ.get(LEVEL_ENV_VAR)
    if not requested:
        return DEFAULT_LEVEL

    level = _LEVELS.get(requested.strip().upper())
    if level is not None:
        return level

    print(
        f"{LEVEL_ENV_VAR}={requested!r} is not one of {sorted(_LEVELS)}; using WARNING",
        file=sys.stderr,
    )
    return DEFAULT_LEVEL


class _PrefixedAdapter(logging.LoggerAdapter):
    """Prepends ``prefix`` to the message.

    ``kwargs`` is returned untouched rather than through
    ``LoggerAdapter.process``, which would inject ``extra={"prefix": ...}``
    into every record for no reader's benefit. ``exc_info``, ``stacklevel`` and
    ``%``-style args pass through either way.
    """

    def process(self, msg, kwargs):
        return f"{self.extra['prefix']}: {msg}", kwargs
