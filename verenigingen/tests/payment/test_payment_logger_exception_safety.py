"""
Exception-safety tests for PaymentLogger sinks.

The four base sink methods (log_debug/log_info/log_warning/log_error) are now
called from inside money-path try/except blocks (webhook signature validation,
PaymentHook.initiate_payment). A logging failure must NEVER propagate into the
caller, or it could mask/alter the real payment outcome. These tests force the
underlying frappe sinks to raise and assert the PaymentLogger swallows it.

Canonical sink module:
    verenigingen.verenigingen_payments.utils.payment_services.logging_utils.PaymentLogger
"""

from unittest.mock import patch

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import PaymentLogger


class TestPaymentLoggerExceptionSafety(VereningingenTestCase):
    """Assert the base sinks never propagate a failure from the underlying logger."""

    def test_log_error_swallows_underlying_failure(self):
        # Mock justified: force the underlying frappe.log_error sink to raise; the
        # PaymentLogger contract is that it must never propagate a logging failure.
        with patch("frappe.log_error", side_effect=Exception("sink boom")):
            # Must NOT raise:
            PaymentLogger.log_error("boom message", "Test Category", {"k": "v"})

    def test_log_error_swallows_logger_failure(self):
        class _BoomLogger:
            def error(self, *a, **k):
                raise Exception("logger boom")

            def debug(self, *a, **k):
                pass

        # Mock justified: force frappe.logger() to return a logger whose .error
        # raises, AND keep frappe.log_error intact (it would also fire); the
        # contract is that neither sink failure escapes.
        with patch("frappe.logger", return_value=_BoomLogger()), patch("frappe.log_error"):
            PaymentLogger.log_error("hi", "Test Category")  # must not raise

    def test_log_info_swallows_underlying_failure(self):
        class _BoomLogger:
            def info(self, *a, **k):
                raise Exception("logger boom")

            def debug(self, *a, **k):
                pass

        # Mock justified: force frappe.logger() to return a logger whose .info raises.
        with patch("frappe.logger", return_value=_BoomLogger()):
            PaymentLogger.log_info("hi", "Test Category")  # must not raise

    def test_log_warning_swallows_underlying_failure(self):
        class _BoomLogger:
            def warning(self, *a, **k):
                raise Exception("logger boom")

            def debug(self, *a, **k):
                pass

        # Mock justified: force frappe.logger() to return a logger whose .warning raises.
        with patch("frappe.logger", return_value=_BoomLogger()):
            PaymentLogger.log_warning("hi", "Test Category")  # must not raise

    def test_log_debug_swallows_underlying_failure(self):
        class _BoomLogger:
            def debug(self, *a, **k):
                raise Exception("logger boom")

        # Mock justified: force frappe.logger() to return a logger whose .debug raises.
        with patch("frappe.logger", return_value=_BoomLogger()):
            PaymentLogger.log_debug("hi", "Test Category")  # must not raise

    def test_log_error_with_overlong_title_does_not_raise(self):
        # A category + message exceeding the 140-char Error Log title limit must
        # not surface as CharacterLengthExceededError (a real prod bug class here).
        long_message = "x" * 500
        PaymentLogger.log_error(long_message, "Test Category", {"k": "v"})  # must not raise
