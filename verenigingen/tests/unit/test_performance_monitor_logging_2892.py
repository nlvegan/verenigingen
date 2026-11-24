"""@performance_monitor must log a slow call, not raise from it (#2892).

Two defects sat on the slow-operation warning:

* no f-prefix, so the braces were logged literally;
* ``extra={"module": ...}``: ``module`` is a reserved LogRecord attribute, so as soon as
  the logger is enabled for WARNING (a dev server) ``Logger.makeRecord`` raised
  ``KeyError`` out of the wrapper's ``finally`` and a slow, successful call failed.

The level is set explicitly (a bare frappe.logger() is WARNING on a developer_mode site and
ERROR on CI), and restored. ``threshold_ms=-1`` makes any call "slow" without sleeping.
"""

import logging
import unittest

import frappe

from verenigingen.utils.performance_utils import performance_monitor

_2892_LOGGER_NAME = "verenigingen.performance"


class _2892ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _2892_slow_function():
    return "result"


class TestPerformanceMonitorLogging2892(unittest.TestCase):
    def setUp(self):
        self.logger = frappe.logger(_2892_LOGGER_NAME)
        self.handler = _2892ListHandler()
        self.old_level = self.logger.level
        self.logger.addHandler(self.handler)
        self.addCleanup(self._restore_logger)

    def _restore_logger(self):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.old_level)

    def _call_slow(self):
        return performance_monitor(threshold_ms=-1)(_2892_slow_function)()

    def test_slow_call_with_warning_enabled_returns_and_logs_real_values(self):
        self.logger.setLevel(logging.WARNING)

        self.assertEqual(self._call_slow(), "result")

        self.assertEqual(len(self.handler.records), 1)
        message = self.handler.records[0].getMessage()
        self.assertIn(f"{_2892_slow_function.__module__}._2892_slow_function took ", message)
        self.assertNotIn("{", message)
        # The real module of the decorated function survives under a non-reserved key,
        # and the record's own ``module`` is the logging module's, untouched.
        self.assertEqual(self.handler.records[0].func_module, _2892_slow_function.__module__)

    def test_slow_call_with_warning_disabled_returns_and_logs_nothing(self):
        self.logger.setLevel(logging.ERROR)

        self.assertEqual(self._call_slow(), "result")

        self.assertEqual(self.handler.records, [])

    def test_fast_call_logs_nothing(self):
        self.logger.setLevel(logging.WARNING)

        self.assertEqual(performance_monitor(threshold_ms=60000)(_2892_slow_function)(), "result")

        self.assertEqual(self.handler.records, [])
