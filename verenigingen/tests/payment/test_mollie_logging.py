"""
Unit tests for Mollie logging utilities.

Target: verenigingen/verenigingen_payments/mollie/utils/logging.py

These tests exercise the logging logic directly and only mock the
frappe boundary (frappe.logger / frappe.log_error). The logger logic
itself (sanitization, context building, level selection) is NOT mocked.
"""

import unittest
from unittest.mock import MagicMock, patch

from verenigingen.verenigingen_payments.mollie.utils import logging as logging_module
from verenigingen.verenigingen_payments.mollie.utils.logging import (
    MollieLogger,
    log_integration_health_check,
    log_mollie_api_call,
    log_payment_processing,
    log_webhook_received,
    mollie_operation_logger,
)


class TestSanitizeData(unittest.TestCase):
    """_sanitize_data is the most business-critical method (security filtering)."""

    def setUp(self):
        self.logger = MollieLogger("test")

    def test_redacts_sensitive_keys_case_insensitive(self):
        data = {
            "api_key": "x",
            "Authorization": "y",
            "webhook_secret": "z",
            "PASSWORD": "p",
            "access_token": "t",
        }
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["api_key"], "***REDACTED***")
        self.assertEqual(result["Authorization"], "***REDACTED***")
        self.assertEqual(result["webhook_secret"], "***REDACTED***")
        self.assertEqual(result["PASSWORD"], "***REDACTED***")
        self.assertEqual(result["access_token"], "***REDACTED***")

    def test_non_sensitive_scalar_passes_through(self):
        data = {"amount": 10, "currency": "EUR", "flag": True}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result, {"amount": 10, "currency": "EUR", "flag": True})

    def test_long_id_truncated_to_12_plus_ellipsis(self):
        # 16 chars > 12 -> first 12 + "..."
        data = {"id": "abcdefghijklmnop"}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["id"], "abcdefghijkl...")

    def test_short_id_left_as_is(self):
        data = {"payment_id": "tr_123"}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["payment_id"], "tr_123")

    def test_id_exactly_12_chars_not_truncated(self):
        # len == 12 is NOT > 12, so left as-is
        data = {"customer_id": "123456789012"}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["customer_id"], "123456789012")

    def test_subscription_id_truncation(self):
        data = {"subscription_id": "sub_aaaaaaaaaaaaaaaa"}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["subscription_id"], "sub_aaaaaaaa...")

    def test_int_id_short_passes_through_unchanged(self):
        # Bug-hunt: int id with str length <= 12 returns the original int value.
        data = {"id": 12345}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["id"], 12345)
        self.assertIsInstance(result["id"], int)

    def test_int_id_long_gets_string_truncated(self):
        # str(value) length 13 > 12 -> truncated string
        data = {"id": 1234567890123}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["id"], "123456789012...")

    def test_nested_dict_secret_redacted(self):
        data = {"outer": {"inner_token": "secret_value", "ok": 1}}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["outer"]["inner_token"], "***REDACTED***")
        self.assertEqual(result["outer"]["ok"], 1)

    def test_list_with_nested_secret_redacted(self):
        data = {"items": [{"auth": "x"}, {"name": "ok"}]}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["items"][0]["auth"], "***REDACTED***")
        self.assertEqual(result["items"][1]["name"], "ok")

    def test_top_level_list_recursively_sanitized(self):
        data = ["plain", {"secret": "hidden"}, ["nested", {"my_key": "v"}]]
        result = self.logger._sanitize_data(data)
        self.assertEqual(result[0], "plain")
        self.assertEqual(result[1]["secret"], "***REDACTED***")
        self.assertEqual(result[2][1]["my_key"], "***REDACTED***")

    def test_long_string_truncated_to_200(self):
        long_str = "a" * 250
        result = self.logger._sanitize_data(long_str)
        self.assertEqual(result, "a" * 200 + "...")
        self.assertEqual(len(result), 203)

    def test_short_string_not_truncated(self):
        result = self.logger._sanitize_data("short value")
        self.assertEqual(result, "short value")

    def test_long_string_value_inside_dict_truncated(self):
        data = {"description": "b" * 300}
        result = self.logger._sanitize_data(data)
        self.assertEqual(result["description"], "b" * 200 + "...")


class TestGetBaseContext(unittest.TestCase):
    def test_context_has_required_keys_and_operation_type(self):
        logger = MollieLogger("my_op")
        ctx = logger._get_base_context()
        self.assertIn("timestamp", ctx)
        self.assertIn("operation_type", ctx)
        self.assertIn("site", ctx)
        self.assertIn("user", ctx)
        self.assertEqual(ctx["operation_type"], "my_op")

    def test_default_operation_type_is_general(self):
        logger = MollieLogger()
        self.assertEqual(logger.operation_type, "general")
        self.assertEqual(logger._get_base_context()["operation_type"], "general")


