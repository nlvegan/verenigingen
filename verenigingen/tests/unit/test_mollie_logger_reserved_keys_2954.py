"""MollieLogger must log a caller kwarg that names a reserved LogRecord attribute (#2954).

``context.update(kwargs)`` fed caller kwargs straight into ``extra=``, so ``module="x"``
made ``Logger.makeRecord`` raise ``KeyError: "Attempt to overwrite 'module' in LogRecord"``
whenever the level was enabled. The caller's value must survive under ``ctx_<key>``.

The level is set explicitly (a bare frappe.logger() is WARNING on a developer_mode site and
ERROR on CI) and restored.
"""

import logging
import unittest

import frappe

from verenigingen.verenigingen_payments.mollie.utils.logging import MollieLogger


class _2954ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestMollieLoggerReservedKeys2954(unittest.TestCase):
    def setUp(self):
        self.std_logger = frappe.logger("mollie")
        self.handler = _2954ListHandler()
        self.old_level = self.std_logger.level
        self.std_logger.addHandler(self.handler)
        self.std_logger.setLevel(logging.DEBUG)
        self.addCleanup(self._restore_logger)
        self.mollie = MollieLogger("t2954")

    def _restore_logger(self):
        self.std_logger.removeHandler(self.handler)
        self.std_logger.setLevel(self.old_level)

    def _assert_one_record_preserving(self, key, value):
        self.assertEqual(len(self.handler.records), 1)
        record = self.handler.records[0]
        self.assertEqual(getattr(record, f"ctx_{key}"), value)
        return record

    def test_info_reserved_kwarg(self):
        self.mollie.info("m", module="x")
        record = self._assert_one_record_preserving("module", "x")
        self.assertNotEqual(record.module, "x")

    def test_success_reserved_kwarg(self):
        self.mollie.success("m", name="y")
        record = self._assert_one_record_preserving("name", "y")
        self.assertNotEqual(record.name, "y")

    def test_warning_reserved_kwarg(self):
        self.mollie.warning("m", args="a")
        self._assert_one_record_preserving("args", "a")

    def test_error_reserved_kwarg(self):
        self.mollie.error("m", lineno=7)
        self._assert_one_record_preserving("lineno", 7)

    def test_performance_reserved_kwarg_fast_and_slow(self):
        self.mollie.performance("op", 0.1, funcName="f")
        self.mollie.performance("op", 3.0, filename="g")
        self.assertEqual(len(self.handler.records), 2)
        self.assertEqual(self.handler.records[0].ctx_funcName, "f")
        self.assertEqual(self.handler.records[1].ctx_filename, "g")

    def test_exc_info_reserved_kwarg_is_preserved_not_applied(self):
        self.mollie.info("m", exc_info="boom")
        record = self._assert_one_record_preserving("exc_info", "boom")
        self.assertIsNone(record.exc_info)

    def test_control_non_reserved_kwarg_keeps_its_own_key(self):
        self.mollie.info("m", payment_ref="p1")
        record = self.handler.records[0]
        self.assertEqual(record.payment_ref, "p1")
        self.assertFalse(hasattr(record, "ctx_payment_ref"))
