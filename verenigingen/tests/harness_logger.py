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
   reads is the bug this module exists to fix, one layer along.

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

    handler = logging.StreamHandler(sys.stderr)
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