class TestLogLevels(unittest.TestCase):
    """info/success/warning/error/performance level + emoji + context behavior."""

    def setUp(self):
        self.logger = MollieLogger("ops")
        self.mock_logger = MagicMock()

    def _patch_logger(self):
        return patch.object(logging_module.frappe, "logger", return_value=self.mock_logger)

    def test_info_logs_info_with_blue_emoji(self):
        with self._patch_logger():
            self.logger.info("doing thing", data={"x": 1})
        self.mock_logger.info.assert_called_once()
        msg, kwargs = self.mock_logger.info.call_args[0][0], self.mock_logger.info.call_args[1]
        self.assertIn("🔵", msg)
        self.assertIn("[ops]", msg)
        self.assertIn("doing thing", msg)
        self.assertIn("extra", kwargs)
        self.assertEqual(kwargs["extra"]["data"], {"x": 1})

    def test_success_logs_info_with_check_emoji(self):
        with self._patch_logger():
            self.logger.success("done")
        self.mock_logger.info.assert_called_once()
        msg = self.mock_logger.info.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("[ops]", msg)

    def test_success_with_duration_sets_duration_ms(self):
        with self._patch_logger():
            self.logger.success("done", duration=1.5)
        kwargs = self.mock_logger.info.call_args[1]
        self.assertEqual(kwargs["extra"]["duration_ms"], 1500.0)

    def test_warning_logs_warning_with_emoji(self):
        with self._patch_logger():
            self.logger.warning("careful")
        self.mock_logger.warning.assert_called_once()
        msg = self.mock_logger.warning.call_args[0][0]
        self.assertIn("⚠️", msg)
        self.assertIn("[ops]", msg)

    def test_error_logs_error_with_emoji(self):
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error") as mock_le:
            self.logger.error("bad")
        self.mock_logger.error.assert_called_once()
        msg = self.mock_logger.error.call_args[0][0]
        self.assertIn("❌", msg)
        # No exception passed -> frappe.log_error NOT called
        mock_le.assert_not_called()

    def test_error_with_exception_sets_context_and_calls_log_error(self):
        exc = ValueError("boom")
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error") as mock_le:
            self.logger.error("bad", error=exc)
        kwargs = self.mock_logger.error.call_args[1]
        self.assertEqual(kwargs["extra"]["error_type"], "ValueError")
        self.assertEqual(kwargs["extra"]["error_message"], "boom")
        mock_le.assert_called_once()

    def test_error_data_is_sanitized(self):
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error"):
            self.logger.error("bad", data={"secret": "hideme"})
        kwargs = self.mock_logger.error.call_args[1]
        self.assertEqual(kwargs["extra"]["data"]["secret"], "***REDACTED***")

    def test_performance_fast_logs_info_with_bolt(self):
        with self._patch_logger():
            self.logger.performance("op", duration=0.5)
        self.mock_logger.info.assert_called_once()
        self.mock_logger.warning.assert_not_called()
        msg = self.mock_logger.info.call_args[0][0]
        self.assertIn("⚡", msg)
        kwargs = self.mock_logger.info.call_args[1]
        self.assertEqual(kwargs["extra"]["duration_ms"], 500.0)
        self.assertTrue(kwargs["extra"]["performance_log"])

    def test_performance_slow_logs_warning_with_snail(self):
        with self._patch_logger():
            self.logger.performance("op", duration=3.0)
        self.mock_logger.warning.assert_called_once()
        self.mock_logger.info.assert_not_called()
        msg = self.mock_logger.warning.call_args[0][0]
        self.assertIn("🐌", msg)

    def test_performance_boundary_2s_is_info(self):
        # duration == 2.0 is NOT > 2.0 -> info / ⚡
        with self._patch_logger():
            self.logger.performance("op", duration=2.0)
        self.mock_logger.info.assert_called_once()
        self.assertIn("⚡", self.mock_logger.info.call_args[0][0])


