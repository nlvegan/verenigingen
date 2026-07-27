"""Tests that service-layer logging actually reaches a log file.

Regression for MR-SYNC-2026-00087: `BaseService.logger` was a bare
`logging.getLogger("verenigingen.services.X")`. Frappe only configures handlers
for loggers it creates itself (named `"{module}-{site}"`), so those loggers had
no handler; records fell through to Python's `lastResort` handler, which put
WARNING and above on stderr (unformatted, untimestamped) and dropped everything
below it.

These tests assert the observable behaviour — a line lands on disk — rather than
the implementation detail of which logger object is returned.

Logger names here are FIXED, not randomised: `frappe.logger()` opens two
`RotatingFileHandler`s per distinct name per site and caches them in the
process-global `frappe.loggers` forever, so a hashed name per test would leak a
pair of files and file descriptors on every run.
"""

import logging
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.service_logger import get_service_logger

PROBE_LOGGER = "verenigingen.test_service_logger"
PROBE_SERVICE = "ServiceLoggerProbe"


def _log_paths(logger_name):
    """Both files frappe.logger() writes: site-level and bench-level."""
    return [
        frappe.get_site_path("logs", f"{logger_name}.log"),
        os.path.join("..", "logs", f"{logger_name}.log"),
    ]


def _read_site_log(logger_name):
    path = frappe.get_site_path("logs", f"{logger_name}.log")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return handle.read()


class _ProbeService(StatelessService):
    def __init__(self, service_name):
        super().__init__(service_name=service_name)


class TestServiceLogger(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self._discard_probe_loggers)

    def _discard_probe_loggers(self):
        """Close handlers, drop the frappe cache entry, and remove the files.

        Without this each run would leave two log files and two open file
        descriptors behind per logger name, in both the site and bench log dirs.
        """
        for logger_name in (PROBE_LOGGER, "verenigingen.services"):
            for key in [k for k in frappe.loggers if k.startswith(f"{logger_name}-")]:
                cached = frappe.loggers.pop(key)
                for handler in list(cached.handlers):
                    handler.close()
                    cached.removeHandler(handler)
            if logger_name == PROBE_LOGGER:
                for path in _log_paths(logger_name):
                    if os.path.exists(path):
                        os.remove(path)

    def test_lazy_logger_writes_error_to_site_log_file(self):
        marker = f"lazy-logger-marker-{frappe.generate_hash(length=8)}"

        get_service_logger(PROBE_LOGGER).error(marker)

        self.assertIn(marker, _read_site_log(PROBE_LOGGER))

    def test_base_service_logger_writes_error_to_site_log_file(self):
        marker = f"base-service-marker-{frappe.generate_hash(length=8)}"

        _ProbeService(PROBE_SERVICE).logger.error(marker)

        self.assertIn(marker, _read_site_log("verenigingen.services"))

    def test_base_service_logger_prefixes_the_service_name(self):
        """Service identity has to survive the collapse to one shared logger name.

        BaseService shares a single "verenigingen.services" logger so frappe does
        not open ~230 file handlers per worker, so the class name must appear in
        the message instead of the filename.
        """
        marker = f"prefix-marker-{frappe.generate_hash(length=8)}"

        _ProbeService(PROBE_SERVICE).logger.error(marker)

        self.assertIn(f"{PROBE_SERVICE}: {marker}", _read_site_log("verenigingen.services"))

    def test_prefix_leaves_percent_args_intact(self):
        """The prefix is prepended to the format string, not to the rendered text."""
        token = frappe.generate_hash(length=8)

        get_service_logger(PROBE_LOGGER, prefix="probe").error("row %s of %s", token, 42)

        self.assertIn(f"probe: row {token} of 42", _read_site_log(PROBE_LOGGER))

    def test_logger_has_a_handler(self):
        """A bare logging.getLogger() has none — that was the whole bug."""
        self.assertTrue(
            get_service_logger(PROBE_LOGGER).handlers,
            "service logger has no handler, messages will be discarded",
        )

    def test_logger_is_resolved_on_every_use_not_cached(self):
        """Module-level singletons outlive a request, so the logger must not pin a site.

        `frappe.logger()` binds its handler to `frappe.local.site` and memoises per
        site. Resolving once and holding the result would send every later request
        on a multi-site bench to the first site's log file.
        """
        from unittest.mock import patch

        logger = get_service_logger(PROBE_LOGGER)
        real_logger = frappe.logger
        calls = []

        def counting_logger(module=None, *args, **kwargs):
            calls.append(module)
            return real_logger(module, *args, **kwargs)

        with patch.object(frappe, "logger", counting_logger):
            logger.error("first")
            logger.error("second")

        self.assertEqual(calls.count(PROBE_LOGGER), 2)

    def test_logging_failure_does_not_propagate_to_the_caller(self):
        """frappe.logger() opens a file handler eagerly and can fail; the caller must not.

        Otherwise this shim would turn a previously-silent log call into an
        exception thrown out of whatever business operation was being logged.
        """
        import warnings
        from unittest.mock import patch

        import verenigingen.utils.service_logger as service_logger

        logger = get_service_logger(PROBE_LOGGER)

        def exploding_logger(*args, **kwargs):
            raise OSError("logs directory is not writable")

        original_warned = service_logger._fallback_warned
        service_logger._fallback_warned = False
        try:
            with patch.object(frappe, "logger", exploding_logger):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    logger.error("must not raise")
                    # Degrades to the unconfigured stdlib logger...
                    self.assertFalse(logger.handlers)
                # ...but says so, rather than silently reinstating the bug.
                self.assertTrue(
                    any(issubclass(w.category, RuntimeWarning) for w in caught),
                    "expected a RuntimeWarning about the logging fallback",
                )
        finally:
            service_logger._fallback_warned = original_warned

    def test_bare_stdlib_logger_still_has_no_handler(self):
        """Pins the premise of the whole fix, so it cannot silently stop being true."""
        self.assertFalse(logging.getLogger(f"{PROBE_LOGGER}.bare").handlers)