class TestOperationLoggerDecorator(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()

    def _patch_logger(self):
        return patch.object(logging_module.frappe, "logger", return_value=self.mock_logger)

    def test_plain_function_returns_value_and_logs_start_success(self):
        @mollie_operation_logger("plain_op")
        def fn(some_arg):
            return {"status": "ok"}

        with self._patch_logger():
            result = fn("primary")

        self.assertEqual(result, {"status": "ok"})
        # Start (info, 🔵) + success (info, ✅) both go through .info
        self.assertEqual(self.mock_logger.info.call_count, 2)
        start_msg = self.mock_logger.info.call_args_list[0][0][0]
        success_msg = self.mock_logger.info.call_args_list[1][0][0]
        self.assertIn("🔵", start_msg)
        self.assertIn("Starting fn", start_msg)
        self.assertIn("✅", success_msg)
        self.assertIn("Completed fn", success_msg)
        # plain-function branch records args[0] as primary_arg
        start_extra = self.mock_logger.info.call_args_list[0][1]["extra"]
        self.assertEqual(start_extra["data"]["primary_arg"], "primary")
        # success records result status
        success_extra = self.mock_logger.info.call_args_list[1][1]["extra"]
        self.assertEqual(success_extra["data"]["status"], "ok")

    def test_method_call_branch_uses_second_arg_as_primary(self):
        class Holder:
            @mollie_operation_logger("method_op")
            def method(self, ident):
                return {"status": "done"}

        with self._patch_logger():
            result = Holder().method("ID-XYZ")

        self.assertEqual(result, {"status": "done"})
        start_extra = self.mock_logger.info.call_args_list[0][1]["extra"]
        # args[0] is self (has __dict__), args[1] used as primary_arg
        self.assertEqual(start_extra["data"]["primary_arg"], "ID-XYZ")

    def test_raising_function_reraises_and_logs_error(self):
        @mollie_operation_logger("err_op")
        def fn():
            raise RuntimeError("kaboom")

        with self._patch_logger(), patch.object(logging_module.frappe, "log_error") as mock_le:
            with self.assertRaises(RuntimeError):
                fn()

        # start logged via info, failure logged via error
        self.assertTrue(self.mock_logger.info.called)
        self.mock_logger.error.assert_called_once()
        err_msg = self.mock_logger.error.call_args[0][0]
        self.assertIn("❌", err_msg)
        self.assertIn("Failed fn", err_msg)
        mock_le.assert_called_once()


class TestModuleLevelHelpers(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()

    def _patch_logger(self):
        return patch.object(logging_module.frappe, "logger", return_value=self.mock_logger)

    # --- log_mollie_api_call ---

    def test_api_call_2xx_success(self):
        with self._patch_logger():
            log_mollie_api_call("GET", "/payments", 200, 0.1)
        self.mock_logger.info.assert_called_once()
        self.assertIn("✅", self.mock_logger.info.call_args[0][0])

    def test_api_call_4xx_warning(self):
        with self._patch_logger():
            log_mollie_api_call("POST", "/payments", 422, 0.1)
        self.mock_logger.warning.assert_called_once()
        self.assertIn("Client Error", self.mock_logger.warning.call_args[0][0])

    def test_api_call_5xx_error(self):
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error"):
            log_mollie_api_call("POST", "/payments", 503, 0.1)
        self.mock_logger.error.assert_called_once()
        self.assertIn("Server Error", self.mock_logger.error.call_args[0][0])

    def test_api_call_sanitizes_request_and_response_secrets(self):
        with self._patch_logger():
            log_mollie_api_call(
                "POST",
                "/payments",
                200,
                0.1,
                request_data={"api_key": "supersecret", "amount": 5},
                response_data={"token": "respsecret", "id": "tr_aaaaaaaaaaaaaaaa"},
            )
        extra = self.mock_logger.info.call_args[1]["extra"]
        call_data = extra["data"]
        # Secrets redacted, never appear verbatim
        self.assertEqual(call_data["request"]["api_key"], "***REDACTED***")
        self.assertEqual(call_data["response"]["token"], "***REDACTED***")
        self.assertNotIn("supersecret", str(call_data))
        self.assertNotIn("respsecret", str(call_data))
        # id truncated
        self.assertEqual(call_data["response"]["id"], "tr_aaaaaaaaa...")

    # --- log_webhook_received ---

    def test_webhook_received_logs_info(self):
        with self._patch_logger():
            log_webhook_received("tr_123", {"id": "tr_123", "amount": {"value": "10.00"}})
        self.mock_logger.info.assert_called_once()
        msg = self.mock_logger.info.call_args[0][0]
        self.assertIn("🔵", msg)
        self.assertIn("Webhook received", msg)

    # --- log_payment_processing ---

    def test_payment_processing_success(self):
        with self._patch_logger():
            log_payment_processing("tr_1", "create_payment_entry", "success")
        self.mock_logger.info.assert_called_once()
        self.assertIn("✅", self.mock_logger.info.call_args[0][0])

    def test_payment_processing_error(self):
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error"):
            log_payment_processing("tr_1", "create_payment_entry", "error")
        self.mock_logger.error.assert_called_once()
        self.assertIn("❌", self.mock_logger.error.call_args[0][0])

    def test_payment_processing_other_status_info(self):
        with self._patch_logger():
            log_payment_processing("tr_1", "skip_step", "skipped", details={"reason": "dup"})
        self.mock_logger.info.assert_called_once()
        msg = self.mock_logger.info.call_args[0][0]
        self.assertIn("🔵", msg)

    # --- log_integration_health_check ---

    def test_health_check_healthy_success(self):
        with self._patch_logger():
            log_integration_health_check("mollie_api", "healthy")
        self.mock_logger.info.assert_called_once()
        self.assertIn("✅", self.mock_logger.info.call_args[0][0])

    def test_health_check_degraded_warning(self):
        with self._patch_logger():
            log_integration_health_check("mollie_api", "degraded")
        self.mock_logger.warning.assert_called_once()
        self.assertIn("⚠️", self.mock_logger.warning.call_args[0][0])

    def test_health_check_unhealthy_error(self):
        with self._patch_logger(), patch.object(logging_module.frappe, "log_error"):
            log_integration_health_check("mollie_api", "unhealthy")
        self.mock_logger.error.assert_called_once()
        self.assertIn("❌", self.mock_logger.error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
